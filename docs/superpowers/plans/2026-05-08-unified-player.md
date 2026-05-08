# Unified Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Books play in the built-in persistent player by default (no automatic popup); PersistentPlayer gets the three missing features from PopOutPlayer; mobile gets a fullscreen expand overlay.

**Architecture:** `PlayerContext.playBook` is simplified to always dispatch directly (same as `playAlbum`). `PersistentPlayer.tsx` receives a Now Playing heartbeat, Mark as Read / archive flow, and a `isExpanded` fullscreen overlay toggled by tapping the album art on mobile. PopOutPlayer.tsx is not touched — desktop users still pop out manually via the existing button.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, react-icons/fi, react-hot-toast, @tanstack/react-query

---

## File Map

| File | What changes |
|---|---|
| `studio54-web/src/contexts/PlayerContext.tsx` | Simplify `playBook` — remove `window.open` branch, always dispatch |
| `studio54-web/src/components/PersistentPlayer.tsx` | Add heartbeat, Mark as Read, mobile fullscreen overlay |

Files **not** touched: `PopOutPlayer.tsx`, `BookDetail.tsx`, `Layout.tsx`, `usePlayerBroadcast.ts`.

---

## Task 1 — PlayerContext: Remove Auto Pop-Out from `playBook`

**Files:**
- Modify: `studio54-web/src/contexts/PlayerContext.tsx` (the `playBook` useCallback, currently around line 545)

- [ ] **Step 1: Replace the `playBook` function**

Find and replace the entire `playBook` useCallback. The current version has an `isMobile` branch and a `window.open` call. Replace it with this:

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
    send({ type: 'PLAY_BOOK', payload })
  } else {
    dispatch({ type: 'PLAY_BOOK', ...payload })
  }
}, [isPopOutOpen, send])
```

`PLAY_BOOK_REQUEST_KEY` and its localStorage write are no longer used by `playBook`. Leave the import/constant in place — PopOutPlayer still reads it on init in the other window.

- [ ] **Step 2: TypeScript check**

```bash
cd /home/tesimmons/Studio54/studio54-web && npx tsc --noEmit
```

Expected: no output (zero errors).

- [ ] **Step 3: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/contexts/PlayerContext.tsx
git commit -m "fix: playBook always dispatches to persistent player — no auto popup"
```

---

## Task 2 — PersistentPlayer: Now Playing Heartbeat + Mark as Read

**Files:**
- Modify: `studio54-web/src/components/PersistentPlayer.tsx`

### Step group A: imports and state

- [ ] **Step 1: Add `nowPlayingApi` to the api import and `FiChevronUp`, `FiChevronDown` to react-icons**

Find line 4 (react-icons import) and line 9 (api import). Replace them:

```typescript
import { FiX, FiExternalLink, FiMinimize2, FiVolume2, FiVolume1, FiVolumeX, FiSave, FiCheck, FiBell, FiChevronUp, FiChevronDown } from 'react-icons/fi'
```

```typescript
import { tracksApi, playlistsApi, booksApi, bookProgressApi, listeningSessionApi, nowPlayingApi } from '../api/client'
```

- [ ] **Step 2: Add state variables and heartbeat ref**

Find the sleep timer state block (the block that starts with `// Sleep timer state`). Add these lines immediately before it:

```typescript
  // Archive (Mark as Read) state
  const [sessionArchived, setSessionArchived] = useState(false)
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)

  // Expanded overlay (mobile)
  const [isExpanded, setIsExpanded] = useState(false)
```

Find the line `const snoozeAutoCloseRef = useRef<...>`. Add `heartbeatRef` on the next line:

```typescript
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null)
```

### Step group B: effects and callbacks

- [ ] **Step 3: Add session-reset effect**

Find the existing `useEffect` that calls `document.addEventListener('mousedown', handler)` for the sleep menu. Add this effect block immediately before it (it resets archive state when a new session starts):

```typescript
  useEffect(() => {
    setSessionArchived(false)
    setShowArchiveConfirm(false)
  }, [state.sessionEntityId])
```

- [ ] **Step 4: Add `handleArchiveSession` callback**

