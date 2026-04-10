# Studio54 Implementation Plan
## Comprehensive Enhancement Roadmap

**Created:** 2026-01-19
**Status:** Ready for Implementation
**Scope:** Multi-session implementation plan

---

## Executive Summary

This plan addresses gaps between current Studio54 functionality and desired behavior for a complete music library management system with automatic file organization, MBID-based matching, and comprehensive job management.

---

## Current State Analysis

### What Already Exists (DO NOT REWRITE)

| Component | Location | Function |
|-----------|----------|----------|
| **Library Scanning** | `scan_coordinator_v2.py`, `fast_ingest_tasks.py` | Walk directories, extract metadata, index files |
| **File Import** | `LibraryFile` model | Store file info with MusicBrainz IDs |
| **Artist/Album Sync** | `sync_tasks.py` | Fetch artist discography from MusicBrainz |
| **MBID Extraction** | `_extract_mbids_from_files()` | Parse MBIDs from file comments into DB |
| **MusicBrainz Client** | `musicbrainz_client.py` | Search recordings, artists, albums |
| **File Organization** | `organization_tasks.py`, `FileOrganizer` | Rename/move files to standard structure |
| **NamingEngine** | `naming_template_engine.py` | Generate paths: `Artist/Album (Year)/Track.ext` |
| **AtomicFileOps** | `shared_services/atomic_file_ops.py` | Safe copy-verify-delete operations |
| **AuditLogger** | `shared_services/audit_logger.py` | Log all file operations |
| **EnhancedImportService** | `enhanced_import_service.py` | Lidarr-style album import |
| **Quality Detector** | `quality_detector.py` | Score audio quality (format, bitrate) |
| **Track Model** | `track.py` | Links to files via `file_path`, `has_file` |
| **Job Cleanup** | `monitoring_tasks.py` | Delete old JobState records |
| **6-Phase Import** | `import_tasks.py` | Orchestrated library import workflow |

### What Needs Modification

| Component | Current State | Required Change |
|-----------|--------------|-----------------|
| **Batch Size** | 50-100 files | Minimum 100 with detailed batch logging |
| **.mbid.json Creation** | Optional | Mandatory with error handling (log/alert, continue) |
| **File Moves** | Has backup option | Remove backup, validate move, fail if >5 failures |
| **fetch_metadata_task** | Updates DB only | Also write metadata to audio files |
| **Download Import** | Basic file placement | Full Artist/Album organization + rename |
| **Log Cleanup** | Deletes DB records only | Also delete log files older than 120 days |
| **Cleanup Retention** | 30 days | 120 days |

### What Needs to Be Created

| Component | Purpose |
|-----------|---------|
| **MetadataWriter Service** | Write MBID and tags to audio file comments |
| **mbid_in_file Column** | Track if MBID exists in file (not just DB) |
| **is_organized Column** | Track if file has been organized |
| **MBID Validation Job** | Verify MBID in file comments, update DB flag |
| **File Linking Job** | Link files with MBID to album tracks |
| **Album Reindex Job** | Reindex albums/singles, update statistics |
| **Audio Verification Job** | Verify downloaded audio matches expected (90 days) |
| **Job Buttons on Detail Pages** | Artist/Album specific job triggers |
| **Comprehensive README** | Document schema, jobs, usage |

---

## Implementation Phases

### Phase 1: Database Schema & Core Services

**Priority:** Critical (Foundation for all other work)

#### 1.1 Database Migration - Add Tracking Columns

Create: `alembic/versions/YYYYMMDD_add_file_tracking_columns.py`

```python
def upgrade():
    # Add columns to library_files
    op.add_column('library_files',
        sa.Column('mbid_in_file', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('library_files',
        sa.Column('is_organized', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('library_files',
        sa.Column('mbid_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('library_files',
        sa.Column('organization_status', sa.String(50), nullable=True, server_default='unprocessed'))

    # Add indexes
    op.create_index('idx_library_files_mbid_in_file', 'library_files', ['mbid_in_file'])
    op.create_index('idx_library_files_is_organized', 'library_files', ['is_organized'])
```

Update: `app/models/library.py` - Add new columns to LibraryFile model

#### 1.2 MetadataWriter Service

Create: `app/services/metadata_writer.py`

