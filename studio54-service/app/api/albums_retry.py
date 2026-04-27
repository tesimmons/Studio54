"""
Album retry control and download history API endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import logging

from app.database import get_db
from app.auth import require_dj_or_above
from app.models.user import User
from app.models.album import Album
from app.models.download_decision import DownloadHistory
from app.security import validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


class RetryControlRequest(BaseModel):
    retry_enabled: bool
    search_now: bool = False


@router.post("/albums/{album_id}/retry-control")
async def retry_control(
    album_id: str,
    body: RetryControlRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    validate_uuid(album_id, "Album ID")
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    album.retry_enabled = body.retry_enabled

    if not body.retry_enabled:
        album.next_retry_at = None
    elif body.search_now:
        album.next_retry_at = None  # search_now fires immediately — no scheduled delay needed
    elif album.next_retry_at is None:
        # Re-enabling with no pending retry → schedule 1h from now
        album.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)

    db.commit()

    if body.search_now and body.retry_enabled:
        try:
            from app.tasks.download_tasks import search_album
            from app.models.job_state import JobType
            search_album.apply_async(
                args=[album_id],
                kwargs={
                    'job_type': JobType.ALBUM_SEARCH,
                    'entity_type': 'album',
                    'entity_id': album_id,
                },
            )
        except Exception as e:
            logger.warning(f"search_now dispatch failed for album {album_id}: {e}")

    return {
        "album_id": str(album.id),
        "retry_enabled": album.retry_enabled,
        "next_retry_at": album.next_retry_at.isoformat() if album.next_retry_at else None,
        "download_retry_count": album.download_retry_count or 0,
    }


@router.get("/albums/{album_id}/download-history")
async def get_album_download_history(
    album_id: str,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    validate_uuid(album_id, "Album ID")
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")

    events = (
        db.query(DownloadHistory)
        .filter(DownloadHistory.album_id == album.id)
        .order_by(DownloadHistory.occurred_at.desc())
        .all()
    )

    return {
        "album_id": str(album.id),
        "retry_enabled": getattr(album, 'retry_enabled', True),
        "next_retry_at": album.next_retry_at.isoformat() if album.next_retry_at else None,
        "download_retry_count": getattr(album, 'download_retry_count', 0),
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type.value if hasattr(e.event_type, 'value') else e.event_type,
                "release_guid": e.release_guid,
                "release_title": e.release_title,
                "message": e.message,
                "created_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "data": e.data,
            }
            for e in events
        ],
    }
