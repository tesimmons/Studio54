# Studio54 UI Update — Implementation Plan

> **STATUS TRACKING — UPDATE THIS SECTION AS EACH PHASE COMPLETES**
>
> When a phase is done, change `[ ]` to `[x]` and add the completion date.
> If a phase reveals unexpected work, document it in the Notes column before continuing.
>
> | Phase | Title | Status | Completed | Notes |
> |-------|-------|--------|-----------|-------|
> | 1 | Image Assets & Graphics Registry | [ ] | | |
> | 2 | Navigation Config | [ ] | | |
> | 3 | NavIcon Component | [ ] | | |
> | 4 | CommandPalette Component | [ ] | | |
> | 5 | Desktop Sidebar Rewrite | [ ] | | |
> | 6 | Mobile Shell Rewrite | [ ] | | |
> | 7 | PersistentPlayer Audio-Only Mode | [ ] | | |
> | 8 | SidebarPlayer Mini-Player Component | [ ] | | |
> | 9 | PageHeader Component | [ ] | | |
> | 10 | Apply PageHeader to All Pages | [ ] | | |
> | 11 | HowTo Page Neon Cards | [ ] | | |
> | 12 | PopOutPlayer Full-Controls Audit | [ ] | | |
> | 13 | Final Integration & Cleanup | [ ] | | |
> | 14 | Validation Test Suite | [ ] | | |

---

## Hard Constraints (Do Not Violate)

These rules come directly from the user. Read them before every phase.

1. **Zero functionality changes.** All features, data flows, API calls, state management, auth logic, and routing must work exactly as they do today. This is a visual-layer update only.
2. **No backend changes** without an explicit written explanation and user approval. The ⌘K palette is confirmed as client-side only (no backend).
3. **No refactoring for simplicity.** Three similar lines stay as three similar lines. Do not extract helper functions, rename variables, or restructure files unless the UI update literally requires it.
4. **No shortcuts.** Take the correct, stable path even if it is longer.
5. **Do not fix unrelated bugs.** If you notice a bug outside the UI update scope, document it in a comment but do not fix it.
6. **Routes may change only if required for the UI update.** No other reason.
7. **Preserve all existing redirects** (`/statistics → /dashboard`, `/queue-status → /activity`, etc.). They must continue to work.
8. **Role-based access control is unchanged.** Nav items for DJ-only and Director-only pages remain hidden from users without that role. Role badges (`DJ` / `DIR`) are shown on items the user CAN see, as a hint that the feature is role-exclusive.
9. **Ask before acting on any ambiguity.** If this plan is unclear on any point, stop and ask rather than improvise.

---

## Architecture Decisions

Document decisions made during planning so future phases do not re-litigate them.

### Player Architecture
- The `PersistentPlayer` bottom bar is **removed from the desktop and mobile main-window layouts**. Its visual UI is replaced by:
  - **Desktop**: a mini-player strip at the bottom of the new sidebar (`SidebarPlayer` component)
  - **Mobile**: a floating mini-player card above the tab bar (same `SidebarPlayer` component, different CSS)
- `PersistentPlayer.tsx` **keeps all audio logic, all useEffects, the `<audio>` element, and the keep-alive element unchanged.** Only the visual JSX that renders the bottom bar is gated: on the main window (not pop-out), PersistentPlayer renders only the audio elements with no visible UI.
- The pop-out indicator bar (currently shown in PersistentPlayer when `isPopOutOpen === true`) is **also moved to SidebarPlayer**, which already has access to `isPopOutOpen` via `usePlayer()`.
- **Lyrics panel and queue panel** are accessible only via the pop-out player window. The sidebar mini-player has a "pop-out" button specifically to give users access to full controls. This matches the user's explicit direction: *"full functionality exists in the popout player."*
- `PopOutPlayer.tsx` is **unchanged**. It already contains the full controls.

### Navigation
- The new nav uses 4 groups: `Listen`, `Collection`, `Activity`, `System`.
- Role-based visibility: items are still **hidden** for users without the required role. Items the user CAN see that have a role restriction display a small `DJ` or `DIR` badge.
- The `⌘K` palette is **client-side only** — it searches `NAV_GROUPS` labels. No backend changes.
- Route paths are **unchanged**. The nav config maps to existing routes.

### Mobile Layout
- Old mobile: hamburger top bar → overlay drawer.
- New mobile: top header bar + 5-tab bottom bar + "More" drawer (full-screen).
- `PersistentPlayer` is shifted above the tab bar on mobile by wrapping it in a container that applies `mb-[72px]` on mobile only.

### Images
- Handoff images (`studio54-handoff/images/`) are the **authoritative versions** for all nav icons.
- Existing `public/images/` files that are replaced are **moved to `public/images/archive/`** — not deleted. They will be deleted after the project is approved and working.
- The handoff images are **copied** (not moved) to `public/images/`. The handoff folder is not modified.

### Page Headers
- All 13 main pages are updated to use the new `PageHeader` component with the `GROUP · TITLE` eyebrow pattern.
- Page functionality (data loading, mutations, modals, tabs) is **not touched** — only the header JSX changes.

---

## File Map — What Gets Created or Modified

### New files
| File | Purpose |
|------|---------|
| `src/config/navigation.ts` | NAV_GROUPS constant — single source of truth for nav structure |
| `src/components/NavIcon.tsx` | Neon plaque wrapper component |
| `src/components/CommandPalette.tsx` | ⌘K jump-to-anywhere overlay |
| `src/components/SidebarPlayer.tsx` | Mini now-playing strip for sidebar + mobile float |
| `src/components/PageHeader.tsx` | GROUP · TITLE eyebrow header component |
| `public/images/archive/` | Directory for archived/replaced image files |

### Modified files
| File | What changes |
|------|-------------|
| `src/assets/graphics.ts` | Update `nav.*` refs to handoff neon plaque icons; add `neonNav.*` sub-object |
| `src/components/Layout.tsx` | Full rewrite of sidebar and mobile shell; wire CommandPalette; add SidebarPlayer |
| `src/components/PersistentPlayer.tsx` | Add a guard: on main window, render only audio elements (no visual bar) |
| `src/pages/HowTo.tsx` | Replace guide card icons with NavIcon neon plaques |
| All 13 main pages | Replace existing page header JSX with `<PageHeader>` component |
| `public/images/` | Add handoff images; archive replaced images |

### Unchanged files (verified)
- `src/contexts/PlayerContext.tsx` — no changes
- `src/hooks/usePlayerBroadcast.ts` — no changes
- `src/pages/PopOutPlayer.tsx` — no changes (full controls already here)
- `src/App.tsx` — no changes (routes, redirects all stay)
- `src/api/client.ts` — no changes
- `src/contexts/AuthContext.tsx` — no changes
- All page content components (data, tabs, modals) — no changes

---

## Phase 1: Image Assets & Graphics Registry

**Goal:** Copy handoff neon plaque images into `public/images/`, archive replaced files, update `graphics.ts`.

**No functionality changes. Image paths only.**

### Steps

- [ ] **1.1 — Create archive directory**
  ```
  public/images/archive/
  ```

- [ ] **1.2 — Archive replaced files**
  Move these existing files FROM `public/images/` TO `public/images/archive/`. Do not delete them.
  ```
  activity-new.png        → archive/activity-new.png
  Activity.png            → archive/Activity.png
  albums-new.png          → archive/albums-new.png
  Albums.menu.png         → archive/Albums.menu.png
  albumn.png              → archive/albumn.png
  Calendar.png            → archive/Calendar.png
  Dashboard.png           → archive/Dashboard.png
  dj-request-new.png      → archive/dj-request-new.png
  DJ.Request.png          → archive/DJ.Request.png
  file-management-new.png → archive/file-management-new.png
  File.Management.png     → archive/File.Management.png
  how-to-new.png          → archive/how-to-new.png
  How.To.png              → archive/How.To.png
  playlists-new.png       → archive/playlists-new.png
  Playlist.menu.png       → archive/Playlist.menu.png
  settings-new.png        → archive/settings-new.png
  Settings.png            → archive/Settings.png
  sound-booth-new.png     → archive/sound-booth-new.png
  Soundbooth.png          → archive/Soundbooth.png
  Statistics.png          → archive/Statistics.png
  Statistics.alternate.png → archive/Statistics.alternate.png
  studio54-logo.png       → archive/studio54-logo.png
  Studio54.Logo.png       → archive/Studio54.Logo.png
  disco-lounge.png        → archive/disco-lounge.png
  reading-room.png        → archive/reading-room.png
  listen.png              → archive/listen.png
  listen_add.png          → archive/listen_add.png
  app-background.png      → archive/app-background.png
  app.background.png      → archive/app.background.png
  default-album-art.png   → archive/default-album-art.png
  default.album.art.png   → archive/default.album.art.png
  pause.png               → archive/pause.png
  play.png                → archive/play.png
  repeat.png              → archive/repeat.png
  rewind.png              → archive/rewind.png
  FastForward.png         → archive/FastForward.png
  shuffle.png             → archive/shuffle.png
  playlist-cover.jpg      → archive/playlist-cover.jpg
  Playlist.cover.jpg      → archive/Playlist.cover.jpg
  ```

