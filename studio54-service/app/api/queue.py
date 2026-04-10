"""
Queue API Router
Download queue management endpoints for tracked downloads
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from sqlalchemy.orm import Session, joinedload
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timezone
import logging

from app.database import get_db
from app.models import Album, Artist, DownloadClient
from app.models.download_decision import (
    TrackedDownload,
    TrackedDownloadState,
    DownloadHistory,
    DownloadEventType,
    Blacklist,
)
from app.services.download.download_client_provider import DownloadClientProvider
from app.security import rate_limit, validate_uuid
from app.auth import require_director, require_dj_or_above
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models
class RemoveFromQueueRequest(BaseModel):
    remove_from_client: bool = True
    blacklist: bool = False
    blacklist_reason: Optional[str] = None


# ============================================================================
# Queue Management Endpoints
# ============================================================================

@router.get("")
@rate_limit("100/minute")
async def get_queue(
    request: Request,
    state: Optional[TrackedDownloadState] = Query(None, description="Filter by state"),
    album_id: Optional[str] = Query(None, description="Filter by album ID"),
    artist_id: Optional[str] = Query(None, description="Filter by artist ID"),
    include_completed: bool = Query(False, description="Include completed downloads"),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get download queue status

    Returns all tracked downloads with their current status,
    progress, and associated album/artist information.
    """
    query = db.query(TrackedDownload).options(
        joinedload(TrackedDownload.album),
        joinedload(TrackedDownload.artist)
    )

    if state:
        query = query.filter(TrackedDownload.state == state)
    elif not include_completed:
        # Exclude completed/imported/ignored by default
        query = query.filter(
            TrackedDownload.state.in_([
                TrackedDownloadState.QUEUED,
                TrackedDownloadState.DOWNLOADING,
                TrackedDownloadState.PAUSED,
                TrackedDownloadState.IMPORT_PENDING,
                TrackedDownloadState.IMPORT_BLOCKED,
                TrackedDownloadState.IMPORTING,
            ])
        )

    if album_id:
        validate_uuid(album_id, "Album ID")
        query = query.filter(TrackedDownload.album_id == album_id)

    if artist_id:
        validate_uuid(artist_id, "Artist ID")
        query = query.filter(TrackedDownload.artist_id == artist_id)

    downloads = query.order_by(TrackedDownload.grabbed_at.desc()).limit(limit).all()

    return {
        "count": len(downloads),
        "items": [
            {
                "id": str(d.id),
                "title": d.title,
                "state": d.state.value,
                "progress": d.progress_percent,
                "size_bytes": d.size_bytes,
                "downloaded_bytes": d.downloaded_bytes,
                "eta_seconds": d.eta_seconds,
                "album_id": str(d.album_id) if d.album_id else None,
                "album_title": d.album.title if d.album else None,
                "artist_id": str(d.artist_id) if d.artist_id else None,
                "artist_name": d.artist.name if d.artist else None,
                "quality": d.release_quality,
                "indexer": d.release_indexer,
                "grabbed_at": d.grabbed_at.isoformat() if d.grabbed_at else None,
                "completed_at": d.completed_at.isoformat() if d.completed_at else None,
                "error_message": d.error_message,
                "status_messages": d.status_messages,
                "output_path": d.output_path
            }
            for d in downloads
        ]
    }


# ============================================================================
# Static Routes (must be before parameterized routes)
# ============================================================================

