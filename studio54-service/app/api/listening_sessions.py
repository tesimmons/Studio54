"""
Listening Sessions API
POST/GET/PATCH/DELETE for /books/{id}/session and /series/{id}/session
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.models.user_listening_session import UserListeningSession
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.series import Series
from app.models.book_playlist import BookPlaylist, BookPlaylistChapter

router = APIRouter()


class PatchSessionRequest(BaseModel):
    current_index: int


def _session_response(session: UserListeningSession) -> dict:
    return {
        "id": str(session.id),
        "session_type": session.session_type,
        "book_id": str(session.book_id) if session.book_id else None,
        "series_id": str(session.series_id) if session.series_id else None,
        "chapter_queue": session.chapter_queue,
        "current_index": session.current_index,
        "archived_at": session.archived_at.isoformat() if session.archived_at else None,
        "pending_delete_at": session.pending_delete_at.isoformat() if session.pending_delete_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _build_book_chapter_queue(book_id: uuid.UUID, db: Session) -> List[str]:
    chapters = (
        db.query(Chapter)
        .filter(Chapter.book_id == book_id, Chapter.has_file == True)  # noqa: E712
        .order_by(Chapter.disc_number, Chapter.chapter_number)
        .all()
    )
    return [str(ch.id) for ch in chapters]


def _build_series_chapter_queue(series_id: uuid.UUID, db: Session) -> List[str]:
    playlist = db.query(BookPlaylist).filter(BookPlaylist.series_id == series_id).first()
    if not playlist:
        return []
    entries = (
        db.query(BookPlaylistChapter)
        .filter(BookPlaylistChapter.playlist_id == playlist.id)
        .order_by(BookPlaylistChapter.position)
        .all()
    )
    return [str(e.chapter_id) for e in entries if e.chapter and e.chapter.has_file]


# ──────────────────────────── BOOK SESSIONS ───────────────────────────────


@router.post("/books/{book_id}/session")
async def create_or_get_book_session(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a book session (idempotent). Reactivates if archived."""
    try:
        bid = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid book_id")

    book = db.query(Book).filter(Book.id == bid).first()
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.book_id == bid,
            UserListeningSession.series_id == None,  # noqa: E711
        )
        .first()
    )

    if session:
        if session.archived_at:
            session.archived_at = None
            session.pending_delete_at = None
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
        return _session_response(session)

    chapter_queue = _build_book_chapter_queue(bid, db)
    session = UserListeningSession(
        user_id=current_user.id,
        session_type="book",
        book_id=bid,
        series_id=None,
        chapter_queue=chapter_queue,
        current_index=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_response(session)


@router.get("/books/{book_id}/session")
async def get_book_session(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch active book session. 404 if none exists."""
    try:
        bid = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid book_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.book_id == bid,
            UserListeningSession.series_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")
    return _session_response(session)


@router.patch("/books/{book_id}/session")
async def patch_book_session(
    book_id: str,
    body: PatchSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current_index for book session."""
    try:
        bid = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid book_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.book_id == bid,
            UserListeningSession.series_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")

    session.current_index = body.current_index
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _session_response(session)


@router.post("/books/{book_id}/session/archive")
async def archive_book_session(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-archive a book session. Sets archived_at and pending_delete_at = +7 days."""
    try:
        bid = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid book_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.book_id == bid,
            UserListeningSession.series_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")

    now = datetime.now(timezone.utc)
    session.archived_at = now
    session.pending_delete_at = now + timedelta(days=7)
    session.updated_at = now
    db.commit()
    return _session_response(session)


@router.delete("/books/{book_id}/session/archive")
async def unarchive_book_session(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Undo archive: clear archived_at and pending_delete_at."""
    try:
        bid = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid book_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.book_id == bid,
            UserListeningSession.series_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")

    session.archived_at = None
    session.pending_delete_at = None
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _session_response(session)


@router.delete("/books/{book_id}/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book_session(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete book session."""
    try:
        bid = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid book_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.book_id == bid,
            UserListeningSession.series_id == None,  # noqa: E711
        )
        .first()
    )
    if session:
        db.delete(session)
        db.commit()


# ──────────────────────────── SERIES SESSIONS ─────────────────────────────


@router.post("/series/{series_id}/session")
async def create_or_get_series_session(
    series_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a series session (idempotent). Reactivates if archived."""
    try:
        sid = uuid.UUID(series_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid series_id")

    series = db.query(Series).filter(Series.id == sid).first()
    if not series:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Series not found")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.series_id == sid,
            UserListeningSession.book_id == None,  # noqa: E711
        )
        .first()
    )

    if session:
        if session.archived_at:
            session.archived_at = None
            session.pending_delete_at = None
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
        return _session_response(session)

    chapter_queue = _build_series_chapter_queue(sid, db)
    session = UserListeningSession(
        user_id=current_user.id,
        session_type="series",
        book_id=None,
        series_id=sid,
        chapter_queue=chapter_queue,
        current_index=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_response(session)


@router.get("/series/{series_id}/session")
async def get_series_session(
    series_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch active series session. 404 if none."""
    try:
        sid = uuid.UUID(series_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid series_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.series_id == sid,
            UserListeningSession.book_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")
    return _session_response(session)


@router.patch("/series/{series_id}/session")
async def patch_series_session(
    series_id: str,
    body: PatchSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current_index for series session."""
    try:
        sid = uuid.UUID(series_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid series_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.series_id == sid,
            UserListeningSession.book_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")

    session.current_index = body.current_index
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _session_response(session)


@router.post("/series/{series_id}/session/archive")
async def archive_series_session(
    series_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-archive a series session."""
    try:
        sid = uuid.UUID(series_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid series_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.series_id == sid,
            UserListeningSession.book_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")

    now = datetime.now(timezone.utc)
    session.archived_at = now
    session.pending_delete_at = now + timedelta(days=7)
    session.updated_at = now
    db.commit()
    return _session_response(session)


@router.delete("/series/{series_id}/session/archive")
async def unarchive_series_session(
    series_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Undo archive for series session."""
    try:
        sid = uuid.UUID(series_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid series_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.series_id == sid,
            UserListeningSession.book_id == None,  # noqa: E711
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No session found")

    session.archived_at = None
    session.pending_delete_at = None
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _session_response(session)


@router.delete("/series/{series_id}/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series_session(
    series_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete series session."""
    try:
        sid = uuid.UUID(series_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid series_id")

    session = (
        db.query(UserListeningSession)
        .filter(
            UserListeningSession.user_id == current_user.id,
            UserListeningSession.series_id == sid,
            UserListeningSession.book_id == None,  # noqa: E711
        )
        .first()
    )
    if session:
        db.delete(session)
        db.commit()
