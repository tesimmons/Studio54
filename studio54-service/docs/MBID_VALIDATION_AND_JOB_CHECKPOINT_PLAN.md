# MBID Validation & Job Checkpoint System Plan
## Studio54 Enhancement - Prevent Reprocessing & Improve Accuracy

**Created:** 2026-01-26
**Status:** Planning
**Priority:** High - Critical for data integrity and efficiency

---

## Executive Summary

This plan addresses three critical issues:

1. **Fetch Metadata Inefficiency** - API calls made without checking existing MBIDs, no match validation
2. **Missing MBID Validation Job** - No way to verify file metadata matches MusicBrainz data
3. **Job Interruption Loss** - System updates/restarts cause complete reprocessing

**Goals:**
- Reduce unnecessary MusicBrainz API calls by 50%+
- Add confidence scoring and match validation
- Create VALIDATE_MBID_METADATA job to correct file metadata
- Implement universal checkpoint/resume for all jobs
- Enable hot-reload updates without job interruption

---

## Part 1: Fix Fetch Metadata Issues

### 1.1 Pre-Check MBID Before API Call

**Current Problem:** Files with `mbid_in_file=False` in DB but actually having MBID in file still trigger MusicBrainz API calls.

**Solution:** Add file check before API call.

```python
# In fetch_metadata_task, BEFORE MusicBrainz search:

# Step 1: Check if file already has MBID (defensive check)
existing_mbid = MetadataWriter.verify_mbid_in_file(file_path)
if existing_mbid.get('has_mbid'):
    # Update database to match reality
    library_file.mbid_in_file = True
    library_file.musicbrainz_trackid = existing_mbid.get('recording_mbid')
    library_file.musicbrainz_artistid = existing_mbid.get('artist_mbid')
    library_file.musicbrainz_albumid = existing_mbid.get('release_mbid')
    library_file.musicbrainz_releasegroupid = existing_mbid.get('release_group_mbid')
    files_skipped_already_has_mbid += 1
    job_logger.log_info(f"SKIPPED (already has MBID): {file_path}")
    continue  # Skip to next file, NO API call

# Step 2: Only now make MusicBrainz API call
recordings = mb_client.search_recording(...)
```

**Impact:** Eliminates wasted API calls for files that already have MBID.

---

### 1.2 Add Confidence Scoring

**Current Problem:** Takes first MusicBrainz result blindly without knowing match quality.

**Solution:** Implement match confidence scoring.

```python
# New file: studio54-service/app/services/mbid_confidence_scorer.py

class MBIDConfidenceScorer:
    """Score MusicBrainz match confidence against file metadata"""

    WEIGHTS = {
        'title_exact': 30,
        'title_fuzzy': 15,
        'artist_exact': 25,
        'artist_fuzzy': 12,
        'album_exact': 15,
        'album_fuzzy': 8,
        'duration_match': 15,  # Within 5 seconds
        'duration_close': 8,   # Within 15 seconds
    }

    @classmethod
    def score_match(
        cls,
        file_metadata: dict,
        mb_recording: dict,
        file_duration_ms: Optional[int] = None
    ) -> MatchResult:
        """
        Score how well a MusicBrainz recording matches file metadata

        Returns:
            MatchResult with:
                - score: 0-100
                - confidence: 'high' (80+), 'medium' (60-79), 'low' (<60)
                - details: dict of individual scores
                - warnings: list of potential issues
        """
        score = 0
        details = {}
        warnings = []

        # Title comparison
        file_title = normalize(file_metadata.get('title', ''))
        mb_title = normalize(mb_recording.get('title', ''))

        if file_title == mb_title:
            score += cls.WEIGHTS['title_exact']
            details['title'] = 'exact'
        elif fuzzy_ratio(file_title, mb_title) > 85:
            score += cls.WEIGHTS['title_fuzzy']
            details['title'] = 'fuzzy'
        else:
            details['title'] = 'mismatch'
            warnings.append(f"Title mismatch: '{file_title}' vs '{mb_title}'")

        # Artist comparison
        file_artist = normalize(file_metadata.get('artist', ''))
        mb_artist = normalize(get_artist_name(mb_recording))

        if file_artist == mb_artist:
            score += cls.WEIGHTS['artist_exact']
            details['artist'] = 'exact'
        elif fuzzy_ratio(file_artist, mb_artist) > 85:
            score += cls.WEIGHTS['artist_fuzzy']
            details['artist'] = 'fuzzy'
        else:
            details['artist'] = 'mismatch'
            warnings.append(f"Artist mismatch: '{file_artist}' vs '{mb_artist}'")

        # Album comparison (if available)
        file_album = normalize(file_metadata.get('album', ''))
        mb_releases = mb_recording.get('releases', [])
        album_matched = False

        for release in mb_releases:
            mb_album = normalize(release.get('title', ''))
            if file_album == mb_album:
                score += cls.WEIGHTS['album_exact']
                details['album'] = 'exact'
                album_matched = True
                break
            elif fuzzy_ratio(file_album, mb_album) > 80:
                score += cls.WEIGHTS['album_fuzzy']
                details['album'] = 'fuzzy'
                album_matched = True
                break

        if not album_matched and file_album:
            details['album'] = 'mismatch'
            warnings.append(f"Album not found in releases: '{file_album}'")

        # Duration comparison (critical for avoiding false matches)
        mb_duration_ms = mb_recording.get('length')
        if file_duration_ms and mb_duration_ms:
            diff_seconds = abs(file_duration_ms - mb_duration_ms) / 1000

            if diff_seconds <= 5:
                score += cls.WEIGHTS['duration_match']
                details['duration'] = 'exact'
            elif diff_seconds <= 15:
                score += cls.WEIGHTS['duration_close']
                details['duration'] = 'close'
            else:
                details['duration'] = 'mismatch'
                warnings.append(f"Duration mismatch: {diff_seconds:.0f}s difference")

                # Large duration diff is a red flag
                if diff_seconds > 60:
                    warnings.append("CRITICAL: Duration differs by >60s - likely wrong recording")

        # Check for live/remix/remaster indicators
        mb_disambiguation = mb_recording.get('disambiguation', '').lower()
        if any(x in mb_disambiguation for x in ['live', 'remix', 'remaster', 'demo', 'acoustic']):
            warnings.append(f"Recording has disambiguation: '{mb_disambiguation}'")

        # Determine confidence level
        if score >= 80:
            confidence = 'high'
        elif score >= 60:
            confidence = 'medium'
        else:
            confidence = 'low'

        return MatchResult(
            score=score,
            confidence=confidence,
            details=details,
            warnings=warnings,
            recording_mbid=mb_recording.get('id'),
            mb_title=mb_recording.get('title'),
            mb_artist=get_artist_name(mb_recording)
        )
```

---

### 1.3 Integrate Confidence Scoring into Fetch Metadata

