# Library Import Workflow

Complete end-to-end workflow for importing a music library into Studio54 with full MusicBrainz integration.

## Overview

This workflow takes a directory of music files and fully imports them into Studio54, including:
- Artist matching/creation
- MusicBrainz metadata download
- Album list syncing
- Automatic folder path assignment
- MBID-based track matching
- Complete metadata enrichment

## Workflow Phases

### Phase 1: Library Scanning
**Status**: ✅ Implemented (`scan_coordinator_v2.py`)

1. Walk directory tree to find all audio files
2. Extract basic metadata from each file (title, artist, album, MBIDs)
3. Store in `library_files` table
4. Group files by artist name

**Output**: Library files with extracted metadata

---

### Phase 2: Artist Import & Matching
**Status**: ⚠️  Needs Implementation

For each unique artist found in library files:

1. Check if artist already exists in Studio54:
   - Match by MusicBrainz Artist ID (if present in files)
   - Match by normalized artist name

2. If artist doesn't exist:
   - Search MusicBrainz for artist by name
   - Present matches to user for confirmation
   - Create new Artist record with MusicBrainz ID

3. Link library files to Studio54 artist

**Input**: Library files grouped by artist
**Output**: Studio54 Artist records with MusicBrainz IDs

---

### Phase 3: Artist Metadata Sync
**Status**: ✅ Implemented (`sync_tasks.py::sync_artist_albums`)

For each artist:

1. Fetch artist metadata from MusicBrainz:
   - Biography
   - Genre tags
   - Artist image (from Fanart.tv API)

2. Fetch all albums/singles from MusicBrainz:
   - Album titles
   - Release dates
   - Album types (Album, Single, EP)
   - Cover art URLs

3. Create Album records in Studio54

4. For each album, fetch track listing:
   - Track numbers
   - Track titles
   - Track durations
   - Track MusicBrainz Recording IDs

**Input**: Artist with MusicBrainz ID
**Output**: Artist metadata, Album records, Track records

---

### Phase 4: Folder Structure Matching
**Status**: ✅ Implemented (`artists.py::scan_artist_folder`)

For each artist with albums:

1. Identify artist root folder in library:
   - Check if artist has `root_folder_path`
   - If not, search library for artist directories

2. Scan artist folder for album subdirectories

3. Match subdirectories to albums using fuzzy matching:
   - 100% confidence: Exact match
   - 90%+ confidence: Album title contained in folder name
   - 70-89% confidence: High similarity (auto-assign)
   - 50-69% confidence: Moderate similarity (suggest to user)

4. Assign `custom_folder_path` for high-confidence matches

**Input**: Artist with albums, library directory structure
**Output**: Albums with `custom_folder_path` assigned

---

### Phase 5: Track File Matching
**Status**: ✅ Implemented (`album_file_matcher.py`)

For each album with `custom_folder_path`:

1. Scan album folder for audio files

2. Match files to tracks using priority system:
   - **Phase 0 (100% accurate)**: MusicBrainz Recording ID match
     - Extract Recording MBID from file comment field
     - Match to track.musicbrainz_id
   - **Phase 1 (95% accurate)**: Track number match
   - **Phase 2 (60-95% accurate)**: Title similarity + duration proximity

3. Update `track.file_path` for matched tracks

4. Calculate album statistics:
   - `track_count` (tracks with assigned files)
   - `total_size_bytes`
   - `has_all_files` (track_count == expected tracks)

**Input**: Album with folder path, audio files
**Output**: Tracks with assigned file paths

---

### Phase 6: Metadata Enrichment
**Status**: ⚠️  Partially Implemented

For matched tracks:

1. Update track metadata from file tags:
   - Bitrate, sample rate, format
   - Actual duration from file
   - Quality score calculation

2. Verify metadata consistency:
   - Compare file metadata to MusicBrainz data
   - Flag discrepancies for review

3. Extract additional metadata:
   - Lyrics (if present)
   - ReplayGain values
   - Embedded artwork

