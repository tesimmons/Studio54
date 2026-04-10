# Download Decision Engine

The Studio54 Download Decision Engine is a Lidarr-style system for evaluating, tracking, and managing music downloads from NZB indexers.

## Overview

The Decision Engine provides:

- **Intelligent Release Evaluation** - Score and rank releases based on quality specifications
- **Full Download Lifecycle** - Track downloads from grab through import
- **State Machine Architecture** - Reliable progress tracking with pause/resume
- **Blacklist Management** - Prevent re-grabbing of failed releases
- **History Tracking** - Complete audit trail of all download events

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Decision Engine Flow                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Search  │───▶│  Parse   │───▶│ Evaluate │───▶│ Prioritize│  │
│  │ Indexers │    │ Releases │    │  Specs   │    │  & Rank   │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                        │         │
│                                                        ▼         │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │  Import  │◀───│  Monitor │◀───│  Track   │◀───│   Grab   │  │
│  │  Files   │    │ Progress │    │ Download │    │ Release  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Models

### TrackedDownload

Tracks a download through its complete lifecycle.

```python
class TrackedDownloadState(str, Enum):
    QUEUED = "queued"              # In download client queue
    DOWNLOADING = "downloading"    # Actively downloading
    PAUSED = "paused"              # Paused in client
    IMPORT_PENDING = "import_pending"  # Downloaded, ready to import
    IMPORT_BLOCKED = "import_blocked"  # Error detected, needs attention
    IMPORTING = "importing"        # Currently importing
    IMPORTED = "imported"          # Successfully imported
    FAILED = "failed"              # Permanently failed
    IGNORED = "ignored"            # Ignored by user
```

**State Machine:**
```
QUEUED ─────────────▶ DOWNLOADING ─────────────▶ IMPORT_PENDING
   │                      │                            │
   │                      │                            ▼
   │                      ▼                      IMPORTING ──▶ IMPORTED
   │                   PAUSED                          │
   │                                                   ▼
   └──────────────────────────────────────────▶ IMPORT_BLOCKED
                                                       │
                                                       ▼
                                               FAILED / IGNORED
```

### ReleaseInfo

Parsed release information from indexer search results.

```python
@dataclass
class ReleaseInfo:
    # Identification
    title: str              # Release title from indexer
    guid: str               # Unique identifier
    indexer_id: str         # Source indexer
    indexer_name: str       # Indexer name for display

    # Download info
    download_url: str       # NZB download URL
    info_url: str           # Release info page
    size: int               # Size in bytes
    age_days: int           # Days since publication
    publish_date: datetime  # Publication timestamp

    # Quality info (parsed from title)
    quality: str            # FLAC, MP3-320, etc.
    codec: str              # Audio codec
    bitrate: int            # Bitrate in kbps
    sample_rate: int        # Sample rate in Hz
    bit_depth: int          # Bit depth (16, 24)

    # Release metadata
    artist_name: str        # Parsed artist
    album_name: str         # Parsed album
    year: int               # Release year
    release_group: str      # Release group/source

    # Protocol
    protocol: str           # usenet or torrent
```

### DownloadDecision

Result of evaluating a release against specifications.

```python
@dataclass
class DownloadDecision:
    remote_album: RemoteAlbum
    rejections: List[Rejection]

    @property
    def approved(self) -> bool:
        return len(self.rejections) == 0

    @property
    def temporarily_rejected(self) -> bool:
        return all(r.type == RejectionType.TEMPORARY for r in self.rejections)

    @property
    def permanently_rejected(self) -> bool:
        return any(r.type == RejectionType.PERMANENT for r in self.rejections)
```

---

## Release Evaluation

### Quality Specifications

Releases are evaluated against quality preferences:

| Quality | Priority | Detected By |
|---------|----------|-------------|
| FLAC | 1 | "FLAC" in title |
| ALAC | 2 | "ALAC" in title |
| WAV | 3 | "WAV" in title |
| MP3-320 | 4 | "320", "CBR 320" |
| MP3-V0 | 5 | "V0", "VBR" |
| AAC-256 | 6 | "AAC", "256" |
| MP3-256 | 7 | "256" without AAC |
| MP3-192 | 8 | "192" |
| Unknown | 9 | No quality detected |

### Size Specifications

Reject releases outside acceptable size ranges:

```python
# Example size spec
{
    "min_size_mb": 50,      # Reject if < 50MB
    "max_size_mb": 2000,    # Reject if > 2GB
    "min_size_per_track": 5  # Reject if < 5MB per track
}
```

### Age Specifications

Prefer newer releases:

```python
# Example age spec
{
    "max_age_days": 365,    # Reject if > 1 year old
    "prefer_recent": True   # Boost score for recent releases
}
```

### Blacklist Checking

Check releases against blacklist before approval:

