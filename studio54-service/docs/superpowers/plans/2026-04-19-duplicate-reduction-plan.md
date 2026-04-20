# Duplicate File Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Celery job that finds duplicate audio files by MusicBrainz track ID, keeps the highest-quality copy (bitrate primary, FLAC > M4A > MP3 tiebreaker), moves the rest to a dated staging directory under the configured recycle bin path, and records each removal in a `duplicate_recycle_bin` DB table. A REST API exposes listing, individual/bulk delete, individual/bulk restore, and manual purge. A daily beat task auto-purges entries past their expiry.

**Architecture:** `DuplicateRecycle` SQLAlchemy model backed by a new Alembic migration. Quality scoring and group-finding are pure functions in the task module (easy to unit-test). The Celery task iterates duplicate groups in batches of 500, moves files with `shutil.move`, and writes DB records transactionally per file. The FastAPI router handles all review-workflow endpoints. Auto-purge runs via a daily beat task that calls a shared purge helper also exposed through the API.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Celery, PostgreSQL, Python `shutil` / `pathlib`, pytest with SQLite fixture (`db_session`).

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `app/models/duplicate_recycle.py` | Create | `DuplicateRecycle` ORM model |
| `app/models/job_state.py` | Modify | Add `DEDUPLICATE` to `JobType` |
| `alembic/versions/20260419_0300_060_add_duplicate_recycle_bin.py` | Create | Schema migration |
| `app/tasks/deduplicate_task.py` | Create | Quality scoring, dedup logic, Celery task, purge helper |
| `app/tasks/celery_app.py` | Modify | Add task to `include`, `task_routes`, and `beat_schedule` |
| `app/api/duplicate_recycle.py` | Create | All review-workflow API endpoints + job trigger |
| `app/main.py` | Modify | Register `duplicate_recycle` router |
| `app/tasks/tests/test_deduplicate_task.py` | Create | Unit tests for quality scoring and dedup logic |
| `app/services/tests/test_duplicate_recycle_api.py` | Create | API endpoint tests |

---

## Task 1: Model, Migration, and JobType

**Files:**
- Create: `app/models/duplicate_recycle.py`
- Create: `alembic/versions/20260419_0300_060_add_duplicate_recycle_bin.py`
- Modify: `app/models/job_state.py`

- [ ] **Step 1: Write the failing model import test**

```python
# app/tasks/tests/test_deduplicate_task.py
import pytest

def test_duplicate_recycle_model_importable():
    from app.models.duplicate_recycle import DuplicateRecycle
    assert DuplicateRecycle.__tablename__ == "duplicate_recycle_bin"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py::test_duplicate_recycle_model_importable -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the model**

```python
# app/models/duplicate_recycle.py
"""DuplicateRecycle — tracks files moved to staging during deduplication."""
import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class DuplicateRecycleStatus(str, enum.Enum):
    PENDING_REVIEW = "pending_review"
    PERMANENTLY_DELETED = "permanently_deleted"
    RESTORED = "restored"


