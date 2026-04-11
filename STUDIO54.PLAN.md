# Studio54 & MUSE — Consolidated Project Plan

**Last Updated:** 2026-02-16
**Consolidates:** STUDIO54.md, STUDIO54.Implementation.Summary.md, STUDIO54.Jobs.Implementation.Plan.md, STUDIO54.Recommendations.md, STUDIO54.SCAN.ENHANCEMENT.PLAN.md, BATCHING.QUEUEING.PLAN.md, MUSE.Plan.txt, MUSE.Enhancement.Implementation.md, MUSE.Optimization.Recommendations.md, MUSE.Scanner.Improvements.md, and other planning docs (all moved to `.old/plans/`)

---

## What's Been Built (Completed)

### Studio54 — Music Acquisition & Library Management

| Area | Status | Details |
|------|--------|---------|
| **Core Backend** | Done | FastAPI + SQLAlchemy + Alembic. 7+ DB models, 34+ API endpoints, Celery task queues |
| **Web UI** | Done | React 18 + TypeScript + TanStack Query + Tailwind. Artists, Albums, AlbumDetail, ArtistDetail, Settings, Activity pages |
| **Download Pipeline** | Done | SABnzbd client (dataclasses, NZB attempt tracking, auto-retry max 3, alternate NZB fallback), Newznab indexer client, quality ranking |
| **Lidarr-Style Workflow** | Done | Add Artist modal (search MB -> configure), root folders, quality profiles (4 defaults), monitor types, search missing, bulk album updates |
| **Job Tracking System** | Done | `JobState` model, `JobTrackedTask` base class with heartbeat/checkpoint/pause/cancel, `JobLogger`, Activity page with real-time refresh |
| **Stall Detection** | Done | `detect_stalled_jobs` every 2 min (5 min threshold JobState, 10 min FileOrganizationJob), handles NULL heartbeat edge case |
| **Background Heartbeat** | Done | `BackgroundHeartbeat` thread class for long-running MB API calls in validate/fetch metadata tasks |
| **File Organization** | Done | MBID-based naming, associate & organize service, organize artist/album tasks, audit trail, rollback, `.mbid.json` metadata files |
| **MBID Workflow Jobs** | Done | Fetch metadata, validate MBID, link files, reindex albums, verify audio — all with checkpoint/resume |
| **Empty Dir Cleanup** | Done | `cleanup_empty_directories()` runs after organize tasks, walks up from moved file parents |
| **Log Cleanup** | Done | Scheduled 120-day retention, preview before cleanup, manual API trigger |
| **MusicBrainz Integration** | Done | Centralized API proxy service (port 8020) with separate MUSE/Studio54 queues, 1 req/sec global rate limit |
| **Docker Deployment** | Done | 5 containers (service, worker, web, db, redis). `deploy.sh` script with `--no-cache` builds |

### MUSE — Music Library Duplicate Detection & Cleanup

| Area | Status | Details |
|------|--------|---------|
| **Core System (Phases 1-10)** | Done | PostgreSQL, Redis, FastAPI, Celery, React frontend. Network shares, library scanning, fingerprinting, 3-phase duplicate detection, cleanup |
| **Scanner v2** | Done | Two-phase scanning (fast ingest + batch metadata), parallel workers, 65K files in ~19 min |
| **NFS Infrastructure** | Done | Host-level NFSv4.2 mount, auto-health checker (60s), auto-remount on stale, 386 MB/s write perf |
| **Duplicate Cleanup** | Done | NFS permission fix (UID/GID matching), cleanup progress endpoint, backup management |
| **Ponder Tag Fixing** | Done | Picard integration, 30s per-file timeout, metadata matching at 100% confidence |
| **Job Monitoring** | Done | Auto-resume for stuck ponder/scan jobs, Jobs Status page with unified view |
| **Library Browser** | Done | Files grid page with sortable columns, pagination, metadata editor |
| **File Organization** | Done | MBID-based renaming, `.mbid.json` files, organize endpoints |
| **MusicBrainz API Service** | Done | Shared rate-limited proxy between MUSE and Studio54 |

---

## What's Left To Do

### Priority 1 — High Impact / Low Effort