```python
# In fetch_metadata_task, after MusicBrainz search:

if recordings and len(recordings) > 0:
    # Score all matches
    scored_matches = []
    for recording in recordings:
        match_result = MBIDConfidenceScorer.score_match(
            file_metadata={'title': title, 'artist': artist, 'album': album},
            mb_recording=recording,
            file_duration_ms=metadata.get('duration_ms')
        )
        scored_matches.append(match_result)

    # Sort by score descending
    scored_matches.sort(key=lambda x: x.score, reverse=True)
    best_match = scored_matches[0]

    # Log confidence and warnings
    job_logger.log_info(
        f"Best match: {best_match.mb_artist} - {best_match.mb_title} "
        f"(confidence: {best_match.confidence}, score: {best_match.score})"
    )

    if best_match.warnings:
        for warning in best_match.warnings:
            job_logger.log_warning(f"  - {warning}")

    # Handle based on confidence level
    if best_match.confidence == 'high':
        # Safe to write automatically
        write_result = MetadataWriter.write_mbids(...)
        files_updated += 1

    elif best_match.confidence == 'medium':
        # Write but flag for review
        write_result = MetadataWriter.write_mbids(...)
        library_file.needs_mbid_review = True
        library_file.mbid_confidence_score = best_match.score
        files_updated += 1
        job_logger.log_info(f"MEDIUM confidence - flagged for review: {file_path}")

    else:  # low confidence
        # Don't write, add to review queue
        library_file.needs_mbid_review = True
        library_file.mbid_confidence_score = best_match.score
        library_file.mbid_review_reason = "; ".join(best_match.warnings)
        files_low_confidence += 1
        job_logger.log_warning(f"LOW confidence - skipped, needs manual review: {file_path}")
```

---

### 1.4 Database Schema Updates for Confidence Tracking

```sql
-- Add columns to library_files table
ALTER TABLE library_files ADD COLUMN mbid_confidence_score INTEGER;
ALTER TABLE library_files ADD COLUMN needs_mbid_review BOOLEAN DEFAULT FALSE;
ALTER TABLE library_files ADD COLUMN mbid_review_reason TEXT;
ALTER TABLE library_files ADD COLUMN mbid_reviewed_at TIMESTAMP;
ALTER TABLE library_files ADD COLUMN mbid_reviewed_by TEXT;

-- Index for finding files needing review
CREATE INDEX idx_library_files_needs_review ON library_files(needs_mbid_review) WHERE needs_mbid_review = TRUE;
CREATE INDEX idx_library_files_confidence ON library_files(mbid_confidence_score);
```

---

## Part 2: New VALIDATE_MBID_METADATA Job

### 2.1 Purpose

This job reads MBID from file, looks it up on MusicBrainz, and:
1. Validates the MBID is correct for the file
2. Updates file metadata to match MusicBrainz canonical data
3. Corrects database registration

### 2.2 Job Type Definition

```python
class JobType(str, enum.Enum):
    # ... existing types ...
    VALIDATE_MBID_METADATA = "validate_mbid_metadata"  # NEW: Validate and correct metadata
```

### 2.3 Task Implementation

```python
# In organization_tasks.py

@shared_task(bind=True, soft_time_limit=14400, time_limit=14460)
def validate_mbid_metadata_task(self, job_id: str):
    """
    Validate MBIDs in files and correct metadata to match MusicBrainz.

    For each file WITH MBID:
    1. Read MBID from file comment
    2. Lookup recording on MusicBrainz by MBID
    3. Compare file metadata with MusicBrainz data
    4. If mismatch: Update file tags to match MusicBrainz
    5. Update database with canonical metadata

    This ensures all tagged files have correct, canonical metadata.
    """
    db = SessionLocal()
    checkpoint_manager = JobCheckpointManager(job_id)

    try:
        job = get_job(db, job_id)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.last_heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        job_logger = JobLogger(job_id=job_id)

        # Resume from checkpoint if exists
        checkpoint = checkpoint_manager.load_checkpoint()
        start_index = checkpoint.get('last_processed_index', 0)

        if start_index > 0:
            job_logger.log_info(f"RESUMING from checkpoint at index {start_index}")

        # Get files WITH MBID to validate
        files_to_validate = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == job.library_path_id,
            LibraryFile.mbid_in_file == True
        ).order_by(LibraryFile.id).all()

        total_files = len(files_to_validate)
        job.files_total = total_files
        db.commit()

        job_logger.log_phase_start("MBID Metadata Validation", f"Validating {total_files} files")

        mb_client = MusicBrainzClient()

        stats = {
            'validated': 0,
            'metadata_updated': 0,
            'already_correct': 0,
            'mbid_invalid': 0,
            'errors': 0
        }

        for i, library_file in enumerate(files_to_validate):
            # Skip already processed (resume support)
            if i < start_index:
                continue

            # Check for pause request
            if checkpoint_manager.is_pause_requested():
                job_logger.log_info(f"PAUSE requested at index {i}")
                checkpoint_manager.save_checkpoint({
                    'last_processed_index': i,
                    'stats': stats
                })
                job.status = JobStatus.PAUSED
                job.current_action = f"Paused at {i}/{total_files}"
                db.commit()
                return {'status': 'paused', 'index': i}

            try:
                file_path = library_file.file_path

                # Progress and heartbeat
                job.files_processed = i + 1
                job.progress_percent = (i + 1) / total_files * 100
                job.current_action = f"Validating metadata: {i + 1}/{total_files}"
                job.current_file_path = file_path

                if (i + 1) % 10 == 0:
                    job.last_heartbeat_at = datetime.now(timezone.utc)
                    db.commit()
                    # Save checkpoint every 100 files
                    if (i + 1) % 100 == 0:
                        checkpoint_manager.save_checkpoint({
                            'last_processed_index': i + 1,
                            'stats': stats
                        })

                # Step 1: Read MBID from file
                mbid_data = MetadataWriter.verify_mbid_in_file(file_path)
                recording_mbid = mbid_data.get('recording_mbid')

                if not recording_mbid:
                    job_logger.log_warning(f"No recording MBID in file: {file_path}")
                    library_file.mbid_in_file = False
                    stats['mbid_invalid'] += 1
                    continue

                # Step 2: Lookup recording on MusicBrainz
                mb_recording = mb_client.get_recording_details(recording_mbid)
                time.sleep(1.0)  # Rate limit

                if not mb_recording:
                    job_logger.log_warning(f"MBID not found on MusicBrainz: {recording_mbid}")
                    library_file.mbid_validation_status = 'invalid_mbid'
                    stats['mbid_invalid'] += 1
                    continue

                # Step 3: Extract canonical metadata from MusicBrainz
                canonical = {
                    'title': mb_recording.get('title'),
                    'artist': get_artist_name(mb_recording),
                    'album': get_release_title(mb_recording),
                    'track_number': get_track_number(mb_recording),
                    'disc_number': get_disc_number(mb_recording),
                    'year': get_release_year(mb_recording),
                    'duration_ms': mb_recording.get('length')
                }

                # Step 4: Read current file metadata
                file_metadata = MetadataExtractor.extract(file_path)

                # Step 5: Compare and identify differences
                differences = []
                for field in ['title', 'artist', 'album']:
                    file_value = normalize(file_metadata.get(field, ''))
                    canonical_value = normalize(canonical.get(field, ''))
                    if file_value != canonical_value:
                        differences.append({
                            'field': field,
                            'file_value': file_metadata.get(field),
                            'canonical_value': canonical.get(field)
                        })

                # Step 6: Update file if differences found
                if differences:
                    job_logger.log_info(f"Updating metadata for: {file_path}")
                    for diff in differences:
                        job_logger.log_info(
                            f"  {diff['field']}: '{diff['file_value']}' -> '{diff['canonical_value']}'"
                        )

                    # Write corrected metadata to file
                    write_result = MetadataWriter.write_metadata(
                        file_path=file_path,
                        title=canonical.get('title'),
                        artist=canonical.get('artist'),
                        album=canonical.get('album'),
                        track_number=canonical.get('track_number'),
                        disc_number=canonical.get('disc_number'),
                        year=canonical.get('year'),
                        overwrite=True  # Overwrite with canonical data
                    )

                    if write_result.success:
                        stats['metadata_updated'] += 1
                        library_file.mbid_validation_status = 'corrected'
                        library_file.mbid_validated_at = datetime.now(timezone.utc)
                    else:
                        job_logger.log_error(f"Failed to write: {write_result.error}")
                        stats['errors'] += 1
                else:
                    stats['already_correct'] += 1
                    library_file.mbid_validation_status = 'valid'
                    library_file.mbid_validated_at = datetime.now(timezone.utc)

                # Step 7: Update database with canonical values
                library_file.title = canonical.get('title')
                library_file.artist = canonical.get('artist')
                library_file.album = canonical.get('album')
                library_file.track_number = canonical.get('track_number')
                library_file.disc_number = canonical.get('disc_number')
                library_file.year = canonical.get('year')

                stats['validated'] += 1

            except Exception as e:
                job_logger.log_error(f"Error validating {file_path}: {e}")
                stats['errors'] += 1
                continue

        # Complete
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.files_renamed = stats['metadata_updated']
        job.files_failed = stats['errors']
        job.current_action = (
            f"Complete: {stats['validated']} validated, "
            f"{stats['metadata_updated']} updated, "
            f"{stats['already_correct']} already correct"
        )
        db.commit()

        checkpoint_manager.clear_checkpoint()

        return stats

    except Exception as e:
        # ... error handling ...
    finally:
        db.close()
```

