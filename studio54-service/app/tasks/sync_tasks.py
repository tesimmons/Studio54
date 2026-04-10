"""
Sync Tasks for Studio54
Celery tasks for syncing artists and albums from MusicBrainz

Architecture (coordinator-batch-finalize):
  sync_all_artists (beat) → sync_artist_coordinator.delay(artist_id) per artist
  sync_artist_coordinator:
    1. Fetch release_groups from MB API
    2. Filter already-synced (bulk DB query by musicbrainz_id)
    3. Split remaining into batches of 10
    4. chord([sync_album_batch.si(...) x N]) | finalize_artist_sync.si(artist_id, job_id)
  sync_album_batch: Process ≤10 albums (MB API, DB insert, cover art, tracks, library check)
  finalize_artist_sync: Aggregate stats, update artist counts
"""

from celery import shared_task, chord
from sqlalchemy.orm import Session
from datetime import datetime, timezone, date
from pathlib import Path
import logging
import shutil
import uuid as uuid_lib

from app.database import SessionLocal
from app.models.album import Album, AlbumStatus
from app.models.artist import Artist, MonitorType
from app.models.track import Track
from app.models.job_state import JobType
from app.services.musicbrainz_client import get_musicbrainz_client
from app.config import settings
from app.tasks.base_task import JobTrackedTask
from app.tasks.celery_app import celery_app
from app.utils.db_retry import retry_db_commit

logger = logging.getLogger(__name__)

BATCH_SIZE = 10  # Albums per batch


def _parse_mb_date(date_str: str):
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


def get_db() -> Session:
    """Get database session"""
    return SessionLocal()


def should_monitor_album(
    artist: Artist,
    release_date: date = None,
    album_type: str = None,
    album_index: int = 0,
    total_albums: int = 0,
    has_local_files: bool = False,
) -> bool:
    """
    Determine if an album should be monitored based on the artist's monitor_type strategy.

    Args:
        artist: The artist record
        release_date: Album release date
        album_type: Album type (Album, Single, EP, etc.)
        album_index: 0-based index of this album when sorted by release_date ascending
        total_albums: Total number of albums for this artist
        has_local_files: Whether this album already has local files

    Returns:
        True if the album should be monitored
    """
    if not artist.is_monitored:
        return False

    monitor_type = getattr(artist, 'monitor_type', MonitorType.ALL_ALBUMS.value)

    if monitor_type == MonitorType.ALL_ALBUMS.value:
        return True
    elif monitor_type == MonitorType.NONE.value:
        return False
    elif monitor_type == MonitorType.FUTURE_ONLY.value:
        if release_date and release_date > date.today():
            return True
        return False
    elif monitor_type == MonitorType.EXISTING_ONLY.value:
        return has_local_files
    elif monitor_type == MonitorType.FIRST_ALBUM.value:
        return album_index == 0
    elif monitor_type == MonitorType.LATEST_ALBUM.value:
        return album_index == total_albums - 1 if total_albums > 0 else True
    else:
        return True