@router.get("/blacklist")
@rate_limit("100/minute")
async def get_blacklist(
    request: Request,
    album_id: Optional[str] = Query(None, description="Filter by album ID"),
    artist_id: Optional[str] = Query(None, description="Filter by artist ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get blacklisted releases
    """
    query = db.query(Blacklist)

    if album_id:
        validate_uuid(album_id, "Album ID")
        query = query.filter(Blacklist.album_id == album_id)

    if artist_id:
        validate_uuid(artist_id, "Artist ID")
        query = query.filter(Blacklist.artist_id == artist_id)

    total = query.count()
    blacklist = query.order_by(Blacklist.added_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": str(b.id),
                "release_guid": b.release_guid,
                "release_title": b.release_title,
                "album_id": str(b.album_id) if b.album_id else None,
                "artist_id": str(b.artist_id) if b.artist_id else None,
                "reason": b.reason,
                "added_at": b.added_at.isoformat() if b.added_at else None
            }
            for b in blacklist
        ]
    }


@router.get("/history")
@rate_limit("100/minute")
async def get_download_history(
    request: Request,
    event_type: Optional[DownloadEventType] = Query(None, description="Filter by event type"),
    status_filter: Optional[str] = Query(None, description="Filter by status: 'completed' or 'failed'"),
    date_from: Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    album_id: Optional[str] = Query(None, description="Filter by album ID"),
    artist_id: Optional[str] = Query(None, description="Filter by artist ID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db)
):
    """
    Get download history

    Returns a history of download events (grabbed, imported, failed, etc.)
    """
    query = db.query(DownloadHistory).options(
        joinedload(DownloadHistory.album),
        joinedload(DownloadHistory.artist),
    )

    if event_type:
        query = query.filter(DownloadHistory.event_type == event_type)

    if status_filter:
        if status_filter == "completed":
            query = query.filter(DownloadHistory.event_type == DownloadEventType.IMPORTED)
        elif status_filter == "failed":
            query = query.filter(DownloadHistory.event_type.in_([
                DownloadEventType.DOWNLOAD_FAILED,
                DownloadEventType.IMPORT_FAILED,
            ]))

    if date_from:
        try:
            from_dt = datetime.fromisoformat(date_from)
            query = query.filter(DownloadHistory.occurred_at >= from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            to_dt = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59)
            query = query.filter(DownloadHistory.occurred_at <= to_dt)
        except ValueError:
            pass

    if album_id:
        validate_uuid(album_id, "Album ID")
        query = query.filter(DownloadHistory.album_id == album_id)

    if artist_id:
        validate_uuid(artist_id, "Artist ID")
        query = query.filter(DownloadHistory.artist_id == artist_id)

    total = query.count()
    history = query.order_by(DownloadHistory.occurred_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": str(h.id),
                "event_type": h.event_type.value,
                "release_guid": h.release_guid,
                "release_title": h.release_title,
                "album_id": str(h.album_id) if h.album_id else None,
                "album_title": h.album.title if h.album else None,
                "artist_id": str(h.artist_id) if h.artist_id else None,
                "artist_name": h.artist.name if h.artist else None,
                "quality": h.quality,
                "source": h.source,
                "message": h.message,
                "download_path": (h.data.get('output_path') or h.data.get('download_path')) if h.data else None,
                "occurred_at": h.occurred_at.isoformat() if h.occurred_at else None
            }
            for h in history
        ]
    }


# ============================================================================
# Individual Download Endpoints (parameterized routes)
# ============================================================================

@router.get("/{download_id}")
@rate_limit("100/minute")
async def get_queue_item(
    request: Request,
    download_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Get details of a specific download

    Returns full details of a tracked download including
    progress and status information.
    """
    validate_uuid(download_id, "Download ID")

    tracked = db.query(TrackedDownload).options(
        joinedload(TrackedDownload.album),
        joinedload(TrackedDownload.artist)
    ).filter(TrackedDownload.id == download_id).first()

    if not tracked:
        raise HTTPException(status_code=404, detail="Download not found")

    return {
        "id": str(tracked.id),
        "title": tracked.title,
        "state": tracked.state.value,
        "progress": tracked.progress_percent,
        "size_bytes": tracked.size_bytes,
        "downloaded_bytes": tracked.downloaded_bytes,
        "eta_seconds": tracked.eta_seconds,
        "album": {
            "id": str(tracked.album.id),
            "title": tracked.album.title,
            "status": tracked.album.status.value
        } if tracked.album else None,
        "artist": {
            "id": str(tracked.artist.id),
            "name": tracked.artist.name
        } if tracked.artist else None,
        "release": {
            "guid": tracked.release_guid,
            "quality": tracked.release_quality,
            "indexer": tracked.release_indexer
        },
        "download_client_id": str(tracked.download_client_id) if tracked.download_client_id else None,
        "download_id": tracked.download_id,
        "output_path": tracked.output_path,
        "grabbed_at": tracked.grabbed_at.isoformat() if tracked.grabbed_at else None,
        "completed_at": tracked.completed_at.isoformat() if tracked.completed_at else None,
        "imported_at": tracked.imported_at.isoformat() if tracked.imported_at else None,
        "error_message": tracked.error_message,
        "status_messages": tracked.status_messages
    }


@router.delete("/{download_id}")
@rate_limit("50/minute")
async def remove_from_queue(
    request: Request,
    download_id: str,
    remove_request: RemoveFromQueueRequest = Body(default=RemoveFromQueueRequest()),
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Remove item from download queue

    Optionally removes from the download client and/or blacklists
    the release to prevent future grabs.
    """
    validate_uuid(download_id, "Download ID")

    tracked = db.query(TrackedDownload).filter(TrackedDownload.id == download_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Download not found")

    # Remove from download client if requested
    if remove_request.remove_from_client and tracked.download_client_id:
        try:
            client_provider = DownloadClientProvider(db)
            client = client_provider.get_client_by_id(str(tracked.download_client_id))

            if client:
                client.delete_download(tracked.download_id, delete_files=False)

        except Exception as e:
            logger.warning(f"Failed to remove from download client: {e}")
            # Continue anyway - we'll still remove from our queue

    # Add to blacklist if requested
    if remove_request.blacklist and tracked.release_guid:
        blacklist = Blacklist(
            album_id=tracked.album_id,
            artist_id=tracked.artist_id,
            indexer_id=tracked.indexer_id,
            release_guid=tracked.release_guid,
            release_title=tracked.title,
            reason=remove_request.blacklist_reason or "Manually removed from queue"
        )
        db.add(blacklist)

        # Record in history
        history = DownloadHistory(
            album_id=tracked.album_id,
            artist_id=tracked.artist_id,
            release_guid=tracked.release_guid,
            release_title=tracked.title,
            event_type=DownloadEventType.BLACKLISTED,
            quality=tracked.release_quality,
            source=tracked.release_indexer,
            message=remove_request.blacklist_reason
        )
        db.add(history)

    # Record deletion in history
    history = DownloadHistory(
        album_id=tracked.album_id,
        artist_id=tracked.artist_id,
        release_guid=tracked.release_guid,
        release_title=tracked.title,
        event_type=DownloadEventType.DELETED,
        quality=tracked.release_quality,
        source=tracked.release_indexer
    )
    db.add(history)

    # Delete the tracked download
    db.delete(tracked)
    db.commit()

    return {
        "status": "removed",
        "download_id": download_id,
        "blacklisted": remove_request.blacklist
    }


# ============================================================================
# Queue State Management
# ============================================================================

@router.post("/{download_id}/pause")
@rate_limit("30/minute")
async def pause_download(
    request: Request,
    download_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Pause a download in the queue
    """
    validate_uuid(download_id, "Download ID")

    tracked = db.query(TrackedDownload).filter(TrackedDownload.id == download_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Download not found")

    if tracked.state not in [TrackedDownloadState.QUEUED, TrackedDownloadState.DOWNLOADING]:
        raise HTTPException(status_code=400, detail="Download cannot be paused in current state")

    # Pause in download client
    if tracked.download_client_id:
        try:
            client_provider = DownloadClientProvider(db)
            client = client_provider.get_client_by_id(str(tracked.download_client_id))

            if client:
                client.pause_download(tracked.download_id)

        except Exception as e:
            logger.warning(f"Failed to pause in download client: {e}")

    tracked.state = TrackedDownloadState.PAUSED
    db.commit()

    return {"status": "paused", "download_id": download_id}


@router.post("/{download_id}/resume")
@rate_limit("30/minute")
async def resume_download(
    request: Request,
    download_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Resume a paused download
    """
    validate_uuid(download_id, "Download ID")

    tracked = db.query(TrackedDownload).filter(TrackedDownload.id == download_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Download not found")

    if tracked.state != TrackedDownloadState.PAUSED:
        raise HTTPException(status_code=400, detail="Download is not paused")

    # Resume in download client
    if tracked.download_client_id:
        try:
            client_provider = DownloadClientProvider(db)
            client = client_provider.get_client_by_id(str(tracked.download_client_id))

            if client:
                client.resume_download(tracked.download_id)

        except Exception as e:
            logger.warning(f"Failed to resume in download client: {e}")

    tracked.state = TrackedDownloadState.DOWNLOADING
    db.commit()

    return {"status": "resumed", "download_id": download_id}


@router.post("/{download_id}/retry-import")
@rate_limit("20/minute")
async def retry_import(
    request: Request,
    download_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Retry import for a blocked download
    """
    validate_uuid(download_id, "Download ID")

    tracked = db.query(TrackedDownload).filter(TrackedDownload.id == download_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Download not found")

    if tracked.state not in [TrackedDownloadState.IMPORT_PENDING, TrackedDownloadState.IMPORT_BLOCKED]:
        raise HTTPException(status_code=400, detail="Download is not ready for import")

    # Reset state to trigger import
    tracked.state = TrackedDownloadState.IMPORT_PENDING
    tracked.error_message = None
    tracked.status_messages = None
    db.commit()

    # Trigger import task (placeholder - would integrate with import service)
    logger.info(f"Retry import requested for: {tracked.title}")

    return {
        "status": "import_queued",
        "download_id": download_id,
        "message": "Import will be retried"
    }


# ============================================================================
# Blacklist Modification Endpoints
# ============================================================================

@router.delete("/blacklist/{blacklist_id}")
@rate_limit("50/minute")
async def remove_from_blacklist(
    request: Request,
    blacklist_id: str,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db)
):
    """
    Remove a release from the blacklist
    """
    validate_uuid(blacklist_id, "Blacklist ID")

    item = db.query(Blacklist).filter(Blacklist.id == blacklist_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Blacklist item not found")

    db.delete(item)
    db.commit()

    return {"status": "removed", "blacklist_id": blacklist_id}


