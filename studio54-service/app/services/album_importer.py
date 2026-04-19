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
    Import a release group as a WANTED stub Album (no tracks).

    Tracks belong to specific releases — call import_release() when a file
    with a known release MBID needs a proper album record.
    """
    existing = db.query(Album).filter(Album.musicbrainz_id == release_group_mbid).first()
    if existing:
        return None

    rg = mb_client.get_release_group(release_group_mbid)
    if not rg:
        logger.warning(f"Could not fetch release group {release_group_mbid}")
        return None

    secondary_types_list = rg.get("secondary-types", [])
    album = Album(
        artist_id=artist_id,
        title=rg.get("title", "Unknown Album"),
        musicbrainz_id=release_group_mbid,
        release_group_mbid=release_group_mbid,
        release_mbid=None,
        album_type=rg.get("primary-type", "Album"),
        secondary_types=",".join(secondary_types_list) if secondary_types_list else None,
        status=AlbumStatus.WANTED,
    )
    album.release_date = _parse_mb_date(rg.get("first-release-date"))
    db.add(album)
    db.flush()

    logger.info(
        f"Imported release group stub '{album.title}' ({release_group_mbid}) "
        f"for artist {artist_id}"
    )
    return album


def import_release(
    db: Session,
    release_mbid: str,
    release_group_mbid: str,
    artist_id: UUID,
    mb_client: MusicBrainzClient,
    title: Optional[str] = None,
    album_type: Optional[str] = None,
    release_date: Optional[date] = None,
) -> Optional[Album]:
    """
    Import a specific release as an Album + Tracks from MusicBrainz.

    Creates an album keyed by release MBID (not release group MBID) so that
    separate editions of the same album get separate records.
    """
    existing = db.query(Album).filter(Album.musicbrainz_id == release_mbid).first()
    if existing:
        return None

    release = mb_client.get_release(release_mbid)
    if not release:
        logger.warning(f"Could not fetch release {release_mbid}")
        return None

    rg = release.get("release-group", {})
    resolved_title = title or rg.get("title") or release.get("title", "Unknown Album")
    resolved_type = album_type or rg.get("primary-type", "Album")
    resolved_date = release_date or _parse_mb_date(release.get("date"))

    album = Album(
        artist_id=artist_id,
        title=resolved_title,
        musicbrainz_id=release_mbid,
        release_mbid=release_mbid,
        release_group_mbid=release_group_mbid,
        album_type=resolved_type,
        status=AlbumStatus.DOWNLOADED,
        release_date=resolved_date,
    )
    db.add(album)
    db.flush()

    tracks_added = 0
    media_list = release.get("media", [])
    for media in media_list:
        disc_number = media.get("position", 1)
        for track_data in media.get("tracks", []):
            recording = track_data.get("recording", {})
            recording_mbid = recording.get("id")
            if not recording_mbid:
                continue
            existing_track = db.query(Track).filter(
                Track.musicbrainz_id == recording_mbid,
                Track.album_id == album.id,
            ).first()
            if not existing_track:
                db.add(Track(
                    album_id=album.id,
                    title=recording.get("title") or track_data.get("title", "Unknown Track"),
                    musicbrainz_id=recording_mbid,
                    track_number=track_data.get("position", 0),
                    disc_number=disc_number,
                    duration_ms=recording.get("length"),
                    has_file=False,
                ))
                tracks_added += 1

    total_tracks = sum(len(m.get("tracks", [])) for m in media_list)
    album.track_count = total_tracks
    db.flush()

    logger.info(
        f"Imported release '{album.title}' ({release_mbid}) "
        f"with {tracks_added} tracks for artist {artist_id}"
    )
    return album


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