```python
class MetadataWriter:
    """Write metadata and MBIDs to audio file tags"""

    def write_mbids(self, file_path: str, mbids: dict) -> bool:
        """
        Write MusicBrainz IDs to file comments field

        Format in comments:
        MUSICBRAINZ_TRACKID=<recording_mbid>
        MUSICBRAINZ_ALBUMID=<release_mbid>
        MUSICBRAINZ_ARTISTID=<artist_mbid>
        MUSICBRAINZ_RELEASEGROUPID=<release_group_mbid>
        """

    def write_metadata(self, file_path: str, metadata: dict) -> bool:
        """
        Write full metadata to file tags

        Updates: title, artist, album, track_number, disc_number, year, genre
        """

    def verify_mbid_in_file(self, file_path: str) -> dict:
        """
        Check if MBIDs exist in file comments

        Returns: {has_mbid: bool, mbids: dict}
        """
```

Uses `mutagen` library for format-specific tag writing (ID3 for MP3, Vorbis for FLAC/OGG, etc.)

---

### Phase 2: Metadata Jobs Enhancement

**Priority:** High

#### 2.1 Update fetch_metadata_task

Modify: `app/tasks/organization_tasks.py`

Current behavior: Searches MusicBrainz, updates LibraryFile records in DB
New behavior: Also writes metadata to file using MetadataWriter

```python
@shared_task
def fetch_metadata_task(job_id: str):
    # ... existing code ...

    for file in files_without_mbid:
        # Search MusicBrainz
        recordings = mb_client.search_recording(artist, title, album)

        if recordings:
            best_match = recordings[0]

            # UPDATE DB (existing)
            library_file.musicbrainz_trackid = best_match['id']
            # ...

            # NEW: Write to file
            metadata_writer = MetadataWriter()
            success = metadata_writer.write_mbids(file.file_path, {
                'recording_mbid': best_match['id'],
                'artist_mbid': best_match.get('artist_mbid'),
                'release_mbid': best_match.get('release_mbid'),
                'release_group_mbid': best_match.get('release_group_mbid')
            })

            if success:
                library_file.mbid_in_file = True
                library_file.mbid_verified_at = datetime.now(timezone.utc)
                job.files_renamed += 1  # Track successful writes
            else:
                job_logger.log_warning(f"Failed to write MBID to file: {file.file_path}")
                job.files_failed += 1
```

#### 2.2 Create MBID Validation Job

Create: New task in `app/tasks/organization_tasks.py`

```python
@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def validate_mbid_in_files_task(self, job_id: str, library_path_id: str):
    """
    Validate that MBIDs exist in file comments and update DB flags

    Purpose: Ensure mbid_in_file flag accurately reflects file state

    Process:
    1. Get all files where mbid_in_file is NULL or False
    2. For each file, check if MBID exists in comments
    3. If yes: Set mbid_in_file = True, update musicbrainz_* fields if missing
    4. If no: Keep mbid_in_file = False, add to list for fetch_metadata job
    5. Create report of files needing MBID fetch
    """
```

#### 2.3 Update Batch Size to 100

Modify batch_size in all file processing loops:
- `_extract_mbids_from_files()`: batch_size = 100
- `fetch_metadata_task()`: batch_size = 100
- `organize_library_files_task()`: batch_size = 100

Add batch logging:
```python
if (i + 1) % batch_size == 0:
    job_logger.log_info(f"Batch {(i + 1) // batch_size}: Processed {i + 1}/{total_files} files")
    db.commit()  # Commit each batch
```

---

### Phase 3: File Linking & Album Management

**Priority:** High

#### 3.1 File Linking Job

Create: `app/tasks/organization_tasks.py`

```python
@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def link_files_to_tracks_task(self, job_id: str, library_path_id: str = None, artist_id: str = None):
    """
    Link LibraryFiles to Track records based on MBID

    Process:
    1. Get files with musicbrainz_trackid (Recording MBID)
    2. For each file, find Track with matching musicbrainz_id
    3. Update Track.file_path and Track.has_file = True
    4. Update LibraryFile.is_organized = True
    5. Log linked vs unlinked statistics

    Can be scoped to:
    - Entire library (library_path_id)
    - Single artist (artist_id)
    """
```

#### 3.2 Album Reindex Job

Create: `app/tasks/organization_tasks.py`

```python
@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def reindex_albums_task(self, job_id: str, library_path_id: str = None):
    """
    Reindex albums and singles based on file metadata

    Process:
    1. Scan all LibraryFiles for unique album/artist combinations
    2. For each album:
       a. Count tracks with files vs total tracks
       b. Determine if album or single (track count)
       c. Update album.status, album.type
    3. Update statistics:
       - Albums with all files
       - Albums with partial files
       - Albums with no files
       - Singles identified
    4. Create .mbid.json in each album directory

    Single detection: album.tracks.count() == 1 or <= 3 tracks
    """
```