---

## Part 3: Universal Job Checkpoint/Resume System

### 3.1 Core Checkpoint Manager

```python
# New file: studio54-service/app/services/job_checkpoint_manager.py

import json
import os
import redis
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path

class JobCheckpointManager:
    """
    Manage job checkpoints for safe pause/resume functionality.

    Uses Redis for checkpoint storage (fast, persistent with RDB).
    Supports all job types.
    """

    CHECKPOINT_PREFIX = "job_checkpoint:"
    PAUSE_REQUEST_PREFIX = "job_pause_request:"
    CHECKPOINT_DIR = "/app/checkpoints"

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.redis_client = redis.from_url(os.getenv('REDIS_URL', 'redis://studio54-redis:6379/0'))
        self.checkpoint_key = f"{self.CHECKPOINT_PREFIX}{job_id}"
        self.pause_key = f"{self.PAUSE_REQUEST_PREFIX}{job_id}"

        # Ensure checkpoint directory exists
        Path(self.CHECKPOINT_DIR).mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, checkpoint_data: Dict[str, Any]) -> bool:
        """
        Save checkpoint data for job.

        Checkpoint includes:
        - last_processed_index: Index of last successfully processed item
        - stats: Current statistics
        - timestamp: When checkpoint was saved
        - Additional job-specific data
        """
        checkpoint = {
            'job_id': self.job_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'data': checkpoint_data
        }

        try:
            # Save to Redis (primary - fast)
            self.redis_client.set(
                self.checkpoint_key,
                json.dumps(checkpoint),
                ex=86400 * 7  # Expire after 7 days
            )

            # Also save to file (backup - survives Redis restart)
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint, f, indent=2)

            return True
        except Exception as e:
            logger.error(f"Failed to save checkpoint for job {self.job_id}: {e}")
            return False

    def load_checkpoint(self) -> Dict[str, Any]:
        """Load checkpoint data if exists"""
        try:
            # Try Redis first
            data = self.redis_client.get(self.checkpoint_key)
            if data:
                checkpoint = json.loads(data)
                return checkpoint.get('data', {})

            # Fallback to file
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            if checkpoint_file.exists():
                with open(checkpoint_file, 'r') as f:
                    checkpoint = json.load(f)
                    return checkpoint.get('data', {})

            return {}
        except Exception as e:
            logger.error(f"Failed to load checkpoint for job {self.job_id}: {e}")
            return {}

    def clear_checkpoint(self) -> bool:
        """Clear checkpoint after successful completion"""
        try:
            self.redis_client.delete(self.checkpoint_key)
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            if checkpoint_file.exists():
                checkpoint_file.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to clear checkpoint for job {self.job_id}: {e}")
            return False

    def request_pause(self) -> bool:
        """Request job to pause at next safe point"""
        try:
            self.redis_client.set(self.pause_key, "1", ex=3600)  # Expire in 1 hour
            return True
        except Exception as e:
            logger.error(f"Failed to request pause for job {self.job_id}: {e}")
            return False

    def is_pause_requested(self) -> bool:
        """Check if pause has been requested"""
        try:
            return self.redis_client.exists(self.pause_key) > 0
        except Exception:
            return False

    def clear_pause_request(self) -> bool:
        """Clear pause request (after pausing or resuming)"""
        try:
            self.redis_client.delete(self.pause_key)
            return True
        except Exception:
            return False

    def has_checkpoint(self) -> bool:
        """Check if checkpoint exists"""
        try:
            if self.redis_client.exists(self.checkpoint_key):
                return True
            checkpoint_file = Path(self.CHECKPOINT_DIR) / f"{self.job_id}.json"
            return checkpoint_file.exists()
        except Exception:
            return False
```

---

### 3.2 Base Task Mixin with Checkpoint Support

```python
# New file: studio54-service/app/tasks/checkpoint_mixin.py

from celery import Task
from app.services.job_checkpoint_manager import JobCheckpointManager

class CheckpointableTask(Task):
    """
    Base task class with checkpoint/pause support.

    Usage:
        @shared_task(bind=True, base=CheckpointableTask)
        def my_task(self, job_id: str):
            # Initialize checkpoint manager
            self.init_checkpoint(job_id)

            for i, item in enumerate(items):
                # Check for pause
                if self.should_pause():
                    self.save_checkpoint_and_pause({'index': i, 'stats': stats})
                    return {'status': 'paused'}

                # Process item...

                # Save checkpoint periodically
                if i % 100 == 0:
                    self.save_checkpoint({'index': i, 'stats': stats})

            # Clear checkpoint on completion
            self.clear_checkpoint()
    """

    _checkpoint_manager: Optional[JobCheckpointManager] = None
    _job_id: Optional[str] = None

    def init_checkpoint(self, job_id: str):
        """Initialize checkpoint manager for this task"""
        self._job_id = job_id
        self._checkpoint_manager = JobCheckpointManager(job_id)

    def load_checkpoint(self) -> Dict[str, Any]:
        """Load existing checkpoint data"""
        if self._checkpoint_manager:
            return self._checkpoint_manager.load_checkpoint()
        return {}

    def save_checkpoint(self, data: Dict[str, Any]) -> bool:
        """Save checkpoint data"""
        if self._checkpoint_manager:
            return self._checkpoint_manager.save_checkpoint(data)
        return False

    def clear_checkpoint(self) -> bool:
        """Clear checkpoint after successful completion"""
        if self._checkpoint_manager:
            return self._checkpoint_manager.clear_checkpoint()
        return False

    def should_pause(self) -> bool:
        """Check if pause has been requested"""
        if self._checkpoint_manager:
            return self._checkpoint_manager.is_pause_requested()
        return False

    def save_checkpoint_and_pause(self, data: Dict[str, Any]) -> bool:
        """Save checkpoint and clear pause request"""
        if self._checkpoint_manager:
            self._checkpoint_manager.save_checkpoint(data)
            self._checkpoint_manager.clear_pause_request()
            return True
        return False

    def has_checkpoint(self) -> bool:
        """Check if checkpoint exists for resume"""
        if self._checkpoint_manager:
            return self._checkpoint_manager.has_checkpoint()
        return False
```