def sync_artist_albums_standalone(db: Session, artist_id: str, heartbeat_fn=None) -> dict:
    """
    Sync all albums for an artist from MusicBrainz (standalone, no task context)

    This is a helper function that can be called directly from other tasks
    without the Celery task overhead.

    Args:
        db: Database session
        artist_id: Artist UUID string
        heartbeat_fn: Optional callback called periodically to keep parent task alive.
                      Signature: heartbeat_fn(step: str) -> None

    Returns:
        dict: Sync summary with counts
    """
    try:
        artist = db.query(Artist).filter(Artist.id == uuid_lib.UUID(artist_id)).first()
        if not artist:
            logger.error(f"Artist not found: {artist_id}")
            return {"success": False, "error": "Artist not found"}

        if not artist.musicbrainz_id:
            logger.error(f"Artist missing MusicBrainz ID: {artist_id}")
            return {"success": False, "error": "No MusicBrainz ID"}

        logger.info(f"Syncing albums for artist: {artist.name}")

        # Fetch artist image if not already present
        if not artist.image_url and artist.musicbrainz_id:
            try:
                from app.services.musicbrainz_images import MusicBrainzImageFetcher
                fetcher = MusicBrainzImageFetcher(fanart_api_key=settings.fanart_api_key)
                image_url = fetcher.fetch_artist_image_sync(artist.musicbrainz_id)
                if image_url:
                    artist.image_url = image_url
                    db.commit()
                    logger.info(f"Fetched artist image for {artist.name}")
            except Exception as e:
                logger.warning(f"Failed to fetch artist image for {artist.name}: {e}")

        # Get albums from MusicBrainz
        mb_client = get_musicbrainz_client()
        release_groups = mb_client.get_artist_albums(
            artist.musicbrainz_id,
            types=["Album", "EP", "Single"],
            exclude_secondary=True
        )

        if not release_groups:
            logger.warning(f"No albums found for artist: {artist.name}")
            artist.last_sync_at = datetime.now(timezone.utc)
            db.commit()
            return {"success": True, "albums_found": 0, "new_albums": 0}

        new_count = 0
        updated_count = 0
        processed_mbids = set()

        for rg_idx, rg in enumerate(release_groups):
            mbid = rg.get("id")
            if not mbid or mbid in processed_mbids:
                continue

            processed_mbids.add(mbid)

            # Send heartbeat every 5 albums to prevent stall detection
            if heartbeat_fn and rg_idx % 5 == 0:
                try:
                    heartbeat_fn(f"Syncing album {rg_idx + 1}/{len(release_groups)} for {artist.name}")
                except Exception:
                    pass

            # Check if album already exists
            existing = db.query(Album).filter(Album.musicbrainz_id == mbid).first()

            if existing and str(existing.artist_id) == str(artist.id):
                # Update existing album
                existing.title = rg.get("title", existing.title)
                existing.album_type = rg.get("primary-type", existing.album_type)
                secondary_types_list = rg.get("secondary-types", [])
                existing.secondary_types = ",".join(secondary_types_list) if secondary_types_list else None

                # Parse release date
                first_release_date = rg.get("first-release-date")
                if first_release_date:
                    try:
                        date_parts = first_release_date.split("-")
                        if len(date_parts) == 3:
                            existing.release_date = date(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                        elif len(date_parts) == 2:
                            existing.release_date = date(int(date_parts[0]), int(date_parts[1]), 1)
                        elif len(date_parts) == 1:
                            existing.release_date = date(int(date_parts[0]), 1, 1)
                    except (ValueError, IndexError):
                        pass

                existing.updated_at = datetime.now(timezone.utc)

                # Backfill tracks if album has zero tracks (recovery from broken sync)
                existing_track_count = db.query(Track).filter(Track.album_id == existing.id).count()
                if existing_track_count == 0:
                    try:
                        tracks_data = mb_client.get_release_tracks(mbid)
                        if tracks_data:
                            for td in tracks_data:
                                track = Track(
                                    album_id=existing.id,
                                    title=td.get("title", "Unknown Track"),
                                    track_number=td.get("track_number", 0),
                                    duration_ms=td.get("duration_ms"),
                                    musicbrainz_id=td.get("musicbrainz_id"),
                                    has_file=False
                                )
                                db.add(track)
                            existing.track_count = len(tracks_data)
                            logger.info(f"Backfilled {len(tracks_data)} tracks for existing album: {existing.title}")
                    except Exception as track_error:
                        logger.error(f"Failed to backfill tracks for album {mbid}: {track_error}")

                updated_count += 1
            else:
                # Create new album
                secondary_types_list = rg.get("secondary-types", [])
                album = Album(
                    artist_id=artist.id,
                    title=rg.get("title", "Unknown Album"),
                    musicbrainz_id=mbid,
                    album_type=rg.get("primary-type", "Album"),
                    secondary_types=",".join(secondary_types_list) if secondary_types_list else None,
                    status=AlbumStatus.WANTED
                )

                # Parse release date
                first_release_date = rg.get("first-release-date")
                if first_release_date:
                    try:
                        date_parts = first_release_date.split("-")
                        if len(date_parts) == 3:
                            album.release_date = date(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
                        elif len(date_parts) == 2:
                            album.release_date = date(int(date_parts[0]), int(date_parts[1]), 1)
                        elif len(date_parts) == 1:
                            album.release_date = date(int(date_parts[0]), 1, 1)
                    except (ValueError, IndexError):
                        pass

                db.add(album)
                new_count += 1

            # Fetch and save tracks for this release group
            try:
                release = mb_client.select_best_release(mbid)
                if release:
                    release_mbid = release.get("id")
                    media_list = release.get("media", [])
                    tracks_added = 0

                    for media in media_list:
                        for track_data in media.get("tracks", []):
                            recording = track_data.get("recording", {})
                            recording_mbid = recording.get("id")

                            if not recording_mbid:
                                continue

                            # Check if track exists
                            existing_track = db.query(Track).filter(
                                Track.musicbrainz_id == recording_mbid,
                                Track.album.has(Album.musicbrainz_id == mbid)
                            ).first()

                            if not existing_track:
                                # Get album for this track
                                album_obj = db.query(Album).filter(
                                    Album.musicbrainz_id == mbid
                                ).first()

                                if album_obj:
                                    track = Track(
                                        album_id=album_obj.id,
                                        title=recording.get("title", track_data.get("title", "Unknown Track")),
                                        musicbrainz_id=recording_mbid,
                                        track_number=track_data.get("position", 0),
                                        duration_ms=recording.get("length")
                                    )
                                    db.add(track)
                                    tracks_added += 1

                    # Update album track_count from total tracks in release
                    total_release_tracks = sum(
                        len(m.get("tracks", [])) for m in media_list
                    )
                    if total_release_tracks > 0:
                        album_obj = db.query(Album).filter(Album.musicbrainz_id == mbid).first()
                        if album_obj and (album_obj.track_count or 0) < total_release_tracks:
                            album_obj.track_count = total_release_tracks
            except Exception as track_error:
                logger.warning(f"Failed to fetch tracks for release group {mbid}: {track_error}")

        # Update artist stats and sync timestamp
        _update_artist_stats(db, artist)
        artist.last_sync_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"Sync complete for {artist.name}: {new_count} new, {updated_count} updated, "
                     f"stats: {artist.album_count} albums, {artist.single_count} singles, {artist.track_count} tracks")
        return {
            "success": True,
            "albums_found": len(release_groups),
            "new_albums": new_count,
            "updated_albums": updated_count
        }

    except Exception as e:
        logger.error(f"Error syncing albums for artist {artist_id}: {e}")
        db.rollback()
        return {"success": False, "error": str(e)}


def _process_single_album(db: Session, artist, rg, idx, total_albums, mb_client):
    """
    Process a single release group: create/update album, fetch cover art, tracks, check library.

    Returns:
        dict with keys: new, updated, skipped, tracks_added, error (if any)
    """
    result = {"new": 0, "updated": 0, "skipped": 0, "tracks_added": 0}

    mbid = rg.get("id")
    if not mbid:
        return result

    try:
        # Check if album already exists (by musicbrainz_id, globally)
        existing = db.query(Album).filter(Album.musicbrainz_id == mbid).first()

        if existing:
            # Album exists - check if it's linked to this artist
            if str(existing.artist_id) == str(artist.id):
                # Update existing album for this artist
                existing.title = rg.get("title", existing.title)
                existing.album_type = rg.get("primary-type", existing.album_type)
                secondary_types_list = rg.get("secondary-types", [])
                existing.secondary_types = ",".join(secondary_types_list) if secondary_types_list else None
                existing.release_date = _parse_mb_date(rg.get("first-release-date")) or existing.release_date
                existing.updated_at = datetime.now(timezone.utc)

                # Fetch cover art if not already present
                if not existing.cover_art_url:
                    try:
                        release = mb_client.select_best_release(mbid)
                        if release:
                            release_mbid = release.get("id")
                            if release_mbid:
                                cover_url = mb_client.get_cover_art(release_mbid)
                                if cover_url:
                                    existing.cover_art_url = cover_url
                                    logger.info(f"Fetched cover art for existing album: {existing.title}")
                    except Exception as art_error:
                        logger.warning(f"Failed to fetch cover art for existing album {mbid}: {art_error}")

                # Sync tracks if album has zero tracks (recovery from broken sync)
                existing_track_count = db.query(Track).filter(Track.album_id == existing.id).count()
                if existing_track_count == 0:
                    try:
                        tracks_data = mb_client.get_release_tracks(mbid)
                        if tracks_data:
                            for track_data in tracks_data:
                                track = Track(
                                    album_id=existing.id,
                                    title=track_data.get("title", "Unknown Track"),
                                    track_number=track_data.get("track_number", 0),
                                    duration_ms=track_data.get("duration_ms"),
                                    musicbrainz_id=track_data.get("musicbrainz_id"),
                                    has_file=False
                                )
                                db.add(track)
                                result["tracks_added"] += 1
                            existing.track_count = len(tracks_data)
                            logger.info(f"Backfilled {len(tracks_data)} tracks for existing album: {existing.title}")
                    except Exception as track_error:
                        logger.error(f"Failed to backfill tracks for album {mbid}: {track_error}")

                result["updated"] = 1
            else:
                # Album exists but linked to different artist (compilation/collaboration)
                logger.debug(f"Skipping album {mbid} - already exists for different artist")
                result["skipped"] = 1
            return result

        # Create new album
        release_date = _parse_mb_date(rg.get("first-release-date"))

        # Determine monitoring based on artist's monitor_type strategy
        album_monitored = should_monitor_album(
            artist=artist,
            release_date=release_date,
            album_type=rg.get("primary-type"),
            album_index=idx,
            total_albums=total_albums,
            has_local_files=False,
        )

        secondary_types_list = rg.get("secondary-types", [])
        album = Album(
            artist_id=artist.id,
            title=rg.get("title", "Unknown Album"),
            musicbrainz_id=mbid,
            release_date=release_date,
            album_type=rg.get("primary-type"),
            secondary_types=",".join(secondary_types_list) if secondary_types_list else None,
            status=AlbumStatus.WANTED,
            monitored=album_monitored,
            added_at=datetime.now(timezone.utc)
        )

        try:
            db.add(album)
            db.flush()  # Flush to get album.id
            result["new"] = 1
        except Exception as insert_error:
            # Handle unique constraint violation (race condition)
            if "duplicate key" in str(insert_error).lower() or "unique constraint" in str(insert_error).lower():
                logger.warning(f"Album {mbid} already exists (race condition), re-querying")
                db.rollback()
                album = db.query(Album).filter(Album.musicbrainz_id == mbid).first()
                if not album:
                    result["skipped"] = 1
                    return result
                result["updated"] = 1
            else:
                raise

        # Fetch album cover art
        try:
            release = mb_client.select_best_release(mbid)
            if release:
                release_mbid = release.get("id")
                if release_mbid:
                    cover_url = mb_client.get_cover_art(release_mbid)
                    if cover_url:
                        album.cover_art_url = cover_url
                        logger.info(f"Fetched cover art for album: {album.title}")
        except Exception as art_error:
            logger.warning(f"Failed to fetch cover art for album {mbid}: {art_error}")

        # Fetch and populate tracks
        try:
            tracks_data = mb_client.get_release_tracks(mbid)
            if tracks_data:
                for track_data in tracks_data:
                    track = Track(
                        album_id=album.id,
                        title=track_data.get("title", "Unknown Track"),
                        track_number=track_data.get("track_number", 0),
                        duration_ms=track_data.get("duration_ms"),
                        musicbrainz_id=track_data.get("musicbrainz_id"),
                        has_file=False
                    )
                    db.add(track)
                    result["tracks_added"] += 1
                album.track_count = len(tracks_data)
                logger.info(f"Added {len(tracks_data)} tracks for {album.title}")
        except Exception as track_error:
            logger.error(f"Failed to fetch tracks for album {mbid}: {track_error}")

        # Check if album exists in libraries (MUSE or Studio54)
        try:
            from app.services.muse_client import get_muse_client
            from app.models.library import LibraryFile

            min_track_count = album.track_count or 1

            muse_client = get_muse_client()
            exists, file_count = muse_client.album_exists(
                musicbrainz_id=album.musicbrainz_id,
                min_track_count=min_track_count
            )

            if exists:
                album.status = AlbumStatus.DOWNLOADED
                album.muse_verified = True
                logger.info(f"Album '{album.title}' found in MUSE library ({file_count} files)")
            else:
                studio54_file_count = db.query(LibraryFile).filter(
                    LibraryFile.musicbrainz_releasegroupid == album.musicbrainz_id
                ).count()
                if studio54_file_count >= min_track_count:
                    album.status = AlbumStatus.DOWNLOADED
                    logger.info(f"Album '{album.title}' found in Studio54 library ({studio54_file_count} files)")
        except Exception as lib_check_error:
            logger.warning(f"Failed to check library for album {mbid}: {lib_check_error}")

    except Exception as e:
        logger.error(f"Failed to process album {mbid}: {e}")

    return result


# ---------------------------------------------------------------------------
# Coordinator: entry point for artist sync (replaces monolithic sync_artist_albums)
# ---------------------------------------------------------------------------
@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.sync_artist_albums",
    max_retries=3,
    default_retry_delay=120,
    autoretry_for=(ConnectionError, TimeoutError)
)
def sync_artist_albums(self, artist_id: str, job_id: str = None, **kwargs):
    """
    Coordinator: fetch release groups from MusicBrainz, split into batches,
    dispatch via chord, then finalize.

    Registered under the original task name for backward compatibility.
    """
    db = self.db

    try:
        artist = db.query(Artist).filter(Artist.id == uuid_lib.UUID(artist_id)).first()
        if not artist:
            logger.error(f"Artist not found: {artist_id}")
            return {"success": False, "error": "Artist not found"}

        if not artist.musicbrainz_id:
            logger.error(f"Artist missing MusicBrainz ID: {artist_id}")
            return {"success": False, "error": "No MusicBrainz ID"}

        logger.info(f"[coordinator] Starting sync for artist: {artist.name}")

        # Initialize job logger
        job_logger = self.init_job_logger("sync", f"Artist Sync: {artist.name}")
        job_logger.log_artist_sync(
            artist_name=artist.name,
            mbid=artist.musicbrainz_id,
            action="found"
        )

        self.update_progress(
            percent=5.0,
            step=f"Starting sync for {artist.name}",
            items_processed=0
        )

        # Fetch artist image if not already present
        if not artist.image_url and artist.musicbrainz_id:
            try:
                from app.services.musicbrainz_images import MusicBrainzImageFetcher
                fetcher = MusicBrainzImageFetcher(fanart_api_key=settings.fanart_api_key)
                image_url = fetcher.fetch_artist_image_sync(artist.musicbrainz_id)
                if image_url:
                    artist.image_url = image_url
                    db.commit()
                    logger.info(f"Fetched artist image for {artist.name}")
                    job_logger.log_info(f"  [IMAGE] Fetched artist image: {image_url}")
                else:
                    logger.debug(f"No artist image found for {artist.name}")
                    job_logger.log_info(f"  [IMAGE] No artist image found")
            except Exception as e:
                logger.warning(f"Failed to fetch artist image for {artist.name}: {e}")
                job_logger.log_warning(f"Failed to fetch artist image: {e}")

        # Get albums from MusicBrainz
        mb_client = get_musicbrainz_client()

        self.update_progress(
            percent=15.0,
            step=f"Fetching albums from MusicBrainz for {artist.name}"
        )
        job_logger.log_info(f"Fetching albums from MusicBrainz...")

        release_groups = mb_client.get_artist_albums(
            artist.musicbrainz_id,
            types=["Album", "EP", "Single"],
            exclude_secondary=True
        )

        if not release_groups:
            logger.warning(f"No albums found for artist: {artist.name}")
            job_logger.log_info(f"No albums found for artist")
            artist.last_sync_at = datetime.now(timezone.utc)
            db.commit()
            return {"success": True, "albums_found": 0, "new_albums": 0}

        # Deduplicate release groups
        seen_mbids = set()
        unique_rgs = []
        for rg in release_groups:
            mbid = rg.get("id")
            if mbid and mbid not in seen_mbids:
                seen_mbids.add(mbid)
                unique_rgs.append(rg)

        # Filter out already-synced albums (bulk query)
        existing_mbids = set(
            row[0] for row in db.query(Album.musicbrainz_id).filter(
                Album.musicbrainz_id.in_(list(seen_mbids)),
                Album.artist_id == artist.id
            ).all()
        )

        # Separate into new (need full processing) and existing (quick update)
        new_rgs = [rg for rg in unique_rgs if rg.get("id") not in existing_mbids]
        existing_rgs = [rg for rg in unique_rgs if rg.get("id") in existing_mbids]

        total_albums = len(unique_rgs)
        job_logger.log_info(
            f"Found {total_albums} albums/singles ({len(new_rgs)} new, {len(existing_rgs)} existing)"
        )
        job_logger.stats.albums_found = total_albums

        self.update_progress(
            percent=20.0,
            step=f"Found {total_albums} albums, dispatching {len(new_rgs)} new to batches"
        )

        # Resolve the job_id for sub-tasks to reference
        coordinator_job_id = str(self.job.id) if self.job else None

        # Quick-update existing albums (metadata only, no MB API calls needed)
        # Also backfill tracks for albums with zero tracks (recovery from broken sync)
        albums_needing_tracks = []
        if existing_rgs:
            updated = 0
            for rg in existing_rgs:
                mbid = rg.get("id")
                existing = db.query(Album).filter(
                    Album.musicbrainz_id == mbid,
                    Album.artist_id == artist.id
                ).first()
                if existing:
                    existing.title = rg.get("title", existing.title)
                    existing.album_type = rg.get("primary-type", existing.album_type)
                    new_date = _parse_mb_date(rg.get("first-release-date"))
                    if new_date:
                        existing.release_date = new_date
                    existing.updated_at = datetime.now(timezone.utc)
                    updated += 1
                    # Check if album has zero tracks and needs backfill
                    track_count = db.query(Track).filter(Track.album_id == existing.id).count()
                    if track_count == 0:
                        albums_needing_tracks.append((existing, mbid))
            retry_db_commit(db)
            logger.info(f"[coordinator] Quick-updated {updated} existing albums for {artist.name}")

            # Backfill tracks for albums with zero tracks
            if albums_needing_tracks:
                mb_client = get_musicbrainz_client()
                backfilled = 0
                for album_obj, rg_mbid in albums_needing_tracks:
                    try:
                        tracks_data = mb_client.get_release_tracks(rg_mbid)
                        if tracks_data:
                            for td in tracks_data:
                                track = Track(
                                    album_id=album_obj.id,
                                    title=td.get("title", "Unknown Track"),
                                    track_number=td.get("track_number", 0),
                                    duration_ms=td.get("duration_ms"),
                                    musicbrainz_id=td.get("musicbrainz_id"),
                                    has_file=False
                                )
                                db.add(track)
                            backfilled += 1
                    except Exception as track_error:
                        logger.warning(f"Failed to backfill tracks for album {rg_mbid}: {track_error}")
                retry_db_commit(db)
                logger.info(f"[coordinator] Backfilled tracks for {backfilled}/{len(albums_needing_tracks)} albums for {artist.name}")

        # If no new albums, finalize immediately
        if not new_rgs:
            logger.info(f"[coordinator] No new albums for {artist.name}, finalizing")
            artist.last_sync_at = datetime.now(timezone.utc)
            _update_artist_stats(db, artist)
            retry_db_commit(db)

            self.update_progress(
                percent=100.0,
                step=f"Sync complete for {artist.name}",
                items_processed=total_albums,
                items_total=total_albums
            )

            return {
                "success": True,
                "artist_id": str(artist.id),
                "artist_name": artist.name,
                "albums_found": total_albums,
                "new_albums": 0,
                "updated_albums": len(existing_rgs),
                "skipped_albums": 0,
                "tracks_added": 0
            }

        # Split new release groups into batches
        batches = [new_rgs[i:i + BATCH_SIZE] for i in range(0, len(new_rgs), BATCH_SIZE)]
        total_batches = len(batches)

        logger.info(
            f"[coordinator] Dispatching {total_batches} batches "
            f"({len(new_rgs)} new albums, batch size {BATCH_SIZE}) for {artist.name}"
        )

        # Build chord: parallel batch tasks → finalize callback
        batch_tasks = []
        for batch_num, batch_rgs in enumerate(batches):
            # Serialize release group dicts for JSON transport
            batch_tasks.append(
                sync_album_batch.si(
                    artist_id=artist_id,
                    release_groups=batch_rgs,
                    batch_num=batch_num + 1,
                    total_batches=total_batches,
                    total_albums=total_albums,
                    coordinator_job_id=coordinator_job_id,
                )
            )

        callback = finalize_artist_sync.si(
            artist_id=artist_id,
            coordinator_job_id=coordinator_job_id,
            existing_updated=len(existing_rgs),
            total_albums=total_albums,
        )

        chord(batch_tasks)(callback)

        logger.info(
            f"[coordinator] Dispatched {total_batches} batch tasks with finalize callback "
            f"for {artist.name}"
        )

        # Return immediately — finalize will update artist stats
        return {
            "success": True,
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            "albums_found": total_albums,
            "batches_dispatched": total_batches,
            "existing_updated": len(existing_rgs),
            "status": "batches_dispatched"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"[coordinator] Failed to sync artist {artist_id}: {e}")
        if self.job_logger:
            self.job_logger.log_error(f"Sync failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Batch task: process a slice of release groups for one artist
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.sync_tasks.sync_album_batch",
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(ConnectionError, TimeoutError)
)
def sync_album_batch(
    artist_id: str,
    release_groups: list,
    batch_num: int,
    total_batches: int,
    total_albums: int,
    coordinator_job_id: str = None,
):
    """
    Process a batch of release groups for a single artist.

    Each batch commits independently so partial results survive crashes.

    Returns:
        dict: Batch stats (new, updated, skipped, tracks_added)
    """
    db = SessionLocal()
    try:
        artist = db.query(Artist).filter(Artist.id == uuid_lib.UUID(artist_id)).first()
        if not artist:
            logger.error(f"[batch {batch_num}/{total_batches}] Artist not found: {artist_id}")
            return {"success": False, "error": "Artist not found"}

        mb_client = get_musicbrainz_client()

        stats = {"new": 0, "updated": 0, "skipped": 0, "tracks_added": 0}

        logger.info(
            f"[batch {batch_num}/{total_batches}] Processing {len(release_groups)} albums "
            f"for {artist.name}"
        )

        for idx, rg in enumerate(release_groups):
            # Calculate global index for monitoring strategy
            global_idx = (batch_num - 1) * BATCH_SIZE + idx
            result = _process_single_album(db, artist, rg, global_idx, total_albums, mb_client)
            stats["new"] += result["new"]
            stats["updated"] += result["updated"]
            stats["skipped"] += result["skipped"]
            stats["tracks_added"] += result["tracks_added"]

            # Update coordinator heartbeat mid-batch to prevent stall detection
            if coordinator_job_id and idx % 3 == 0:
                try:
                    from app.models.job_state import JobState as _JS
                    _job = db.query(_JS).filter(_JS.id == uuid_lib.UUID(coordinator_job_id)).first()
                    if _job:
                        _job.last_heartbeat_at = datetime.now(timezone.utc)
                        _job.current_step = (
                            f"Batch {batch_num}/{total_batches}: album {idx + 1}/{len(release_groups)}"
                        )
                        db.flush()
                except Exception:
                    pass

        # Commit the whole batch
        retry_db_commit(db)

        # Update coordinator job progress and heartbeat
        if coordinator_job_id:
            try:
                from app.models.job_state import JobState
                job = db.query(JobState).filter(
                    JobState.id == uuid_lib.UUID(coordinator_job_id)
                ).first()
                if job:
                    # Progress: 20% (coordinator overhead) + batch proportion of remaining 75%
                    progress = 20.0 + (batch_num / total_batches) * 75.0
                    job.progress_percent = min(95.0, progress)
                    job.current_step = (
                        f"Batch {batch_num}/{total_batches} complete "
                        f"({stats['new']} new, {stats['updated']} updated)"
                    )
                    # Keep coordinator heartbeat alive
                    job.last_heartbeat_at = datetime.now(timezone.utc)
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception as progress_err:
                logger.warning(f"[batch {batch_num}] Failed to update job progress: {progress_err}")
                try:
                    db.rollback()
                except Exception:
                    pass

        logger.info(
            f"[batch {batch_num}/{total_batches}] Complete for {artist.name}: "
            f"{stats['new']} new, {stats['updated']} updated, "
            f"{stats['skipped']} skipped, {stats['tracks_added']} tracks"
        )

        stats["success"] = True
        stats["batch_num"] = batch_num
        return stats

    except Exception as e:
        db.rollback()
        logger.error(f"[batch {batch_num}/{total_batches}] Failed for artist {artist_id}: {e}")
        return {
            "success": False,
            "batch_num": batch_num,
            "error": str(e),
            "new": 0, "updated": 0, "skipped": 0, "tracks_added": 0,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Finalize: aggregate batch results and update artist stats
# ---------------------------------------------------------------------------
@celery_app.task(
    name="app.tasks.sync_tasks.finalize_artist_sync",
    max_retries=2,
    default_retry_delay=30,
)
def finalize_artist_sync(
    batch_results,
    artist_id: str,
    coordinator_job_id: str = None,
    existing_updated: int = 0,
    total_albums: int = 0,
):
    """
    Aggregate batch results and update artist stats.

    Called automatically by chord after all sync_album_batch tasks complete.

    Args:
        batch_results: List of dicts returned by sync_album_batch tasks
        artist_id: Artist UUID
        coordinator_job_id: Job ID for progress tracking
        existing_updated: Count of existing albums quick-updated by coordinator
        total_albums: Total album count for stats
    """
    db = SessionLocal()
    try:
        artist = db.query(Artist).filter(Artist.id == uuid_lib.UUID(artist_id)).first()
        if not artist:
            logger.error(f"[finalize] Artist not found: {artist_id}")
            return {"success": False, "error": "Artist not found"}

        # Aggregate stats from all batches
        totals = {"new": 0, "updated": existing_updated, "skipped": 0, "tracks_added": 0, "errors": 0}
        if isinstance(batch_results, list):
            for br in batch_results:
                if isinstance(br, dict):
                    totals["new"] += br.get("new", 0)
                    totals["updated"] += br.get("updated", 0)
                    totals["skipped"] += br.get("skipped", 0)
                    totals["tracks_added"] += br.get("tracks_added", 0)
                    if not br.get("success", False):
                        totals["errors"] += 1

        # Update artist stats
        _update_artist_stats(db, artist)
        artist.last_sync_at = datetime.now(timezone.utc)

        retry_db_commit(db)

        # Update coordinator job to COMPLETED
        if coordinator_job_id:
            try:
                from app.models.job_state import JobState, JobStatus
                job = db.query(JobState).filter(
                    JobState.id == uuid_lib.UUID(coordinator_job_id)
                ).first()
                if job:
                    job.progress_percent = 100.0
                    job.current_step = (
                        f"Sync complete: {totals['new']} new, {totals['updated']} updated, "
                        f"{totals['skipped']} skipped"
                    )
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.now(timezone.utc)
                    job.updated_at = datetime.now(timezone.utc)
                    job.last_heartbeat_at = datetime.now(timezone.utc)
                    job.result_data = {
                        "success": True,
                        "artist_id": str(artist.id),
                        "artist_name": artist.name,
                        "albums_found": total_albums,
                        "new_albums": totals["new"],
                        "updated_albums": totals["updated"],
                        "skipped_albums": totals["skipped"],
                        "tracks_added": totals["tracks_added"],
                        "batch_errors": totals["errors"],
                    }
                    db.commit()
            except Exception as job_err:
                logger.warning(f"[finalize] Failed to update coordinator job: {job_err}")
                try:
                    db.rollback()
                except Exception:
                    pass

        logger.info(
            f"[finalize] Sync complete for {artist.name}: "
            f"{totals['new']} new, {totals['updated']} updated, "
            f"{totals['skipped']} skipped, {totals['tracks_added']} tracks"
        )

        return {
            "success": True,
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            **totals,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"[finalize] Failed for artist {artist_id}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def _update_artist_stats(db: Session, artist: Artist):
    """Update artist album/single/track counts from DB."""
    from sqlalchemy import func
    artist.album_count = db.query(Album).filter(
        Album.artist_id == artist.id,
        Album.album_type != 'Single'
    ).count()
    artist.single_count = db.query(Album).filter(
        Album.artist_id == artist.id,
        Album.album_type == 'Single'
    ).count()
    artist.track_count = db.query(func.sum(Album.track_count)).filter(
        Album.artist_id == artist.id
    ).scalar() or 0


@shared_task(name="app.tasks.sync_tasks.sync_album_tracks")
def sync_album_tracks(album_id: str, release_mbid: str = None):
    """
    Sync track list for an album from MusicBrainz

    Args:
        album_id: Album UUID
        release_mbid: Specific release MBID (optional, will select best if not provided)

    Returns:
        dict: Sync summary
    """
    db = get_db()
    try:
        album = db.query(Album).filter(Album.id == album_id).first()
        if not album:
            logger.error(f"Album not found: {album_id}")
            return {"success": False, "error": "Album not found"}

        if not album.musicbrainz_id:
            logger.error(f"Album missing MusicBrainz ID: {album_id}")
            return {"success": False, "error": "No MusicBrainz ID"}

        mb_client = get_musicbrainz_client()

        # Get best release if not provided
        if not release_mbid:
            release = mb_client.select_best_release(album.musicbrainz_id)
            if not release:
                logger.warning(f"No release found for album: {album.title}")
                return {"success": False, "error": "No release found"}

            release_mbid = release.get("id")
            album.release_mbid = release_mbid

            # Get cover art
            cover_url = mb_client.get_cover_art(release_mbid)
            if cover_url:
                album.cover_art_url = cover_url
        else:
            release = mb_client.get_release(release_mbid)
            if not release:
                return {"success": False, "error": "Release not found"}

        # Extract tracks
        media = release.get("media", [])
        track_count = 0

        for medium in media:
            tracks = medium.get("tracks", [])
            disc_number = medium.get("position", 1)

            for track_data in tracks:
                track_number = track_data.get("position")
                recording = track_data.get("recording", {})

                # Check if track exists (match by disc + track number)
                existing = db.query(Track).filter(
                    Track.album_id == album.id,
                    Track.disc_number == disc_number,
                    Track.track_number == track_number
                ).first()

                if existing:
                    # Update existing
                    existing.title = recording.get("title", existing.title)
                    existing.musicbrainz_id = recording.get("id")
                    existing.duration_ms = recording.get("length")
                    existing.disc_number = disc_number
                else:
                    # Create new track
                    track = Track(
                        album_id=album.id,
                        title=recording.get("title", "Unknown Track"),
                        musicbrainz_id=recording.get("id"),
                        track_number=track_number,
                        disc_number=disc_number,
                        duration_ms=recording.get("length"),
                        has_file=False
                    )
                    db.add(track)

                track_count += 1

        # Update album track count
        album.track_count = track_count
        album.updated_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(f"Synced {track_count} tracks for album: {album.title}")

        return {
            "success": True,
            "album_id": str(album.id),
            "album_title": album.title,
            "track_count": track_count,
            "release_mbid": release_mbid
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to sync tracks for album {album_id}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(bind=True, base=JobTrackedTask, name="app.tasks.sync_tasks.sync_all_artists")
def sync_all_artists(self, job_id=None, **kwargs):
    """
    Sync all monitored artists with batched dispatch and job tracking.

    Periodic task (runs daily via beat schedule).
    Dispatches artists in batches of 10 via Celery chord for parallel processing.

    Returns:
        dict: Summary of sync operation
    """
    db = self.db if self.db else get_db()
    try:
        artists = db.query(Artist).filter(Artist.is_monitored == True).all()

        if not artists:
            logger.info("No monitored artists to sync")
            return {"monitored_artists": 0, "synced": 0}

        job_logger = self.init_job_logger("artist_sync", "Sync All Artists")
        job_logger.log_info(f"Syncing {len(artists)} monitored artists")

        BATCH_SIZE = 10
        artist_ids = [str(a.id) for a in artists]
        batches = [artist_ids[i:i + BATCH_SIZE] for i in range(0, len(artist_ids), BATCH_SIZE)]

        self.update_progress(percent=5.0, step=f"Dispatching {len(batches)} artist batches")

        batch_tasks = [sync_artist_batch.si(batch, idx, len(batches)) for idx, batch in enumerate(batches)]
        parent_job_id = str(self.job.id) if self.job else None
        callback = finalize_all_artists_sync.si(len(artists), len(batches), parent_job_id)
        chord(batch_tasks)(callback)

        return {"monitored_artists": len(artists), "batches": len(batches)}

    except Exception as e:
        logger.error(f"All artists sync failed: {e}")
        raise


@shared_task(name="app.tasks.sync_tasks.sync_artist_batch")
def sync_artist_batch(artist_ids, batch_idx, total_batches):
    """Dispatch sync_artist_albums for each artist in a batch."""
    results = {"queued": 0, "failed": 0}
    for artist_id in artist_ids:
        try:
            sync_artist_albums.delay(artist_id)
            results["queued"] += 1
        except Exception as e:
            logger.error(f"Failed to queue sync for artist {artist_id}: {e}")
            results["failed"] += 1
    logger.info(f"Artist batch {batch_idx + 1}/{total_batches}: queued {results['queued']}")
    return results


@shared_task(name="app.tasks.sync_tasks.finalize_all_artists_sync")
def finalize_all_artists_sync(batch_results, total_artists, total_batches, parent_job_id=None):
    """Aggregate batch results and mark parent job complete."""
    total_queued = sum(r.get("queued", 0) for r in batch_results if isinstance(r, dict))
    total_failed = sum(r.get("failed", 0) for r in batch_results if isinstance(r, dict))
    logger.info(f"All artists sync dispatched: {total_queued} queued, {total_failed} failed")

    if parent_job_id:
        from app.utils.db_retry import retry_db_commit
        from app.models.job_state import JobState, JobStatus
        db = SessionLocal()
        try:
            job = db.query(JobState).filter(JobState.id == parent_job_id).first()
            if job:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(timezone.utc)
                job.progress_percent = 100.0
                job.current_step = f"Dispatched {total_queued}/{total_artists} artists"
                retry_db_commit(db)
        finally:
            db.close()

    return {"total_artists": total_artists, "total_queued": total_queued, "total_failed": total_failed}

@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.refresh_artist_metadata",
    max_retries=3,
    default_retry_delay=60
)
def refresh_artist_metadata(self, artist_id: str, job_id: str = None, force: bool = False, **kwargs):
    """
    Refresh metadata (images) for a single artist and its albums

    This is a lighter operation than full sync - only fetches missing images
    without re-syncing the full album list from MusicBrainz.

    Args:
        artist_id: Artist UUID
        job_id: Optional job ID for resuming
        force: If True, re-fetch metadata even if fields already have values
        **kwargs: Job tracking parameters

    Returns:
        dict: Summary with counts of updated metadata
    """
    db = self.db

    try:
        artist = db.query(Artist).filter(Artist.id == uuid_lib.UUID(artist_id)).first()
        if not artist:
            logger.error(f"Artist not found: {artist_id}")
            return {"success": False, "error": "Artist not found"}

        # Initialize job logger for log file tracking
        job_logger = self.init_job_logger("metadata_refresh", f"Metadata refresh: {artist.name}")

        logger.info(f"Refreshing metadata for artist: {artist.name}")

        self.update_progress(
            percent=5.0,
            step=f"Starting metadata refresh for {artist.name}",
            items_processed=0
        )

        artist_image_updated = False
        biography_updated = False
        albums_updated = 0

        # Fetch artist image if missing (or if force=True)
        if (force or not artist.image_url) and artist.musicbrainz_id:
            logger.info(f"Attempting to fetch artist image for {artist.name} (MBID: {artist.musicbrainz_id})")
            try:
                from app.services.musicbrainz_images import MusicBrainzImageFetcher
                from app.config import settings
                fetcher = MusicBrainzImageFetcher(fanart_api_key=getattr(settings, 'fanart_api_key', None))
                image_url = fetcher.fetch_artist_image_sync(artist.musicbrainz_id)
                if image_url:
                    artist.image_url = image_url
                    db.commit()
                    artist_image_updated = True
                    logger.info(f"Fetched artist image for {artist.name}: {image_url}")
                else:
                    logger.warning(f"No artist image found for {artist.name} (MBID: {artist.musicbrainz_id})")
            except Exception as e:
                logger.warning(f"Failed to fetch artist image for {artist.name}: {e}")

        # Fetch Wikipedia biography if missing (or if force=True)
        if force or not artist.overview:
            logger.info(f"Attempting to fetch Wikipedia biography for {artist.name}")
            try:
                from app.services.wikipedia import get_wikipedia_service
                wikipedia = get_wikipedia_service()
                biography = wikipedia.fetch_artist_biography(artist.name)
                if biography:
                    artist.overview = biography
                    db.commit()
                    biography_updated = True
                    logger.info(f"Fetched Wikipedia biography for {artist.name} ({len(biography)} chars)")
                else:
                    logger.debug(f"No Wikipedia biography found for {artist.name}")
            except Exception as e:
                logger.warning(f"Failed to fetch Wikipedia biography for {artist.name}: {e}")

        # Fetch genre from MusicBrainz if missing (or if force=True)
        genre_updated = False
        if (force or not artist.genre) and artist.musicbrainz_id:
            try:
                mb_client = get_musicbrainz_client()
                artist_data = mb_client.get_artist(artist.musicbrainz_id)
                if artist_data:
                    mb_genres = artist_data.get("genres") or []
                    if mb_genres:
                        top_genre = sorted(mb_genres, key=lambda g: g.get("count", 0), reverse=True)[0]
                        genre_name = top_genre.get("name")
                        if genre_name:
                            artist.genre = genre_name
                            db.commit()
                            genre_updated = True
                            logger.info(f"Set genre for {artist.name}: {genre_name}")
            except Exception as e:
                logger.warning(f"Failed to fetch genre for {artist.name}: {e}")

        self.update_progress(
            percent=20.0,
            step=f"Fetching album cover art for {artist.name}"
        )
        
        # Get albums missing cover art for this artist (or all albums if force=True)
        MAX_ALBUMS_PER_ARTIST = 500  # Skip mega-artists like "Various Artists"
        album_query = db.query(Album).filter(
            Album.artist_id == artist.id,
            Album.musicbrainz_id.isnot(None)
        )
        if not force:
            album_query = album_query.filter(
                (Album.cover_art_url.is_(None)) | (Album.cover_art_url == '')
            )
        albums = album_query.limit(MAX_ALBUMS_PER_ARTIST).all()

        total_albums_for_artist = db.query(Album).filter(Album.artist_id == artist.id).count()
        total_needing_art = len(albums)

        if total_needing_art == 0:
            self.update_progress(percent=100.0, step=f"No albums need cover art (all {total_albums_for_artist} have it)")
            return {
                "success": True,
                "artist_id": str(artist.id),
                "artist_name": artist.name,
                "artist_image_updated": artist_image_updated,
                "biography_updated": biography_updated,
                "genre_updated": genre_updated,
                "albums_processed": 0,
                "albums_updated": 0
            }

        if total_albums_for_artist > MAX_ALBUMS_PER_ARTIST:
            logger.info(f"Artist {artist.name} has {total_albums_for_artist} albums, capping cover art fetch at {MAX_ALBUMS_PER_ARTIST}")

        # Fetch cover art for albums that don't have it
        mb_client = get_musicbrainz_client()
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 20  # Stop if CAA is down or unreachable

        for idx, album in enumerate(albums):
            progress_percent = 20.0 + (idx / total_needing_art) * 75.0
            self.update_progress(
                percent=progress_percent,
                step=f"Cover art {idx+1}/{total_needing_art}: {album.title}",
                items_processed=idx,
                items_total=total_needing_art
            )

            # Check for cancellation
            if self.check_should_cancel():
                logger.info(f"Metadata refresh cancelled for {artist.name} at album {idx}/{total_needing_art}")
                return {"success": False, "cancelled": True, "processed": idx}

            # Stop if too many consecutive failures (service likely down)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(f"Stopping cover art fetch for {artist.name} after {MAX_CONSECUTIVE_FAILURES} consecutive failures")
                break

            try:
                cover_url = mb_client.get_cover_art_for_release_group(album.musicbrainz_id)
                if cover_url:
                    album.cover_art_url = cover_url
                    albums_updated += 1
                    consecutive_failures = 0
                else:
                    consecutive_failures = 0  # 404 is not a failure, just no art
            except Exception as e:
                consecutive_failures += 1
                logger.warning(f"Failed to fetch cover art for {album.title} ({album.musicbrainz_id}): {e} [consecutive failures: {consecutive_failures}]")

            # Commit every 50 albums to avoid losing all progress on failure
            if (idx + 1) % 50 == 0:
                try:
                    db.commit()
                except Exception:
                    db.rollback()

        db.commit()
        
        self.update_progress(
            percent=100.0,
            step=f"Metadata refresh complete for {artist.name}",
            items_processed=total_needing_art,
            items_total=total_needing_art
        )

        logger.info(f"Metadata refresh complete for {artist.name}: artist_image={artist_image_updated}, biography={biography_updated}, genre={genre_updated}, albums={albums_updated}/{total_needing_art}")

        return {
            "success": True,
            "artist_id": str(artist.id),
            "artist_name": artist.name,
            "artist_image_updated": artist_image_updated,
            "biography_updated": biography_updated,
            "genre_updated": genre_updated,
            "albums_processed": total_needing_art,
            "albums_updated": albums_updated
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to refresh metadata for artist {artist_id}: {e}")
        raise


@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.refresh_all_metadata",
    max_retries=2,
    default_retry_delay=300
)
def refresh_all_metadata(self, job_id: str = None, **kwargs):
    """
    Refresh metadata for ALL artists in the library
    
    This triggers individual metadata refresh tasks for each artist.
    
    Args:
        job_id: Optional job ID for resuming
        **kwargs: Job tracking parameters
        
    Returns:
        dict: Summary of queued tasks
    """
    db = self.db
    
    try:
        # Get all artists (not just monitored)
        artists = db.query(Artist).all()
        total_artists = len(artists)
        
        if total_artists == 0:
            logger.info("No artists to refresh metadata for")
            return {"success": True, "total_artists": 0, "queued": 0}
        
        logger.info(f"Queuing metadata refresh for {total_artists} artists")
        
        self.update_progress(
            percent=10.0,
            step=f"Queuing metadata refresh for {total_artists} artists",
            items_total=total_artists
        )
        
        queued_count = 0
        
        for idx, artist in enumerate(artists):
            try:
                # Queue individual refresh task
                from app.models.job_state import JobType
                refresh_artist_metadata.apply_async(
                    args=[str(artist.id)],
                    kwargs={
                        'job_type': JobType.METADATA_REFRESH,
                        'entity_type': 'artist',
                        'entity_id': str(artist.id)
                    }
                )
                queued_count += 1
                
                # Update progress
                progress_percent = 10.0 + (idx / total_artists) * 85.0
                self.update_progress(
                    percent=progress_percent,
                    step=f"Queued {queued_count}/{total_artists} artists",
                    items_processed=queued_count,
                    items_total=total_artists
                )
                
            except Exception as e:
                logger.error(f"Failed to queue metadata refresh for artist {artist.id}: {e}")
                continue
        
        self.update_progress(
            percent=100.0,
            step=f"Queued {queued_count} metadata refresh tasks",
            items_processed=queued_count,
            items_total=total_artists
        )
        
        logger.info(f"Queued {queued_count} metadata refresh tasks")
        
        return {
            "success": True,
            "total_artists": total_artists,
            "queued": queued_count
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to queue all metadata refresh: {e}")
        raise


@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.sync_all_albums",
    max_retries=1,
    default_retry_delay=300,
    soft_time_limit=43200,
    time_limit=43260
)
def sync_all_albums(self, job_id: str = None, **kwargs):
    """
    Sync albums and tracks for ALL artists in the library.

    Iterates through every artist with a MusicBrainz ID and calls
    sync_artist_albums_standalone to fetch/backfill albums and tracks.
    Uses the local MusicBrainz DB when available (no rate limiting).

    Returns:
        dict: Summary with counts
    """
    db = self.db

    try:
        artists = db.query(Artist).filter(
            Artist.musicbrainz_id.isnot(None),
            Artist.musicbrainz_id != ''
        ).all()
        total_artists = len(artists)

        if total_artists == 0:
            logger.info("No artists with MBIDs to sync")
            return {"success": True, "total_artists": 0, "synced": 0}

        # Skip artists that are known to have massive catalogs in MusicBrainz
        # "Various Artists" has ~280K release groups and would stall the sync
        SKIP_MBIDS = {
            "89ad4ac3-39f7-470e-963a-56509c546377",  # Various Artists
        }
        artists = [a for a in artists if a.musicbrainz_id not in SKIP_MBIDS]
        total_artists = len(artists)

        logger.info(f"Starting full album sync for {total_artists} artists")

        # Initialize job logger for activity page visibility
        job_logger = self.init_job_logger("sync", f"Sync All Albums ({total_artists} artists)")
        job_logger.log_info(f"Starting full album sync for {total_artists} artists")

        self.update_progress(
            percent=5.0,
            step=f"Syncing albums for {total_artists} artists",
            items_total=total_artists
        )

        synced_count = 0
        failed_count = 0
        total_new_albums = 0
        total_tracks_added = 0

        # Heartbeat callback to keep job alive during long per-artist syncs
        def heartbeat(step: str):
            self.update_progress(step=step)

        for idx, artist in enumerate(artists):
            try:
                self.update_progress(
                    percent=5.0 + (idx / total_artists) * 90.0,
                    step=f"Syncing {idx + 1}/{total_artists}: {artist.name}",
                    items_processed=idx,
                    items_total=total_artists
                )

                result = sync_artist_albums_standalone(db, str(artist.id), heartbeat_fn=heartbeat)
                if result and result.get("success"):
                    synced_count += 1
                    new_albums = result.get("new_albums", 0)
                    total_new_albums += new_albums
                    if new_albums > 0:
                        job_logger.log_info(f"  {artist.name}: {new_albums} new albums, {result.get('albums_found', 0)} total")
                else:
                    failed_count += 1
                    job_logger.log_warning(f"  {artist.name}: sync failed - {result.get('error', 'unknown')}")

            except Exception as e:
                logger.warning(f"Failed to sync albums for {artist.name}: {e}")
                db.rollback()
                failed_count += 1
                job_logger.log_warning(f"  {artist.name}: exception - {e}")

        self.update_progress(
            percent=100.0,
            step=f"Synced {synced_count}/{total_artists} artists ({total_new_albums} new albums)",
            items_processed=total_artists,
            items_total=total_artists
        )

        job_logger.log_info(f"\nSync complete: {synced_count} synced, {failed_count} failed, {total_new_albums} new albums")
        logger.info(f"Full album sync complete: {synced_count} synced, {failed_count} failed, {total_new_albums} new albums")

        return {
            "success": True,
            "total_artists": total_artists,
            "synced": synced_count,
            "failed": failed_count,
            "new_albums": total_new_albums
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed full album sync: {e}")
        raise


@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.bulk_resolve_mbid_remote_task",
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=7200,
    time_limit=7500,
)
def bulk_resolve_mbid_remote_task(self, artist_ids: list, job_id: str = None, **kwargs):
    """
    Resolve MBIDs for a list of artists using the remote MusicBrainz API.

    Queries each artist by name, auto-updates if confidence >= 95.
    Respects rate limiting for the remote API.

    Args:
        artist_ids: List of artist UUIDs to resolve
        job_id: Optional job ID for resuming
    """
    db = self.db
    mb_client = get_musicbrainz_client()

    total = len(artist_ids)
    resolved_count = 0
    failed_count = 0
    resolved = []
    unresolved = []

    logger.info(f"Starting remote MBID resolution for {total} artists")

    self.update_progress(
        percent=5.0,
        step=f"Resolving MBIDs for {total} artists via remote API",
        items_total=total,
    )

    for idx, artist_id in enumerate(artist_ids):
        try:
            artist = db.query(Artist).filter(Artist.id == artist_id).first()
            if not artist:
                logger.warning(f"Artist {artist_id} not found, skipping")
                failed_count += 1
                continue

            # Skip if already has MBID
            if artist.musicbrainz_id:
                logger.info(f"Artist '{artist.name}' already has MBID, skipping")
                continue

            # Search via mb_client (local-first, then remote)
            results = mb_client.search_artist(artist.name, limit=3)

            if results and len(results) > 0:
                top = results[0]
                score = top.get("score", 0)

                if score >= 95:
                    mbid = top.get("id")

                    # Check MBID not already in use
                    existing = db.query(Artist).filter(
                        Artist.musicbrainz_id == mbid
                    ).first()

                    if not existing:
                        artist.musicbrainz_id = mbid
                        retry_db_commit(db)
                        resolved_count += 1
                        resolved.append({
                            "id": str(artist.id),
                            "name": artist.name,
                            "mbid": mbid,
                            "score": score,
                        })
                        logger.info(f"Resolved '{artist.name}' -> {mbid} (score: {score})")
                    else:
                        unresolved.append({"id": str(artist.id), "name": artist.name})
                else:
                    unresolved.append({"id": str(artist.id), "name": artist.name})
            else:
                unresolved.append({"id": str(artist.id), "name": artist.name})

        except Exception as e:
            logger.error(f"Error resolving MBID for artist {artist_id}: {e}")
            db.rollback()
            failed_count += 1

        # Update progress
        progress = 5.0 + ((idx + 1) / total) * 90.0
        self.update_progress(
            percent=progress,
            step=f"Resolved {resolved_count}/{idx + 1} artists",
            items_processed=idx + 1,
            items_total=total,
        )

    self.update_progress(
        percent=100.0,
        step=f"Done: {resolved_count} resolved, {len(unresolved)} unresolved, {failed_count} failed",
        items_processed=total,
        items_total=total,
    )

    logger.info(f"Remote MBID resolution complete: {resolved_count} resolved, {len(unresolved)} unresolved, {failed_count} failed")

    return {
        "success": True,
        "resolved_count": resolved_count,
        "unresolved_count": len(unresolved),
        "failed_count": failed_count,
        "resolved": resolved,
        "unresolved": unresolved,
    }


# ---------------------------------------------------------------------------
# Audiobook sync: Author / Book / Chapter
# ---------------------------------------------------------------------------

def should_monitor_book(
    author,
    release_date: date = None,
    book_index: int = 0,
    total_books: int = 0,
    has_local_files: bool = False,
) -> bool:
    """
    Determine if a book should be monitored based on the author's monitor_type strategy.

    Defaults to False — audiobooks are unmonitored unless the author is monitored
    and the monitor_type strategy selects this book.
    """
    if not author.is_monitored:
        return False

    monitor_type = getattr(author, 'monitor_type', MonitorType.NONE.value)

    if monitor_type == MonitorType.ALL_ALBUMS.value:
        return True
    elif monitor_type == MonitorType.NONE.value:
        return False
    elif monitor_type == MonitorType.FUTURE_ONLY.value:
        return bool(release_date and release_date > date.today())
    elif monitor_type == MonitorType.EXISTING_ONLY.value:
        return has_local_files
    elif monitor_type == MonitorType.FIRST_ALBUM.value:
        return book_index == 0
    elif monitor_type == MonitorType.LATEST_ALBUM.value:
        return book_index == total_books - 1 if total_books > 0 else True
    else:
        return False


def _update_author_stats(db: Session, author):
    """Update author book/chapter counts from DB."""
    from sqlalchemy import func
    from app.models.book import Book
    from app.models.chapter import Chapter

    author.book_count = db.query(Book).filter(Book.author_id == author.id).count()
    author.chapter_count = db.query(func.sum(Book.chapter_count)).filter(
        Book.author_id == author.id
    ).scalar() or 0
    # series_count
    from app.models.series import Series
    author.series_count = db.query(Series).filter(Series.author_id == author.id).count()


def sync_author_books_standalone(db: Session, author_id: str, heartbeat_fn=None) -> dict:
    """
    Sync all audiobooks for an author from MusicBrainz (standalone, no task context).

    Mirrors sync_artist_albums_standalone but:
    - Calls mb_client.get_artist_audiobooks() instead of get_artist_albums()
    - Creates Book/Chapter records instead of Album/Track
    - Sets monitored=False by default

    Args:
        db: Database session
        author_id: Author UUID string
        heartbeat_fn: Optional callback called periodically to keep parent task alive.

    Returns:
        dict: Sync summary with counts
    """
    from app.models.author import Author
    from app.models.book import Book, BookStatus
    from app.models.chapter import Chapter
    from app.services.book_importer import import_release_group_as_book

    try:
        author = db.query(Author).filter(Author.id == uuid_lib.UUID(author_id)).first()
        if not author:
            logger.error(f"Author not found: {author_id}")
            return {"success": False, "error": "Author not found"}

        if not author.musicbrainz_id:
            logger.error(f"Author missing MusicBrainz ID: {author_id}")
            return {"success": False, "error": "No MusicBrainz ID"}

        logger.info(f"Syncing audiobooks for author: {author.name}")

        # Fetch author image if not already present
        if not author.image_url and author.musicbrainz_id:
            try:
                from app.services.musicbrainz_images import MusicBrainzImageFetcher
                fetcher = MusicBrainzImageFetcher(fanart_api_key=settings.fanart_api_key)
                image_url = fetcher.fetch_artist_image_sync(author.musicbrainz_id)
                if image_url:
                    author.image_url = image_url
                    db.commit()
                    logger.info(f"Fetched author image for {author.name}")
            except Exception as e:
                logger.warning(f"Failed to fetch author image for {author.name}: {e}")

        # Get audiobooks from MusicBrainz
        mb_client = get_musicbrainz_client()
        release_groups = mb_client.get_artist_audiobooks(author.musicbrainz_id)

        if not release_groups:
            logger.warning(f"No audiobooks found for author: {author.name}")
            author.last_sync_at = datetime.now(timezone.utc)
            db.commit()
            return {"success": True, "books_found": 0, "new_books": 0}

        new_count = 0
        updated_count = 0
        processed_mbids = set()

        for rg_idx, rg in enumerate(release_groups):
            mbid = rg.get("id")
            if not mbid or mbid in processed_mbids:
                continue

            processed_mbids.add(mbid)

            # Send heartbeat every 5 books to prevent stall detection
            if heartbeat_fn and rg_idx % 5 == 0:
                try:
                    heartbeat_fn(f"Syncing book {rg_idx + 1}/{len(release_groups)} for {author.name}")
                except Exception:
                    pass

            # Check if book already exists
            existing = db.query(Book).filter(Book.musicbrainz_id == mbid).first()

            if existing and str(existing.author_id) == str(author.id):
                # Update existing book metadata
                existing.title = rg.get("title", existing.title)
                existing.album_type = rg.get("primary-type", existing.album_type)
                secondary_types_list = rg.get("secondary-types", [])
                existing.secondary_types = ",".join(secondary_types_list) if secondary_types_list else None

                first_release_date = rg.get("first-release-date")
                if first_release_date:
                    parsed = _parse_mb_date(first_release_date)
                    if parsed:
                        existing.release_date = parsed

                existing.updated_at = datetime.now(timezone.utc)

                # Backfill chapters if book has zero chapters
                existing_chapter_count = db.query(Chapter).filter(Chapter.book_id == existing.id).count()
                if existing_chapter_count == 0:
                    try:
                        book_result = import_release_group_as_book(db, author.id, mbid, mb_client)
                        # import_release_group_as_book returns None for existing books
                        # but internally backfills chapters, so we just log
                        if existing_chapter_count == 0:
                            logger.info(f"Attempted chapter backfill for existing book: {existing.title}")
                    except Exception as ch_error:
                        logger.warning(f"Failed to backfill chapters for book {mbid}: {ch_error}")

                updated_count += 1
            elif not existing:
                # Create new book via book_importer
                release_date = _parse_mb_date(rg.get("first-release-date"))
                book_monitored = should_monitor_book(
                    author=author,
                    release_date=release_date,
                    book_index=rg_idx,
                    total_books=len(release_groups),
                    has_local_files=False,
                )

                book = import_release_group_as_book(db, author.id, mbid, mb_client)
                if book:
                    book.monitored = book_monitored
                    new_count += 1

        # Update author stats and sync timestamp
        _update_author_stats(db, author)
        author.last_sync_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            f"Audiobook sync complete for {author.name}: {new_count} new, {updated_count} updated, "
            f"stats: {author.book_count} books, {author.chapter_count} chapters"
        )
        return {
            "success": True,
            "books_found": len(release_groups),
            "new_books": new_count,
            "updated_books": updated_count,
        }

    except Exception as e:
        logger.error(f"Error syncing audiobooks for author {author_id}: {e}")
        db.rollback()
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Rewrite Book File Tags (bulk edit title / author in audio files)
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.rewrite_book_file_tags",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=3600,
    time_limit=7200,
)
def rewrite_book_file_tags(
    self,
    book_id: str,
    new_title: str = None,
    new_author: str = None,
    job_id: str = None,
    **kwargs,
):
    """
    Rewrite artist / album tags in every chapter audio file for a book.

    Writes:
      - album  → new_title  (if provided)
      - artist → new_author (if provided)
      - album_artist → new_author (if provided)
    """
    from app.models.book import Book
    from app.models.chapter import Chapter
    from app.services.metadata_writer import MetadataWriter

    db = self.db

    book = db.query(Book).filter(Book.id == uuid_lib.UUID(book_id)).first()
    if not book:
        logger.error(f"rewrite_book_file_tags: book not found {book_id}")
        return {"success": False, "error": "Book not found"}

    job_logger = self.init_job_logger(
        "metadata_refresh",
        f"Rewrite tags: {new_title or book.title} / {new_author or book.credit_name or ''}"
    )

    chapters = (
        db.query(Chapter)
        .filter(
            Chapter.book_id == book.id,
            Chapter.has_file == True,
            Chapter.file_path.isnot(None),
        )
        .order_by(Chapter.disc_number, Chapter.chapter_number)
        .all()
    )

    total = len(chapters)
    logger.info(f"Rewriting tags for {total} chapters of book {book.title!r}")

    self.update_progress(percent=0.0, step=f"Rewriting tags for {total} chapters", items_total=total)

    success_count = 0
    fail_count = 0

    for idx, chapter in enumerate(chapters):
        if self.check_should_cancel():
            break

        file_path = chapter.file_path
        if not file_path:
            continue

        try:
            result = MetadataWriter.write_metadata(
                file_path=file_path,
                album=new_title,
                artist=new_author,
                album_artist=new_author,
                overwrite=True,
            )
            if result.success:
                success_count += 1
            else:
                fail_count += 1
                logger.warning(f"Failed to write tags to {file_path}: {result.error}")
        except Exception as e:
            fail_count += 1
            logger.warning(f"Exception writing tags to {file_path}: {e}")

        self.update_progress(
            percent=(idx + 1) / total * 100.0,
            step=f"Updated {idx + 1}/{total}: {chapter.title}",
            items_processed=idx + 1,
            items_total=total,
        )

    logger.info(f"Tag rewrite complete for {book.title!r}: {success_count} ok, {fail_count} failed")
    return {"success": True, "book_id": book_id, "updated": success_count, "failed": fail_count}


