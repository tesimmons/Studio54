# Audiobook Session Persistence & Sleep Timer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sleep timer, reliable position saving, per-user session persistence, and Mark as Finished to the Studio54 pop-out audiobook player.

**Architecture:** New `user_listening_sessions` DB table owns queue/index state; existing `book_progress` continues to own millisecond position. The pop-out player always opens on Play Book / Play Series, inheriting the session's current chapter index and seeking to the saved timestamp. Sleep timer, snooze popup, and session current-index sync all live as local state in PopOutPlayer — no persistence across player close for the timer.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend); React + TypeScript + Axios (frontend); Celery beat (scheduled cleanup).

---

## File Map

**Create:**
- `studio54-service/app/models/user_listening_session.py`
- `studio54-service/alembic/versions/20260503_0100_062_add_user_listening_sessions.py`
- `studio54-service/app/api/listening_sessions.py`

**Modify:**
- `studio54-service/app/main.py` — register new router
- `studio54-service/app/tasks/monitoring_tasks.py` — nightly cleanup task
- `studio54-service/app/tasks/celery_app.py` — include module + beat entry
- `studio54-web/src/hooks/usePlayerBroadcast.ts` — add session fields to SerializedPlayerState, add PLAY_BOOK_REQUEST_KEY
- `studio54-web/src/contexts/PlayerContext.tsx` — extend PLAY_BOOK action/state/reducer; playBook() always opens pop-out; play-book-playlist passes sessionType
- `studio54-web/src/api/client.ts` — add listeningSessionApi
- `studio54-web/src/pages/PopOutPlayer.tsx` — pause save, sendBeacon, sleep timer, snooze popup, session index PATCH, init from PLAY_BOOK_REQUEST_KEY
- `studio54-web/src/pages/BookDetail.tsx` — session fetch/create, Mark as Read, undo banner
- `studio54-web/src/pages/SeriesDetail.tsx` — session fetch/create, Mark as Complete, undo banner

---

## Task 1: UserListeningSession SQLAlchemy Model

**Files:**
- Create: `studio54-service/app/models/user_listening_session.py`

- [ ] **Step 1: Write the failing import test**

```python
# studio54-service/app/models/tests/test_user_listening_session_import.py
def test_import():
    from app.models.user_listening_session import UserListeningSession
    assert UserListeningSession.__tablename__ == "user_listening_sessions"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd studio54-service && docker compose exec studio54 python -m pytest app/models/tests/test_user_listening_session_import.py -v 2>&1 | tail -10
```

Expected: ModuleNotFoundError or similar

- [ ] **Step 3: Create the model**

```python
# studio54-service/app/models/user_listening_session.py
"""
UserListeningSession model — per-user audiobook session (book or series).

Owns the chapter queue and current position within it.
BookProgress owns the millisecond position within the current chapter.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import relationship
from sqlalchemy import Index, text
from app.database import Base


class UserListeningSession(Base):
    __tablename__ = "user_listening_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_type = Column(String(10), nullable=False)  # "book" | "series"
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=True)
    series_id = Column(UUID(as_uuid=True), ForeignKey("series.id", ondelete="CASCADE"), nullable=True)
    chapter_queue = Column(JSON, nullable=False, default=list)
    current_index = Column(Integer, nullable=False, default=0)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    pending_delete_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "(book_id IS NOT NULL AND series_id IS NULL) OR (book_id IS NULL AND series_id IS NOT NULL)",
            name="ck_uls_exactly_one_fk",
        ),
        Index(
            "uq_uls_user_book", "user_id", "book_id",
            unique=True, postgresql_where=text("series_id IS NULL"),
        ),
        Index(
            "uq_uls_user_series", "user_id", "series_id",
            unique=True, postgresql_where=text("book_id IS NULL"),
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd studio54-service && docker compose exec studio54 python -m pytest app/models/tests/test_user_listening_session_import.py -v 2>&1 | tail -10
```

Expected: PASSED

- [ ] **Step 5: Commit**

```bash
git add studio54-service/app/models/user_listening_session.py studio54-service/app/models/tests/test_user_listening_session_import.py
git commit -m "feat: add UserListeningSession model"
```

---

## Task 2: Alembic Migration 062

**Files:**
- Create: `studio54-service/alembic/versions/20260503_0100_062_add_user_listening_sessions.py`

- [ ] **Step 1: Write the migration**

```python
# studio54-service/alembic/versions/20260503_0100_062_add_user_listening_sessions.py
"""Add user_listening_sessions table

Revision ID: 20260503_0100_062
Revises: 20260426_0100_061
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260503_0100_062'
down_revision = '20260426_0100_061'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_listening_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_type', sa.String(10), nullable=False),
        sa.Column('book_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('books.id', ondelete='CASCADE'), nullable=True),
        sa.Column('series_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('series.id', ondelete='CASCADE'), nullable=True),
        sa.Column('chapter_queue', postgresql.JSON(astext_type=sa.Text()),
                  nullable=False, server_default='[]'),
        sa.Column('current_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('pending_delete_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "(book_id IS NOT NULL AND series_id IS NULL) OR (book_id IS NULL AND series_id IS NOT NULL)",
            name="ck_uls_exactly_one_fk",
        ),
    )
    op.create_index(
        'uq_uls_user_book', 'user_listening_sessions',
        ['user_id', 'book_id'], unique=True,
        postgresql_where=sa.text('series_id IS NULL'),
    )
    op.create_index(
        'uq_uls_user_series', 'user_listening_sessions',
        ['user_id', 'series_id'], unique=True,
        postgresql_where=sa.text('book_id IS NULL'),
    )


def downgrade():
    op.drop_index('uq_uls_user_series', table_name='user_listening_sessions')
    op.drop_index('uq_uls_user_book', table_name='user_listening_sessions')
    op.drop_table('user_listening_sessions')
```

- [ ] **Step 2: Run migration to verify it applies cleanly**

```bash
cd studio54-service && docker compose exec studio54 alembic upgrade head 2>&1 | tail -10
```

Expected: `Running upgrade 20260426_0100_061 -> 20260503_0100_062, Add user_listening_sessions table`

- [ ] **Step 3: Verify table exists**

```bash
docker compose exec db psql -U studio54 -d studio54 -c "\d user_listening_sessions" 2>&1 | head -20
```

Expected: column list including `chapter_queue`, `current_index`, `archived_at`, `pending_delete_at`

- [ ] **Step 4: Commit**

```bash
git add studio54-service/alembic/versions/20260503_0100_062_add_user_listening_sessions.py
git commit -m "feat: migration 062 — add user_listening_sessions table"
```

---

## Task 3: Listening Sessions API Router

**Files:**
- Create: `studio54-service/app/api/listening_sessions.py`

- [ ] **Step 1: Write the test file**

