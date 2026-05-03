"""
Book Progress API Router
Per-user audiobook playback progress: get, upsert, reset.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import logging

from app.database import get_db
from app.auth import require_any_user
from app.models.user import User
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.book_progress import BookProgress
from app.security import rate_limit, validate_uuid

logger = logging.getLogger(__name__)

router = APIRouter()


class ProgressUpdateRequest(BaseModel):
    chapter_id: str
    position_ms: int = 0
    completed: Optional[bool] = None


class BatchProgressRequest(BaseModel):
    book_ids: List[str]


@router.get("/books/{book_id}/progress")
@rate_limit("100/minute")
async def get_book_progress(
    request: Request,
    book_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Get the current user's playback progress for a book."""
    validate_uuid(book_id, "Book ID")

    progress = (
        db.query(BookProgress)
        .filter(
            BookProgress.user_id == current_user.id,
            BookProgress.book_id == book_id,
        )
        .first()
    )

    if not progress:
        return None

    chapter = db.query(Chapter).filter(Chapter.id == progress.chapter_id).first()

    return {
        "book_id": str(progress.book_id),
        "chapter_id": str(progress.chapter_id),
        "chapter_title": chapter.title if chapter else None,
        "chapter_number": chapter.chapter_number if chapter else None,
        "position_ms": progress.position_ms,
        "completed": progress.completed,
        "updated_at": progress.updated_at.isoformat() if progress.updated_at else None,
    }


@router.post("/books/{book_id}/progress")
@rate_limit("60/minute")
async def upsert_book_progress(
    request: Request,
    book_id: str,
    body: ProgressUpdateRequest,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Create or update the current user's playback progress for a book."""
    validate_uuid(book_id, "Book ID")
    validate_uuid(body.chapter_id, "Chapter ID")

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book not found",
        )

    chapter = db.query(Chapter).filter(
        Chapter.id == body.chapter_id,
        Chapter.book_id == book_id,
    ).first()
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found in this book",
        )

    try:
        progress = (
            db.query(BookProgress)
            .filter(
                BookProgress.user_id == current_user.id,
                BookProgress.book_id == book_id,
            )
            .first()
        )

        if progress:
            progress.chapter_id = chapter.id
            progress.position_ms = body.position_ms
            if body.completed is not None:
                progress.completed = body.completed
            progress.updated_at = datetime.now(timezone.utc)
        else:
            progress = BookProgress(
                user_id=current_user.id,
                book_id=book_id,
                chapter_id=chapter.id,
                position_ms=body.position_ms,
                completed=body.completed or False,
            )
            db.add(progress)

        db.commit()
        db.refresh(progress)

        return {
            "book_id": str(progress.book_id),
            "chapter_id": str(progress.chapter_id),
            "chapter_title": chapter.title,
            "chapter_number": chapter.chapter_number,
            "position_ms": progress.position_ms,
            "completed": progress.completed,
            "updated_at": progress.updated_at.isoformat() if progress.updated_at else None,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to upsert book progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save progress: {str(e)}",
        )


@router.post("/books/progress/batch")
@rate_limit("60/minute")
async def batch_get_progress(
    request: Request,
    body: BatchProgressRequest,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Get the current user's playback progress for multiple books at once."""
    # Validate and deduplicate book IDs
    valid_ids = []
    for book_id in body.book_ids:
        try:
            validate_uuid(book_id, "Book ID")
            valid_ids.append(book_id)
        except Exception:
            continue

    if not valid_ids:
        return {"progress": {}}

    # Query all progress records for this user and the given book IDs
    progress_records = (
        db.query(BookProgress)
        .filter(
            BookProgress.user_id == current_user.id,
            BookProgress.book_id.in_(valid_ids),
        )
        .all()
    )

    # Build response dict keyed by book_id
    result = {}
    for progress in progress_records:
        chapter = db.query(Chapter).filter(Chapter.id == progress.chapter_id).first()
        result[str(progress.book_id)] = {
            "chapter_id": str(progress.chapter_id),
            "chapter_title": chapter.title if chapter else None,
            "chapter_number": chapter.chapter_number if chapter else None,
            "position_ms": progress.position_ms,
            "completed": progress.completed,
            "updated_at": progress.updated_at.isoformat() if progress.updated_at else None,
        }

    return {"progress": result}


@router.delete("/books/{book_id}/progress", status_code=204)
@rate_limit("50/minute")
async def delete_book_progress(
    request: Request,
    book_id: str,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db),
):
    """Reset the current user's progress for a book (start over)."""
    validate_uuid(book_id, "Book ID")

    deleted = (
        db.query(BookProgress)
        .filter(
            BookProgress.user_id == current_user.id,
            BookProgress.book_id == book_id,
        )
        .delete(synchronize_session="fetch")
    )
    db.commit()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No progress found for this book",
        )


@router.post("/books/{book_id}/progress/beacon")
async def save_progress_beacon(
    book_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Lightweight progress save endpoint for navigator.sendBeacon() on player close.
    Authenticates via JWT token in the request body (sendBeacon cannot set headers).
    """
    import uuid as _uuid
    from jose import jwt as jose_jwt, JWTError
    from app.auth import JWT_SECRET, JWT_ALGORITHM

    validate_uuid(book_id, "Book ID")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    token = body.get("token", "")
    chapter_id_str = body.get("chapter_id", "")
    position_ms = body.get("position_ms", 0)

    if not token or not chapter_id_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token or chapter_id")

    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    from app.models.user import User as UserModel
    user = db.query(UserModel).filter(UserModel.id == user_id, UserModel.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or disabled")

    try:
        bid = _uuid.UUID(book_id)
        cid = _uuid.UUID(chapter_id_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid UUID")

    existing = db.query(BookProgress).filter(
        BookProgress.user_id == user.id,
        BookProgress.book_id == bid,
    ).first()

    if existing:
        existing.chapter_id = cid
        existing.position_ms = int(position_ms)
    else:
        db.add(BookProgress(
            user_id=user.id,
            book_id=bid,
            chapter_id=cid,
            position_ms=int(position_ms),
        ))

    db.commit()
    return {"ok": True}