Add this immediately after the `snooze15` callback:

```typescript
  const handleArchiveSession = useCallback(async () => {
    if (!state.sessionEntityId || !state.sessionType) return
    try {
      if (state.sessionType === 'book') {
        await listeningSessionApi.archiveBook(state.sessionEntityId)
      } else {
        await listeningSessionApi.archiveSeries(state.sessionEntityId)
      }
      setSessionArchived(true)
      toast.success(state.sessionType === 'series' ? 'Series marked as complete' : 'Marked as read')
    } catch {
      toast.error('Failed — try again from the book page')
    }
    setShowArchiveConfirm(false)
  }, [state.sessionEntityId, state.sessionType])
```

- [ ] **Step 5: Add Now Playing heartbeat effect**

Add this useEffect immediately after the `save-on-close` / beforeunload+visibilitychange effect block, and before `handleEnded`:

```typescript
  // Now Playing heartbeat — fires every 30s while playing; guarded against pop-out double-fire
  useEffect(() => {
    if (isPopOutOpen) return
    const sendHeartbeat = () => {
      if (!state.currentTrack || !state.isPlaying) return
      const heartbeatData: any = {
        track_id: state.currentTrack.id,
        track_title: state.currentTrack.title,
        artist_name: state.currentTrack.artist_name || 'Unknown Artist',
        artist_id: state.currentTrack.artist_id,
        album_id: state.currentTrack.album_id,
        album_title: state.currentTrack.album_title,
        cover_art_url: state.currentTrack.album_cover_art_url,
      }
      if (state.bookId && state.chapterId) {
        heartbeatData.book_id = state.bookId
        heartbeatData.chapter_id = state.chapterId
        heartbeatData.position_ms = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
      }
      nowPlayingApi.heartbeat(heartbeatData).catch(() => {})
    }
    if (heartbeatRef.current) { clearInterval(heartbeatRef.current); heartbeatRef.current = null }
    if (state.currentTrack && state.isPlaying) {
      sendHeartbeat()
      heartbeatRef.current = setInterval(sendHeartbeat, 30000)
    }
    return () => {
      if (heartbeatRef.current) { clearInterval(heartbeatRef.current); heartbeatRef.current = null }
    }
  }, [state.currentTrack?.id, state.isPlaying, isPopOutOpen, state.bookId, state.chapterId, audioRef])
```

Also add heartbeat cleanup to the existing sleep-timer cleanup effect (the `useEffect(() => { return () => { ... } }, [])` block):

```typescript
  useEffect(() => {
    return () => {
      if (sleepTimerRef.current) clearTimeout(sleepTimerRef.current)
      if (sleepTickRef.current) clearInterval(sleepTickRef.current)
      if (snoozeAutoCloseRef.current) clearTimeout(snoozeAutoCloseRef.current)
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
    }
  }, [])
```

### Step group C: JSX — archive confirm dialog

- [ ] **Step 6: Add archive confirm overlay to main return**

The main return block (the "Full Bottom Bar" return) has this structure at the top:

```tsx
      {audioElement}

      {showSnoozePopup && (
        <div className="fixed inset-0 ...">
```

Add the archive confirm overlay immediately after `{showSnoozePopup && (...)}`:

```tsx
      {showArchiveConfirm && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/60 z-[60]">
          <div className="bg-white dark:bg-[#1a1a2e] border border-gray-200 dark:border-gray-700 rounded-xl p-5 text-center shadow-xl mx-4">
            <p className="text-gray-900 dark:text-white font-medium mb-1">
              {state.sessionType === 'series' ? 'Mark Series as Complete?' : 'Mark as Read?'}
            </p>
            <p className="text-xs text-gray-500 dark:text-[#8B949E] mb-4">Your progress will be kept for 7 days in case you need to recover it.</p>
            <div className="flex gap-2 justify-center">
              <button onClick={handleArchiveSession} className="px-4 py-2 rounded-lg bg-[#FF1493] hover:bg-[#FF1493]/80 text-white font-medium transition-colors">Confirm</button>
              <button onClick={() => setShowArchiveConfirm(false)} className="px-4 py-2 rounded-lg bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 text-gray-900 dark:text-white font-medium transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}
```