```python
# studio54-service/app/api/tests/test_listening_sessions.py
"""Tests for /books/{id}/session and /series/{id}/session endpoints."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.models.user_listening_session import UserListeningSession


def _auth_header(client):
    resp = client.post("/api/v1/auth/login", json={"username": "testuser", "password": "testpass"})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_create_book_session_creates_new(client, db_session, test_book_with_chapters, test_user_token):
    """POST /books/{id}/session creates a new session with full chapter queue."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_type"] == "book"
    assert data["current_index"] == 0
    assert len(data["chapter_queue"]) == len(test_book_with_chapters["chapter_ids"])


def test_create_book_session_is_idempotent(client, db_session, test_book_with_chapters, test_user_token):
    """POST /books/{id}/session returns existing session if one exists."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    r1 = client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    r2 = client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    assert r1.json()["id"] == r2.json()["id"]


def test_get_book_session_not_found(client, test_book_with_chapters, test_user_token):
    """GET /books/{id}/session returns 404 when no session exists."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    resp = client.get(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    assert resp.status_code == 404


def test_patch_book_session_updates_index(client, db_session, test_book_with_chapters, test_user_token):
    """PATCH /books/{id}/session updates current_index."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    resp = client.patch(f"/api/v1/books/{test_book_with_chapters['id']}/session",
                        json={"current_index": 2}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["current_index"] == 2


def test_archive_book_session(client, db_session, test_book_with_chapters, test_user_token):
    """POST /books/{id}/session/archive sets archived_at and pending_delete_at."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    resp = client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session/archive", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["archived_at"] is not None
    assert data["pending_delete_at"] is not None


def test_unarchive_book_session(client, db_session, test_book_with_chapters, test_user_token):
    """DELETE /books/{id}/session/archive clears archived_at and pending_delete_at."""
    headers = {"Authorization": f"Bearer {test_user_token}"}
    client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session", headers=headers)
    client.post(f"/api/v1/books/{test_book_with_chapters['id']}/session/archive", headers=headers)
    resp = client.delete(f"/api/v1/books/{test_book_with_chapters['id']}/session/archive", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["archived_at"] is None
    assert data["pending_delete_at"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd studio54-service && docker compose exec studio54 python -m pytest app/api/tests/test_listening_sessions.py -v 2>&1 | tail -20
```

Expected: errors (router not registered yet)

- [ ] **Step 3: Create the router**

```python
# studio54-service/app/api/listening_sessions.py
"""
Listening Sessions API
POST/GET/PATCH/DELETE for /books/{id}/session and /series/{id}/session
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
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
        .filter(Chapter.book_id == book_id, Chapter.has_file == True)
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
    chapter_ids = []
    for entry in entries:
        if entry.chapter and entry.chapter.has_file:
            chapter_ids.append(str(entry.chapter_id))
    return chapter_ids


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
            UserListeningSession.series_id == None,
        )
        .first()
    )

    if session:
        # Reactivate if archived
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
            UserListeningSession.series_id == None,
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
            UserListeningSession.series_id == None,
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
            UserListeningSession.series_id == None,
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
            UserListeningSession.series_id == None,
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
            UserListeningSession.series_id == None,
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
            UserListeningSession.book_id == None,
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
            UserListeningSession.book_id == None,
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
            UserListeningSession.book_id == None,
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
            UserListeningSession.book_id == None,
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
            UserListeningSession.book_id == None,
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
            UserListeningSession.book_id == None,
        )
        .first()
    )
    if session:
        db.delete(session)
        db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd studio54-service && docker compose exec studio54 python -m pytest app/api/tests/test_listening_sessions.py -v 2>&1 | tail -20
```

Expected: all passing (after router is registered in next task)

- [ ] **Step 5: Commit**

```bash
git add studio54-service/app/api/listening_sessions.py studio54-service/app/api/tests/test_listening_sessions.py
git commit -m "feat: add listening sessions API router"
```

---

## Task 4: Register Router in main.py

**Files:**
- Modify: `studio54-service/app/main.py`

- [ ] **Step 1: Find the import block and router registration area**

Open `studio54-service/app/main.py`. The imports are at the top and router registrations are around line 600–669.

- [ ] **Step 2: Add import and registration**

In the imports section (after the other API imports), add:
```python
from app.api import listening_sessions as listening_sessions_api
```

In the router registration section (after `book_playlists_api` around line 663), add:
```python
app.include_router(listening_sessions_api.router, prefix="/api/v1", tags=["listening-sessions"])
```

- [ ] **Step 3: Verify the endpoint is reachable**

```bash
cd studio54-service && docker compose exec studio54 python -c "from app.main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'session' in r])"
```

Expected: list including `/api/v1/books/{book_id}/session` and `/api/v1/series/{series_id}/session`

- [ ] **Step 4: Commit**

```bash
git add studio54-service/app/main.py
git commit -m "feat: register listening-sessions router in main.py"
```

---

## Task 5: Nightly Cleanup Task

**Files:**
- Modify: `studio54-service/app/tasks/monitoring_tasks.py`
- Modify: `studio54-service/app/tasks/celery_app.py`

- [ ] **Step 1: Write the failing test**

```python
# studio54-service/app/tasks/tests/test_cleanup_sessions.py
"""Test the nightly listening session cleanup task."""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from app.tasks.monitoring_tasks import cleanup_expired_listening_sessions


def test_cleanup_deletes_sessions_past_pending_delete_at(db_session, test_user):
    from app.models.user_listening_session import UserListeningSession
    import uuid

    # Create a session that should be deleted
    expired = UserListeningSession(
        user_id=test_user.id,
        session_type="book",
        book_id=uuid.uuid4(),
        chapter_queue=[],
        current_index=0,
        archived_at=datetime.now(timezone.utc) - timedelta(days=8),
        pending_delete_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    # Create a session that should NOT be deleted (pending_delete_at in future)
    active = UserListeningSession(
        user_id=test_user.id,
        session_type="book",
        book_id=uuid.uuid4(),
        chapter_queue=[],
        current_index=0,
        archived_at=datetime.now(timezone.utc) - timedelta(days=2),
        pending_delete_at=datetime.now(timezone.utc) + timedelta(days=5),
    )
    db_session.add_all([expired, active])
    db_session.commit()

    expired_id = expired.id
    active_id = active.id

    with patch("app.tasks.monitoring_tasks.SessionLocal", return_value=db_session):
        cleanup_expired_listening_sessions()

    remaining = db_session.query(UserListeningSession).filter(
        UserListeningSession.id.in_([expired_id, active_id])
    ).all()
    remaining_ids = {str(r.id) for r in remaining}
    assert str(expired_id) not in remaining_ids
    assert str(active_id) in remaining_ids
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd studio54-service && docker compose exec studio54 python -m pytest app/tasks/tests/test_cleanup_sessions.py -v 2>&1 | tail -10
```

