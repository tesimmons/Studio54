# Studio54 — Core Workflows

**Version:** 1.0  
**Date:** 2026-05-14  

---

## Table of Contents

1. [User Authentication](#1-user-authentication)
2. [Artist Add & MusicBrainz Sync](#2-artist-add--musicbrainz-sync)
3. [Automated Album Acquisition](#3-automated-album-acquisition)
4. [Decision Engine — Release Evaluation](#4-decision-engine--release-evaluation)
5. [Download Monitoring & Import](#5-download-monitoring--import)
6. [Library Scan (V2 Scanner)](#6-library-scan-v2-scanner)
7. [Library Import (6-Phase Orchestration)](#7-library-import-6-phase-orchestration)
8. [Audio Playback & Now Playing](#8-audio-playback--now-playing)
9. [Audiobook Playback & Progress Tracking](#9-audiobook-playback--progress-tracking)
10. [DJ Request Lifecycle](#10-dj-request-lifecycle)
11. [Worker Startup & Orphan Recovery](#11-worker-startup--orphan-recovery)

---

## 1. User Authentication

**Trigger:** User navigates to the app for the first time or token expires.

```mermaid
sequenceDiagram
    actor User
    participant SPA as React SPA
    participant AC as AuthContext
    participant API as FastAPI /api/v1
    participant DB as PostgreSQL

    User->>SPA: Navigate to any route
    SPA->>AC: Check localStorage for JWT
    AC-->>SPA: No token / expired

    SPA->>SPA: Redirect to /login

    User->>SPA: Enter username + password
    SPA->>API: POST /api/v1/login
    API->>DB: SELECT user WHERE username = ?
    DB-->>API: User row (password_hash, role, is_active)
    API->>API: bcrypt.verify(password, hash)

    alt Valid credentials
        API-->>SPA: { access_token (JWT), token_type }
        SPA->>AC: Store token in localStorage
        AC->>AC: Decode JWT → user_id, role, expiry
        SPA->>SPA: Redirect to /disco-lounge
    else Invalid credentials
        API-->>SPA: 401 Unauthorized
        SPA->>User: Show error message
    end

    Note over SPA,API: All subsequent requests include<br/>Authorization: Bearer <JWT>

    SPA->>API: GET /api/v1/artists (Bearer token)
    API->>API: Decode JWT → require_any_user dependency
    API->>DB: SELECT user WHERE id = ?
    DB-->>API: User (role check)
    API-->>SPA: 200 OK + data
```

**Role gates enforced by `<ProtectedRoute requiredRoles={[...]}>`:**

| Route | Required Role |
|---|---|
| `/dashboard` | `director`, `dj` |
| `/file-management` | `director`, `dj` |
| `/activity` | `director`, `dj` |
| `/settings` | `director` only |
| All others | Any authenticated user |

---

## 2. Artist Add & MusicBrainz Sync

**Trigger:** User searches for and adds an artist from the Disco Lounge.

```mermaid
sequenceDiagram
    actor User
    participant SPA as React SPA
    participant API as FastAPI
    participant DB as PostgreSQL
    participant BEAT as Celery Beat
    participant SYNC as Celery Worker (sync queue)
    participant MB as MusicBrainz Local Mirror

    User->>SPA: Search for artist by name
    SPA->>API: GET /api/v1/artists/search?q=The+Beatles
    API->>MB: musicbrainzngs.search_artists(query)
    MB-->>API: List of MusicBrainz artist candidates
    API-->>SPA: Candidate list with MBIDs

    User->>SPA: Select artist + choose monitor type
    SPA->>API: POST /api/v1/artists { musicbrainz_id, monitor_type, quality_profile_id }
    API->>DB: INSERT INTO artists (musicbrainz_id, monitor_type, ...)
    DB-->>API: Artist record (id)
    API->>SYNC: sync_artist_albums.delay(artist_id)
    API-->>SPA: 201 Created + artist record

    Note over SYNC,MB: Runs on sync queue

    SYNC->>MB: Get all release groups for MBID
    MB-->>SYNC: Release groups list

    SYNC->>DB: Bulk SELECT albums WHERE musicbrainz_id IN (...)
    DB-->>SYNC: Already-synced album MBIDs

    loop For each NEW release group (batches of 10)
        SYNC->>MB: Get full release group details
        MB-->>SYNC: Tracks, credits, dates, formats
        SYNC->>SYNC: should_monitor_album(monitor_type, release_date, album_type)
        SYNC->>DB: INSERT INTO albums (title, musicbrainz_id, status=WANTED, monitored=?)
        SYNC->>DB: INSERT INTO tracks (title, musicbrainz_id, track_number, ...)
        SYNC->>MB: Fetch cover art URL
        MB-->>SYNC: cover_art_url
    end

    SYNC->>DB: UPDATE artists SET album_count=?, last_sync_at=NOW()
    SYNC-->>API: Sync complete (N albums added)

    Note over BEAT,SYNC: Daily: sync_all_artists (beat schedule)
    BEAT->>SYNC: sync_all_artists.delay()
    SYNC->>DB: SELECT monitored artists
    loop Per artist
        SYNC->>SYNC: sync_artist_coordinator.delay(artist_id)
    end
```

**Monitor type logic (`should_monitor_album`):**

| Monitor Type | Albums Monitored |
|---|---|
| `all_albums` | Every release group |
| `future_only` | Only releases with `release_date > today` |
| `existing_only` | Only if local files already present |
| `first_album` | Chronologically first album only |
| `latest_album` | Most recent album only |
| `none` | No albums monitored |

---

## 3. Automated Album Acquisition

**Trigger:** Celery Beat fires `search_wanted_albums_v2` every 15 minutes, or user manually triggers search.

```mermaid
flowchart TD
    A([Beat: every 15 min]) --> B[search_wanted_albums_v2\nsearch queue]
    B --> C[Query DB: albums WHERE\nstatus=WANTED AND monitored=TRUE\nAND retry_enabled=TRUE\nAND next_retry_at ≤ NOW]
    C --> D{Any wanted\nalbums?}
    D -- No --> Z([Done])
    D -- Yes --> E[For each album\ndispatch search_album.delay]

    E --> F[search_album\ndownloads queue]
    F --> G{Acquire Redis\ndistributed lock\nfor album_id}
    G -- Locked by another worker --> H([Skip — search in-flight])
    G -- Lock acquired --> I[Load previously\nattempted NZB GUIDs]

    I --> J[Query enabled indexers\nfrom DB]
    J --> K{Any enabled\nindexers?}
    K -- No --> L([Return: no indexers])
    K -- Yes --> M[SET album.status = SEARCHING]

    M --> N[Decrypt indexer API keys\nvia Fernet]
    N --> O[Create Newznab clients\nper indexer]
    O --> P[Aggregator: search_music\nartist + album, limit 50 per indexer]
    P --> Q{Results\nfound?}
    Q -- No --> R[SET album.status = WANTED]
    R --> S([Release lock — no results])

    Q -- Yes --> T[Filter top 20 results\nExclude previously attempted GUIDs]
    T --> U{Any new\ncandidates?}
    U -- No --> V[SET album.status = WANTED]
    V --> W([Release lock — all tried])

    U -- Yes --> X[Pass results to\nDecision Engine]
    X --> Y{Best candidate\napproved?}
    Y -- No --> AA[Log rejections]
    AA --> AB([Release lock — all rejected])

    Y -- Yes --> AC[add_download.delay\nbest NZB + alternates list]
    AC --> AD([Release lock — download queued])
```

---

## 4. Decision Engine — Release Evaluation

**Trigger:** Called by `search_album` for every candidate release from indexers.

The decision engine implements a **Specification Pattern**: each spec evaluates one rule and returns a `Rejection` or `None`. Specs are sorted by priority; a `PERMANENT` rejection short-circuits evaluation.

```mermaid
flowchart TD
    A([releases list + album]) --> B[DownloadDecisionMaker\n.get_decisions]

    B --> C[For each release\nbuild RemoteAlbum]

    C --> D[Sort specifications\nby priority asc]

    D --> E{Next spec?}
    E -- None left --> F{Any rejections?}

    E -- Run spec --> G[spec.is_satisfied_by\nremote_album]
    G --> H{Rejection\nreturned?}
    H -- No → satisfied --> E
    H -- Yes --> I{Rejection\ntype?}
    I -- TEMPORARY --> J[Append rejection\ncontinue to next spec]
    J --> E
    I -- PERMANENT --> K[Append rejection\nSTOP evaluation]
    K --> F

    F -- Yes --> L([DownloadDecision: REJECTED\ntemporarily or permanently])
    F -- No --> M([DownloadDecision: APPROVED])

    M --> N[prioritize_decisions\nsort by quality then size]

    subgraph Specifications["Built-in Specifications (priority order)"]
        S1["Priority 1–10: Critical\n• AlreadyDownloadedSpec\n• BlacklistSpec\n• AlreadyImportingSpec"]
        S2["Priority 11–30: Quality\n• QualityAllowedSpec\n• QualityUpgradeSpec\n• CutoffNotMetSpec"]
        S3["Priority 31–50: Constraints\n• SizeSpec (min/max MB)\n• RetentionSpec (age days)"]
        S4["Priority 51–70: History\n• PreviouslyAttemptedSpec\n• DuplicateSpec"]
    end

    subgraph QualityOrder["Quality Ranking (best → worst)"]
        Q1["FLAC-24 → FLAC → MP3-320 → MP3-V0\n→ MP3-256 → MP3-192 → MP3-128\n→ AAC-256 → AAC → OGG → OPUS → Unknown"]
    end
```

---

## 5. Download Monitoring & Import

**Trigger:** `monitor_active_downloads` runs every 30 seconds on the monitoring queue.

```mermaid
sequenceDiagram
    participant BEAT as Celery Beat (30s)
    participant MON as monitor_active_downloads
    participant DB as PostgreSQL
    participant SAB as SABnzbd API
    participant FS as /downloads (filesystem)
    participant IMP as import_download task

    BEAT->>MON: Fire every 30s
    MON->>DB: SELECT download_queue WHERE\nstatus IN (QUEUED, DOWNLOADING, POST_PROCESSING)

    loop For each active download
        MON->>SAB: GET /api?mode=queue&nzo_id=<sabnzbd_id>
        SAB-->>MON: { status, percentage, mb_left, fail_msg }

        alt SABnzbd: Downloading
            MON->>DB: UPDATE download_queue SET\nstatus=DOWNLOADING, progress=N%
        else SABnzbd: Completed (moved to history)
            MON->>SAB: GET /api?mode=history&nzo_id=<sabnzbd_id>
            SAB-->>MON: { storage (download path), fail_msg }

            alt No fail message
                MON->>DB: UPDATE status=POST_PROCESSING\ndownload_path=<storage>
                MON->>IMP: import_download.delay(download_id)
            else SABnzbd fail_message present
                MON->>DB: UPDATE status=FAILED\nsab_fail_message=<msg>
                MON->>MON: try_alternate_nzb(download_id)

                alt Alternates available
                    MON->>SAB: Submit alternate NZB
                    MON->>DB: New DownloadQueue row for alternate
                else No alternates
                    MON->>DB: SET album.status=FAILED
                end
            end
        else SABnzbd: Not found / deleted
            MON->>DB: Mark FAILED, try alternates
        end
    end

    IMP->>FS: Scan download_path for audio files
    IMP->>DB: Match files to tracks via MBID + fuzzy
    IMP->>FS: Move files to /music/<Artist>/<Album>/
    IMP->>DB: UPDATE track.has_file=TRUE\ntrack.file_path=<new_path>
    IMP->>IMP: _verify_and_set_album_status(album)

    alt All tracks linked
        IMP->>DB: SET album.status=DOWNLOADED
    else Partial
        IMP->>DB: SET album.status=DOWNLOADING
    else None linked
        IMP->>DB: SET album.status=FAILED
    end
```

---

## 6. Library Scan (V2 Scanner)

**Trigger:** User clicks "Scan" in File Management, or `orchestrate_library_import` calls it as Phase 1.

The V2 scanner pipelines work across **four dedicated Celery queues** to parallelize discovery and enrichment.

```mermaid
flowchart TD
    A([scan_library_v2\nscan queue]) --> B[walk_directory_v2\nCollect all audio file paths\nSkip: hidden, resource fork, system, unsupported]

    B --> C[Split files into batches\ndefault: 100 files/batch]

    C --> D[start_fast_ingestion\ningest_fast queue]

    subgraph Phase1["Phase 1 — Fast Ingest (ingest_fast queue)"]
        D --> E[fast_ingest_batch\nFor each file:\n• Extract basic tags via mutagen\n• INSERT or UPDATE library_files\n• Skip unchanged mtime files]
    end

    E --> F[index_metadata_batch\nindex_metadata queue]

    subgraph Phase2a["Phase 2a — Full Metadata (index_metadata queue)"]
        F --> G[Read all ID3/FLAC/AAC tags\nStore metadata_json JSONB\nExtract MusicBrainz IDs from tags\nSet mbid_in_file flag]
    end

    G --> H[fetch_images_batch\nfetch_images queue]

    subgraph Phase2b["Phase 2b — Image Fetching (fetch_images queue)"]
        H --> I[For files without art:\n• Check embedded artwork\n• Fetch cover via MusicBrainz\n• Fetch artist image via Fanart.tv\nSet album_art_url, artist_image_url]
    end

    I --> J[calculate_hash_batch\ncalculate_hashes queue]

    subgraph Phase2c["Phase 2c — Hash Calculation (calculate_hashes queue)"]
        J --> K[Compute AcoustID fingerprint\nfor unlinked files\nStore in metadata_json]
    end

    K --> L[UPDATE scan_job:\nfiles_scanned, files_added\nfiles_updated, files_skipped]
    L --> M([Scan complete])

    subgraph Resume["Checkpoint / Resume"]
        N[ScanJob.checkpoint_data JSONB\nStores: phase, last_batch, counters]
        N --> O[On pause_requested=TRUE:\nWorker stops after current batch]
        O --> P[On resume: read checkpoint\nSkip already-processed batches]
    end
```

**Skip rules in `FastMetadataExtractor.should_skip_file`:**

| Reason | Example |
|---|---|
| `resource_fork` | `._filename.mp3` (macOS) |
| `hidden` | `.DS_Store`, `.hidden_file` |
| `system` | `Thumbs.db` |
| `unsupported` | `.doc`, `.jpg`, `.pdf` |

---

## 7. Library Import (6-Phase Orchestration)

**Trigger:** User initiates an import from the File Management page. Supports full pause/resume.

```mermaid
flowchart TD
    A([orchestrate_library_import\ncelery queue]) --> B{Already\ncompleted/running?}
    B -- Yes --> Z([Skip — guard against duplicates])
    B -- No --> C{Resuming from\nfailed/paused?}
    C -- Yes --> D[Load checkpoint\nSkip completed phases]
    C -- No --> E[Mark status=running]
    D --> E

    E --> P1

    subgraph P1["Phase 1 — File Scanning (15%)"]
        P1s[scan_library_v2\nWalk filesystem\nINSERT library_files]
    end

    P1 --> P2

    subgraph P2["Phase 2 — Artist Matching (20–35%)"]
        P2s[Get unique artists from library_files\nFor each artist:\n• Search MusicBrainz by name\n• Score confidence 0–100\n• If ≥ threshold: auto-match → INSERT artist\n• If < threshold: flag manual_review\nINSERT library_artist_matches]
    end

    P2 --> P2b{All artists\nmatched?}
    P2b -- Manual review required --> WAIT[Set status=paused\nUI shows unmatched artists\nUser resolves matches]
    WAIT --> P2
    P2b -- Yes --> P3

    subgraph P3["Phase 3 — Metadata Sync (35–65%) — parallel chord"]
        P3s[Split matched artists into batches of 50\nchord sync_import_batch × N\n  | finalize_import_sync\nEach batch: sync albums+tracks from MusicBrainz]
    end

    P3 --> P4

    subgraph P4["Phase 4 — Folder Matching (65–75%)"]
        P4s[AlbumFileMatcher:\nMatch directories to album records\nby folder name similarity\nUpdate album.root_folder_path]
    end

    P4 --> P5

    subgraph P5["Phase 5 — Track Matching (75–90%)"]
        P5s[MBIDFileMatcher:\nFor each library_file:\n  1. Match via musicbrainz_trackid tag\n  2. Fallback: fuzzy title + artist match\nIf matched: UPDATE track.has_file=TRUE\n             UPDATE track.file_path\nIf not matched: INSERT unlinked_files]
    end

    P5 --> P6

    subgraph P6["Phase 6 — Finalization (90–100%)"]
        P6s[Recalculate album.status for each artist\nUpdate artist stats\nMark import_job.status=completed]
    end

    P6 --> DONE([Import complete])

    subgraph Checkpoint["Pause / Resume at any phase boundary"]
        CHK[JobCheckpointManager writes\nphase + last_artist_index to DB\nWorker checks pause_requested flag]
    end
```

---

## 8. Audio Playback & Now Playing

**Trigger:** User clicks Play on any track in the SPA.

```mermaid
sequenceDiagram
    actor User
    participant PP as PersistentPlayer\n(always mounted in Layout)
    participant PC as PlayerContext\n(useReducer)
    participant BC as BroadcastChannel\n(cross-tab)
    participant POP as PopOutPlayer\n(/player window)
    participant API as FastAPI
    participant RD as Redis
    participant SB as Sound Booth page

    User->>PP: Click Play on track
    PP->>PC: dispatch(PLAY_TRACK, { track, queue })
    PC->>PC: State update:\n currentTrack, queue,\n isPlaying=true
    PC->>BC: broadcast({ type: PLAY_TRACK, payload })
    BC-->>POP: Receive → dispatch to local PlayerContext
    PP->>PP: <audio> element: src=track.file_path, play()

    loop Every 30s while isPlaying
        PP->>API: POST /api/v1/now-playing/heartbeat\n{ track_id, track_title, artist_name,\n  album_id, cover_art_url }
        API->>RD: SETEX studio54:now_playing:<user_id>\n60s TTL\nJSON { track_title, artist_name, listening_since, ... }
        API-->>PP: 204 No Content
    end

    Note over RD: Key expires after 60s with no heartbeat<br/>(user stopped playing or closed tab)

    SB->>API: GET /api/v1/now-playing
    API->>RD: SCAN studio54:now_playing:*
    RD-->>API: All active listener keys
    API-->>SB: [ { user, display_name, track_title,\n  artist_name, listening_since }, ... ]
    SB->>SB: Render live listener cards\n(polls every 30s)

    User->>PP: Click Mark as Read (archive)
    PP->>API: POST /api/v1/now-playing/archive\n{ session_entity_id }
    API->>DB: UPDATE user_listening_sessions\nSET archived_at=NOW()
    API-->>PP: 200 OK
    PP->>PC: dispatch(RESET_SESSION)
```

**BroadcastChannel sync events:**

| Action | Description |
|---|---|
| `PLAY_TRACK` | Start playing a new track |
| `PAUSE` / `RESUME` | Toggle playback state |
| `SKIP_NEXT` / `SKIP_PREV` | Navigate queue |
| `SET_QUEUE` | Replace full queue |
| `VOLUME_CHANGE` | Sync volume across tabs |
| `RESET_SESSION` | Clear player after archive |

---

## 9. Audiobook Playback & Progress Tracking

**Trigger:** User opens a book or series in the Reading Room and presses Play.

```mermaid
sequenceDiagram
    actor User
    participant SPA as Reading Room / BookDetail
    participant API as FastAPI
    participant DB as PostgreSQL
    participant PC as PlayerContext
    participant PP as PersistentPlayer
    participant RD as Redis

    User->>SPA: Open book or series
    SPA->>API: GET /api/v1/books/:id
    API-->>SPA: Book + chapters list

    SPA->>API: GET /api/v1/book-progress/:book_id
    API->>DB: SELECT book_progress WHERE user_id=? AND book_id=?
    DB-->>API: { chapter_id, position_ms } or null
    API-->>SPA: Resume position (or chapter 1 / 0ms)

    User->>SPA: Click Play (book or series)
    SPA->>API: POST /api/v1/listening-sessions\n{ session_type: "book"|"series",\n  book_id or series_id }
    API->>DB: UPSERT user_listening_sessions\n(unique per user+book or user+series)\nchapter_queue = [chapter IDs in order]
    API-->>SPA: Session + chapter_queue

    SPA->>PC: dispatch(PLAY_BOOK, { chapters, startIndex, startPosition })
    PC->>PP: Set currentTrack = chapter\nSet isAudiobook = true

    PP->>PP: <audio>.src = chapter.file_path\n<audio>.currentTime = position_ms / 1000
    PP->>PP: Play

    loop Every 30s while playing
        PP->>API: POST /api/v1/now-playing/heartbeat\n{ track_id: chapter_id,\n  book_id, chapter_id,\n  position_ms: audio.currentTime * 1000 }
        API->>DB: UPSERT book_progress\n(user_id, book_id)\nSET chapter_id=?, position_ms=?
        API->>RD: SETEX now_playing key (60s TTL)
        API-->>PP: 204
    end

    PP->>PP: audio 'ended' event
    PP->>PC: dispatch(CHAPTER_ENDED)
    PC->>PC: Advance currentIndex in session

    alt More chapters remain
        PC->>PP: Load next chapter\nstartPosition = 0
    else Book complete
        PP->>API: POST /api/v1/book-progress/:book_id/complete
        API->>DB: UPDATE book_progress SET completed=TRUE
        PP->>PC: dispatch(RESET_SESSION)
    end

    User->>SPA: Resume later (new session)
    SPA->>API: GET /api/v1/book-progress/:book_id
    API->>DB: SELECT book_progress WHERE user_id=? AND book_id=?
    DB-->>API: { chapter_id, position_ms }
    SPA->>PC: dispatch(PLAY_BOOK, { startChapter, startPosition })
```

---

## 10. DJ Request Lifecycle

**Trigger:** Any authenticated user submits a content request from the DJ Requests page.

```mermaid
flowchart TD
    A([User: Submit Request]) --> B[POST /api/v1/dj-requests\n{ request_type, title, artist_name,\n  musicbrainz_id, notes }]
    B --> C[INSERT dj_requests\nstatus=pending]
    C --> D([Requester sees: Pending])

    D --> E{Director reviews\nrequest}

    E -- Reject --> F[PATCH /api/v1/dj-requests/:id\n{ status: rejected, response_note }]
    F --> G([Requester notified: Rejected\nwith director note])

    E -- Approve --> H[PATCH /api/v1/dj-requests/:id\n{ status: approved, response_note }]
    H --> I{request_type?}

    I -- artist --> J[POST /api/v1/artists\nmusicbrainz_id from request]
    J --> K[Artist added + MB sync triggered]
    K --> L[PATCH status=fulfilled\nfulfilled_by_id=director_user_id]

    I -- album --> M[Find or add artist\nThen add specific album]
    M --> L

    I -- track --> N[Manual search triggered\nPOST /api/v1/search/manual\n{ artist, album, track_name }]
    N --> L

    L --> O([Requester sees: Fulfilled])
```

---

## 11. Worker Startup & Orphan Recovery

**Trigger:** Any Celery worker starts (deploy, restart, crash recovery).

```mermaid
sequenceDiagram
    participant W as Celery Worker
    participant RD as Redis
    participant DB as PostgreSQL
    participant CEL as Celery Broker

    W->>W: Worker initializes
    W->>W: sleep(5s) — let worker fully boot

    W->>RD: SETNX worker_recovery_lock (timeout=60s)
    RD-->>W: Lock acquired? (only one worker wins)

    alt Lock NOT acquired
        W-->>W: Another worker handling recovery\nSkip and proceed normally
    else Lock acquired
        W->>DB: SELECT library_import_jobs WHERE\nstatus IN ('pending','running','stalled')

        loop For each orphaned LibraryImportJob
            W->>DB: If running/stalled:\n  SET status=failed,\n  error_message="Worker restarted"
            W->>CEL: orchestrate_library_import.delay\n(library_path_id, import_job_id)
            W->>DB: UPDATE celery_task_id = new_task_id
            Note over W: Resumes from last checkpoint phase
        end

        W->>DB: SELECT job_states WHERE\nstatus IN ('running','stalled','retrying')

        loop For each orphaned JobState
            W->>DB: SET status=failed\nerror_message="Worker restarted during <status>"
            Note over W: Beat will re-dispatch via normal schedule
        end

        W->>DB: SELECT file_organization_jobs WHERE\nstatus IN ('running','pending')

        loop For each orphaned FileOrganizationJob
            W->>DB: SET status=failed\nerror_message="Progress: N/M files — resumable"
            Note over W: User can restart from File Management UI
        end

        W->>RD: Release worker_recovery_lock
    end

    W-->>W: Ready to process tasks
```

**Why this matters:** Celery tasks are dispatched as Redis messages. If a worker dies mid-task, the DB record stays `running` but the Redis message is gone. Without recovery, these jobs would be stuck forever. The distributed lock ensures exactly one worker runs recovery, preventing duplicate re-dispatches on multi-worker deployments.

---

## 12. End-to-End: "Wanted Album" Happy Path

This composite diagram shows the complete happy path from artist addition through a playable downloaded album.

```mermaid
flowchart LR
    A([User adds artist]) --> B[MusicBrainz Sync\nN albums inserted\nstatus=WANTED]
    B --> C[Beat: every 15 min\nsearch_wanted_albums_v2]
    C --> D[search_album\nQuery all indexers]
    D --> E[Decision Engine\nEvaluate candidates]
    E --> F{Approved?}
    F -- No --> G[Log rejections\nAlbum stays WANTED]
    F -- Yes --> H[add_download\nSubmit best NZB to SABnzbd]
    H --> I[monitor_active_downloads\nevery 30s]
    I --> J{SABnzbd\ncomplete?}
    J -- No --> I
    J -- Yes --> K[import_download\nMove files to /music/]
    K --> L[Link tracks\nhas_file=TRUE, file_path=?]
    L --> M[album.status=DOWNLOADED]
    M --> N([User plays album\nin PersistentPlayer])
    N --> O[Heartbeat → Redis\nNow Playing: Sound Booth]
```

---

*Next documents: `Backend_API.md`, `Frontend.md`, `TaskQueue.md`, `ExternalIntegrations.md`*
