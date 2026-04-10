"""
Now Playing API Router
Tracks active listeners via Redis heartbeats for the Sound Booth "Now Listening" feature.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, List
import json
import logging
from datetime import datetime, timezone

import redis

from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.auth import require_any_user
from app.models.user import User
from app.models.book_progress import BookProgress
from app.models.chapter import Chapter
from app.security import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()

REDIS_KEY_PREFIX = "studio54:now_playing:"
HEARTBEAT_TTL_SECONDS = 60


def _get_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


# --- Schemas ---

class HeartbeatRequest(BaseModel):
    track_id: str = Field(..., min_length=1)
    track_title: str = Field(..., min_length=1)
    artist_name: str = Field(..., min_length=1)
    artist_id: Optional[str] = None
    album_id: Optional[str] = None
    album_title: Optional[str] = None
    cover_art_url: Optional[str] = None
    # Optional book progress fields (for audiobook resume)
    book_id: Optional[str] = None
    chapter_id: Optional[str] = None
    position_ms: Optional[int] = None


class NowPlayingListener(BaseModel):
    user_id: str
    display_name: str
    role: str
    track_title: str
    artist_name: str
    artist_id: Optional[str] = None
    album_id: Optional[str] = None
    album_title: Optional[str] = None
    cover_art_url: Optional[str] = None
    listening_since: str


class NowPlayingResponse(BaseModel):
    listeners: List[NowPlayingListener]


# --- Endpoints ---

@router.post("/now-playing/heartbeat", status_code=204)
@rate_limit("60/minute")
async def heartbeat(
    request: Request,
    body: HeartbeatRequest,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Send a heartbeat indicating the user is currently listening to a track.
    When book_id, chapter_id, and position_ms are provided, also auto-saves
    audiobook playback progress for resume functionality."""
    # Auto-save book progress if audiobook fields are present
    if body.book_id and body.chapter_id and body.position_ms is not None:
        try:
            progress = (
                db.query(BookProgress)
                .filter(
                    BookProgress.user_id == current_user.id,
                    BookProgress.book_id == body.book_id,
                )
                .first()
            )
            if progress:
                progress.chapter_id = body.chapter_id
                progress.position_ms = body.position_ms
                progress.updated_at = datetime.now(timezone.utc)
            else:
                progress = BookProgress(
                    user_id=current_user.id,
                    book_id=body.book_id,
                    chapter_id=body.chapter_id,
                    position_ms=body.position_ms,
                )
                db.add(progress)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Failed to auto-save book progress: {e}")

    r = _get_redis()
    key = f"{REDIS_KEY_PREFIX}{current_user.id}"

    # Preserve listening_since if the key already exists
    existing = r.get(key)
    if existing:
        try:
            existing_data = json.loads(existing)
            listening_since = existing_data.get("listening_since")
        except (json.JSONDecodeError, TypeError):
            listening_since = None
    else:
        listening_since = None

    if not listening_since:
        listening_since = datetime.now(timezone.utc).isoformat()

    payload = {
        "user_id": str(current_user.id),
        "display_name": current_user.display_name or current_user.username,
        "role": current_user.role,
        "track_id": body.track_id,
        "track_title": body.track_title,
        "artist_name": body.artist_name,
        "artist_id": body.artist_id,
        "album_id": body.album_id,
        "album_title": body.album_title,
        "cover_art_url": body.cover_art_url,
        "listening_since": listening_since,
    }

    r.setex(key, HEARTBEAT_TTL_SECONDS, json.dumps(payload))


@router.delete("/now-playing/heartbeat", status_code=204)
@rate_limit("60/minute")
async def clear_heartbeat(
    request: Request,
    current_user: User = Depends(require_any_user),
):
    """Clear the user's now-playing status (when playback stops)."""
    r = _get_redis()
    r.delete(f"{REDIS_KEY_PREFIX}{current_user.id}")


@router.get("/now-playing", response_model=NowPlayingResponse)
@rate_limit("60/minute")
async def get_now_playing(
    request: Request,
    current_user: User = Depends(require_any_user),
):
    """Get the list of active listeners (max 5)."""
    r = _get_redis()
    listeners: List[NowPlayingListener] = []

    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"{REDIS_KEY_PREFIX}*", count=100)
        for key in keys:
            raw = r.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                listeners.append(NowPlayingListener(
                    user_id=data["user_id"],
                    display_name=data["display_name"],
                    role=data["role"],
                    track_title=data["track_title"],
                    artist_name=data["artist_name"],
                    artist_id=data.get("artist_id"),
                    album_id=data.get("album_id"),
                    album_title=data.get("album_title"),
                    cover_art_url=data.get("cover_art_url"),
                    listening_since=data["listening_since"],
                ))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid now-playing data for key {key}: {e}")
                continue

            if len(listeners) >= 5:
                break
        if cursor == 0 or len(listeners) >= 5:
            break

    # Sort by listening_since (earliest first)
    listeners.sort(key=lambda l: l.listening_since)

    return NowPlayingResponse(listeners=listeners[:5])