---

### 3.3 API Endpoints for Pause/Resume

```python
# Add to studio54-service/app/api/jobs.py

@router.post("/{job_id}/pause")
async def pause_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Request a running job to pause at the next safe checkpoint.

    The job will:
    1. Finish processing current item
    2. Save checkpoint with current progress
    3. Set status to PAUSED

    This allows safe updates without losing work.
    """
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.RUNNING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause job with status {job.status}. Only running jobs can be paused."
        )

    # Request pause via checkpoint manager
    checkpoint_manager = JobCheckpointManager(str(job_id))
    checkpoint_manager.request_pause()

    logger.info(f"Pause requested for job {job_id}")

    return {
        "status": "pause_requested",
        "job_id": str(job_id),
        "message": "Job will pause at next safe checkpoint. Check job status for completion."
    }


@router.post("/{job_id}/resume")
async def resume_job(job_id: UUID, db: Session = Depends(get_db)):
    """
    Resume a paused job from its last checkpoint.

    The job will:
    1. Load checkpoint data
    2. Resume processing from saved index
    3. Continue until completion or next pause
    """
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in [JobStatus.PAUSED, JobStatus.FAILED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume job with status {job.status}. Only paused or failed jobs can be resumed."
        )

    # Check if checkpoint exists
    checkpoint_manager = JobCheckpointManager(str(job_id))
    if not checkpoint_manager.has_checkpoint():
        raise HTTPException(
            status_code=400,
            detail="No checkpoint found. Job cannot be resumed and must be restarted."
        )

    # Clear any stale pause request
    checkpoint_manager.clear_pause_request()

    # Dispatch appropriate task based on job type
    task_map = {
        JobType.FETCH_METADATA: fetch_metadata_task,
        JobType.VALIDATE_MBID: validate_mbid_task,
        JobType.VALIDATE_MBID_METADATA: validate_mbid_metadata_task,
        JobType.ORGANIZE_LIBRARY: organize_library_files_task,
        JobType.ORGANIZE_ARTIST: organize_artist_files_task,
        JobType.VALIDATE_STRUCTURE: validate_library_structure_task,
        JobType.LINK_FILES: link_files_task,
        JobType.REINDEX_ALBUMS: reindex_albums_task,
        JobType.VERIFY_AUDIO: verify_audio_task,
    }

    task_func = task_map.get(job.job_type)
    if not task_func:
        raise HTTPException(status_code=400, detail=f"Unknown job type: {job.job_type}")

    # Update job status
    job.status = JobStatus.PENDING
    job.current_action = "Resuming from checkpoint..."
    db.commit()

    # Dispatch task
    result = task_func.delay(str(job_id))
    job.celery_task_id = result.id
    db.commit()

    logger.info(f"Resumed job {job_id} from checkpoint, new task ID: {result.id}")

    return {
        "status": "resumed",
        "job_id": str(job_id),
        "celery_task_id": result.id,
        "message": "Job resumed from checkpoint"
    }


@router.get("/{job_id}/checkpoint")
async def get_job_checkpoint(job_id: UUID):
    """Get checkpoint information for a job"""
    checkpoint_manager = JobCheckpointManager(str(job_id))
    checkpoint_data = checkpoint_manager.load_checkpoint()

    return {
        "job_id": str(job_id),
        "has_checkpoint": checkpoint_manager.has_checkpoint(),
        "checkpoint_data": checkpoint_data,
        "pause_requested": checkpoint_manager.is_pause_requested()
    }
```

---

### 3.4 Update All Tasks with Checkpoint Support

Each task needs to be updated with the checkpoint pattern:

```python
# Template for all tasks:

@shared_task(bind=True, base=CheckpointableTask, soft_time_limit=7200, time_limit=7260)
def some_task(self, job_id: str):
    db = SessionLocal()

    try:
        # Initialize checkpoint support
        self.init_checkpoint(job_id)

        job = get_job(db, job_id)

        # Load checkpoint for resume
        checkpoint = self.load_checkpoint()
        start_index = checkpoint.get('last_processed_index', 0)
        stats = checkpoint.get('stats', {'processed': 0, 'failed': 0})

        if start_index > 0:
            logger.info(f"Resuming from index {start_index}")

        # Get items to process
        items = get_items_to_process(db, job)
        total = len(items)

        for i, item in enumerate(items):
            # Skip already processed (for resume)
            if i < start_index:
                continue

            # Check for pause request
            if self.should_pause():
                self.save_checkpoint_and_pause({
                    'last_processed_index': i,
                    'stats': stats
                })
                job.status = JobStatus.PAUSED
                job.current_action = f"Paused at {i}/{total}"
                db.commit()
                return {'status': 'paused', 'index': i}

            # Process item
            try:
                process_item(item)
                stats['processed'] += 1
            except Exception as e:
                stats['failed'] += 1

            # Update progress
            job.files_processed = i + 1
            job.progress_percent = (i + 1) / total * 100

            # Checkpoint periodically
            if (i + 1) % 100 == 0:
                job.last_heartbeat_at = datetime.now(timezone.utc)
                db.commit()
                self.save_checkpoint({
                    'last_processed_index': i + 1,
                    'stats': stats
                })

        # Complete - clear checkpoint
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        self.clear_checkpoint()

        return stats

    except Exception as e:
        # Save checkpoint on error for retry
        if hasattr(self, '_checkpoint_manager'):
            self.save_checkpoint({
                'last_processed_index': job.files_processed,
                'error': str(e)
            })
        raise
    finally:
        db.close()
```

---

## Part 4: Hot-Reload Update System

### 4.1 Safe Update Procedure

```bash
#!/bin/bash
# scripts/safe_update.sh

# 1. Pause all running jobs
echo "Pausing all running jobs..."
curl -X POST "http://localhost:8010/api/v1/jobs/pause-all"

# 2. Wait for jobs to reach pause state (max 5 minutes)
echo "Waiting for jobs to pause..."
for i in {1..30}; do
    running=$(curl -s "http://localhost:8010/api/v1/jobs?status=running" | jq '.total')
    if [ "$running" -eq "0" ]; then
        echo "All jobs paused."
        break
    fi
    echo "Still running: $running jobs"
    sleep 10
done

# 3. Build new image
echo "Building new image..."
docker-compose -f config/docker-compose.yml build --no-cache studio54-service

# 4. Rolling restart (keeps one worker running during transition)
echo "Performing rolling restart..."
docker-compose -f config/docker-compose.yml up -d --scale studio54-worker=2 studio54-service
sleep 5
docker-compose -f config/docker-compose.yml up -d --scale studio54-worker=1 studio54-service studio54-worker

# 5. Resume all paused jobs
echo "Resuming paused jobs..."
curl -X POST "http://localhost:8010/api/v1/jobs/resume-all"

echo "Update complete!"
```

### 4.2 Pause/Resume All API