#### 1.1 Studio54 Test Suite ✅ COMPLETED
**Effort:** 2-3 days | **Impact:** Critical for reliability
- ✅ Created `studio54-service/tests/` with conftest.py, SQLite in-memory DB, and model factories
- ✅ 235 tests across 15 test files (unit + integration)
- ✅ Unit tests for: `sync_tasks.py` (should_monitor_album, _parse_mb_date, _update_artist_stats), `download_tasks.py` (8 tests), `organization_tasks.py` (ErrorCategory, ErrorTracker, BackgroundHeartbeat), `search_tasks.py` (Redis lock acquire/release), `sabnzbd_client.py`, `naming_engine.py`, `encryption.py`, `security.py`, `notifications.py`
- ✅ Integration tests for: Artists API, Albums API, Health API, Notifications API, Search API, Queue API, Quality Profiles, Download Clients, Indexers, Root Folders

#### 1.2 Album Search Deduplication ✅ COMPLETED
**Effort:** 0.5 days | **Impact:** Reduces wasted API calls
- ✅ Redis-based dedup implemented in `search_tasks.py`: `_acquire_search_lock()` / `_release_search_lock()`
- ✅ Key: `search:album:{album_id}` with 300s TTL (SEARCH_LOCK_TTL)
- ✅ Unit tests verifying lock acquire, reject, and release behavior

#### 1.3 Download Queue Archival ✅ COMPLETED
**Effort:** 0.5 days | **Impact:** Prevents DB bloat
- ✅ `cleanup_old_downloads` task in `monitoring_tasks.py` with configurable retention
- ✅ Beat schedule for automatic periodic cleanup
- ✅ `DELETE /albums/{id}/downloads?status_filter=failed` API endpoint for manual cleanup

### Priority 2 — Important Improvements

#### 2.1 Studio54 Scanner Batching
**Effort:** 3-5 days | **Impact:** Performance for large libraries
- Current scanner iterates release groups sequentially in `sync_tasks.py`
- Refactor to coordinator-batch-finalize pattern (per BATCHING.QUEUEING.PLAN.md):
  - `scan_library_path_coordinator`: splits work into batches
  - `scan_library_batch`: processes batch of N artists/albums
  - `finalize_library_scan`: aggregates results, updates stats
- Target: 10x improvement for libraries with 1000+ artists

#### 2.2 MUSE MBID Enrichment Tasks
**Effort:** 2-3 days | **Impact:** Better metadata coverage
- Currently enrichment jobs appear in Redis cache but lack dedicated task infrastructure
- Create standalone `enrichment_tasks.py` with batched processing
- Model after Studio54's fetch_metadata_task pattern
- Add BackgroundHeartbeat for MusicBrainz API calls

#### 2.3 Worker Autoscaling
**Effort:** 1 day | **Impact:** Better resource utilization
- Current: fixed worker count regardless of queue depth
- Add Celery autoscale: `--autoscale=8,2` (max 8, min 2 workers)
- Monitor queue depth, scale workers up during large scan/organize jobs

#### 2.4 Database Connection Resilience
**Effort:** 1 day | **Impact:** Prevents crashes on transient DB issues
- Add connection pool health checks and auto-reconnect
- SQLAlchemy `pool_pre_ping=True` if not already set
- Wrap long-running task DB operations with retry on disconnect

### Priority 3 — Nice to Have

#### 3.1 WebSocket Real-Time Updates
**Effort:** 3-5 days | **Impact:** Better UX (replaces polling)
- Both services currently poll every 5 seconds
- Add FastAPI WebSocket endpoint for job progress
- Frontend: replace `useQuery` polling with WebSocket subscription
- Falls back to polling if WebSocket disconnects
- **Note:** Referenced in nearly every planning doc but never implemented

#### 3.2 Notification System
**Effort:** 3-5 days | **Impact:** Automation-friendly
- Common in *arr apps (Sonarr/Radarr/Lidarr) but missing here
- Webhook support for: download complete, import complete, job failed
- Optional: Discord/Slack/email integrations
- Configuration via Settings page
- DB model: `notification_profiles` with URL, events, enabled flag

#### 3.3 Ponder Batched Refactoring
**Effort:** 3-5 days | **Impact:** Performance for large tag-fix jobs
- Refactor to coordinator-batch-finalize pattern
- Enable parallel fingerprinting across workers
- batch_size=50 per chunk

#### 3.4 MUSE Scan Enhancements (Remaining)
**Effort:** 2-3 days | **Impact:** Incremental improvements
- Checkpoint/resume for interrupted scans (partially done)
- Enhanced progress reporting: phase, throughput, ETA
- Rescan endpoint that respects MBID-validated files
- Database index optimization for large libraries