Expected: AttributeError or ImportError (function doesn't exist yet)

- [ ] **Step 3: Add cleanup task to monitoring_tasks.py**

At the end of `studio54-service/app/tasks/monitoring_tasks.py`, add:

```python
@shared_task(name="app.tasks.monitoring_tasks.cleanup_expired_listening_sessions")
def cleanup_expired_listening_sessions():
    """
    Hard-delete UserListeningSession rows where pending_delete_at < now.

    Runs nightly at 2am. For book sessions, also deletes BookProgress.
    For series sessions, deletes BookProgress for all books in the series.
    """
    from app.models.user_listening_session import UserListeningSession
    from app.models.book_progress import BookProgress
    from app.models.book_playlist import BookPlaylist, BookPlaylistChapter

    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired = db.query(UserListeningSession).filter(
            UserListeningSession.pending_delete_at < now
        ).all()

        book_sessions_deleted = 0
        series_sessions_deleted = 0

        for session in expired:
            if session.session_type == "book" and session.book_id:
                db.query(BookProgress).filter(
                    BookProgress.user_id == session.user_id,
                    BookProgress.book_id == session.book_id,
                ).delete(synchronize_session=False)
                book_sessions_deleted += 1

            elif session.session_type == "series" and session.series_id:
                playlist = db.query(BookPlaylist).filter(
                    BookPlaylist.series_id == session.series_id
                ).first()
                if playlist:
                    book_ids = db.query(BookPlaylistChapter.chapter_id).filter(
                        BookPlaylistChapter.playlist_id == playlist.id
                    ).subquery()
                    # Get distinct book_ids from chapters in this playlist
                    from app.models.chapter import Chapter
                    chapter_book_ids = (
                        db.query(Chapter.book_id)
                        .filter(Chapter.id.in_(
                            db.query(BookPlaylistChapter.chapter_id)
                            .filter(BookPlaylistChapter.playlist_id == playlist.id)
                        ))
                        .distinct()
                        .all()
                    )
                    for (bid,) in chapter_book_ids:
                        db.query(BookProgress).filter(
                            BookProgress.user_id == session.user_id,
                            BookProgress.book_id == bid,
                        ).delete(synchronize_session=False)
                series_sessions_deleted += 1

            db.delete(session)

        db.commit()
        logger.info(
            f"Session cleanup: deleted {book_sessions_deleted} book sessions, "
            f"{series_sessions_deleted} series sessions"
        )

    except Exception as e:
        logger.error(f"Session cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()
```

- [ ] **Step 4: Add module include and beat entry to celery_app.py**

In `celery_app.py`, in the `include` list, add `"app.tasks.monitoring_tasks"` if not already present (it is: check line 41). It's already included, so no change needed there.

In the `beat_schedule` dict, add:

```python
        # ── Nightly cleanup (monitoring queue) ─────────────────
        "cleanup-expired-sessions": {
            "task": "app.tasks.monitoring_tasks.cleanup_expired_listening_sessions",
            "schedule": crontab(hour=2, minute=0),
            "options": {"expires": 3600, "queue": "monitoring"},
        },
```

- [ ] **Step 5: Run cleanup tests to verify they pass**

```bash
cd studio54-service && docker compose exec studio54 python -m pytest app/tasks/tests/test_cleanup_sessions.py -v 2>&1 | tail -10
```

Expected: PASSED

- [ ] **Step 6: Commit**

```bash
git add studio54-service/app/tasks/monitoring_tasks.py studio54-service/app/tasks/celery_app.py studio54-service/app/tasks/tests/test_cleanup_sessions.py
git commit -m "feat: add nightly listening session cleanup task (Celery beat)"
```

---

## Task 6: Frontend — listeningSessionApi in client.ts

**Files:**
- Modify: `studio54-web/src/api/client.ts`

- [ ] **Step 1: Add ListeningSession type and API object**

Find the `bookProgressApi` export in `client.ts` (around line 2889). After the `storageMountsApi` export, add the following at the appropriate place in the file (near other book-related APIs):

```typescript
// ==================== LISTENING SESSIONS ====================

export interface ListeningSession {
  id: string
  session_type: 'book' | 'series'
  book_id: string | null
  series_id: string | null
  chapter_queue: string[]
  current_index: number
  archived_at: string | null
  pending_delete_at: string | null
  created_at: string | null
  updated_at: string | null
}

export const listeningSessionApi = {
  // Book sessions
  getBook: async (bookId: string): Promise<ListeningSession | null> => {
    try {
      const { data } = await api.get(`/books/${bookId}/session`)
      return data
    } catch (e: any) {
      if (e.response?.status === 404) return null
      throw e
    }
  },

  createBook: async (bookId: string): Promise<ListeningSession> => {
    const { data } = await api.post(`/books/${bookId}/session`)
    return data
  },

  patchBook: async (bookId: string, currentIndex: number): Promise<ListeningSession> => {
    const { data } = await api.patch(`/books/${bookId}/session`, { current_index: currentIndex })
    return data
  },

  archiveBook: async (bookId: string): Promise<ListeningSession> => {
    const { data } = await api.post(`/books/${bookId}/session/archive`)
    return data
  },

  unarchiveBook: async (bookId: string): Promise<ListeningSession> => {
    const { data } = await api.delete(`/books/${bookId}/session/archive`)
    return data
  },

  // Series sessions
  getSeries: async (seriesId: string): Promise<ListeningSession | null> => {
    try {
      const { data } = await api.get(`/series/${seriesId}/session`)
      return data
    } catch (e: any) {
      if (e.response?.status === 404) return null
      throw e
    }
  },

  createSeries: async (seriesId: string): Promise<ListeningSession> => {
    const { data } = await api.post(`/series/${seriesId}/session`)
    return data
  },

  patchSeries: async (seriesId: string, currentIndex: number): Promise<ListeningSession> => {
    const { data } = await api.patch(`/series/${seriesId}/session`, { current_index: currentIndex })
    return data
  },

  archiveSeries: async (seriesId: string): Promise<ListeningSession> => {
    const { data } = await api.post(`/series/${seriesId}/session/archive`)
    return data
  },

  unarchiveSeries: async (seriesId: string): Promise<ListeningSession> => {
    const { data } = await api.delete(`/series/${seriesId}/session/archive`)
    return data
  },
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add studio54-web/src/api/client.ts
git commit -m "feat: add listeningSessionApi to client.ts"
```

---

## Task 7: PlayerContext — Session State Fields + playBook Always Opens Pop-out

**Files:**
- Modify: `studio54-web/src/hooks/usePlayerBroadcast.ts`
- Modify: `studio54-web/src/contexts/PlayerContext.tsx`

This task has two sub-goals:
1. Add `sessionType`, `sessionEntityId`, `sessionCurrentIndex` to PlayerState so PopOutPlayer can PATCH the session on chapter advance.
2. Make `playBook()` always open the pop-out (using `PLAY_BOOK_REQUEST_KEY` for a newly opened window).

- [ ] **Step 1: Update usePlayerBroadcast.ts — add session fields and PLAY_BOOK_REQUEST_KEY**

In `studio54-web/src/hooks/usePlayerBroadcast.ts`, find `SerializedPlayerState` (around line 10) and add three fields:

```typescript
export interface SerializedPlayerState {
  currentTrack: PlayerTrack | null
  queue: PlayerTrack[]
  history: PlayerTrack[]
  playHistory: PlayerTrack[]
  isPlaying: boolean
  repeatMode: RepeatMode
  shuffleMode: boolean
  volume: number
  isMuted: boolean
  bookId: string | null
  chapterId: string | null
  currentTime: number
  sessionType: 'book' | 'series' | null       // NEW
  sessionEntityId: string | null               // NEW
  sessionCurrentIndex: number                  // NEW
}
```

Also add the constant after the existing constants:
```typescript
export const PLAY_BOOK_REQUEST_KEY = 'studio54_play_book_request'
```

- [ ] **Step 2: Update PlayerState in PlayerContext.tsx**

Find the `PlayerState` type definition (around line 33) and add three fields:
```typescript
  sessionType: 'book' | 'series' | null
  sessionEntityId: string | null
  sessionCurrentIndex: number
```

- [ ] **Step 3: Update PlayerAction PLAY_BOOK type**

Find the PLAY_BOOK action type (line 51) and extend it:
```typescript
  | { type: 'PLAY_BOOK'; tracks: PlayerTrack[]; startIndex: number; bookId: string; sessionType?: 'book' | 'series'; sessionEntityId?: string }
```

- [ ] **Step 4: Update the PLAY_BOOK reducer case**

Find the `case 'PLAY_BOOK':` block (around line 189) and add the session fields to the returned state:
```typescript
    case 'PLAY_BOOK': {
      const tracksWithFile = action.tracks.filter(t => t.has_file).map(t => ({ ...t, isBookChapter: true }))
      if (tracksWithFile.length === 0) return state
      const startIdx = Math.min(action.startIndex, tracksWithFile.length - 1)
      const remaining = tracksWithFile.slice(startIdx + 1)
      return {
        ...state,
        currentTrack: tracksWithFile[startIdx],
        queue: remaining,
        playHistory: [],
        isPlaying: true,
        shuffleMode: false,
        history: state.currentTrack
          ? [state.currentTrack, ...state.history].slice(0, 50)
          : state.history,
        bookId: action.bookId,
        chapterId: tracksWithFile[startIdx].id,
        sessionType: action.sessionType ?? null,
        sessionEntityId: action.sessionEntityId ?? null,
        sessionCurrentIndex: startIdx,
      }
    }
```

- [ ] **Step 5: Update the NEXT reducer case to increment sessionCurrentIndex**

Find the `case 'NEXT':` block and add `sessionCurrentIndex` increment. Look for where `chapterId` is updated for book sessions (around line 147) and add alongside it:
```typescript
        chapterId: state.bookId ? nextTrack.id : state.chapterId,
        sessionCurrentIndex: state.bookId ? state.sessionCurrentIndex + 1 : state.sessionCurrentIndex,
```

- [ ] **Step 6: Update initial state and RESTORE_STATE case**

In the initial state object (around line 273), add:
```typescript
    sessionType: null,
    sessionEntityId: null,
    sessionCurrentIndex: 0,
```

In the `case 'RESTORE_STATE':` block (around line 230), add:
```typescript
        sessionType: action.state.sessionType ?? null,
        sessionEntityId: action.state.sessionEntityId ?? null,
        sessionCurrentIndex: action.state.sessionCurrentIndex ?? 0,
```

- [ ] **Step 7: Update serializePlayerState in usePlayerBroadcast.ts**

Find `serializePlayerState` and add the new fields to the return value:
```typescript
export function serializePlayerState(state: PlayerState, currentTime: number): SerializedPlayerState {
  return {
    ...
    sessionType: state.sessionType,
    sessionEntityId: state.sessionEntityId,
    sessionCurrentIndex: state.sessionCurrentIndex,
  }
}
```

- [ ] **Step 8: Update playBook() to always open pop-out**

Find the `playBook` useCallback (line 532). Replace it with:

```typescript
  const playBook = useCallback((
    tracks: PlayerTrack[],
    startIndex: number,
    bookId: string,
    sessionType?: 'book' | 'series',
    sessionEntityId?: string,
  ) => {
    const payload = { tracks, startIndex, bookId, sessionType, sessionEntityId }
    if (isPopOutOpen) {
      // Pop-out already open — send via BroadcastChannel
      send({ type: 'PLAY_BOOK', payload })
    } else {
      // Store request for the newly opened pop-out to read on init
      try {
        localStorage.setItem(PLAY_BOOK_REQUEST_KEY, JSON.stringify(payload))
      } catch {}
      // Open pop-out (it will read PLAY_BOOK_REQUEST_KEY on mount)
      const win = window.open('/player', 'studio54-player', 'width=420,height=250,resizable=yes')
      if (win) {
        popOutWindowRef.current = win
        setIsPopOutOpen(true)
      }
    }
  }, [isPopOutOpen, send])
```

Also update the `playBook` type in the context value (around line 349):
```typescript
  playBook: (tracks: PlayerTrack[], startIndex: number, bookId: string, sessionType?: 'book' | 'series', sessionEntityId?: string) => void
```

- [ ] **Step 9: Update play-book-playlist handler to pass sessionType/sessionEntityId**

Find `handlePlayBookPlaylist` (around line 820). After building the tracks array, update the `dispatch` call to include session info:

```typescript
        const firstBookId = playlist.chapters.find((ch: BookPlaylistChapter) => ch.book_id)?.book_id
        if (firstBookId) {
          playBook(tracks, 0, firstBookId, 'series', detail.seriesId)
        } else {
          dispatch({ type: 'PLAY_ALBUM', tracks, startIndex: 0 })
        }
```

Note: change `dispatch({ type: 'PLAY_BOOK', ... })` to use `playBook()` so the pop-out opens. This requires `playBook` to be in scope — it is, since this effect is inside `PlayerProvider` after `playBook` is defined. But since `handlePlayBookPlaylist` is defined in a `useEffect`, we need to include `playBook` in the deps array or use a ref. The simplest fix: move the `play-book-playlist` useEffect to AFTER the `playBook` definition, and include `playBook` in its dependency array.

- [ ] **Step 10: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 11: Commit**

```bash
git add studio54-web/src/hooks/usePlayerBroadcast.ts studio54-web/src/contexts/PlayerContext.tsx
git commit -m "feat: add session state to PlayerContext; playBook always opens pop-out"
```

---

## Task 8: PopOutPlayer — Init from PLAY_BOOK_REQUEST_KEY

**Files:**
- Modify: `studio54-web/src/pages/PopOutPlayer.tsx`

When the pop-out opens fresh for a book/series play request, it reads from `PLAY_BOOK_REQUEST_KEY` and dispatches PLAY_BOOK immediately.

- [ ] **Step 1: Add import for PLAY_BOOK_REQUEST_KEY**

At the top of `PopOutPlayer.tsx`, update the import from `usePlayerBroadcast`:
```typescript
import { usePlayerBroadcast, POPOUT_STATE_KEY, POPUP_OPEN_FLAG_KEY, PLAY_BOOK_REQUEST_KEY, serializePlayerState, type BroadcastMessage } from '../hooks/usePlayerBroadcast'
```

Also add `listeningSessionApi` to the client.ts import:
```typescript
import { tracksApi, playlistsApi, booksApi, bookProgressApi, nowPlayingApi, listeningSessionApi } from '../api/client'
```

- [ ] **Step 2: Add init effect to handle PLAY_BOOK_REQUEST_KEY**

After the existing `handleBroadcastMessage` / `broadcastSend` setup and BEFORE the audio source management section, add:

```typescript
  // On mount: check if a PLAY_BOOK request was queued before this window opened
  useEffect(() => {
    const raw = localStorage.getItem(PLAY_BOOK_REQUEST_KEY)
    if (!raw) return
    localStorage.removeItem(PLAY_BOOK_REQUEST_KEY)
    try {
      const req = JSON.parse(raw)
      dispatch({
        type: 'PLAY_BOOK',
        tracks: req.tracks,
        startIndex: req.startIndex ?? 0,
        bookId: req.bookId,
        sessionType: req.sessionType,
        sessionEntityId: req.sessionEntityId,
      })
    } catch {}
  }, [])
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add studio54-web/src/pages/PopOutPlayer.tsx
git commit -m "feat: pop-out player reads PLAY_BOOK_REQUEST_KEY on init"
```

---

## Task 9: PopOutPlayer — Position Save on Pause + beforeunload sendBeacon

**Files:**
- Modify: `studio54-web/src/pages/PopOutPlayer.tsx`

The spec requires saving position on pause and on window close (via sendBeacon). The main PlayerContext already does this for the non-pop-out case (guarded by `IS_POPOUT_WINDOW`). We add the same triggers specifically for the pop-out.

- [ ] **Step 1: Add pause save effect**

After the existing `heartbeatRef` / sendHeartbeat block (around line 312), add:

```typescript
  // Save book progress on pause (pop-out only — main window does this in PlayerContext)
  const prevIsPlayingRef = useRef(state.isPlaying)
  useEffect(() => {
    const wasPaused = prevIsPlayingRef.current && !state.isPlaying
    prevIsPlayingRef.current = state.isPlaying
    if (!wasPaused || !state.bookId || !state.chapterId) return
    const positionMs = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
    bookProgressApi.upsert(state.bookId, {
      chapter_id: state.chapterId,
      position_ms: positionMs,
    }).catch(() => {})
  }, [state.isPlaying, state.bookId, state.chapterId])
```

- [ ] **Step 2: Update the beforeunload handler to use sendBeacon**

Find the existing `beforeunload` useEffect (around line 136–149). Replace the handler body to add a sendBeacon call after the existing localStorage save:

```typescript
  useEffect(() => {
    const handler = () => {
      const ct = audioRef.current?.currentTime ?? 0
      const serialized = serializePlayerState(state, ct)
      try {
        localStorage.setItem(POPOUT_STATE_KEY, JSON.stringify(serialized))
      } catch {}
      localStorage.removeItem(POPUP_OPEN_FLAG_KEY)
      broadcastSend({ type: 'POPOUT_CLOSED' })

      // Save book progress via sendBeacon (guaranteed delivery on unload)
      if (state.bookId && state.chapterId) {
        const token = localStorage.getItem('studio54_token')
        const baseUrl = (import.meta as any).env?.VITE_API_URL || '/api/v1'
        const url = `${baseUrl}/books/${state.bookId}/progress`
        const positionMs = Math.round(ct * 1000)
        const body = JSON.stringify({
          chapter_id: state.chapterId,
          position_ms: positionMs,
        })
        const headers = { type: 'application/json' }
        const blob = new Blob([body], headers)
        // sendBeacon doesn't support custom headers; use token as query param
        navigator.sendBeacon(`${url}?token=${encodeURIComponent(token || '')}`, blob)
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [state, broadcastSend])
```

Note: the backend `/books/{book_id}/progress` endpoint must support `?token=` query param authentication. Check the `books.py` API to confirm — if it uses `get_current_user` dependency with Bearer only, you may need to add a fallback. If the existing heartbeat already works via `?token=` query param, no backend change is needed. Check by grepping for `token` in the books progress endpoint; if not, add query-param token support (see note below).

**Note on token auth for sendBeacon:** If the progress endpoint only accepts Bearer tokens, add this fallback to the book progress POST endpoint in `books.py`:
```python
from fastapi import Query as QueryParam
# In the endpoint signature, add:
token: Optional[str] = QueryParam(None)
# Then in get_current_user, if credentials is None and token param is present, use it.
```
A cleaner alternative: move the sendBeacon to POST to a dedicated `/books/{id}/progress/beacon` endpoint that reads the token from the request body. However, the simplest approach is: check if the chapter stream already uses `?token=` (it does, line 154–157 in PopOutPlayer). If the progress POST endpoint is protected by the same auth middleware that supports `?token=` via `HTTPBearer`, it will work automatically. Confirm by checking `get_current_user` in `app/auth.py` — it uses `HTTPBearer` which only reads from the header. For sendBeacon support, the cleanest solution is to include the token in the beacon body and add a separate lightweight endpoint:

```python
# In books.py (or listening_sessions.py)
@router.post("/books/{book_id}/progress/beacon")
async def save_progress_beacon(
    book_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Receives sendBeacon progress saves. Authenticates via token in body."""
    body = await request.json()
    token = body.get("token")
    if not token:
        raise HTTPException(status_code=401)
    from app.auth import JWT_SECRET, JWT_ALGORITHM
    from jose import jwt as jose_jwt, JWTError
    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401)
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401)
    # Save progress
    from app.models.book_progress import BookProgress
    ...
```

**Decision for this plan:** use the `/books/{book_id}/progress/beacon` approach to keep auth clean. Update the sendBeacon call in PopOutPlayer accordingly:
```typescript
      if (state.bookId && state.chapterId) {
        const token = localStorage.getItem('studio54_token') || ''
        const baseUrl = (import.meta as any).env?.VITE_API_URL || '/api/v1'
        const url = `${baseUrl}/books/${state.bookId}/progress/beacon`
        const positionMs = Math.round(ct * 1000)
        const blob = new Blob(
          [JSON.stringify({ chapter_id: state.chapterId, position_ms: positionMs, token })],
          { type: 'application/json' }
        )
        navigator.sendBeacon(url, blob)
      }
```

And add the beacon endpoint to `studio54-service/app/api/books.py` (or a new `book_progress_api.py`). Find the existing progress endpoints in `books.py` and add after them:

```python
@router.post("/books/{book_id}/progress/beacon")
async def save_progress_beacon(
    book_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Lightweight endpoint for navigator.sendBeacon() unload saves. Token in body."""
    from jose import jwt as jose_jwt, JWTError
    from app.auth import JWT_SECRET, JWT_ALGORITHM
    from app.models.book_progress import BookProgress
    
    body = await request.json()
    token = body.get("token", "")
    chapter_id_str = body.get("chapter_id", "")
    position_ms = body.get("position_ms", 0)
    
    if not token or not chapter_id_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    try:
        bid = uuid.UUID(book_id)
        cid = uuid.UUID(chapter_id_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    
    existing = db.query(BookProgress).filter(
        BookProgress.user_id == user.id,
        BookProgress.book_id == bid,
    ).first()
    if existing:
        existing.chapter_id = cid
        existing.position_ms = position_ms
    else:
        db.add(BookProgress(user_id=user.id, book_id=bid, chapter_id=cid, position_ms=position_ms))
    db.commit()
    return {"ok": True}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add studio54-web/src/pages/PopOutPlayer.tsx studio54-service/app/api/books.py
git commit -m "feat: pop-out saves position on pause and via sendBeacon on close"
```

---

## Task 10: PopOutPlayer — Session current_index PATCH on Chapter Advance

**Files:**
- Modify: `studio54-web/src/pages/PopOutPlayer.tsx`

When a chapter ends and the player advances (NEXT), PATCH the session's `current_index`.

- [ ] **Step 1: Update handleEnded to PATCH session after chapter advance**

Find `handleEnded` (around line 314). Before the existing `dispatch({ type: 'NEXT' })` call, compute and PATCH the new index. The new `sessionCurrentIndex` from the reducer will be `state.sessionCurrentIndex + 1` after NEXT fires, so we use that value:

```typescript
  const handleEnded = useCallback(() => {
    if (currentTrack?.id) {
      if (state.bookId) {
        booksApi.recordChapterPlay(currentTrack.id).catch(() => {})

        const isLastChapter = queue.length === 0 && repeatMode === 'off'
        bookProgressApi.upsert(state.bookId, {
          chapter_id: currentTrack.id,
          position_ms: 0,
          ...(isLastChapter ? { completed: true } : {}),
        }).catch(() => {})

        // PATCH session current_index if a session is tracked
        if (state.sessionEntityId && !isLastChapter) {
          const nextIndex = state.sessionCurrentIndex + 1
          if (state.sessionType === 'book') {
            listeningSessionApi.patchBook(state.sessionEntityId, nextIndex).catch(() => {})
          } else if (state.sessionType === 'series') {
            listeningSessionApi.patchSeries(state.sessionEntityId, nextIndex).catch(() => {})
          }
        }
      } else {
        tracksApi.recordPlay(currentTrack.id).catch(() => {})
      }
    }
    if (repeatMode === 'one') {
      const audio = audioRef.current
      if (audio) {
        audio.currentTime = 0
        audio.play().catch(() => {})
      }
    } else {
      dispatch({ type: 'NEXT' })
    }
  }, [repeatMode, currentTrack?.id, state.bookId, state.sessionEntityId, state.sessionType, state.sessionCurrentIndex, queue.length, dispatch])
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add studio54-web/src/pages/PopOutPlayer.tsx
git commit -m "feat: PATCH session current_index on chapter advance in pop-out"
```

---

## Task 11: PopOutPlayer — Sleep Timer + Snooze Popup

**Files:**
- Modify: `studio54-web/src/pages/PopOutPlayer.tsx`

All sleep timer state is local — no persistence across player close.

- [ ] **Step 1: Add sleep timer state and types**

At the top of the `PopOutPlayer` function, after existing state declarations, add:

```typescript
  // Sleep timer state (all local, no persistence)
  const [sleepTimerEndsAt, setSleepTimerEndsAt] = useState<number | null>(null)
  const [sleepTimerEndOfChapter, setSleepTimerEndOfChapter] = useState(false)
  const [sleepTimerDisplay, setSleepTimerDisplay] = useState('')
  const [showSnoozePopup, setShowSnoozePopup] = useState(false)
  const [showSleepMenu, setShowSleepMenu] = useState(false)
  const [customMinutes, setCustomMinutes] = useState('')
  const sleepTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sleepTickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const snoozeAutoCloseRef = useRef<ReturnType<typeof setTimeout> | null>(null)
```

- [ ] **Step 2: Add sleep timer helper functions**

After the existing `formatTime` helper, add:

```typescript
  const clearSleepTimer = () => {
    if (sleepTimerRef.current) { clearTimeout(sleepTimerRef.current); sleepTimerRef.current = null }
    if (sleepTickRef.current) { clearInterval(sleepTickRef.current); sleepTickRef.current = null }
    setSleepTimerEndsAt(null)
    setSleepTimerEndOfChapter(false)
    setSleepTimerDisplay('')
  }

  const fireSleepTimer = useCallback(() => {
    clearSleepTimer()
    // Save position before pausing
    if (state.bookId && state.chapterId) {
      const positionMs = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
      bookProgressApi.upsert(state.bookId, {
        chapter_id: state.chapterId,
        position_ms: positionMs,
      }).catch(() => {})
    }
    dispatch({ type: 'PAUSE' })
    setShowSnoozePopup(true)
    // Auto-dismiss after 30 seconds
    snoozeAutoCloseRef.current = setTimeout(() => setShowSnoozePopup(false), 30000)
  }, [state.bookId, state.chapterId, dispatch])

  const setSleepTimer = useCallback((minutes: number) => {
    clearSleepTimer()
    setSleepTimerEndOfChapter(false)
    const endsAt = Date.now() + minutes * 60 * 1000
    setSleepTimerEndsAt(endsAt)
    setShowSleepMenu(false)

    sleepTimerRef.current = setTimeout(fireSleepTimer, minutes * 60 * 1000)
    sleepTickRef.current = setInterval(() => {
      const remaining = Math.max(0, Math.round((endsAt - Date.now()) / 1000))
      const m = Math.floor(remaining / 60)
      const s = remaining % 60
      setSleepTimerDisplay(`${m}:${s.toString().padStart(2, '0')}`)
      if (remaining === 0) {
        if (sleepTickRef.current) { clearInterval(sleepTickRef.current); sleepTickRef.current = null }
      }
    }, 1000)
  }, [fireSleepTimer])

  const setSleepTimerEndOfChapterMode = useCallback(() => {
    clearSleepTimer()
    setSleepTimerEndOfChapter(true)
    setShowSleepMenu(false)
  }, [])

  const snooze15 = useCallback(() => {
    if (snoozeAutoCloseRef.current) { clearTimeout(snoozeAutoCloseRef.current); snoozeAutoCloseRef.current = null }
    setShowSnoozePopup(false)
    dispatch({ type: 'RESUME' })
    setSleepTimer(15)
  }, [dispatch, setSleepTimer])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (sleepTimerRef.current) clearTimeout(sleepTimerRef.current)
      if (sleepTickRef.current) clearInterval(sleepTickRef.current)
      if (snoozeAutoCloseRef.current) clearTimeout(snoozeAutoCloseRef.current)
    }
  }, [])
```

- [ ] **Step 3: Intercept handleEnded for end-of-chapter mode**

In `handleEnded`, add an early-exit check for end-of-chapter mode at the very top:

```typescript
  const handleEnded = useCallback(() => {
    // End-of-chapter sleep timer intercept
    if (sleepTimerEndOfChapter) {
      setSleepTimerEndOfChapter(false)
      fireSleepTimer()
      return
    }
    // ... existing handleEnded logic ...
  }, [sleepTimerEndOfChapter, fireSleepTimer, repeatMode, currentTrack?.id, ...existing deps...])
```

- [ ] **Step 4: Add sleep timer button and popover to the JSX**

The pop-out player has two rendering paths (small and expanded) — you need to add the timer icon to both. Find the controls section in each path and add a timer icon button. Also add the popover overlay and snooze popup as siblings to the controls.

Import `FiBell` from `react-icons/fi` at the top of the file.

**Sleep menu popover** (add as a positioned overlay above/near the controls):
```tsx
      {/* Sleep Timer */}
      <div className="relative">
        <button
          title={sleepTimerEndsAt ? `Sleep: ${sleepTimerDisplay}` : sleepTimerEndOfChapter ? 'Sleep: end of chapter' : 'Sleep timer'}
          onClick={() => setShowSleepMenu(v => !v)}
          className={`p-1 rounded transition-colors ${sleepTimerEndsAt || sleepTimerEndOfChapter ? 'text-[#FF1493]' : 'text-gray-400 hover:text-white'}`}
        >
          <FiBell className="w-4 h-4" />
          {(sleepTimerEndsAt || sleepTimerEndOfChapter) && (
            <span className="ml-1 text-xs">
              {sleepTimerEndOfChapter ? 'EOC' : sleepTimerDisplay}
            </span>
          )}
        </button>

        {showSleepMenu && (
          <div className="absolute bottom-8 right-0 bg-[#1a1a2e] border border-gray-700 rounded-lg shadow-xl p-3 z-50 w-52">
            <p className="text-xs text-gray-400 mb-2 font-medium">Sleep Timer</p>
            <div className="grid grid-cols-2 gap-1 mb-2">
              {[15, 30, 45, 60].map(m => (
                <button key={m} onClick={() => setSleepTimer(m)}
                  className="px-2 py-1 text-sm rounded bg-gray-800 hover:bg-[#FF1493] transition-colors text-white">
                  {m} min
                </button>
              ))}
            </div>
            <button onClick={setSleepTimerEndOfChapterMode}
              className="w-full px-2 py-1 text-sm rounded bg-gray-800 hover:bg-[#FF1493] transition-colors text-white mb-2">
              End of chapter
            </button>
            <div className="flex gap-1">
              <input
                type="number" min="1" max="999"
                value={customMinutes}
                onChange={e => setCustomMinutes(e.target.value)}
                placeholder="_ min"
                className="flex-1 px-2 py-1 text-sm rounded bg-gray-800 text-white border border-gray-600 focus:border-[#FF1493] outline-none"
              />
              <button
                onClick={() => { const m = parseInt(customMinutes); if (m > 0) setSleepTimer(m) }}
                className="px-2 py-1 text-sm rounded bg-[#FF1493] hover:bg-[#FF1493]/80 text-white"
              >
                Set
              </button>
            </div>
            {(sleepTimerEndsAt || sleepTimerEndOfChapter) && (
              <button onClick={clearSleepTimer}
                className="w-full mt-2 px-2 py-1 text-sm rounded bg-gray-700 hover:bg-gray-600 text-white transition-colors">
                Cancel timer
              </button>
            )}
          </div>
        )}
      </div>
```

**Snooze popup overlay** (add just before the closing `</div>` of the player wrapper, at the same level as the controls):
```tsx
      {/* Snooze popup */}
      {showSnoozePopup && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70 z-50 rounded-lg">
          <div className="bg-[#1a1a2e] border border-gray-700 rounded-xl p-4 text-center shadow-xl">
            <p className="text-white font-medium mb-3">Sleep timer ended</p>
            <div className="flex gap-2 justify-center">
              <button
                onClick={snooze15}
                className="px-4 py-2 rounded-lg bg-[#FF1493] hover:bg-[#FF1493]/80 text-white font-medium transition-colors"
              >
                + 15 minutes
              </button>
              <button
                onClick={() => { if (snoozeAutoCloseRef.current) clearTimeout(snoozeAutoCloseRef.current); setShowSnoozePopup(false) }}
                className="px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
```

- [ ] **Step 5: Close sleep menu when clicking outside**

Add a `useEffect` to close the sleep menu on outside click:
```typescript
  useEffect(() => {
    if (!showSleepMenu) return
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest('[data-sleep-menu]')) setShowSleepMenu(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showSleepMenu])
```

Add `data-sleep-menu` attribute to the sleep menu's container `<div className="relative">` wrapper.

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add studio54-web/src/pages/PopOutPlayer.tsx
git commit -m "feat: add sleep timer with snooze popup to pop-out player"
```

---

## Task 12: BookDetail — Session Fetch + Mark as Read + Undo Banner

**Files:**
- Modify: `studio54-web/src/pages/BookDetail.tsx`

- [ ] **Step 1: Add listeningSessionApi import**

Find the existing import of `bookProgressApi` in BookDetail.tsx and add `listeningSessionApi`:
```typescript
import { bookProgressApi, listeningSessionApi, type ListeningSession } from '../api/client'
```

- [ ] **Step 2: Add session state and fetch**

After existing state declarations, add:
```typescript
  const [listeningSession, setListeningSession] = useState<ListeningSession | null>(null)
  const [sessionLoading, setSessionLoading] = useState(false)
  const [markingFinished, setMarkingFinished] = useState(false)
  const [showMarkFinishedDialog, setShowMarkFinishedDialog] = useState(false)
```

Add a `useEffect` to fetch the session when the book loads. Place it after the `bookProgress` fetch effects:

```typescript
  useEffect(() => {
    if (!book?.id) return
    setSessionLoading(true)
    listeningSessionApi.getBook(book.id)
      .then(session => setListeningSession(session))
      .catch(() => setListeningSession(null))
      .finally(() => setSessionLoading(false))
  }, [book?.id])
```

- [ ] **Step 3: Update handlePlayBook to create/use session and open pop-out**

Replace the existing `handlePlayBook` function with one that:
1. Creates a session if none exists (using the session's `current_index`)
2. Calls `player.playBook()` with `sessionType='book'` and `sessionEntityId=book.id`

```typescript
  const handlePlayBook = async (fromBeginning = false) => {
    const tracks = buildPlayerTracks()
    if (tracks.length === 0) return

    if (fromBeginning) {
      bookProgressApi.reset(book.id).catch(() => {})
      // Reset session index to 0
      let session = listeningSession
      if (session) {
        listeningSessionApi.patchBook(book.id, 0).catch(() => {})
        setListeningSession({ ...session, current_index: 0 })
      }
      refetchProgress()
      player.playBook(tracks, 0, book.id, 'book', book.id)
      return
    }

    // Ensure session exists; use its current_index for resume
    let session = listeningSession
    if (!session) {
      try {
        session = await listeningSessionApi.createBook(book.id)
        setListeningSession(session)
      } catch {
        // Fall back to progress-based resume
      }
    }

    const startIdx = session ? Math.min(session.current_index, tracks.length - 1) : 0

    // Also seek to millisecond position from bookProgress
    if (bookProgress?.position_ms && bookProgress.position_ms > 0) {
      const seekAfterLoad = () => {
        const audio = player.audioRef.current
        if (audio) {
          const doSeek = () => {
            audio.currentTime = bookProgress.position_ms / 1000
            audio.removeEventListener('canplay', doSeek)
          }
          audio.addEventListener('canplay', doSeek)
        }
      }
      setTimeout(seekAfterLoad, 100)
    }

    player.playBook(tracks, startIdx, book.id, 'book', book.id)
  }
```

- [ ] **Step 4: Add Mark as Read button and confirmation dialog**

Find where "Play Book" buttons appear (around line 1105 and 1217). Near each "Play Book" button, add a "Mark as Read" button:

```tsx
              {/* Mark as Read */}
              {listeningSession && !listeningSession.archived_at && (
                <button
                  onClick={() => setShowMarkFinishedDialog(true)}
                  className="px-4 py-2 rounded-lg font-medium transition-colors bg-gray-700 hover:bg-gray-600 text-white text-sm"
                >
                  Mark as Read
                </button>
              )}
```

Add the confirmation dialog (place near other dialog components in JSX):
```tsx
      {showMarkFinishedDialog && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a2e] border border-gray-700 rounded-xl p-6 max-w-md mx-4 shadow-xl">
            <h3 className="text-white font-semibold text-lg mb-2">Mark as finished?</h3>
            <p className="text-gray-400 mb-4">
              Mark <span className="text-white">{book.title}</span> as finished? Your progress will be
              kept for 7 days in case you need to recover it.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowMarkFinishedDialog(false)}
                className="px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors"
              >
                Cancel
              </button>
              <button
                disabled={markingFinished}
                onClick={async () => {
                  setMarkingFinished(true)
                  try {
                    const updated = await listeningSessionApi.archiveBook(book.id)
                    setListeningSession(updated)
                    setShowMarkFinishedDialog(false)
                  } catch {
                    // toast error if desired
                  } finally {
                    setMarkingFinished(false)
                  }
                }}
                className="px-4 py-2 rounded-lg bg-[#FF1493] hover:bg-[#FF1493]/80 text-white font-medium transition-colors"
              >
                {markingFinished ? 'Saving…' : 'Mark as Read'}
              </button>
            </div>
          </div>
        </div>
      )}
