"""
Resolve Unlinked Files Task

A Celery task that resolves unlinked library files through three phases:
1. Auto-import missing albums (files with valid RG MBIDs where artist exists but album doesn't)
2. Populate missing release group MBIDs via local MusicBrainz DB lookup, then import
3. Quality-based duplicate resolution with AcoustID fingerprinting

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
        }

        # Start background heartbeat to prevent stall detection during long MB API calls
        from app.models.file_organization_job import FileOrganizationJob as HeartbeatModel
        with BackgroundHeartbeat(job_id, HeartbeatModel, interval=30):

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
        # SUMMARY
        # ═══════════════════════════════════════════════
        job_logger.log_info("=" * 60)
        job_logger.log_info("RESOLVE UNLINKED FILES — FINAL SUMMARY")
        job_logger.log_info("=" * 60)
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
        total_linked = (stats['phase1_files_linked'] + stats['phase1b_files_linked'] +
                        stats['phase2_files_linked'] + stats['phase3_upgrades'])
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
    # - artist is in DB
    # - album is NOT in DB
    sql = text(f"""
        SELECT DISTINCT lf.musicbrainz_releasegroupid AS rg_mbid, a.id AS artist_id
        FROM library_files lf
        JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
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
            job.progress_percent = (imported / total) * 15  # Phase 1 = 0-15%
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
            job.progress_percent = 15 + (i / total) * 15  # Phase 1B = 15-30%
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

    # Find files with recording MBID but no RG MBID, where artist is in DB,
    # and no matching track exists
    sql = text(f"""
        SELECT DISTINCT lf.musicbrainz_trackid AS recording_mbid, lf.id AS file_id,
               a.id AS artist_id, a.musicbrainz_id AS artist_mbid
        FROM library_files lf
        JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
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
            job.progress_percent = 30 + (processed / total_recordings) * 30  # Phase 2 = 30-60% (after 1+1B)
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
        JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
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
            job.progress_percent = 60 + (checked / total) * 40  # Phase 3 = 60-100%
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