### Step group D: JSX — Mark as Read button in controls

- [ ] **Step 7: Add Mark as Read button to desktop controls**

In the `hidden md:flex` desktop controls div, find the sleep timer `<div className="relative" data-sleep-menu>` block. Add the Mark as Read button immediately before it:

```tsx
            {/* Mark as Read */}
            {isBookChapter && state.sessionType && state.sessionEntityId && (
              sessionArchived ? (
                <span className="p-1 lg:p-2 text-green-500" title="Marked as read">
                  <FiCheck className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10" />
                </span>
              ) : (
                <button
                  title={state.sessionType === 'series' ? 'Mark Series as Complete' : 'Mark as Read'}
                  onClick={() => setShowArchiveConfirm(true)}
                  className="p-1 lg:p-2 rounded-lg transition-colors text-gray-500 dark:text-[#8B949E] hover:text-green-400"
                >
                  <FiCheck className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10" />
                </button>
              )
            )}
```

- [ ] **Step 8: Add Mark as Read button to mobile bottom row**

In the `flex md:hidden` mobile bottom row, find the sleep timer `<div className="relative" data-sleep-menu>` block. Add the Mark as Read button immediately before it:

```tsx
          {isBookChapter && state.sessionType && state.sessionEntityId && (
            sessionArchived ? (
              <span className="p-1 text-green-500" title="Marked as read"><FiCheck className="w-7 h-7" /></span>
            ) : (
              <button
                title={state.sessionType === 'series' ? 'Mark Series as Complete' : 'Mark as Read'}
                onClick={() => setShowArchiveConfirm(true)}
                className="p-1 rounded transition-colors text-gray-500 dark:text-[#8B949E] hover:text-green-400"
              >
                <FiCheck className="w-7 h-7" />
              </button>
            )
          )}
```

- [ ] **Step 9: TypeScript check**

```bash
cd /home/tesimmons/Studio54/studio54-web && npx tsc --noEmit
```

Expected: no output.

- [ ] **Step 10: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/components/PersistentPlayer.tsx
git commit -m "feat: add Now Playing heartbeat and Mark as Read to persistent player"
```

---

## Task 3 — PersistentPlayer: Mobile Fullscreen Expand Overlay

**Files:**
- Modify: `studio54-web/src/components/PersistentPlayer.tsx`

### Step group A: Expand triggers in the bottom bar

- [ ] **Step 1: Make the mobile album art tappable**

In the mobile track info section, find the `<img>` tag for the album art on mobile (the one around the second `album_cover_art_url` reference, line ~705). It currently sits inside a plain `<div>`. Wrap only the mobile instance in a `<button>`:

Find this pattern (the mobile album art, which is inside an `md:flex` or similar mobile section):
```tsx
              src={currentTrack.album_cover_art_url || S54.defaultAlbumArt}
```

The mobile album art `<img>` lives inside a container. Wrap it with:
```tsx
              <button className="md:hidden flex-shrink-0 rounded overflow-hidden" onClick={() => setIsExpanded(true)} aria-label="Expand player">
                <img
                  src={currentTrack.album_cover_art_url || S54.defaultAlbumArt}
                  alt=""
                  className="w-16 h-16 object-cover"
                  onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultAlbumArt }}
                />
              </button>
```

> **Note:** Grep for the exact surrounding code first: `grep -n "album_cover_art_url\|defaultAlbumArt" studio54-web/src/components/PersistentPlayer.tsx` to confirm which instance is the mobile one (the one inside the `md:hidden` or bottom section, not the desktop sidebar track info).

- [ ] **Step 2: Add FiChevronUp expand button to mobile bottom row**

In the `flex md:hidden` mobile bottom row, add a chevron-up button as the first item (before shuffle):

```tsx
          <button
            className="p-1 rounded transition-colors text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]"
            onClick={() => setIsExpanded(true)}
            title="Expand player"
          >
            <FiChevronUp className="w-7 h-7" />
          </button>