```

- [ ] **Step 5: Add undo banner**

Just below the hero/cover-art section (above the chapter list), add:
```tsx
      {/* Archived session undo banner */}
      {listeningSession?.archived_at && listeningSession.pending_delete_at && (
        <div className="mx-4 mb-4 px-4 py-3 bg-gray-800/80 border border-gray-700 rounded-lg flex items-center justify-between">
          <span className="text-gray-300 text-sm">
            You marked this as finished on{' '}
            {new Date(listeningSession.archived_at).toLocaleDateString()}.{' '}
            Undo until {new Date(listeningSession.pending_delete_at).toLocaleDateString()}.
          </span>
          <button
            onClick={async () => {
              try {
                const updated = await listeningSessionApi.unarchiveBook(book.id)
                setListeningSession(updated)
              } catch {}
            }}
            className="ml-4 px-3 py-1 rounded bg-[#FF1493] hover:bg-[#FF1493]/80 text-white text-sm transition-colors"
          >
            Undo
          </button>
        </div>
      )}
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add studio54-web/src/pages/BookDetail.tsx
git commit -m "feat: BookDetail — session fetch, Mark as Read, undo banner"
```

---

## Task 13: SeriesDetail — Session Fetch + Mark Series as Complete + Undo Banner

**Files:**
- Modify: `studio54-web/src/pages/SeriesDetail.tsx`

- [ ] **Step 1: Add listeningSessionApi import**

```typescript
import { listeningSessionApi, type ListeningSession } from '../api/client'
```

- [ ] **Step 2: Add session state and fetch**

```typescript
  const [listeningSession, setListeningSession] = useState<ListeningSession | null>(null)
  const [markingFinished, setMarkingFinished] = useState(false)
  const [showMarkFinishedDialog, setShowMarkFinishedDialog] = useState(false)
