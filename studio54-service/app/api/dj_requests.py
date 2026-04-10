"""
DJ Requests API Router
Allows all users to request artists, albums, or tracks.
Directors can approve/reject/fulfill requests.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func
from typing import Optional
from pydantic import BaseModel, Field
import logging

from app.database import get_db
from app.security import rate_limit
from app.auth import require_any_user, require_director
from app.models.user import User
from app.models.dj_request import DjRequest

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Schemas ---

class CreateDjRequest(BaseModel):
    request_type: str = Field(..., pattern="^(artist|album|track|problem)$")
    title: str = Field(..., min_length=1, max_length=500)
    artist_name: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None
    musicbrainz_id: Optional[str] = Field(None, max_length=36)
    musicbrainz_name: Optional[str] = Field(None, max_length=500)
    track_name: Optional[str] = Field(None, max_length=500)


class UpdateDjRequestStatus(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|fulfilled)$")
    response_note: Optional[str] = None


class DjRequestResponse(BaseModel):
    id: str
    user_id: str
    requester_name: str
    request_type: str
    title: str
    artist_name: Optional[str]
    notes: Optional[str]
    musicbrainz_id: Optional[str]
    musicbrainz_name: Optional[str]
    track_name: Optional[str]
    status: str
    response_note: Optional[str]
    fulfilled_by_name: Optional[str]
    created_at: str
    updated_at: str


# --- Helpers ---

def _to_response(req: DjRequest) -> dict:
    return {
        "id": str(req.id),
        "user_id": str(req.user_id),
        "requester_name": req.user.display_name or req.user.username if req.user else "Unknown",
        "request_type": req.request_type,
        "title": req.title,
        "artist_name": req.artist_name,
        "notes": req.notes,
        "musicbrainz_id": req.musicbrainz_id,
        "musicbrainz_name": req.musicbrainz_name,
        "track_name": req.track_name,
        "status": req.status,
        "response_note": req.response_note,
        "fulfilled_by_name": (
            req.fulfilled_by.display_name or req.fulfilled_by.username
            if req.fulfilled_by else None
        ),
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
    }


# --- Endpoints ---

@router.get("/dj-requests")
@rate_limit("100/minute")
async def list_requests(
    request: Request,
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected, fulfilled"),
    request_type: Optional[str] = Query(None, description="Filter by type: artist, album, track"),
    my_requests: bool = Query(False, description="Only show my requests"),
    user_id: Optional[str] = Query(None, description="Filter by user ID (directors only)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """List DJ requests. All users can see all requests."""
    query = db.query(DjRequest).options(
        joinedload(DjRequest.user),
        joinedload(DjRequest.fulfilled_by),
    )

    if status_filter:
        query = query.filter(DjRequest.status == status_filter)
    if request_type:
        query = query.filter(DjRequest.request_type == request_type)
    if my_requests:
        query = query.filter(DjRequest.user_id == current_user.id)
    if user_id and current_user.role == "director":
        query = query.filter(DjRequest.user_id == user_id)

    total = query.count()
    items = query.order_by(DjRequest.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total_count": total,
        "limit": limit,
        "offset": offset,
        "requests": [_to_response(r) for r in items],
    }


@router.get("/dj-requests/by-user")
@rate_limit("60/minute")
async def list_requests_by_user(
    request: Request,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Get request summaries grouped by user. Directors only."""
    results = (
        db.query(
            DjRequest.user_id,
            User.username,
            User.display_name,
            sa_func.count(DjRequest.id).label("total_count"),
            sa_func.count(sa_func.nullif(DjRequest.status != 'pending', True)).label("pending_count"),
        )
        .join(User, User.id == DjRequest.user_id)
        .group_by(DjRequest.user_id, User.username, User.display_name)
        .order_by(sa_func.count(sa_func.nullif(DjRequest.status != 'pending', True)).desc(), User.display_name)
        .all()
    )

    users = []
    for row in results:
        users.append({
            "user_id": str(row.user_id),
            "username": row.username,
            "display_name": row.display_name or row.username,
            "total_count": row.total_count,
            "pending_count": row.pending_count,
        })

    return {"users": users}


@router.post("/dj-requests", status_code=status.HTTP_201_CREATED)
@rate_limit("30/minute")
async def create_request(
    request: Request,
    body: CreateDjRequest,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Submit a new DJ request. Any authenticated user can request."""
    dj_request = DjRequest(
        user_id=current_user.id,
        request_type=body.request_type,
        title=body.title,
        artist_name=body.artist_name,
        notes=body.notes,
        musicbrainz_id=body.musicbrainz_id,
        musicbrainz_name=body.musicbrainz_name,
        track_name=body.track_name,
        status="pending",
    )
    db.add(dj_request)
    db.commit()
    db.refresh(dj_request)

    # Reload with relationships
    dj_request = db.query(DjRequest).options(
        joinedload(DjRequest.user),
        joinedload(DjRequest.fulfilled_by),
    ).filter(DjRequest.id == dj_request.id).first()

    logger.info(f"DJ request created: {body.request_type} '{body.title}' by {current_user.username}")
    return _to_response(dj_request)


@router.patch("/dj-requests/{request_id}")
@rate_limit("60/minute")
async def update_request_status(
    request: Request,
    request_id: str,
    body: UpdateDjRequestStatus,
    current_user: User = Depends(require_director),
    db: Session = Depends(get_db),
):
    """Update request status. Directors only."""
    dj_request = db.query(DjRequest).options(
        joinedload(DjRequest.user),
        joinedload(DjRequest.fulfilled_by),
    ).filter(DjRequest.id == request_id).first()

    if not dj_request:
        raise HTTPException(status_code=404, detail="Request not found")

    dj_request.status = body.status
    if body.response_note is not None:
        dj_request.response_note = body.response_note
    if body.status == "fulfilled":
        dj_request.fulfilled_by_id = current_user.id

    db.commit()
    db.refresh(dj_request)

    # Reload with relationships
    dj_request = db.query(DjRequest).options(
        joinedload(DjRequest.user),
        joinedload(DjRequest.fulfilled_by),
    ).filter(DjRequest.id == dj_request.id).first()

    logger.info(f"DJ request {request_id} updated to {body.status} by {current_user.username}")
    return _to_response(dj_request)


@router.delete("/dj-requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
@rate_limit("30/minute")
async def delete_request(
    request: Request,
    request_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Delete a request. Users can delete their own; Directors can delete any."""
    dj_request = db.query(DjRequest).filter(DjRequest.id == request_id).first()
    if not dj_request:
        raise HTTPException(status_code=404, detail="Request not found")

    if str(dj_request.user_id) != str(current_user.id) and current_user.role != "director":
        raise HTTPException(status_code=403, detail="Can only delete your own requests")

    db.delete(dj_request)
    db.commit()
    logger.info(f"DJ request {request_id} deleted by {current_user.username}")
