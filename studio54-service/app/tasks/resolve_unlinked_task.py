"""
Resolve Unlinked Files Task

A Celery task that resolves unlinked library files through six phases:
0. Create missing artists from embedded artistid tags (NEW)
1. Auto-import missing albums (files with valid RG MBIDs where artist exists but album doesn't)
2. Populate missing release group MBIDs via local MusicBrainz DB lookup, then import
   1B. Create missing tracks for existing albums (alternate release recordings)
3. Quality-based duplicate resolution with AcoustID fingerprinting
4. AcoustID fingerprint identification for files with no MBID at all (NEW)
5. Metadata stub creation — zero-unlinked guarantee (NEW)

"Unlinked" means: library_file has a recording MBID but no matching track exists in the
tracks table, OR the track exists but already has a different file linked (duplicate).

Schema note: library_files has NO linked_track_id column. Linking is determined by
checking tracks.musicbrainz_id = library_files.musicbrainz_trackid and tracks.has_file.
"""

import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from celery import shared_task
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.library import LibraryFile
from app.models.album import Album
from app.models.track import Track
from app.models.media_management import MediaManagementConfig
from app.shared_services.job_logger import JobLogger
from app.tasks.organization_tasks import BackgroundHeartbeat

logger = logging.getLogger(__name__)


def _get_recycle_bin_path(db: Session) -> str:
    """Get configured recycle bin path from media management config."""
    config = db.query(MediaManagementConfig).first()
    if config and config.recycle_bin_path:
        return config.recycle_bin_path
    return "/music/.recycle"


def _get_file_organizer(db: Session):
    """Create a FileOrganizer with configured recycle bin."""
    from app.services.file_organizer import FileOrganizer
    recycle_path = _get_recycle_bin_path(db)
    return FileOrganizer(
        music_library_path=Path("/music"),
        recycle_bin_path=Path(recycle_path),
    )