```python
# Blacklist check
if release.guid in blacklisted_guids:
    return Rejection(
        reason="Release is blacklisted",
        type=RejectionType.PERMANENT
    )
```

---

## Download Queue API

### Get Queue Status

```http
GET /api/v1/queue
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `state` | enum | Filter by state |
| `album_id` | uuid | Filter by album |
| `artist_id` | uuid | Filter by artist |
| `include_completed` | bool | Include completed downloads |
| `limit` | int | Max results (default 100) |

**Response:**
```json
{
  "count": 5,
  "items": [
    {
      "id": "uuid",
      "title": "Artist - Album (2024) [FLAC]",
      "state": "downloading",
      "progress": 45.5,
      "size_bytes": 524288000,
      "downloaded_bytes": 238600000,
      "eta_seconds": 120,
      "album_id": "uuid",
      "album_title": "Album Name",
      "artist_id": "uuid",
      "artist_name": "Artist Name",
      "quality": "FLAC",
      "indexer": "nzbgeek",
      "grabbed_at": "2026-02-06T12:00:00Z",
      "error_message": null,
      "status_messages": null,
      "output_path": "/downloads/Artist - Album"
    }
  ]
}
```

### Get Download Details

```http
GET /api/v1/queue/{download_id}
```

**Response:**
```json
{
  "id": "uuid",
  "title": "Artist - Album (2024) [FLAC]",
  "state": "downloading",
  "progress": 45.5,
  "size_bytes": 524288000,
  "downloaded_bytes": 238600000,
  "eta_seconds": 120,
  "album": {
    "id": "uuid",
    "title": "Album Name",
    "status": "downloading"
  },
  "artist": {
    "id": "uuid",
    "name": "Artist Name"
  },
  "release": {
    "guid": "release-guid",
    "quality": "FLAC",
    "indexer": "nzbgeek"
  },
  "download_client_id": "uuid",
  "download_id": "SABnzbd_nzo_id",
  "output_path": "/downloads/Artist - Album",
  "grabbed_at": "2026-02-06T12:00:00Z",
  "completed_at": null,
  "imported_at": null,
  "error_message": null,
  "status_messages": null
}
```

### Remove from Queue

```http
DELETE /api/v1/queue/{download_id}
```

**Request Body:**
```json
{
  "remove_from_client": true,
  "blacklist": false,
  "blacklist_reason": null
}
```

**Response:**
```json
{
  "status": "removed",
  "download_id": "uuid",
  "blacklisted": false
}
```

### Pause Download

```http
POST /api/v1/queue/{download_id}/pause
```

**Response:**
```json
{
  "status": "paused",
  "download_id": "uuid"
}
```

### Resume Download

```http
POST /api/v1/queue/{download_id}/resume
```

**Response:**
```json
{
  "status": "resumed",
  "download_id": "uuid"
}
```

### Retry Import

```http
POST /api/v1/queue/{download_id}/retry-import
```

**Response:**
```json
{
  "status": "import_queued",
  "download_id": "uuid",
  "message": "Import will be retried"
}
```

---

## Blacklist API

### Get Blacklist

```http
GET /api/v1/queue/blacklist
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `album_id` | uuid | Filter by album |
| `artist_id` | uuid | Filter by artist |
| `limit` | int | Max results (default 100) |
| `offset` | int | Pagination offset |

**Response:**
```json
{
  "total": 15,
  "items": [
    {
      "id": "uuid",
      "release_guid": "indexer-release-guid",
      "release_title": "Artist - Album (2024) [FLAC]",
      "album_id": "uuid",
      "artist_id": "uuid",
      "reason": "Import failed: corrupt file",
      "added_at": "2026-02-05T10:00:00Z"
    }
  ]
}
```

### Remove from Blacklist

```http
DELETE /api/v1/queue/blacklist/{blacklist_id}
```

**Response:**
```json
{
  "status": "removed",
  "blacklist_id": "uuid"
}
```

---

## Download History API

### Get History

```http
GET /api/v1/queue/history
```

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | enum | Filter by event type |
| `album_id` | uuid | Filter by album |
| `artist_id` | uuid | Filter by artist |
| `limit` | int | Max results (default 100) |
| `offset` | int | Pagination offset |

**Event Types:**
- `grabbed` - Release sent to download client
- `import_started` - Import process began
- `imported` - Successfully imported
- `import_failed` - Import failed
- `download_failed` - Download failed
- `deleted` - Removed from queue
- `blacklisted` - Added to blacklist

**Response:**
```json
{
  "total": 250,
  "items": [
    {
      "id": "uuid",
      "event_type": "grabbed",
      "release_guid": "indexer-release-guid",
      "release_title": "Artist - Album (2024) [FLAC]",
      "album_id": "uuid",
      "artist_id": "uuid",
      "quality": "FLAC",
      "source": "nzbgeek",
      "message": null,
      "occurred_at": "2026-02-06T12:00:00Z"
    }
  ]
}
```

