# Audiobook Session Persistence & Sleep Timer — Design Spec
**Date:** 2026-05-03
**Status:** Approved (updated to include Play Series)

---

## Overview

This spec covers four interconnected features added to the Studio54 pop-out player for audiobook listening. All features apply equally to **Play Book** and **Play Series**.

1. **Reliable position saving** — position is saved on pause, close, and sleep timer stop (not just on heartbeat/chapter end)
2. **Queue persistence** — "Play Book" and "Play Series" always open the pop-out player and always resume exactly where the listener left off (chapter and millisecond)
3. **Sleep timer** — configurable countdown that stops playback and offers a one-tap 15-minute extension
4. **Mark as Finished** — soft-archives a book or series session with a 7-day recovery window and nightly scheduled cleanup

---

## Section 1 — Data Model

### New table: `user_listening_sessions`

Handles both single-book and full-series sessions. Exactly one of `book_id` or `series_id` is set per row.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK → users | Cascade delete |
| `session_type` | Enum: `book` \| `series` | Determines which FK is active |
| `book_id` | UUID FK → books (nullable) | Set when `session_type = book` |
| `series_id` | UUID FK → series (nullable) | Set when `session_type = series` |
| `chapter_queue` | JSON | Ordered list of chapter IDs (for a series, spans all books in order) |
| `current_index` | Integer | Index into `chapter_queue` for the active chapter |
| `archived_at` | Timestamp (nullable) | Set when user marks as finished; null = active |
| `pending_delete_at` | Timestamp (nullable) | `archived_at + 7 days`; null = not archived |
| `created_at` | Timestamp | |
| `updated_at` | Timestamp | |

**Unique constraints (partial indexes):**
- `(user_id, book_id)` where `series_id IS NULL` — one book session per user per book
- `(user_id, series_id)` where `book_id IS NULL` — one series session per user per series

**Check constraint:** exactly one of `book_id` / `series_id` must be non-null.

### Existing table: `book_progress` — no schema changes

`book_progress` continues to own `(user_id, book_id, chapter_id, position_ms, completed)`. Its role is unchanged: it tracks the exact millisecond position within the current chapter. For a series session, `book_id` in `book_progress` refers to whichever book the current chapter belongs to — this works naturally since chapters always belong to a specific book.

### Division of responsibility

- `user_listening_sessions` = the **session layer**: what queue is loaded, where in the queue you are, whether it's a book or series session, and archive/delete state
- `book_progress` = the **position layer**: which chapter is active and exactly how many milliseconds in

When resuming, the player reads both: `user_listening_sessions` to reconstruct the chapter queue and jump to the right index, then `book_progress` to seek the audio to the exact timestamp within that chapter.

---

## Section 2 — Reliable Position Saving

### Current state (gaps)

Position is saved only when:
- The 30-second heartbeat fires (up to 30s of loss on abrupt stop)
- A chapter ends naturally

Pause and player close do **not** currently save position.

### New save triggers

**1. On pause**
When the user hits pause, immediately call `bookProgressApi.upsert()` with `audioRef.current.currentTime`. This is the highest-priority trigger — deliberate pauses are the most common way listeners put a book down.

**2. On `beforeunload`**
When the pop-out player window closes, fire `navigator.sendBeacon()` POST to the progress endpoint. `sendBeacon` is guaranteed by the browser to deliver even during page unload, unlike `fetch`.

**3. On sleep timer stop**
Save position before audio is paused when the sleep timer fires (see Section 3).

The existing 30-second heartbeat remains as a safety net for crashes and power loss.

**Result:** Position loss is effectively zero for all normal usage patterns. Applies identically whether the user is in a book session or a series session.

---

## Section 3 — Sleep Timer

### UI

A timer icon button in the pop-out player controls. Clicking it opens a small popover containing:

- **Preset buttons:** 15 min · 30 min · 45 min · 60 min · End of chapter
- **Custom input:** a number field labeled "_ minutes" with a Set button
- **Active state:** when a timer is running, the popover shows a live countdown (e.g. "23:41 remaining") and a Cancel button

The sleep timer is available during both book and series playback.

### Behavior

- On set: a `setTimeout` starts for the chosen duration
- On fire:
  1. Save position immediately (Section 2 trigger)
  2. Pause audio
  3. Show snooze popup (see below)