```

```typescript
  useEffect(() => {
    if (!id) return
    listeningSessionApi.getSeries(id)
      .then(session => setListeningSession(session))
      .catch(() => setListeningSession(null))
  }, [id])
```

- [ ] **Step 3: Update Play Series handler to create session and open pop-out**

Find the "Play Series" button's `onClick` handler (around line 653). Replace with:

```tsx
                  onClick={async () => {
                    const firstChapter = playlist.chapters?.[0]
                    if (!firstChapter?.file_path) return

                    // Ensure session exists
                    let session = listeningSession
                    if (!session) {
                      try {
                        session = await listeningSessionApi.createSeries(id)
                        setListeningSession(session)
                      } catch {}
                    }

                    // Dispatch the play-book-playlist event with session context
                    window.dispatchEvent(new CustomEvent('play-book-playlist', {
                      detail: {
                        seriesId: id,
                        playlistId: playlist.id,
                        sessionStartIndex: session?.current_index ?? 0,
                      }
                    }))
                  }}
```

- [ ] **Step 4: Update play-book-playlist handler in PlayerContext to use sessionStartIndex**

In `PlayerContext.tsx`, find `handlePlayBookPlaylist` (around line 820). Update it to use `detail.sessionStartIndex` when provided:

```typescript
    const handlePlayBookPlaylist = async (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (!detail?.playlistId) return

      try {
        const playlist = await bookPlaylistsApi.get(detail.seriesId)
        if (!playlist?.chapters?.length) return

        const tracks: PlayerTrack[] = playlist.chapters
          .filter((ch: BookPlaylistChapter) => ch.has_file && ch.file_path)
          .map((ch: BookPlaylistChapter) => ({
            id: ch.chapter_id,
            title: ch.chapter_title,
            track_number: ch.chapter_number ?? undefined,
            duration_ms: ch.duration_ms,
            has_file: true,
            file_path: ch.file_path,
            artist_name: playlist.series_name || playlist.name || undefined,
            album_title: ch.book_title || undefined,
            album_cover_art_url: ch.book_cover_art_url || undefined,
            isBookChapter: true,
          }))

        if (tracks.length === 0) return

        const startIndex = detail.sessionStartIndex ?? 0
        const firstBookId = playlist.chapters.find((ch: BookPlaylistChapter) => ch.book_id)?.book_id
        if (firstBookId) {
          playBook(tracks, startIndex, firstBookId, 'series', detail.seriesId)
        } else {
          dispatch({ type: 'PLAY_ALBUM', tracks, startIndex: 0 })
        }
      } catch (err) {
        console.error('Failed to play book playlist:', err)
      }
    }