- [ ] **1.3 — Copy handoff images into `public/images/`**
  Copy FROM `studio54-handoff/images/` TO `public/images/` with these target names:
  ```
  handoff: activity.png       → public/images/activity.png
  handoff: albums.png         → public/images/albums.png
  handoff: bg.png             → public/images/app-background.png
  handoff: calendar.png       → public/images/calendar.png
  handoff: dashboard.png      → public/images/dashboard.png
  handoff: default-album.png  → public/images/default-album-art.png
  handoff: disco-lounge.png   → public/images/disco-lounge.png
  handoff: dj-requests.png    → public/images/dj-requests.png
  handoff: file-management.png → public/images/file-management.png
  handoff: how-to.png         → public/images/how-to.png
  handoff: listen.png         → public/images/listen.png
  handoff: logo.png           → public/images/studio54-logo.png
  handoff: pause.png          → public/images/pause.png
  handoff: play.png           → public/images/play.png
  handoff: playlist-cover.jpg → public/images/playlist-cover.jpg
  handoff: playlists.png      → public/images/playlists.png
  handoff: reading-room.png   → public/images/reading-room.png
  handoff: repeat.png         → public/images/repeat.png
  handoff: rewind.png         → public/images/rewind.png
  handoff: settings.png       → public/images/settings.png
  handoff: shuffle.png        → public/images/shuffle.png
  handoff: sound-booth.png    → public/images/sound-booth.png
  ```
  Note: `fast-forward.png` in the handoff → `public/images/FastForward.png` (keep existing casing for the graphics.ts reference).

- [ ] **1.4 — Update `src/assets/graphics.ts`**
  Rewrite the `nav` sub-object to point at the new canonical names. Keep all other keys (`player`, `favSelected`, etc.) pointing at their existing files — only update `nav.*` refs that changed. The full updated object:
  ```typescript
  export const S54 = {
    logo: '/images/studio54-logo.png',
    background: '/images/app-background.png',
    loading: '/images/Loading.png',
    defaultAlbumArt: '/images/default-album-art.png',
    defaultBookCover: '/images/unknown-book.png',
    defaultPlaylistCover: '/images/playlist-cover.jpg',
    search: '/images/search.png',
    menu: '/images/Menu.png',
    director: '/images/director.png',
    album: '/images/albums.png',
    listen: '/images/listen.png',
    preview30s: '/images/30sec-preview.png',

    nav: {
      dashboard:      '/images/dashboard.png',
      discoLounge:    '/images/disco-lounge.png',
      readingRoom:    '/images/reading-room.png',
      soundBooth:     '/images/sound-booth.png',
      listenAdd:      '/images/listen.png',
      albums:         '/images/albums.png',
      playlists:      '/images/playlists.png',
      fileManagement: '/images/file-management.png',
      djRequest:      '/images/dj-requests.png',
      calendar:       '/images/calendar.png',
      activity:       '/images/activity.png',
      settings:       '/images/settings.png',
      howTo:          '/images/how-to.png',
      // keep legacy keys that other components may reference:
      library:        '/images/disco-lounge.png',
      downloads:      '/images/activity.png',
      queueStatus:    '/images/activity.png',
      statistics:     '/images/dashboard.png',
      libraryImport:  '/images/file-management.png',
      download:       '/images/activity.png',
    },

    player: {
      play:        '/images/play.png',
      pause:       '/images/pause.png',
      rewind:      '/images/rewind.png',
      fastForward: '/images/FastForward.png',
      shuffle:     '/images/shuffle.png',
      repeat:      '/images/repeat.png',
      playlist:    '/images/player-playlist.png',
      lyrics:      '/images/Lyrics.png',
    },

    favSelected:    '/images/fav-selected.png',
    favUnselected:  '/images/fav-unselected.png',
    starSelected:   '/images/star-selected.png',
    starUnselected: '/images/star-unselected.png',
  } as const
  ```

- [ ] **1.5 — TypeScript compile check**
  ```bash
  node /home/tesimmons/Studio54/studio54-web/node_modules/typescript/bin/tsc \
    --noEmit --project /home/tesimmons/Studio54/studio54-web/tsconfig.json
  ```
  Expected: no errors.

---

## Phase 2: Navigation Config

**Goal:** Create a single source of truth for the nav structure. This is a new file — no existing file is changed.

**No functionality changes.**

- [ ] **2.1 — Create `src/config/navigation.ts`**

  ```typescript
  // Navigation groups — single source of truth for sidebar, mobile tabs, drawer, and ⌘K palette.
  // Role filtering is enforced in Layout.tsx using AuthContext, not here.
  // badge values are static placeholders; dynamic badges (e.g. pending requests) are
  // injected at render time in Layout.tsx.

  export interface NavItem {
    id: string
    to: string
    icon: string        // path to neon plaque PNG, from S54.nav
    label: string
    sub?: string        // subtitle shown under label in some contexts
    role?: 'dj' | 'director'   // minimum role required; undefined = all roles
    badge?: number      // static badge; override dynamically in Layout
  }

  export interface NavGroup {
    label: string
    items: NavItem[]
  }

  import { S54 } from '../assets/graphics'

  export const NAV_GROUPS: NavGroup[] = [
    {
      label: 'Listen',
      items: [
        { id: 'disco-lounge',  to: '/disco-lounge',  icon: S54.nav.discoLounge,    label: 'Disco Lounge',  sub: 'Music library' },
        { id: 'reading-room',  to: '/reading-room',  icon: S54.nav.readingRoom,    label: 'Reading Room',  sub: 'Audiobooks' },
        { id: 'sound-booth',   to: '/sound-booth',   icon: S54.nav.soundBooth,     label: 'Sound Booth',   sub: 'Live mix' },
        { id: 'listen',        to: '/listen',         icon: S54.nav.listenAdd,      label: 'Listen & Add',  sub: 'Discover new' },
      ],
    },
    {
      label: 'Collection',
      items: [
        { id: 'albums',           to: '/albums',           icon: S54.nav.albums,         label: 'Albums' },
        { id: 'playlists',        to: '/playlists',         icon: S54.nav.playlists,      label: 'Playlists' },
        { id: 'file-management',  to: '/file-management',  icon: S54.nav.fileManagement, label: 'File Mgmt',  role: 'dj' },
      ],
    },
    {
      label: 'Activity',
      items: [
        { id: 'dashboard',    to: '/dashboard',    icon: S54.nav.dashboard,  label: 'Dashboard',    role: 'dj' },
        { id: 'dj-requests',  to: '/dj-requests',  icon: S54.nav.djRequest,  label: 'DJ Requests' },
        { id: 'calendar',     to: '/calendar',     icon: S54.nav.calendar,   label: 'Calendar' },
        { id: 'activity',     to: '/activity',     icon: S54.nav.activity,   label: 'Activity',     role: 'dj' },
      ],
    },
    {
      label: 'System',
      items: [
        { id: 'settings', to: '/settings', icon: S54.nav.settings, label: 'Settings', role: 'director' },
        { id: 'how-to',   to: '/how-to',   icon: S54.nav.howTo,    label: 'How To' },
      ],
    },
  ]

  // Flat list used by CommandPalette and mobile tab lookups
  export const FLAT_NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap(g => g.items)

  // The 4 bottom-tab items shown on mobile (the rest go in the "More" drawer)
  export const MOBILE_TABS: NavItem[] = [
    NAV_GROUPS[0].items[0], // Disco Lounge → Listen
    NAV_GROUPS[1].items[0], // Albums → Library
    NAV_GROUPS[1].items[1], // Playlists
    NAV_GROUPS[2].items[1], // DJ Requests
  ]
  ```