- **End of chapter mode:** instead of a countdown, sets a flag that intercepts `handleEnded` and stops rather than advancing to the next chapter
- The countdown display updates every second via a `setInterval` tick
- The timer is time-based (wall clock), not play-based — pausing does not pause the timer

### Snooze popup (fires when timer ends)

A non-blocking overlay appears with:
- **"+ 15 minutes"** button — resumes playback and resets the timer to 15 minutes from now
- **"Dismiss"** button — closes the popup, player stays paused
- **Auto-dismisses after 30 seconds** with no action — popup disappears, player stays paused

### Frontend state (all local, no persistence)

```typescript
sleepTimerEndsAt: number | null        // Date.now() + ms, set when timer starts
sleepTimerEndOfChapter: boolean        // true for "end of chapter" mode
sleepTimerDisplay: string              // "23:41" — updated by tick interval
showSnoozePopup: boolean               // true when timer has just fired
```

---

## Section 4 — Queue Persistence

### "Play Book" and "Play Series" always open the pop-out player

Clicking either button anywhere in the app (book detail, series detail, book/series lists):
1. Opens the pop-out player window — if already open, focuses it rather than opening a second instance
2. The pop-out player fetches the `UserListeningSession` for that book or series
3. Reconstructs the chapter queue and seeks to `chapter_queue[current_index]`
4. Fetches `BookProgress` for the exact `position_ms` and seeks the audio there
5. Begins playback — no manual resume step

If no session exists (first-time play), one is created:
- **Book session:** queue = all chapters of the book in order, `current_index = 0`
- **Series session:** queue = all chapters of all books in the series in series order, `current_index = 0` (uses the existing `BookPlaylist` ordering already stored in `book_playlist_chapters`)

### Saving queue state during playback

- On chapter advance (`handleEnded` → `NEXT`): PATCH session `current_index += 1`
- On "Play Book" / "Play Series" first open: POST to create session if none exists

### API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/books/{book_id}/session` | Create or reactivate book session (idempotent) |
| `GET` | `/books/{book_id}/session` | Fetch book session (queue + current_index) |
| `PATCH` | `/books/{book_id}/session` | Update `current_index` for book session |
| `POST` | `/books/{book_id}/session/archive` | Mark book as finished (soft archive) |
| `DELETE` | `/books/{book_id}/session` | Hard delete book session |
| `POST` | `/series/{series_id}/session` | Create or reactivate series session (idempotent) |
| `GET` | `/series/{series_id}/session` | Fetch series session (queue + current_index) |
| `PATCH` | `/series/{series_id}/session` | Update `current_index` for series session |
| `POST` | `/series/{series_id}/session/archive` | Mark series as finished (soft archive) |
| `DELETE` | `/series/{series_id}/session` | Hard delete series session |

---

## Section 5 — Mark as Finished & Scheduled Cleanup

### Mark as Finished flow

Available on: book detail page, series detail page, and in the pop-out player controls.

- For a book session the button reads **"Mark as Read"**
- For a series session the button reads **"Mark Series as Complete"**

Flow (identical for both):
1. User clicks the button
2. Confirmation dialog:
   - Book: *"Mark [Book Title] as finished? Your progress will be kept for 7 days in case you need to recover it."*
   - Series: *"Mark [Series Name] as complete? Your progress will be kept for 7 days in case you need to recover it."*
3. On confirm: `POST /books/{id}/session/archive` or `POST /series/{id}/session/archive`
4. Backend sets `archived_at = now`, `pending_delete_at = now + 7 days`
5. Session disappears from the active listening view immediately
6. All `BookProgress` records for the session are left untouched

### Recovery (Undo) within 7 days

On the book or series detail page, if the user has an archived session a subtle banner shows:
> *"You marked this as finished on [date]. Undo until [pending_delete_at]."*

An **Undo** button clears both `archived_at` and `pending_delete_at`, restoring the session to active.

### Scheduled cleanup job (Celery beat)

- **Schedule:** nightly at 2:00am
- **Query:** `UserListeningSession` rows where `pending_delete_at < now`
- **Action:** hard-delete those sessions; for book sessions also delete the associated `BookProgress` record; for series sessions delete all `BookProgress` records for books in the series
- **Logging:** logs a summary (e.g. "Cleaned up 2 book sessions, 1 series session")
- **No user notification** — the 7-day Undo banner is the only communication

---

## Out of Scope

- Cross-user shared sessions
- Audiobook ratings or reviews
- Push notification when cleanup fires
- Sleep timer persistence across player close (timer resets if player is closed)
