"""
One-time migration: split albums from one-per-release-group to one-per-release.

Run with:
    docker exec studio54-service python scripts/migrate_per_release_albums.py
"""
import sys
import os
import uuid
import logging
from collections import defaultdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import SessionLocal
from app.models.album import Album, AlbumStatus
from app.models.track import Track
from app.models.library import LibraryFile

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BATCH_SIZE = 500


def migrate_album(db: Session, album: Album, mb_client=None) -> str:
    """
    Migrate a single album. Returns one of: 'stub', 'converted', 'split', 'legacy'.

    - stub: no files, release_group_mbid set, musicbrainz_id unchanged
    - converted: single release, musicbrainz_id re-keyed to release MBID
    - split: mixed releases, album split into multiple records
    - legacy: files present but no musicbrainz_albumid tags
    """
    if album.release_group_mbid is not None:
        return "already_done"

    file_tracks = db.query(Track).filter(
        Track.album_id == album.id,
        Track.has_file == True,
        Track.file_path.isnot(None),
    ).all()

    if not file_tracks:
        # Case 1: No files — wanted stub
        album.release_group_mbid = album.musicbrainz_id
        db.flush()
        return "stub"

    release_to_tracks = defaultdict(list)
    no_albumid_tracks = []

    for track in file_tracks:
        lf = db.query(LibraryFile).filter(
            LibraryFile.file_path == track.file_path
        ).first()
        if lf and lf.musicbrainz_albumid:
            release_to_tracks[lf.musicbrainz_albumid].append(track)
        else:
            no_albumid_tracks.append(track)

    if not release_to_tracks:
        # Case 4: Has files but no musicbrainz_albumid on any
        album.release_group_mbid = album.musicbrainz_id
        db.flush()
        return "legacy"

    old_rg_mbid = album.musicbrainz_id

    if len(release_to_tracks) == 1:
        # Case 2: Single release — re-key this album
        release_mbid = list(release_to_tracks.keys())[0]
        conflict = db.query(Album).filter(
            Album.musicbrainz_id == release_mbid,
            Album.id != album.id,
        ).first()
        if conflict:
            album.release_group_mbid = old_rg_mbid
            db.flush()
            return "legacy"
        album.musicbrainz_id = release_mbid
        album.release_mbid = release_mbid
        album.release_group_mbid = old_rg_mbid
        db.flush()
        return "converted"

    # Case 3: Mixed releases — split
    sorted_releases = sorted(release_to_tracks.items(), key=lambda x: len(x[1]), reverse=True)

    primary_release_mbid, primary_tracks = sorted_releases[0]
    conflict = db.query(Album).filter(
        Album.musicbrainz_id == primary_release_mbid,
        Album.id != album.id,
    ).first()
    if not conflict:
        album.musicbrainz_id = primary_release_mbid
        album.release_mbid = primary_release_mbid
    album.release_group_mbid = old_rg_mbid

    primary_track_ids = {t.id for t in primary_tracks}
    for track in file_tracks:
        if track.id not in primary_track_ids:
            db.delete(track)

    for release_mbid, tracks in sorted_releases[1:]:
        conflict = db.query(Album).filter(Album.musicbrainz_id == release_mbid).first()
        if conflict:
            continue

        new_album = Album(
            id=uuid.uuid4(),
            artist_id=album.artist_id,
            title=album.title,
            musicbrainz_id=release_mbid,
            release_mbid=release_mbid,
            release_group_mbid=old_rg_mbid,
            album_type=album.album_type,
            secondary_types=album.secondary_types,
            release_date=album.release_date,
            status=album.status,
            monitored=album.monitored,
            cover_art_url=album.cover_art_url,
        )
        db.add(new_album)
        db.flush()

        for track in tracks:
            track.album_id = new_album.id

    return "split"


