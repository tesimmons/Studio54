# Library Scanning

This document describes what happens when you run a library scan in Studio54.

## Overview

A library scan indexes all audio files in a configured library path, extracting metadata and storing it in the database. The scan process ensures the database accurately reflects the files on disk.

## What Happens During a Library Scan

### Phase 1: Directory Walking
1. **Traverse directory tree** - Recursively walk all directories in the library path
2. **Skip non-audio files** - Filter based on supported formats (MP3, FLAC, M4A, OGG, WAV, etc.)
3. **Skip system files** - Ignore hidden files (starting with `.`), resource forks (`._*`), and system files

### Phase 2: Orphan Detection & Cleanup
1. **Compare disk vs database** - Identify files that exist in the database but no longer exist on disk
2. **Remove orphaned records** - Delete database records for files that have been moved or deleted
3. **Log removed files** - Track count of removed files in scan statistics

### Phase 3: File Processing
For each audio file found on disk:

1. **Check if file exists in database**
   - If exists and unchanged (same modification time): Skip
   - If exists but modified: Update metadata
   - If not in database: Add as new file

2. **Extract metadata** (for new/updated files)
   - Basic info: title, artist, album, track number, disc number, year
   - Duration and bitrate
   - File format and codec info
   - MusicBrainz IDs (if present in tags)

3. **Batch operations**
   - Insert/update files in batches of 100 for performance
   - Commit to database every 500 files
   - Update progress in scan job record

### Phase 4: Image Fetching (Optional)
1. **Fetch album art** - For files with MusicBrainz album IDs, fetch cover art from MusicBrainz
2. **Fetch artist images** - For files with MusicBrainz artist IDs, fetch artist images

### Phase 5: Statistics Update
1. **Update library statistics** - Total files, total size
2. **Mark scan complete** - Set scan job status to completed
3. **Trigger background processing** - Start Phase 2 processing for full metadata enrichment

## Scan Types

### Full Scan
- Processes all files regardless of modification time
- Useful for initial indexing or after major library changes
- Takes longer but ensures complete accuracy

### Incremental Scan (Default)
- Only processes new or modified files
- Skips files with unchanged modification time
- Much faster for regular maintenance scans
- Still detects and removes orphaned files

## Scan Statistics

After a scan completes, the following statistics are available:

| Statistic | Description |
|-----------|-------------|
| `files_scanned` | Total number of audio files found on disk |
| `files_added` | New files added to database |
| `files_updated` | Existing files that were re-indexed (modified) |
| `files_skipped` | Unchanged files that were skipped |
| `files_removed` | Orphaned files removed from database |
| `files_failed` | Files that failed to process (errors) |

## V2 Scanner Architecture

Studio54 uses a two-phase scanning architecture for large libraries:

### Phase 1: Fast Ingestion
- Parallel batch processing across Celery workers
- Minimal metadata extraction for speed
- Can process 100K+ files in 2-5 minutes

### Phase 2: Background Processing
- Full metadata extraction
- Image fetching from MusicBrainz
- Hash calculation for duplicate detection
- Runs asynchronously after Phase 1 completes

## API Endpoints

### Start a Scan
```bash
POST /api/v1/library/{library_id}/scan
```

Query parameters:
- `incremental` (bool, default: true) - Use incremental scanning
- `fetch_images` (bool, default: true) - Fetch album/artist images

### Check Scan Status
```bash
GET /api/v1/jobs/{scan_job_id}
```

### Cancel a Scan
```bash
POST /api/v1/jobs/{scan_job_id}/cancel
```

## Supported Audio Formats

- MP3 (.mp3)
- FLAC (.flac)
- AAC/M4A (.m4a, .aac)
- OGG Vorbis (.ogg)
- WAV (.wav)
- AIFF (.aiff, .aif)
- WMA (.wma)
- APE (.ape)
- OPUS (.opus)

## Troubleshooting

### Scan is slow
- Use incremental scanning for regular maintenance
- Check if library is on a slow network share
- Consider scanning during off-peak hours

### Files not being detected
- Verify file format is supported
- Check file permissions
- Ensure files are not hidden (starting with `.`)

### Orphaned files not being removed
- Ensure running a full directory scan (not artist/album specific)
- Check scan job log for errors
- Verify database connectivity
