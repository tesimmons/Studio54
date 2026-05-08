# Studio54 Navigation — Integration Guide

This package contains the **Option A: Grouped Sidebar with Neon Plaques** redesign for Studio54, with desktop and mobile shells across all 13 routes.

It's a **design prototype in HTML/JSX**, not production React components. The goal of this doc is to give Claude Code (or any engineer) enough context to translate it into your actual codebase.

---

## What's in the box

| File | Purpose |
|---|---|
| `Studio54 Prototype.html` | Entry point. Wires the shell + router + all 13 pages. Open this to see the design. |
| `shared.jsx` | Design tokens (`T`), navigation structure (`NAV_GROUPS`), mock "now playing" data. **Source of truth for colors, nav order, and grouping.** |
| `app-shell.jsx` | `<Sidebar>` (desktop) and `<MobileShell>` (mobile bottom-tabs + drawer). The actual chrome to port. |
| `pages-1.jsx` | Listen + Collection pages: Disco Lounge, Reading Room, Sound Booth, Listen & Add, Albums, Playlists, File Mgmt |
| `pages-2.jsx` | Activity + System pages: Dashboard, DJ Requests, Calendar, Activity, Settings, How To |
| `images/` | All neon plaque icons (`disco-lounge.png`, `playlists.png`, etc.) + logo + bg art |
| `Studio54 Navigation Redesign.html` | Original design canvas — shows the audit, three direction options, and mobile spec. Reference only. |

---

## Design decisions baked into the prototype

### Navigation model
- **4 groups, never collapsed:** `Listen`, `Collection`, `Activity`, `System` (defined in `shared.jsx → NAV_GROUPS`)
- Each item carries: `id`, `to` (route path), `icon`, `label`, optional `badge` (number), optional `role` (`"dj"` or `"director"`)
- Role markers (`DJ` / `DIR`) appear as small letterforms on the right side of nav items — they hint at audience without hiding anything

### Visual language — "neon plaque" icons
- Each nav item has a **44×44 black plaque** with the icon centered and a soft pink glow (`box-shadow: 0 0 14px rgba(255,20,147,0.55)`)
- Active state intensifies the glow + adds a pink border ring
- Inactive icons get `filter: saturate(0.85) brightness(0.92)` so they read as dimmer
- This is the single most distinctive visual element — preserve it

### Colors (`shared.jsx → T`)
```
pink:        #FF1493   (primary accent, glow)
pinkSoft:    rgba(255,20,147,0.14)  (active row bg)
pinkBorder:  rgba(255,20,147,0.45)
orange:      #FF8C00   (director role marker, secondary accent)
bg:          #0D1117   (app background)
bg2:         #161B22   (cards, sidebar)
bg3:         #1C2128   (hover, kbd)
border:      #30363D
text:        #E6EDF3
muted:       #8B949E
mutedDim:    #484F58
```

### Layout
- **Desktop sidebar**: 248px fixed width, contains: brand plaque → ⌘K search → grouped nav → mini "now playing" → user chip
- **Mobile**: 5-tab bottom bar (`Listen / Library / Playlists / Requests / More`) + 56px floating mini-player above the tabs. "More" opens a full-screen drawer with the complete grouped sidebar
- **Mobile breakpoint**: `<820px` (in `useViewport` hook)

### Global affordances
- ⌘K opens a fuzzy jump-to-anywhere palette (component: `CmdK` in `Studio54 Prototype.html`)
- Mini-player visible at all times (sidebar bottom on desktop, floating above tabs on mobile)
- Page header pattern: `GROUP · Title` eyebrow → big title → optional subtitle → right-aligned actions

---

## How to integrate into your codebase

### Step 1 — Lift the design tokens
Copy the `T` color object from `shared.jsx` into your existing token file (likely `theme.ts` or `tokens.css`). If you already have CSS variables, map them:
```css
--color-accent: #FF1493;
--color-accent-soft: rgba(255,20,147,0.14);
--color-accent-border: rgba(255,20,147,0.45);
--color-accent-2: #FF8C00;
/* ...etc */
```

