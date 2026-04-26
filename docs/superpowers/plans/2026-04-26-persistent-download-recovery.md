# Persistent Download Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Studio54 fully persistent in acquiring music — retry failed downloads forever using tiered back-off, log every SABnzbd interaction to a visible album timeline, and give users per-album control over the retry lifecycle.

**Architecture:** DB-driven retry state lives on `albums` (3 new columns). A 30-minute Celery beat task fires fresh indexer searches for albums whose `next_retry_at` has elapsed. `_trigger_auto_retry` is rewritten to first consume `pending_alternates` on the failed `DownloadQueue` row (Phase 1), then fall back to scheduling a progressive-delay fresh search (Phase 2). Four new `DownloadHistory` write sites make failures visible.

**Tech Stack:** Python/SQLAlchemy/Alembic (backend), Celery + beat (scheduling), FastAPI (API), React 18 + TypeScript + TanStack Query 5 (frontend).

---

## File Map

| Action | File |
|--------|------|
| Create | `studio54-service/alembic/versions/20260426_0100_061_add_retry_state.py` |
| Modify | `studio54-service/app/models/download_decision.py` — add `RETRY_SCHEDULED` enum value |
| Modify | `studio54-service/app/models/album.py` — add 3 retry columns |
| Modify | `studio54-service/app/models/download_queue.py` — add `pending_alternates` JSONB column |
| Modify | `studio54-service/app/tasks/download_tasks.py` — rewrite `_trigger_auto_retry`, add 4 event writes, `pending_alternates` store, `retry_scheduled_downloads` task, call `_trigger_auto_retry` from `add_download` all-fail path |
| Modify | `studio54-service/app/tasks/celery_app.py` — register beat schedule |
| Create | `studio54-service/app/api/albums_retry.py` — retry-control + download-history endpoints |
| Modify | `studio54-service/app/api/queue.py` — add `POST /queue/blacklist`, include FAILED in default filter |
| Modify | `studio54-service/app/main.py` — register albums_retry router |
| Create | `studio54-service/tests/integration/test_api_albums_retry.py` — API endpoint tests |
| Modify | `studio54-service/tests/unit/test_download_tasks.py` — new test classes for retry logic |
| Modify | `studio54-web/src/types/index.ts` — add 4 new interfaces |
| Modify | `studio54-web/src/api/client.ts` — add `getDownloadHistory`, `retryControl` to `albumsApi`; add `addToBlacklist` to `queueApi` |
| Create | `studio54-web/src/components/DownloadTimeline.tsx` — new timeline component |
| Modify | `studio54-web/src/pages/AlbumDetail.tsx` — import and render `<DownloadTimeline>` |
| Modify | `studio54-web/src/components/activity/DownloadQueueTab.tsx` — show FAILED by default, rename label |
| Modify | `studio54-web/src/pages/Activity.tsx` — add `RETRY_SCHEDULED` to badge map |

---

### Task 1: Alembic Migration

**Files:**
- Create: `studio54-service/alembic/versions/20260426_0100_061_add_retry_state.py`