```

### Step group B: Fullscreen overlay JSX

- [ ] **Step 3: Add the expanded overlay to the main return**

In the "Full Bottom Bar" return block, add the overlay immediately after the archive confirm dialog block (before `{showLyrics && ...}`):

```tsx
      {isExpanded && (
        <div className="fixed inset-0 z-[60] bg-[#0D1117] text-white flex flex-col select-none overflow-hidden">
          {/* Overlays inside expanded view */}
          {showArchiveConfirm && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/70 z-50">
              <div className="bg-[#1a1a2e] border border-gray-700 rounded-xl p-5 text-center shadow-xl mx-4">
                <p className="text-white font-medium mb-1">
                  {state.sessionType === 'series' ? 'Mark Series as Complete?' : 'Mark as Read?'}
                </p>
                <p className="text-xs text-[#8B949E] mb-4">Your progress will be kept for 7 days in case you need to recover it.</p>
                <div className="flex gap-2 justify-center">
                  <button onClick={handleArchiveSession} className="px-4 py-2 rounded-lg bg-[#FF1493] hover:bg-[#FF1493]/80 text-white font-medium transition-colors">Confirm</button>
                  <button onClick={() => setShowArchiveConfirm(false)} className="px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-white font-medium transition-colors">Cancel</button>
                </div>
              </div>
            </div>
          )}
          {showSnoozePopup && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/70 z-50">
              <div className="bg-[#1a1a2e] border border-gray-700 rounded-xl p-5 text-center shadow-xl">
                <p className="text-white font-medium mb-3">Sleep timer ended</p>
                <div className="flex gap-2 justify-center">
                  <button onClick={snooze15} className="px-4 py-2 rounded-lg bg-[#FF1493] hover:bg-[#FF1493]/80 text-white font-medium transition-colors">+ 15 minutes</button>
                  <button onClick={() => { if (snoozeAutoCloseRef.current) clearTimeout(snoozeAutoCloseRef.current); setShowSnoozePopup(false) }} className="px-4 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors">Dismiss</button>
                </div>
              </div>
            </div>
          )}

          {/* Top bar */}
          <div className="flex items-center justify-between px-4 pt-4 pb-2 flex-shrink-0">
            <button onClick={() => setIsExpanded(false)} className="p-2 text-[#8B949E] hover:text-white transition-colors">
              <FiChevronDown className="w-6 h-6" />
            </button>
            <span className="text-xs text-[#8B949E] font-medium">
              {queue.length > 0 ? `${(state.sessionCurrentIndex ?? 0) + 1} of ${(state.sessionCurrentIndex ?? 0) + 1 + queue.length}` : ''}
            </span>
            <button onClick={closePlayer} className="p-2 text-[#8B949E] hover:text-white transition-colors">
              <FiX className="w-5 h-5" />
            </button>
          </div>

          {/* Album art */}
          <div className="flex justify-center px-8 py-2 flex-shrink-0">
            <div className="w-full aspect-square max-w-[260px] rounded-xl overflow-hidden shadow-2xl bg-[#161B22]">
              <img
                src={currentTrack.album_cover_art_url || S54.defaultAlbumArt}
                alt=""
                className="w-full h-full object-cover"
                onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultAlbumArt }}
              />
            </div>
          </div>

          {/* Track info */}
          <div className="px-8 py-3 text-center flex-shrink-0">
            <p className="text-white font-semibold text-lg truncate">{currentTrack.title}</p>
            <p className="text-[#8B949E] text-sm truncate mt-0.5">{currentTrack.artist_name || currentTrack.album_title || ''}</p>
          </div>

          {/* Seek bar */}
          <div className="px-8 pb-3 flex-shrink-0">
            <input
              type="range" min={0} max={duration || 1} step={0.1} value={currentTime}
              onChange={handleSeek}
              className="w-full h-1 bg-[#30363D] rounded-full appearance-none cursor-pointer accent-[#FF1493]"
            />
            <div className="flex justify-between text-xs text-[#8B949E] mt-1">
              <span>{formatTime(currentTime)}</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>

          {/* Transport */}
          <div className="flex items-center justify-center gap-8 pb-4 flex-shrink-0">
            <button onClick={previous} className="p-2 text-[#8B949E] hover:text-white transition-colors">
              <img src={S54.player.rewind} alt="Previous" className="w-8 h-8 object-contain" />
            </button>
            <button
              onClick={() => isPlaying ? pause() : resume()}
              className="w-16 h-16 rounded-full bg-[#FF1493] hover:bg-[#d10f7a] text-white flex items-center justify-center transition-colors"
            >
              <img src={isPlaying ? S54.player.pause : S54.player.play} alt={isPlaying ? 'Pause' : 'Play'} className="w-8 h-8 object-contain brightness-0 invert" />
            </button>
            <button onClick={next} className="p-2 text-[#8B949E] hover:text-white transition-colors">
              <img src={S54.player.fastForward} alt="Next" className="w-8 h-8 object-contain" />
            </button>
          </div>

          {/* Secondary controls */}
          <div className="flex items-center justify-center gap-5 pb-3 flex-shrink-0">
            {renderShuffleButton('w-6 h-6', 'p-2')}
            {renderRepeatButton('w-6 h-6', 'p-2')}

            {/* Sleep timer */}
            <div className="relative" data-sleep-menu>
              <button
                title={sleepTimerEndsAt ? `Sleep: ${sleepTimerDisplay}` : sleepTimerEndOfTrack ? `Sleep: end of ${isBookChapter ? 'chapter' : 'song'}` : 'Sleep timer'}
                onClick={() => setShowSleepMenu(v => !v)}
                className={`p-2 rounded-lg transition-colors flex items-center gap-0.5 ${sleepTimerEndsAt || sleepTimerEndOfTrack ? 'text-[#FF1493]' : 'text-[#8B949E] hover:text-white'}`}
              >
                <FiBell className="w-6 h-6" />
                {(sleepTimerEndsAt || sleepTimerEndOfTrack) && (
                  <span className="text-[9px] font-medium">{sleepTimerEndOfTrack ? (isBookChapter ? 'EOC' : 'EOS') : sleepTimerDisplay}</span>
                )}
              </button>
              {showSleepMenu && (
                <div className="absolute bottom-12 left-1/2 -translate-x-1/2 bg-[#1a1a2e] border border-gray-700 rounded-lg shadow-xl p-3 z-50 w-52">
                  <p className="text-xs text-gray-400 mb-2 font-medium">Sleep Timer</p>
                  <div className="grid grid-cols-2 gap-1 mb-2">
                    {[15, 30, 45, 60].map(m => (
                      <button key={m} onClick={() => setSleepTimer(m)} className="px-2 py-1 text-sm rounded bg-gray-800 hover:bg-[#FF1493] transition-colors text-white">{m} min</button>
                    ))}
                  </div>
                  <button onClick={setSleepTimerEndOfTrackMode} className="w-full px-2 py-1 text-sm rounded bg-gray-800 hover:bg-[#FF1493] transition-colors text-white mb-2">
                    End of {isBookChapter ? 'chapter' : 'song'}
                  </button>
                  <div className="flex gap-1">
                    <input type="number" min="1" max="999" value={customMinutes} onChange={e => setCustomMinutes(e.target.value)} placeholder="_ min" className="flex-1 px-2 py-1 text-sm rounded bg-gray-800 text-white border border-gray-600 focus:border-[#FF1493] outline-none" />
                    <button onClick={() => { const m = parseInt(customMinutes); if (m > 0) setSleepTimer(m) }} className="px-2 py-1 text-sm rounded bg-[#FF1493] hover:bg-[#FF1493]/80 text-white">Set</button>
                  </div>
                  {(sleepTimerEndsAt || sleepTimerEndOfTrack) && (
                    <button onClick={clearSleepTimer} className="w-full mt-2 px-2 py-1 text-sm rounded bg-gray-700 hover:bg-gray-600 text-white transition-colors">Cancel timer</button>
                  )}
                </div>
              )}
            </div>

            {/* Mark as Read */}
            {isBookChapter && state.sessionType && state.sessionEntityId && (
              sessionArchived ? (
                <span className="p-2 text-green-400" title="Marked as read"><FiCheck className="w-6 h-6" /></span>
              ) : (
                <button
                  title={state.sessionType === 'series' ? 'Mark Series as Complete' : 'Mark as Read'}
                  onClick={() => setShowArchiveConfirm(true)}
                  className="p-2 text-[#8B949E] hover:text-green-400 transition-colors"
                >
                  <FiCheck className="w-6 h-6" />
                </button>
              )
            )}

            {/* Queue toggle */}
            <button
              onClick={() => setShowQueue(prev => !prev)}
              title={showQueue ? 'Hide queue' : 'Show queue'}
              className={`p-2 rounded-lg transition-colors relative ${showQueue ? 'text-[#FF1493]' : 'text-[#8B949E] hover:text-white'}`}
            >
              <img src={S54.player.playlist} alt="Queue" className="w-6 h-6 object-contain" />
              {queue.length > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-[#FF1493] text-white text-[7px] font-bold rounded-full flex items-center justify-center">{queue.length}</span>
              )}
            </button>
          </div>

          {/* Collapsible queue */}
          {showQueue && (
            <div className="flex-1 overflow-hidden px-2 pb-2">
              {renderQueueList('100%', 'w-full')}
            </div>
          )}
        </div>
      )}