**Input**: Tracks with file paths
**Output**: Enriched track metadata

---

### Phase 7: Statistics & Finalization
**Status**: ⚠️  Needs Implementation

1. Calculate artist statistics:
   - Total albums
   - Total singles
   - Total tracks
   - Library coverage percentage

2. Calculate library statistics:
   - Total artists
   - Total albums
   - Total tracks
   - Total size
   - Format distribution

3. Mark import as complete

**Input**: All imported data
**Output**: Updated statistics, completion status

---

## API Endpoints

### 1. Start Library Import
```http
POST /api/v1/library/paths/{library_path_id}/import
```

**Request**:
```json
{
  "auto_match_artists": true,
  "auto_assign_folders": true,
  "auto_match_tracks": true,
  "confidence_threshold": 70
}
```

**Response**:
```json
{
  "import_job_id": "uuid",
  "status": "running",
  "phases": {
    "scanning": "completed",
    "artist_matching": "in_progress",
    "metadata_sync": "pending",
    "folder_matching": "pending",
    "track_matching": "pending",
    "enrichment": "pending",
    "finalization": "pending"
  }
}
```

### 2. Get Import Progress
```http
GET /api/v1/library/imports/{import_job_id}
```

**Response**:
```json
{
  "import_job_id": "uuid",
  "status": "running",
  "current_phase": "metadata_sync",
  "progress_percent": 45.2,
  "statistics": {
    "artists_found": 150,
    "artists_matched": 145,
    "artists_pending": 5,
    "albums_synced": 892,
    "albums_pending": 234,
    "tracks_matched": 8542,
    "tracks_unmatched": 156
  },
  "started_at": "2026-01-10T01:30:00Z",
  "estimated_completion": "2026-01-10T02:15:00Z"
}
```

### 3. Review Unmatched Artists
```http
GET /api/v1/library/imports/{import_job_id}/unmatched-artists
```

**Response**:
```json
{
  "unmatched_artists": [
    {
      "artist_name": "The Beatles",
      "file_count": 245,
      "sample_albums": ["Abbey Road", "Let It Be"],
      "musicbrainz_suggestions": [
        {
          "mbid": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d",
          "name": "The Beatles",
          "disambiguation": "UK rock band",
          "confidence": 98.5
        }
      ]
    }
  ]
}
```

### 4. Match Artist Manually
```http
POST /api/v1/library/imports/{import_job_id}/match-artist
```

**Request**:
```json
{
  "library_artist_name": "The Beatles",
  "musicbrainz_id": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d"
}
```

---

## Integration with Existing Features

### MUSE Integration
After import completion, files can be synced with MUSE:
- Use `/api/v1/muse/find-missing` to identify albums not in MUSE
- Use `/api/v1/muse/verify-album` to check if files match MUSE library

### Download Integration
For missing albums identified:
- Use `/api/v1/artists/{artist_id}/albums` to view wanted albums
- Use download tasks to fetch missing content

### Media Management
After import, use media management rules:
- Rename files according to naming templates
- Move files to organized folder structure
- Apply consistent tagging

---

## Configuration

Environment variables:
```bash
# Artist matching
STUDIO54_ARTIST_MATCH_THRESHOLD=0.85  # 85% similarity required
STUDIO54_AUTO_CREATE_ARTISTS=true     # Auto-create from MusicBrainz

# Folder matching
STUDIO54_FOLDER_MATCH_THRESHOLD=0.70  # 70% confidence for auto-assign
STUDIO54_AUTO_SCAN_ARTIST_FOLDERS=true

# Track matching
STUDIO54_PREFER_MBID_MATCHING=true    # Use MBID when available
STUDIO54_TRACK_MATCH_THRESHOLD=0.75   # 75% title similarity required

# Performance
STUDIO54_IMPORT_BATCH_SIZE=100        # Files per batch
STUDIO54_IMPORT_WORKERS=4             # Parallel workers
```

---

