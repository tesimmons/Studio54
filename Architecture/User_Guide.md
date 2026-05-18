# Studio54 — User Guide

> **Audience:** End-users (web UI) and API consumers  
> **Base URL:** `https://studio54.homeip.net` (your host may differ)  
> **API Base:** `https://studio54.homeip.net/api/v1`  
> **Interactive API docs:** `http://<host>:8010/docs`  
> **Last updated:** 2026-05-14

---

## Table of Contents

1. [Roles & Permissions](#1-roles--permissions)
2. [Authentication](#2-authentication)
3. [Dashboard](#3-dashboard)
4. [Disco Lounge — Music Library](#4-disco-lounge--music-library)
   - 4.1 [Artists](#41-artists)
   - 4.2 [Albums](#42-albums)
   - 4.3 [Tracks](#43-tracks)
5. [The Player](#5-the-player)
6. [Sound Booth](#6-sound-booth)
7. [Playlists](#7-playlists)
8. [Reading Room — Audiobooks](#8-reading-room--audiobooks)
9. [DJ Requests](#9-dj-requests)
10. [Listen & Add](#10-listen--add)
11. [Activity & Jobs](#11-activity--jobs)
12. [File Management](#12-file-management)
13. [Settings (Director Only)](#13-settings-director-only)
14. [Statistics](#14-statistics)
15. [API Reference](#15-api-reference)

---

## 1. Roles & Permissions

Studio54 uses four roles. Each role includes all permissions of roles below it.

| Role | Badge Color | Capabilities |
|---|---|---|
| **Director** | Amber | Full access — system settings, user management, all content operations |
| **DJ** | Purple | Manage music & audiobooks, download, approve DJ requests, file management |
| **Bouncer** | Blue | Browse library, play music, submit DJ requests |
| **Partygoer** | Green | Browse library, play music, submit DJ requests |

**Role gates on navigation:**

| Section | Minimum Role |
|---|---|
| Dashboard | Bouncer |
| Disco Lounge (browse/play) | Partygoer |
| Reading Room (browse/play) | Partygoer |
| Sound Booth | Partygoer |
| DJ Requests | Partygoer |
| Activity & Jobs | DJ |
| File Management | DJ |
| Settings | Director |

---

## 2. Authentication

### Web UI Login

Navigate to the login page at `/login`. Enter your username and password. On success you are redirected to the Dashboard.

- **First login:** If your account has `must_change_password` set, you are prompted to choose a new password before continuing.
- **Session length:** Tokens are valid for 7 days. The app silently refreshes your session on the next page load after expiry.

### API Authentication

All API requests (except `/auth/login`) require a Bearer token in the `Authorization` header.

**1. Obtain a token:**

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "your_username",
  "password": "your_password"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "username": "alice",
    "display_name": "Alice",
    "role": "dj",
    "must_change_password": false
  }
}
```

**2. Use the token:**
```http
GET /api/v1/artists
Authorization: Bearer eyJ...
```

**3. Refresh before expiry:**
```http
POST /api/v1/auth/refresh
Authorization: Bearer eyJ...
```

Returns a new token. Accepts tokens that expired within the last 7 days for silent recovery.

### API Pagination

All list endpoints support:

| Parameter | Default | Max | Description |
|---|---|---|---|
| `limit` | `100` | `1000` | Items per page |
| `offset` | `0` | `100000` | Offset from first result |

List responses include a `total_count` (or equivalent) field for computing page counts.

---

## 3. Dashboard

The Dashboard (`/dashboard`) is a customizable widget grid. Each widget can be resized, repositioned, hidden, or re-added.

### Editing the Layout

1. Click the **Edit Layout** button (pencil icon in the toolbar).
2. Drag widgets to new positions. Resize using the corner handle.
3. Click the **×** on any widget to hide it.
4. Use **Add Widget** to restore hidden widgets or add duplicates of configurable widgets.
5. Click **Save** to persist your layout. **Cancel** to revert all changes.

Your layout is stored per-user in the database and restored on every session.

### Available Widgets

| Widget | Description |
|---|---|
| **Now Playing** | Currently playing track across all connected users (live, polls the now-playing heartbeat) |
| **Library Stats** | Total artists, albums, tracks, and library size at a glance |
| **Recent Downloads** | Latest completed download jobs |
| **Wanted Albums** | Albums that are monitored but not yet in the library |
| **Download Queue** | Active SABnzbd queue items |
| **Activity Feed** | Recent job events |
| **Calendar** | Upcoming album release dates |
| **Quick Play** | Your playlists for one-click playback |

---

## 4. Disco Lounge — Music Library

The Disco Lounge (`/disco-lounge`) is the primary music management section. It contains sub-sections for Artists, Albums, and Tracks, accessed via the left navigation.

### 4.1 Artists

**URL:** `/disco-lounge/artists`

#### Browsing & Searching

Use the search bar to filter by artist name. Sort by:
- **Name** (alphabetical)
- **Files** (descending / ascending)
- **Date added**

Filter by monitored status (All / Monitored / Unmonitored) and by genre tag.

Click any artist card to open the Artist Detail page (`/disco-lounge/artists/:id`), which shows all albums for that artist grouped by release type (Album, EP, Single, Compilation) along with monitoring status and file counts.

#### Adding an Artist (DJ+)

1. Click **Add Artist** (+ button).
2. Search MusicBrainz by name. Results include disambiguation, country, and release count.
3. Select the correct artist.
4. Configure:
   - **Monitor:** Enable to track new releases.
   - **Monitor Type:** Which releases to watch (`all_albums`, `future_only`, `existing_only`, `first_album`, `latest_album`, `none`).
   - **Quality Profile:** Which audio quality to target.
   - **Root Folder:** Where on disk to organize files.
   - **Search for Missing:** Immediately trigger a search for existing wanted albums.
5. Click **Add**.

**API equivalent:**
```http
POST /api/v1/artists
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "musicbrainz_id": "5b11f4ce-a62d-471e-81fc-a69a8278c7da",
  "is_monitored": true,
  "monitor_type": "all_albums",
  "quality_profile_id": null,
  "root_folder_path": "/music",
  "search_for_missing": true
}
```

#### Artist Actions (right-click or overflow menu)

| Action | Minimum Role | Description |
|---|---|---|
| **Sync Albums** | DJ | Re-queries MusicBrainz for new releases |
| **Refresh Metadata** | DJ | Re-fetches all metadata (genres, bio, images) |
| **Scan Folder** | DJ | Scans the artist's folder for new/changed files |
| **Edit Monitoring** | DJ | Toggle monitored on/off, change monitor type |
| **Upload Cover Art** | DJ | Replace cover art with a local file |
| **Set Cover Art from URL** | DJ | Replace cover art with an image URL |
| **Delete** | DJ | Remove artist and optionally delete files |
| **Rate** | Any | Set a 1–5 star rating for the artist |

#### Bulk Actions (DJ+)

In bulk mode (checkbox select), you can:
- Toggle monitored/unmonitored for a selection
- Assign a quality profile to a selection

#### MusicBrainz Search (API)

```http
GET /api/v1/musicbrainz/search/artists?query=radiohead&limit=25
Authorization: Bearer eyJ...
```

### 4.2 Albums

**URL:** `/disco-lounge/albums`

#### Album Status Lifecycle

```
WANTED → SEARCHING → DOWNLOADING → DOWNLOADED
                  ↘ FAILED
```

| Status | Meaning |
|---|---|
| `wanted` | Monitored but no file found |
| `searching` | Search task is active |
| `downloading` | NZB submitted to SABnzbd |
| `downloaded` | Files present in library |
| `failed` | All searches failed; waiting for retry |
| `unmonitored` | Not tracked for downloads |

#### Browsing & Filtering

Filter albums by:
- **Search:** Fuzzy match on title or artist name
- **Status:** Any of the statuses above
- **Artist:** Filter to one artist's discography
- **Monitored Only:** Hide unmonitored
- **In Library:** Only show downloaded or only show wanted

Sort by: `title`, `release_date`, `files_desc`, `files_asc`, `added_at`.

#### Album Detail (`/disco-lounge/albums/:id`)

The album detail page shows:
- Full track listing with playback buttons, file status, and duration
- Download queue status for active downloads
- Cover art (click to upload replacement)
- Edit fields: monitor toggle, custom folder path

#### Triggering a Download (DJ+)

1. Navigate to the Album Detail page.
2. Click **Search** — triggers an immediate Newznab indexer search.
3. If results are found, the best release is automatically submitted to SABnzbd.
4. Track the download in the [Activity](#11-activity--jobs) section.

**API:**
```http
POST /api/v1/albums/{album_id}/search
Authorization: Bearer eyJ...
```

Manually grab a specific release:
```http
POST /api/v1/queue/albums/{album_id}/grab
Authorization: Bearer eyJ...
Content-Type: application/json

{ "release_guid": "..." }
```

#### Wanted Albums

```http
GET /api/v1/albums/wanted?limit=50&offset=0
Authorization: Bearer eyJ...
```

Returns all monitored albums not yet in the library, sorted by release date descending.

#### Album Calendar

Upcoming release dates for monitored artists:
```http
GET /api/v1/albums/calendar
Authorization: Bearer eyJ...
```

#### Bulk Album Updates (DJ+)

```http
PATCH /api/v1/albums/bulk-update
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "album_ids": ["uuid1", "uuid2"],
  "monitored": true
}
```

### 4.3 Tracks

#### Streaming a Track

```http
GET /api/v1/tracks/{track_id}/stream
Authorization: Bearer eyJ...
```

Returns the audio file as a streaming response. Supports `Range` headers for seeking.

#### Downloading a Track File

```http
GET /api/v1/tracks/{track_id}/download
Authorization: Bearer eyJ...
```

Returns the audio file as an attachment.

#### Track Ratings

Get a track's rating:
```http
GET /api/v1/tracks/{track_id}/rating
Authorization: Bearer eyJ...
```

Set your rating (1–5 stars):
```http
PATCH /api/v1/tracks/{track_id}/rating
Authorization: Bearer eyJ...
Content-Type: application/json

{ "rating": 4 }
```

#### Track Lyrics

```http
GET /api/v1/tracks/{track_id}/lyrics
Authorization: Bearer eyJ...
```

Pre-fetch lyrics (background job):
```http
POST /api/v1/albums/{album_id}/prefetch-lyrics
Authorization: Bearer eyJ...
```

#### Top Tracks

```http
GET /api/v1/tracks/top?limit=20&artist_id=<uuid>
Authorization: Bearer eyJ...
```

#### Record a Play

Increment the play count for a track:
```http
POST /api/v1/tracks/{track_id}/record-play
Authorization: Bearer eyJ...
```

---

## 5. The Player

The persistent player bar appears at the bottom of every page once playback starts. It persists across page navigation.

### Controls

| Control | Description |
|---|---|
| ▶ / ⏸ | Play / Pause |
| ⏮ / ⏭ | Previous / Next track in queue |
| Seek bar | Click or drag to seek within the track |
| Volume | Slider + mute toggle |
| Queue | Opens the queue panel — shows history, now playing, and upcoming tracks |
| Pop-out | Opens a floating player window (desktop only) |
| Sleep Timer | Sets a countdown to fade and stop playback |

### Mobile Fullscreen Overlay

On mobile, tap the album art thumbnail (or the **^** chevron) to expand the player to a fullscreen overlay showing:
- Large album art
- Track title and artist
- Full transport controls (seek, skip, volume)
- Sleep Timer
- Queue list
- Mark as Read (audiobooks)

Collapse with the **∨** chevron or the **×** close button.

### Playing from the UI

- **Play Album:** Click the play icon on any album card, or use the **Play All** button on the Album Detail page.
- **Play Playlist:** Click the play icon on any playlist row in the Sound Booth or Playlists page.
- **Play Track:** Click the play icon next to any individual track.
- **Play Book:** Click the play icon on any book card in the Reading Room.

### Queue Management

Open the queue panel with the queue icon in the player. The queue is divided into three sections:

1. **History** — Tracks already played this session
2. **Now Playing** — Currently active track (highlighted)
3. **Upcoming** — Queued tracks, drag to reorder

Tracks are added to the end of the queue by default. On the Track Listing, use **Add to Queue** to enqueue without interrupting current playback.

---

## 6. Sound Booth

**URL:** `/sound-booth`

The Sound Booth is the DJ hub — it combines social listening awareness with quick access to playlists and albums.

### Now Listening

A live-updating strip of cards shows every user currently playing something. Each card displays:
- User avatar (initials if no photo) and role badge
- Track name and album
- Artist name
- A real-time pulsing indicator

Clicking a user's card navigates to that album's detail page. Clicking the artist name navigates to the artist page.

### Quick Play — Music Playlists

Your music playlists are listed here. Click any playlist to start immediate playback. Click the **+** button to add the currently displayed albums to a playlist.

### Quick Play — Book Playlists

Your audiobook playlists appear in a separate section below music playlists.

### Recently Added Albums

The bottom section shows recently added albums. Hover to reveal a **Play** button or an **Add to Playlist** dropdown.

---

## 7. Playlists

**URL:** `/disco-lounge/playlists` (music) and Reading Room playlists within `/reading-room`

### Creating a Playlist (any authenticated user)

```http
POST /api/v1/playlists
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "name": "Late Night Vibes",
  "description": "Optional description",
  "is_public": false
}
```

### Adding Tracks

Single track:
```http
POST /api/v1/playlists/{playlist_id}/tracks
Authorization: Bearer eyJ...
Content-Type: application/json

{ "track_id": "uuid", "position": 1 }
```

Bulk add (entire album):
```http
POST /api/v1/playlists/{playlist_id}/tracks/bulk
Authorization: Bearer eyJ...
Content-Type: application/json

{ "track_ids": ["uuid1", "uuid2", "uuid3"] }
```

### Reordering

```http
PUT /api/v1/playlists/{playlist_id}/reorder
Authorization: Bearer eyJ...
Content-Type: application/json

{ "track_ids": ["uuid3", "uuid1", "uuid2"] }
```

### Publishing / Sharing (DJ+)

Published playlists are visible to all users.

```http
POST /api/v1/playlists/{playlist_id}/publish
Authorization: Bearer eyJ...
```

Retrieve all published playlists:
```http
GET /api/v1/playlists/published
Authorization: Bearer eyJ...
```

### Book Playlists (Audiobook Chapters)

Book playlists work identically to music playlists but hold chapters instead of tracks:

```http
POST /api/v1/playlists/{playlist_id}/chapters/bulk
Authorization: Bearer eyJ...
Content-Type: application/json

{ "chapter_ids": ["uuid1", "uuid2"] }
```

---

## 8. Reading Room — Audiobooks

**URL:** `/reading-room`

The Reading Room manages your audiobook collection with Author → Series → Book → Chapter hierarchy.

### Browsing

Switch the sort view with the toggle at the top:

| View | Sort Options | Description |
|---|---|---|
| **Authors** | name, files desc/asc, added_at | One row per author |
| **Books** | release_date, title, author, files desc/asc | Flat list of all books |
| **Series** | name, book_count, added_at | Series grouping |

Filter by monitored status and by genre. The search bar performs fuzzy matching across the active view.

### Author Detail (`/reading-room/authors/:id`)

Shows all books grouped by series. Each book card displays file count, chapter count, and a play button.

### Book Detail (`/reading-room/books/:id`)

Shows the chapter listing with duration, file status, and play controls. The right panel shows:
- Progress bar (% listened)
- Last chapter and timestamp (synced from the player)
- Edit metadata fields (DJ+)

### Adding an Author (DJ+)

1. Click **Add Author** in the Reading Room header.
2. Search by name — results pull from the Hardcover API and MusicBrainz.
3. Select the correct author.
4. Set monitoring and root folder.
5. Click **Add** — Studio54 will sync their catalog from Hardcover/OpenLibrary.

**API:**
```http
POST /api/v1/authors
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "name": "Brandon Sanderson",
  "hardcover_id": "brandon-sanderson",
  "is_monitored": true
}
```

### Audiobook Playback & Progress

Progress is tracked automatically while you listen. The player sends a heartbeat every 30 seconds to save your position.

**Get progress:**
```http
GET /api/v1/books/{book_id}/progress
Authorization: Bearer eyJ...
```

**Manually set progress:**
```http
POST /api/v1/books/{book_id}/progress
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "chapter_id": "uuid",
  "position_ms": 123456,
  "completed": false
}
```

**Mark as Read:** Click the checkmark button in the player or book detail page. This marks the book complete and archives the listening session.

### Tabs in Reading Room (DJ+)

| Tab | Description |
|---|---|
| **Browse** | Default view — authors, books, or series |
| **Scanner** | Run the V2 library scanner on the audiobook directory |
| **Import** | Import files found by the scanner into the database |
| **Unlinked Files** | Audio files on disk not linked to any book |
| **Unorganized Files** | Files whose folder structure doesn't match naming conventions |

### Bulk Author Actions (DJ+)

Select multiple authors with the checkbox mode, then:
- **Refresh Metadata** — Re-fetches metadata for all selected authors
- **Toggle Monitored** — Enable/disable monitoring
- **Delete** — Remove selected authors (with option to delete files)

### Merge Authors (DJ+)

Combines duplicate author entries into a single canonical record:

1. Select two or more authors in bulk mode.
2. Click **Merge** in the actions menu.
3. Choose which author record to keep as the canonical entry.
4. All books from the others are reassigned to the canonical author.

---

## 9. DJ Requests

**URL:** `/dj-requests`

DJ Requests let any user ask the system to acquire specific music.

### Submitting a Request

1. Click **New Request** (+ button).
2. **Step 1 — Choose type:**
   - `artist` — Request that an artist be added and monitored
   - `album` — Request a specific album
   - `track` — Request a specific track
   - `problem` — Report a playback issue or library problem
3. **Search MusicBrainz** — Type an artist name to find the correct entry. A live search against MusicBrainz returns up to 25 results with disambiguation.
4. **Step 2 — Preview and Details:**
   - Select a specific track or album name (for album/track requests).
   - Click **Preview** to stream a 30-second iTunes preview before confirming.
   - Add an optional note.
5. Click **Submit**.

**API:**
```http
POST /api/v1/dj-requests
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "request_type": "artist",
  "artist_name": "Radiohead",
  "musicbrainz_id": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
  "notes": "Please add their full discography"
}
```

### Request Statuses

| Status | Badge Color | Meaning |
|---|---|---|
| `pending` | Yellow | Waiting for review |
| `approved` | Blue | Approved — acquisition in progress |
| `rejected` | Red | Declined by a DJ/Director |
| `fulfilled` | Green | Request completed |

### Managing Requests (DJ+)

DJs and Directors see all pending requests. For each request you can:

- **Approve** — Confirms the request; typically triggers adding the artist or searching for the album.
- **Reject** — Declines with an optional reason.
- **Fulfill** — Marks the request as completed after the content has been acquired.

```http
PATCH /api/v1/dj-requests/{request_id}
Authorization: Bearer eyJ...
Content-Type: application/json

{ "status": "approved" }
```

Requests submitted by the current user are accessible at:
```http
GET /api/v1/dj-requests/by-user
Authorization: Bearer eyJ...
```

---

## 10. Listen & Add

**URL:** `/listen-add`

Listen & Add identifies music playing near you using your device microphone and offers to add it to the library.

### How It Works

1. Click the **microphone** button. Grant microphone permission when prompted.
2. Hold the device near the audio source. Studio54 records for up to **20 seconds** and shows a live audio level meter.
3. The recording is sent to the server, which runs the following pipeline:
   - **AcoustID fingerprinting** (`fpcalc` via `libchromaprint`) — matches against the open-source fingerprint database
   - **AudD fallback** — if AcoustID returns no match, tries the AudD commercial recognition API (requires `AUDD_API_TOKEN`)
   - **MusicBrainz enrichment** — fetches full metadata for the identified recording
4. Results appear with: track name, artist, album, release date, cover art, and whether the artist is already in your library.

### Identification Result Actions

| Action | Minimum Role | Description |
|---|---|---|
| **View Artist** | Any | Navigate to the artist's library page |
| **View Album** | Any | Navigate to the album detail page |
| **Add Artist** | DJ | Add the artist to the library and start monitoring |
| **Search for Album** | DJ | Trigger an immediate download search for the identified album |

> **Note:** This feature requires HTTPS (or `localhost`). The browser blocks microphone access on unencrypted HTTP connections. If you see a "microphone not available" error, ensure you are accessing Studio54 over HTTPS.

---

## 11. Activity & Jobs

**URL:** `/activity` (requires DJ+)

The Activity page provides full visibility into background processing.

### Jobs Tab

Lists all background jobs (Celery tasks) with live auto-refresh every 5 seconds.

**Filter by:**
- **Status:** `pending`, `running`, `completed`, `failed`, `stalled`, `paused`, `cancelled`
- **Type:** `library_import`, `metadata_refresh`, `file_organization`, `scan`, `sync`, and more

**Per-job actions:**

| Action | Description |
|---|---|
| **Cancel** | Stop a running job |
| **Pause / Resume** | Pause a long-running import and resume later |
| **Retry** | Re-queue a failed job |
| **View Log** | Open the structured job log (lines emitted by the task) |

**Bulk controls:** Pause All / Resume All for mass job management.

**API:**
```http
GET /api/v1/jobs?status=running&job_type=library_import&limit=25&offset=0
Authorization: Bearer eyJ...

POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/pause
POST /api/v1/jobs/{job_id}/resume
POST /api/v1/jobs/{job_id}/retry
GET  /api/v1/jobs/{job_id}/log
GET  /api/v1/jobs/{job_id}/log/content
```

### Downloads Tab

Lists completed and active downloads from SABnzbd with filtering by status and date range.

```http
GET /api/v1/queue?limit=50&offset=0
Authorization: Bearer eyJ...
```

**Per-download actions:**
- **Pause / Resume** — Pause the SABnzbd item
- **Retry Import** — Re-attempt the import pipeline after a download completes
- **Delete** — Remove from queue and optionally delete files

### Queue Tab

Shows the live SABnzbd download queue (items currently downloading or waiting). Provides a real-time view of slot status, speed, ETA, and category.

### Pending Tab

Shows NZB releases that have been found by a search but not yet submitted to SABnzbd.

```http
GET  /api/v1/queue/pending
DELETE /api/v1/queue/pending/{pending_id}
POST /api/v1/queue/pending/{pending_id}/retry
```

### Blacklist Tab

NZB GUIDs that have been permanently rejected (duplicate or bad quality). Blacklisted releases are skipped in future searches.

```http
GET    /api/v1/queue/blacklist
POST   /api/v1/queue/blacklist
DELETE /api/v1/queue/blacklist/{blacklist_id}
```

---

## 12. File Management

**URL:** `/file-management` (requires DJ+)

File Management surfaces two categories of problem files discovered by the library scanner.

### Unlinked Files

Audio files that exist on disk but are not associated with any artist, album, or track in the database. This happens when files are added directly to the library folder without going through the download pipeline.

**Actions per file:**
- **Edit Metadata** — Correct the embedded artist, album, and title tags before re-linking.
- **Link to Album** — Manually associate the file with a known album in the database.
- **Ignore** — Mark as intentionally unlinked (hides from the list).

**Filters:** by reason code, by search query, sort by any column.

### Unorganized Files

Audio files whose folder path does not match Studio54's naming convention (e.g., `Artist/Album (Year)/track.flac`). These are valid library files but need to be moved.

**Actions:**
- **Organize** — Triggers a file organization job to move files into the correct folder structure.

**Filters:** by audio format, by search query.

### Library Import (DJ+)

**URL:** `/file-management` → **Import** tab

Import an existing directory of audio files that have never been processed by Studio54:

1. Select a **root folder** (a configured library path) or enter a custom path.
2. Click **Start Import** — launches a 6-phase import job:
   1. **Scan** — Walk the directory and index all audio files
   2. **Artist Match** — Fuzzy-match folder names to existing or new artists
   3. **Metadata Sync** — Batch-sync MusicBrainz metadata (parallel Celery chord)
   4. **Folder Match** — Match scanned folders to albums
   5. **Track Match** — Link audio files to specific track records
   6. **Finalize** — Write file links, update statuses, emit completion events

The job supports **pause and resume** at any phase boundary. Monitor progress on the Activity → Jobs tab.

---

## 13. Settings (Director Only)

**URL:** `/settings`

### Indexers

Indexers are Newznab-compatible NZB search providers. Studio54 searches all enabled indexers when looking for a release.

**Add an indexer:**
1. Go to Settings → Indexers.
2. Click **Add Indexer**.
3. Enter the Newznab API URL and API key.
4. Click **Test** to verify connectivity.
5. Enable the indexer.

**API:**
```http
POST /api/v1/indexers
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "name": "My NZB Provider",
  "url": "https://mynzb.example.com",
  "api_key": "your-api-key",
  "is_enabled": true
}

POST /api/v1/indexers/{indexer_id}/test
```

API keys are encrypted at rest using Fernet. To retrieve a stored key:
```http
GET /api/v1/indexers/{indexer_id}/api-key
Authorization: Bearer eyJ...
```

### Download Clients

Configure the SABnzbd instance that receives NZB files.

1. Go to Settings → Download Clients.
2. Click **Add Client**.
3. Enter host, port, and API key.
4. Click **Test** — Studio54 will connect to SABnzbd and verify the API key.
5. Set as the **Default** client.

### Quality Profiles

Quality profiles define which audio formats and bitrates are acceptable for a given download.

**Default quality profile:**
- Minimum bitrate: 192 kbps
- Maximum size: 500 MB per album
- Preferred formats: FLAC, MP3-320

**Format ranking (best to worst):**  
FLAC-24 > FLAC > MP3-320 > MP3-V0 > MP3-256 > MP3-192 > MP3-128 > AAC-256 > AAC > OGG > OPUS > Unknown

### MusicBrainz Settings

| Setting | Description |
|---|---|
| **Rate Limit** | Requests per second to the remote API (max 1.0 per ToS) |
| **Local DB Enabled** | Use the local MusicBrainz mirror instead of the remote API |
| **Local DB URL** | PostgreSQL connection string for the local mirror |
| **Test Connection** | Verify local DB connectivity |

```http
GET /api/v1/settings/musicbrainz
PUT /api/v1/settings/musicbrainz
POST /api/v1/settings/musicbrainz/test-connection
```

### Worker Settings

Control Celery autoscaling without editing `.env`:

```http
GET /api/v1/settings/workers
PUT /api/v1/settings/workers
Content-Type: application/json

{ "autoscale_max": 8, "autoscale_min": 2 }

POST /api/v1/settings/workers/scale
Content-Type: application/json

{ "target": 4 }
```

### Album Type Filters

Configure which MusicBrainz release types Studio54 monitors per artist:

```http
GET /api/v1/settings/album-type-filters
PUT /api/v1/settings/album-type-filters
Content-Type: application/json

{ "enabled_types": ["Album", "EP"] }
```

### Hardcover Integration

Hardcover is an external audiobook catalog. Connect your account to enable book metadata enrichment:

```http
PUT /api/v1/settings/hardcover
Content-Type: application/json

{ "api_key": "your-hardcover-api-key" }

DELETE /api/v1/settings/hardcover
```

### User Management (Director Only)

**Create a user:**
```http
POST /api/v1/auth/users
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "username": "alice",
  "password": "temp-password",
  "display_name": "Alice",
  "role": "dj"
}
```

**Valid roles:** `director`, `dj`, `bouncer`, `partygoer`

**Update a user (role, display name, active status, password reset):**
```http
PATCH /api/v1/auth/users/{user_id}
Authorization: Bearer eyJ...
Content-Type: application/json

{
  "role": "bouncer",
  "is_active": true,
  "reset_password": "new-temp-password"
}
```

**Deactivate (soft delete):**
```http
DELETE /api/v1/auth/users/{user_id}
Authorization: Bearer eyJ...
```

**List all users:**
```http
GET /api/v1/auth/users
Authorization: Bearer eyJ...
```

### Notifications

Configure webhook notifications (Discord, Slack, custom HTTP) for download events:

Notifications are configured via `POST /api/v1/notifications`. Webhook URLs are stored encrypted.

### Storage Mounts

Register named mount points (NAS shares, external drives) that Studio54 can use as library paths or download destinations:

```http
GET  /api/v1/storage-mounts
POST /api/v1/storage-mounts
```

---

## 14. Statistics

**URL:** `/statistics`

The Statistics page (`/statistics`) provides a library health dashboard with no interaction — read-only.

| Section | Metrics |
|---|---|
| **Library Overview** | Total artists, monitored artists, total albums, total tracks, tracks with files |
| **Album Status Breakdown** | Stacked bar showing wanted / searching / downloading / downloaded / failed counts |
| **File Formats** | Distribution of audio formats in the library (FLAC, MP3, AAC, etc.) |
| **MusicBrainz Coverage** | % of tracks and albums tagged with MusicBrainz IDs |
| **Download Trend** | Daily bar chart of completed vs. failed downloads over the last 7 days |
| **Job Summary** | Count of each job type run in the past 7 days |

**API:**
```http
GET /api/v1/stats
Authorization: Bearer eyJ...
```

---

## 15. API Reference

Full interactive documentation is available at `http://<host>:8010/docs` (Swagger UI) and `http://<host>:8010/redoc` (ReDoc).

### Base URL

```
http://<host>:8010/api/v1
```

All responses are JSON. All request bodies must use `Content-Type: application/json` unless uploading a file (`multipart/form-data`).

### Error Responses

```json
{
  "detail": "Human-readable error message"
}
```

| HTTP Status | Meaning |
|---|---|
| `400` | Bad request — invalid parameters |
| `401` | Missing or invalid token |
| `403` | Insufficient role |
| `404` | Resource not found |
| `409` | Conflict (e.g., artist already exists) |
| `422` | Validation error — request body schema mismatch |
| `429` | Rate limit exceeded |
| `500` | Internal server error |

### Complete Endpoint Index

#### Auth

| Method | Path | Min Role | Description |
|---|---|---|---|
| `POST` | `/auth/login` | — | Log in, get JWT |
| `POST` | `/auth/refresh` | Any | Refresh JWT |
| `POST` | `/auth/change-password` | Any | Change own password |
| `GET` | `/auth/me` | Any | Current user info |
| `GET` | `/auth/me/preferences` | Any | Dashboard preferences |
| `PUT` | `/auth/me/preferences` | Any | Save dashboard preferences |
| `GET` | `/auth/users` | Director | List all users |
| `POST` | `/auth/users` | Director | Create user |
| `PATCH` | `/auth/users/{id}` | Director | Update user |
| `DELETE` | `/auth/users/{id}` | Director | Deactivate user |

#### Artists

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/musicbrainz/search/artists` | Any | Search MusicBrainz |
| `POST` | `/artists/search` | Any | Internal artist lookup |
| `GET` | `/artists` | Any | List library artists |
| `POST` | `/artists` | DJ | Add artist |
| `GET` | `/artists/genres` | Any | Get genre list |
| `GET` | `/artists/{id}` | Any | Artist detail with albums |
| `PATCH` | `/artists/{id}` | DJ | Update monitoring/profile |
| `DELETE` | `/artists/{id}` | DJ | Remove artist |
| `POST` | `/artists/{id}/sync` | DJ | Sync albums from MusicBrainz |
| `POST` | `/artists/{id}/refresh-metadata` | DJ | Refresh metadata |
| `POST` | `/artists/{id}/scan-folder` | DJ | Scan artist folder |
| `PATCH` | `/artists/{id}/rating` | Any | Rate artist |
| `PATCH` | `/artists/bulk-update` | DJ | Bulk update |
| `POST` | `/artists/refresh-all-metadata` | DJ | Refresh all artists |
| `POST` | `/artists/{id}/resolve-mbid` | DJ | Auto-resolve missing MBID |
| `POST` | `/{id}/cover-art` | DJ | Upload cover art |
| `POST` | `/{id}/cover-art-from-url` | DJ | Set cover art from URL |

#### Albums & Tracks

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/albums` | Any | List/search albums |
| `GET` | `/albums/wanted` | Any | Monitored but missing albums |
| `GET` | `/albums/calendar` | Any | Upcoming releases |
| `GET` | `/albums/{id}` | Any | Album detail with tracks |
| `PATCH` | `/albums/{id}` | DJ | Update album |
| `POST` | `/albums/{id}/search` | DJ | Search for NZB releases |
| `POST` | `/albums/{id}/scan-files` | DJ | Re-scan album folder |
| `POST` | `/albums/{id}/import` | DJ | Import found files |
| `GET` | `/albums/{id}/import-preview` | DJ | Preview import actions |
| `DELETE` | `/albums/{id}/downloads` | DJ | Cancel download |
| `PATCH` | `/albums/bulk-update` | DJ | Bulk update monitored |
| `GET` | `/tracks` | Any | List tracks with filters |
| `GET` | `/tracks/top` | Any | Top tracks |
| `GET` | `/tracks/{id}/stream` | Any | Stream audio file |
| `GET` | `/tracks/{id}/download` | Any | Download audio file |
| `GET` | `/tracks/{id}/lyrics` | Any | Get lyrics |
| `GET` | `/tracks/{id}/rating` | Any | Get track rating |
| `PATCH` | `/tracks/{id}/rating` | Any | Set track rating |
| `POST` | `/tracks/{id}/record-play` | Any | Increment play count |

#### Queue / Downloads

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/queue` | DJ | Active download queue |
| `POST` | `/queue/blacklist` | DJ | Add to blacklist |
| `GET` | `/queue/blacklist` | DJ | List blacklisted releases |
| `GET` | `/queue/history` | DJ | Download history |
| `GET` | `/queue/pending` | DJ | Pending NZB submissions |
| `POST` | `/queue/wanted` | DJ | Search all wanted albums |
| `POST` | `/queue/albums/{id}` | DJ | Trigger album download |
| `POST` | `/queue/albums/{id}/grab` | DJ | Grab specific release |
| `POST` | `/queue/{id}/retry-import` | DJ | Retry import |
| `DELETE` | `/queue/{id}` | DJ | Delete queue item |

#### Playlists

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/playlists` | Any | List own playlists |
| `GET` | `/playlists/published` | Any | List published playlists |
| `POST` | `/playlists` | Any | Create playlist |
| `GET` | `/playlists/{id}` | Any | Playlist with tracks |
| `PUT` | `/playlists/{id}` | Owner | Update playlist |
| `DELETE` | `/playlists/{id}` | Owner | Delete playlist |
| `POST` | `/playlists/{id}/tracks` | Owner | Add track |
| `POST` | `/playlists/{id}/tracks/bulk` | Owner | Add multiple tracks |
| `DELETE` | `/playlists/{id}/tracks/{track_id}` | Owner | Remove track |
| `PUT` | `/playlists/{id}/reorder` | Owner | Reorder tracks |
| `POST` | `/playlists/{id}/publish` | DJ | Publish playlist |
| `POST` | `/playlists/{id}/unpublish` | DJ | Unpublish playlist |
| `POST` | `/playlists/{id}/cover-art` | Owner | Upload cover art |

#### Audiobooks

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/authors` | Any | List authors |
| `POST` | `/authors` | DJ | Add author |
| `GET` | `/authors/{id}` | Any | Author detail |
| `PATCH` | `/authors/{id}` | DJ | Update author |
| `DELETE` | `/authors/{id}` | DJ | Remove author |
| `POST` | `/authors/{id}/sync` | DJ | Sync from Hardcover |
| `POST` | `/authors/{id}/refresh-metadata` | DJ | Refresh metadata |
| `POST` | `/authors/{id}/detect-series` | DJ | Auto-detect series |
| `POST` | `/authors/merge` | DJ | Merge duplicate authors |
| `GET` | `/books` | Any | List books |
| `GET` | `/books/wanted` | Any | Monitored but missing books |
| `GET` | `/books/{id}` | Any | Book detail with chapters |
| `PATCH` | `/books/{id}` | DJ | Update book |
| `POST` | `/books/{id}/search` | DJ | Search for NZB release |
| `POST` | `/books/{id}/refresh-metadata` | DJ | Refresh metadata |
| `POST` | `/books/{id}/edit-metadata` | DJ | Manually edit metadata |
| `POST` | `/books/{id}/set-lead-author` | DJ | Reassign primary author |
| `POST` | `/books/bulk-move-author` | DJ | Bulk reassign author |
| `GET` | `/books/{id}/progress` | Any | Get reading progress |
| `POST` | `/books/{id}/progress` | Any | Update progress |
| `POST` | `/books/progress/batch` | Any | Batch update progress |
| `DELETE` | `/books/{id}/progress` | Any | Clear progress |

#### Now Playing

| Method | Path | Min Role | Description |
|---|---|---|---|
| `POST` | `/now-playing/heartbeat` | Any | Register now-playing (30s TTL) |
| `DELETE` | `/now-playing/heartbeat` | Any | Clear now-playing |
| `GET` | `/now-playing` | Any | Get all active listeners |

**Heartbeat payload:**
```json
{
  "track_id": "uuid",
  "track_title": "Everything In Its Right Place",
  "artist_name": "Radiohead",
  "artist_id": "uuid",
  "album_id": "uuid",
  "album_title": "Kid A",
  "cover_art_url": "/api/v1/...",
  "position_ms": 45000,
  "book_id": null,
  "chapter_id": null
}
```

Must be sent every ≤30 seconds while playing. Omitting `book_id`/`chapter_id` indicates music playback; populating them triggers audiobook progress auto-save.

#### DJ Requests

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/dj-requests` | DJ | All requests |
| `GET` | `/dj-requests/by-user` | Any | Own requests |
| `POST` | `/dj-requests` | Any | Submit request |
| `PATCH` | `/dj-requests/{id}` | DJ | Update status |
| `DELETE` | `/dj-requests/{id}` | Any | Delete own request |

#### Jobs

| Method | Path | Min Role | Description |
|---|---|---|---|
| `GET` | `/jobs` | DJ | List jobs |
| `GET` | `/jobs/stats` | DJ | Job statistics |
| `GET` | `/jobs/{id}` | DJ | Job detail |
| `POST` | `/jobs/{id}/cancel` | DJ | Cancel job |
| `POST` | `/jobs/{id}/pause` | DJ | Pause job |
| `POST` | `/jobs/{id}/resume` | DJ | Resume job |
| `POST` | `/jobs/{id}/retry` | DJ | Retry failed job |
| `GET` | `/jobs/{id}/log` | DJ | Job log metadata |
| `GET` | `/jobs/{id}/log/content` | DJ | Job log text |
| `POST` | `/jobs/pause-all` | Director | Pause all running jobs |
| `POST` | `/jobs/resume-all` | Director | Resume all paused jobs |
| `DELETE` | `/jobs/{id}` | DJ | Delete job record |

#### Listen & Add

| Method | Path | Min Role | Description |
|---|---|---|---|
| `POST` | `/listen/identify` | Any | Identify audio via microphone recording |

**Request:** `multipart/form-data` with a `file` field containing WAV, WebM, or OGG audio (≤20 seconds).

**Response:**
```json
{
  "track_title": "Karma Police",
  "artist_name": "Radiohead",
  "album_title": "OK Computer",
  "release_year": 1997,
  "musicbrainz_id": "uuid",
  "confidence": 0.92,
  "in_library": true,
  "artist_id": "uuid",
  "album_id": "uuid"
}
```

#### Settings (Director)

| Method | Path | Description |
|---|---|---|
| `GET/PUT` | `/settings/musicbrainz` | MusicBrainz configuration |
| `POST` | `/settings/musicbrainz/test-connection` | Test MB local DB |
| `GET/PUT` | `/settings/workers` | Celery worker autoscale |
| `POST` | `/settings/workers/scale` | Scale to target worker count |
| `GET/PUT` | `/settings/album-type-filters` | Enabled album types |
| `GET/PUT` | `/settings/hardcover` | Hardcover API key |
| `DELETE` | `/settings/hardcover` | Remove Hardcover integration |