#### 3.5 Statistics Dashboard
**Effort:** 2-3 days | **Impact:** Visibility
- Studio54: download trends, library growth, quality distribution
- MUSE: scan history, duplicate detection rates, cleanup savings
- Charts using Recharts or similar

#### 3.6 Distributed Tracing (OpenTelemetry)
**Effort:** 5 days | **Impact:** Debugging complex workflows
- Trace requests across service → worker → MusicBrainz API → SABnzbd
- Correlate job IDs with spans
- Export to Jaeger or similar

#### 3.7 Request Caching for MusicBrainz
**Effort:** 1 day | **Impact:** Reduces API calls
- Cache frequently requested artist/album data in Redis
- TTL: 24 hours for artist data, 1 hour for search results
- Invalidate on manual refresh

---

## Architecture Notes

### Service Ports
| Service | Port | Description |
|---------|------|-------------|
| studio54-service | 8010 | FastAPI backend |
| studio54-web | 8009 | React frontend (nginx) |
| studio54-db | 5434 | PostgreSQL |
| studio54-redis | 6381 | Redis |
| studio54-worker | — | Celery worker (no exposed port) |
| muse-service | 8007 | FastAPI backend |
| muse-web | 8006 | React frontend (nginx) |
| muse-db | 5433 | PostgreSQL |
| muse-redis | 6380 | Redis |
| musicbrainz-api-service | 8020 | Shared MusicBrainz proxy |

### Key Files
- **Studio54 Tasks:** `studio54-service/app/tasks/` (sync, download, import, organization, monitoring, search)
- **Studio54 Services:** `studio54-service/app/services/` (sabnzbd_client, associate_and_organize, metadata_writer, musicbrainz_client)
- **Studio54 Shared:** `studio54-service/app/shared_services/` (file_organizer, naming_engine, atomic_file_ops, audit_logger)
- **MUSE Tasks:** `muse-service/app/tasks/` (scan, ponder, enrichment, job_monitor)
- **Latest Migration:** `20260213_0100_030` (add associate/organize job type)

### Deployment
- Always use `./scripts/deploy.sh <service>` or manual `--no-cache` builds
- **Remember to deploy BOTH service AND worker** when changing task code
- `--no-deps` flag needed if ollama has NVIDIA issues

---

## Completed Planning Docs (Archived)

The following files have been moved to `.old/plans/`:

| File | Date | What It Covered |
|------|------|----------------|
| STUDIO54.md | Dec 2025 | Original Studio54 architecture doc (Phases 1-5 complete) |
| STUDIO54.Implementation.Summary.md | Dec 2025 | Phase 1-5 completion report |
| STUDIO54.Jobs.Implementation.Plan.md | Dec 2025 | Jobs system plan (now implemented) |
| STUDIO54.Recommendations.md | Dec 2025 | 12 enhancement recommendations |
| STUDIO54.SCAN.ENHANCEMENT.PLAN.md | Dec 2025 | Scanner refactoring plan |
| BATCHING.QUEUEING.PLAN.md | Dec 2025 | Unified batching architecture plan |
| MUSE.Plan.txt | Nov 2025 | Original 12-phase MUSE roadmap |
| MUSE.Enhancement.Implementation.md | Dec 2025 | Scanner optimization Phase 1 |
| MUSE.Optimization.Recommendations.md | Dec 2025 | 10 optimization recommendations |
| MUSE.Scanner.Improvements.md | Dec 2025 | Two-phase scanning architecture |
| JOB_MONITORING.md | Jan 2026 | MUSE auto-resume watchdog docs |
| MUSICBRAINZ_API_SERVICE.md | Jan 2026 | Centralized MB proxy docs |
| MUSICBRAINZ_INTEGRATION_COMPLETE.md | Jan 2026 | MB integration completion report |
| DUPLICATE_CLEANUP_STATUS.md | Dec 2025 | NFS permission fix for cleanup |
| muse-test-report.md | Dec 2025 | 30/30 test pass report |
| diagnose_picard.md | Dec 2025 | Picard NFS diagnostic |
| PICARD_FIX_SUMMARY.md | Dec 2025 | Picard timeout fix |
| NFS_CONFIGURATION.md | Dec 2025 | NFS mount setup and benchmarks |
| NFS_IMPROVEMENTS_COMPLETE.md | Dec 2025 | NFS auto-health checker |
| scripts/Build a plan to enhance...sty | Feb 2026 | File management requirements prompt |
