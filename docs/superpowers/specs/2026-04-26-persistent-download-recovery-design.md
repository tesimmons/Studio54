# Persistent Download Recovery Design

**Date:** 2026-04-26
**Status:** Approved

## Goal

Make Studio54 fully persistent in acquiring music: retry failed downloads forever (until manually stopped), log every SABnzbd interaction to a visible history, and give users per-album control over the retry lifecycle.

## Architecture

All retry state lives in the database on the `albums` table. A new Celery beat task fires every 30 minutes and triggers fresh indexer searches for albums whose retry timer has elapsed. The existing `search_album` → `add_download` → `_trigger_auto_retry` pipeline is extended rather than replaced. Event logging is added at four call sites in `download_tasks.py` — no new services.

## Tech Stack

Python/SQLAlchemy (backend), Alembic (migrations), Celery + beat (scheduling), FastAPI (API), React 18 + TypeScript + TanStack Query 5 (frontend).

---

## Section 1: Data Model

### New columns on `albums` table

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `retry_enabled` | Boolean | `True` | When `False`, all auto-retry and periodic searches skip this album |
| `next_retry_at` | DateTime (UTC, nullable) | `None` | When the next fresh indexer search should fire |
| `download_retry_count` | Integer | `0` | Total retry cycles across all failures for this album |

### New column on `download_queue` table

| Column | Type | Purpose |
|--------|------|---------|
| `pending_alternates` | JSON (nullable) | Un-tried alternate NZB candidates from the original search. Populated when `add_download` succeeds with the primary — stores the remaining alternates so a mid-download failure can try them without hitting indexers again |

### New `DownloadEventType` values

Added to the existing enum in `app/models/download_decision.py`:

| Value | When written |
|-------|-------------|
| `GRABBED` | NZB successfully accepted by SABnzbd |
| `DOWNLOAD_FAILED` | SABnzbd rejected, aborted, encrypted, or failed during download |
| `RETRY_SCHEDULED` | System queued a retry, including when and why |

Existing `IMPORTED` and `IMPORT_FAILED` types are unchanged.

### Alembic migration

One migration adds all four new columns (`retry_enabled`, `next_retry_at`, `download_retry_count` on `albums`; `pending_alternates` on `download_queue`).

---

## Section 2: Retry Engine

### `_trigger_auto_retry()` — rewritten

**Guard (first line):** Check `album.retry_enabled`. If `False`, return immediately — no retry, no event written.

**Phase 1 — Quick (pending alternates, no indexer hit):**

When a download fails mid-way (e.g., encryption abort during download), the alternates from the original search were never tried — they're in `failed_download.pending_alternates`. If this list is non-empty:

1. Pop the full list
2. Call `add_download.apply_async` with them as the candidate list (no primary URL needed — the alternates become the candidates)
3. Clear `pending_alternates` on the failed download row
4. Write `RETRY_SCHEDULED` event: `"Trying N alternate NZB(s) — no indexer search needed"`
5. Fires with `countdown=30` seconds

If `pending_alternates` is empty or None, fall through to Phase 2.

**Phase 2 — Fresh (hit indexers again, progressive delay):**

Sets `album.next_retry_at` based on `album.download_retry_count`:

| `download_retry_count` value | Delay |
|------------------------------|-------|
| 1 | 1 hour |
| 2 | 6 hours |
| 3 | 24 hours |
| 4+ | 24 hours (daily, forever) |

Writes `RETRY_SCHEDULED` event: `"Fresh indexer search scheduled for {next_retry_at ISO}"`.

The album stays `WANTED`. The beat task picks it up when `next_retry_at <= now`.

### `add_download()` — one addition

After SABnzbd accepts the primary candidate and the `DownloadQueue` row is created:

```python
download.pending_alternates = alternates  # the un-tried candidates list
```

This is the only change to `add_download`'s core logic.

---

## Section 3: Event Logging

Four write sites in `download_tasks.py`:

**1. `add_download()` — after SABnzbd accepts (successful grab):**
```
event_type: GRABBED
release_guid: c_guid
release_title: c_title
message: "Sent to SABnzbd (attempt {N} of {M})"
data: { nzo_id, indexer_id, size_bytes, alternate_count }
```