# ---------------------------------------------------------------------------
# Refresh Author Metadata (image, biography, genre, book covers)
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.refresh_author_metadata",
    max_retries=3,
    default_retry_delay=60
)
def refresh_author_metadata(self, author_id: str, job_id: str = None, force: bool = False, **kwargs):
    """
    Refresh metadata (image, biography, genre, book covers) for a single author.

    Mirrors refresh_artist_metadata but for authors/audiobooks.

    Args:
        author_id: Author UUID
        job_id: Optional job ID for resuming
        force: If True, re-fetch metadata even if fields already have values
        **kwargs: Job tracking parameters

    Returns:
        dict: Summary with counts of updated metadata
    """
    from app.models.author import Author
    from app.models.book import Book

    db = self.db

    try:
        author = db.query(Author).filter(Author.id == uuid_lib.UUID(author_id)).first()
        if not author:
            logger.error(f"Author not found: {author_id}")
            return {"success": False, "error": "Author not found"}

        job_logger = self.init_job_logger("metadata_refresh", f"Metadata refresh: {author.name}")

        logger.info(f"Refreshing metadata for author: {author.name}")

        self.update_progress(
            percent=5.0,
            step=f"Starting metadata refresh for {author.name}",
            items_processed=0
        )

        author_image_updated = False
        biography_updated = False
        genre_updated = False
        books_updated = 0
        image_source = None
        bio_chars = 0
        genre_name = None

        # Fetch author image if missing (or if force=True)
        # Priority: Fanart.tv → MusicBrainz URL relations → Wikipedia photo
        if force or not author.image_url:
            image_url = None

            # Try Fanart.tv / MusicBrainz URL relations first (needs real MBID)
            if author.musicbrainz_id and not author.musicbrainz_id.startswith('local-'):
                logger.info(f"Attempting Fanart.tv/MB image fetch for {author.name} (MBID: {author.musicbrainz_id})")
                try:
                    from app.services.musicbrainz_images import MusicBrainzImageFetcher
                    fetcher = MusicBrainzImageFetcher(fanart_api_key=getattr(settings, 'fanart_api_key', None))
                    image_url = fetcher.fetch_artist_image_sync(author.musicbrainz_id)
                    if image_url:
                        image_source = "fanart.tv"
                except Exception as e:
                    logger.warning(f"Fanart.tv/MB image fetch failed for {author.name}: {e}")

            # Fall back to Wikipedia photo (no MBID required)
            if not image_url:
                logger.info(f"Attempting Wikipedia image fetch for {author.name}")
                try:
                    from app.services.wikipedia import get_wikipedia_service
                    wikipedia_img_url = get_wikipedia_service().fetch_author_image(author.name)
                    if wikipedia_img_url:
                        # Download and store locally so we own the file
                        from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url
                        import asyncio
                        local_path = asyncio.run(
                            fetch_and_save_entity_cover_art_from_url("author", str(author.id), wikipedia_img_url)
                        )
                        image_url = local_path
                        image_source = "wikipedia"
                        logger.info(f"Downloaded Wikipedia photo for {author.name} → {local_path}")
                except Exception as e:
                    logger.warning(f"Wikipedia image fetch/download failed for {author.name}: {e}")

            if image_url:
                author.image_url = image_url
                db.commit()
                author_image_updated = True
                logger.info(f"Author image set for {author.name}: {image_url}")
            else:
                logger.debug(f"No author image found for {author.name}")

        # Fetch Wikipedia biography if missing (or if force=True)
        if force or not author.overview:
            logger.info(f"Attempting to fetch Wikipedia biography for author {author.name}")
            try:
                from app.services.wikipedia import get_wikipedia_service
                wikipedia = get_wikipedia_service()
                biography = wikipedia.fetch_author_biography(author.name)
                if biography:
                    author.overview = biography
                    db.commit()
                    biography_updated = True
                    bio_chars = len(biography)
                    logger.info(f"Fetched Wikipedia biography for author {author.name} ({bio_chars} chars)")
                else:
                    logger.debug(f"No Wikipedia biography found for author {author.name}")
            except Exception as e:
                logger.warning(f"Failed to fetch Wikipedia biography for author {author.name}: {e}")

        # Fetch genre from MusicBrainz if missing (or if force=True)
        if (force or not author.genre) and author.musicbrainz_id:
            try:
                mb_client = get_musicbrainz_client()
                author_data = mb_client.get_artist(author.musicbrainz_id)
                if author_data:
                    mb_genres = author_data.get("genres") or []
                    if mb_genres:
                        top_genre = sorted(mb_genres, key=lambda g: g.get("count", 0), reverse=True)[0]
                        genre_name = top_genre.get("name")
                        if genre_name:
                            author.genre = genre_name
                            db.commit()
                            genre_updated = True
                            genre_name = genre_name  # capture for result_data
                            logger.info(f"Set genre for author {author.name}: {genre_name}")
            except Exception as e:
                logger.warning(f"Failed to fetch genre for author {author.name}: {e}")

        self.update_progress(
            percent=20.0,
            step=f"Fetching book cover art for {author.name}"
        )

        books_found = []
        books_not_found = []

        # ── Step 1: local directory scan (all books, highest priority) ────────
        # Check the book's audio directory for extracted cover images before
        # hitting any external API.
        COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png",
                       "folder.jpg", "folder.jpeg", "folder.png",
                       "front.jpg", "front.jpeg", "front.png")
        ART_DIR = Path("/docker/studio54/book-art")
        ART_DIR.mkdir(parents=True, exist_ok=True)

        from app.models.chapter import Chapter as ChapterModel

        MAX_BOOKS_PER_AUTHOR = 500
        all_books_query = db.query(Book).filter(Book.author_id == author.id)
        if not force:
            all_books_query = all_books_query.filter(
                (Book.cover_art_url.is_(None)) | (Book.cover_art_url == '')
            )
        all_books = all_books_query.limit(MAX_BOOKS_PER_AUTHOR).all()

        local_scan_updated = 0
        for book in all_books:
            # Get any chapter with a file path to find the directory
            chapter = (
                db.query(ChapterModel)
                .filter(ChapterModel.book_id == book.id, ChapterModel.file_path.isnot(None))
                .first()
            )
            if not chapter or not chapter.file_path:
                continue
            book_dir = Path(chapter.file_path).parent
            for name in COVER_NAMES:
                candidate = book_dir / name
                if candidate.is_file():
                    try:
                        dest = ART_DIR / f"{book.id}{candidate.suffix.lower()}"
                        shutil.copy2(str(candidate), str(dest))
                        book.cover_art_url = str(dest)
                        local_scan_updated += 1
                        books_found.append({"id": str(book.id), "title": book.title, "source": "local"})
                        logger.info(f"[LocalScan] Cover art found for '{book.title}': {candidate}")
                    except Exception as e:
                        logger.warning(f"[LocalScan] Failed to copy cover for '{book.title}': {e}")
                    break  # first match wins

        if local_scan_updated:
            try:
                db.commit()
            except Exception:
                db.rollback()

        books_updated += local_scan_updated
        logger.info(f"[LocalScan] {local_scan_updated} book covers found in local directories")

        # ── Step 2: Cover Art Archive (real MusicBrainz IDs) ──────────────────
        book_query = db.query(Book).filter(
            Book.author_id == author.id,
            Book.musicbrainz_id.isnot(None),
            ~Book.musicbrainz_id.like('local-%'),
            (Book.cover_art_url.is_(None)) | (Book.cover_art_url == '')  # skip books found in local scan
        )
        books = book_query.limit(MAX_BOOKS_PER_AUTHOR).all()

        total_books_for_author = db.query(Book).filter(Book.author_id == author.id).count()
        total_needing_art = len(books)

        if total_needing_art == 0:
            self.update_progress(percent=50.0, step=f"Checking OpenLibrary for remaining books")

        mb_client = get_musicbrainz_client()
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 20

        for idx, book in enumerate(books):
            progress_percent = 20.0 + (idx / total_needing_art) * 75.0
            self.update_progress(
                percent=progress_percent,
                step=f"Cover art {idx+1}/{total_needing_art}: {book.title}",
                items_processed=idx,
                items_total=total_needing_art
            )

            if self.check_should_cancel():
                logger.info(f"Metadata refresh cancelled for author {author.name} at book {idx}/{total_needing_art}")
                return {"success": False, "cancelled": True, "processed": idx}

            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(f"Stopping cover art fetch for author {author.name} after {MAX_CONSECUTIVE_FAILURES} consecutive failures")
                break

            had_art = bool(book.cover_art_url)
            try:
                cover_url = mb_client.get_cover_art_for_release_group(book.musicbrainz_id)
                if cover_url:
                    book.cover_art_url = cover_url
                    books_updated += 1
                    consecutive_failures = 0
                    books_found.append({"id": str(book.id), "title": book.title})
                else:
                    consecutive_failures = 0
                    if not had_art:
                        books_not_found.append({"id": str(book.id), "title": book.title})
            except Exception as e:
                consecutive_failures += 1
                if not had_art:
                    books_not_found.append({"id": str(book.id), "title": book.title})
                logger.warning(f"Failed to fetch cover art for book {book.title} ({book.musicbrainz_id}): {e} [consecutive failures: {consecutive_failures}]")

            if (idx + 1) % 50 == 0:
                try:
                    db.commit()
                except Exception:
                    db.rollback()

        db.commit()

        # ── Step 3: OpenLibrary fallback (local MBIDs only, still missing art) ─
        local_books_query = db.query(Book).filter(
            Book.author_id == author.id,
            Book.musicbrainz_id.like('local-%'),
            (Book.cover_art_url.is_(None)) | (Book.cover_art_url == '')  # skip books found in local scan
        )
        local_books = local_books_query.limit(MAX_BOOKS_PER_AUTHOR).all()

        if local_books:
            from app.services.openlibrary import get_openlibrary_service
            from app.services.cover_art_service import fetch_and_save_entity_cover_art_from_url
            import asyncio
            ol = get_openlibrary_service()
            total_local = len(local_books)

            self.update_progress(
                percent=95.0,
                step=f"Checking OpenLibrary for {total_local} book(s) without MusicBrainz IDs"
            )

            for idx, book in enumerate(local_books):
                had_art = bool(book.cover_art_url)
                try:
                    cover_url = ol.fetch_book_cover_url(book.title, author_name=author.name)
                    if cover_url:
                        local_path = asyncio.run(
                            fetch_and_save_entity_cover_art_from_url("book", str(book.id), cover_url)
                        )
                        if local_path:
                            book.cover_art_url = local_path
                            books_updated += 1
                            books_found.append({"id": str(book.id), "title": book.title, "source": "openlibrary"})
                            logger.info(f"[OpenLibrary] Cover art saved for '{book.title}': {local_path}")
                        else:
                            if not had_art:
                                books_not_found.append({"id": str(book.id), "title": book.title})
                    else:
                        if not had_art:
                            books_not_found.append({"id": str(book.id), "title": book.title})
                except Exception as e:
                    logger.warning(f"[OpenLibrary] Failed for '{book.title}': {e}")
                    if not had_art:
                        books_not_found.append({"id": str(book.id), "title": book.title})

            try:
                db.commit()
            except Exception:
                db.rollback()

        total_processed = total_needing_art + len(local_books) if local_books else total_needing_art

        self.update_progress(
            percent=100.0,
            step=f"Metadata refresh complete for {author.name}",
            items_processed=total_processed,
            items_total=total_processed
        )

        logger.info(f"Metadata refresh complete for author {author.name}: image={author_image_updated}, biography={biography_updated}, genre={genre_updated}, books={books_updated}/{total_processed}")

        return {
            "success": True,
            "author_id": str(author.id),
            "author_name": author.name,
            "author_image_updated": author_image_updated,
            "image_source": image_source,
            "biography_updated": biography_updated,
            "bio_chars": bio_chars,
            "genre_updated": genre_updated,
            "genre_name": genre_name,
            "books_processed": total_processed,
            "books_updated": books_updated,
            "books_found": books_found,
            "books_not_found": books_not_found
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to refresh metadata for author {author_id}: {e}")
        raise


@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.refresh_all_author_metadata",
    max_retries=2,
    default_retry_delay=300
)
def refresh_all_author_metadata(self, force: bool = False, job_id: str = None, **kwargs):
    """
    Refresh metadata (image, biography, genre, book covers) for ALL authors in the library.

    Queues individual refresh_author_metadata tasks for every author.
    """
    from app.models.author import Author

    db = self.db

    try:
        authors = db.query(Author).all()
        total = len(authors)

        if total == 0:
            logger.info("No authors to refresh metadata for")
            return {"success": True, "total_authors": 0, "queued": 0}

        logger.info(f"Queuing metadata refresh for {total} authors")

        self.update_progress(
            percent=10.0,
            step=f"Queuing metadata refresh for {total} authors",
            items_total=total
        )

        queued = 0
        for idx, author in enumerate(authors):
            try:
                from app.models.job_state import JobType
                refresh_author_metadata.apply_async(
                    args=[str(author.id)],
                    kwargs={
                        'force': force,
                        'job_type': JobType.METADATA_REFRESH,
                        'entity_type': 'author',
                        'entity_id': str(author.id)
                    }
                )
                queued += 1
            except Exception as e:
                logger.error(f"Failed to queue metadata refresh for author {author.id}: {e}")
                continue

            self.update_progress(
                percent=10.0 + (idx / total) * 85.0,
                step=f"Queued {queued}/{total} authors",
                items_processed=queued,
                items_total=total
            )

        self.update_progress(
            percent=100.0,
            step=f"Queued {queued} author metadata refresh tasks",
            items_processed=queued,
            items_total=total
        )

        logger.info(f"Queued {queued}/{total} author metadata refresh tasks")
        return {"success": True, "total_authors": total, "queued": queued}

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to queue all author metadata refresh: {e}")
        raise


