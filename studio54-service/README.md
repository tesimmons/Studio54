# Studio54 Service

**Music Acquisition & Library Management System - Backend API Service**

Studio54 is a modern music acquisition and library management system that reimplements Lidarr functionality with native MusicBrainz integration, MUSE library sync, and comprehensive file organization capabilities.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Download Decision Engine](#download-decision-engine)
- [File Organization System](#file-organization-system)
- [Library Import Workflow](#library-import-workflow)
- [MUSE Integration](#muse-integration)
- [Configuration](#configuration)
- [Database Schema](#database-schema)
- [Background Tasks](#background-tasks)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

---

## Overview

Studio54 provides:

- **Direct MusicBrainz Integration** - No broken SkyHook proxy, native API calls with proper rate limiting
- **Lidarr-Style Decision Engine** - Quality-aware release evaluation and download tracking
- **MUSE Library Integration** - Bidirectional sync with MUSE for duplicate prevention
- **SABnzbd Download Automation** - Automatic search, grab, and import workflow
- **Multi-Indexer Support** - Newznab API compatible with any NZB indexer
- **MBID-Based File Organization** - Automatic renaming and folder structure based on MusicBrainz IDs
- **Comprehensive Import Workflow** - 6-phase library import with artist matching and metadata sync

---

## Features

### Core Capabilities

| Feature | Status | Description |
|---------|--------|-------------|
| Artist Management | ✅ | Search, add, monitor artists with MusicBrainz metadata |
| Album Tracking | ✅ | Track wanted/available albums with quality profiles |
| Download Automation | ✅ | Automatic search, quality ranking, and grabbing |
| Decision Engine | ✅ | Lidarr-style release evaluation with specifications |
| Queue Management | ✅ | Full download queue tracking with pause/resume |
| File Organization | ✅ | MBID-based renaming and folder structure |
| Library Import | ✅ | 6-phase import with artist/folder/track matching |
| MUSE Integration | ✅ | Bidirectional sync, duplicate prevention |
| Quality Profiles | ✅ | Configurable quality preferences (FLAC, MP3, etc.) |
| Indexer Management | ✅ | Multi-indexer support with health monitoring |

### Download Decision Engine

The decision engine evaluates releases from indexers using a specification-based system:

- **Quality Specifications** - Prefer FLAC over MP3, enforce minimum bitrates
- **Size Specifications** - Reject releases outside acceptable size ranges
- **Age Specifications** - Prefer newer releases, reject stale content
- **Blacklist Checking** - Avoid previously failed releases
- **Upgrade Detection** - Replace lower quality with higher quality versions

### File Organization

Automatic file management with:

- **MBID Extraction** - Read MusicBrainz IDs from file comments
- **Metadata Validation** - Verify file metadata against MusicBrainz
- **Intelligent Renaming** - Template-based file naming
- **Folder Restructuring** - Organize into Artist/Album (Year) hierarchy
- **Metadata Files** - Create `.mbid.json` in album directories

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Studio54 Architecture                     │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐    │
│  │   React     │────▶│   FastAPI   │────▶│  PostgreSQL │    │
│  │  Frontend   │     │   Backend   │     │   Database  │    │
│  │  (8009)     │     │   (8010)    │     │   (5434)    │    │
│  └─────────────┘     └──────┬──────┘     └─────────────┘    │
│                             │                                │
│                             ▼                                │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐    │
│  │   Celery    │◀───▶│    Redis    │     │ MusicBrainz │    │
│  │   Worker    │     │   (6381)    │     │     API     │    │
│  └─────────────┘     └─────────────┘     └─────────────┘    │
│         │                                       ▲            │
│         ▼                                       │            │
│  ┌─────────────┐     ┌─────────────┐            │            │
│  │  SABnzbd    │     │    MUSE     │────────────┘            │
│  │   Client    │     │   Service   │                         │
│  └─────────────┘     └─────────────┘                         │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Technology Stack

- **FastAPI** - Modern async Python web framework
- **PostgreSQL 15** - Primary database with UUID primary keys
- **Redis 7** - Message broker for Celery tasks
- **Celery** - Distributed task queue for background jobs
- **SQLAlchemy** - ORM with Alembic migrations
- **Fernet Encryption** - Secure API key storage

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Access to MUSE service (optional but recommended)
- SABnzbd instance for downloads
- At least one Newznab-compatible indexer

### Quick Start

```bash
# Enable Studio54 via MasterControl
./mastercontrol studio54 enable

# Start services
./mastercontrol start

# Access web interface
# http://localhost:8009

# Access API documentation
# http://localhost:8010/docs
```

### Manual Docker Deployment

```bash
# Build and start services
docker-compose -f config/docker-compose.yml --profile studio54 up -d

# Run database migrations
docker exec studio54-service alembic upgrade head

# Check service status
docker ps | grep studio54
```

---

## API Reference

### Base URL

```
http://localhost:8010/api/v1
```

### Authentication

Currently uses internal network security. Rate limiting applied to all endpoints.

### Artists API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/artists/search` | POST | Search MusicBrainz for artists |
| `/artists` | GET | List all monitored artists |
| `/artists` | POST | Add artist to monitoring |
| `/artists/{id}` | GET | Get artist details |
| `/artists/{id}` | PATCH | Update artist settings |
| `/artists/{id}` | DELETE | Remove artist |
| `/artists/{id}/sync` | POST | Sync albums from MusicBrainz |
| `/artists/{id}/scan-folder` | POST | Scan and match album folders |
| `/artists/{id}/organize` | POST | Organize artist files |

### Albums API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/albums` | GET | List albums (filterable by status, artist) |
| `/albums/wanted` | GET | Get wanted albums |
| `/albums/calendar` | GET | Upcoming releases |
| `/albums/{id}` | GET | Get album details |
| `/albums/{id}` | PATCH | Update album settings |
| `/albums/{id}/search` | POST | Search indexers for album |
| `/albums/{id}/verify-muse` | POST | Check if album exists in MUSE |
| `/albums/{id}/organize` | POST | Organize album files |

### Search API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/search/album/{album_id}` | POST | Search all indexers for album |
| `/search/album/{album_id}/releases` | GET | Get available releases |
| `/search/grab` | POST | Grab a release for download |
| `/search/pending` | GET | List pending releases (temporarily rejected) |

### Queue API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/queue` | GET | Get download queue status |
| `/queue/blacklist` | GET | Get blacklisted releases |
| `/queue/history` | GET | Get download history |
| `/queue/{id}` | GET | Get specific download details |
| `/queue/{id}` | DELETE | Remove from queue |
| `/queue/{id}/pause` | POST | Pause download |
| `/queue/{id}/resume` | POST | Resume download |
| `/queue/{id}/retry-import` | POST | Retry failed import |
| `/queue/blacklist/{id}` | DELETE | Remove from blacklist |

### Indexers API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/indexers` | GET | List configured indexers |
| `/indexers` | POST | Add new indexer |
| `/indexers/{id}` | GET | Get indexer details |
| `/indexers/{id}` | PATCH | Update indexer |
| `/indexers/{id}` | DELETE | Remove indexer |
| `/indexers/{id}/test` | POST | Test indexer connection |

### Download Clients API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/download-clients` | GET | List download clients |
| `/download-clients` | POST | Add download client |
| `/download-clients/{id}` | GET | Get client details |
| `/download-clients/{id}` | PATCH | Update client |
| `/download-clients/{id}` | DELETE | Remove client |
| `/download-clients/{id}/test` | POST | Test client connection |

### Library API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/library/paths` | GET | List library paths |
| `/library/paths` | POST | Add library path |
| `/library/paths/{id}` | GET | Get path details |
| `/library/paths/{id}` | DELETE | Remove path |
| `/library/paths/{id}/scan` | POST | Start library scan |
| `/library/paths/{id}/import` | POST | Start import workflow |

### File Organization API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/file-organization/library-paths/{id}/organize` | POST | Organize library files |
| `/file-organization/library-paths/{id}/validate` | POST | Validate file structure |
| `/file-organization/library-paths/{id}/fetch-metadata` | POST | Fetch MBIDs from MusicBrainz |
| `/file-organization/library-paths/{id}/validate-mbid` | POST | Verify MBIDs in files |
| `/file-organization/library-paths/{id}/link-files` | POST | Link files to tracks |
| `/file-organization/library-paths/{id}/reindex-albums` | POST | Reindex album detection |
| `/file-organization/library-paths/{id}/verify-audio` | POST | Verify downloaded audio |
| `/file-organization/jobs` | GET | List organization jobs |
| `/file-organization/jobs/{id}` | GET | Get job status |
| `/file-organization/jobs/{id}/resume` | POST | Resume paused job |
| `/file-organization/jobs/{id}/rollback` | POST | Rollback job changes |
| `/file-organization/audit/operations` | GET | View audit log |

### Jobs API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/jobs` | GET | List all jobs |
| `/jobs/{id}` | GET | Get job details |
| `/jobs/{id}/pause` | POST | Pause running job |
| `/jobs/{id}/resume` | POST | Resume paused job |
| `/jobs/{id}/cancel` | POST | Cancel job |
| `/jobs/cleanup-logs` | POST | Cleanup old log files |
| `/jobs/cleanup-logs/preview` | GET | Preview log cleanup |

### MUSE Integration API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/muse/libraries` | GET | List MUSE libraries |
| `/muse/libraries/{id}/stats` | GET | Get library statistics |
| `/muse/verify-album` | POST | Check if album exists in MUSE |
| `/muse/trigger-scan` | POST | Trigger MUSE library scan |
| `/muse/find-missing` | POST | Find albums missing from MUSE |
| `/muse/connection-test` | GET | Test MUSE connectivity |
| `/muse/quality-check/{mbid}` | GET | Check album quality in MUSE |

### System API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | API information |
| `/health` | GET | Health check |
| `/stats` | GET | System statistics |

---

## Download Decision Engine

The Decision Engine evaluates releases from indexers using a Lidarr-style specification system.

### How It Works

1. **Search Phase** - Query indexers for album releases
2. **Parse Phase** - Extract quality, codec, and release info from titles
3. **Evaluate Phase** - Apply specifications to each release
4. **Prioritize Phase** - Rank approved releases by quality score
5. **Grab Phase** - Send best release to download client
6. **Track Phase** - Monitor download progress and status

### Release States

| State | Description |
|-------|-------------|
| `queued` | In download client queue |
| `downloading` | Actively downloading |
| `paused` | Paused in client |
| `import_pending` | Downloaded, ready to import |
| `import_blocked` | Error detected, needs attention |
| `importing` | Currently importing |
| `imported` | Successfully imported |
| `failed` | Permanently failed |
| `ignored` | Ignored by user |

### Quality Ranking

Releases are scored based on quality preference:

| Quality | Priority | Description |
|---------|----------|-------------|
| FLAC | 1 | Lossless audio |
| ALAC | 2 | Apple lossless |
| WAV | 3 | Uncompressed |
| MP3-320 | 4 | 320kbps CBR |
| MP3-V0 | 5 | Variable bitrate ~245kbps |
| AAC-256 | 6 | 256kbps AAC |
| MP3-256 | 7 | 256kbps CBR |
| MP3-192 | 8 | 192kbps CBR |
| Unknown | 9 | Quality not detected |

### Blacklist

Failed releases are blacklisted to prevent re-grabbing:

- Manually removed releases
- Failed imports
- Corrupt or wrong content

**API:** `GET /api/v1/queue/blacklist`

### Download History

Complete audit trail of download events:

- `grabbed` - Release sent to download client
- `import_started` - Import process began
- `imported` - Successfully imported
- `import_failed` - Import failed
- `download_failed` - Download failed
- `deleted` - Removed from queue
- `blacklisted` - Added to blacklist

**API:** `GET /api/v1/queue/history`

---

## File Organization System

### MBID-Based Workflow

1. **Fetch Metadata** - Search MusicBrainz for files without MBIDs
   - Uses artist/title from ID3 tags
   - Writes MBIDs to file Comment field
   - Format: `RecordingMBID:{uuid} | ArtistMBID:{uuid} | ReleaseMBID:{uuid} | ReleaseGroupMBID:{uuid}`

2. **Validate MBID** - Verify MBIDs are in file comments
   - Reads Comment tag from audio files
   - Updates `mbid_in_file` database flag

3. **Link Files** - Connect files to album tracks
   - Matches Recording MBIDs to tracks table
   - Updates track `has_file` and `file_path`

4. **Reindex Albums** - Detect albums/singles from metadata
   - Groups files by Release Group MBID
   - Identifies album type (Album vs Single)

5. **Organize Files** - Move and rename files
   - Calculates target path using naming template
   - Moves files to correct location
   - Creates `.mbid.json` metadata files

6. **Verify Audio** - Check downloaded files
   - Verifies MBIDs in recently downloaded files
   - Configurable time window (default 90 days)

### Naming Templates

**Standard Track:**
```
{Artist Name}/{Album Title} ({Release Year})/{Artist Name} - {Album Title} - {track:00} - {Track Title}.{ext}
```

**Multi-Disc Album:**
```
{Artist Name}/{Album Title} ({Release Year})/{Medium Format} {medium:00}/{Artist Name} - {Album Title} - {track:00} - {Track Title}.{ext}
```

**Example:**
```
Michael Jackson/Thriller (1982)/Michael Jackson - Thriller - 01 - Wanna Be Startin' Somethin'.flac
```

### Organization Options

| Option | Default | Description |
|--------|---------|-------------|
| `dry_run` | false | Preview changes without moving files |
| `create_metadata_files` | true | Create .mbid.json in album folders |
| `only_with_mbid` | true | Skip files without MusicBrainz IDs |
| `only_unorganized` | true | Skip already organized files |

### Safety Features

- **Checksum Validation** - Verify files after move (copy-verify-delete pattern)
- **Max Failures** - Job fails after 5 move failures
- **Batch Processing** - 100 files minimum per batch
- **Audit Trail** - Complete log of all file operations
- **Rollback Capability** - Reverse operations using audit log
- **Log Cleanup** - Automatic removal after 120 days

---

## Library Import Workflow

### 6-Phase Import Process

#### Phase 1: Library Scanning
- Walk directory tree for audio files
- Extract basic metadata (title, artist, album, MBIDs)
- Store in `library_files` table
- Group files by artist name

#### Phase 2: Artist Import & Matching
- Match by MusicBrainz Artist ID (if present)
- Match by normalized artist name
- Search MusicBrainz for unmatched artists
- Create Artist records with MusicBrainz IDs

#### Phase 3: Artist Metadata Sync
- Fetch artist metadata (biography, genres, images)
- Fetch all albums/singles from MusicBrainz
- Create Album and Track records
- Download cover art

#### Phase 4: Folder Structure Matching
- Scan artist root folder for subdirectories
- Match folder names to album titles
- Auto-assign paths for high-confidence matches (≥70%)
- Flag low-confidence matches for review

#### Phase 5: Track File Matching
- Match by MusicBrainz Recording ID (100% accurate)
- Match by track number (95% accurate)
- Match by title similarity + duration (60-95% accurate)
- Update track file paths

#### Phase 6: Metadata Enrichment
- Update track metadata from file tags
- Calculate quality scores
- Verify metadata consistency
- Extract lyrics, ReplayGain, artwork

### Import API

```bash
# Start import
POST /api/v1/library/paths/{id}/import

# Monitor progress
GET /api/v1/library/imports/{id}

# Review unmatched artists
GET /api/v1/library/imports/{id}/unmatched-artists

# Manual artist match
POST /api/v1/library/imports/{id}/match-artist
```

---

## MUSE Integration

### Capabilities

- **Duplicate Prevention** - Check MUSE before downloading
- **Quality Comparison** - Compare existing vs available quality
- **Library Sync** - Sync artist/album data between systems
- **Scan Triggering** - Trigger MUSE scans after imports
- **Missing Detection** - Find albums not in MUSE library

### Configuration

```bash
MUSE_SERVICE_URL=http://muse-service:8005
```

### Usage

```bash
# Check if album exists in MUSE
POST /api/v1/muse/verify-album
{
  "artist_mbid": "...",
  "album_mbid": "...",
  "album_title": "Thriller"
}

# Find missing albums
POST /api/v1/muse/find-missing
{
  "artist_id": "..."
}

# Trigger MUSE scan after download
POST /api/v1/muse/trigger-scan
{
  "library_id": "...",
  "path": "/music/Michael Jackson/Thriller"
}
```

---

## Configuration

### Environment Variables

```bash
# Service Ports
STUDIO54_WEB_PORT=8009
STUDIO54_SERVICE_PORT=8010
STUDIO54_DB_PORT=5434
STUDIO54_REDIS_PORT=6381

# Database
STUDIO54_DB_NAME=studio54_db
STUDIO54_DB_USER=studio54
STUDIO54_DB_PASSWORD=change_me_in_production

# Encryption (auto-generated)
STUDIO54_ENCRYPTION_KEY=<fernet-key>

# SABnzbd
SABNZBD_HOST=192.168.150.99
SABNZBD_PORT=2600
SABNZBD_API_KEY=<from .secrets>
SABNZBD_DOWNLOAD_DIR=/downloads/music

# Music Library
MUSIC_LIBRARY_PATH=/music

# MUSE Integration
MUSE_SERVICE_URL=http://muse-service:8005

# Ollama (AI features)
OLLAMA_URL=http://ollama:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_MODEL=llama3.1:8b

# Import Settings
STUDIO54_ARTIST_MATCH_THRESHOLD=0.85
STUDIO54_FOLDER_MATCH_THRESHOLD=0.70
STUDIO54_TRACK_MATCH_THRESHOLD=0.75
STUDIO54_PREFER_MBID_MATCHING=true

# Performance
STUDIO54_IMPORT_BATCH_SIZE=100
STUDIO54_IMPORT_WORKERS=4
```

---

## Database Schema

### Core Tables

| Table | Description |
|-------|-------------|
| `artists` | Monitored artists with MusicBrainz metadata |
| `albums` | Album releases linked to artists |
| `tracks` | Individual tracks within albums |
| `indexers` | NZB indexer configurations |
| `download_clients` | SABnzbd configurations |
| `quality_profiles` | Download quality preferences |
| `playlists` | User playlists |
| `playlist_tracks` | Playlist track associations |

### Library Tables

| Table | Description |
|-------|-------------|
| `library_paths` | Monitored directories |
| `library_files` | Discovered audio files with metadata |
| `scan_jobs` | Library scan job tracking |
| `library_import_jobs` | Import workflow tracking |

### Download Decision Tables

| Table | Description |
|-------|-------------|
| `tracked_downloads` | Active downloads with state machine |
| `pending_releases` | Temporarily rejected releases for retry |
| `download_history` | History of download events |
| `blacklist` | Permanently rejected releases |

### File Organization Tables

| Table | Description |
|-------|-------------|
| `file_organization_jobs` | Background job tracking |
| `file_operation_audit` | Audit trail for file operations |

---

## Background Tasks

### Scheduled Tasks (Celery Beat)

| Task | Interval | Description |
|------|----------|-------------|
| `search_wanted_albums` | 6 hours | Search indexers for wanted albums |
| `monitor_downloads` | 30 seconds | Check download client status |
| `sync_artist_albums` | Daily | Sync albums from MusicBrainz |
| `cleanup_old_logs` | Daily | Remove logs older than 120 days |
| `health_check_indexers` | 1 hour | Verify indexer connectivity |

### On-Demand Tasks

| Task | Trigger | Description |
|------|---------|-------------|
| `organize_library_files_task` | API call | Organize entire library |
| `organize_artist_files_task` | API call | Organize single artist |
| `organize_album_files_task` | API call | Organize single album |
| `validate_library_structure_task` | API call | Validate file structure |
| `fetch_metadata_task` | API call | Fetch MBIDs from MusicBrainz |
| `validate_mbid_task` | API call | Verify MBIDs in files |
| `link_files_task` | API call | Link files to tracks |
| `reindex_albums_task` | API call | Reindex albums/singles |
| `verify_audio_task` | API call | Verify downloaded audio |
| `import_artist_task` | API call | Import artist from MusicBrainz |
| `scan_library_task` | API call | Scan library path |

---

## Security

### Encryption

- API keys encrypted with Fernet (AES-128 CBC + HMAC)
- Master encryption key in environment variable
- Secrets stored in `.secrets` file (git-ignored)

### Rate Limiting

- All endpoints rate limited
- MusicBrainz API: 1 request/second
- Indexer APIs: Configurable per indexer

### Input Validation

- UUID verification on all ID parameters
- Path traversal prevention
- SQL injection protection via SQLAlchemy

---

## Troubleshooting

### Common Issues

#### MusicBrainz Rate Limiting
```
Error: 503 Service Unavailable
```
**Solution:** MusicBrainz enforces 1 req/sec. The client handles this automatically, but heavy concurrent usage may trigger limits.

#### Download Client Connection Failed
```
Error: Could not connect to SABnzbd
```
**Solution:**
1. Verify SABnzbd is running
2. Check `SABNZBD_HOST` and `SABNZBD_PORT`
3. Verify API key in `.secrets`

#### Files Not Organizing
```
Error: No MBID found in file
```
**Solution:** Run "Fetch Metadata" job first to retrieve MBIDs from MusicBrainz, or use MUSE Ponder for audio fingerprinting.

#### Import Stuck in Progress
```
Status: Running for >1 hour
```
**Solution:**
1. Check Celery worker logs: `docker logs studio54-worker`
2. Check for MusicBrainz rate limiting
3. Pause and resume the job

### Logs

```bash
# Service logs
docker logs studio54-service

# Worker logs
docker logs studio54-worker

# Database logs
docker logs studio54-db
```

### Health Checks

```bash
# API health
curl http://localhost:8010/health

# Database connection
docker exec studio54-service python -c "from app.database import engine; engine.connect(); print('OK')"

# Redis connection
docker exec studio54-redis redis-cli ping
```

---

## Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8010

# Start Celery worker
celery -A app.tasks.celery_app worker --loglevel=info

# Start Celery beat scheduler
celery -A app.tasks.celery_app beat --loglevel=info
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_decision_engine.py
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

---

## Additional Documentation

- [Library Import Workflow](docs/LIBRARY_IMPORT_WORKFLOW.md)
- [Library Scanning](docs/LIBRARY_SCANNING.md)
- [Artist Folder Scanning](docs/ARTIST_FOLDER_SCANNING.md)
- [Decision Engine Details](docs/DECISION_ENGINE.md)
- [MBID Validation System](docs/MBID_VALIDATION_AND_JOB_CHECKPOINT_PLAN.md)

---

## License

Part of the MasterControl Suite