```

- [ ] **Step 4: Collapse overlay when player closes**

Find the `closePlayer` call in the existing `usePlayer()` destructure (line ~14). When `closePlayer` is called, `isExpanded` should also close. Add a wrapped handler rather than changing the API — find where `closePlayer` is called in the JSX close button and wrap it:

In the overlay top bar, the close button already calls `closePlayer`. In the main bar, the close button also calls `closePlayer`. Additionally add a `useEffect` to collapse the overlay if the player closes (currentTrack becomes null):

```typescript
  useEffect(() => {
    if (!currentTrack) setIsExpanded(false)
  }, [currentTrack])
```

Add this effect near the other track-watching effects.

- [ ] **Step 5: TypeScript check**

```bash
cd /home/tesimmons/Studio54/studio54-web && npx tsc --noEmit
```

Expected: no output.

---

## Task 4 — Build, Deploy, Verify

- [ ] **Step 1: Build Docker image**

```bash
cd /home/tesimmons/Studio54
sudo docker compose build studio54-web 2>&1 | tail -5
```

Expected: last line contains `Built`.

- [ ] **Step 2: Redeploy**

```bash
sudo docker compose stop studio54-web && sudo docker compose up -d studio54-web
```

- [ ] **Step 3: Confirm healthy**

```bash
sleep 12 && sudo docker compose ps studio54-web
```

Expected: `STATUS` column shows `Up ... (healthy)`.

- [ ] **Step 4: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/components/PersistentPlayer.tsx
git commit -m "feat: mobile fullscreen expand overlay for persistent player"
```