#### 3.3 Make .mbid.json Mandatory

Modify: `organize_library_files_task()` and related functions

```python
def create_album_metadata_file(album_dir: str, album_data: dict, job_logger) -> bool:
    """
    Create .mbid.json file in album directory - MANDATORY

    On failure: Log error, add to alert queue, continue processing
    """
    try:
        metadata = {
            "version": "1.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "album": {
                "title": album_data['title'],
                "artist": album_data['artist'],
                "artist_mbid": album_data.get('artist_mbid'),
                "album_mbid": album_data.get('release_mbid'),
                "release_group_mbid": album_data.get('release_group_mbid'),
                "release_year": album_data.get('year'),
                "track_count": album_data.get('track_count', 0)
            },
            "tracks": album_data.get('tracks', [])
        }

        mbid_file = Path(album_dir) / '.mbid.json'
        with open(mbid_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        job_logger.log_info(f"Created .mbid.json: {mbid_file}")
        return True

    except Exception as e:
        job_logger.log_error(f"ALERT: Failed to create .mbid.json in {album_dir}: {e}")
        # Add to alert queue for notification
        add_alert(f"Failed to create metadata file: {album_dir}", severity="warning")
        return False  # Continue processing, don't fail job
```

---

### Phase 4: File Operations & Downloads

**Priority:** High

#### 4.1 Update File Move Logic

Modify: `app/shared_services/file_organizer.py`

```python
class FileOrganizer:
    def __init__(self, ...):
        self.max_move_failures = 5
        self.move_failure_count = 0

    def organize_track_file(self, track_context, job_logger, job) -> FileOperation:
        """
        Organize a single track file

        Changes:
        - NO backup option (removed)
        - Validate move succeeded (verify destination exists, checksum match)
        - Track failures, fail job if > 5 failures
        """
        try:
            # Generate target path
            target_path = self.naming_engine.generate_path(track_context)

            if track_context.file_path == target_path:
                return FileOperation(skipped=True, reason="Already organized")

            # Move file (copy + verify + delete)
            success = self.atomic_ops.move_file(
                source=track_context.file_path,
                destination=target_path,
                verify_checksum=True  # MANDATORY verification
            )

            if not success:
                self.move_failure_count += 1
                job_logger.log_error(f"ALERT: Move failed for {track_context.file_path}")

                if self.move_failure_count > self.max_move_failures:
                    raise MoveFailureThresholdExceeded(
                        f"More than {self.max_move_failures} move operations failed. Job aborted."
                    )

                return FileOperation(failed=True, error="Move verification failed")

            return FileOperation(success=True, destination=target_path)

        except Exception as e:
            self.move_failure_count += 1
            if self.move_failure_count > self.max_move_failures:
                raise
            return FileOperation(failed=True, error=str(e))
```

#### 4.2 Update Download Import

Modify: `app/services/enhanced_import_service.py`

```python
def import_album(self, album: Album, source_directory: str) -> dict:
    """
    Import downloaded album to organized library structure

    Enhanced behavior:
    1. Detect audio files in source_directory
    2. Match to album tracks by filename/metadata
    3. Generate target paths using NamingEngine
    4. Move files to Artist/Album (Year)/Track.ext structure
    5. Write metadata to files (title, artist, album, track#)
    6. Update Track.file_path and Track.has_file
    7. Create .mbid.json in album directory
    8. Clean up empty source directory
    """
```

#### 4.3 Create Audio Verification Job

Create: `app/tasks/verification_tasks.py`