---

## Search and Grab API

### Search for Album

```http
POST /api/v1/search/album/{album_id}
```

Searches all enabled indexers for the specified album.

**Response:**
```json
{
  "album_id": "uuid",
  "album_title": "Album Name",
  "artist_name": "Artist Name",
  "releases_found": 15,
  "approved_releases": 8,
  "search_duration_ms": 2500
}
```

### Get Available Releases

```http
GET /api/v1/search/album/{album_id}/releases
```

Returns all releases found with their approval status.

**Response:**
```json
{
  "releases": [
    {
      "title": "Artist - Album (2024) [FLAC]",
      "guid": "release-guid",
      "quality": "FLAC",
      "size": 524288000,
      "size_display": "500 MB",
      "age_days": 5,
      "indexer": "nzbgeek",
      "approved": true,
      "rejections": [],
      "score": 95
    },
    {
      "title": "Artist - Album (2024) [MP3-320]",
      "guid": "release-guid-2",
      "quality": "MP3-320",
      "size": 157286400,
      "size_display": "150 MB",
      "age_days": 10,
      "indexer": "nzbplanet",
      "approved": true,
      "rejections": [],
      "score": 75
    },
    {
      "title": "Artist - Album [MP3-128]",
      "guid": "release-guid-3",
      "quality": "MP3-128",
      "size": 52428800,
      "size_display": "50 MB",
      "age_days": 180,
      "indexer": "nzbsu",
      "approved": false,
      "rejections": [
        {"reason": "Quality below minimum", "type": "permanent"}
      ],
      "score": 0
    }
  ]
}
```

### Grab Release

```http
POST /api/v1/search/grab
```

**Request Body:**
```json
{
  "release_guid": "release-guid",
  "album_id": "uuid",
  "download_client_id": "uuid"
}
```

**Response:**
```json
{
  "status": "grabbed",
  "download_id": "uuid",
  "message": "Release sent to download client"
}
```

### Get Pending Releases

```http
GET /api/v1/search/pending
```

Returns temporarily rejected releases that may be retried later.

**Response:**
```json
{
  "count": 3,
  "items": [
    {
      "id": "uuid",
      "album_id": "uuid",
      "album_title": "Album Name",
      "release_guid": "release-guid",
      "release_title": "Artist - Album (2024) [FLAC]",
      "added_at": "2026-02-06T10:00:00Z",
      "retry_after": "2026-02-06T11:00:00Z",
      "retry_count": 1,
      "rejection_reasons": ["Rate limited by indexer"]
    }
  ]
}
```

---

## Database Schema

### tracked_downloads

```sql
CREATE TABLE tracked_downloads (
    id UUID PRIMARY KEY,
    download_client_id UUID REFERENCES download_clients(id),
    download_id VARCHAR(255) NOT NULL,  -- ID in download client

    album_id UUID REFERENCES albums(id),
    artist_id UUID REFERENCES artists(id),
    indexer_id UUID REFERENCES indexers(id),

    title VARCHAR(500) NOT NULL,
    output_path VARCHAR(1000),
    state tracked_download_state NOT NULL DEFAULT 'queued',

    -- Release info
    release_guid VARCHAR(255),
    release_quality VARCHAR(50),
    release_indexer VARCHAR(100),

    -- Progress
    size_bytes BIGINT,
    downloaded_bytes BIGINT DEFAULT 0,
    progress_percent FLOAT DEFAULT 0,
    eta_seconds INTEGER,

    -- Timestamps
    grabbed_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    imported_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,

    -- Error handling
    error_message VARCHAR(1000),
    status_messages JSONB
);

CREATE INDEX idx_tracked_downloads_state ON tracked_downloads(state);
CREATE INDEX idx_tracked_downloads_album ON tracked_downloads(album_id);
CREATE INDEX idx_tracked_downloads_artist ON tracked_downloads(artist_id);
```

### pending_releases

```sql
CREATE TABLE pending_releases (
    id UUID PRIMARY KEY,
    album_id UUID REFERENCES albums(id),
    artist_id UUID REFERENCES artists(id),
    indexer_id UUID REFERENCES indexers(id),

    release_guid VARCHAR(255) NOT NULL,
    release_title VARCHAR(500) NOT NULL,
    release_data JSONB NOT NULL,  -- Full ReleaseInfo

    added_at TIMESTAMP WITH TIME ZONE,
    retry_after TIMESTAMP WITH TIME ZONE,
    rejection_reasons JSONB,
    retry_count INTEGER DEFAULT 0,

    UNIQUE(album_id, release_guid)
);

CREATE INDEX idx_pending_releases_album ON pending_releases(album_id);
CREATE INDEX idx_pending_releases_retry ON pending_releases(retry_after);
```