def run_migration(db: Session) -> dict:
    """Run the full migration over all albums in batches."""
    stats = {"stub": 0, "converted": 0, "split": 0, "legacy": 0,
             "already_done": 0, "errors": 0}

    processed = 0
    while True:
        batch = db.query(Album).filter(
            Album.release_group_mbid.is_(None)
        ).limit(BATCH_SIZE).all()

        if not batch:
            break

        for album in batch:
            album_id = str(album.id)
            album_mbid = album.musicbrainz_id
            sp = db.begin_nested()
            try:
                result = migrate_album(db, album)
                sp.commit()
                stats[result] = stats.get(result, 0) + 1
            except Exception as e:
                sp.rollback()
                logger.error(f"Error migrating album {album_id} ({album_mbid}): {e}")
                stats["errors"] += 1

        db.commit()
        processed += len(batch)
        logger.info(f"Processed {processed} albums... {stats}")

    return stats


def run_validation(db: Session) -> dict:
    """
    Run post-migration validation checks.
    Returns a dict of check_name -> {pass: bool, count: int, sample_ids: list}.
    """
    report = {}

    # Check 1: No duplicate track positions
    rows = db.execute(text("""
        SELECT album_id, COUNT(*) as cnt
        FROM (
            SELECT album_id, disc_number, track_number
            FROM tracks
            WHERE track_number IS NOT NULL
            GROUP BY album_id, disc_number, track_number
            HAVING COUNT(*) > 1
        ) dupes
        GROUP BY album_id
    """)).fetchall()
    report["duplicate_track_positions"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 2: No cross-release file contamination
    rows = db.execute(text("""
        SELECT t.album_id, COUNT(DISTINCT lf.musicbrainz_albumid) as release_count
        FROM tracks t
        JOIN library_files lf ON lf.file_path = t.file_path
        WHERE lf.musicbrainz_albumid IS NOT NULL AND lf.musicbrainz_albumid != ''
          AND t.has_file = true
        GROUP BY t.album_id
        HAVING COUNT(DISTINCT lf.musicbrainz_albumid) > 1
    """)).fetchall()
    report["cross_release_contamination"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 3: release_group_mbid populated on all albums
    rows = db.execute(text("""
        SELECT id FROM albums WHERE release_group_mbid IS NULL
    """)).fetchall()
    report["release_group_mbid_populated"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 4: musicbrainz_id uniqueness
    rows = db.execute(text("""
        SELECT musicbrainz_id, COUNT(*) FROM albums
        GROUP BY musicbrainz_id HAVING COUNT(*) > 1
    """)).fetchall()
    report["musicbrainz_id_uniqueness"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    # Check 5: No orphaned tracks
    rows = db.execute(text("""
        SELECT t.id
        FROM tracks t
        JOIN library_files lf ON lf.file_path = t.file_path
        JOIN albums al ON al.id = t.album_id
        WHERE t.has_file = true
          AND lf.musicbrainz_albumid IS NOT NULL
          AND lf.musicbrainz_albumid != ''
          AND lf.musicbrainz_albumid != al.musicbrainz_id
    """)).fetchall()
    report["orphaned_tracks"] = {
        "pass": len(rows) == 0,
        "count": len(rows),
        "sample_ids": [str(r[0]) for r in rows[:10]],
    }

    return report


def print_report(report: dict):
    print("\n=== Validation Report ===")
    all_passed = True
    for check, result in report.items():
        icon = "+" if result["pass"] else "x"
        print(f"  {icon} {check}: count={result['count']}")
        if not result["pass"]:
            all_passed = False
            for aid in result.get("sample_ids", []):
                print(f"      -> {aid}")
    print(f"\nOverall: {'PASSED' if all_passed else 'FAILED'}")
    return all_passed


if __name__ == "__main__":
    logger.info("Starting per-release album migration...")
    db = SessionLocal()
    try:
        stats = run_migration(db)
        logger.info(f"Migration complete: {stats}")

        report = run_validation(db)
        passed = print_report(report)
        sys.exit(0 if passed else 1)
    finally:
        db.close()
