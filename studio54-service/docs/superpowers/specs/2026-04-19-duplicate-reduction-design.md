# Duplicate File Reduction Design

## Goal

A background job that finds duplicate audio files (same MusicBrainz track ID, multiple physical files), keeps the highest-quality copy, moves the rest to a dedicated staging area for user review, and auto-purges them after a configurable retention period. A new UI tab in File Management lets users review, restore, or permanently delete staged duplicates individually or in bulk.

## Architecture

### Quality Ranking

Winner is selected per duplicate group using:

1. **Bitrate** (primary) — higher `bitrate_kbps` wins
2. **Format** (tiebreaker) — FLAC (3) > M4A (2) > MP3 (1) > everything else (0)
3. **File size** (final tiebreaker) — larger file wins

### Deduplication Job

- New Celery task in `app/tasks/deduplicate_task.py`
- New `JobType.DEDUPLICATE = "deduplicate"` added to `app/models/job_state.py`
- Groups all `library_files` by `musicbrainz_trackid` where count > 1
- Skips groups where any file has no `musicbrainz_trackid`
- Processes in batches of 500 groups with checkpoint/resume support
- For each loser file:
  - Moves file to `<recycle_bin_path>/duplicates/<YYYY-MM-DD>/` using `shutil.move`
  - Creates a `duplicate_recycle_bin` DB record
  - Sets `library_files.organization_status = 'duplicate_removed'` on the loser row
  - Unlinks the loser from any `tracks` row (`has_file = false, file_path = NULL`)
- Triggered on-demand via `POST /api/v1/jobs/deduplicate`; no automatic scheduling

### Staging Directory

Files move to `<media_management_config.recycle_bin_path>/duplicates/<YYYY-MM-DD>/` where the date is the run date. The `recycle_bin_path` comes from the existing `media_management_config` table. If `recycle_bin_path` is null or empty, the job fails immediately with a clear error.

### Auto-Purge

Entries are purged when `recycled_at + recycle_bin_cleanup_days < now()`. Purge is triggered by the existing cleanup beat task and by `POST /api/v1/duplicate-recycle-bin/purge-expired`. Purging permanently deletes the file from staging and marks the record `permanently_deleted`.

---

## Database

### New Table: `duplicate_recycle_bin`

```sql
CREATE TABLE duplicate_recycle_bin (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    musicbrainz_trackid  VARCHAR(36) NOT NULL,
    original_file_path   TEXT NOT NULL,
    staging_file_path    TEXT NOT NULL,
    kept_file_path       TEXT NOT NULL,
    removed_bitrate_kbps INTEGER,
    removed_format       VARCHAR(20),
    kept_bitrate_kbps    INTEGER,
    kept_format          VARCHAR(20),
    recycled_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at           TIMESTAMPTZ NOT NULL,
    status               VARCHAR(30) NOT NULL DEFAULT 'pending_review',
    restored_at          TIMESTAMPTZ,
    deleted_at           TIMESTAMPTZ
);

-- status values: 'pending_review', 'permanently_deleted', 'restored'

CREATE INDEX ix_dup_recycle_status ON duplicate_recycle_bin (status);
CREATE INDEX ix_dup_recycle_expires ON duplicate_recycle_bin (expires_at) WHERE status = 'pending_review';
CREATE INDEX ix_dup_recycle_trackid ON duplicate_recycle_bin (musicbrainz_trackid);
```

### Modified: `job_state.py`

Add `DEDUPLICATE = "deduplicate"` to `JobType` enum.

---

## API

All endpoints require DJ or above. Base path: `/api/v1/duplicate-recycle-bin`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | List entries. Query params: `status` (default `pending_review`), `format`, `page`, `page_size`. Returns paginated list with quality comparison data. |
| `DELETE` | `/{id}` | Permanently delete one entry. Removes file from staging, marks `permanently_deleted`. |
| `POST` | `/{id}/restore` | Restore one entry. Moves file back to `original_file_path`, re-links in `library_files` and `tracks`, marks `restored`. Fails if original path is now occupied. |
| `DELETE` | `/bulk` | Body: `{ "ids": ["uuid", ...] }`. Permanently delete multiple. |
| `POST` | `/bulk/restore` | Body: `{ "ids": ["uuid", ...] }`. Restore multiple. Returns per-item success/failure. |
| `POST` | `/purge-expired` | Immediately purge all entries where `expires_at < now()`. Director only. |

Job trigger: `POST /api/v1/jobs/deduplicate` (no body). Returns job ID.

---

## New Files

- `app/tasks/deduplicate_task.py` — Celery task
- `app/models/duplicate_recycle.py` — SQLAlchemy model
- `app/api/duplicate_recycle.py` — API router
- `alembic/versions/20260419_0300_060_add_duplicate_recycle_bin.py` — migration

### Modified Files

- `app/models/job_state.py` — add `DEDUPLICATE` to `JobType`
- `app/main.py` — register new router
- `app/tasks/celery_app.py` — register new task

---

## Error Handling

- **Staging path missing:** job fails immediately, logs clear error, no files touched
- **File already missing from disk:** log warning, still create DB record marked `permanently_deleted`
- **Restore path occupied:** return 409, do not overwrite — user must resolve manually
- **Purge of missing staging file:** log warning, mark `permanently_deleted` anyway

---

## UI

New **"Duplicate Bin"** tab in the File Management page (`/file-management`).

**Table columns:** Track title (from `library_files.title`), Removed file (format badge + bitrate), Kept file (format badge + bitrate), Removed date, Expires in (countdown or "Expired" badge), Status.

**Row actions:** Restore button, Delete button.

**Header actions:** Select-all checkbox, Bulk Restore, Bulk Delete.

**Filters:** Status dropdown (Pending / Restored / Deleted), Format filter.

Expired entries shown with an amber "Expired" badge. Restored entries shown greyed out (read-only). The tab shows a count badge of pending-review items.