## Example: Complete Import Workflow

```bash
# 1. Add library path
curl -X POST http://localhost:8010/api/v1/library/paths \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/music",
    "name": "Main Music Library"
  }'

# 2. Start library import
curl -X POST http://localhost:8010/api/v1/library/paths/{path_id}/import \
  -H "Content-Type: application/json" \
  -d '{
    "auto_match_artists": true,
    "auto_assign_folders": true,
    "auto_match_tracks": true
  }'

# 3. Monitor progress
curl http://localhost:8010/api/v1/library/imports/{import_job_id}

# 4. Review unmatched artists (if any)
curl http://localhost:8010/api/v1/library/imports/{import_job_id}/unmatched-artists

# 5. Manually match any unmatched artists
curl -X POST http://localhost:8010/api/v1/library/imports/{import_job_id}/match-artist \
  -H "Content-Type: application/json" \
  -d '{
    "library_artist_name": "Artist Name",
    "musicbrainz_id": "mbid-here"
  }'

# 6. View imported artists
curl http://localhost:8010/api/v1/artists

# 7. For each artist, folder paths are auto-assigned and tracks are matched
curl http://localhost:8010/api/v1/artists/{artist_id}
```

---

## Database Schema

### Import Job Tracking
```sql
CREATE TABLE library_import_jobs (
    id UUID PRIMARY KEY,
    library_path_id UUID REFERENCES library_paths(id),
    status VARCHAR(20),  -- pending, running, paused, completed, failed
    current_phase VARCHAR(50),
    progress_percent DECIMAL(5,2),

    -- Statistics
    artists_found INT DEFAULT 0,
    artists_matched INT DEFAULT 0,
    albums_synced INT DEFAULT 0,
    tracks_matched INT DEFAULT 0,
    tracks_unmatched INT DEFAULT 0,

    -- Configuration
    auto_match_artists BOOLEAN DEFAULT TRUE,
    auto_assign_folders BOOLEAN DEFAULT TRUE,
    auto_match_tracks BOOLEAN DEFAULT TRUE,
    confidence_threshold INT DEFAULT 70,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    estimated_completion TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Artist Matching Queue
```sql
CREATE TABLE library_artist_matches (
    id UUID PRIMARY KEY,
    import_job_id UUID REFERENCES library_import_jobs(id),
    library_artist_name VARCHAR(500),
    file_count INT,
    musicbrainz_id VARCHAR(36),  -- NULL if unmatched
    confidence_score DECIMAL(5,2),
    status VARCHAR(20),  -- pending, matched, rejected, manual_review
    matched_artist_id UUID REFERENCES artists(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## Notes

- **Performance**: For large libraries (100K+ files), import can take 1-2 hours
- **Rate Limiting**: MusicBrainz API limited to 1 request/second (enforced in client)
- **Caching**: Artist/album metadata cached to reduce API calls
- **Resumability**: Import jobs can be paused and resumed
- **Rollback**: Failed imports can be rolled back (files remain in library)
- **Idempotency**: Re-running import on same library is safe (updates existing records)

---

## Troubleshooting

### Artists Not Matching
- Check MusicBrainz ID in file tags
- Verify artist name normalization (remove "The", articles)
- Lower `STUDIO54_ARTIST_MATCH_THRESHOLD` if too strict
- Use manual matching endpoint

### Folders Not Matching
- Check folder naming convention matches album titles
- Verify `confidence_threshold` setting
- Review matches with 50-69% confidence for manual assignment

### Tracks Not Matching
- Verify MBID present in file comment field (MUSE Ponder format)
- Check track numbers in file tags
- Ensure album folder path is correctly assigned
- Review unmatched tracks for manual assignment

### Slow Import
- Increase `STUDIO54_IMPORT_WORKERS` for more parallelization
- Reduce `STUDIO54_IMPORT_BATCH_SIZE` if memory constrained
- Check MusicBrainz API rate limiting
- Monitor Celery worker performance