@shared_task(bind=True, soft_time_limit=86400, time_limit=86460)
def resolve_unlinked_files_task(self, job_id: str, library_path_id: str = None):
    """
    Bulk resolution of unlinked files.

    Phase 1: Auto-import missing albums (artist in DB, RG MBID present, album missing)
    Phase 2: Populate missing RG MBIDs from local MB DB, then import those albums
    Phase 3: Quality-based duplicate resolution (file matches track that already has a file)

    Args:
        job_id: FileOrganizationJob ID for tracking
        library_path_id: Optional library path UUID to scope the operation
    """
    db = SessionLocal()
    job_logger = None

    try:
        from app.models.file_organization_job import FileOrganizationJob, JobStatus

        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == job_id
        ).first()
        if not job:
            logger.error(f"Job not found: {job_id}")
            return {"success": False, "error": "Job not found"}

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        job_logger = JobLogger(job_id, job_type="resolve_unlinked")

        # Save log file path to job record
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_job_start("resolve_unlinked", "Resolve Unlinked Files")

        # Build optional path filter
        path_filter = ""
        bulk_params = {}
        if library_path_id:
            path_filter = "AND lf.library_path_id = :lp_id"
            bulk_params["lp_id"] = library_path_id

        stats = {
            "phase0_artists_created": 0,
            "phase0_artists_synced": 0,
            "phase1_albums_imported": 0,
            "phase1_tracks_created": 0,
            "phase1_files_linked": 0,
            "phase1b_tracks_created": 0,
            "phase1b_files_linked": 0,
            "phase2_rg_mbids_found": 0,
            "phase2_albums_imported": 0,
            "phase2_files_linked": 0,
            "phase3_duplicates_checked": 0,
            "phase3_upgrades": 0,
            "phase3_lower_quality_removed": 0,
            "phase3_fingerprint_failures": 0,
            "phase3_not_same_recording": 0,
            "phase4_files_fingerprinted": 0,
            "phase4_recordings_found": 0,
            "phase4_albums_imported": 0,
            "phase4_files_linked": 0,
            "phase4_fingerprint_failures": 0,
            "phase5_files_processed": 0,
            "phase5_mb_matches": 0,
            "phase5_stubs_created": 0,
            "phase5_files_linked": 0,
        }

        # Start background heartbeat to prevent stall detection during long MB API calls
        from app.models.file_organization_job import FileOrganizationJob as HeartbeatModel
        with BackgroundHeartbeat(job_id, HeartbeatModel, interval=30):

            # ═══════════════════════════════════════════════
            # PHASE 0: Create missing artists from embedded MBIDs
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 0: Create Missing Artists",
                                       "Adding artists whose MBID appears in file tags but are not in DB")
            job.current_action = "Phase 0: Creating missing artists..."
            db.commit()

            try:
                stats.update(_phase0_create_missing_artists(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 0 failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 0 failed (non-fatal): {e}")
                db.rollback()

            # ═══════════════════════════════════════════════
            # PHASE 1: Auto-import missing albums
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 1: Auto-Import Albums",
                                       "Importing albums with valid RG MBIDs")
            job.current_action = "Phase 1: Finding missing albums..."
            db.commit()

            try:
                stats.update(_phase1_auto_import(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 1 failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 1 failed (non-fatal): {e}")
                db.rollback()

            # ═══════════════════════════════════════════════
            # PHASE 1B: Create missing tracks for existing albums
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 1B: Create Missing Tracks",
                                       "Adding tracks from alternate releases to existing albums")
            job.current_action = "Phase 1B: Creating missing tracks for existing albums..."
            db.commit()

            try:
                stats.update(_phase1b_create_missing_tracks(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 1B failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 1B failed (non-fatal): {e}")
                db.rollback()

            # ═══════════════════════════════════════════════
            # PHASE 2: Populate missing RG MBIDs
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 2: Populate RG MBIDs",
                                       "Looking up release groups for files with recording MBIDs")
            job.current_action = "Phase 2: Looking up release group MBIDs..."
            db.commit()

            try:
                stats.update(_phase2_populate_rg_mbids(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 2 failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 2 failed (non-fatal): {e}")
                db.rollback()

            # ═══════════════════════════════════════════════
            # PHASE 3: Quality-based duplicate resolution
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 3: Duplicate Resolution",
                                       "Fingerprinting and comparing quality of duplicate files")
            job.current_action = "Phase 3: Resolving duplicates..."
            db.commit()

            try:
                stats.update(_phase3_duplicate_resolution(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 3 failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 3 failed (non-fatal): {e}")
                db.rollback()

            # ═══════════════════════════════════════════════
            # PHASE 4: AcoustID fingerprint identification
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 4: Fingerprint Identification",
                                       "Fingerprinting files with no MBID to identify recordings")
            job.current_action = "Phase 4: Fingerprinting unidentified files..."
            db.commit()

            try:
                stats.update(_phase4_fingerprint_identification(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 4 failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 4 failed (non-fatal): {e}")
                db.rollback()

            # ═══════════════════════════════════════════════
            # PHASE 5: Metadata stub creation
            # ═══════════════════════════════════════════════
            job_logger.log_phase_start("Phase 5: Metadata Stub Creation",
                                       "Creating stub records for remaining unlinked files")
            job.current_action = "Phase 5: Creating metadata stubs..."
            db.commit()

            try:
                stats.update(_phase5_metadata_stub_creation(db, job, job_logger, path_filter, bulk_params))
            except Exception as e:
                logger.error(f"Phase 5 failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Phase 5 failed (non-fatal): {e}")
                db.rollback()

        # ═══════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════
        job_logger.log_info("=" * 60)
        job_logger.log_info("RESOLVE UNLINKED FILES — FINAL SUMMARY")
        job_logger.log_info("=" * 60)
        job_logger.log_info(f"Phase 0  — Artists created: {stats['phase0_artists_created']}")
        job_logger.log_info(f"Phase 0  — Artists synced: {stats['phase0_artists_synced']}")
        job_logger.log_info(f"Phase 1  — Albums imported: {stats['phase1_albums_imported']}")
        job_logger.log_info(f"Phase 1  — Tracks created: {stats['phase1_tracks_created']}")
        job_logger.log_info(f"Phase 1  — Files linked: {stats['phase1_files_linked']}")
        job_logger.log_info(f"Phase 1B — Tracks created (alt releases): {stats['phase1b_tracks_created']}")
        job_logger.log_info(f"Phase 1B — Files linked: {stats['phase1b_files_linked']}")
        job_logger.log_info(f"Phase 2  — RG MBIDs found: {stats['phase2_rg_mbids_found']}")
        job_logger.log_info(f"Phase 2  — Albums imported: {stats['phase2_albums_imported']}")
        job_logger.log_info(f"Phase 2  — Files linked: {stats['phase2_files_linked']}")
        job_logger.log_info(f"Phase 3  — Duplicates checked: {stats['phase3_duplicates_checked']}")
        job_logger.log_info(f"Phase 3  — Upgrades (kept better file): {stats['phase3_upgrades']}")
        job_logger.log_info(f"Phase 3  — Lower quality removed: {stats['phase3_lower_quality_removed']}")
        job_logger.log_info(f"Phase 3  — Not same recording: {stats['phase3_not_same_recording']}")
        job_logger.log_info(f"Phase 3  — Fingerprint failures: {stats['phase3_fingerprint_failures']}")
        job_logger.log_info(f"Phase 4  — Files fingerprinted: {stats['phase4_files_fingerprinted']}")
        job_logger.log_info(f"Phase 4  — Recordings identified: {stats['phase4_recordings_found']}")
        job_logger.log_info(f"Phase 4  — Albums imported: {stats['phase4_albums_imported']}")
        job_logger.log_info(f"Phase 4  — Files linked: {stats['phase4_files_linked']}")
        job_logger.log_info(f"Phase 4  — Fingerprint failures: {stats['phase4_fingerprint_failures']}")
        job_logger.log_info(f"Phase 5  — Files processed: {stats['phase5_files_processed']}")
        job_logger.log_info(f"Phase 5  — MB search matches: {stats['phase5_mb_matches']}")
        job_logger.log_info(f"Phase 5  — Stubs created: {stats['phase5_stubs_created']}")
        job_logger.log_info(f"Phase 5  — Files linked: {stats['phase5_files_linked']}")
        total_linked = (stats['phase1_files_linked'] + stats['phase1b_files_linked'] +
                        stats['phase2_files_linked'] + stats['phase3_upgrades'] +
                        stats['phase4_files_linked'] + stats['phase5_files_linked'])
        job_logger.log_info(f"TOTAL FILES RESOLVED: {total_linked}")
        job_logger.log_info("=" * 60)

        # Mark job complete
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Complete — {total_linked} files resolved"
        job.progress_percent = 100.0
        db.commit()

        return {"success": True, "stats": stats}

    except Exception as e:
        logger.error(f"resolve_unlinked_files_task failed: {e}\n{traceback.format_exc()}")
        try:
            from app.models.file_organization_job import FileOrganizationJob, JobStatus
            job = db.query(FileOrganizationJob).filter(
                FileOrganizationJob.id == job_id
            ).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)[:500]
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def _phase1_auto_import(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 1: Import missing albums where artist exists and RG MBID is valid.

    Finds files where:
    - Has a recording MBID that does NOT match any track in the DB
    - Has a release group MBID
    - Artist exists in DB
    - Album does NOT exist in DB

    Then imports those albums and re-links files.
    """
    from app.services.album_importer import bulk_import_release_groups
    from app.services.musicbrainz_client import get_musicbrainz_client

    stats = {
        "phase1_albums_imported": 0,
        "phase1_tracks_created": 0,
        "phase1_files_linked": 0,
    }

    # Find (artist_id, rg_mbid) pairs for files where:
    # - recording MBID has no matching track
    # - artist is in DB (matched by MBID, or by name when artistid tag is absent)
    # - album is NOT in DB
    sql = text(f"""
        SELECT DISTINCT lf.musicbrainz_releasegroupid AS rg_mbid, a.id AS artist_id
        FROM library_files lf
        JOIN artists a ON (
            (lf.musicbrainz_artistid IS NOT NULL AND lf.musicbrainz_artistid != ''
             AND a.musicbrainz_id = lf.musicbrainz_artistid)
            OR
            ((lf.musicbrainz_artistid IS NULL OR lf.musicbrainz_artistid = '')
             AND LOWER(TRIM(a.name)) = LOWER(TRIM(lf.artist)))
        )
        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
        LEFT JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid
        WHERE lf.musicbrainz_trackid IS NOT NULL
          AND t.id IS NULL
          AND lf.musicbrainz_releasegroupid IS NOT NULL
          AND lf.musicbrainz_releasegroupid != ''
          AND al.id IS NULL
          {path_filter}
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 1: No missing albums found to import")
        return stats

    job_logger.log_info(f"Phase 1: Found {len(rows)} missing release groups to import")
    mb_client = get_musicbrainz_client()
    artist_rg_pairs = [(row.artist_id, row.rg_mbid) for row in rows]

    def progress_cb(imported, total, title):
        job.current_action = f"Phase 1: Importing album {imported}/{total} — {title}"
        try:
            job.progress_percent = 10 + (imported / total) * 10  # Phase 1 = 10-20%
            db.commit()
        except Exception:
            pass

    import_stats = bulk_import_release_groups(db, artist_rg_pairs, mb_client, progress_cb)

    stats["phase1_albums_imported"] = import_stats["albums_imported"]
    stats["phase1_tracks_created"] = import_stats["tracks_created"]

    job_logger.log_info(f"Phase 1: Imported {import_stats['albums_imported']} albums, "
                        f"{import_stats['tracks_created']} tracks, "
                        f"skipped {import_stats['skipped']}, failed {import_stats['failed']}")

    # Re-link files: update tracks that now match library files via recording MBID
    if import_stats["albums_imported"] > 0:
        relink_sql = text(f"""
            UPDATE tracks t
            SET file_path = lf.file_path, has_file = true
            FROM library_files lf
            WHERE t.musicbrainz_id = lf.musicbrainz_trackid
              AND lf.musicbrainz_trackid IS NOT NULL
              AND t.has_file = false
              {path_filter}
        """)
        result = db.execute(relink_sql, bulk_params)
        linked = result.rowcount
        db.commit()

        stats["phase1_files_linked"] = linked
        job_logger.log_info(f"Phase 1: Linked {linked} files after album import")
        _mark_resolved_files(db, job_logger)

    job_logger.log_phase_complete("Phase 1", count=stats["phase1_albums_imported"])
    return stats


def _phase1b_create_missing_tracks(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 1B: Create tracks for files where the album exists but the file's recording
    MBID isn't in the tracks table.

    This happens when MusicBrainz has multiple releases of the same release group
    (e.g. original vs remaster vs deluxe) with different recording MBIDs. The album
    importer picks one release, so files tagged from alternate releases have recording
    MBIDs that don't match any imported track.

    Solution: Create a new Track record under the existing album using the file's
    metadata and recording MBID, then link the file to it.
    """
    import uuid as uuid_mod

    stats = {
        "phase1b_tracks_created": 0,
        "phase1b_files_linked": 0,
    }

    # Find files where:
    # - Has recording MBID with no matching track
    # - Has RG MBID matching an existing album
    # - Artist is in DB
    sql = text(f"""
        SELECT
            lf.id AS file_id,
            lf.file_path,
            lf.title AS file_title,
            lf.track_number,
            lf.disc_number,
            lf.musicbrainz_trackid AS recording_mbid,
            lf.musicbrainz_releasegroupid AS rg_mbid,
            al.id AS album_id,
            al.title AS album_title
        FROM library_files lf
        JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
        JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid
        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
        WHERE lf.musicbrainz_trackid IS NOT NULL
          AND lf.musicbrainz_trackid != ''
          AND t.id IS NULL
          AND lf.musicbrainz_releasegroupid IS NOT NULL
          AND lf.musicbrainz_releasegroupid != ''
          {path_filter}
        ORDER BY al.id, lf.disc_number, lf.track_number
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 1B: No files with existing albums need track creation")
        return stats

    job_logger.log_info(f"Phase 1B: Found {len(rows)} files with existing albums but missing tracks")

    # Track which recording MBIDs we've already created to avoid duplicates
    # (multiple files could have the same recording MBID)
    created_recording_mbids = set()
    total = len(rows)

    for i, row in enumerate(rows):
        if i % 500 == 0 and i > 0:
            job.current_action = f"Phase 1B: Creating tracks {i}/{total}"
            job.progress_percent = 20 + (i / total) * 15  # Phase 1B = 20-35%
            try:
                db.commit()
            except Exception:
                pass

        recording_mbid = row.recording_mbid

        # Skip if we already created a track for this recording MBID in this run
        if recording_mbid in created_recording_mbids:
            continue

        # Double-check the track doesn't exist (could have been created by Phase 1)
        existing = db.query(Track).filter(
            Track.musicbrainz_id == recording_mbid
        ).first()
        if existing:
            # Track exists now — just link the file if it's not already linked
            if not existing.has_file:
                existing.file_path = row.file_path
                existing.has_file = True
                stats["phase1b_files_linked"] += 1
            created_recording_mbids.add(recording_mbid)
            continue

        # Create the track under the existing album
        track = Track(
            id=uuid_mod.uuid4(),
            album_id=row.album_id,
            title=row.file_title or "Unknown Track",
            musicbrainz_id=recording_mbid,
            track_number=row.track_number,
            disc_number=row.disc_number or 1,
            duration_ms=None,
            has_file=True,
            file_path=row.file_path,
        )
        db.add(track)
        created_recording_mbids.add(recording_mbid)
        stats["phase1b_tracks_created"] += 1
        stats["phase1b_files_linked"] += 1

        if stats["phase1b_tracks_created"] % 200 == 0:
            db.flush()

    db.commit()
    _mark_resolved_files(db, job_logger)

    job_logger.log_info(
        f"Phase 1B: Created {stats['phase1b_tracks_created']} tracks, "
        f"linked {stats['phase1b_files_linked']} files"
    )
    job_logger.log_phase_complete("Phase 1B", count=stats["phase1b_tracks_created"])
    return stats


def _phase2_populate_rg_mbids(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 2: For files with recording MBIDs but no release group MBID,
    look up the recording in the local MusicBrainz DB to find the release group.
    Then import those albums and re-link.
    """
    from app.services.musicbrainz_client import get_musicbrainz_client

    stats = {
        "phase2_rg_mbids_found": 0,
        "phase2_albums_imported": 0,
        "phase2_files_linked": 0,
    }

    # Find files with recording MBID but no RG MBID, where artist is in DB
    # (matched by MBID, or by name when artistid tag is absent), and no matching track exists
    sql = text(f"""
        SELECT DISTINCT lf.musicbrainz_trackid AS recording_mbid, lf.id AS file_id,
               a.id AS artist_id, a.musicbrainz_id AS artist_mbid
        FROM library_files lf
        JOIN artists a ON (
            (lf.musicbrainz_artistid IS NOT NULL AND lf.musicbrainz_artistid != ''
             AND a.musicbrainz_id = lf.musicbrainz_artistid)
            OR
            ((lf.musicbrainz_artistid IS NULL OR lf.musicbrainz_artistid = '')
             AND LOWER(TRIM(a.name)) = LOWER(TRIM(lf.artist)))
        )
        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
        WHERE t.id IS NULL
          AND lf.musicbrainz_trackid IS NOT NULL
          AND (lf.musicbrainz_releasegroupid IS NULL OR lf.musicbrainz_releasegroupid = '')
          {path_filter}
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 2: No files need RG MBID lookup")
        return stats

    job_logger.log_info(f"Phase 2: Found {len(rows)} files needing RG MBID lookup")

    # Try local MB database first
    mb_client = get_musicbrainz_client()
    local_db = getattr(mb_client, 'local_db', None)

    # Collect unique recording MBIDs
    recording_to_artists = {}  # recording_mbid -> artist_id
    for row in rows:
        if row.recording_mbid not in recording_to_artists:
            recording_to_artists[row.recording_mbid] = row.artist_id

    rg_mbids_found = {}  # recording_mbid -> rg_mbid
    total_recordings = len(recording_to_artists)
    processed = 0

    for recording_mbid, artist_id in recording_to_artists.items():
        processed += 1
        if processed % 100 == 0:
            job.current_action = f"Phase 2: Looking up RG MBIDs {processed}/{total_recordings}"
            job.progress_percent = 35 + (processed / total_recordings) * 25  # Phase 2 = 35-60%
            try:
                db.commit()
            except Exception:
                pass

        rg_mbid = None

        # Try local DB first (fast, no rate limit)
        if local_db:
            try:
                releases = local_db._get_recording_releases(recording_mbid)
                for rel in releases:
                    rg = rel.get("release-group", {})
                    if rg.get("id"):
                        rg_mbid = rg["id"]
                        break
            except Exception:
                pass

        # Fallback to remote MB API if local didn't work
        if not rg_mbid:
            try:
                recording_data = mb_client.get_recording(
                    recording_mbid, includes=["releases", "release-groups"]
                )
                if recording_data:
                    releases = recording_data.get("releases", [])
                    for rel in releases:
                        rg = rel.get("release-group", {})
                        if rg.get("id"):
                            rg_mbid = rg["id"]
                            break
            except Exception:
                pass

        if rg_mbid:
            rg_mbids_found[recording_mbid] = rg_mbid

    stats["phase2_rg_mbids_found"] = len(rg_mbids_found)
    job_logger.log_info(f"Phase 2: Found {len(rg_mbids_found)} RG MBIDs out of {total_recordings} recordings")

    # Update library_files with found RG MBIDs
    if rg_mbids_found:
        for rec_mbid, rg_mbid in rg_mbids_found.items():
            db.execute(
                text("""
                    UPDATE library_files
                    SET musicbrainz_releasegroupid = :rg_mbid
                    WHERE musicbrainz_trackid = :rec_mbid
                      AND (musicbrainz_releasegroupid IS NULL OR musicbrainz_releasegroupid = '')
                """),
                {"rg_mbid": rg_mbid, "rec_mbid": rec_mbid}
            )
        db.commit()
        job_logger.log_info(f"Phase 2: Updated {len(rg_mbids_found)} files with RG MBIDs")

    # Now import missing albums (same as phase 1 but for newly-tagged files)
    import_sql = text(f"""
        SELECT DISTINCT lf.musicbrainz_releasegroupid AS rg_mbid, a.id AS artist_id
        FROM library_files lf
        JOIN artists a ON (
            (lf.musicbrainz_artistid IS NOT NULL AND lf.musicbrainz_artistid != ''
             AND a.musicbrainz_id = lf.musicbrainz_artistid)
            OR
            ((lf.musicbrainz_artistid IS NULL OR lf.musicbrainz_artistid = '')
             AND LOWER(TRIM(a.name)) = LOWER(TRIM(lf.artist)))
        )
        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
        LEFT JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid
        WHERE lf.musicbrainz_trackid IS NOT NULL
          AND t.id IS NULL
          AND lf.musicbrainz_releasegroupid IS NOT NULL
          AND lf.musicbrainz_releasegroupid != ''
          AND al.id IS NULL
          {path_filter}
    """)
    missing_rows = db.execute(import_sql, bulk_params).fetchall()

    if missing_rows:
        from app.services.album_importer import bulk_import_release_groups

        job_logger.log_info(f"Phase 2: Importing {len(missing_rows)} newly-identified albums")
        artist_rg_pairs = [(row.artist_id, row.rg_mbid) for row in missing_rows]

        def progress_cb(imported, total, title):
            job.current_action = f"Phase 2: Importing album {imported}/{total} — {title}"
            try:
                db.commit()
            except Exception:
                pass

        import_stats = bulk_import_release_groups(db, artist_rg_pairs, mb_client, progress_cb)
        stats["phase2_albums_imported"] = import_stats["albums_imported"]
        job_logger.log_info(f"Phase 2: Imported {import_stats['albums_imported']} albums")

    # Re-link all unlinked files (those with recording MBID matching a track that has no file)
    relink_sql = text(f"""
        UPDATE tracks t
        SET file_path = lf.file_path, has_file = true
        FROM library_files lf
        WHERE t.musicbrainz_id = lf.musicbrainz_trackid
          AND lf.musicbrainz_trackid IS NOT NULL
          AND t.has_file = false
          {path_filter}
    """)
    result = db.execute(relink_sql, bulk_params)
    linked = result.rowcount
    db.commit()

    stats["phase2_files_linked"] = linked
    job_logger.log_info(f"Phase 2: Linked {linked} files after RG lookup + album import")
    _mark_resolved_files(db, job_logger)
    job_logger.log_phase_complete("Phase 2", count=stats["phase2_rg_mbids_found"])
    return stats


def _phase3_duplicate_resolution(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 3: For files where a matching track exists but already has a file linked,
    use AcoustID to confirm they're the same recording, then compare quality and
    keep the better file. The worse file is moved to the recycle bin.

    Quality ranking: FLAC > WAV > ALAC > 320mp3 > 256+ > rest
    - If new file is better: update track file_path, move old to recycle bin
    - If new file is worse: move the new file to recycle bin
    """
    from app.services.acoustid_service import get_acoustid_service, compare_quality

    stats = {
        "phase3_duplicates_checked": 0,
        "phase3_upgrades": 0,
        "phase3_lower_quality_removed": 0,
        "phase3_fingerprint_failures": 0,
        "phase3_not_same_recording": 0,
    }

    acoustid = get_acoustid_service()
    file_organizer = _get_file_organizer(db)

    # Find files where:
    # - The file's recording MBID matches a track in the DB
    # - That track already has a file (has_file=true)
    # - The file path on the track is different from this library file
    sql = text(f"""
        SELECT
            lf.id AS file_id,
            lf.file_path,
            lf.format,
            lf.bitrate_kbps,
            lf.sample_rate_hz,
            lf.title AS file_title,
            lf.musicbrainz_trackid AS file_recording_mbid,
            t.id AS track_id,
            t.title AS track_title,
            t.file_path AS track_file_path,
            t.musicbrainz_id AS track_recording_mbid,
            al.title AS album_title
        FROM library_files lf
        JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
        JOIN albums al ON al.id = t.album_id
        WHERE lf.musicbrainz_trackid IS NOT NULL
          AND t.has_file = true
          AND t.file_path IS NOT NULL
          AND t.file_path != lf.file_path
          {path_filter}
        ORDER BY al.id, t.track_number
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 3: No duplicate candidates found")
        return stats

    # Group by file_id to avoid processing the same file multiple times
    # For each unlinked file, find the best matching track
    from difflib import SequenceMatcher
    file_candidates = {}  # file_id -> best (row, similarity)

    for row in rows:
        file_id = str(row.file_id)
        file_title = (row.file_title or "").lower().strip()
        track_title = (row.track_title or "").lower().strip()

        # If recording MBIDs match exactly, that's a strong signal — always a candidate
        if row.file_recording_mbid and row.track_recording_mbid and \
           row.file_recording_mbid == row.track_recording_mbid:
            sim = 1.0
        elif file_title and track_title:
            sim = SequenceMatcher(None, file_title, track_title).ratio()
        else:
            continue

        if sim >= 0.75:
            existing = file_candidates.get(file_id)
            if not existing or sim > existing[1]:
                file_candidates[file_id] = (row, sim)

    job_logger.log_info(f"Phase 3: {len(file_candidates)} candidate duplicates to check")

    total = len(file_candidates)
    checked = 0

    for file_id, (row, sim) in file_candidates.items():
        checked += 1
        if checked % 10 == 0:
            job.current_action = f"Phase 3: Fingerprinting {checked}/{total}"
            job.progress_percent = 60 + (checked / total) * 20  # Phase 3 = 60-80%
            try:
                db.commit()
            except Exception:
                pass

        stats["phase3_duplicates_checked"] += 1

        new_file = row.file_path
        existing_file = row.track_file_path

        # Verify both files exist on disk
        if not Path(new_file).exists():
            continue
        if not Path(existing_file).exists():
            # Existing file is gone — just update the track to use the new file
            track = db.query(Track).filter(Track.id == row.track_id).first()
            if track:
                track.file_path = new_file
                track.has_file = True
                db.commit()
                stats["phase3_upgrades"] += 1
                job_logger.log_info(
                    f"  Linked (existing file missing): {row.track_title} -> {new_file}"
                )
            continue

        # AcoustID fingerprint comparison
        is_same, confidence = acoustid.are_same_recording(new_file, existing_file)

        if not is_same:
            if confidence == 0.0:
                stats["phase3_fingerprint_failures"] += 1
            else:
                stats["phase3_not_same_recording"] += 1
            continue

        # Same recording confirmed — compare quality
        existing_lf = db.query(LibraryFile).filter(
            LibraryFile.file_path == existing_file
        ).first()

        existing_fmt = existing_lf.format if existing_lf else _guess_format(existing_file)
        existing_br = existing_lf.bitrate_kbps if existing_lf else None
        existing_sr = existing_lf.sample_rate_hz if existing_lf else None

        new_fmt = row.format
        new_br = row.bitrate_kbps
        new_sr = row.sample_rate_hz

        quality_diff = compare_quality(
            new_fmt, new_br, new_sr,
            existing_fmt, existing_br, existing_sr,
        )

        track = db.query(Track).filter(Track.id == row.track_id).first()

        if quality_diff > 0:
            # New file is better — upgrade
            job_logger.log_info(
                f"  UPGRADE: {row.track_title} | "
                f"{existing_fmt}/{existing_br}kbps -> {new_fmt}/{new_br}kbps "
                f"(AcoustID: {confidence:.2f})"
            )

            # Move old file to recycle bin
            file_organizer.delete_file(
                Path(existing_file), use_recycle_bin=True, subfolder="duplicates"
            )

            # Update track to point to new file
            if track:
                track.file_path = new_file
                track.has_file = True

            db.commit()
            stats["phase3_upgrades"] += 1

        else:
            # New file is same or worse quality — remove it
            job_logger.log_info(
                f"  SKIP (lower quality): {row.track_title} | "
                f"keeping {existing_fmt}/{existing_br}kbps, "
                f"removing {new_fmt}/{new_br}kbps"
            )

            # Move lower quality file to recycle bin
            file_organizer.delete_file(
                Path(new_file), use_recycle_bin=True, subfolder="duplicates"
            )

            db.commit()
            stats["phase3_lower_quality_removed"] += 1

    _mark_resolved_files(db, job_logger)
    job_logger.log_phase_complete("Phase 3", count=stats["phase3_upgrades"])
    return stats


def _guess_format(file_path: str) -> str:
    """Guess audio format from file extension."""
    ext = Path(file_path).suffix.lower().lstrip(".")
    fmt_map = {
        "flac": "FLAC",
        "wav": "WAV",
        "m4a": "M4A",
        "mp3": "MP3",
        "ogg": "OGG",
        "wma": "WMA",
        "alac": "ALAC",
        "aac": "M4A",
    }
    return fmt_map.get(ext, ext.upper())


def _mark_resolved_files(db, job_logger) -> int:
    """
    Bulk-mark unlinked_files rows as resolved where the file now has a linked track.

    Called after each phase's relinking step so the unlinked_files table stays
    accurate and the UI count drops in real time.
    Returns the number of rows updated.
    """
    result = db.execute(text("""
        UPDATE unlinked_files uf
        SET resolved_at = NOW()
        FROM library_files lf
        JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                      AND t.has_file = true
        WHERE uf.library_file_id = lf.id
          AND uf.resolved_at IS NULL
          AND t.file_path = lf.file_path
    """))
    count = result.rowcount
    db.commit()
    if count:
        job_logger.log_info(f"  Marked {count} unlinked_files rows as resolved")
    return count


def _score_rg_secondary_types(rg_data: dict) -> int:
    """
    Score a release-group dict by secondary types.
    Used in Phase 4/5 when selecting the best RG from AcoustID/MB results.
    Returns negative scores for undesirable types; 0 for clean studio albums.

    Handles both AcoustID key ('secondarytypes') and MB API key ('secondary-types').
    """
    secondary = (
        [st.lower() for st in (rg_data.get("secondarytypes") or [])]
        or [st.lower() for st in (rg_data.get("secondary-types") or [])]
    )
    PENALTIES = {
        "remix":          -300,
        "compilation":    -200,
        "live":           -150,
        "mixtape/street": -300,
        "dj-mix":         -300,
        "demo":           -100,
        "interview":      -100,
        "spokenword":     -100,
    }
    return sum(PENALTIES.get(st, 0) for st in secondary)


def _phase0_create_missing_artists(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 0: Create Artist records for files that have a musicbrainz_artistid embedded
    in their tags but whose artist is not yet in the DB.

    After creating each artist, syncs their albums inline so Phase 1 can pick up
    their albums and link files in the same run.
    """
    from app.models.artist import Artist
    from app.services.artist_import_service import ArtistImportService
    from app.services.musicbrainz_client import get_musicbrainz_client
    from app.tasks.sync_tasks import sync_artist_albums_standalone

    stats = {
        "phase0_artists_created": 0,
        "phase0_artists_synced": 0,
    }

    sql = text(f"""
        SELECT DISTINCT lf.musicbrainz_artistid AS artist_mbid,
               lf.artist AS artist_name
        FROM library_files lf
        LEFT JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
        WHERE lf.musicbrainz_artistid IS NOT NULL
          AND lf.musicbrainz_artistid != ''
          AND a.id IS NULL
          {path_filter}
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 0: No missing artists to create")
        return stats

    job_logger.log_info(f"Phase 0: Found {len(rows)} missing artists to create")

    import_service = ArtistImportService(db)
    mb_client = get_musicbrainz_client()
    total = len(rows)

    for i, row in enumerate(rows):
        artist_mbid = row.artist_mbid
        artist_name = (row.artist_name or "").strip() or "Unknown Artist"

        if i % 5 == 0:
            job.current_action = f"Phase 0: Creating artists {i}/{total}"
            job.progress_percent = (i / total) * 10  # Phase 0 = 0-10%
            try:
                db.commit()
            except Exception:
                pass

        try:
            # Race-condition guard: another process may have created it already
            existing = db.query(Artist).filter(Artist.musicbrainz_id == artist_mbid).first()
            if existing:
                continue

            # Fetch canonical name from MB API; fall back to tag name on failure
            try:
                mb_artist = mb_client.get_artist(artist_mbid)
                if mb_artist and mb_artist.get("name"):
                    artist_name = mb_artist["name"]
            except Exception as e:
                job_logger.log_info(
                    f"  Phase 0: MB lookup failed for {artist_mbid} — using tag name '{artist_name}': {e}"
                )

            artist = import_service.create_artist_from_musicbrainz(artist_mbid, artist_name)
            if not artist:
                job_logger.log_info(f"  Phase 0: Could not create artist {artist_mbid}")
                continue

            db.commit()
            stats["phase0_artists_created"] += 1
            job_logger.log_info(f"  Phase 0: Created artist '{artist.name}' ({artist_mbid})")

            # Sync albums + tracks so Phase 1 can match files immediately
            try:
                sync_artist_albums_standalone(db, str(artist.id))
                db.commit()
                stats["phase0_artists_synced"] += 1
                job_logger.log_info(f"  Phase 0: Synced albums for '{artist.name}'")
            except Exception as e:
                logger.warning(f"Phase 0: Album sync failed for {artist.name}: {e}")
                job_logger.log_info(f"  Phase 0: Album sync failed for '{artist.name}': {e}")
                db.rollback()

        except Exception as e:
            logger.error(f"Phase 0: Failed to create artist {artist_mbid}: {e}")
            job_logger.log_error(f"Phase 0: Failed for {artist_mbid}: {e}")
            db.rollback()

    job_logger.log_info(
        f"Phase 0: Created {stats['phase0_artists_created']} artists, "
        f"synced {stats['phase0_artists_synced']} catalogs"
    )
    job_logger.log_phase_complete("Phase 0", count=stats["phase0_artists_created"])
    return stats


def _phase4_fingerprint_identification(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 4: For files with NO recording MBID that still have no linked track,
    fingerprint via AcoustID to identify the recording and link it.

    On success, writes the discovered MBIDs back to library_files so future
    runs skip re-fingerprinting.
    """
    import uuid as uuid_mod
    from app.models.artist import Artist
    from app.models.album import Album
    from app.models.track import Track
    from app.services.acoustid_service import get_acoustid_service
    from app.services.musicbrainz_client import get_musicbrainz_client
    from app.services.album_importer import import_release_group
    from app.services.artist_import_service import ArtistImportService

    ACOUSTID_MIN_SCORE = 0.75

    stats = {
        "phase4_files_fingerprinted": 0,
        "phase4_recordings_found": 0,
        "phase4_albums_imported": 0,
        "phase4_files_linked": 0,
        "phase4_fingerprint_failures": 0,
    }

    acoustid = get_acoustid_service()
    mb_client = get_musicbrainz_client()
    import_service = ArtistImportService(db)

    sql = text(f"""
        SELECT
            lf.id AS file_id,
            lf.file_path,
            lf.artist,
            lf.album,
            lf.title,
            lf.musicbrainz_artistid AS artist_mbid
        FROM library_files lf
        JOIN library_paths lp ON lp.id = lf.library_path_id
        WHERE (lf.musicbrainz_trackid IS NULL OR lf.musicbrainz_trackid = '')
          AND lp.library_type != 'audiobook'
          AND NOT EXISTS (
              SELECT 1 FROM tracks t
              WHERE t.file_path = lf.file_path AND t.has_file = true
          )
          {path_filter}
        ORDER BY lf.artist, lf.album, lf.track_number
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 4: No music files without recording MBID to fingerprint")
        return stats

    job_logger.log_info(f"Phase 4: Found {len(rows)} files to fingerprint")
    total = len(rows)

    for i, row in enumerate(rows):
        if i % 5 == 0:
            job.current_action = f"Phase 4: Fingerprinting {i}/{total} — {row.artist or 'Unknown'}"
            job.progress_percent = 80 + (i / total) * 15  # Phase 4 = 80-95%
            try:
                db.commit()
            except Exception:
                pass

        if not Path(row.file_path).exists():
            continue

        # Fingerprint the file
        fp_result = acoustid.fingerprint_file(row.file_path)
        if not fp_result:
            stats["phase4_fingerprint_failures"] += 1
            continue

        fingerprint, duration = fp_result
        stats["phase4_files_fingerprinted"] += 1

        # AcoustID lookup — results sorted by score desc
        acoustid_results = acoustid.lookup(fingerprint, duration)
        if not acoustid_results:
            continue

        # Find best (recording_mbid, rg_mbid) — highest AcoustID score, then
        # prefer original studio albums (no secondary types) over live/remix/compilations
        best_recording_mbid = None
        best_rg_mbid = None
        best_combined = -99999.0

        for result in acoustid_results:
            score = result.get("score", 0.0)
            if score < ACOUSTID_MIN_SCORE:
                break  # sorted descending — no point continuing

            for recording in result.get("recordings", []):
                rec_mbid = recording.get("id")
                if not rec_mbid:
                    continue

                for rg in recording.get("releasegroups", []):
                    rg_mbid = rg.get("id")
                    if not rg_mbid:
                        continue

                    rg_type_score = _score_rg_secondary_types(rg)

                    # Tiebreaker: prefer earliest release date
                    releases = rg.get("releases") or []
                    year = 9999
                    for rel in releases:
                        date_str = rel.get("date", "")
                        try:
                            y = int(date_str[:4])
                            if y < year:
                                year = y
                        except (ValueError, IndexError):
                            pass

                    combined = score * 100 + rg_type_score - (year / 100.0)
                    if combined > best_combined:
                        best_combined = combined
                        best_recording_mbid = rec_mbid
                        best_rg_mbid = rg_mbid

        if not best_recording_mbid or not best_rg_mbid:
            continue

        stats["phase4_recordings_found"] += 1

        # Write discovered MBIDs back to library_files (avoids re-fingerprinting)
        db.execute(
            text("""
                UPDATE library_files
                SET musicbrainz_trackid = :rec_mbid,
                    musicbrainz_releasegroupid = :rg_mbid
                WHERE id = :file_id
            """),
            {"rec_mbid": best_recording_mbid, "rg_mbid": best_rg_mbid,
             "file_id": str(row.file_id)}
        )

        # Resolve artist
        artist_id = None
        artist_mbid = row.artist_mbid

        if not artist_mbid:
            # Look up artist from the recording
            try:
                rec_data = mb_client.get_recording(best_recording_mbid, includes=["artists"])
                if rec_data:
                    for credit in (rec_data.get("artist-credit") or []):
                        if isinstance(credit, dict):
                            mb_artist_mbid = (credit.get("artist") or {}).get("id")
                            if mb_artist_mbid:
                                artist_mbid = mb_artist_mbid
                                break
            except Exception as e:
                job_logger.log_info(f"  Phase 4: Could not fetch artist for {best_recording_mbid}: {e}")

        if artist_mbid:
            db_artist = db.query(Artist).filter(Artist.musicbrainz_id == artist_mbid).first()
            if db_artist:
                artist_id = db_artist.id
            else:
                try:
                    mb_artist_data = mb_client.get_artist(artist_mbid)
                    a_name = (mb_artist_data or {}).get("name") or row.artist or "Unknown Artist"
                    from app.services.artist_import_service import ArtistImportService as AIS
                    new_artist = AIS(db).create_artist_from_musicbrainz(artist_mbid, a_name)
                    if new_artist:
                        db.flush()
                        artist_id = new_artist.id
                except Exception as e:
                    job_logger.log_info(f"  Phase 4: Could not create artist {artist_mbid}: {e}")

        if not artist_id:
            db.commit()  # still commit the MBID back-write
            continue

        # Import release group if not already present
        existing_album = db.query(Album).filter(Album.musicbrainz_id == best_rg_mbid).first()
        if not existing_album:
            try:
                album = import_release_group(db, artist_id, best_rg_mbid, mb_client)
                if album:
                    db.commit()
                    stats["phase4_albums_imported"] += 1
                    job_logger.log_info(f"  Phase 4: Imported album '{album.title}'")
            except Exception as e:
                job_logger.log_error(f"  Phase 4: Album import failed for {best_rg_mbid}: {e}")
                db.rollback()
                continue

        # Link file to track
        track = db.query(Track).filter(Track.musicbrainz_id == best_recording_mbid).first()
        if track and not track.has_file:
            track.file_path = row.file_path
            track.has_file = True
            db.commit()
            stats["phase4_files_linked"] += 1
            job_logger.log_info(
                f"  Phase 4: Linked '{row.title or row.file_path}' -> '{track.title}'"
            )
        else:
            db.commit()

    # Post-loop sweep: pick up any files whose MBID was written back to library_files
    # by this run (or a prior run) but whose track row still has has_file = false.
    # This also covers the ~186 pre-existing "MBID set, track not linked" cases.
    sweep_sql = text(f"""
        UPDATE tracks t
        SET file_path = lf.file_path, has_file = true
        FROM library_files lf
        WHERE t.musicbrainz_id = lf.musicbrainz_trackid
          AND lf.musicbrainz_trackid IS NOT NULL
          AND lf.musicbrainz_trackid != ''
          AND t.has_file = false
          AND lf.file_path IS NOT NULL
          {path_filter}
    """)
    sweep_result = db.execute(sweep_sql, bulk_params)
    sweep_linked = sweep_result.rowcount
    db.commit()
    if sweep_linked:
        stats["phase4_files_linked"] += sweep_linked
        job_logger.log_info(f"Phase 4 sweep: Linked {sweep_linked} additional files via existing MBIDs")

    _mark_resolved_files(db, job_logger)
    job_logger.log_info(
        f"Phase 4: Fingerprinted {stats['phase4_files_fingerprinted']}, "
        f"identified {stats['phase4_recordings_found']}, "
        f"imported {stats['phase4_albums_imported']} albums, "
        f"linked {stats['phase4_files_linked']}, "
        f"failures {stats['phase4_fingerprint_failures']}"
    )
    job_logger.log_phase_complete("Phase 4", count=stats["phase4_files_linked"])
    return stats


def _phase5_metadata_stub_creation(db, job, job_logger, path_filter, bulk_params):
    """
    Phase 5: Zero-unlinked guarantee.

    For files still unlinked after all prior phases, attempt one more MB search
    by artist + title (5a). If that fails, create synthetic stub Artist/Album/Track
    records from the file's metadata tags (5b).

    Stub records use 'local-<uuid>' as their musicbrainz_id to distinguish them
    from real MusicBrainz-backed records. The is_stub flag is set so future
    re-resolution runs can retry them when real data becomes available.
    """
    import uuid as uuid_mod
    from app.models.artist import Artist
    from app.models.album import Album, AlbumStatus
    from app.models.track import Track
    from app.services.musicbrainz_client import get_musicbrainz_client
    from app.services.album_importer import import_release_group
    from app.services.artist_import_service import ArtistImportService

    stats = {
        "phase5_files_processed": 0,
        "phase5_mb_matches": 0,
        "phase5_stubs_created": 0,
        "phase5_files_linked": 0,
    }

    mb_client = get_musicbrainz_client()
    import_service = ArtistImportService(db)

    sql = text(f"""
        SELECT
            lf.id AS file_id,
            lf.file_path,
            lf.artist,
            lf.album,
            lf.title,
            lf.track_number,
            lf.disc_number,
            lf.year,
            lf.duration_seconds
        FROM library_files lf
        JOIN library_paths lp ON lp.id = lf.library_path_id
        WHERE (lf.musicbrainz_trackid IS NULL OR lf.musicbrainz_trackid = '')
          AND lp.library_type != 'audiobook'
          AND NOT EXISTS (
              SELECT 1 FROM tracks t
              WHERE t.file_path = lf.file_path AND t.has_file = true
          )
          {path_filter}
        ORDER BY lf.artist, lf.album, lf.track_number
    """)
    rows = db.execute(sql, bulk_params).fetchall()

    if not rows:
        job_logger.log_info("Phase 5: No remaining unlinked files — all resolved")
        return stats

    job_logger.log_info(f"Phase 5: {len(rows)} files still unlinked — applying stub fallback")
    total = len(rows)

    for i, row in enumerate(rows):
        if i % 20 == 0:
            job.current_action = f"Phase 5: Stub creation {i}/{total}"
            job.progress_percent = 95 + (i / total) * 5  # Phase 5 = 95-100%
            try:
                db.commit()
            except Exception:
                pass

        stats["phase5_files_processed"] += 1
        file_path = row.file_path
        artist_name = (row.artist or "").strip()
        album_name = (row.album or "").strip()
        track_title = (row.title or "").strip() or Path(file_path).stem
        linked_via_mb = False

        # ── 5a: Try MB recording search ─────────────────────────────────────
        if artist_name and track_title:
            try:
                recordings = mb_client.search_recording(
                    artist=artist_name, title=track_title, limit=3
                )
                for rec in (recordings or []):
                    rec_mbid = rec.get("id")
                    if not rec_mbid:
                        continue

                    rec_detail = mb_client.get_recording(
                        rec_mbid, includes=["releases", "release-groups"]
                    )
                    if not rec_detail:
                        continue

                    # Score release groups and prefer originals
                    best_rg_mbid = None
                    best_rg_score = -99999
                    for rel in (rec_detail.get("releases") or []):
                        rg = rel.get("release-group", {})
                        rg_mbid = rg.get("id")
                        if not rg_mbid:
                            continue
                        rg_score = _score_rg_secondary_types(rg)
                        date_str = rel.get("date", "")
                        try:
                            year = int(date_str[:4]) if date_str else 9999
                        except ValueError:
                            year = 9999
                        combined = rg_score - (year / 100.0)
                        if combined > best_rg_score:
                            best_rg_score = combined
                            best_rg_mbid = rg_mbid

                    if not best_rg_mbid:
                        continue

                    # Find/create artist from recording credits
                    artist_id = None
                    for credit in (rec_detail.get("artist-credit") or []):
                        if not isinstance(credit, dict):
                            continue
                        mb_a = credit.get("artist", {})
                        mb_artist_mbid = mb_a.get("id")
                        if not mb_artist_mbid:
                            continue
                        db_artist = db.query(Artist).filter(
                            Artist.musicbrainz_id == mb_artist_mbid
                        ).first()
                        if db_artist:
                            artist_id = db_artist.id
                        else:
                            new_artist = import_service.create_artist_from_musicbrainz(
                                mb_artist_mbid, mb_a.get("name", artist_name)
                            )
                            if new_artist:
                                db.flush()
                                artist_id = new_artist.id
                        break

                    if not artist_id:
                        continue

                    # Import RG if needed
                    existing_album = db.query(Album).filter(
                        Album.musicbrainz_id == best_rg_mbid
                    ).first()
                    if not existing_album:
                        album = import_release_group(db, artist_id, best_rg_mbid, mb_client)
                        if album:
                            db.commit()

                    # Link file to track
                    track = db.query(Track).filter(Track.musicbrainz_id == rec_mbid).first()
                    if track and not track.has_file:
                        track.file_path = file_path
                        track.has_file = True
                        db.execute(
                            text("""
                                UPDATE library_files
                                SET musicbrainz_trackid = :rec_mbid,
                                    musicbrainz_releasegroupid = :rg_mbid
                                WHERE id = :file_id
                            """),
                            {"rec_mbid": rec_mbid, "rg_mbid": best_rg_mbid,
                             "file_id": str(row.file_id)}
                        )
                        db.commit()
                        stats["phase5_mb_matches"] += 1
                        stats["phase5_files_linked"] += 1
                        linked_via_mb = True
                        job_logger.log_info(
                            f"  Phase 5a: Linked '{track_title}' via MB search"
                        )
                        break

            except Exception as e:
                job_logger.log_info(f"  Phase 5a: MB search failed for '{track_title}': {e}")
                db.rollback()

        if linked_via_mb:
            continue

        # ── 5b: Create synthetic stub records ────────────────────────────────
        try:
            # Find or create stub artist (dedup by normalized name)
            stub_artist = None
            if artist_name:
                normalized = ArtistImportService.normalize_artist_name(artist_name)
                for a in db.query(Artist).all():
                    if ArtistImportService.normalize_artist_name(a.name) == normalized:
                        stub_artist = a
                        break

            if not stub_artist:
                stub_artist = Artist(
                    name=artist_name or "Unknown Artist",
                    musicbrainz_id=f"local-{uuid_mod.uuid4()}",
                    is_monitored=False,
                    is_stub=True,
                )
                db.add(stub_artist)
                db.flush()

            # Find or create stub album (dedup by lowercase title under this artist)
            stub_album = None
            if album_name:
                album_title_lower = album_name.lower().strip()
                for al in db.query(Album).filter(Album.artist_id == stub_artist.id).all():
                    if al.title.lower().strip() == album_title_lower:
                        stub_album = al
                        break

            if not stub_album:
                stub_album = Album(
                    artist_id=stub_artist.id,
                    title=album_name or "Unknown Album",
                    musicbrainz_id=f"local-{uuid_mod.uuid4()}",
                    album_type="Album",
                    status=AlbumStatus.WANTED,
                    is_stub=True,
                )
                if row.year:
                    from datetime import date as date_cls
                    stub_album.release_date = date_cls(row.year, 1, 1)
                db.add(stub_album)
                db.flush()

            # Create stub track (always new — one per file)
            stub_rec_mbid = f"local-{uuid_mod.uuid4()}"
            stub_track = Track(
                id=uuid_mod.uuid4(),
                album_id=stub_album.id,
                title=track_title,
                musicbrainz_id=stub_rec_mbid,
                track_number=row.track_number,
                disc_number=row.disc_number or 1,
                duration_ms=int(row.duration_seconds * 1000) if row.duration_seconds else None,
                has_file=True,
                file_path=file_path,
                is_stub=True,
            )
            db.add(stub_track)

            # Back-write stub MBIDs to library_files for consistency
            db.execute(
                text("""
                    UPDATE library_files
                    SET musicbrainz_trackid = :rec_mbid,
                        musicbrainz_releasegroupid = :rg_mbid
                    WHERE id = :file_id
                """),
                {
                    "rec_mbid": stub_rec_mbid,
                    "rg_mbid": stub_album.musicbrainz_id,
                    "file_id": str(row.file_id),
                }
            )

            db.commit()
            stats["phase5_stubs_created"] += 1
            stats["phase5_files_linked"] += 1
            job_logger.log_info(
                f"  Phase 5b: Stub created for '{track_title}' by '{artist_name or 'Unknown'}'"
            )

        except Exception as e:
            logger.error(f"Phase 5: Stub creation failed for {file_path}: {e}")
            job_logger.log_error(f"Phase 5: Stub failed for {file_path}: {e}")
            db.rollback()

    _mark_resolved_files(db, job_logger)
    job_logger.log_info(
        f"Phase 5: Processed {stats['phase5_files_processed']}, "
        f"MB matches {stats['phase5_mb_matches']}, "
        f"stubs {stats['phase5_stubs_created']}, "
        f"linked {stats['phase5_files_linked']}"
    )
    job_logger.log_phase_complete("Phase 5", count=stats["phase5_files_linked"])
    return stats