```

- [ ] **Step 5: Add Mark Series as Complete button**

Near the "Play Series" button, add:
```tsx
              {listeningSession && !listeningSession.archived_at && (
                <button
                  onClick={() => setShowMarkFinishedDialog(true)}
                  className="px-4 py-2 rounded-lg font-medium transition-colors bg-gray-700 hover:bg-gray-600 text-white text-sm"
                >
                  Mark Series as Complete
                </button>
              )}
```

Add the dialog:
```tsx
      {showMarkFinishedDialog && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a2e] border border-gray-700 rounded-xl p-6 max-w-md mx-4 shadow-xl">
            <h3 className="text-white font-semibold text-lg mb-2">Mark series as complete?</h3>
            <p className="text-gray-400 mb-4">
              Mark <span className="text-white">{series.name}</span> as complete? Your progress will be
              kept for 7 days in case you need to recover it.
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowMarkFinishedDialog(false)}
                className="px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors">
                Cancel
              </button>
              <button
                disabled={markingFinished}
                onClick={async () => {
                  setMarkingFinished(true)
                  try {
                    const updated = await listeningSessionApi.archiveSeries(id)
                    setListeningSession(updated)
                    setShowMarkFinishedDialog(false)
                  } catch {} finally {
                    setMarkingFinished(false)
                  }
                }}
                className="px-4 py-2 rounded-lg bg-[#FF1493] hover:bg-[#FF1493]/80 text-white font-medium transition-colors"
              >
                {markingFinished ? 'Saving…' : 'Mark as Complete'}
              </button>
            </div>
          </div>
        </div>
      )}