- [ ] **2.2 — TypeScript compile check** (same command as 1.5)

---

## Phase 3: NavIcon Component

**Goal:** The reusable neon plaque wrapper used in sidebar rows, mobile tabs, mobile drawer rows, and HowTo cards.

- [ ] **3.1 — Create `src/components/NavIcon.tsx`**

  ```tsx
  interface NavIconProps {
    src: string
    alt?: string
    active?: boolean
    size?: 'sm' | 'md' | 'lg'   // sm = mobile tab (32×32 plaque, 26×26 img)
                                  // md = sidebar (36×36 plaque, 28×28 img)
                                  // lg = HowTo cards (56×56 plaque, 44×44 img)
  }

  const SIZE_MAP = {
    sm: { plaque: 'w-8 h-8',   img: 'w-[26px] h-[26px]', radius: 'rounded-lg' },
    md: { plaque: 'w-9 h-9',   img: 'w-7 h-7',            radius: 'rounded-lg' },
    lg: { plaque: 'w-14 h-14', img: 'w-11 h-11',           radius: 'rounded-xl' },
  }

  export default function NavIcon({ src, alt = '', active = false, size = 'md' }: NavIconProps) {
    const { plaque, img, radius } = SIZE_MAP[size]
    return (
      <div
        className={`
          ${plaque} ${radius} flex-shrink-0 bg-black flex items-center justify-center
          ${active
            ? 'shadow-[0_0_14px_rgba(255,20,147,0.55),inset_0_0_0_1px_rgba(255,20,147,0.45)]'
            : 'shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05)]'
          }
        `}
      >
        <img
          src={src}
          alt={alt}
          className={`${img} object-contain ${active ? '' : '[filter:saturate(0.85)_brightness(0.92)]'}`}
        />
      </div>
    )
  }
  ```

- [ ] **3.2 — TypeScript compile check**

---

## Phase 4: CommandPalette Component

**Goal:** ⌘K / Ctrl+K overlay that fuzzy-matches nav item labels. No backend calls. Navigation uses `useNavigate` from react-router-dom.