# ---------------------------------------------------------------------------
# Detect Series (MusicBrainz + File Metadata)
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.detect_author_series",
    max_retries=2,
    default_retry_delay=30
)
def detect_author_series(self, author_id: str, job_id: str = None, **kwargs):
    """
    Detect and create series for a single author.

    Phase 1: Query local MusicBrainz DB for series relationships (best coverage).
    Phase 2: Fall back to file metadata tags (catches anything MB missed).

    Args:
        author_id: Author UUID
        job_id: Optional job ID for tracking
        **kwargs: Job tracking parameters

    Returns:
        dict: Summary with series_created and books_linked counts
    """
    from app.models.author import Author
    from app.services.book_from_metadata import detect_and_create_series, detect_series_from_musicbrainz, detect_series_from_paths
    from app.tasks.playlist_tasks import create_series_playlist_task

    db = self.db

    try:
        author = db.query(Author).filter(Author.id == uuid_lib.UUID(author_id)).first()
        if not author:
            logger.error(f"Author not found: {author_id}")
            return {"success": False, "error": "Author not found"}

        job_logger = self.init_job_logger("series_detection", f"Series detection: {author.name}")

        logger.info(f"Detecting series for author: {author.name}")

        self.update_progress(
            percent=10.0,
            step=f"Checking MusicBrainz for series by {author.name}",
            items_processed=0
        )

        # Phase 1: MusicBrainz local DB (best source for known series)
        mb_stats = detect_series_from_musicbrainz(db, author.id)

        self.update_progress(
            percent=33.0,
            step=f"Checking file metadata for series by {author.name}",
            items_processed=mb_stats.get('series_created', 0) + mb_stats.get('books_linked', 0)
        )

        # Phase 2: File metadata fallback (catches anything MB missed;
        # detect_and_create_series already skips books with existing series assignment)
        file_stats = detect_and_create_series(db, author.id)

        self.update_progress(
            percent=66.0,
            step=f"Checking directory names for series by {author.name}",
            items_processed=(
                mb_stats.get('series_created', 0) + mb_stats.get('books_linked', 0) +
                file_stats.get('series_created', 0) + file_stats.get('books_linked', 0)
            )
        )

        # Phase 3: Path-based detection (parses series info from directory names)
        path_stats = detect_series_from_paths(db, author.id)

        # Merge stats from all phases
        total_series_created = (
            mb_stats.get('series_created', 0) +
            file_stats.get('series_created', 0) +
            path_stats.get('series_created', 0)
        )
        total_books_linked = (
            mb_stats.get('books_linked', 0) +
            file_stats.get('books_linked', 0) +
            path_stats.get('books_linked', 0)
        )
        all_new_series_ids = (
            mb_stats.get('new_series_ids', []) +
            file_stats.get('new_series_ids', []) +
            path_stats.get('new_series_ids', [])
        )

        # Update author stats (series_count etc.)
        _update_author_stats(db, author)
        db.commit()

        # Dispatch playlist creation for all newly created series
        for sid in all_new_series_ids:
            create_series_playlist_task.delay(str(sid))
            logger.info(f"Dispatched series playlist creation for series {sid}")

        self.update_progress(
            percent=100.0,
            step=f"Series detection complete for {author.name}",
            items_processed=total_series_created + total_books_linked
        )

        logger.info(
            f"Series detection complete for {author.name}: "
            f"{total_series_created} series created, {total_books_linked} books linked "
            f"(MB: {mb_stats.get('series_created', 0)}/{mb_stats.get('books_linked', 0)}, "
            f"file: {file_stats.get('series_created', 0)}/{file_stats.get('books_linked', 0)}, "
            f"path: {path_stats.get('series_created', 0)}/{path_stats.get('books_linked', 0)})"
        )

        return {
            "success": True,
            "author_id": str(author.id),
            "author_name": author.name,
            "series_created": total_series_created,
            "books_linked": total_books_linked,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to detect series for author {author_id}: {e}")
        raise


# ---------------------------------------------------------------------------
# Import Unlinked Artists (async Celery task)
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="app.tasks.sync_tasks.import_unlinked_artists_task",
    max_retries=0,
    soft_time_limit=7200,
    time_limit=7500,
)
def import_unlinked_artists_task(self, library_path_id=None, is_monitored=False, auto_sync=True, **kwargs):
    """
    Import artists from library files that have MBIDs but no matching track in the DB.

    Finds files with Recording MBIDs that couldn't be linked (artist not in DB),
    extracts unique Artist MBIDs, creates Artist records, and queues album sync.
    """
    from app.models.library import LibraryFile
    from sqlalchemy import distinct

    db = self.db
    mb_client = get_musicbrainz_client()

    self.update_progress(
        percent=5.0,
        step="Finding unlinked artist MBIDs...",
    )

    # Find files with Recording MBID that have NO matching track in the DB
    unlinked_query = db.query(
        distinct(LibraryFile.musicbrainz_artistid).label('artist_mbid')
    ).filter(
        LibraryFile.musicbrainz_trackid.isnot(None),
        LibraryFile.musicbrainz_artistid.isnot(None),
        ~LibraryFile.musicbrainz_trackid.in_(
            db.query(Track.musicbrainz_id).filter(Track.musicbrainz_id.isnot(None))
        )
    )

    if library_path_id:
        unlinked_query = unlinked_query.filter(
            LibraryFile.library_path_id == library_path_id
        )

    artist_mbids = [row.artist_mbid for row in unlinked_query.all() if row.artist_mbid]

    if not artist_mbids:
        self.update_progress(percent=100.0, step="No unlinked artists found")
        return {
            "success": True,
            "imported_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "message": "No unlinked artists found",
        }

    # Filter out artist MBIDs that already exist
    existing_mbids = {
        row[0] for row in
        db.query(Artist.musicbrainz_id).filter(
            Artist.musicbrainz_id.in_(artist_mbids)
        ).all()
    }

    new_mbids = [mbid for mbid in artist_mbids if mbid not in existing_mbids]
    skipped_count = len(artist_mbids) - len(new_mbids)

    if not new_mbids:
        self.update_progress(percent=100.0, step=f"All {skipped_count} artists already exist")
        return {
            "success": True,
            "imported_count": 0,
            "skipped_count": skipped_count,
            "failed_count": 0,
            "message": f"All {skipped_count} artists already exist in library",
        }

    total = len(new_mbids)
    imported_count = 0
    failed_count = 0

    self.update_progress(
        percent=10.0,
        step=f"Importing {total} new artists (skipping {skipped_count} existing)...",
        items_total=total,
    )

    logger.info(f"Import unlinked: {total} new artist MBIDs to import, {skipped_count} already exist")

    for idx, mbid in enumerate(new_mbids):
        try:
            artist_info = mb_client.get_artist(mbid)
            if not artist_info:
                logger.warning(f"Could not find artist with MBID {mbid} on MusicBrainz")
                failed_count += 1
                continue

            artist_name = artist_info.get("name", f"Unknown ({mbid})")

            artist = Artist(
                name=artist_name,
                musicbrainz_id=mbid,
                is_monitored=is_monitored,
                import_source="studio54",
                studio54_library_path_id=library_path_id,
                added_at=datetime.now(timezone.utc)
            )

            db.add(artist)
            retry_db_commit(db)
            db.refresh(artist)

            # Queue album sync
            if auto_sync:
                try:
                    sync_artist_albums.delay(str(artist.id))
                except Exception as e:
                    logger.warning(f"Failed to queue album sync for {artist_name}: {e}")

            imported_count += 1
            logger.info(f"Imported unlinked artist '{artist_name}' (MBID: {mbid})")

        except Exception as e:
            db.rollback()
            error_str = str(e).lower()
            if "duplicate key" in error_str or "unique constraint" in error_str:
                logger.info(f"Artist MBID {mbid} already exists (race condition), skipping")
                skipped_count += 1
            else:
                logger.error(f"Failed to import artist MBID {mbid}: {e}")
                failed_count += 1

        # Update progress
        progress = 10.0 + ((idx + 1) / total) * 85.0
        self.update_progress(
            percent=progress,
            step=f"Imported {imported_count}/{idx + 1} artists",
            items_processed=idx + 1,
            items_total=total,
        )

    self.update_progress(
        percent=100.0,
        step=f"Done: {imported_count} imported, {skipped_count} skipped, {failed_count} failed",
        items_processed=total,
        items_total=total,
    )

    message = f"Imported {imported_count} new artists, skipped {skipped_count}, failed {failed_count}"
    logger.info(f"Import unlinked artists complete: {message}")

    return {
        "success": True,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Celery task wrapper for author book sync (called from API)
# ---------------------------------------------------------------------------
@celery_app.task(
    bind=True,
    name="app.tasks.sync_tasks.sync_author_books",
    max_retries=2,
    default_retry_delay=60,
)
def sync_author_books(self, author_id: str, **kwargs):
    """Celery task wrapper for sync_author_books_standalone."""
    db = SessionLocal()
    try:
        result = sync_author_books_standalone(db, author_id)
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"sync_author_books task failed for {author_id}: {e}")
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()