```

- [ ] **Step 6: Add undo banner for archived series session**

Near the top of the series detail content area, add:
```tsx
      {listeningSession?.archived_at && listeningSession.pending_delete_at && (
        <div className="mx-4 mb-4 px-4 py-3 bg-gray-800/80 border border-gray-700 rounded-lg flex items-center justify-between">
          <span className="text-gray-300 text-sm">
            You marked this as complete on{' '}
            {new Date(listeningSession.archived_at).toLocaleDateString()}.{' '}
            Undo until {new Date(listeningSession.pending_delete_at).toLocaleDateString()}.
          </span>
          <button
            onClick={async () => {
              try {
                const updated = await listeningSessionApi.unarchiveSeries(id)
                setListeningSession(updated)
              } catch {}
            }}
            className="ml-4 px-3 py-1 rounded bg-[#FF1493] hover:bg-[#FF1493]/80 text-white text-sm transition-colors"
          >
            Undo
          </button>
        </div>
      )}
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd studio54-web && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add studio54-web/src/pages/SeriesDetail.tsx studio54-web/src/contexts/PlayerContext.tsx
git commit -m "feat: SeriesDetail — session fetch, Mark Series as Complete, undo banner"
```

---

## Task 14: Docker Rebuild and Smoke Test

**Files:** none (operational)

- [ ] **Step 1: Rebuild and restart both containers**

```bash
cd /home/tesimmons/Studio54
docker compose build --no-cache studio54 studio54-web && docker compose up -d studio54 studio54-web
```

- [ ] **Step 2: Verify migration ran**

```bash
docker compose exec studio54 alembic current 2>&1 | tail -5
```

Expected: `20260503_0100_062 (head)`

- [ ] **Step 3: Smoke test — create a book session**

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"your_user","password":"your_pass"}' | jq -r '.access_token')

# Pick any book ID from your DB
BOOK_ID=$(docker compose exec db psql -U studio54 -d studio54 -t -c "SELECT id FROM books LIMIT 1" | tr -d ' ')

# Create session
curl -s -X POST "http://localhost:8000/api/v1/books/${BOOK_ID}/session" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

Expected: JSON with `session_type: "book"`, `chapter_queue: [...]`, `current_index: 0`

- [ ] **Step 4: Smoke test — sleep timer visible in pop-out**

Open the app, navigate to a book detail page, click "Play Book". Verify:
- Pop-out player opens
- A bell icon (🔔) appears in the player controls
- Clicking it shows the sleep timer popover with preset buttons and custom input

- [ ] **Step 5: Smoke test — pause saves position**

In the pop-out, play for 30+ seconds then pause. Check the DB:
```bash
docker compose exec db psql -U studio54 -d studio54 -c \
  "SELECT position_ms FROM book_progress WHERE book_id='${BOOK_ID}' LIMIT 1"