### download_history

```sql
CREATE TABLE download_history (
    id UUID PRIMARY KEY,
    album_id UUID REFERENCES albums(id),
    artist_id UUID REFERENCES artists(id),
    indexer_id UUID REFERENCES indexers(id),
    download_client_id UUID REFERENCES download_clients(id),
    tracked_download_id UUID REFERENCES tracked_downloads(id),

    release_guid VARCHAR(255),
    release_title VARCHAR(500),

    event_type download_event_type NOT NULL,
    quality VARCHAR(50),
    source VARCHAR(100),

    message VARCHAR(1000),
    data JSONB,

    occurred_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_download_history_album ON download_history(album_id);
CREATE INDEX idx_download_history_event ON download_history(event_type);
CREATE INDEX idx_download_history_occurred ON download_history(occurred_at);
```

### blacklist

```sql
CREATE TABLE blacklist (
    id UUID PRIMARY KEY,
    album_id UUID REFERENCES albums(id),
    artist_id UUID REFERENCES artists(id),
    indexer_id UUID REFERENCES indexers(id),

    release_guid VARCHAR(255) NOT NULL,
    release_title VARCHAR(500),

    reason VARCHAR(500),
    source_title VARCHAR(500),

    added_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_blacklist_album ON blacklist(album_id);
CREATE INDEX idx_blacklist_guid ON blacklist(release_guid);
```

---

## Background Tasks

### Download Monitoring

The `monitor_downloads` task runs every 30 seconds to:

1. Query download clients for active download status
2. Update `TrackedDownload` progress fields
3. Detect completed downloads and transition to `import_pending`
4. Detect failed downloads and transition to `failed`
5. Trigger import tasks for completed downloads

### Wanted Album Search

The `search_wanted_albums` task runs every 6 hours to:

1. Query albums with status `WANTED`
2. Search all enabled indexers for each album
3. Evaluate releases against specifications
4. Auto-grab best approved release (if configured)
5. Record pending releases for manual review

---

## Integration with MUSE

Before grabbing a release, Studio54 checks MUSE for existing copies:

```python
# Pre-grab MUSE check
muse_check = muse_client.verify_album(
    artist_mbid=album.artist.mbid,
    album_mbid=album.mbid,
    album_title=album.title
)

if muse_check.exists:
    if muse_check.quality >= requested_quality:
        return Rejection(
            reason=f"Already exists in MUSE at {muse_check.quality} quality",
            type=RejectionType.PERMANENT
        )
```

---

## Error Handling

### Download Failures

When a download fails:

1. State transitions to `failed`
2. Error message stored in `error_message` field
3. History event recorded with `download_failed` type
4. Release optionally blacklisted

### Import Failures

When import fails:

1. State transitions to `import_blocked`
2. Error message stored with status messages
3. History event recorded with `import_failed` type
4. User can retry or blacklist

### Retry Logic

For temporary failures (rate limiting, network issues):

1. Release added to `pending_releases` table
2. `retry_after` timestamp set based on retry count
3. Scheduled task retries after delay
4. Max 3 retries before permanent rejection

---

## Configuration

```bash
# Download monitoring
STUDIO54_DOWNLOAD_MONITOR_INTERVAL=30  # seconds

# Search settings
STUDIO54_AUTO_SEARCH_INTERVAL=21600    # 6 hours
STUDIO54_AUTO_GRAB_ENABLED=true        # Auto-grab best release

# Quality settings
STUDIO54_MIN_QUALITY=MP3-256           # Minimum acceptable quality
STUDIO54_PREFERRED_QUALITY=FLAC        # Preferred quality

# Blacklist
STUDIO54_AUTO_BLACKLIST_ON_FAIL=true   # Auto-blacklist failed imports
STUDIO54_BLACKLIST_RETENTION_DAYS=365  # Days to keep blacklist entries
```

---

## Troubleshooting

### Downloads Stuck in Queue

```
State: queued (for >1 hour)
```

**Check:**
1. Download client connectivity: `POST /api/v1/download-clients/{id}/test`
2. Download client queue: Check SABnzbd web interface
3. Worker logs: `docker logs studio54-worker`

### Import Blocked

```
State: import_blocked
Error: No matching album folder found
```

**Solution:**
1. Verify album folder exists in library
2. Check folder naming matches expectations
3. Retry import: `POST /api/v1/queue/{id}/retry-import`

### Release Keeps Getting Rejected

**Check:**
1. View rejection reasons: `GET /api/v1/search/album/{id}/releases`
2. Check quality profile settings
3. Verify size limits aren't too restrictive
4. Check blacklist: `GET /api/v1/queue/blacklist`

### History Not Recording

**Check:**
1. Database connectivity
2. Worker task completion
3. Check for database transaction errors in logs