```python
@router.post("/pause-all")
async def pause_all_jobs(db: Session = Depends(get_db)):
    """Pause all running jobs for safe system update"""
    running_jobs = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.status == JobStatus.RUNNING
    ).all()

    paused = []
    for job in running_jobs:
        checkpoint_manager = JobCheckpointManager(str(job.id))
        checkpoint_manager.request_pause()
        paused.append(str(job.id))

    return {
        "status": "pause_requested",
        "jobs_count": len(paused),
        "job_ids": paused
    }


@router.post("/resume-all")
async def resume_all_jobs(db: Session = Depends(get_db)):
    """Resume all paused jobs after system update"""
    paused_jobs = db.query(FileOrganizationJob).filter(
        FileOrganizationJob.status == JobStatus.PAUSED
    ).all()

    resumed = []
    for job in paused_jobs:
        try:
            # Resume logic from resume_job endpoint
            # ...
            resumed.append(str(job.id))
        except Exception as e:
            logger.error(f"Failed to resume job {job.id}: {e}")

    return {
        "status": "resumed",
        "jobs_count": len(resumed),
        "job_ids": resumed
    }
```

---

## Part 5: Database Schema Updates

### 5.1 Migration for New Columns

```python
# alembic/versions/20260126_0100_add_checkpoint_and_validation_columns.py

def upgrade():
    # Library files - confidence and validation tracking
    op.add_column('library_files', sa.Column('mbid_confidence_score', sa.Integer(), nullable=True))
    op.add_column('library_files', sa.Column('needs_mbid_review', sa.Boolean(), default=False))
    op.add_column('library_files', sa.Column('mbid_review_reason', sa.Text(), nullable=True))
    op.add_column('library_files', sa.Column('mbid_reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('library_files', sa.Column('mbid_reviewed_by', sa.Text(), nullable=True))
    op.add_column('library_files', sa.Column('mbid_validation_status', sa.Text(), nullable=True))
    op.add_column('library_files', sa.Column('mbid_validated_at', sa.DateTime(timezone=True), nullable=True))

    # File organization jobs - checkpoint support
    op.add_column('file_organization_jobs', sa.Column('checkpoint_data', sa.Text(), nullable=True))
    op.add_column('file_organization_jobs', sa.Column('can_resume', sa.Boolean(), default=True))
    op.add_column('file_organization_jobs', sa.Column('files_skipped', sa.Integer(), default=0))

    # Indexes
    op.create_index('idx_library_files_needs_review', 'library_files', ['needs_mbid_review'],
                    postgresql_where=sa.text('needs_mbid_review = TRUE'))
    op.create_index('idx_library_files_confidence', 'library_files', ['mbid_confidence_score'])
    op.create_index('idx_library_files_validation_status', 'library_files', ['mbid_validation_status'])


def downgrade():
    op.drop_index('idx_library_files_validation_status')
    op.drop_index('idx_library_files_confidence')
    op.drop_index('idx_library_files_needs_review')

    op.drop_column('file_organization_jobs', 'files_skipped')
    op.drop_column('file_organization_jobs', 'can_resume')
    op.drop_column('file_organization_jobs', 'checkpoint_data')

    op.drop_column('library_files', 'mbid_validated_at')
    op.drop_column('library_files', 'mbid_validation_status')
    op.drop_column('library_files', 'mbid_reviewed_by')
    op.drop_column('library_files', 'mbid_reviewed_at')
    op.drop_column('library_files', 'mbid_review_reason')
    op.drop_column('library_files', 'needs_mbid_review')
    op.drop_column('library_files', 'mbid_confidence_score')
```

---

## Part 6: Implementation Order

### Phase 1: Checkpoint System (Critical - Do First)
**Priority: HIGHEST - Prevents data loss**

1. [ ] Create `JobCheckpointManager` class
2. [ ] Create `CheckpointableTask` base class
3. [ ] Add pause/resume API endpoints
4. [ ] Update `fetch_metadata_task` with checkpoint support
5. [ ] Update `validate_mbid_task` with checkpoint support
6. [ ] Update `validate_library_structure_task` with checkpoint support
7. [ ] Update `organize_library_files_task` with checkpoint support
8. [ ] Update ALL other job tasks with checkpoint support
9. [ ] Create database migration for new columns
10. [ ] Test pause/resume cycle on each job type

### Phase 2: Pre-Check MBID Before API Call
**Priority: HIGH - Reduces API waste**

1. [ ] Add MBID file check before MusicBrainz search
2. [ ] Add `files_skipped` counter to job
3. [ ] Log skipped files with reason
4. [ ] Update database for files already having MBID

### Phase 3: Confidence Scoring
**Priority: MEDIUM - Improves accuracy**

1. [ ] Create `MBIDConfidenceScorer` service
2. [ ] Add fuzzy matching utilities (Levenshtein, etc.)
3. [ ] Integrate scoring into `fetch_metadata_task`
4. [ ] Add `needs_mbid_review` flag handling
5. [ ] Create API endpoint to list files needing review
6. [ ] Add review queue UI (optional)

### Phase 4: VALIDATE_MBID_METADATA Job
**Priority: MEDIUM - Corrects metadata**

1. [ ] Add `VALIDATE_MBID_METADATA` job type
2. [ ] Implement `validate_mbid_metadata_task` with scope support
3. [ ] Add MusicBrainz recording lookup method (`get_recording_details`)
4. [ ] Add API endpoint for library-level validation
5. [ ] Add UI button for validation job

### Phase 5: Granular Validation Scopes
**Priority: MEDIUM - Enables targeted corrections**

1. [ ] Add artist-level validation API endpoint
2. [ ] Add album-level validation API endpoint
3. [ ] Add single-file validation API endpoint (synchronous)
4. [ ] Add batch validation API endpoint (list of file IDs)
5. [ ] Update `validate_mbid_metadata_task` to handle all scopes
6. [ ] Add validation options schema (update_files, update_database, dry_run)
7. [ ] Add UI buttons for artist/album/track validation

### Phase 6: MUSE Ponder Integration
**Priority: MEDIUM - Audio fingerprint identification**

1. [ ] Create `PonderClient` service
2. [ ] Add Ponder identify endpoint to MUSE (if not exists)
3. [ ] Integrate Ponder option into validation task
4. [ ] Add `use_ponder` and `force_ponder` options
5. [ ] Handle Ponder confidence scores
6. [ ] Add batch identification support
7. [ ] Add UI options for Ponder identification

### Phase 7: Hot-Reload System
**Priority: LOW - Nice to have**

1. [ ] Create `safe_update.sh` script
2. [ ] Add `pause-all` / `resume-all` endpoints
3. [ ] Test rolling restart procedure
4. [ ] Document update procedure

---

## Part 7: Granular Validation Scopes

### 7.1 Validation Scope Levels

Support validation at multiple levels without processing entire library:

| Scope | Use Case | Example |
|-------|----------|---------|
| **Library** | Initial full validation | Validate all 60,000 files |
| **Artist** | Fix specific artist's files | Validate all Beatles files (500 files) |
| **Album** | Fix specific album | Validate "Abbey Road" (17 files) |
| **File** | Fix single song | Validate one mismatched track |

### 7.2 API Endpoints for Granular Validation