- [ ] **Step 1: Write the failing test (verify migration applies cleanly)**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -c "from alembic.config import Config; from alembic import command; c = Config('alembic.ini'); command.check(c)"
```
Expected: no errors (or "No new upgrade operations detected" — confirm current state is clean).

- [ ] **Step 2: Create the migration file**

```python
# studio54-service/alembic/versions/20260426_0100_061_add_retry_state.py
"""Add retry state columns to albums and download_queue

Revision ID: 20260426_0100_061
Revises: 20260419_0300_060
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20260426_0100_061'
down_revision = '20260419_0300_060'
branch_labels = None
depends_on = None


def upgrade():
    # Add new enum value — IF NOT EXISTS prevents failure on re-run
    op.execute("ALTER TYPE downloadeventtype ADD VALUE IF NOT EXISTS 'retry_scheduled'")

    # albums: persistent retry tracking
    op.add_column('albums', sa.Column('retry_enabled', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('albums', sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('albums', sa.Column('download_retry_count', sa.Integer(), nullable=False, server_default='0'))

    # download_queue: un-tried alternate NZBs from the original search
    op.add_column('download_queue', sa.Column('pending_alternates', JSONB(), nullable=True))


def downgrade():
    op.drop_column('download_queue', 'pending_alternates')
    op.drop_column('albums', 'download_retry_count')
    op.drop_column('albums', 'next_retry_at')
    op.drop_column('albums', 'retry_enabled')
```

- [ ] **Step 3: Run the migration**

```bash
cd /home/tesimmons/Studio54/studio54-service
alembic upgrade head
```
Expected: `Running upgrade 20260419_0300_060 -> 20260426_0100_061, Add retry state columns to albums and download_queue`

- [ ] **Step 4: Commit**

```bash
git add studio54-service/alembic/versions/20260426_0100_061_add_retry_state.py
git commit -m "feat: add retry state migration (061)"
```

---

### Task 2: Model Updates

**Files:**
- Modify: `studio54-service/app/models/download_decision.py`
- Modify: `studio54-service/app/models/album.py`
- Modify: `studio54-service/app/models/download_queue.py`

- [ ] **Step 1: Add `RETRY_SCHEDULED` to `DownloadEventType`**

In `studio54-service/app/models/download_decision.py`, find the `DownloadEventType` class (line ~47). It currently ends with `BLACKLISTED = "blacklisted"`. Add the new value:

```python
class DownloadEventType(str, enum.Enum):
    """Types of events in download history"""
    GRABBED = "grabbed"
    IMPORT_STARTED = "import_started"
    IMPORTED = "imported"
    IMPORT_FAILED = "import_failed"
    DOWNLOAD_FAILED = "download_failed"
    DELETED = "deleted"
    BLACKLISTED = "blacklisted"
    RETRY_SCHEDULED = "retry_scheduled"    # ← add this line
```

- [ ] **Step 2: Add 3 retry columns to `Album` model**

In `studio54-service/app/models/album.py`, the existing imports already include `Boolean`, `DateTime`, `Integer`. Find the `searched_at` column (around line 71) and add the three new columns after `searched_at`:

```python
    searched_at = Column(DateTime(timezone=True), nullable=True)
    downloaded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Persistent retry tracking
    retry_enabled = Column(Boolean, nullable=False, default=True, server_default='true')
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    download_retry_count = Column(Integer, nullable=False, default=0, server_default='0')
```

- [ ] **Step 3: Add `pending_alternates` to `DownloadQueue` model**

In `studio54-service/app/models/download_queue.py`, the `JSONB` import is already present. Find `attempted_nzb_guids` (around line 71) and add `pending_alternates` after it:

```python
    # NZB attempt tracking - stores GUIDs of all NZBs tried for this album's download
    attempted_nzb_guids = Column(JSONB, default=list, server_default='[]', nullable=False)

    # Un-tried alternate NZB candidates saved at grab time for fast retry on mid-download failure
    pending_alternates = Column(JSONB, nullable=True)
```

- [ ] **Step 4: Verify SQLite test schema picks up new columns**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/unit/test_download_tasks.py -v -x 2>&1 | head -30
```
Expected: existing tests pass (not fail with "no such column").

- [ ] **Step 5: Commit**

```bash
git add studio54-service/app/models/download_decision.py \
        studio54-service/app/models/album.py \
        studio54-service/app/models/download_queue.py
git commit -m "feat: add retry_enabled/next_retry_at/download_retry_count to Album, pending_alternates to DownloadQueue, RETRY_SCHEDULED event type"
```

---

### Task 3: Rewrite `_trigger_auto_retry` and Add Event Write Sites

**Files:**
- Modify: `studio54-service/app/tasks/download_tasks.py`
- Test: `studio54-service/tests/unit/test_download_tasks.py`

The existing `_trigger_auto_retry` (lines 670–706) caps retries at 3 and re-searches immediately. Replace it entirely. Also add `timedelta` to imports, event writes in `add_download`, event write in `_mark_download_failed`, `pending_alternates` store in `add_download`, and call `_trigger_auto_retry` from the all-candidates-failed path.

- [ ] **Step 1: Write the failing tests**

Append to `studio54-service/tests/unit/test_download_tasks.py`:

```python
class TestTriggerAutoRetryRewrite:
    def test_phase1_uses_pending_alternates(self, db_session):
        from unittest.mock import patch, MagicMock
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.download_decision import DownloadHistory, DownloadEventType

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id,
                                  retry_enabled=True, download_retry_count=0)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status='failed',
            pending_alternates=[{
                'nzb_url': 'http://alt1', 'nzb_title': 'Alt 1',
                'nzb_guid': 'guid-alt-1', 'indexer_id': str(indexer.id),
                'size_bytes': 1000,
            }],
        )

        mock_add = MagicMock()
        with patch('app.tasks.download_tasks.add_download', mock_add):
            _trigger_auto_retry(db_session, download)

        mock_add.apply_async.assert_called_once()
        call_kwargs = mock_add.apply_async.call_args[1]['kwargs']
        assert call_kwargs['nzb_guid'] == 'guid-alt-1'
        assert download.pending_alternates is None

        event = db_session.query(DownloadHistory).filter(
            DownloadHistory.album_id == album.id,
            DownloadHistory.event_type == DownloadEventType.RETRY_SCHEDULED,
        ).first()
        assert event is not None
        assert event.data['phase'] == 'quick'

    def test_phase2_sets_next_retry_at_on_first_failure(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.album import Album
        from app.models.download_decision import DownloadHistory, DownloadEventType
        from datetime import timedelta, timezone
        from datetime import datetime

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id,
                                  retry_enabled=True, download_retry_count=0)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(db_session, album.id, indexer.id, dl_client.id,
                                        status='failed')

        before = datetime.now(timezone.utc)
        _trigger_auto_retry(db_session, download)

        db_session.refresh(album)
        assert album.next_retry_at is not None
        # First retry: ~1 hour delay
        delta = (album.next_retry_at - before).total_seconds()
        assert 3590 < delta < 3620

        event = db_session.query(DownloadHistory).filter(
            DownloadHistory.event_type == DownloadEventType.RETRY_SCHEDULED
        ).first()
        assert event is not None
        assert event.data['phase'] == 'fresh'

    def test_phase2_progressive_delay_at_count_1(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.album import Album
        from datetime import datetime, timezone

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id,
                                  retry_enabled=True, download_retry_count=1)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(db_session, album.id, indexer.id, dl_client.id,
                                        status='failed')

        before = datetime.now(timezone.utc)
        _trigger_auto_retry(db_session, download)

        db_session.refresh(album)
        delta = (album.next_retry_at - before).total_seconds()
        assert 21590 < delta < 21620  # ~6 hours

    def test_skips_when_retry_disabled(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.album import Album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=False)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(db_session, album.id, indexer.id, dl_client.id,
                                        status='failed')

        _trigger_auto_retry(db_session, download)

        db_session.refresh(album)
        assert album.next_retry_at is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/unit/test_download_tasks.py::TestTriggerAutoRetryRewrite -v 2>&1 | tail -20
```
Expected: `FAILED` — AttributeError or AssertionError because `_trigger_auto_retry` is still the old version.

- [ ] **Step 3: Add `timedelta` to imports in `download_tasks.py`**

Find the existing import line (line ~15):
```python
from datetime import datetime, timezone
```
Change it to:
```python
from datetime import datetime, timezone, timedelta
```

- [ ] **Step 4: Replace `_trigger_auto_retry` (lines 670–706) with the new implementation**

Remove the entire old function and replace with:

```python
def _trigger_auto_retry(db: Session, failed_download: DownloadQueue):
    """
    Phase 1: if pending_alternates exist, try them immediately without re-searching.
    Phase 2: schedule a fresh indexer search with progressive back-off.
    Writes a RETRY_SCHEDULED DownloadHistory event on every path.
    Skips entirely when album.retry_enabled is False.
    """
    album = db.query(Album).filter(Album.id == failed_download.album_id).first()
    if not album:
        return

    if not album.retry_enabled:
        logger.info(f"Retry disabled for album '{album.title}', skipping auto-retry")
        return

    # ── Phase 1: pending alternates (no indexer hit needed) ──────────────────
    if failed_download.pending_alternates:
        alternates = list(failed_download.pending_alternates)
        failed_download.pending_alternates = None

        first = alternates[0]
        add_download.apply_async(
            kwargs={
                'album_id': str(album.id),
                'nzb_url': first['nzb_url'],
                'nzb_title': first['nzb_title'],
                'nzb_guid': first['nzb_guid'],
                'indexer_id': first['indexer_id'],
                'size_bytes': first.get('size_bytes', 0),
                'alternate_nzbs': alternates[1:],
            },
            countdown=30,
        )

        try:
            db.add(DownloadHistory(
                album_id=album.id,
                artist_id=failed_download.artist_id,
                event_type=DownloadEventType.RETRY_SCHEDULED,
                message=f"Trying {len(alternates)} alternate NZB(s) — no indexer search needed",
                data={
                    'phase': 'quick',
                    'retry_count': album.download_retry_count,
                    'alternate_count': len(alternates),
                },
            ))
        except Exception as e:
            logger.warning(f"Failed to write RETRY_SCHEDULED event: {e}")
        return

    # ── Phase 2: fresh indexer search with progressive back-off ──────────────
    # retry_num is what download_retry_count will be after the beat task fires
    retry_num = (album.download_retry_count or 0) + 1
    delay_seconds = {1: 3600, 2: 21600}.get(retry_num, 86400)
    album.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

    try:
        db.add(DownloadHistory(
            album_id=album.id,
            artist_id=failed_download.artist_id,
            event_type=DownloadEventType.RETRY_SCHEDULED,
            message=f"Fresh indexer search scheduled for {album.next_retry_at.isoformat()}",
            data={
                'phase': 'fresh',
                'retry_count': retry_num,
                'next_retry_at': album.next_retry_at.isoformat(),
            },
        ))
    except Exception as e:
        logger.warning(f"Failed to write RETRY_SCHEDULED event: {e}")
```

- [ ] **Step 5: Add `pending_alternates` store and GRABBED event write in `add_download()` success branch**

In `add_download()`, find the success branch where the `DownloadQueue` row is created (around line 401–430). The existing code creates `download`, calls `db.add(download)`, updates album status, then `db.commit()`, `db.refresh(download)`. Add `pending_alternates` before `db.commit()`, and the GRABBED event write after:

```python
            download = DownloadQueue(
                album_id=album_id,
                artist_id=album_for_artist.artist_id if album_for_artist else None,
                indexer_id=c_indexer_id,
                download_client_id=download_client.id,
                nzb_title=c_title,
                nzb_guid=c_guid,
                nzb_url=c_url,
                sabnzbd_id=result.nzo_id,
                status=DownloadStatus.QUEUED,
                size_bytes=c_size,
                queued_at=datetime.now(timezone.utc),
                attempted_nzb_guids=all_attempted_guids,
            )
            # Store remaining un-tried candidates for fast retry on mid-download failure
            remaining = candidates[attempt + 1:]
            download.pending_alternates = remaining if remaining else None
            db.add(download)

            # Update album status
            album = db.query(Album).filter(Album.id == album_id).first()
            if album:
                album.status = AlbumStatus.DOWNLOADING

            db.commit()
            db.refresh(download)

            # Write GRABBED event (best-effort — never breaks pipeline)
            try:
                db.add(DownloadHistory(
                    album_id=album_id,
                    artist_id=album_for_artist.artist_id if album_for_artist else None,
                    release_guid=c_guid,
                    release_title=c_title,
                    event_type=DownloadEventType.GRABBED,
                    message=f"Sent to SABnzbd (attempt {attempt + 1} of {len(candidates)})",
                    data={
                        'nzo_id': result.nzo_id,
                        'indexer_id': c_indexer_id,
                        'size_bytes': c_size,
                        'alternate_count': len(candidates) - 1,
                    },
                ))
                db.commit()
            except Exception as e:
                logger.warning(f"Failed to write GRABBED event: {e}")
```

- [ ] **Step 6: Add DOWNLOAD_FAILED event write and `_trigger_auto_retry` call in `add_download()` all-candidates-failed branch**

Find the all-candidates-failed branch (around line 442–475) where the failed `DownloadQueue` row is committed. After `db.commit()`, add:

```python
        db.commit()

        # Write DOWNLOAD_FAILED event and schedule retry
        try:
            db.add(DownloadHistory(
                album_id=album_id,
                artist_id=album_for_artist.artist_id if album_for_artist else None,
                release_guid=candidates[0]['nzb_guid'],
                release_title=candidates[0]['nzb_title'],
                event_type=DownloadEventType.DOWNLOAD_FAILED,
                message=f"All {len(candidates)} candidates rejected by SABnzbd. Last: {last_error}",
                data={
                    'attempted_guids': all_attempted_guids,
                    'total_candidates': len(candidates),
                },
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"Failed to write DOWNLOAD_FAILED event: {e}")

        _trigger_auto_retry(db, download)
        db.commit()  # persist next_retry_at set by _trigger_auto_retry
```

- [ ] **Step 7: Add DOWNLOAD_FAILED event write in `_mark_download_failed()`**

Find `_mark_download_failed` (around line 639). After `download.completed_at = datetime.now(timezone.utc)`, add the event write. The notification block that follows can stay as-is:

```python
def _mark_download_failed(db: Session, download: DownloadQueue, error_message: str,
                          sab_fail_message: str = None, reset_album_to_wanted: bool = False):
    """Mark a download as failed with full error details"""
    download.status = DownloadStatus.FAILED
    download.error_message = error_message
    download.sab_fail_message = sab_fail_message
    download.completed_at = datetime.now(timezone.utc)

    # Write DOWNLOAD_FAILED event (best-effort)
    try:
        db.add(DownloadHistory(
            album_id=download.album_id,
            artist_id=download.artist_id,
            release_guid=download.nzb_guid,
            release_title=download.nzb_title,
            event_type=DownloadEventType.DOWNLOAD_FAILED,
            message=error_message,
            data={
                'sab_fail_message': sab_fail_message,
                'sabnzbd_id': download.sabnzbd_id,
            },
        ))
    except Exception as e:
        logger.warning(f"Failed to write DOWNLOAD_FAILED event: {e}")

    album = db.query(Album).filter(Album.id == download.album_id).first()

    if reset_album_to_wanted:
        if album and album.status in (AlbumStatus.DOWNLOADING, AlbumStatus.SEARCHING):
            album.status = AlbumStatus.WANTED
            logger.info(f"Reset album '{album.title}' to WANTED")

    # Send failure notification when album has retried many times
    if album and (album.download_retry_count or 0) >= 3:
        try:
            from app.services.notification_service import send_notification
            artist = db.query(Artist).filter(Artist.id == album.artist_id).first() if album else None
            send_notification("album_failed", {
                "message": f"Download failed: {artist.name if artist else 'Unknown'} - {album.title if album else 'Unknown'}",
                "artist_name": artist.name if artist else "Unknown",
                "album_title": album.title if album else "Unknown",
                "error": error_message,
                "retries_exhausted": False,
            })
        except Exception as e:
            logger.debug(f"Notification send failed: {e}")
```

Note: The notification condition changes from `download.retry_count >= 3` to `album.download_retry_count >= 3` to reflect the new album-level counter.

- [ ] **Step 8: Run tests**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/unit/test_download_tasks.py::TestTriggerAutoRetryRewrite -v 2>&1 | tail -20
```
Expected: all 4 new tests PASS.

- [ ] **Step 9: Run full unit test suite to check for regressions**

```bash
python -m pytest tests/unit/test_download_tasks.py -v 2>&1 | tail -20
```
Expected: all existing tests still pass.

- [ ] **Step 10: Commit**

```bash
git add studio54-service/app/tasks/download_tasks.py \
        studio54-service/tests/unit/test_download_tasks.py
git commit -m "feat: rewrite _trigger_auto_retry with Phase 1/2 logic, add GRABBED/DOWNLOAD_FAILED/RETRY_SCHEDULED event writes"
```

---

### Task 4: Add `retry_scheduled_downloads` Task and Beat Schedule

**Files:**
- Modify: `studio54-service/app/tasks/download_tasks.py`
- Modify: `studio54-service/app/tasks/celery_app.py`
- Test: `studio54-service/tests/unit/test_download_tasks.py`

- [ ] **Step 1: Write the failing test**

Append to `studio54-service/tests/unit/test_download_tasks.py`:

```python
class TestRetryScheduledDownloads:
    def test_triggers_search_for_due_albums(self, db_session):
        from unittest.mock import patch, MagicMock
        from datetime import datetime, timezone, timedelta
        from app.tasks.download_tasks import _process_retry_scheduled_albums

        artist = create_test_artist(db_session)
        album = create_test_album(
            db_session, artist.id,
            status='wanted',
            retry_enabled=True,
            download_retry_count=1,
            next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        mock_search = MagicMock()
        with patch('app.tasks.download_tasks.search_album', mock_search):
            result = _process_retry_scheduled_albums(db_session)

        assert result['triggered'] == 1
        mock_search.apply_async.assert_called_once()
        db_session.refresh(album)
        assert album.next_retry_at is None        # cleared
        assert album.download_retry_count == 2    # incremented

    def test_skips_albums_not_yet_due(self, db_session):
        from unittest.mock import patch, MagicMock
        from datetime import datetime, timezone, timedelta
        from app.tasks.download_tasks import _process_retry_scheduled_albums

        artist = create_test_artist(db_session)
        create_test_album(
            db_session, artist.id,
            status='wanted',
            retry_enabled=True,
            download_retry_count=0,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        result = _process_retry_scheduled_albums(db_session)
        assert result['triggered'] == 0

    def test_skips_retry_disabled_albums(self, db_session):
        from unittest.mock import patch, MagicMock
        from datetime import datetime, timezone, timedelta
        from app.tasks.download_tasks import _process_retry_scheduled_albums

        artist = create_test_artist(db_session)
        create_test_album(
            db_session, artist.id,
            status='wanted',
            retry_enabled=False,
            next_retry_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )

        result = _process_retry_scheduled_albums(db_session)
        assert result['triggered'] == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/unit/test_download_tasks.py::TestRetryScheduledDownloads -v 2>&1 | tail -10
```
Expected: `FAILED` — `_process_retry_scheduled_albums` does not exist yet.

- [ ] **Step 3: Add `_process_retry_scheduled_albums` helper and `retry_scheduled_downloads` task**

Append after `_trigger_auto_retry` in `studio54-service/app/tasks/download_tasks.py`:

```python
def _process_retry_scheduled_albums(db: Session) -> dict:
    """
    Query albums whose next_retry_at has elapsed and fire a fresh search for each.
    Separated from the Celery task for testability.
    """
    now = datetime.now(timezone.utc)
    due = db.query(Album).filter(
        Album.retry_enabled == True,
        Album.next_retry_at.isnot(None),
        Album.next_retry_at <= now,
        Album.status == AlbumStatus.WANTED,
    ).all()

    if not due:
        return {'albums_due': 0, 'triggered': 0}

    triggered = 0
    for album in due:
        try:
            album.next_retry_at = None  # clear first — prevents double-firing
            album.download_retry_count = (album.download_retry_count or 0) + 1
            db.commit()
            search_album.apply_async(
                args=[str(album.id)],
                kwargs={
                    'job_type': JobType.ALBUM_SEARCH,
                    'entity_type': 'album',
                    'entity_id': str(album.id),
                },
            )
            triggered += 1
            logger.info(
                f"Triggered retry #{album.download_retry_count} for '{album.title}'"
            )
        except Exception as e:
            logger.error(f"Failed to trigger retry for album {album.id}: {e}")
            db.rollback()

    return {'albums_due': len(due), 'triggered': triggered}


@shared_task(name="app.tasks.download_tasks.retry_scheduled_downloads")
def retry_scheduled_downloads():
    """
    Periodic task (every 30 min): fire fresh indexer searches for albums
    whose next_retry_at has elapsed.
    """
    db = get_db()
    try:
        return _process_retry_scheduled_albums(db)
    except Exception as e:
        logger.error(f"retry_scheduled_downloads failed: {e}")
        return {'error': str(e)}
    finally:
        db.close()
```

- [ ] **Step 4: Register in beat schedule in `celery_app.py`**

Find the `from celery import Celery, signals` import in `studio54-service/app/tasks/celery_app.py`. Add crontab to the import:

```python
from celery import Celery, signals
from celery.schedules import crontab
```

Then find `beat_schedule` in the `celery_app.conf.update(...)` block. After the `"verify-downloaded-files"` entry (or at the end of the beat_schedule dict), add:

```python
        "retry-scheduled-downloads": {
            "task": "app.tasks.download_tasks.retry_scheduled_downloads",
            "schedule": crontab(minute="*/30"),
            "options": {"expires": 1500, "queue": "downloads"},
        },
```

- [ ] **Step 5: Run tests**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/unit/test_download_tasks.py::TestRetryScheduledDownloads -v 2>&1 | tail -15
```
Expected: all 3 tests PASS.

- [ ] **Step 6: Run full unit test suite**

```bash
python -m pytest tests/unit/test_download_tasks.py -v 2>&1 | tail -10
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add studio54-service/app/tasks/download_tasks.py \
        studio54-service/app/tasks/celery_app.py \
        studio54-service/tests/unit/test_download_tasks.py
git commit -m "feat: add retry_scheduled_downloads beat task (every 30 min)"
```

---

### Task 5: New API Endpoints

**Files:**
- Create: `studio54-service/app/api/albums_retry.py`
- Modify: `studio54-service/app/api/queue.py`
- Modify: `studio54-service/app/main.py`
- Create: `studio54-service/tests/integration/test_api_albums_retry.py`

- [ ] **Step 1: Write the failing integration tests**

Create `studio54-service/tests/integration/test_api_albums_retry.py`:

```python
"""Integration tests for albums retry-control and download-history endpoints."""
import uuid
from datetime import datetime, timezone
from tests.conftest import create_test_artist, create_test_album


class TestRetryControl:
    def test_disable_retry(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=True)

        resp = client.post(
            f"/api/v1/albums/{album.id}/retry-control",
            json={"retry_enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["retry_enabled"] is False
        assert body["next_retry_at"] is None

    def test_enable_retry_schedules_1h(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=False)

        resp = client.post(
            f"/api/v1/albums/{album.id}/retry-control",
            json={"retry_enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["retry_enabled"] is True
        assert body["next_retry_at"] is not None

    def test_returns_404_for_unknown_album(self, client, db_session):
        resp = client.post(
            f"/api/v1/albums/{uuid.uuid4()}/retry-control",
            json={"retry_enabled": False},
        )
        assert resp.status_code == 404


class TestDownloadHistory:
    def test_returns_empty_events_for_new_album(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)

        resp = client.get(f"/api/v1/albums/{album.id}/download-history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["album_id"] == str(album.id)
        assert body["events"] == []
        assert body["retry_enabled"] is True
        assert body["download_retry_count"] == 0

    def test_returns_history_events(self, client, db_session):
        from app.models.download_decision import DownloadHistory, DownloadEventType

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)

        event = DownloadHistory(
            album_id=album.id,
            artist_id=artist.id,
            event_type=DownloadEventType.DOWNLOAD_FAILED,
            release_title='Artist - Album FLAC',
            message='Encrypted / Passworded',
            occurred_at=datetime.now(timezone.utc),
        )
        db_session.add(event)
        db_session.commit()

        resp = client.get(f"/api/v1/albums/{album.id}/download-history")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "download_failed"
        assert body["events"][0]["message"] == "Encrypted / Passworded"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/integration/test_api_albums_retry.py -v 2>&1 | tail -15
```
Expected: 404 for all — routers not registered yet.

- [ ] **Step 3: Create `app/api/albums_retry.py`**

```python
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
```

- [ ] **Step 4: Add `POST /queue/blacklist` endpoint to `app/api/queue.py`**

Find the existing `@router.get("/blacklist")` endpoint in `studio54-service/app/api/queue.py` (around line 123) and add a `POST /blacklist` endpoint immediately before it:

```python
class BlacklistNzbRequest(BaseModel):
    release_guid: str
    release_title: Optional[str] = None
    album_id: Optional[str] = None
    reason: Optional[str] = None


@router.post("/blacklist")
@rate_limit("30/minute")
async def add_to_blacklist(
    request: Request,
    body: BlacklistNzbRequest,
    current_user: User = Depends(require_dj_or_above),
    db: Session = Depends(get_db),
):
    """Add a release GUID directly to the blacklist (e.g., from download timeline)."""
    from app.models.download_decision import Blacklist
    import uuid as _uuid

    album_id = None
    if body.album_id:
        validate_uuid(body.album_id, "Album ID")
        album_id = _uuid.UUID(body.album_id)

    existing = db.query(Blacklist).filter(Blacklist.release_guid == body.release_guid).first()
    if existing:
        return {"id": str(existing.id), "already_blacklisted": True}

    entry = Blacklist(
        release_guid=body.release_guid,
        release_title=body.release_title,
        album_id=album_id,
        reason=body.reason or "Blacklisted from download timeline",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return {"id": str(entry.id), "already_blacklisted": False}
```

Also add the `Optional` import to `queue.py` if not already present, and `BaseModel` from pydantic.

- [ ] **Step 5: Fix the default queue filter to include FAILED**

In `studio54-service/app/api/queue.py`, find the `elif not include_completed:` block (around line 68) and add `TrackedDownloadState.FAILED` to the list:

```python
    elif not include_completed:
        # Exclude imported/ignored by default but always show FAILED
        query = query.filter(
            TrackedDownload.state.in_([
                TrackedDownloadState.QUEUED,
                TrackedDownloadState.DOWNLOADING,
                TrackedDownloadState.PAUSED,
                TrackedDownloadState.IMPORT_PENDING,
                TrackedDownloadState.IMPORT_BLOCKED,
                TrackedDownloadState.IMPORTING,
                TrackedDownloadState.FAILED,
            ])
        )
```

- [ ] **Step 6: Register the new router in `app/main.py`**

Find the block at the bottom of `studio54-service/app/main.py` that imports routers (around line 584). Add:

```python
from app.api import albums_retry as albums_retry_api
```

Then in the `app.include_router(...)` block, add after the existing albums router:

```python
app.include_router(albums_retry_api.router, prefix="/api/v1", tags=["albums-retry"])
```

- [ ] **Step 7: Run the integration tests**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/integration/test_api_albums_retry.py -v 2>&1 | tail -20
```
Expected: all 5 tests PASS.

- [ ] **Step 8: Run existing integration tests for regressions**

```bash
python -m pytest tests/integration/ -v 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add studio54-service/app/api/albums_retry.py \
        studio54-service/app/api/queue.py \
        studio54-service/app/main.py \
        studio54-service/tests/integration/test_api_albums_retry.py
git commit -m "feat: add retry-control, download-history, and blacklist-nzb API endpoints"
```

---

### Task 6: Frontend Types and API Client

**Files:**
- Modify: `studio54-web/src/types/index.ts`
- Modify: `studio54-web/src/api/client.ts`

- [ ] **Step 1: Add new interfaces to `types/index.ts`**

Open `studio54-web/src/types/index.ts`. Find the end of the existing Download Queue types section (search for `DownloadQueueEntry` or similar). Append the following interfaces:

```typescript
// Album Download Timeline
export interface AlbumDownloadEvent {
  id: string
  event_type: 'grabbed' | 'download_failed' | 'retry_scheduled' | 'imported' | 'import_failed' | 'import_started' | 'deleted' | 'blacklisted' | string
  release_guid: string | null
  release_title: string | null
  message: string | null
  created_at: string | null
  data: Record<string, unknown> | null
}

export interface AlbumDownloadHistory {
  album_id: string
  retry_enabled: boolean
  next_retry_at: string | null
  download_retry_count: number
  events: AlbumDownloadEvent[]
}

export interface RetryControlRequest {
  retry_enabled: boolean
  search_now?: boolean
}

export interface RetryControlResponse {
  album_id: string
  retry_enabled: boolean
  next_retry_at: string | null
  download_retry_count: number
}
```

- [ ] **Step 2: Add imports for new types to `client.ts`**

Open `studio54-web/src/api/client.ts`. At the top where types are imported, add `AlbumDownloadHistory`, `RetryControlRequest`, `RetryControlResponse` to the type imports. The import line should look like:

```typescript
import type {
  // ... existing types ...
  AlbumDownloadHistory,
  RetryControlRequest,
  RetryControlResponse,
} from '../types'
```

(The exact existing import line structure may differ — find the types import block and add the three new types.)

- [ ] **Step 3: Add `getDownloadHistory` and `retryControl` to `albumsApi`**

In `studio54-web/src/api/client.ts`, find `export const albumsApi = {` (around line 401). Inside the object, add after the last existing method:

```typescript
  getDownloadHistory: async (albumId: string): Promise<AlbumDownloadHistory> => {
    const { data } = await api.get(`/albums/${albumId}/download-history`)
    return data
  },

  retryControl: async (albumId: string, req: RetryControlRequest): Promise<RetryControlResponse> => {
    const { data } = await api.post(`/albums/${albumId}/retry-control`, req)
    return data
  },
```

- [ ] **Step 4: Add `addToBlacklist` to `queueApi`**

In `studio54-web/src/api/client.ts`, find the `queueApi` object (search for `removeFromBlacklist`). Add after `removeFromBlacklist`:

```typescript
  addToBlacklist: async (releaseGuid: string, releaseTitle?: string, albumId?: string): Promise<void> => {
    await api.post('/queue/blacklist', {
      release_guid: releaseGuid,
      release_title: releaseTitle,
      album_id: albumId,
    })
  },
```

- [ ] **Step 5: Verify TypeScript compilation**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add studio54-web/src/types/index.ts \
        studio54-web/src/api/client.ts
git commit -m "feat: add AlbumDownloadHistory types and API client methods for retry control"
```

---

### Task 7: Create `DownloadTimeline` Component

**Files:**
- Create: `studio54-web/src/components/DownloadTimeline.tsx`

- [ ] **Step 1: Create the component**

```tsx
// studio54-web/src/components/DownloadTimeline.tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FiClock, FiStopCircle, FiPlay, FiSearch, FiSlash } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { albumsApi, queueApi } from '../api/client'
import type { AlbumDownloadEvent, RetryControlRequest } from '../types'

const EVENT_BADGE: Record<string, { label: string; className: string }> = {
  grabbed:          { label: 'Grabbed',       className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  download_failed:  { label: 'Failed',        className: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' },
  retry_scheduled:  { label: 'Retry',         className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400' },
  imported:         { label: 'Imported',      className: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' },
  import_failed:    { label: 'Import Failed', className: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400' },
}

function EventBadge({ type }: { type: string }) {
  const cfg = EVENT_BADGE[type] ?? {
    label: type,
    className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap shrink-0 ${cfg.className}`}>
      {cfg.label}
    </span>
  )
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function DownloadTimeline({ albumId }: { albumId: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['album-download-history', albumId],
    queryFn: () => albumsApi.getDownloadHistory(albumId),
    refetchInterval: 30000,
    enabled: open,
  })

  const retryControlMutation = useMutation({
    mutationFn: (req: RetryControlRequest) => albumsApi.retryControl(albumId, req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['album-download-history', albumId] })
    },
    onError: () => toast.error('Failed to update retry settings'),
  })

  const blacklistMutation = useMutation({
    mutationFn: ({ guid, title }: { guid: string; title?: string }) =>
      queueApi.addToBlacklist(guid, title, albumId),
    onSuccess: () => toast.success('NZB blacklisted'),
    onError: () => toast.error('Failed to blacklist NZB'),
  })

  const retryEnabled = data?.retry_enabled ?? true
  const nextRetry = data?.next_retry_at
  const retryCount = data?.download_retry_count ?? 0
  const events = data?.events ?? []

  return (
    <div className="mt-6 border-t border-gray-200 dark:border-[#30363D] pt-4">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-[#E6EDF3] hover:text-[#FF1493] dark:hover:text-[#FF1493] transition-colors w-full text-left"
      >
        <FiClock size={14} />
        Download Timeline
        <span className="ml-auto text-gray-400 dark:text-gray-500 font-normal text-xs">
          {open ? '▲' : '▼'}
        </span>
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {/* Retry status bar */}
          {data && (
            <div className="flex items-center gap-3 flex-wrap">
              {/* Status badge */}
              {!retryEnabled
                ? <span className="px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">Stopped</span>
                : nextRetry
                ? <span className="px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">Retrying</span>
                : <span className="px-2 py-1 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400">Active</span>
              }
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {retryCount} attempt{retryCount !== 1 ? 's' : ''}
              </span>
              {nextRetry && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  · Next search at {new Date(nextRetry).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}

              <div className="flex gap-2 ml-auto">
                {retryEnabled ? (
                  <button
                    onClick={() => retryControlMutation.mutate({ retry_enabled: false })}
                    disabled={retryControlMutation.isPending}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-gray-200 dark:border-[#30363D] text-gray-600 dark:text-gray-400 hover:text-red-600 hover:border-red-300 dark:hover:text-red-400 dark:hover:border-red-800 transition-colors disabled:opacity-50"
                  >
                    <FiStopCircle size={11} />
                    Stop Retrying
                  </button>
                ) : (
                  <button
                    onClick={() => retryControlMutation.mutate({ retry_enabled: true })}
                    disabled={retryControlMutation.isPending}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-gray-200 dark:border-[#30363D] text-gray-600 dark:text-gray-400 hover:text-green-600 hover:border-green-300 dark:hover:text-green-400 dark:hover:border-green-800 transition-colors disabled:opacity-50"
                  >
                    <FiPlay size={11} />
                    Resume
                  </button>
                )}
                <button
                  onClick={() => retryControlMutation.mutate({ retry_enabled: true, search_now: true })}
                  disabled={retryControlMutation.isPending}
                  className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-gray-200 dark:border-[#30363D] text-gray-600 dark:text-gray-400 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-800 transition-colors disabled:opacity-50"
                >
                  <FiSearch size={11} />
                  Search Now
                </button>
              </div>
            </div>
          )}

          {/* Event list */}
          {isLoading && (
            <div className="flex justify-center py-6">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[#FF1493]" />
            </div>
          )}

          {!isLoading && events.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400 py-2">No download attempts yet</p>
          )}

          {events.length > 0 && (
            <div className="card overflow-hidden">
              <div className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {events.map((event: AlbumDownloadEvent) => (
                  <div
                    key={event.id}
                    className="px-4 py-3 flex items-start gap-3 hover:bg-gray-50 dark:hover:bg-[#161B22]/50"
                  >
                    <EventBadge type={event.event_type} />
                    <div className="flex-1 min-w-0">
                      {event.release_title && (
                        <p
                          className="text-xs font-mono text-gray-800 dark:text-[#E6EDF3] truncate"
                          title={event.release_title}
                        >
                          {event.release_title}
                        </p>
                      )}
                      {event.message && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          {event.message}
                        </p>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap shrink-0">
                      {formatTime(event.created_at)}
                    </span>
                    {event.event_type === 'download_failed' && event.release_guid && (
                      <button
                        onClick={() => {
                          if (confirm(`Blacklist this NZB?\n"${event.release_title}"`)) {
                            blacklistMutation.mutate({
                              guid: event.release_guid!,
                              title: event.release_title ?? undefined,
                            })
                          }
                        }}
                        disabled={blacklistMutation.isPending}
                        title="Blacklist this NZB"
                        className="shrink-0 p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                      >
                        <FiSlash size={12} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add studio54-web/src/components/DownloadTimeline.tsx
git commit -m "feat: add DownloadTimeline component with retry control and event history"
```

---

### Task 8: Wire `DownloadTimeline` into `AlbumDetail`

**Files:**
- Modify: `studio54-web/src/pages/AlbumDetail.tsx`

- [ ] **Step 1: Add the import**

In `studio54-web/src/pages/AlbumDetail.tsx`, find the import block (around lines 10–12) where `ManualSearchModal` is imported:

```typescript
import ManualSearchModal from '../components/ManualSearchModal'
```

Add `DownloadTimeline` import immediately after:

```typescript
import ManualSearchModal from '../components/ManualSearchModal'
import DownloadTimeline from '../components/DownloadTimeline'
```

- [ ] **Step 2: Render `<DownloadTimeline>` below the track list**

The component renders at the bottom of the JSX (around line 2097). Find the `ManualSearchModal` block and the outer wrapper `</div>` immediately after it (lines 2091–2099):

```tsx
      {showManualSearch && album && (
        <ManualSearchModal
          albumId={album.id}
          albumTitle={album.title}
          onClose={() => setShowManualSearch(false)}
        />
      )}
      </div>
    </div>
  )
}
```

Add `<DownloadTimeline>` before `</div>` — it goes inside the main wrapper div, after the ManualSearch modal block. Insert it as a collapsible section in the main content area. Find the main content section where tracks are rendered (a large `<div>` containing the track list, around line 1700–1980). After the closing `</div>` of the track list section, add:

```tsx
              {/* Download Timeline */}
              {album && (
                <DownloadTimeline albumId={album.id} />
              )}
```

The exact insertion point: search for the track list's closing wrapper. The structure is roughly:
```
<div className="...">   ← main content column
  <div>tracks...</div>
  {/* INSERT HERE */}
  <DownloadTimeline albumId={album.id} />
</div>
```

If unclear from the structure, append it just before the `{showManualSearch && ...}` block, inside the outermost content div.

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 4: Build to confirm no bundle errors**

```bash
npm run build 2>&1 | tail -10
```
Expected: `built in` with no errors.

- [ ] **Step 5: Commit**

```bash
git add studio54-web/src/pages/AlbumDetail.tsx
git commit -m "feat: render DownloadTimeline on AlbumDetail page"
```

---

### Task 9: Update `DownloadQueueTab` Filter and `Activity` Badge Map

**Files:**
- Modify: `studio54-web/src/components/activity/DownloadQueueTab.tsx`
- Modify: `studio54-web/src/pages/Activity.tsx`

**Context:** `DownloadQueueTab` currently hides `FAILED` downloads behind a "Show completed" checkbox. The spec requires FAILED to be visible by default. The backend (Task 5) already includes FAILED in the default filter. Now we clean up the frontend label and empty state text. `Activity.tsx` needs `RETRY_SCHEDULED` added to its badge map.

- [ ] **Step 1: Update `DownloadQueueTab.tsx`**

In `studio54-web/src/components/activity/DownloadQueueTab.tsx`, find the `DownloadQueueTab` component (around line 161). Make three changes:

**Change 1** — Rename the state from `includeCompleted` to `includeImported`:
```tsx
const [includeImported, setIncludeImported] = useState(false)
```

**Change 2** — Update the query to use the new state name:
```tsx
  const { data, isLoading, isError } = useQuery({
    queryKey: ['download-queue', includeImported],
    queryFn: () => queueApi.getQueue({ include_completed: includeImported, limit: 200 }),
    refetchInterval: 5000,
  })
```

**Change 3** — Update the checkbox label from "Show completed" to "Show imported":
```tsx
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={includeImported}
            onChange={e => setIncludeImported(e.target.checked)}
            className="rounded"
          />
          Show imported
        </label>
```

**Change 4** — Update the empty state text:
```tsx
          {includeImported ? 'No downloads found' : 'No active or failed downloads'}
```

- [ ] **Step 2: Add `RETRY_SCHEDULED` to `DL_STATUS_BADGES` in `Activity.tsx`**

In `studio54-web/src/pages/Activity.tsx`, find `DL_STATUS_BADGES` (around line 115). It currently has entries for `GRABBED`, `IMPORTED`, `IMPORT_STARTED`, `DOWNLOAD_FAILED`, `IMPORT_FAILED`, `DELETED`, `BLACKLISTED`. Add `RETRY_SCHEDULED`:

```typescript
  const DL_STATUS_BADGES: Record<string, { label: string; className: string }> = {
    GRABBED: { label: 'Grabbed', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
    IMPORTED: { label: 'Imported', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    IMPORT_STARTED: { label: 'Importing', className: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400' },
    DOWNLOAD_FAILED: { label: 'Download Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
    IMPORT_FAILED: { label: 'Import Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
    DELETED: { label: 'Deleted', className: 'bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-300' },
    BLACKLISTED: { label: 'Blacklisted', className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
    RETRY_SCHEDULED: { label: 'Retry Scheduled', className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
  }
```

Note: Activity.tsx stores events with uppercase event_type values from the backend. Verify the backend returns `retry_scheduled` (lowercase). If the badge map uses uppercase keys but the backend returns lowercase, find where the event_type is transformed to uppercase (look for `.toUpperCase()` near `DL_STATUS_BADGES` usage) and confirm the key matches. If backend returns lowercase, the key should be `retry_scheduled` not `RETRY_SCHEDULED` — match whatever the existing keys use.

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 4: Build**

```bash
npm run build 2>&1 | tail -10
```
Expected: built successfully with no errors.

- [ ] **Step 5: Commit**

```bash
git add studio54-web/src/components/activity/DownloadQueueTab.tsx \
        studio54-web/src/pages/Activity.tsx
git commit -m "feat: show FAILED downloads by default in queue tab, add RETRY_SCHEDULED badge to activity history"
```

---

### Task 10: Container Rebuild and Smoke Test

**Files:** None (operational verification)

- [ ] **Step 1: Run the full Python test suite one final time**

```bash
cd /home/tesimmons/Studio54/studio54-service
python -m pytest tests/unit/ tests/integration/ -v 2>&1 | tail -30
```
Expected: all tests pass.

- [ ] **Step 2: Rebuild and restart containers**

```bash
cd /home/tesimmons/Studio54
docker compose build studio54-service studio54-worker studio54-web && \
docker compose up -d studio54-service studio54-worker studio54-web
```
Expected: all three containers start without errors.

- [ ] **Step 3: Run the migration inside the service container**

```bash
docker exec studio54-service alembic upgrade head
```
Expected: `Running upgrade ... -> 20260426_0100_061, Add retry state columns to albums and download_queue`

- [ ] **Step 4: Verify retry beat task is registered**

```bash
docker exec studio54-worker celery -A app.tasks.celery_app inspect scheduled 2>&1 | grep -i retry
```
Expected: `retry-scheduled-downloads` appears in the output.

- [ ] **Step 5: Verify API endpoints respond**

```bash
# Get a real album ID from the DB
ALBUM_ID=$(docker exec studio54-service python -c "
from app.database import SessionLocal; from app.models.album import Album
db = SessionLocal(); a = db.query(Album).first(); print(a.id)
")

curl -s -X GET "http://localhost:8000/api/v1/albums/$ALBUM_ID/download-history" \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:8000/api/v1/auth/login -d 'username=admin&password=admin' -H 'Content-Type: application/x-www-form-urlencoded' | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"access_token\"])')" | python3 -m json.tool
```
Expected: JSON response with `album_id`, `retry_enabled`, `events: []`.

- [ ] **Step 6: Verify the DownloadTimeline appears on an album page**

Open the Studio54 web UI, navigate to any album's detail page, look for the "Download Timeline" collapsible section. Click to expand — it should show "No download attempts yet" for albums with no history, or events for albums that have been searched.

- [ ] **Step 7: Verify the Download Queue tab shows FAILED items**

Navigate to Activity → Download Queue tab. Confirm FAILED downloads appear without requiring the checkbox. Confirm the checkbox is now labeled "Show imported".

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `retry_enabled`, `next_retry_at`, `download_retry_count` on `albums` | Task 1+2 |
| `pending_alternates` on `download_queue` | Task 1+2 |
| `RETRY_SCHEDULED` event type | Task 2 |
| `_trigger_auto_retry` Phase 1 (pending alternates) | Task 3 |
| `_trigger_auto_retry` Phase 2 (progressive delay: 1h/6h/24h) | Task 3 |
| `add_download` stores `pending_alternates` after success | Task 3 |
| GRABBED event write in `add_download()` | Task 3 |
| DOWNLOAD_FAILED event write in `add_download()` all-fail path | Task 3 |
| DOWNLOAD_FAILED event write in `_mark_download_failed()` | Task 3 |
| RETRY_SCHEDULED event write in `_trigger_auto_retry()` | Task 3 |
| `_trigger_auto_retry` called from `add_download()` all-fail path | Task 3 |
| `retry_scheduled_downloads` beat task every 30 min | Task 4 |
| Beat task increments `download_retry_count`, clears `next_retry_at` | Task 4 |
| `POST /albums/{id}/retry-control` | Task 5 |
| `GET /albums/{id}/download-history` | Task 5 |
| `POST /queue/blacklist` (for Blacklist NZB button) | Task 5 |
| FAILED state visible by default in Download Queue tab | Task 5+9 |
| `AlbumDownloadEvent`, `AlbumDownloadHistory`, `RetryControlRequest`, `RetryControlResponse` types | Task 6 |
| `albumsApi.getDownloadHistory`, `albumsApi.retryControl`, `queueApi.addToBlacklist` | Task 6 |
| `DownloadTimeline` component with retry status bar + event timeline | Task 7 |
| Retry status badge (Retrying/Stopped/Active) | Task 7 |
| Stop Retrying / Resume / Search Now buttons | Task 7 |
| DOWNLOAD_FAILED rows with Blacklist NZB button | Task 7 |
| `refetchInterval: 30000` | Task 7 |
| `DownloadTimeline` rendered on `AlbumDetail` | Task 8 |
| `DownloadQueueTab` default filter change + label rename | Task 9 |
| `RETRY_SCHEDULED` badge in Activity Downloads history tab | Task 9 |
| All event writes wrapped in try/except | Task 3 |
| `retry_scheduled_downloads` skips per-album errors and continues | Task 4 |

**Type consistency check:** `AlbumDownloadEvent.event_type` uses lowercase string values (`'grabbed'`, `'download_failed'`, `'retry_scheduled'`) matching what the backend enum returns. `EVENT_BADGE` in `DownloadTimeline` uses the same lowercase keys. `DL_STATUS_BADGES` in `Activity.tsx` uses uppercase keys (existing pattern) — Task 9 note warns the implementer to verify and match.

**No placeholders:** Every step contains actual code or exact commands.