**2. `add_download()` — when all candidates fail (line ~442):**
```
event_type: DOWNLOAD_FAILED
release_guid: candidates[0]["nzb_guid"]
release_title: candidates[0]["nzb_title"]
message: "All {N} candidates rejected by SABnzbd. Last: {last_error}"
data: { attempted_guids: [...], total_candidates: N }
```

**3. `_mark_download_failed()` — monitor detects SABnzbd failure:**
```
event_type: DOWNLOAD_FAILED
release_guid: download.nzb_guid
release_title: download.nzb_title
message: {error_message}  ← verbatim from SABnzbd (e.g. "Encrypted / Passworded")
data: { sab_fail_message, sabnzbd_id: download.sabnzbd_id }
```

**4. `_trigger_auto_retry()` — when retry is queued:**
```
event_type: RETRY_SCHEDULED
message: "Trying N alternate NZB(s)..." (Phase 1)
      OR "Fresh indexer search scheduled for {ISO timestamp}" (Phase 2)
data: { phase: "quick"|"fresh", retry_count, next_retry_at }
```

All four writes are wrapped in try/except so a logging failure never breaks the download pipeline.

---

## Section 4: Beat Task

**New task: `retry_scheduled_downloads`** in `app/tasks/download_tasks.py`

```
Query albums WHERE:
  retry_enabled = True
  AND next_retry_at IS NOT NULL
  AND next_retry_at <= now (UTC)
  AND status = WANTED

For each album:
  Clear album.next_retry_at      ← prevents double-firing
  Increment album.download_retry_count
  Commit
  Fire search_album.apply_async([album.id])
```

**Beat schedule** in `app/tasks/celery_app.py`:
```python
"retry-scheduled-downloads": {
    "task": "app.tasks.download_tasks.retry_scheduled_downloads",
    "schedule": crontab(minute="*/30"),
}
```

**Why 30 minutes:** The 1-hour minimum retry delay means polling hourly could add up to 59 minutes of extra wait. 30-minute polling keeps actual delays within ~30 minutes of the target.

**Interaction with `search_wanted_albums`:** The existing 6-hour task will also find and search retry albums (they stay `WANTED`). This is safe — `search_album` holds a distributed lock per album, so concurrent triggers don't cause double-submission.

---

## Section 5: API

### `POST /api/v1/albums/{album_id}/retry-control`

Request body:
```json
{ "retry_enabled": false }                          // Stop retrying
{ "retry_enabled": true }                           // Resume (schedules next retry in 1h)
{ "retry_enabled": true, "search_now": true }       // Resume + trigger immediate search
```

Response:
```json
{
  "album_id": "...",
  "retry_enabled": true,
  "next_retry_at": "2026-04-26T18:00:00Z",
  "download_retry_count": 2
}
```

### `GET /api/v1/albums/{album_id}/download-history`

Returns all `DownloadHistory` events for the album, newest first:
```json
{
  "album_id": "...",
  "retry_enabled": true,
  "next_retry_at": "2026-04-26T18:00:00Z",
  "download_retry_count": 2,
  "events": [
    {
      "id": "...",
      "event_type": "DOWNLOAD_FAILED",
      "release_title": "Artist - Album-FLAC-2024",
      "message": "Encrypted / Passworded",
      "created_at": "2026-04-26T12:02:30Z",
      "data": { "sab_fail_message": "Encrypted / Passworded", "sabnzbd_id": "..." }
    }
  ]
}
```

### No changes needed

- `GET /api/v1/queue/blacklist` — already built; UI links to it for per-GUID blacklisting
- Downloads history endpoint — already queries `DownloadHistory`; new event types appear automatically

---

## Section 6: Frontend

### New file: `studio54-web/src/components/DownloadTimeline.tsx`

A component rendered on the Album Detail page. Two sub-sections:

**Retry status bar:**
- Badge: `Retrying` (green) / `Stopped` (gray) / `Searching…` (blue pulse)
- Retry count: "X attempts"
- Next retry: "Next search at 6:00 PM" or blank if not scheduled
- Buttons: "Stop Retrying" / "Resume" toggle, "Search Now" (calls `retry-control` API)