### Step 2 — Rewrite `Layout.tsx` (or wherever the sidebar lives)
The current sidebar in your codebase needs to become two surfaces:
1. **`<Sidebar>`** for `md:` and up — port from `app-shell.jsx`
2. **`<MobileShell>`** replacing the existing `md:hidden` branch

The structure of each group/item should be driven by the `NAV_GROUPS` constant — copy `shared.jsx → NAV_GROUPS` into your routing/nav config and read from it. Keep the `role` and `badge` fields; they're used in both shells.

### Step 3 — Port the icon plaques
Drop the 13 PNGs from `images/` into your `public/icons/` (or equivalent). Build a small `<NavIcon>` component that wraps an `<img>` in the black plaque + glow. Reuse it in:
- Desktop sidebar rows
- Mobile bottom-tab buttons (smaller — 32×32 plaque, 26×26 image)
- Mobile drawer rows
- ⌘K search results
- "How To" page cards

### Step 4 — Port pages incrementally
Each page in `pages-1.jsx` / `pages-2.jsx` is a self-contained component. Don't port them as JSX literals — they're prototype-grade with mock data. Instead, **read each page as a spec**:
- What's the page header (group label, title, subtitle, action buttons)?
- What tabs does it have, and what's the active state?
- What's the primary content layout (grid, cards, list)?
- Where does mock data appear vs. real data?

Wire each one to your existing data layer (Sonarr/Lidarr-style API, MusicBrainz, etc.).

### Step 5 — Add the global affordances
- **⌘K palette**: see the `CmdK` component in `Studio54 Prototype.html`. It's ~40 lines and self-contained — port it as `<CommandPalette>` and mount it once at the app root. The hotkey listener and ESC-to-close are wired in `App`.
- **Mini-player**: extract from the bottom of `<Sidebar>` and the floating bar in `<MobileShell>`. Should be a single `<NowPlayingBar>` component that adapts to viewport.

### Step 6 — Validate against the prototype
Open `Studio54 Prototype.html` side-by-side with your implementation. The prototype is the visual spec — match the spacing, glow intensity, and active-state treatment exactly. Anything fancier than the prototype is scope creep.

---

## What NOT to port verbatim

- **Mock data** in pages (album titles, request names, calendar events) — replace with real data
- **Inline styles** — convert to your existing styling solution (Tailwind, CSS modules, styled-components)
- **The hash router** in `Studio54 Prototype.html` — you already have a real router (Next/React Router/etc.); use it
- **The `useViewport` hook** — if you have a media-query hook already, prefer it

---

## Open questions to resolve before shipping

1. **Role badges (`DJ` / `DIR`)** — should non-permitted users see disabled items, or have them hidden entirely? Prototype shows them all the time.
2. **Mobile "Library" tab** — currently routes to Albums. Could route to a unified Library page that contains Albums + Playlists + Books tabs. Worth a UX call.
3. **⌘K scope** — currently only searches nav items. Should also search across albums/tracks/artists once wired to the data layer.
4. **Now-playing on mobile** — the floating bar above the tab bar covers ~52px of content. Consider whether tapping it should expand to a full-screen player (standard pattern, not built here).
5. **Reading Room icon** — currently uses the same plaque treatment as music sections. May warrant a slightly different visual cue since it's a different content type.

---

## Quick reference — file dependency graph

```
Studio54 Prototype.html
├── shared.jsx          (T, NAV_GROUPS, FLAT_ITEMS, NOW_PLAYING)
├── app-shell.jsx       (Sidebar, MobileShell, useRoute, useViewport, Btn, Card, PageHeader)
├── pages-1.jsx         (PageDisco, PageReading, PageBooth, PageListen, PageAlbums, PagePlaylists, PageFiles)
└── pages-2.jsx         (PageDashboard, PageRequests, PageCalendar, PageActivity, PageSettings, PageHowTo)
```

All component scripts attach to `window.*` for cross-script access (Babel standalone limitation — not needed in a real bundled app).