class DuplicateRecycle(Base):
    __tablename__ = "duplicate_recycle_bin"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    musicbrainz_trackid = Column(String(36), nullable=False)
    original_file_path = Column(Text, nullable=False)
    staging_file_path = Column(Text, nullable=False)
    kept_file_path = Column(Text, nullable=False)
    removed_bitrate_kbps = Column(Integer, nullable=True)
    removed_format = Column(String(20), nullable=True)
    kept_bitrate_kbps = Column(Integer, nullable=True)
    kept_format = Column(String(20), nullable=True)
    recycled_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), nullable=False, default="pending_review")
    restored_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dup_recycle_status", "status"),
        Index("ix_dup_recycle_expires", "expires_at"),
        Index("ix_dup_recycle_trackid", "musicbrainz_trackid"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py::test_duplicate_recycle_model_importable -v
```
Expected: PASS

- [ ] **Step 5: Add DEDUPLICATE to JobType**

In `app/models/job_state.py`, add one line to the `JobType` enum:

```python
class JobType(str, enum.Enum):
    ALBUM_SEARCH = "album_search"
    DOWNLOAD_MONITOR = "download_monitor"
    IMPORT_DOWNLOAD = "import_download"
    LIBRARY_SCAN = "library_scan"
    ARTIST_SYNC = "artist_sync"
    METADATA_REFRESH = "metadata_refresh"
    IMAGE_FETCH = "image_fetch"
    CLEANUP = "cleanup"
    DEDUPLICATE = "deduplicate"   # ← add this line
```

- [ ] **Step 6: Create the migration**

```python
# alembic/versions/20260419_0300_060_add_duplicate_recycle_bin.py
"""Add duplicate_recycle_bin table

Revision ID: 20260419_0300_060
Revises: 20260419_0200_059
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

revision = '20260419_0300_060'
down_revision = '20260419_0200_059'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'duplicate_recycle_bin',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('musicbrainz_trackid', sa.String(36), nullable=False),
        sa.Column('original_file_path', sa.Text(), nullable=False),
        sa.Column('staging_file_path', sa.Text(), nullable=False),
        sa.Column('kept_file_path', sa.Text(), nullable=False),
        sa.Column('removed_bitrate_kbps', sa.Integer(), nullable=True),
        sa.Column('removed_format', sa.String(20), nullable=True),
        sa.Column('kept_bitrate_kbps', sa.Integer(), nullable=True),
        sa.Column('kept_format', sa.String(20), nullable=True),
        sa.Column('recycled_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(30), nullable=False,
                  server_default='pending_review'),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_dup_recycle_status', 'duplicate_recycle_bin', ['status'])
    op.create_index('ix_dup_recycle_expires', 'duplicate_recycle_bin', ['expires_at'])
    op.create_index('ix_dup_recycle_trackid', 'duplicate_recycle_bin', ['musicbrainz_trackid'])

    # Also add DEDUPLICATE to job_state job_type enum
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'deduplicate'")


def downgrade():
    op.drop_table('duplicate_recycle_bin')
```

- [ ] **Step 7: Run migration**

```bash
docker exec studio54-service alembic upgrade head
```
Expected: `Running upgrade 20260419_0200_059 -> 20260419_0300_060, Add duplicate_recycle_bin table`

- [ ] **Step 8: Commit**

```bash
git add app/models/duplicate_recycle.py \
        app/models/job_state.py \
        alembic/versions/20260419_0300_060_add_duplicate_recycle_bin.py \
        app/tasks/tests/test_deduplicate_task.py
git commit -m "feat: add DuplicateRecycle model, migration, and DEDUPLICATE job type"
```

---

## Task 2: Quality Scoring and Group-Finding Functions

**Files:**
- Create: `app/tasks/deduplicate_task.py` (scoring functions only)
- Modify: `app/tasks/tests/test_deduplicate_task.py`

- [ ] **Step 1: Write failing tests for quality_score and pick_winner**

Add to `app/tasks/tests/test_deduplicate_task.py`:

```python
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _make_lf(bitrate, fmt, size=1000000):
    lf = MagicMock()
    lf.id = uuid.uuid4()
    lf.bitrate_kbps = bitrate
    lf.format = fmt
    lf.file_size_bytes = size
    lf.file_path = f"/music/{uuid.uuid4()}.{fmt}"
    lf.musicbrainz_trackid = "abc123"
    return lf


def test_quality_score_higher_bitrate_wins():
    from app.tasks.deduplicate_task import quality_score
    flac_low = _make_lf(800, "flac")
    flac_high = _make_lf(1200, "flac")
    assert quality_score(flac_high) > quality_score(flac_low)


def test_quality_score_format_breaks_tie():
    from app.tasks.deduplicate_task import quality_score
    flac = _make_lf(320, "flac")
    mp3 = _make_lf(320, "mp3")
    assert quality_score(flac) > quality_score(mp3)


def test_quality_score_format_order():
    from app.tasks.deduplicate_task import quality_score
    flac = _make_lf(320, "flac")
    m4a = _make_lf(320, "m4a")
    mp3 = _make_lf(320, "mp3")
    assert quality_score(flac) > quality_score(m4a) > quality_score(mp3)


def test_quality_score_size_final_tiebreak():
    from app.tasks.deduplicate_task import quality_score
    big = _make_lf(320, "mp3", size=50_000_000)
    small = _make_lf(320, "mp3", size=10_000_000)
    assert quality_score(big) > quality_score(small)


def test_pick_winner_selects_highest_quality():
    from app.tasks.deduplicate_task import pick_winner
    low = _make_lf(128, "mp3")
    mid = _make_lf(320, "mp3")
    high = _make_lf(1000, "flac")
    winner, losers = pick_winner([low, mid, high])
    assert winner is high
    assert set(losers) == {low, mid}


def test_pick_winner_single_file_returns_no_losers():
    from app.tasks.deduplicate_task import pick_winner
    only = _make_lf(320, "mp3")
    winner, losers = pick_winner([only])
    assert winner is only
    assert losers == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py -k "quality_score or pick_winner" -v
```
Expected: FAIL with `ImportError`

- [ ] **Step 3: Create deduplicate_task.py with scoring functions**

```python
# app/tasks/deduplicate_task.py
"""Duplicate file reduction job for Studio54."""
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.duplicate_recycle import DuplicateRecycle
from app.models.library import LibraryFile
from app.models.media_management import MediaManagementConfig
from app.models.job_state import JobType
from app.tasks.base_task import JobTrackedTask
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
FORMAT_RANK = {"flac": 3, "m4a": 2, "mp3": 1}


def quality_score(lf: LibraryFile) -> tuple:
    """Return a comparable quality tuple: (bitrate, format_rank, file_size)."""
    fmt = (lf.format or "").lower()
    return (lf.bitrate_kbps or 0, FORMAT_RANK.get(fmt, 0), lf.file_size_bytes or 0)


def pick_winner(files: List[LibraryFile]) -> Tuple[LibraryFile, List[LibraryFile]]:
    """Return (best_file, list_of_losers) sorted by quality_score descending."""
    ranked = sorted(files, key=quality_score, reverse=True)
    return ranked[0], ranked[1:]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py -k "quality_score or pick_winner" -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/tasks/deduplicate_task.py app/tasks/tests/test_deduplicate_task.py
git commit -m "feat: add quality scoring and pick_winner functions for deduplication"
```

---

## Task 3: Dedup Celery Task and Purge Helper

**Files:**
- Modify: `app/tasks/deduplicate_task.py`
- Modify: `app/tasks/tests/test_deduplicate_task.py`

- [ ] **Step 1: Write failing tests for the task logic**

Add to `app/tasks/tests/test_deduplicate_task.py`:

```python
def test_run_deduplicate_job_moves_lower_quality_file(db_session, tmp_path):
    """Lower-quality duplicate is moved to staging and a DB record is created."""
    from app.tasks.deduplicate_task import _process_duplicate_group
    from app.models.media_management import MediaManagementConfig
    from app.models.library import LibraryPath

    # Config with recycle bin path
    cfg = MediaManagementConfig(
        id=uuid.uuid4(),
        recycle_bin_path=str(tmp_path),
        recycle_bin_cleanup_days=30,
        auto_cleanup_recycle_bin=True,
    )
    db_session.add(cfg)

    # Library path
    lp = LibraryPath(id=uuid.uuid4(), path="/music", name="Music", library_type="music")
    db_session.add(lp)
    db_session.flush()

    trackid = str(uuid.uuid4())
    staging_dir = tmp_path / "duplicates" / "2026-04-19"
    staging_dir.mkdir(parents=True)

    # Create two real temp files
    hi_file = tmp_path / "hi.flac"
    lo_file = tmp_path / "lo.mp3"
    hi_file.write_bytes(b"hi")
    lo_file.write_bytes(b"lo")

    hi_lf = LibraryFile(
        id=uuid.uuid4(), library_path_id=lp.id,
        file_path=str(hi_file), file_name="hi.flac",
        file_size_bytes=2, file_modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        musicbrainz_trackid=trackid, format="flac", bitrate_kbps=1000,
    )
    lo_lf = LibraryFile(
        id=uuid.uuid4(), library_path_id=lp.id,
        file_path=str(lo_file), file_name="lo.mp3",
        file_size_bytes=1, file_modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        musicbrainz_trackid=trackid, format="mp3", bitrate_kbps=128,
    )
    db_session.add_all([hi_lf, lo_lf])
    db_session.commit()

    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    _process_duplicate_group(
        db=db_session,
        files=[hi_lf, lo_lf],
        staging_dir=staging_dir,
        expires_at=expires_at,
    )
    db_session.commit()

    # lo.mp3 should have been moved
    assert not lo_file.exists()
    records = db_session.query(DuplicateRecycle).all()
    assert len(records) == 1
    assert records[0].kept_file_path == str(hi_file)
    assert records[0].removed_format == "mp3"
    assert records[0].status == "pending_review"


def test_purge_expired_deletes_staging_file(db_session, tmp_path):
    """purge_expired_entries deletes files past expires_at and marks records deleted."""
    from app.tasks.deduplicate_task import purge_expired_entries
    from datetime import datetime, timezone, timedelta

    staging_file = tmp_path / "old.mp3"
    staging_file.write_bytes(b"data")

    past = datetime.now(timezone.utc) - timedelta(days=1)
    record = DuplicateRecycle(
        id=uuid.uuid4(),
        musicbrainz_trackid="abc",
        original_file_path="/music/old.mp3",
        staging_file_path=str(staging_file),
        kept_file_path="/music/kept.flac",
        expires_at=past,
        status="pending_review",
    )
    db_session.add(record)
    db_session.commit()

    purged = purge_expired_entries(db_session)
    db_session.commit()

    assert purged == 1
    assert not staging_file.exists()
    db_session.refresh(record)
    assert record.status == "permanently_deleted"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py -k "process_duplicate or purge_expired" -v
```
Expected: FAIL with `ImportError`

- [ ] **Step 3: Add _process_duplicate_group and purge_expired_entries to deduplicate_task.py**

Append to `app/tasks/deduplicate_task.py` (after `pick_winner`):

```python
def _process_duplicate_group(
    db: Session,
    files: List[LibraryFile],
    staging_dir: Path,
    expires_at: datetime,
) -> int:
    """Move losers to staging and create DuplicateRecycle records. Returns count removed."""
    winner, losers = pick_winner(files)
    removed = 0

    for loser in losers:
        src = Path(loser.file_path)
        dest = staging_dir / f"{loser.id}_{src.name}"

        if src.exists():
            shutil.move(str(src), str(dest))
            staging_path = str(dest)
        else:
            logger.warning(f"Duplicate source missing on disk: {src}")
            staging_path = ""

        record = DuplicateRecycle(
            id=uuid.uuid4(),
            musicbrainz_trackid=loser.musicbrainz_trackid,
            original_file_path=loser.file_path,
            staging_file_path=staging_path,
            kept_file_path=winner.file_path,
            removed_bitrate_kbps=loser.bitrate_kbps,
            removed_format=loser.format,
            kept_bitrate_kbps=winner.bitrate_kbps,
            kept_format=winner.format,
            expires_at=expires_at,
            status="pending_review",
        )
        db.add(record)

        # Unlink loser from any track row
        db.execute(
            text("UPDATE tracks SET has_file = false, file_path = NULL WHERE file_path = :p"),
            {"p": loser.file_path},
        )
        loser.organization_status = "duplicate_removed"
        removed += 1

    return removed


def purge_expired_entries(db: Session) -> int:
    """Permanently delete all pending_review entries past expires_at. Returns count purged."""
    now = datetime.now(timezone.utc)
    expired = db.query(DuplicateRecycle).filter(
        DuplicateRecycle.status == "pending_review",
        DuplicateRecycle.expires_at < now,
    ).all()

    purged = 0
    for entry in expired:
        staging = Path(entry.staging_file_path)
        if entry.staging_file_path and staging.exists():
            staging.unlink()
        elif entry.staging_file_path and not staging.exists():
            logger.warning(f"Staging file missing during purge: {staging}")
        entry.status = "permanently_deleted"
        entry.deleted_at = now
        purged += 1

    return purged
```

- [ ] **Step 4: Add the Celery task and purge task at the bottom of deduplicate_task.py**

```python
@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="deduplicate.run_job",
    max_retries=0,
)
def run_deduplicate_job(self, job_id: str = None):
    """Find duplicate audio files and move lower-quality copies to the staging area."""
    db = self.db

    job_logger = self.init_job_logger("deduplicate", "Duplicate File Reduction")

    config = db.query(MediaManagementConfig).first()
    if not config or not config.recycle_bin_path:
        raise ValueError(
            "recycle_bin_path is not configured. Set it in Media Management settings."
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    staging_dir = Path(config.recycle_bin_path) / "duplicates" / today
    staging_dir.mkdir(parents=True, exist_ok=True)

    expires_at = datetime.now(timezone.utc) + timedelta(days=config.recycle_bin_cleanup_days)

    # Fetch all trackids with more than one file
    rows = db.execute(text("""
        SELECT musicbrainz_trackid
        FROM library_files
        WHERE musicbrainz_trackid IS NOT NULL
          AND library_type = 'music'
        GROUP BY musicbrainz_trackid
        HAVING COUNT(*) > 1
        ORDER BY musicbrainz_trackid
    """)).fetchall()

    total_groups = len(rows)
    job_logger.log_info(f"Found {total_groups} duplicate groups")
    self.update_progress(percent=5.0, items_total=total_groups)

    stats = {"groups_processed": 0, "files_removed": 0, "errors": 0}

    for i, row in enumerate(rows):
        trackid = row[0]
        files = db.query(LibraryFile).filter(
            LibraryFile.musicbrainz_trackid == trackid
        ).all()

        if len(files) < 2:
            continue

        try:
            removed = _process_duplicate_group(db, files, staging_dir, expires_at)
            db.commit()
            stats["groups_processed"] += 1
            stats["files_removed"] += removed
        except Exception as e:
            db.rollback()
            logger.error(f"Error deduplicating trackid {trackid}: {e}")
            stats["errors"] += 1

        if i % 100 == 0:
            self.update_progress(
                percent=5.0 + (i / total_groups) * 90.0,
                items_processed=i,
                items_total=total_groups,
                step=f"Processed {i}/{total_groups} groups",
            )
            job_logger.log_info(f"Progress: {i}/{total_groups} groups | {stats}")

    job_logger.log_info(f"Complete: {stats}")
    self.update_progress(percent=100.0, items_processed=total_groups)
    return stats


@celery_app.task(name="deduplicate.purge_expired")
def purge_expired_duplicates_task():
    """Beat task: purge expired duplicate_recycle_bin entries."""
    db = SessionLocal()
    try:
        purged = purge_expired_entries(db)
        db.commit()
        logger.info(f"Purged {purged} expired duplicate recycle entries")
        return {"purged": purged}
    finally:
        db.close()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py -v
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/tasks/deduplicate_task.py app/tasks/tests/test_deduplicate_task.py
git commit -m "feat: add deduplication Celery task and purge helper"
```

---

## Task 4: API Router

**Files:**
- Create: `app/api/duplicate_recycle.py`
- Create: `app/services/tests/test_duplicate_recycle_api.py`

- [ ] **Step 1: Write failing API tests**

```python
# app/services/tests/test_duplicate_recycle_api.py
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.models.duplicate_recycle import DuplicateRecycle


def _make_record(db, tmp_path, status="pending_review", expired=False):
    staging = tmp_path / f"{uuid.uuid4()}.mp3"
    staging.write_bytes(b"data")
    expires = (
        datetime.now(timezone.utc) - timedelta(days=1)
        if expired
        else datetime.now(timezone.utc) + timedelta(days=30)
    )
    r = DuplicateRecycle(
        id=uuid.uuid4(),
        musicbrainz_trackid=str(uuid.uuid4()),
        original_file_path="/music/dup.mp3",
        staging_file_path=str(staging),
        kept_file_path="/music/kept.flac",
        removed_bitrate_kbps=128,
        removed_format="mp3",
        kept_bitrate_kbps=1000,
        kept_format="flac",
        expires_at=expires,
        status=status,
    )
    db.add(r)
    db.commit()
    return r


def test_list_returns_pending_entries(client, db_session, tmp_path):
    _make_record(db_session, tmp_path)
    resp = client.get("/api/v1/duplicate-recycle-bin")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["items"][0]["status"] == "pending_review"


def test_delete_removes_staging_file(client, db_session, tmp_path):
    r = _make_record(db_session, tmp_path)
    staging = r.staging_file_path
    resp = client.delete(f"/api/v1/duplicate-recycle-bin/{r.id}")
    assert resp.status_code == 200
    import os
    assert not os.path.exists(staging)
    db_session.refresh(r)
    assert r.status == "permanently_deleted"


def test_restore_returns_409_if_original_occupied(client, db_session, tmp_path):
    r = _make_record(db_session, tmp_path)
    # Write a file at the original path so restore would collide
    import os
    os.makedirs(os.path.dirname(r.original_file_path), exist_ok=True)
    open(r.original_file_path, "w").close()
    resp = client.post(f"/api/v1/duplicate-recycle-bin/{r.id}/restore")
    assert resp.status_code == 409


def test_bulk_delete(client, db_session, tmp_path):
    r1 = _make_record(db_session, tmp_path)
    r2 = _make_record(db_session, tmp_path)
    resp = client.request(
        "DELETE",
        "/api/v1/duplicate-recycle-bin/bulk",
        json={"ids": [str(r1.id), str(r2.id)]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker exec studio54-service python -m pytest app/services/tests/test_duplicate_recycle_api.py -v
```
Expected: FAIL with `404` or `ImportError`

- [ ] **Step 3: Create the API router**

```python
# app/api/duplicate_recycle.py
"""Duplicate Recycle Bin — review, restore, and delete duplicate files."""
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_director, require_dj_or_above
from app.database import get_db
from app.models.duplicate_recycle import DuplicateRecycle
from app.models.library import LibraryFile
from app.models.track import Track
from app.models.user import User
from app.security import rate_limit
from app.tasks.deduplicate_task import purge_expired_entries, run_deduplicate_job
from app.models.job_state import JobState, JobStatus, JobType

import logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["duplicate-recycle"])


class DuplicateRecycleItem(BaseModel):
    id: str
    musicbrainz_trackid: str
    original_file_path: str
    staging_file_path: str
    kept_file_path: str
    removed_bitrate_kbps: Optional[int]
    removed_format: Optional[str]
    kept_bitrate_kbps: Optional[int]
    kept_format: Optional[str]
    recycled_at: datetime
    expires_at: datetime
    status: str

    @classmethod
    def from_record(cls, r: DuplicateRecycle) -> "DuplicateRecycleItem":
        return cls(
            id=str(r.id),
            musicbrainz_trackid=r.musicbrainz_trackid,
            original_file_path=r.original_file_path,
            staging_file_path=r.staging_file_path,
            kept_file_path=r.kept_file_path,
            removed_bitrate_kbps=r.removed_bitrate_kbps,
            removed_format=r.removed_format,
            kept_bitrate_kbps=r.kept_bitrate_kbps,
            kept_format=r.kept_format,
            recycled_at=r.recycled_at,
            expires_at=r.expires_at,
            status=r.status,
        )


class BulkIdsRequest(BaseModel):
    ids: List[str]


def _get_entry(db: Session, entry_id: str) -> DuplicateRecycle:
    try:
        uid = UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
    entry = db.query(DuplicateRecycle).filter(DuplicateRecycle.id == uid).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _permanently_delete(db: Session, entry: DuplicateRecycle) -> None:
    if entry.staging_file_path:
        p = Path(entry.staging_file_path)
        if p.exists():
            p.unlink()
        elif not p.exists():
            logger.warning(f"Staging file missing on delete: {p}")
    entry.status = "permanently_deleted"
    entry.deleted_at = datetime.now(timezone.utc)


@router.get("/duplicate-recycle-bin")
@rate_limit("60/minute")
async def list_duplicate_recycle(
    request: Request,
    entry_status: str = Query("pending_review", alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dj_or_above),
):
    q = db.query(DuplicateRecycle).filter(DuplicateRecycle.status == entry_status)
    total = q.count()
    items = q.order_by(DuplicateRecycle.recycled_at.desc()) \
             .offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [DuplicateRecycleItem.from_record(r) for r in items],
    }


@router.delete("/duplicate-recycle-bin/bulk")
@rate_limit("20/minute")
async def bulk_delete_duplicates(
    request: Request,
    body: BulkIdsRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dj_or_above),
):
    deleted = 0
    for entry_id in body.ids:
        try:
            entry = _get_entry(db, entry_id)
            if entry.status == "pending_review":
                _permanently_delete(db, entry)
                deleted += 1
        except HTTPException:
            pass
    db.commit()
    return {"deleted": deleted}


@router.post("/duplicate-recycle-bin/bulk/restore")
@rate_limit("20/minute")
async def bulk_restore_duplicates(
    request: Request,
    body: BulkIdsRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dj_or_above),
):
    results = []
    for entry_id in body.ids:
        try:
            entry = _get_entry(db, entry_id)
            if entry.status != "pending_review":
                results.append({"id": entry_id, "success": False, "error": "Not pending review"})
                continue
            if Path(entry.original_file_path).exists():
                results.append({"id": entry_id, "success": False, "error": "Original path occupied"})
                continue
            _do_restore(db, entry)
            results.append({"id": entry_id, "success": True})
        except HTTPException as e:
            results.append({"id": entry_id, "success": False, "error": e.detail})
    db.commit()
    return {"results": results}


@router.post("/duplicate-recycle-bin/purge-expired")
@rate_limit("5/minute")
async def purge_expired(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_director),
):
    purged = purge_expired_entries(db)
    db.commit()
    return {"purged": purged}


@router.post("/duplicate-recycle-bin/run")
@rate_limit("5/minute")
async def trigger_deduplicate_job(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_director),
):
    """Trigger the deduplication job. Returns job ID."""
    task = run_deduplicate_job.delay()
    return {"job_id": task.id, "status": "queued"}


@router.delete("/duplicate-recycle-bin/{entry_id}")
@rate_limit("30/minute")
async def delete_duplicate(
    request: Request,
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dj_or_above),
):
    entry = _get_entry(db, entry_id)
    if entry.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Entry is already {entry.status}")
    _permanently_delete(db, entry)
    db.commit()
    return {"deleted": True}


@router.post("/duplicate-recycle-bin/{entry_id}/restore")
@rate_limit("30/minute")
async def restore_duplicate(
    request: Request,
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_dj_or_above),
):
    entry = _get_entry(db, entry_id)
    if entry.status != "pending_review":
        raise HTTPException(status_code=400, detail=f"Entry is already {entry.status}")
    if not entry.staging_file_path or not Path(entry.staging_file_path).exists():
        raise HTTPException(status_code=404, detail="Staging file no longer exists")
    if Path(entry.original_file_path).exists():
        raise HTTPException(status_code=409, detail="Original path is already occupied")
    _do_restore(db, entry)
    db.commit()
    return {"restored": True, "path": entry.original_file_path}


def _do_restore(db: Session, entry: DuplicateRecycle) -> None:
    Path(entry.original_file_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(entry.staging_file_path, entry.original_file_path)

    # Re-link library file record
    lf = db.query(LibraryFile).filter(
        LibraryFile.file_path == entry.original_file_path
    ).first()
    if lf:
        lf.organization_status = "unprocessed"

    # Re-link one unlinked track with matching trackid
    track = db.query(Track).filter(
        Track.musicbrainz_id == entry.musicbrainz_trackid,
        Track.has_file == False,
    ).first()
    if track:
        track.has_file = True
        track.file_path = entry.original_file_path

    entry.status = "restored"
    entry.restored_at = datetime.now(timezone.utc)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec studio54-service python -m pytest app/services/tests/test_duplicate_recycle_api.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/duplicate_recycle.py app/services/tests/test_duplicate_recycle_api.py
git commit -m "feat: add duplicate recycle bin API router"
```

---

## Task 5: Wire Up (Celery + FastAPI Registration)

**Files:**
- Modify: `app/tasks/celery_app.py`
- Modify: `app/main.py`

- [ ] **Step 1: Add task to celery_app.py include list**

In `app/tasks/celery_app.py`, add `"app.tasks.deduplicate_task"` to the `include` list:

```python
celery_app = Celery(
    "studio54",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.download_tasks",
        "app.tasks.sync_tasks",
        "app.tasks.library_tasks",
        "app.tasks.fast_ingest_tasks",
        "app.tasks.background_tasks",
        "app.tasks.scan_coordinator_v2",
        "app.tasks.monitoring_tasks",
        "app.tasks.import_tasks",
        "app.tasks.book_import_task",
        "app.tasks.organization_tasks",
        "app.tasks.resolve_unlinked_task",
        "app.tasks.search_tasks",
        "app.tasks.playlist_tasks",
        "app.tasks.deduplicate_task",   # ← add this line
    ]
)
```

- [ ] **Step 2: Add task route for deduplicate tasks**

In the `task_routes` dict in `celery_app.conf.update(...)`, add before the `"app.tasks.library_tasks.*"` line:

```python
"app.tasks.deduplicate_task.*": {"queue": "organization"},
```

- [ ] **Step 3: Add daily beat schedule entry for auto-purge**

In the `beat_schedule` dict, add under the `cleanup-old-logs` entry:

```python
"purge-expired-duplicates": {
    "task": "deduplicate.purge_expired",
    "schedule": 86400.0,  # daily
    "options": {"expires": 82800},
},
```

- [ ] **Step 4: Register the router in main.py**

Find the imports block in `app/main.py` (around line 586). Add `duplicate_recycle` to the import:

```python
from app.api import (
    artists, albums, indexers, muse, download_clients, playlists, library,
    admin, jobs, filesystem, media_management, file_management, duplicate_recycle
)
```

Then after the last `app.include_router(...)` call (around line 656), add:

```python
app.include_router(duplicate_recycle.router, prefix="/api/v1", tags=["duplicate-recycle"])
```

- [ ] **Step 5: Verify the app starts and endpoints are reachable**

```bash
docker cp app/tasks/deduplicate_task.py studio54-service:/app/app/tasks/deduplicate_task.py
docker cp app/api/duplicate_recycle.py studio54-service:/app/app/api/duplicate_recycle.py
docker cp app/models/duplicate_recycle.py studio54-service:/app/app/models/duplicate_recycle.py
docker cp app/tasks/celery_app.py studio54-service:/app/app/tasks/celery_app.py
docker cp app/main.py studio54-service:/app/app/main.py
docker restart studio54-service
```

Wait 10 seconds, then:

```bash
curl -s http://localhost:8010/api/v1/duplicate-recycle-bin \
  -H "X-API-Key: <your-api-key>" | python3 -m json.tool | head -5
```
Expected: `{"total": 0, "page": 1, ...}`

- [ ] **Step 6: Run full test suite**

```bash
docker exec studio54-service python -m pytest app/tasks/tests/test_deduplicate_task.py app/services/tests/test_duplicate_recycle_api.py -v
```
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/tasks/celery_app.py app/main.py
git commit -m "feat: wire up deduplication task and API router"
```