- [ ] **4.1 — Create `src/components/CommandPalette.tsx`**

  ```tsx
  import { useState, useEffect, useRef, useCallback } from 'react'
  import { useNavigate } from 'react-router-dom'
  import { useAuth } from '../contexts/AuthContext'
  import { NAV_GROUPS } from '../config/navigation'
  import NavIcon from './NavIcon'
  import type { NavItem } from '../config/navigation'

  interface CommandPaletteProps {
    open: boolean
    onClose: () => void
  }

  // Simple substring match — no external fuzzy library needed
  function matchesQuery(item: NavItem, query: string): boolean {
    if (!query) return true
    const q = query.toLowerCase()
    return (
      item.label.toLowerCase().includes(q) ||
      (item.sub?.toLowerCase().includes(q) ?? false)
    )
  }

  export default function CommandPalette({ open, onClose }: CommandPaletteProps) {
    const [query, setQuery] = useState('')
    const inputRef = useRef<HTMLInputElement>(null)
    const navigate = useNavigate()
    const { isDirector, isDjOrAbove } = useAuth()
    const [selectedIndex, setSelectedIndex] = useState(0)

    // Filter items by role (same logic as Layout nav filtering)
    const visibleItems: NavItem[] = NAV_GROUPS
      .flatMap(g => g.items.map(item => ({ ...item, groupLabel: g.label })))
      .filter(item => {
        if (!item.role) return true
        if (item.role === 'director') return isDirector
        if (item.role === 'dj') return isDjOrAbove
        return true
      })
      .filter(item => matchesQuery(item, query))

    useEffect(() => {
      if (open) {
        setQuery('')
        setSelectedIndex(0)
        setTimeout(() => inputRef.current?.focus(), 10)
      }
    }, [open])

    useEffect(() => { setSelectedIndex(0) }, [query])

    const handleSelect = useCallback((item: NavItem) => {
      navigate(item.to)
      onClose()
    }, [navigate, onClose])

    const handleKeyDown = (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIndex(i => Math.min(i + 1, visibleItems.length - 1)) }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setSelectedIndex(i => Math.max(i - 1, 0)) }
      if (e.key === 'Enter' && visibleItems[selectedIndex]) { handleSelect(visibleItems[selectedIndex]) }
    }

    if (!open) return null

    return (
      <div
        className="fixed inset-0 bg-black/60 z-50 flex items-start justify-center pt-24"
        onClick={onClose}
      >
        <div
          className="w-full max-w-md bg-[#161B22] border border-[#30363D] rounded-xl shadow-2xl overflow-hidden"
          onClick={e => e.stopPropagation()}
        >
          {/* Search input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-[#30363D]">
            <span className="text-[#8B949E] text-base">⌕</span>
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Jump to anywhere…"
              className="flex-1 bg-transparent text-[#E6EDF3] text-sm placeholder-[#8B949E] outline-none"
            />
            <kbd className="text-[10px] bg-[#1C2128] px-1.5 py-0.5 rounded border border-[#30363D] text-[#8B949E] font-mono">ESC</kbd>
          </div>

          {/* Results */}
          <div className="max-h-80 overflow-y-auto py-2">
            {visibleItems.length === 0 && (
              <div className="px-4 py-6 text-center text-sm text-[#8B949E]">No results</div>
            )}
            {visibleItems.map((item, idx) => (
              <button
                key={item.id}
                onClick={() => handleSelect(item)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                  idx === selectedIndex
                    ? 'bg-[rgba(255,20,147,0.14)] text-[#FF1493]'
                    : 'text-[#E6EDF3] hover:bg-[#1C2128]'
                }`}
              >
                <NavIcon src={item.icon} active={idx === selectedIndex} size="sm" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{item.label}</div>
                  {item.sub && <div className="text-xs text-[#8B949E] truncate">{item.sub}</div>}
                </div>
                {item.role === 'director' && (
                  <span className="text-[9px] font-bold text-[#FF8C00] tracking-wide">DIR</span>
                )}
                {item.role === 'dj' && (
                  <span className="text-[9px] font-bold text-[#FF1493] tracking-wide">DJ</span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }
  ```

- [ ] **4.2 — TypeScript compile check**

---

## Phase 5: Desktop Sidebar Rewrite

**Goal:** Replace the existing `<aside>` in `Layout.tsx` with the new 248px grouped sidebar. Mobile layout is handled in Phase 6. The `SidebarPlayer` component is added in Phase 8 — for now, use a placeholder comment where it goes.

**Critical:** Keep the `showAbout` popup, the `handleLogout` function, the `SystemMonitor`, the `filteredNavItems` role logic, and the `Outlet` structure completely intact.

- [ ] **5.1 — Add ⌘K state and hotkey to Layout.tsx**
  At the top of the `Layout` function body, add:
  ```tsx
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false)
  ```
  Add a `useEffect` for the hotkey (alongside existing useEffects — do not remove any):
  ```tsx
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setCmdPaletteOpen(open => !open)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  ```

- [ ] **5.2 — Import new components into Layout.tsx**
  Add to Layout.tsx imports:
  ```tsx
  import { NAV_GROUPS } from '../config/navigation'
  import { useLocation } from 'react-router-dom'
  import NavIcon from './NavIcon'
  import CommandPalette from './CommandPalette'
  // SidebarPlayer imported in Phase 8
  ```
  Add `useLocation` to derive active nav item from current URL.

- [ ] **5.3 — Replace desktop sidebar JSX**

  The `filteredNavItems` array in the current Layout.tsx filters by role. The new sidebar uses `NAV_GROUPS` but applies the same role filtering. Replace the entire `<aside ...>` JSX block (lines 98–171 in the current Layout.tsx) with:

  ```tsx
  <aside className="hidden md:flex fixed inset-y-0 left-0 z-40 w-[248px] bg-[#161B22] border-r border-[#30363D] flex-col">

    {/* ── Brand plaque ── */}
    <div className="flex items-center gap-3 px-5 py-4 border-b border-[#30363D] flex-shrink-0">
      <button
        onClick={() => setShowAbout(true)}
        className="flex items-center gap-3 min-w-0 hover:opacity-80 transition-opacity"
      >
        <div className="w-11 h-11 rounded-[10px] bg-black flex items-center justify-center flex-shrink-0
                        shadow-[0_0_20px_rgba(255,20,147,0.45),inset_0_0_0_1px_rgba(255,20,147,0.45)]">
          <img src={S54.logo} alt="Studio54" className="w-9 h-9 object-contain" />
        </div>
        <div className="min-w-0">
          <div className="text-base font-bold text-[#E6EDF3] leading-tight">
            Studio<span className="text-[#FF1493]">54</span>
          </div>
          <div className="text-[10px] text-[#8B949E] tracking-[1.5px] uppercase">Music · Books · Mix</div>
        </div>
      </button>
    </div>

    {/* ── ⌘K search ── */}
    <div className="px-4 py-3 flex-shrink-0">
      <button
        onClick={() => setCmdPaletteOpen(true)}
        className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-[#0D1117] border border-[#30363D]
                   text-[#8B949E] text-xs hover:border-[rgba(255,20,147,0.35)] transition-colors"
      >
        <span className="text-sm">⌕</span>
        <span className="flex-1 text-left">Jump to anywhere…</span>
        <kbd className="text-[10px] bg-[#1C2128] px-1.5 py-0.5 rounded border border-[#30363D] font-mono">⌘K</kbd>
      </button>
    </div>

    {/* ── Grouped nav ── */}
    <nav className="flex-1 overflow-y-auto px-3 pb-4 sidebar-scroll">
      {NAV_GROUPS.map((group) => {
        // Apply same role filtering as before
        const visibleItems = group.items.filter(item => {
          if (!item.role) return true
          if (item.role === 'director') return isDirector
          if (item.role === 'dj') return isDjOrAbove
          return true
        })
        if (visibleItems.length === 0) return null

        return (
          <div key={group.label} className="mb-3">
            <div className="px-2 pt-3 pb-1.5 text-[10px] font-bold tracking-[2px] uppercase text-[#484F58]">
              {group.label}
            </div>
            {visibleItems.map((item) => {
              const isActive = location.pathname === item.to ||
                               location.pathname.startsWith(item.to + '/')
              return (
                <NavLink
                  key={item.id}
                  to={item.to}
                  className={() =>
                    `flex items-center gap-3 px-2 py-1.5 mb-0.5 rounded-lg transition-colors
                     ${isActive
                       ? 'bg-[rgba(255,20,147,0.14)] text-[#FF1493]'
                       : 'text-[#E6EDF3] hover:bg-[#1C2128]'
                     }`
                  }
                >
                  <NavIcon src={item.icon} active={isActive} size="md" />
                  <span className={`flex-1 text-[13px] ${isActive ? 'font-semibold' : 'font-medium'}`}>
                    {item.label}
                  </span>
                  {item.role === 'director' && (
                    <span className="text-[9px] font-bold text-[#FF8C00] tracking-wide">DIR</span>
                  )}
                  {item.role === 'dj' && (
                    <span className="text-[9px] font-bold text-[#FF1493] tracking-wide">DJ</span>
                  )}
                </NavLink>
              )
            })}
          </div>
        )
      })}
    </nav>

    {/* ── SidebarPlayer (added Phase 8) ── */}
    {/* <SidebarPlayer /> */}

    {/* ── User chip ── */}
    {user && (
      <div className="px-4 py-3 border-t border-[#30363D] flex items-center gap-3 flex-shrink-0">
        <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold text-black
                        bg-gradient-to-br from-[#FF1493] to-[#FF8C00]">
          {(user.display_name || user.username).slice(0, 2).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-semibold text-[#E6EDF3] truncate">
            {user.display_name || user.username}
          </div>
          <span className={`inline-block text-[9px] font-bold px-1.5 py-0.5 rounded tracking-wide
                           ${ROLE_COLORS[user.role]}`}>
            {ROLE_LABELS[user.role]}
          </span>
        </div>
        <button
          onClick={handleLogout}
          title="Sign out"
          className="p-1.5 text-[#8B949E] hover:text-red-400 hover:bg-[#1C2128] rounded transition-colors"
        >
          <FiLogOut className="w-4 h-4" />
        </button>
      </div>
    )}
  </aside>
  ```

- [ ] **5.4 — Update main content area left offset and padding**
  The existing main content `<div className="flex-1 flex flex-col overflow-hidden">` is inside a `flex h-screen` container. With a fixed 248px sidebar (not relative), update the content wrapper:
  ```tsx
  <div className="flex-1 flex flex-col overflow-hidden md:ml-[248px]">
  ```
  And update main `<main>` padding classes: remove the existing `md:px-6 md:py-6` variant adjustments (those accounted for the old 192px relative sidebar) since the sidebar is now fixed-position.

- [ ] **5.5 — Wire CommandPalette into Layout JSX**
  Before the closing `</div>` of the root layout div, add:
  ```tsx
  <CommandPalette open={cmdPaletteOpen} onClose={() => setCmdPaletteOpen(false)} />
  ```

- [ ] **5.6 — TypeScript compile check**

---

## Phase 6: Mobile Shell Rewrite

**Goal:** Replace the old mobile hamburger/overlay pattern with the new top header bar + 5-tab bottom bar + "More" drawer. The `SidebarPlayer` floating mini-player above the tab bar is wired in Phase 8.

- [ ] **6.1 — Remove old mobile-specific JSX from Layout.tsx**
  Remove:
  - The `{/* Mobile Top Bar */}` block (hamburger, logo, top bar)
  - The `{/* Backdrop overlay (mobile only) */}` block
  The `sidebarOpen` state can be repurposed for the new "More" drawer (or renamed to `drawerOpen`). Rename it to `drawerOpen` / `setDrawerOpen` consistently in Layout.tsx.

- [ ] **6.2 — Add mobile top header bar**
  The mobile header is `fixed top-0 left-0 right-0 z-30 h-14`. Add it BEFORE the `<aside>`:
  ```tsx
  {/* Mobile header bar */}
  <div className="md:hidden fixed top-0 left-0 right-0 h-14 z-30 bg-[#161B22] border-b border-[#30363D]
                  flex items-center px-4 gap-3">
    <div className="w-8 h-8 rounded-lg bg-black flex-shrink-0 flex items-center justify-center
                    shadow-[0_0_12px_rgba(255,20,147,0.5),inset_0_0_0_1px_rgba(255,20,147,0.45)]">
      <img src={S54.logo} alt="Studio54" className="w-[26px] h-[26px] object-contain" />
    </div>
    <div className="flex-1 min-w-0">
      {/* Active group label + page title derived from current route */}
      <div className="text-[9px] text-[#8B949E] tracking-[1.5px] uppercase">{mobileGroupLabel}</div>
      <div className="text-base font-bold text-[#E6EDF3] truncate">{mobilePageLabel}</div>
    </div>
    <button
      onClick={() => setCmdPaletteOpen(true)}
      className="w-9 h-9 rounded-full bg-[#0D1117] border border-[#30363D] text-[#8B949E]
                 flex items-center justify-center hover:border-[rgba(255,20,147,0.35)] transition-colors"
    >
      <span className="text-base">⌕</span>
    </button>
  </div>
  ```

  Derive `mobileGroupLabel` and `mobilePageLabel` by looking up the current `location.pathname` in `FLAT_NAV_ITEMS` (from navigation config), and also checking `NAV_GROUPS` for the group. Add this logic near the top of the `Layout` function body (NOT inside any JSX):
  ```tsx
  const location = useLocation()
  const activeMobileItem = FLAT_NAV_ITEMS.find(item =>
    location.pathname === item.to || location.pathname.startsWith(item.to + '/')
  )
  const activeMobileGroup = NAV_GROUPS.find(g =>
    g.items.some(item => location.pathname === item.to || location.pathname.startsWith(item.to + '/'))
  )
  const mobileGroupLabel = activeMobileGroup?.label ?? ''
  const mobilePageLabel  = activeMobileItem?.label ?? 'Studio54'
  ```

- [ ] **6.3 — Add mobile "More" drawer**
  The drawer is a full-screen overlay with the complete grouped sidebar nav, used for items not in the bottom tab bar. Place it just before the closing `</div>` of the root layout element:
  ```tsx
  {/* Mobile "More" drawer */}
  {drawerOpen && (
    <div className="md:hidden fixed inset-0 bg-[#161B22] z-50 flex flex-col">
      {/* Drawer header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-[#30363D]">
        <div className="w-11 h-11 rounded-[10px] bg-black flex-shrink-0 flex items-center justify-center
                        shadow-[0_0_16px_rgba(255,20,147,0.5),inset_0_0_0_1px_rgba(255,20,147,0.45)]">
          <img src={S54.logo} alt="Studio54" className="w-9 h-9 object-contain" />
        </div>
        <div className="flex-1">
          <div className="text-base font-bold text-[#E6EDF3]">Studio<span className="text-[#FF1493]">54</span></div>
          <div className="text-[10px] text-[#8B949E] tracking-[1.5px] uppercase">All sections</div>
        </div>
        <button
          onClick={() => setDrawerOpen(false)}
          className="w-8 h-8 rounded-full bg-[#0D1117] border border-[#30363D] text-[#8B949E]
                     flex items-center justify-center hover:text-[#E6EDF3] transition-colors"
        >
          <FiX className="w-4 h-4" />
        </button>
      </div>
      {/* Drawer nav — same grouped structure as desktop sidebar */}
      <nav className="flex-1 overflow-y-auto px-3 py-2">
        {NAV_GROUPS.map((group) => {
          const visibleItems = group.items.filter(item => {
            if (!item.role) return true
            if (item.role === 'director') return isDirector
            if (item.role === 'dj') return isDjOrAbove
            return true
          })
          if (visibleItems.length === 0) return null
          return (
            <div key={group.label} className="mb-4">
              <div className="px-2 pt-3 pb-2 text-[10px] font-bold tracking-[2px] uppercase text-[#484F58]">
                {group.label}
              </div>
              {visibleItems.map((item) => {
                const isActive = location.pathname === item.to || location.pathname.startsWith(item.to + '/')
                return (
                  <NavLink
                    key={item.id}
                    to={item.to}
                    onClick={() => setDrawerOpen(false)}
                    className={() =>
                      `flex items-center gap-4 px-2 py-2.5 mb-0.5 rounded-xl transition-colors
                       ${isActive ? 'bg-[rgba(255,20,147,0.14)] text-[#FF1493]' : 'text-[#E6EDF3] hover:bg-[#1C2128]'}`
                    }
                  >
                    <NavIcon src={item.icon} active={isActive} size="md" />
                    <span className={`flex-1 text-[15px] ${isActive ? 'font-semibold' : 'font-medium'}`}>
                      {item.label}
                    </span>
                    {item.role === 'director' && (
                      <span className="text-[9px] font-bold text-[#FF8C00] tracking-wide">DIR</span>
                    )}
                    {item.role === 'dj' && (
                      <span className="text-[9px] font-bold text-[#FF1493] tracking-wide">DJ</span>
                    )}
                  </NavLink>
                )
              })}
            </div>
          )
        })}
      </nav>
    </div>
  )}
  ```

- [ ] **6.4 — Add mobile bottom tab bar**
  Add just before the closing root `</div>`, after the drawer:
  ```tsx
  {/* Mobile bottom tab bar */}
  <div className="md:hidden fixed bottom-0 left-0 right-0 h-[72px] z-40 bg-[#161B22] border-t border-[#30363D] flex">
    {MOBILE_TABS.filter(item => {
      if (!item.role) return true
      if (item.role === 'director') return isDirector
      if (item.role === 'dj') return isDjOrAbove
      return true
    }).map((item) => {
      const isActive = location.pathname === item.to || location.pathname.startsWith(item.to + '/')
      return (
        <NavLink
          key={item.id}
          to={item.to}
          className="flex-1 flex flex-col items-center justify-center gap-1"
        >
          <NavIcon src={item.icon} active={isActive} size="sm" />
          <span className={`text-[10px] font-semibold ${isActive ? 'text-[#FF1493]' : 'text-[#8B949E]'}`}>
            {item.label === 'Disco Lounge' ? 'Listen' : item.label}
          </span>
        </NavLink>
      )
    })}
    {/* "More" button */}
    <button
      onClick={() => setDrawerOpen(true)}
      className="flex-1 flex flex-col items-center justify-center gap-1 text-[#8B949E]"
    >
      <div className="w-8 h-8 flex flex-col justify-center items-center gap-1">
        <div className="w-[18px] h-0.5 bg-[#8B949E] rounded" />
        <div className="w-[18px] h-0.5 bg-[#8B949E] rounded" />
        <div className="w-[18px] h-0.5 bg-[#8B949E] rounded" />
      </div>
      <span className="text-[10px] font-semibold">More</span>
    </button>
  </div>
  ```

- [ ] **6.5 — Update mobile content padding**
  On mobile, content must clear the top header (56px), the tab bar (72px), and the floating mini-player (52px + 8px gap above tab bar). Update `<main>`:
  ```
  pt-[calc(1rem+3.5rem)]  → stays (top bar clearance)
  pb class for mobile     → pb-[calc(52px+72px+24px)] = pb-[148px] on mobile
                             pb-48 md:pb-36 etc. for desktop (unchanged — SidebarPlayer doesn't need bottom padding)
  ```

- [ ] **6.6 — Add MOBILE_TABS import to Layout.tsx**
  ```tsx
  import { NAV_GROUPS, FLAT_NAV_ITEMS, MOBILE_TABS } from '../config/navigation'
  ```

- [ ] **6.7 — TypeScript compile check**

---

## Phase 7: PersistentPlayer Audio-Only Mode

**Goal:** Make `PersistentPlayer.tsx` render only the audio elements on the main window (not pop-out). All useEffects, logic, mutations, and queries remain completely unchanged. Only the visual return value changes.

**This is the most sensitive phase. Read the constraint rules again before starting.**

The key insight: `IS_POPOUT_WINDOW` is already defined in `PersistentPlayer.tsx` (or `PlayerContext.tsx`) and distinguishes the pop-out window from the main window.

- [ ] **7.1 — Locate `IS_POPOUT_WINDOW` constant**
  Verify that `IS_POPOUT_WINDOW` is accessible inside `PersistentPlayer.tsx`. It is defined near the top of `PlayerContext.tsx`. If it is not exported, add `export` to the `const IS_POPOUT_WINDOW` line in `PlayerContext.tsx`. This is the only change to PlayerContext.

- [ ] **7.2 — Add import in PersistentPlayer.tsx**
  ```tsx
  import { usePlayer, type RepeatMode, IS_POPOUT_WINDOW } from '../contexts/PlayerContext'
  ```

- [ ] **7.3 — Add early return at the END of PersistentPlayer**
  After all hooks, effects, mutations, and helper renders are defined (they MUST all run, hooks cannot be conditional), find the visual return section. Currently it has three branches:
  1. `if (!currentTrack) return <audio .../>`
  2. `if (isPopOutOpen) return <indicator bar>`
  3. `return <full bottom bar>`

  Replace these three branches with:
  ```tsx
  // On the main window: render only the audio elements.
  // All visual controls live in SidebarPlayer (desktop) and SidebarPlayer floating (mobile).
  // On the pop-out window: the PopOutPlayer component handles rendering; PersistentPlayer
  //   still runs here to keep the audio element alive for cross-window communication.
  if (!IS_POPOUT_WINDOW) {
    return <>{audioElement}</>
  }

  // Pop-out window: full UI is in PopOutPlayer.tsx — PersistentPlayer is not rendered there.
  // This branch should never be reached, but guard defensively:
  return <>{audioElement}</>
  ```

  **Wait** — if `IS_POPOUT_WINDOW` is true, PersistentPlayer is still mounted in the app root (because `<PersistentPlayer />` is in `Layout.tsx` which is only used for protected routes, NOT the `/player` route). So on the pop-out window, Layout is never rendered, and PersistentPlayer is never mounted. The code above simplifies to: on the main window, always return only audioElement.

  The corrected change is:
  ```tsx
  // MAIN WINDOW: visual UI moved to SidebarPlayer.
  // All audio logic above this line remains intact.
  if (!currentTrack) {
    return <>{audioElement}</>
  }
  return <>{audioElement}</>
  ```
  Which simplifies to:
  ```tsx
  return <>{audioElement}</>
  ```
  This replaces the entire three-branch visual section at the bottom of PersistentPlayer.

  **Important:** The `LyricsPanel` and `showQueue` panel JSX that was inside the bottom bar are removed from PersistentPlayer's return. These features are fully available in the PopOutPlayer window.

- [ ] **7.4 — TypeScript compile check**
- [ ] **7.5 — Smoke test: open browser, verify audio plays, no visible bottom bar on desktop**

---

## Phase 8: SidebarPlayer Mini-Player Component

**Goal:** Build the mini now-playing strip used in the desktop sidebar and the floating card above the mobile tab bar. Uses `usePlayer()` context only — no new state in PlayerContext.

- [ ] **8.1 — Create `src/components/SidebarPlayer.tsx`**

  ```tsx
  import { useState, useEffect, useRef } from 'react'
  import { FiExternalLink, FiMinimize2 } from 'react-icons/fi'
  import { usePlayer } from '../contexts/PlayerContext'
  import { S54 } from '../assets/graphics'

  interface SidebarPlayerProps {
    variant: 'sidebar' | 'float'   // sidebar = desktop strip, float = mobile card above tabs
  }

  export default function SidebarPlayer({ variant }: SidebarPlayerProps) {
    const {
      state, pause, resume, next, previous,
      isPopOutOpen, popOut, closePopOut,
      audioRef, popOutCurrentTime, popOutDuration,
    } = usePlayer()
    const { currentTrack, isPlaying } = state

    // Poll audio element for progress when playing locally
    const [localTime, setLocalTime] = useState(0)
    const [localDuration, setLocalDuration] = useState(0)
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

    useEffect(() => {
      if (isPopOutOpen) {
        if (intervalRef.current) clearInterval(intervalRef.current)
        return
      }
      intervalRef.current = setInterval(() => {
        const audio = audioRef.current
        if (audio) {
          setLocalTime(audio.currentTime ?? 0)
          setLocalDuration(audio.duration || 0)
        }
      }, 250)
      return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
    }, [isPopOutOpen, audioRef])

    const displayTime     = isPopOutOpen ? popOutCurrentTime : localTime
    const displayDuration = isPopOutOpen ? popOutDuration    : localDuration
    const progressPct     = displayDuration > 0 ? (displayTime / displayDuration) * 100 : 0

    if (!currentTrack) return null

    // ── Sidebar variant (desktop, inside the sidebar below nav) ──
    if (variant === 'sidebar') {
      return (
        <div className="px-3 py-3 border-t border-[#30363D] bg-[#0D1117] flex-shrink-0">
          {isPopOutOpen && (
            <div className="text-[10px] text-[#FF1493] font-semibold tracking-wide mb-2 px-1">
              PLAYING IN POP-OUT
            </div>
          )}
          <div className="flex items-center gap-2.5 mb-2">
            <img
              src={currentTrack.album_cover_art_url || S54.defaultAlbumArt}
              alt=""
              className="w-9 h-9 rounded flex-shrink-0 object-cover"
              onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultAlbumArt }}
            />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-semibold text-[#E6EDF3] truncate leading-tight">
                {currentTrack.title}
              </div>
              <div className="text-[10px] text-[#8B949E] truncate">
                {currentTrack.artist_name}
              </div>
            </div>
          </div>
          {/* Progress bar (non-interactive display) */}
          <div className="h-0.5 bg-[#30363D] rounded-full mb-2.5 mx-1">
            <div
              className="h-full bg-[#FF1493] rounded-full transition-all duration-300"
              style={{ width: `${Math.min(progressPct, 100)}%` }}
            />
          </div>
          {/* Controls row */}
          <div className="flex items-center justify-between px-1">
            <button onClick={previous} className="p-1 text-[#8B949E] hover:text-[#E6EDF3] transition-colors">
              <img src={S54.player.rewind} alt="Previous" className="w-4 h-4 object-contain" />
            </button>
            <button
              onClick={() => isPlaying ? pause() : resume()}
              className="w-8 h-8 rounded-full bg-[#FF1493] hover:bg-[#d10f7a] flex items-center justify-center transition-colors"
            >
              <img
                src={isPlaying ? S54.player.pause : S54.player.play}
                alt={isPlaying ? 'Pause' : 'Play'}
                className="w-4 h-4 object-contain brightness-0 invert"
              />
            </button>
            <button onClick={next} className="p-1 text-[#8B949E] hover:text-[#E6EDF3] transition-colors">
              <img src={S54.player.fastForward} alt="Next" className="w-4 h-4 object-contain" />
            </button>
            {isPopOutOpen ? (
              <button
                onClick={closePopOut}
                title="Dock to main window"
                className="p-1 text-[#8B949E] hover:text-[#E6EDF3] transition-colors"
              >
                <FiMinimize2 className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={popOut}
                title="Full player"
                className="p-1 text-[#8B949E] hover:text-[#FF1493] transition-colors"
              >
                <FiExternalLink className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      )
    }

    // ── Float variant (mobile, above tab bar) ──
    return (
      <div className="fixed left-3 right-3 bottom-[80px] h-[52px] z-40
                      bg-[#161B22] rounded-xl border border-[rgba(255,20,147,0.45)]
                      shadow-[0_4px_16px_rgba(0,0,0,0.4),0_0_16px_rgba(255,20,147,0.15)]
                      flex items-center px-3 gap-3">
        <img
          src={currentTrack.album_cover_art_url || S54.defaultAlbumArt}
          alt=""
          className="w-9 h-9 rounded flex-shrink-0 object-cover"
          onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultAlbumArt }}
        />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-[#E6EDF3] truncate leading-tight">
            {currentTrack.title}
          </div>
          <div className="h-0.5 bg-[#1C2128] rounded-full mt-1.5">
            <div
              className="h-full bg-[#FF1493] rounded-full transition-all duration-300"
              style={{ width: `${Math.min(progressPct, 100)}%` }}
            />
          </div>
        </div>
        <button
          onClick={() => isPlaying ? pause() : resume()}
          className="w-8 h-8 rounded-full bg-[#FF1493] hover:bg-[#d10f7a] flex-shrink-0
                     flex items-center justify-center transition-colors"
        >
          <img
            src={isPlaying ? S54.player.pause : S54.player.play}
            alt={isPlaying ? 'Pause' : 'Play'}
            className="w-4 h-4 object-contain brightness-0 invert"
          />
        </button>
        {isPopOutOpen ? (
          <button onClick={closePopOut} className="p-1 text-[#8B949E] hover:text-[#E6EDF3] transition-colors">
            <FiMinimize2 className="w-4 h-4" />
          </button>
        ) : (
          <button onClick={popOut} className="p-1 text-[#8B949E] hover:text-[#FF1493] transition-colors">
            <FiExternalLink className="w-4 h-4" />
          </button>
        )}
      </div>
    )
  }
  ```

- [ ] **8.2 — Wire SidebarPlayer into Layout.tsx — desktop sidebar**
  In the sidebar JSX from Phase 5, replace the placeholder comment with:
  ```tsx
  <SidebarPlayer variant="sidebar" />
  ```
  Add the import:
  ```tsx
  import SidebarPlayer from './SidebarPlayer'
  ```

- [ ] **8.3 — Wire SidebarPlayer into Layout.tsx — mobile float**
  In the mobile section (between the main content and the tab bar), add:
  ```tsx
  {/* Mobile floating mini-player */}
  <div className="md:hidden">
    <SidebarPlayer variant="float" />
  </div>
  ```

- [ ] **8.4 — Remove PersistentPlayer from Layout.tsx main content area**
  The `<PersistentPlayer />` component is currently rendered at the bottom of the Layout JSX. It MUST remain rendered (it holds the `<audio>` element), but its visual output is now empty (Phase 7). Verify it is still present in the JSX — do not remove it. Just remove any padding classes in `<aside>` and `<main>` that were added for the old bottom bar height.

- [ ] **8.5 — TypeScript compile check**
- [ ] **8.6 — Test: play a track, verify sidebar mini-player appears, play/pause/next/prev work, pop-out button opens pop-out with full controls**

---

## Phase 9: PageHeader Component

**Goal:** Build the reusable `GROUP · TITLE` header pattern from the prototype.

- [ ] **9.1 — Create `src/components/PageHeader.tsx`**

  ```tsx
  interface PageHeaderProps {
    group: string
    title: string
    subtitle?: string
    actions?: React.ReactNode
  }

  export default function PageHeader({ group, title, subtitle, actions }: PageHeaderProps) {
    return (
      <div className="mb-6">
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <div>
            <div className="text-[11px] text-[#8B949E] tracking-[1.5px] uppercase font-medium mb-1.5">
              {group} · {title}
            </div>
            <h1 className="text-3xl font-bold text-[#E6EDF3] dark:text-[#E6EDF3] tracking-tight leading-tight">
              {title}
            </h1>
            {subtitle && (
              <div className="mt-1 text-sm text-[#8B949E]">{subtitle}</div>
            )}
          </div>
          {actions && (
            <div className="flex items-center gap-2 flex-shrink-0">
              {actions}
            </div>
          )}
        </div>
      </div>
    )
  }
  ```

- [ ] **9.2 — TypeScript compile check**

---

## Phase 10: Apply PageHeader to All Pages

**Goal:** Replace the existing header JSX in each of the 13 main pages with `<PageHeader group="..." title="..." subtitle="..." actions={...} />`. Page content (data, tabs, tables, modals) is NOT touched.

For each page, the steps are:
1. Add `import PageHeader from '../components/PageHeader'`
2. Find the existing top-of-page header JSX (usually a `<div>` with `<h1>` and/or subtitle text and action buttons)
3. Replace it with the `<PageHeader>` call
4. Leave everything else in the file unchanged

Group + Title mapping for each page:

| Page | File | Group | Title |
|------|------|-------|-------|
| Disco Lounge (Library) | `Library.tsx` | Listen | Disco Lounge |
| Reading Room | `ReadingRoom.tsx` | Listen | Reading Room |
| Sound Booth | `SoundBooth.tsx` | Listen | Sound Booth |
| Listen & Add | `ListenAdd.tsx` | Listen | Listen & Add |
| Albums | `Albums.tsx` | Collection | Albums |
| Playlists | `Playlists.tsx` | Collection | Playlists |
| File Management | `FileManagement.tsx` | Collection | File Management |
| Dashboard | `Dashboard.tsx` | Activity | Dashboard |
| DJ Requests | `DjRequests.tsx` | Activity | DJ Requests |
| Calendar | `Calendar.tsx` | Activity | Calendar |
| Activity | `Activity.tsx` | Activity | Activity |
| Settings | `Settings.tsx` | System | Settings |
| How To | `HowTo.tsx` | System | How To |

- [ ] **10.1 — Update `Library.tsx`** (Disco Lounge)
- [ ] **10.2 — Update `ReadingRoom.tsx`**
- [ ] **10.3 — Update `SoundBooth.tsx`**
- [ ] **10.4 — Update `ListenAdd.tsx`**
- [ ] **10.5 — Update `Albums.tsx`**
- [ ] **10.6 — Update `Playlists.tsx`**
- [ ] **10.7 — Update `FileManagement.tsx`**
- [ ] **10.8 — Update `Dashboard.tsx`**
- [ ] **10.9 — Update `DjRequests.tsx`**
- [ ] **10.10 — Update `Calendar.tsx`**
- [ ] **10.11 — Update `Activity.tsx`**
- [ ] **10.12 — Update `Settings.tsx`**
- [ ] **10.13 — Update `HowTo.tsx`**
- [ ] **10.14 — TypeScript compile check**

---

## Phase 11: HowTo Page Neon Cards

**Goal:** Update the guide cards in `HowTo.tsx` to use `NavIcon` plaques instead of the existing icon treatment. Content and navigation behavior unchanged.

The prototype shows each HowTo card with a 56×56 neon plaque (`size="lg"`) at the top. Map each guide card to its corresponding nav icon:

| Guide | NavIcon src |
|-------|-------------|
| Add your first artist | `S54.nav.discoLounge` |
| Build a smart playlist | `S54.nav.playlists` |
| Run a live set | `S54.nav.soundBooth` |
| Take requests from the floor | `S54.nav.djRequest` |
| Fix unlinked files | `S54.nav.fileManagement` |
| Set up indexers | `S54.nav.settings` |

- [ ] **11.1 — Add NavIcon import to `HowTo.tsx`**
  ```tsx
  import NavIcon from '../components/NavIcon'
  import { S54 } from '../assets/graphics'
  ```

- [ ] **11.2 — Replace icon rendering in each guide card**
  Find the existing icon element at the top of each guide card and replace with:
  ```tsx
  <NavIcon src={/* corresponding S54.nav.* */} size="lg" active={false} />
  ```

- [ ] **11.3 — TypeScript compile check**

---

## Phase 12: PopOutPlayer Full-Controls Audit

**Goal:** Verify that every feature previously accessible in the PersistentPlayer bottom bar is accessible in `PopOutPlayer.tsx`. No code changes expected — this is a checklist audit.

- [ ] **12.1 — Verify PopOutPlayer has:**
  - [ ] Seek bar (click to seek)
  - [ ] Volume control
  - [ ] Repeat mode toggle
  - [ ] Shuffle toggle
  - [ ] Lyrics toggle (or note if absent and document)
  - [ ] Queue view (or note if absent and document)
  - [ ] Track rating
  - [ ] Prev / Play-Pause / Next controls
  - [ ] Close player button
  - [ ] Dock (return to main window) button

- [ ] **12.2 — If any feature is missing from PopOutPlayer**, document it here before marking Phase 12 complete, and create a follow-up task. Do NOT add features to PopOutPlayer during this UI update if they require backend changes or significant new code — document them instead.

---

## Phase 13: Final Integration & Cleanup

**Goal:** Remove dead code, verify all routes work, check for visual regressions.

- [ ] **13.1 — Remove unused Layout.tsx imports**
  After Phases 5–8, the old imports no longer needed in Layout.tsx (e.g., old nav item array, unused icon imports) should be removed. Only remove clearly unused imports — do not reorganize.

- [ ] **13.2 — Verify all existing App.tsx redirects still work**
  Check that these routes still correctly redirect:
  - `/` → `/disco-lounge`
  - `/statistics` → `/dashboard`
  - `/queue-status` → `/activity`
  - `/download-history` → `/activity`
  - `/download-clients` → `/settings`
  - `/library` → `/disco-lounge`
  - `/library/import` → `/file-management`
  - `/artists` → `/disco-lounge`

- [ ] **13.3 — Verify `SystemMonitor` still renders for directors**
  It is rendered with `{isDirector && <SystemMonitor />}` above the main content. It must remain.

- [ ] **13.4 — Verify About popup still works**
  The `showAbout` state and popup JSX must remain in Layout.tsx.

- [ ] **13.5 — Final TypeScript compile check**

- [ ] **13.6 — Docker rebuild**
  ```bash
  cd /home/tesimmons/Studio54 && docker compose build studio54-web
  docker compose stop studio54-web && docker compose up -d studio54-web
  ```

---

## Phase 14: Validation Test Suite

**Goal:** A concrete checklist of tests to run and verify before marking the project complete. Includes automated and manual checks.

### 14.1 — Automated: TypeScript
```bash
node /home/tesimmons/Studio54/studio54-web/node_modules/typescript/bin/tsc \
  --noEmit --project /home/tesimmons/Studio54/studio54-web/tsconfig.json
```
**Pass criteria:** zero errors.

### 14.2 — Automated: Visual regression via Playwright
Run the following Playwright script. It verifies that each protected route mounts without crashing. Save as `tests/ui-update-smoke.spec.ts` in `studio54-web`:

```typescript
import { test, expect } from '@playwright/test'

const PROTECTED_ROUTES = [
  '/disco-lounge',
  '/reading-room',
  '/sound-booth',
  '/listen',
  '/albums',
  '/playlists',
  '/dj-requests',
  '/calendar',
  '/how-to',
]

const DJ_ROUTES = [
  '/dashboard',
  '/file-management',
  '/activity',
]

const DIRECTOR_ROUTES = [
  '/settings',
]

const REDIRECT_ROUTES: [string, string][] = [
  ['/statistics', '/dashboard'],
  ['/queue-status', '/activity'],
  ['/download-history', '/activity'],
  ['/download-clients', '/settings'],
  ['/library', '/disco-lounge'],
  ['/artists', '/disco-lounge'],
]

test.describe('Studio54 UI Update — Smoke Tests', () => {

  test.beforeEach(async ({ page }) => {
    // Login as director (all routes visible)
    await page.goto('/login')
    await page.fill('[name="username"]', 'director_user')
    await page.fill('[name="password"]', 'test_password')
    await page.click('[type="submit"]')
    await expect(page).toHaveURL(/disco-lounge/)
  })

  test('Sidebar renders with 4 groups', async ({ page }) => {
    await page.goto('/disco-lounge')
    for (const group of ['Listen', 'Collection', 'Activity', 'System']) {
      await expect(page.getByText(group).first()).toBeVisible()
    }
  })

  test('Sidebar is 248px wide on desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/disco-lounge')
    const sidebar = page.locator('aside').first()
    const box = await sidebar.boundingBox()
    expect(box?.width).toBe(248)
  })

  test('Mobile: bottom tab bar visible at 375px width', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/disco-lounge')
    await expect(page.getByText('More')).toBeVisible()
    await expect(page.getByText('Listen').first()).toBeVisible()
  })

  test('Mobile: More drawer opens and shows all groups', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/disco-lounge')
    await page.getByText('More').click()
    for (const group of ['Listen', 'Collection', 'Activity', 'System']) {
      await expect(page.getByText(group).first()).toBeVisible()
    }
  })

  test('CommandPalette opens with Ctrl+K', async ({ page }) => {
    await page.goto('/disco-lounge')
    await page.keyboard.press('Control+k')
    await expect(page.getByPlaceholder('Jump to anywhere…')).toBeVisible()
  })

  test('CommandPalette closes with Escape', async ({ page }) => {
    await page.goto('/disco-lounge')
    await page.keyboard.press('Control+k')
    await page.keyboard.press('Escape')
    await expect(page.getByPlaceholder('Jump to anywhere…')).not.toBeVisible()
  })

  test('CommandPalette navigates to a page', async ({ page }) => {
    await page.goto('/disco-lounge')
    await page.keyboard.press('Control+k')
    await page.getByPlaceholder('Jump to anywhere…').fill('Calendar')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/calendar/)
  })

  for (const route of PROTECTED_ROUTES) {
    test(`Route ${route} loads without error`, async ({ page }) => {
      await page.goto(route)
      await expect(page.locator('h1').first()).toBeVisible()
      const errors: string[] = []
      page.on('pageerror', e => errors.push(e.message))
      expect(errors).toHaveLength(0)
    })
  }

  for (const route of DJ_ROUTES) {
    test(`DJ route ${route} loads for director`, async ({ page }) => {
      await page.goto(route)
      await expect(page.locator('h1').first()).toBeVisible()
    })
  }

  for (const route of DIRECTOR_ROUTES) {
    test(`Director route ${route} loads for director`, async ({ page }) => {
      await page.goto(route)
      await expect(page.locator('h1').first()).toBeVisible()
    })
  }

  for (const [from, to] of REDIRECT_ROUTES) {
    test(`Redirect ${from} → ${to}`, async ({ page }) => {
      await page.goto(from)
      await expect(page).toHaveURL(new RegExp(to.replace('/', '\\/')))
    })
  }

  test('PageHeader GROUP · TITLE eyebrow visible on Disco Lounge', async ({ page }) => {
    await page.goto('/disco-lounge')
    await expect(page.getByText(/Listen.*Disco Lounge/i).first()).toBeVisible()
  })

  test('PageHeader visible on Settings page', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByText(/System.*Settings/i).first()).toBeVisible()
  })

  test('Player: play a track, SidebarPlayer appears in sidebar', async ({ page }) => {
    await page.goto('/disco-lounge')
    // Find and click a play button (implementation-specific; adjust selector if needed)
    const playBtn = page.locator('[title*="play" i], [aria-label*="play" i]').first()
    if (await playBtn.count() > 0) {
      await playBtn.click()
      // SidebarPlayer should appear in sidebar (it has a progress bar div)
      const sidebar = page.locator('aside').first()
      await expect(sidebar.locator('[style*="FF1493"]').first()).toBeVisible({ timeout: 3000 })
    }
  })

  test('No old bottom player bar on desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 })
    await page.goto('/disco-lounge')
    // The old bottom bar had class "fixed bottom-0 left-0 right-0" — it should not exist
    const oldBar = page.locator('.fixed.bottom-0.left-0.right-0').filter({ hasText: 'Playing' })
    await expect(oldBar).not.toBeVisible()
  })

  test('Role badge DJ visible for file-management', async ({ page }) => {
    await page.goto('/disco-lounge')
    // Director sees file-management nav item with DJ badge
    await expect(page.getByText('DJ').first()).toBeVisible()
  })

  test('About popup opens on logo click', async ({ page }) => {
    await page.goto('/disco-lounge')
    await page.locator('aside button').first().click()
    await expect(page.getByText(/version/i).first()).toBeVisible({ timeout: 2000 })
  })

})
```

### 14.3 — Manual checklist
Run through this after Playwright passes:

- [ ] Open in Chrome at 1280px: sidebar is dark, 248px, neon plaques visible for all nav items
- [ ] Active nav item: correct item has pink glow + pink text
- [ ] Hover on inactive item: `#1C2128` background appears
- [ ] Desktop: no bottom player bar visible when nothing is playing
- [ ] Play a track from Disco Lounge: SidebarPlayer appears in sidebar bottom
- [ ] SidebarPlayer shows cover art, track title, artist, progress bar
- [ ] SidebarPlayer play/pause/prev/next work correctly
- [ ] SidebarPlayer pop-out button opens the pop-out window with full controls
- [ ] Pop-out window: seek bar, volume, repeat, shuffle all functional
- [ ] Pop-out window: close (X) button stops all players and dismisses
- [ ] Dock button in SidebarPlayer when pop-out is open: docks back to main window
- [ ] ⌘K opens command palette; typing filters items; Enter navigates
- [ ] ⌘K shows DJ/DIR badges; non-accessible routes are hidden
- [ ] Mobile 375px: bottom tab bar with 4 icons + More button
- [ ] Mobile: floating mini-player appears above tab bar when track is playing
- [ ] Mobile: "More" button opens full-screen drawer
- [ ] Mobile drawer: all groups and role-filtered nav items visible, tap navigates
- [ ] Page headers: GROUP · TITLE eyebrow above all 13 pages
- [ ] Director role: sees DIR badge on Settings nav item
- [ ] DJ role login: does not see Settings; sees DJ badge on relevant items
- [ ] Partygoer role: sees only unrestricted nav items; no role badges shown
- [ ] SystemMonitor bar visible for directors, hidden for others
- [ ] About popup still opens from logo in sidebar
- [ ] All legacy redirects work (check the list in Phase 13.2)
- [ ] HowTo page: guide cards show neon plaque icons

---

## Questions That Arose During Planning (For the Record)

1. **Lyrics in main window**: With PersistentPlayer moved to audio-only on the main window, the Lyrics panel and Queue panel are only accessible via the pop-out player. The user explicitly confirmed: *"full functionality exists in the popout player."* This is the intended design.

2. **Progress bar in SidebarPlayer**: There is no `currentTime` in PlayerContext. SidebarPlayer polls `audioRef.current` at 250ms intervals. This is self-contained within SidebarPlayer and requires no PlayerContext changes.

3. **⌘K scope**: Nav-only search. No backend changes. Confirmed by user.

4. **Statistics page**: `/statistics` already redirects to `/dashboard` in App.tsx. No change needed. Statistics.tsx file remains.

5. **Sound booth icon name**: The handoff has `sound-booth.png`. The existing codebase has `sound-booth-new.png`. Phase 1 archives `sound-booth-new.png` and uses the handoff version as `sound-booth.png`.

---

*This document must be updated at the completion of each phase before implementation of the next phase begins.*