```python
@shared_task(bind=True, soft_time_limit=7200, time_limit=7260)
def verify_downloaded_audio_task(self, job_id: str, days: int = 90):
    """
    Verify audio integrity of files downloaded within the past N days

    Process:
    1. Query DownloadQueue for completed downloads in date range
    2. For each downloaded file:
       a. Verify file exists at expected path
       b. Extract audio fingerprint (optional: AcoustID integration)
       c. Verify file is playable (try to read audio frames)
       d. Verify metadata matches expected values
    3. Report:
       - Files verified OK
       - Files missing
       - Files corrupted
       - Files with mismatched metadata

    Note: Full AcoustID fingerprint matching requires external service setup
    """

    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        job_logger = JobLogger(job_id)

        # Get downloads from past N days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        downloads = db.query(DownloadQueue).filter(
            DownloadQueue.status == DownloadStatus.COMPLETED,
            DownloadQueue.completed_at >= cutoff
        ).all()

        verified = 0
        missing = 0
        corrupted = 0

        for download in downloads:
            album = db.query(Album).filter(Album.id == download.album_id).first()
            if not album:
                continue

            for track in album.tracks:
                if not track.file_path or not track.has_file:
                    continue

                # Verify file exists
                if not os.path.exists(track.file_path):
                    job_logger.log_error(f"Missing file: {track.file_path}")
                    missing += 1
                    continue

                # Verify file is readable
                try:
                    metadata = MetadataExtractor.extract(track.file_path)
                    if metadata:
                        verified += 1
                    else:
                        job_logger.log_warning(f"Could not read metadata: {track.file_path}")
                        corrupted += 1
                except Exception as e:
                    job_logger.log_error(f"Corrupted file: {track.file_path}: {e}")
                    corrupted += 1

        job.files_processed = verified + missing + corrupted
        job.files_renamed = verified  # Using renamed as "verified" count
        job.files_failed = corrupted + missing

        return {
            "verified": verified,
            "missing": missing,
            "corrupted": corrupted,
            "total_checked": len(downloads)
        }
```

---

### Phase 5: Cleanup & UI Updates

**Priority:** Medium

#### 5.1 Log File Cleanup

Modify: `app/tasks/monitoring_tasks.py`

```python
@shared_task(name="app.tasks.monitoring_tasks.cleanup_old_logs")
def cleanup_old_logs(days_to_keep: int = 120):
    """
    Delete log files older than N days

    Cleans up:
    - Job log files in /app/logs/jobs/
    - Summary report files
    - Any orphaned log files
    """
    import os
    from pathlib import Path

    log_dir = Path("/app/logs/jobs")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    deleted_count = 0

    if log_dir.exists():
        for log_file in log_dir.glob("*.log"):
            try:
                file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
                if file_mtime < cutoff:
                    log_file.unlink()
                    deleted_count += 1
            except Exception as e:
                logger.warning(f"Failed to delete log file {log_file}: {e}")

    logger.info(f"Cleaned up {deleted_count} log files older than {days_to_keep} days")
    return {"deleted_count": deleted_count, "retention_days": days_to_keep}


# Update cleanup_old_jobs to use 120 days
@shared_task(name="app.tasks.monitoring_tasks.cleanup_old_jobs")
def cleanup_old_jobs(days_to_keep: int = 120):  # Changed from 30 to 120
    # ... existing code ...
```

Add to Celery beat schedule:
```python
'cleanup-old-logs': {
    'task': 'app.tasks.monitoring_tasks.cleanup_old_logs',
    'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM
    'kwargs': {'days_to_keep': 120}
},
```

#### 5.2 Update File Management Page

Modify: `studio54-web/src/pages/FileManagement.tsx`

Add buttons for all jobs:
- **Validate MBIDs** - validate_mbid_in_files_task
- **Fetch Missing MBIDs** - fetch_metadata_task
- **Link Files to Tracks** - link_files_to_tracks_task
- **Reindex Albums** - reindex_albums_task
- **Verify Downloads** - verify_downloaded_audio_task
- **Organize Library** - organize_library_files_task (existing)
- **Validate Structure** - validate_library_structure_task (existing)

#### 5.3 Add Job Buttons to Detail Pages

Modify: `studio54-web/src/pages/ArtistDetail.tsx`

Add buttons:
- **Organize Artist Files** - organize_artist_files_task (existing)
- **Link Artist Files** - link_files_to_tracks_task (artist_id param)
- **Reindex Artist Albums** - reindex_albums_task (artist_id param)

Modify: `studio54-web/src/pages/AlbumDetail.tsx`

Add buttons:
- **Link Album Files** - Match and link files to tracks
- **Verify Album Files** - Verify all track files exist and are valid

---

### Phase 6: Documentation

**Priority:** Medium

#### 6.1 Update MasterControl README

Add section about Studio54:

```markdown
## Studio54 - Music Library Manager

Studio54 is a Lidarr-style music library management system integrated into MasterControl.

**Features:**
- Library scanning and file indexing
- MusicBrainz metadata integration
- Automatic file organization
- Download management with SABnzbd/NZBGet
- Album/Single detection and tracking

**Enable Studio54:**
```bash
./mastercontrol studio54 enable
```

**Access:**
- Web UI: http://localhost:8009
- API: http://localhost:8010

See `studio54-service/README.md` for detailed documentation.
```