```python
# Add to studio54-service/app/api/file_management.py

@router.post("/artists/{artist_id}/validate-metadata", response_model=OrganizationJobResponse)
async def validate_artist_metadata(
    artist_id: UUID,
    options: Optional[ValidationOptions] = None,
    db: Session = Depends(get_db)
):
    """
    Validate MBID metadata for all files belonging to an artist.

    Options:
        - update_files: bool - Write corrected metadata to files (default: True)
        - update_database: bool - Update database with canonical data (default: True)
        - use_ponder: bool - Use MUSE Ponder for fingerprint identification (default: False)
        - dry_run: bool - Preview changes without writing (default: False)
    """
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail=f"Artist {artist_id} not found")

    # Get all library files for this artist
    file_count = db.query(LibraryFile).filter(
        LibraryFile.musicbrainz_artistid == str(artist.mbid)
    ).count()

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID_METADATA,
        status=JobStatus.PENDING,
        artist_id=artist_id,
        files_total=file_count,
        current_action=f"Queued: Validate metadata for {artist.name} ({file_count} files)"
    )
    db.add(job)
    db.commit()

    # Store options in job
    job_options = {
        'scope': 'artist',
        'artist_id': str(artist_id),
        'update_files': options.update_files if options else True,
        'update_database': options.update_database if options else True,
        'use_ponder': options.use_ponder if options else False,
        'dry_run': options.dry_run if options else False
    }
    job.options_json = json.dumps(job_options)
    db.commit()

    result = validate_mbid_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Validation queued for artist "{artist.name}" ({file_count} files)'
    )


@router.post("/albums/{album_id}/validate-metadata", response_model=OrganizationJobResponse)
async def validate_album_metadata(
    album_id: UUID,
    options: Optional[ValidationOptions] = None,
    db: Session = Depends(get_db)
):
    """
    Validate MBID metadata for all files in an album.
    """
    album = db.query(Album).filter(Album.id == album_id).first()
    if not album:
        raise HTTPException(status_code=404, detail=f"Album {album_id} not found")

    # Get tracks with files
    tracks_with_files = db.query(Track).filter(
        Track.album_id == album_id,
        Track.file_path.isnot(None)
    ).count()

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID_METADATA,
        status=JobStatus.PENDING,
        album_id=album_id,
        artist_id=album.artist_id,
        files_total=tracks_with_files,
        current_action=f"Queued: Validate metadata for {album.title} ({tracks_with_files} tracks)"
    )
    db.add(job)
    db.commit()

    job_options = {
        'scope': 'album',
        'album_id': str(album_id),
        'update_files': options.update_files if options else True,
        'update_database': options.update_database if options else True,
        'use_ponder': options.use_ponder if options else False,
        'dry_run': options.dry_run if options else False
    }
    job.options_json = json.dumps(job_options)
    db.commit()

    result = validate_mbid_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Validation queued for album "{album.title}" ({tracks_with_files} tracks)'
    )


@router.post("/files/{file_id}/validate-metadata", response_model=ValidationResult)
async def validate_single_file_metadata(
    file_id: UUID,
    options: Optional[SingleFileValidationOptions] = None,
    db: Session = Depends(get_db)
):
    """
    Validate and optionally correct metadata for a single file.

    This is a synchronous operation (no background job) for quick single-file fixes.

    Options:
        - update_file: bool - Write corrected metadata to file
        - update_database: bool - Update database
        - use_ponder: bool - Use MUSE Ponder for identification
        - force_ponder: bool - Use Ponder even if MBID exists (re-identify)
    """
    library_file = db.query(LibraryFile).filter(LibraryFile.id == file_id).first()
    if not library_file:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")

    result = validate_single_file(
        db=db,
        library_file=library_file,
        update_file=options.update_file if options else True,
        update_database=options.update_database if options else True,
        use_ponder=options.use_ponder if options else False,
        force_ponder=options.force_ponder if options else False
    )

    return result


@router.post("/files/validate-metadata-batch", response_model=OrganizationJobResponse)
async def validate_files_batch(
    request: BatchValidationRequest,
    db: Session = Depends(get_db)
):
    """
    Validate metadata for a specific list of files.

    Request body:
        file_ids: List[UUID] - List of file IDs to validate
        options: ValidationOptions - Validation options
    """
    file_count = len(request.file_ids)
    if file_count > 10000:
        raise HTTPException(status_code=400, detail="Maximum 10,000 files per batch")

    # Verify all files exist
    existing = db.query(LibraryFile.id).filter(
        LibraryFile.id.in_(request.file_ids)
    ).count()

    if existing != file_count:
        raise HTTPException(status_code=400, detail=f"Only {existing} of {file_count} files found")

    job = FileOrganizationJob(
        job_type=JobType.VALIDATE_MBID_METADATA,
        status=JobStatus.PENDING,
        files_total=file_count,
        current_action=f"Queued: Validate {file_count} selected files"
    )
    db.add(job)
    db.commit()

    job_options = {
        'scope': 'batch',
        'file_ids': [str(f) for f in request.file_ids],
        'update_files': request.options.update_files if request.options else True,
        'update_database': request.options.update_database if request.options else True,
        'use_ponder': request.options.use_ponder if request.options else False,
        'dry_run': request.options.dry_run if request.options else False
    }
    job.options_json = json.dumps(job_options)
    db.commit()

    result = validate_mbid_metadata_task.delay(str(job.id))
    job.celery_task_id = result.id
    db.commit()

    return OrganizationJobResponse(
        job_id=str(job.id),
        status='queued',
        message=f'Validation queued for {file_count} files'
    )
```

### 7.3 Updated Task with Scope Support

```python
# In validate_mbid_metadata_task:

def get_files_for_scope(db: Session, job: FileOrganizationJob) -> List[LibraryFile]:
    """Get files based on job scope"""
    options = json.loads(job.options_json) if job.options_json else {}
    scope = options.get('scope', 'library')

    if scope == 'artist':
        artist_id = UUID(options['artist_id'])
        artist = db.query(Artist).filter(Artist.id == artist_id).first()
        return db.query(LibraryFile).filter(
            LibraryFile.musicbrainz_artistid == str(artist.mbid)
        ).order_by(LibraryFile.id).all()

    elif scope == 'album':
        album_id = UUID(options['album_id'])
        tracks = db.query(Track).filter(
            Track.album_id == album_id,
            Track.file_path.isnot(None)
        ).all()
        file_paths = [t.file_path for t in tracks]
        return db.query(LibraryFile).filter(
            LibraryFile.file_path.in_(file_paths)
        ).order_by(LibraryFile.id).all()

    elif scope == 'batch':
        file_ids = [UUID(f) for f in options['file_ids']]
        return db.query(LibraryFile).filter(
            LibraryFile.id.in_(file_ids)
        ).order_by(LibraryFile.id).all()

    else:  # library scope
        return db.query(LibraryFile).filter(
            LibraryFile.library_path_id == job.library_path_id,
            LibraryFile.mbid_in_file == True
        ).order_by(LibraryFile.id).all()
```

---

## Part 8: MUSE Ponder Integration for Audio Fingerprinting

### 8.1 Purpose

When a file has no MBID or needs re-identification, use MUSE Ponder's audio fingerprinting to identify the song. Ponder uses Chromaprint (AcoustID) to generate audio fingerprints and match against MusicBrainz.

### 8.2 Ponder Service Client