- [ ] **Step 5: Manual verification checklist**

On a **mobile browser**:
- [ ] Play Book on a book → audio starts in bottom bar, no popup opens
- [ ] Resume on a partially-played book → audio starts at correct chapter and position
- [ ] Tap album art in bottom bar → fullscreen overlay opens
- [ ] Tap chevron-up in bottom bar → fullscreen overlay opens
- [ ] All transport controls (prev/play/next/seek) work in overlay
- [ ] Sleep timer button works in overlay
- [ ] Queue panel toggles in overlay
- [ ] Mark as Read button appears for book; confirm dialog works; button becomes checkmark
- [ ] Tap chevron-down → collapses back to bar, audio uninterrupted
- [ ] Music playback works normally (no popup, plays in bar)

- [ ] Resume on a book plays at correct **chapter** (not always chapter 1) and correct **position within that chapter** (not always 0:00)

On **desktop browser**:
- [ ] Play Book → audio starts in bottom bar (no popup)
- [ ] Pop-out button (`FiExternalLink`) still opens new window
- [ ] Mark as Read button visible in desktop bar during book playback
- [ ] Now Playing heartbeat fires (check server logs or network tab for `/api/v1/now-playing/heartbeat` requests at ~30s intervals)
- [ ] Music playback unaffected