#### 6.2 Create Comprehensive Studio54 README

Create: `studio54-service/README.md`

Include:
- Overview and purpose
- Architecture diagram
- Database schema documentation
- API endpoints reference
- Job types and triggers
- File Management page usage
- Configuration options
- Troubleshooting guide

---

## Database Schema (for README)

### Core Tables

```
┌─────────────────────────────────────────────────────────────────┐
│                        LIBRARY MANAGEMENT                        │
├─────────────────────────────────────────────────────────────────┤
│ library_paths          │ Root directories to scan                │
│ library_files          │ Indexed audio files with metadata       │
│ scan_jobs             │ Library scan operations                  │
│ library_import_jobs   │ 6-phase import operations               │
│ library_artist_matches│ Artist matching results                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        MUSIC CATALOG                             │
├─────────────────────────────────────────────────────────────────┤
│ artists               │ Artist records with MusicBrainz IDs      │
│ albums                │ Album records with status tracking       │
│ tracks                │ Track records linked to files            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        FILE MANAGEMENT                           │
├─────────────────────────────────────────────────────────────────┤
│ file_organization_jobs│ Organization/validation job tracking    │
│ file_operation_audit  │ Audit trail for all file operations     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        DOWNLOADS                                 │
├─────────────────────────────────────────────────────────────────┤
│ download_clients      │ SABnzbd/NZBGet configurations           │
│ indexers              │ Newznab indexer configurations          │
│ download_queue        │ Download queue with status              │
└─────────────────────────────────────────────────────────────────┘
```

### Key Fields

**library_files (Enhanced)**
```sql
id                      UUID PRIMARY KEY
file_path               TEXT NOT NULL UNIQUE
musicbrainz_trackid     VARCHAR(36)      -- Recording MBID
musicbrainz_albumid     VARCHAR(36)      -- Release MBID
musicbrainz_artistid    VARCHAR(36)      -- Artist MBID
mbid_in_file            BOOLEAN          -- NEW: MBID exists in file comments
is_organized            BOOLEAN          -- NEW: File has been organized
organization_status     VARCHAR(50)      -- NEW: unprocessed/validated/organized
```

**tracks**
```sql
id                      UUID PRIMARY KEY
album_id                UUID REFERENCES albums(id)
title                   TEXT NOT NULL
musicbrainz_id          VARCHAR(36)      -- Recording MBID
track_number            INTEGER
has_file                BOOLEAN          -- File linked
file_path               TEXT             -- Path to audio file
```

---

## Job Types Summary

| Job Type | Trigger | Purpose |
|----------|---------|---------|
| **validate_mbid_in_files** | File Management page | Verify MBIDs in file comments |
| **fetch_metadata** | After validation or manual | Search MusicBrainz, write to files |
| **link_files_to_tracks** | File Management page | Link files to Track records by MBID |
| **reindex_albums** | File Management page | Reindex albums/singles from files |
| **verify_downloaded_audio** | Scheduled or manual | Verify recent downloads |
| **organize_library_files** | File Management page | Organize files to standard structure |
| **validate_library_structure** | File Management page | Validate naming conventions |
| **cleanup_old_logs** | Scheduled (daily) | Remove logs older than 120 days |

---

## Implementation Order

1. **Phase 1** (Foundation) - Database schema, MetadataWriter service
2. **Phase 2** (Metadata) - Enhanced fetch_metadata, MBID validation job
3. **Phase 3** (Linking) - File linking job, album reindex job
4. **Phase 4** (Operations) - Move validation, download import, audio verification
5. **Phase 5** (Cleanup & UI) - Log cleanup, UI buttons
6. **Phase 6** (Docs) - README updates

Each phase can be implemented in a separate session. Test thoroughly after each phase before proceeding.

---

## Testing Checklist

- [ ] Database migration applies cleanly
- [ ] MetadataWriter successfully writes to MP3, FLAC, OGG files
- [ ] fetch_metadata_task writes to files AND updates DB
- [ ] MBID validation job correctly detects MBIDs in file comments
- [ ] File linking job correctly links files to tracks
- [ ] Album reindex correctly identifies singles vs albums
- [ ] Move validation catches failures and fails job at threshold
- [ ] Download import organizes files correctly
- [ ] Audio verification detects missing/corrupted files
- [ ] Log cleanup removes old files
- [ ] All job buttons appear on File Management page
- [ ] Artist/Album detail pages have job action buttons
- [ ] Documentation is accurate and complete
