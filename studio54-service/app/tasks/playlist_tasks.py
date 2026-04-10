"""
Playlist Tasks - Celery tasks for book playlist creation
"""
import logging

from app.tasks.celery_app import celery_app
from app.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="create_series_playlist", bind=True, max_retries=2)
def create_series_playlist_task(self, series_id: str):
    """Create or update a series playlist with ordered chapters."""
    db = SessionLocal()
    try:
        from app.services.book_playlist_service import create_or_update_series_playlist
        playlist = create_or_update_series_playlist(db, series_id)
        db.commit()

        if playlist:
            logger.info(f"Created/updated series playlist: {playlist.name} ({len(playlist.entries)} chapters)")
            return {"status": "success", "playlist_id": str(playlist.id), "chapter_count": len(playlist.entries)}
        else:
            logger.info(f"No playlist created for series {series_id} (no eligible chapters)")
            return {"status": "skipped", "reason": "no eligible chapters"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create series playlist for {series_id}: {e}")
        raise self.retry(exc=e, countdown=30)
    finally:
        db.close()
