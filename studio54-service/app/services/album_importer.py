"""
Album Importer Service
Imports individual release groups as Album + Track records from MusicBrainz.

Extracted from sync_tasks.py album creation pattern for reuse across:
- link_files_task (auto-import missing albums phase)
- resolve_unlinked_files_task (bulk resolution)
- import_tasks.py (import pipeline)
"""

import logging
from datetime import date
from typing import Optional, List, Dict, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.album import Album, AlbumStatus
from app.models.track import Track
from app.services.musicbrainz_client import MusicBrainzClient

logger = logging.getLogger(__name__)


def _parse_mb_date(date_str: str) -> Optional[date]:
    """Parse a MusicBrainz date string (YYYY, YYYY-MM, or YYYY-MM-DD) into a date object."""
    if not date_str:
        return None
    try:
        parts = date_str.split("-")
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        elif len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        elif len(parts) == 1:
            return date(int(parts[0]), 1, 1)
    except (ValueError, IndexError):
        pass
    return None


def import_release_group(
    db: Session,
    artist_id: UUID,
    release_group_mbid: str,
    mb_client: MusicBrainzClient,
) -> Optional[Album]:
    """
    Import a single release group as an Album + Tracks from MusicBrainz.

    Reuses the exact pattern from sync_artist_albums_standalone:
    1. Check if album already exists (idempotent)
    2. Fetch release group metadata
    3. Create Album record (status=WANTED)
    4. select_best_release() to pick the canonical release
    5. Fetch tracks from that release, create Track records

    Args:
        db: Database session
        artist_id: Artist UUID
        release_group_mbid: MusicBrainz release group MBID
        mb_client: MusicBrainz client instance

    Returns:
        The created Album, or None if it already exists or import fails.
    """
    # Skip if album with this musicbrainz_id already exists
    existing = db.query(Album).filter(Album.musicbrainz_id == release_group_mbid).first()
    if existing:
        # Backfill tracks if album has zero tracks (recovery from broken sync)
        existing_track_count = db.query(Track).filter(Track.album_id == existing.id).count()
        if existing_track_count == 0:
            tracks_added = _import_tracks_for_album(db, existing, release_group_mbid, mb_client)
            if tracks_added > 0:
                logger.info(f"Backfilled {tracks_added} tracks for existing album: {existing.title}")
        return None

    # Fetch release group metadata
    rg = mb_client.get_release_group(release_group_mbid)
    if not rg:
        logger.warning(f"Could not fetch release group {release_group_mbid}")
        return None

    # Create Album record
    secondary_types_list = rg.get("secondary-types", [])
    album = Album(
        artist_id=artist_id,
        title=rg.get("title", "Unknown Album"),
        musicbrainz_id=release_group_mbid,
        album_type=rg.get("primary-type", "Album"),
        secondary_types=",".join(secondary_types_list) if secondary_types_list else None,
        status=AlbumStatus.WANTED,
    )

    # Parse release date
    album.release_date = _parse_mb_date(rg.get("first-release-date"))

    db.add(album)
    db.flush()  # Get album.id without committing

    # Import tracks
    tracks_added = _import_tracks_for_album(db, album, release_group_mbid, mb_client)

    logger.info(
        f"Imported release group '{album.title}' ({release_group_mbid}) "
        f"with {tracks_added} tracks for artist {artist_id}"
    )
    return album


def _import_tracks_for_album(
    db: Session,
    album: Album,
    release_group_mbid: str,
    mb_client: MusicBrainzClient,
) -> int:
    """
    Import tracks for an album from MusicBrainz.

    Selects the best release and creates Track records.

    Returns:
        Number of tracks added.
    """
    tracks_added = 0
    try:
        release = mb_client.select_best_release(release_group_mbid)
        if not release:
            return 0

        release_mbid = release.get("id")
        if release_mbid and not album.release_mbid:
            album.release_mbid = release_mbid

        media_list = release.get("media", [])
        for media in media_list:
            disc_number = media.get("position", 1)
            for track_data in media.get("tracks", []):
                recording = track_data.get("recording", {})
                recording_mbid = recording.get("id")

                if not recording_mbid:
                    continue

                # Check if track already exists for this album
                existing_track = db.query(Track).filter(
                    Track.musicbrainz_id == recording_mbid,
                    Track.album_id == album.id,
                ).first()

                if not existing_track:
                    track = Track(
                        album_id=album.id,
                        title=recording.get("title", track_data.get("title", "Unknown Track")),
                        musicbrainz_id=recording_mbid,
                        track_number=track_data.get("position", 0),
                        disc_number=disc_number,
                        duration_ms=recording.get("length"),
                        has_file=False,
                    )
                    db.add(track)
                    tracks_added += 1

        # Update album track_count
        total_release_tracks = sum(len(m.get("tracks", [])) for m in media_list)
        if total_release_tracks > 0 and (album.track_count or 0) < total_release_tracks:
            album.track_count = total_release_tracks

    except Exception as e:
        logger.warning(f"Failed to fetch tracks for release group {release_group_mbid}: {e}")

    return tracks_added


def bulk_import_release_groups(
    db: Session,
    artist_rg_pairs: List[Tuple[UUID, str]],
    mb_client: MusicBrainzClient,
    progress_callback=None,
) -> Dict[str, int]:
    """
    Import multiple release groups, batched by artist for efficiency.

    Args:
        db: Database session
        artist_rg_pairs: List of (artist_id, release_group_mbid) tuples
        mb_client: MusicBrainz client instance
        progress_callback: Optional callable(imported, total, album_title) for progress updates

    Returns:
        Dict with counts: albums_imported, tracks_created, skipped, failed
    """
    stats = {
        "albums_imported": 0,
        "tracks_created": 0,
        "skipped": 0,
        "failed": 0,
    }

    total = len(artist_rg_pairs)
    for idx, (artist_id, rg_mbid) in enumerate(artist_rg_pairs):
        try:
            album = import_release_group(db, artist_id, rg_mbid, mb_client)
            if album:
                stats["albums_imported"] += 1
                track_count = db.query(Track).filter(Track.album_id == album.id).count()
                stats["tracks_created"] += track_count
                db.commit()

                if progress_callback:
                    progress_callback(idx + 1, total, album.title)
            else:
                stats["skipped"] += 1

        except Exception as e:
            logger.error(f"Failed to import release group {rg_mbid}: {e}")
            stats["failed"] += 1
            db.rollback()

    return stats