```

Expected: non-zero position_ms

- [ ] **Step 6: Smoke test — Mark as Read**

On the book detail page, click "Mark as Read", confirm the dialog. Verify the undo banner appears.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: rebuild and verify audiobook session + sleep timer features"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Section 1 — `user_listening_sessions` table with all columns (Tasks 1–2)
- ✅ Section 2 — Position save on pause (Task 9), beforeunload sendBeacon (Task 9), sleep timer stop (Task 11)
- ✅ Section 3 — Sleep timer with presets + custom + end-of-chapter + snooze popup (Task 11)
- ✅ Section 4 — Play Book / Play Series always open pop-out (Tasks 7–8, 12–13); session fetch + resume at current_index; PATCH on advance (Task 10)
- ✅ Section 5 — Mark as Read / Mark Series as Complete (Tasks 12–13); undo banner; nightly cleanup job (Task 5)

**Type consistency:**
- `sessionType / sessionEntityId / sessionCurrentIndex` defined in Task 7, used in Tasks 8, 10, 12, 13
- `PLAY_BOOK_REQUEST_KEY` defined in Task 7 (usePlayerBroadcast.ts), imported in Tasks 7 and 8
- `listeningSessionApi` defined in Task 6, imported in Tasks 12, 13
- `ListeningSession` interface defined in Task 6, used in Tasks 12, 13
- `handlePlayBookPlaylist` updated in both Task 7 (PlayerContext) and Task 13 (SessionDetail reference)

**Placeholder scan:** No TBDs or incomplete sections. The sendBeacon `/books/{id}/progress/beacon` endpoint is fully specified inline in Task 9.
