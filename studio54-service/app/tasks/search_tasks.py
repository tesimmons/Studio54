"""
Search Tasks - Automatic album searching with decision engine

Celery tasks for automatic album searching using the new
Lidarr-style decision engine and download pipeline.
"""
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

import redis
from celery import shared_task

from app.config import settings
from app.database import SessionLocal
from app.models import Album, Artist
from app.models.album import AlbumStatus
from app.models.download_decision import (
    TrackedDownload,
    TrackedDownloadState,
    DownloadHistory,
    DownloadEventType,
)
from app.services.search.album_search_service import AlbumSearchService, SearchService
from app.services.download.process_decisions import ProcessDownloadDecisions
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Redis client for search deduplication locks
_redis_client = None

SEARCH_LOCK_TTL = 300  # 5 minutes max search duration


def _get_redis():
    """Get or create Redis client for search locks"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url)
    return _redis_client


def _acquire_search_lock(album_id: str, task_id: str = "") -> bool:
    """
    Acquire a distributed lock for album search.

    Returns True if lock acquired, False if search already in-flight.
    """
    r = _get_redis()
    key = f"search:album:{album_id}"
    value = f"{task_id}:{time.time()}"
    acquired = r.set(key, value, nx=True, ex=SEARCH_LOCK_TTL)
    if not acquired:
        existing = r.get(key)
        logger.info(
            f"Search already in-flight for album {album_id} (lock: {existing})"
        )
    return bool(acquired)


def _release_search_lock(album_id: str):
    """Release the search lock for an album"""
    r = _get_redis()
    key = f"search:album:{album_id}"
    r.delete(key)


def get_db():
    """Get database session"""
    return SessionLocal()


@celery_app.task(name="app.tasks.search_tasks.search_album_with_decision_engine")
def search_album_with_decision_engine(
    album_id: str,
    auto_grab: bool = True
) -> Dict[str, Any]:
    """
    Search for an album using the decision engine

    Uses the new Lidarr-style decision engine to evaluate releases
    and optionally auto-grab the best result.

    Args:
        album_id: UUID of the album to search
        auto_grab: If True, automatically grab approved releases

    Returns:
        Dict with search results and grab status
    """
    # Acquire distributed lock to prevent concurrent searches
    task_id = search_album_with_decision_engine.request.id or ""
    if not _acquire_search_lock(album_id, task_id):
        return {
            "success": False,
            "error": "Search already in-flight for this album",
            "album_id": album_id,
            "skipped": True,
        }

    db = get_db()
    try:
        search_service = AlbumSearchService(db)
        process_service = ProcessDownloadDecisions(db)

        # Get album
        album = db.query(Album).filter(Album.id == album_id).first()
        if not album:
            return {"success": False, "error": f"Album {album_id} not found"}

        logger.info(f"Searching for album: {album.artist.name} - {album.title}")

        # Update album status
        album.status = AlbumStatus.SEARCHING
        db.commit()

        # Perform search
        result = search_service.search_album_sync(album_id)

        if not result.get("decisions"):
            album.status = AlbumStatus.WANTED
            db.commit()
            return {
                "success": False,
                "error": "No results found",
                "album_id": album_id,
                "total_results": 0
            }

        decisions = result.get("decisions", [])
        approved = [d for d in decisions if d.approved]

        if not approved:
            album.status = AlbumStatus.WANTED
            db.commit()
            return {
                "success": False,
                "error": "No approved releases found",
                "album_id": album_id,
                "total_results": len(decisions),
                "approved_count": 0,
                "rejections": [
                    {
                        "title": d.remote_album.release_info.title,
                        "reasons": d.rejection_reasons
                    }
                    for d in decisions[:5]  # Top 5 rejections
                ]
            }

        if auto_grab:
            # Process approved decisions
            submission_result = process_service.process(decisions, auto_grab=True)

            if submission_result.grabbed > 0:
                album.status = AlbumStatus.DOWNLOADING
                db.commit()

                return {
                    "success": True,
                    "album_id": album_id,
                    "total_results": len(decisions),
                    "approved_count": len(approved),
                    "grabbed": submission_result.grabbed,
                    "pending": submission_result.pending,
                    "rejected": submission_result.rejected,
                    "grabbed_items": submission_result.grabbed_items
                }

        # Not auto-grabbing or no successful grabs
        album.status = AlbumStatus.WANTED
        db.commit()

        return {
            "success": len(approved) > 0,
            "album_id": album_id,
            "total_results": len(decisions),
            "approved_count": len(approved),
            "auto_grab": auto_grab,
            "decisions": [d.to_dict() for d in decisions[:10]]  # Top 10
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Search failed for album {album_id}: {e}")
        return {"success": False, "error": str(e), "album_id": album_id}
    finally:
        _release_search_lock(album_id)
        db.close()


@celery_app.task(name="app.tasks.search_tasks.search_wanted_albums_v2")
def search_wanted_albums_v2(limit: int = 10) -> Dict[str, Any]:
    """
    Search for wanted albums using decision engine

    Improved version that uses the decision engine for smarter
    release selection and respects search intervals.

    Args:
        limit: Maximum number of albums to search

    Returns:
        Dict with search summary
    """
    db = get_db()
    try:
        search_service = SearchService(db)

        # Get wanted albums that haven't been searched recently
        min_search_interval = timedelta(hours=6)
        cutoff_time = datetime.now(timezone.utc) - min_search_interval

        wanted = db.query(Album).join(Artist).filter(
            Album.monitored == True,
            Artist.is_monitored == True,
            Album.status == AlbumStatus.WANTED
        ).filter(
            # Not searched recently or never searched
            (Album.last_search_time == None) |
            (Album.last_search_time < cutoff_time)
        ).order_by(
            Album.added_at.asc()  # Oldest first
        ).limit(limit).all()

        if not wanted:
            return {
                "success": True,
                "albums_searched": 0,
                "message": "No wanted albums due for search"
            }

        logger.info(f"Searching {len(wanted)} wanted albums")

        total_grabbed = 0
        searched = 0
        errors = []

        for album in wanted:
            try:
                # Call search directly (NOT as a subtask) to avoid
                # blocking the worker pool with .get() — see Celery docs:
                # "Never call result.get() within a task"
                result = search_album_with_decision_engine(
                    str(album.id), auto_grab=True
                )

                searched += 1
                total_grabbed += result.get("grabbed", 0)

                if result.get("grabbed", 0) > 0:
                    logger.info(
                        f"Grabbed {result['grabbed']} releases for "
                        f"{album.artist.name} - {album.title}"
                    )

            except Exception as e:
                error_msg = f"Failed to search {album.title}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        return {
            "success": True,
            "albums_searched": searched,
            "total_grabbed": total_grabbed,
            "errors": errors[:5] if errors else []
        }

    except Exception as e:
        logger.error(f"Wanted albums search failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.search_tasks.monitor_tracked_downloads")
def monitor_tracked_downloads() -> Dict[str, Any]:
    """
    Monitor tracked downloads and update their status

    Checks SABnzbd for download progress on all TrackedDownload records.
    Triggers import when downloads complete.

    Returns:
        Dict with monitoring summary
    """
    db = get_db()
    try:
        from app.services.download.download_client_provider import DownloadClientProvider
        from app.services.encryption import get_encryption_service
        from app.services.sabnzbd_client import SABnzbdClient
        from app.models import DownloadClient

        # Get active tracked downloads
        active = db.query(TrackedDownload).filter(
            TrackedDownload.state.in_([
                TrackedDownloadState.QUEUED,
                TrackedDownloadState.DOWNLOADING,
                TrackedDownloadState.PAUSED,
            ])
        ).all()

        if not active:
            return {"active_downloads": 0, "updated": 0}

        logger.debug(f"Monitoring {len(active)} tracked downloads")

        encryption_service = get_encryption_service()
        updated_count = 0
        completed_count = 0
        failed_count = 0

        # Group by download client
        by_client = {}
        for tracked in active:
            client_id = str(tracked.download_client_id)
            by_client.setdefault(client_id, []).append(tracked)

        for client_id, downloads in by_client.items():
            try:
                # Get download client
                client_model = db.query(DownloadClient).filter(
                    DownloadClient.id == client_id
                ).first()

                if not client_model:
                    continue

                # Build SABnzbd client
                api_key = encryption_service.decrypt(client_model.api_key_encrypted)
                client = SABnzbdClient(client_model.base_url, api_key)

                # Get queue and history from SABnzbd
                queue_items = client.get_queue()
                history_items = client.get_history(limit=100)

                for tracked in downloads:
                    # Check in queue first
                    queue_item = next(
                        (q for q in queue_items if q.get('nzo_id') == tracked.download_id),
                        None
                    )

                    if queue_item:
                        # Update progress
                        tracked.progress_percent = queue_item.get('percentage', 0)
                        tracked.updated_at = datetime.now(timezone.utc)

                        status = queue_item.get('status', '').lower()
                        if 'downloading' in status:
                            tracked.state = TrackedDownloadState.DOWNLOADING
                        elif 'paused' in status:
                            tracked.state = TrackedDownloadState.PAUSED

                        updated_count += 1
                        continue

                    # Check in history (completed or failed)
                    history_item = next(
                        (h for h in history_items if h.get('nzo_id') == tracked.download_id),
                        None
                    )

                    if history_item:
                        tracked.completed_at = datetime.now(timezone.utc)
                        tracked.output_path = history_item.get('download_path')

                        if history_item.get('status', '').lower() == 'completed':
                            tracked.state = TrackedDownloadState.IMPORT_PENDING
                            tracked.progress_percent = 100

                            # Record completion in history
                            history_record = DownloadHistory(
                                album_id=tracked.album_id,
                                artist_id=tracked.artist_id,
                                release_guid=tracked.release_guid,
                                release_title=tracked.title,
                                event_type=DownloadEventType.IMPORT_STARTED,
                                quality=tracked.release_quality,
                                source=tracked.release_indexer
                            )
                            db.add(history_record)

                            completed_count += 1

                            # Trigger import (placeholder - actual import service would go here)
                            logger.info(
                                f"Download complete, ready for import: {tracked.title}"
                            )

                        else:
                            tracked.state = TrackedDownloadState.FAILED
                            tracked.error_message = history_item.get('fail_message', 'Download failed')
                            failed_count += 1

                            # Record failure in history
                            history_record = DownloadHistory(
                                album_id=tracked.album_id,
                                artist_id=tracked.artist_id,
                                release_guid=tracked.release_guid,
                                release_title=tracked.title,
                                event_type=DownloadEventType.DOWNLOAD_FAILED,
                                quality=tracked.release_quality,
                                source=tracked.release_indexer,
                                message=tracked.error_message
                            )
                            db.add(history_record)

                        updated_count += 1

            except Exception as e:
                logger.error(f"Error monitoring client {client_id}: {e}")
                continue

        db.commit()

        return {
            "active_downloads": len(active),
            "updated": updated_count,
            "completed": completed_count,
            "failed": failed_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Download monitoring failed: {e}")
        return {"error": str(e)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.search_tasks.search_wanted_albums_for_artist")
def search_wanted_albums_for_artist(artist_id: str) -> Dict[str, Any]:
    """
    Search for all wanted, monitored albums for a specific artist

    Used when adding an artist with "search for missing" enabled,
    or when manually triggering "Search Missing" on an artist.

    Args:
        artist_id: UUID of the artist

    Returns:
        Dict with search summary
    """
    db = get_db()
    try:
        artist = db.query(Artist).filter(Artist.id == artist_id).first()
        if not artist:
            return {"success": False, "error": f"Artist {artist_id} not found"}

        # Get wanted, monitored albums for this artist
        wanted = db.query(Album).filter(
            Album.artist_id == artist_id,
            Album.monitored == True,
            Album.status == AlbumStatus.WANTED
        ).order_by(Album.release_date.asc().nullslast()).all()

        if not wanted:
            return {
                "success": True,
                "artist_id": artist_id,
                "artist_name": artist.name,
                "albums_searched": 0,
                "message": "No wanted albums to search"
            }

        logger.info(f"Searching {len(wanted)} wanted albums for {artist.name}")

        total_grabbed = 0
        searched = 0
        errors = []

        for album in wanted:
            try:
                result = search_album_with_decision_engine(
                    str(album.id), auto_grab=True
                )

                searched += 1
                total_grabbed += result.get("grabbed", 0)

                if result.get("grabbed", 0) > 0:
                    logger.info(
                        f"Grabbed {result['grabbed']} releases for "
                        f"{artist.name} - {album.title}"
                    )

            except Exception as e:
                error_msg = f"Failed to search {album.title}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        return {
            "success": True,
            "artist_id": artist_id,
            "artist_name": artist.name,
            "albums_searched": searched,
            "total_grabbed": total_grabbed,
            "errors": errors[:5] if errors else []
        }

    except Exception as e:
        logger.error(f"Search for artist {artist_id} failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.search_tasks.search_cutoff_unmet")
def search_cutoff_unmet(limit: int = 5) -> Dict[str, Any]:
    """
    Search for quality upgrades on existing albums

    Searches for albums where the current quality is below
    the cutoff defined in the quality profile.

    Args:
        limit: Maximum albums to search

    Returns:
        Dict with search summary
    """
    db = get_db()
    try:
        # Get albums below cutoff
        unmet = db.query(Album).join(Artist).filter(
            Album.monitored == True,
            Artist.is_monitored == True,
            Album.status == AlbumStatus.DOWNLOADED,
            Album.quality_meets_cutoff == False
        ).limit(limit).all()

        if not unmet:
            return {
                "success": True,
                "albums_searched": 0,
                "message": "No albums below quality cutoff"
            }

        logger.info(f"Searching {len(unmet)} albums for quality upgrades")

        upgraded = 0
        for album in unmet:
            try:
                result = search_album_with_decision_engine(
                    str(album.id), auto_grab=True
                )

                if result.get("grabbed", 0) > 0:
                    upgraded += 1
                    logger.info(f"Upgrade grabbed for: {album.artist.name} - {album.title}")

            except Exception as e:
                logger.error(f"Failed to search upgrade for {album.title}: {e}")

        return {
            "success": True,
            "albums_searched": len(unmet),
            "upgraded": upgraded
        }

    except Exception as e:
        logger.error(f"Cutoff unmet search failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()
