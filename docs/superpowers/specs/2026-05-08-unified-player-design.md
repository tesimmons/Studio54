# Unified Player Design
**Date:** 2026-05-08  
**Status:** Approved

## Problem

Books fail to play on mobile because `playBook` in `PlayerContext` always calls `window.open('/player', ...)` to launch a pop-out window. Mobile browsers block or mishandle that popup, so tapping Play Book or Resume does nothing. Music works because `playAlbum` dispatches directly to the reducer — books need the same path.

## Goal

- Playback always starts in the built-in persistent player (bottom bar) — no automatic window
- The built-in player is fully featured for both music and books on all screen sizes
- On desktop, the user can still manually expand to a new window via the pop-out button
- On mobile, tapping the album art expands to a fullscreen overlay within the same tab

## Approach

Approach A — minimal surgery. Fix the one function that auto-opens the window, port the three missing features into PersistentPlayer, and add a mobile fullscreen overlay. PopOutPlayer.tsx is not modified.

---

## Section 1: PlayerContext — Remove Auto Pop-Out from `playBook`

**File:** `studio54-web/src/contexts/PlayerContext.tsx`

`playBook` currently has two branches:
1. Pop-out already open → broadcast via BroadcastChannel
2. Pop-out not open → write `PLAY_BOOK_REQUEST_KEY` to localStorage + `window.open`

**Change:** Remove branch 2 entirely. Replace it with a direct `dispatch({ type: 'PLAY_BOOK', ...payload })` — identical to how `playAlbum` behaves when the pop-out is not open. The localStorage write and `window.open` call are deleted.

Branch 1 (pop-out already open → broadcast) is kept. If the user has manually popped out and then triggers Play Book from a book detail page, the command is forwarded to the existing pop-out window as before.

No other changes to PlayerContext. `popOut()`, `closePopOut()`, the BroadcastChannel, and all transport functions are untouched.

**Result:** `playBook` and `playAlbum` are structurally identical. Books play in the persistent player by default.

---

## Section 2: PersistentPlayer — Port Missing Features

**File:** `studio54-web/src/components/PersistentPlayer.tsx`

Three features present in PopOutPlayer are missing from PersistentPlayer. All three are ported verbatim, guarded by `!isPopOutOpen` so they don't double-fire when the user has manually opened the pop-out.

### 2a. Now Playing Heartbeat

A 30-second `setInterval` calls `nowPlayingApi.heartbeat` with current track, chapter, and `position_ms` data while `isPlaying` is true. The interval starts when playback begins and clears on pause, track change, or unmount. Identical to PopOutPlayer lines 342–375.

`nowPlayingApi` is added to the import from `'../api/client'`.

### 2b. Mark as Read / Mark Series as Complete

State: `sessionArchived: boolean`, `showArchiveConfirm: boolean`.

A button is shown in the player bar (and in the mobile expanded overlay — see Section 3) when all three conditions are true:
- `isBookChapter` is true
- `state.sessionType` and `state.sessionEntityId` are set
- `sessionArchived` is false

Tapping the button sets `showArchiveConfirm = true`, which renders a small inline confirmation. Confirming calls `listeningSessionApi.archiveBook(sessionEntityId)` or `archiveSeries(sessionEntityId)` depending on `state.sessionType`. On success, `sessionArchived = true` and the button is replaced by a checkmark. On error, a toast is shown.

`sessionArchived` resets to `false` whenever `state.sessionEntityId` changes (new book session started).

`listeningSessionApi` is already imported in PersistentPlayer (added in a prior session). No import change needed.

### 2c. Initial Position Restore

When `playBook` dispatches synchronously, `BookDetail.tsx` already attaches a `canplay` listener to `player.audioRef` to seek to `bookProgress.position_ms`. Verify this fires correctly with the new synchronous dispatch path. If the `setTimeout(100)` race is unreliable, add a fallback in PersistentPlayer's `onCanPlay` callback: if `state.bookId` is set and `bookProgress.position_ms > 0` and `currentTime === 0`, seek to the saved position. This is a safety net only — the primary seek stays in `BookDetail.tsx`.

---

## Section 3: PersistentPlayer — Mobile Fullscreen Overlay

**File:** `studio54-web/src/components/PersistentPlayer.tsx`

### Trigger

New state: `isExpanded: boolean`, initially `false`.

On mobile (`md:hidden` context), two elements become tappable to set `isExpanded = true`:
- The album art thumbnail in the bottom bar
- A `FiChevronUp` button added to the mobile control row

On desktop, these elements are not shown — the existing `FiExternalLink` button still calls `popOut()` as before.

### Overlay

When `isExpanded` is true, render a `fixed inset-0 z-[60] bg-[#0D1117] text-white flex flex-col` overlay on top of everything. No explicit breakpoint guard is needed on the overlay itself — the expand triggers are `md:hidden`, so `isExpanded` can only become true on a mobile-width viewport.

The overlay contains, top to bottom:
1. **Top bar** — chevron-down button (left, collapses overlay), track counter if in a queue (center), close-player X button (right)
2. **Album art** — large square, centered, with cover art or S54 logo fallback
3. **Track info** — title (large), artist/book name (smaller, muted)
4. **Seek bar** — full-width range input with current time / duration labels
5. **Transport** — previous, play/pause (large pink button), next
6. **Secondary controls row** — shuffle, repeat, sleep timer (bell icon), Mark as Read button (when applicable)
7. **Queue panel** — collapsible, triggered by a queue button; renders `renderQueueList` already defined in PersistentPlayer

### Collapse

Setting `isExpanded = false` collapses back to the bottom bar. Audio never stops — only the render path changes.

### Architecture

The overlay is a second render branch inside the same component function. It reads the same state (`currentTrack`, `isPlaying`, `queue`, `state.bookId`, etc.) and calls the same callbacks (`pause`, `resume`, `next`, `previous`, `seekTo`, `setSleepTimer`, etc.) already wired in PersistentPlayer. No new data fetching or audio elements.

---

## Section 4: Layout.tsx — No Change Required

`Layout.tsx` uses `isPopOutOpen` to adjust bottom padding when the pop-out indicator bar is showing. Since the pop-out is still available as a manual user action on desktop, this logic stays correct. No changes needed.

---

## Files Changed

| File | Change |
|---|---|
| `PlayerContext.tsx` | Remove `window.open` + localStorage write from `playBook`; dispatch directly instead |
| `PersistentPlayer.tsx` | Add heartbeat, Mark as Read, mobile fullscreen overlay |

## Files Unchanged

| File | Reason |
|---|---|
| `PopOutPlayer.tsx` | Unchanged — still used for manual desktop expand |
| `BookDetail.tsx` | Seek-on-load logic stays; no structural change needed |
| `Layout.tsx` | Pop-out padding logic still valid for manual pop-out |
| `usePlayerBroadcast.ts` | BroadcastChannel still used for manual pop-out path |

---

## Verification

- [ ] Play Book on mobile → audio starts in bottom bar, no popup
- [ ] Resume on mobile → seeks to correct position, correct chapter
- [ ] Sleep timer works on mobile (already deployed)
- [ ] Mark as Read button appears during book playback, archives session correctly
- [ ] Now Playing heartbeat fires every 30s during playback
- [ ] Tapping album art on mobile opens fullscreen overlay
- [ ] Fullscreen overlay controls (transport, seek, queue, sleep) all function
- [ ] Collapsing overlay returns to bottom bar with audio uninterrupted
- [ ] Desktop: pop-out button still opens new window
- [ ] Desktop: book playback works in persistent player
- [ ] Music playback unaffected on both mobile and desktop
- [ ] TypeScript: zero errors
