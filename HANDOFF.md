# Session Handoff Document
**Date:** 2026-05-07
**Status:** Ready for Handoff

## Current Task
Fix "No track playing" / nothing happens when pressing Play Book or Resume on mobile.

## Root Cause
`playBook` in `PlayerContext.tsx` always called `window.open('/player', ...)` to launch the pop-out player. On mobile browsers, popups are either blocked (returns `null`) or open as a new tab (taking the user away from the page). Either way, nothing plays.

Music works fine on mobile because `playAlbum` dispatches directly to the reducer when no pop-out is open — the PersistentPlayer handles playback in-page.

## Fix Applied
`studio54-web/src/contexts/PlayerContext.tsx` — `playBook` callback:

Added a mobile detection check using `window.matchMedia('(max-width: 767px)').matches`. On mobile, dispatch directly to the reducer (`dispatch({ type: 'PLAY_BOOK', ...payload })`) so the PersistentPlayer handles it — same path as music. Also added a desktop fallback: if `window.open` returns `null` (popup blocked by adblocker), dispatch directly as well.

## Work Completed
- [x] Root cause identified
- [x] Fix applied to `PlayerContext.tsx`
- [x] Docker image rebuilt and container redeployed (healthy)

## Next Steps
Test on mobile: open a book detail page, press Play Book and Resume — audio should play in the bottom persistent player bar.