**Event timeline:**
- Chronological list, newest first, from `GET /albums/{id}/download-history`
- Each row: event type badge + timestamp + NZB title (truncated) + message
- Badge colors: `GRABBED`=blue, `DOWNLOAD_FAILED`=red, `RETRY_SCHEDULED`=yellow, `IMPORTED`=green, `IMPORT_FAILED`=orange
- `DOWNLOAD_FAILED` rows include a "Blacklist NZB" button (calls existing blacklist API with GUID)
- Empty state: "No download attempts yet"
- `refetchInterval: 30000`

### Modified: `studio54-web/src/pages/AlbumDetail.tsx`

Import and render `<DownloadTimeline albumId={album.id} />` as a new collapsible section below the track list.

### Modified: `studio54-web/src/components/activity/DownloadQueueTab.tsx`

Change default filter: show `FAILED` state by default alongside active states. Only hide `IMPORTED` and `IGNORED` by default. Rename checkbox to "Show imported" instead of "Show completed."

### Modified: `studio54-web/src/types/index.ts`

Add:
- `AlbumDownloadEvent` interface
- `AlbumDownloadHistory` interface (the full API response shape)
- `RetryControlRequest` / `RetryControlResponse` interfaces

### Modified: `studio54-web/src/api/client.ts`

Add to `albumApi` (or create if not present):
- `getDownloadHistory(albumId: string): Promise<AlbumDownloadHistory>`
- `retryControl(albumId: string, req: RetryControlRequest): Promise<RetryControlResponse>`

### Activity page — Downloads history tab

Zero code changes. New event types appear automatically once backend writes them. The existing event type label/color map in the tab needs the three new types added (minor update to whatever switch/map renders event type badges).

---

## File Map

| Action | File | Change |
|--------|------|--------|
| Create | `alembic/versions/YYYYMMDD_add_retry_state.py` | New migration: 4 columns |
| Modify | `app/models/download_decision.py` | Add 3 new `DownloadEventType` values |
| Modify | `app/models/album.py` | Add `retry_enabled`, `next_retry_at`, `download_retry_count` |
| Modify | `app/models/download_queue.py` | Add `pending_alternates` JSON column |
| Modify | `app/tasks/download_tasks.py` | Rewrite `_trigger_auto_retry`, add event writes to 4 sites, add `pending_alternates` write in `add_download`, add `retry_scheduled_downloads` task |
| Modify | `app/tasks/celery_app.py` | Register `retry_scheduled_downloads` in beat schedule |
| Create | `app/api/albums_retry.py` (or add to `app/api/albums.py`) | `POST /albums/{id}/retry-control`, `GET /albums/{id}/download-history` |
| Modify | `app/main.py` | Register new router if separate file |
| Create | `studio54-web/src/components/DownloadTimeline.tsx` | New timeline component |
| Modify | `studio54-web/src/pages/AlbumDetail.tsx` | Render `DownloadTimeline` |
| Modify | `studio54-web/src/components/activity/DownloadQueueTab.tsx` | Default filter change |
| Modify | `studio54-web/src/types/index.ts` | New interfaces |
| Modify | `studio54-web/src/api/client.ts` | New API methods |
| Modify | Activity Downloads tab (event badge map) | Add 3 new event type labels/colors |

---

## Error Handling

- All `DownloadHistory` writes are wrapped in `try/except` — a logging failure never breaks the download pipeline
- `retry_scheduled_downloads` skips individual album errors and continues the batch
- `_trigger_auto_retry` is a best-effort operation — any exception is logged and swallowed
- If `search_now=true` in retry-control and `search_album` fails to queue, the API returns success (the album stays retryable)

## Success Criteria

- An encrypted NZB abort appears in the album's download timeline within 30 seconds of SABnzbd detecting it
- The album automatically retries with alternates (if any), then schedules a fresh search at progressive intervals
- After 3+ failures, the album retries daily until a file is successfully imported and linked to the album
- "Stop Retrying" on an album prevents all future auto-searches for it
- "Blacklist NZB" on a failure event prevents that specific GUID from ever being tried again
- The Download Queue tab shows failed entries without requiring a filter toggle