```python
# New file: studio54-service/app/services/ponder_client.py

import requests
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PONDER_SERVICE_URL = os.getenv('PONDER_SERVICE_URL', 'http://muse-service:8007')


@dataclass
class PonderIdentificationResult:
    """Result of Ponder audio fingerprint identification"""
    success: bool
    recording_mbid: Optional[str] = None
    artist_mbid: Optional[str] = None
    release_mbid: Optional[str] = None
    release_group_mbid: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    confidence: float = 0.0
    fingerprint: Optional[str] = None
    error: Optional[str] = None


class PonderClient:
    """
    Client for MUSE Ponder audio fingerprinting service.

    Ponder identifies songs using:
    1. Chromaprint audio fingerprint generation
    2. AcoustID lookup against MusicBrainz database
    3. Confidence scoring based on fingerprint match quality
    """

    def __init__(self, base_url: str = None):
        self.base_url = base_url or PONDER_SERVICE_URL

    def identify_file(
        self,
        file_path: str,
        duration_hint: Optional[int] = None
    ) -> PonderIdentificationResult:
        """
        Identify a song using audio fingerprinting.

        Args:
            file_path: Path to audio file (must be accessible from MUSE service)
            duration_hint: Optional duration in seconds to limit fingerprint

        Returns:
            PonderIdentificationResult with MBIDs and metadata
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/ponder/identify",
                json={
                    'file_path': file_path,
                    'duration_hint': duration_hint,
                    'return_metadata': True
                },
                timeout=120  # Fingerprinting can take time
            )

            if response.status_code == 200:
                data = response.json()

                if data.get('match_found'):
                    return PonderIdentificationResult(
                        success=True,
                        recording_mbid=data.get('recording_mbid'),
                        artist_mbid=data.get('artist_mbid'),
                        release_mbid=data.get('release_mbid'),
                        release_group_mbid=data.get('release_group_mbid'),
                        title=data.get('title'),
                        artist=data.get('artist'),
                        album=data.get('album'),
                        confidence=data.get('confidence', 0.0),
                        fingerprint=data.get('fingerprint')
                    )
                else:
                    return PonderIdentificationResult(
                        success=False,
                        error="No match found",
                        fingerprint=data.get('fingerprint')
                    )

            else:
                return PonderIdentificationResult(
                    success=False,
                    error=f"Ponder API error: {response.status_code}"
                )

        except requests.exceptions.Timeout:
            return PonderIdentificationResult(
                success=False,
                error="Ponder request timed out"
            )
        except requests.exceptions.ConnectionError:
            return PonderIdentificationResult(
                success=False,
                error="Could not connect to Ponder service"
            )
        except Exception as e:
            return PonderIdentificationResult(
                success=False,
                error=str(e)
            )

    def identify_batch(
        self,
        file_paths: List[str],
        callback_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submit batch of files for identification.

        For large batches, this queues files for async processing.

        Args:
            file_paths: List of file paths to identify
            callback_url: Optional webhook URL for completion notification

        Returns:
            Job ID for tracking batch progress
        """
        try:
            response = requests.post(
                f"{self.base_url}/api/v1/ponder/identify-batch",
                json={
                    'file_paths': file_paths,
                    'callback_url': callback_url
                },
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f"Ponder API error: {response.status_code}"}

        except Exception as e:
            return {'error': str(e)}

    def get_batch_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of batch identification job"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/ponder/batch/{job_id}",
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {'error': str(e)}
```

### 8.3 Integration in Validation Task

```python
# In validate_mbid_metadata_task, when processing each file:

def process_file_with_ponder(
    db: Session,
    library_file: LibraryFile,
    ponder_client: PonderClient,
    job_logger: JobLogger,
    force_ponder: bool = False
) -> Dict[str, Any]:
    """
    Process file using MUSE Ponder for identification.

    Args:
        force_ponder: If True, re-identify even if MBID exists

    Returns:
        Dict with identification results
    """
    file_path = library_file.file_path
    result = {'status': 'unknown', 'changes': []}

    # Check if we should skip Ponder
    if not force_ponder and library_file.mbid_in_file:
        # Already has MBID, just validate against MusicBrainz
        return validate_existing_mbid(db, library_file, job_logger)

    # Use Ponder for identification
    job_logger.log_info(f"Using Ponder to identify: {file_path}")

    ponder_result = ponder_client.identify_file(file_path)

    if ponder_result.success:
        job_logger.log_info(
            f"Ponder identified: {ponder_result.artist} - {ponder_result.title} "
            f"(confidence: {ponder_result.confidence:.1%})"
        )

        # Check confidence threshold
        if ponder_result.confidence < 0.85:
            job_logger.log_warning(
                f"Low confidence ({ponder_result.confidence:.1%}), flagging for review"
            )
            library_file.needs_mbid_review = True
            library_file.mbid_review_reason = f"Ponder confidence: {ponder_result.confidence:.1%}"
            result['status'] = 'low_confidence'
            return result

        # Write MBIDs to file
        write_result = MetadataWriter.write_mbids(
            file_path=file_path,
            recording_mbid=ponder_result.recording_mbid,
            artist_mbid=ponder_result.artist_mbid,
            release_mbid=ponder_result.release_mbid,
            release_group_mbid=ponder_result.release_group_mbid,
            overwrite=True  # Overwrite with Ponder results
        )

        if write_result.success:
            # Update file metadata with canonical data
            MetadataWriter.write_metadata(
                file_path=file_path,
                title=ponder_result.title,
                artist=ponder_result.artist,
                album=ponder_result.album,
                overwrite=True
            )

            # Update database
            library_file.musicbrainz_trackid = ponder_result.recording_mbid
            library_file.musicbrainz_artistid = ponder_result.artist_mbid
            library_file.musicbrainz_albumid = ponder_result.release_mbid
            library_file.musicbrainz_releasegroupid = ponder_result.release_group_mbid
            library_file.mbid_in_file = True
            library_file.mbid_validated_at = datetime.now(timezone.utc)
            library_file.mbid_confidence_score = int(ponder_result.confidence * 100)
            library_file.title = ponder_result.title
            library_file.artist = ponder_result.artist
            library_file.album = ponder_result.album

            result['status'] = 'identified'
            result['changes'] = [
                f"MBID: {ponder_result.recording_mbid}",
                f"Title: {ponder_result.title}",
                f"Artist: {ponder_result.artist}"
            ]
        else:
            job_logger.log_error(f"Failed to write MBIDs: {write_result.error}")
            result['status'] = 'write_failed'
            result['error'] = write_result.error

    else:
        job_logger.log_warning(f"Ponder could not identify: {file_path} - {ponder_result.error}")
        library_file.needs_mbid_review = True
        library_file.mbid_review_reason = f"Ponder: {ponder_result.error}"
        result['status'] = 'not_identified'
        result['error'] = ponder_result.error

    return result
```

### 8.4 MUSE Ponder API Endpoint (if not exists)

Add to MUSE service if needed:

```python
# muse-service/app/api/ponder.py

@router.post("/identify")
async def identify_file(
    request: IdentifyRequest,
    db: Session = Depends(get_db)
):
    """
    Identify a song using audio fingerprinting.

    Uses Chromaprint to generate fingerprint, then queries AcoustID/MusicBrainz.
    """
    file_path = request.file_path

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Generate Chromaprint fingerprint
    fingerprinter = AudioFingerprinter()
    fingerprint = fingerprinter.generate_fingerprint(
        file_path,
        duration=request.duration_hint or 120
    )

    if not fingerprint:
        return {
            'match_found': False,
            'error': 'Could not generate fingerprint'
        }

    # Query AcoustID
    acoustid_client = AcoustIDClient()
    matches = acoustid_client.lookup(fingerprint)

    if not matches:
        return {
            'match_found': False,
            'fingerprint': fingerprint,
            'error': 'No AcoustID match found'
        }

    # Get best match
    best_match = matches[0]
    confidence = best_match.get('score', 0)

    # Get MusicBrainz metadata
    recording_mbid = best_match.get('recordings', [{}])[0].get('id')
    if recording_mbid:
        mb_client = MusicBrainzClient()
        recording = mb_client.get_recording_details(recording_mbid)

        return {
            'match_found': True,
            'recording_mbid': recording_mbid,
            'artist_mbid': get_artist_mbid(recording),
            'release_mbid': get_release_mbid(recording),
            'release_group_mbid': get_release_group_mbid(recording),
            'title': recording.get('title'),
            'artist': get_artist_name(recording),
            'album': get_release_title(recording),
            'confidence': confidence,
            'fingerprint': fingerprint
        }

    return {
        'match_found': False,
        'fingerprint': fingerprint,
        'error': 'No recording found for AcoustID match'
    }
```

---

## Part 9: UI Support for Granular Validation

### 9.1 Artist Page - Validate Button

```tsx
// In studio54-web/src/pages/ArtistDetail.tsx

<Button
  onClick={() => validateArtistMetadata(artistId)}
  disabled={isValidating}
  variant="outline"
>
  <FiCheckCircle className="mr-2" />
  Validate Metadata
</Button>

{/* Options dropdown */}
<DropdownMenu>
  <DropdownMenuItem onClick={() => validateArtistMetadata(artistId, { use_ponder: true })}>
    Validate with Audio Fingerprinting (Ponder)
  </DropdownMenuItem>
  <DropdownMenuItem onClick={() => validateArtistMetadata(artistId, { dry_run: true })}>
    Preview Changes (Dry Run)
  </DropdownMenuItem>
</DropdownMenu>
```

### 9.2 Album Page - Validate Button

```tsx
// In studio54-web/src/pages/AlbumDetail.tsx

<Button
  onClick={() => validateAlbumMetadata(albumId)}
  disabled={isValidating}
  variant="outline"
>
  <FiCheckCircle className="mr-2" />
  Validate Album Metadata
</Button>
```

### 9.3 Track/File Context Menu

```tsx
// Track list row context menu

<ContextMenu>
  <ContextMenuItem onClick={() => validateFile(fileId)}>
    Validate Metadata
  </ContextMenuItem>
  <ContextMenuItem onClick={() => validateFile(fileId, { use_ponder: true })}>
    Re-identify with Ponder
  </ContextMenuItem>
  <ContextMenuItem onClick={() => validateFile(fileId, { force_ponder: true })}>
    Force Re-identify (ignore existing MBID)
  </ContextMenuItem>
</ContextMenu>
```

---

## Summary of Benefits

| Problem | Solution | Impact |
|---------|----------|--------|
| Wasted API calls | Pre-check file for MBID before API | 50%+ reduction in API calls |
| Blind matching | Confidence scoring with thresholds | Catch bad matches before writing |
| Wrong metadata | VALIDATE_MBID_METADATA job | Correct file tags to match MusicBrainz |
| Lost progress on restart | Checkpoint/resume system | Never reprocess completed work |
| Update interruption | Safe pause/resume | Zero-downtime updates |
| Whole library required | Granular validation scopes | Fix single artist/album/file |
| Can't identify unknown files | MUSE Ponder integration | Audio fingerprint identification |
| No review process | Low-confidence flagging | Human review for uncertain matches |

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `studio54-service/app/services/job_checkpoint_manager.py` | Redis-based checkpoint storage |
| `studio54-service/app/services/mbid_confidence_scorer.py` | Match confidence scoring |
| `studio54-service/app/services/ponder_client.py` | MUSE Ponder API client |
| `studio54-service/app/tasks/checkpoint_mixin.py` | Base task class with checkpoint support |
| `scripts/safe_update.sh` | Safe system update script |

### Modified Files
| File | Changes |
|------|---------|
| `studio54-service/app/tasks/organization_tasks.py` | Add checkpoint support to ALL tasks, add VALIDATE_MBID_METADATA task, pre-check MBID, confidence scoring |
| `studio54-service/app/api/jobs.py` | Add pause/resume/pause-all/resume-all endpoints |
| `studio54-service/app/api/file_management.py` | Add granular validation endpoints (artist/album/file/batch) |
| `studio54-service/app/models/file_organization_job.py` | Add VALIDATE_MBID_METADATA type, checkpoint columns |
| `studio54-service/app/models/library.py` | Add validation and confidence columns |
| `studio54-web/src/pages/ArtistDetail.tsx` | Add validate metadata button |
| `studio54-web/src/pages/AlbumDetail.tsx` | Add validate metadata button |
| `studio54-web/src/components/TrackList.tsx` | Add validate context menu |
| `muse-service/app/api/ponder.py` | Add identify endpoint (if not exists) |

### Migrations
| Migration | Purpose |
|-----------|---------|
| `20260126_0100_add_checkpoint_and_validation_columns.py` | Confidence, review, validation columns |

---

## API Endpoint Summary

### Job Control
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/jobs/{id}/pause` | POST | Request job to pause at next checkpoint |
| `/api/v1/jobs/{id}/resume` | POST | Resume paused job from checkpoint |
| `/api/v1/jobs/{id}/checkpoint` | GET | Get checkpoint info |
| `/api/v1/jobs/pause-all` | POST | Pause all running jobs |
| `/api/v1/jobs/resume-all` | POST | Resume all paused jobs |

### Granular Validation
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/file-organization/library-paths/{id}/validate-metadata` | POST | Validate entire library |
| `/api/v1/file-organization/artists/{id}/validate-metadata` | POST | Validate artist files |
| `/api/v1/file-organization/albums/{id}/validate-metadata` | POST | Validate album files |
| `/api/v1/file-organization/files/{id}/validate-metadata` | POST | Validate single file (sync) |
| `/api/v1/file-organization/files/validate-metadata-batch` | POST | Validate list of files |

---

## Validation Options Schema

```typescript
interface ValidationOptions {
  update_files: boolean;      // Write corrected metadata to files (default: true)
  update_database: boolean;   // Update database with canonical data (default: true)
  use_ponder: boolean;        // Use MUSE Ponder for identification (default: false)
  force_ponder: boolean;      // Re-identify even if MBID exists (default: false)
  dry_run: boolean;           // Preview changes without writing (default: false)
  confidence_threshold: number; // Minimum confidence to auto-write (default: 80)
}
```

---

## Current Job Status

The running fetch_metadata job will complete normally. Once you're ready to implement this plan:

1. Wait for current job to complete, OR
2. Use the new pause feature (once implemented) to safely pause
3. Apply updates
4. Resume from checkpoint

---

**Status:** Ready for implementation
**Estimated Effort:**
- Phase 1 (Checkpoint): 2-3 days
- Phase 2-4: 1-2 days each
- Phase 5-6: 2-3 days each
- Phase 7: 1 day

**Total:** ~2 weeks for complete implementation
**Risk Level:** Low - Changes are additive and backward compatible
