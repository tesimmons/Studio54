"""
Library Migration Tasks
Celery tasks for migrating files between libraries with MBID validation.

Features:
- Fully automated migration (no user intervention required)
- MBID lookup via centralized MusicBrainz API service
- Metadata validation and correction against MusicBrainz
- Validation tag writing to "Encoded By" field
- File renaming and directory creation using NamingEngine
- 3-retry logic per operation with self-recovery
- Separate success/failed/skipped logs
- Auto-dispatch Ponder fingerprint job for unmatched files
"""

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
import traceback
import logging
import json
import time
import os

from app.database import SessionLocal
from app.models.library import LibraryPath, LibraryFile
from app.models.file_organization_job import FileOrganizationJob, JobStatus, JobType
from app.services.metadata_writer import MetadataWriter
from app.services.metadata_extractor import MetadataExtractor
from app.services.musicbrainz_client import get_musicbrainz_client
from app.services.mbid_confidence_scorer import MBIDConfidenceScorer
from app.services.ponder_client import get_ponder_client, PonderClientError
from app.shared_services import (
    FileOrganizer,
    NamingEngine,
    AtomicFileOps,
    AuditLogger,
    MetadataFileManager,
    TrackContext
)
from app.shared_services.job_logger import JobLogger
from app.tasks.checkpoint_mixin import CheckpointableTask

logger = logging.getLogger(__name__)

# Configuration
CONFIDENCE_THRESHOLD = 80  # Minimum confidence for auto-acceptance
CHECKPOINT_INTERVAL = 100  # Checkpoint every N files
MAX_RETRY_ATTEMPTS = 3  # Retry each operation up to 3 times
RETRY_DELAY_BASE = 2  # Base delay for exponential backoff (2/4/6 seconds)


# ========================================
# Helper Functions
# ========================================

def get_file_organizer(db: Session, dry_run: bool = False) -> FileOrganizer:
    """Create FileOrganizer with all dependencies"""
    naming_engine = NamingEngine()
    atomic_ops = AtomicFileOps()
    audit_logger = AuditLogger(db=db)

    return FileOrganizer(
        db=db,
        naming_engine=naming_engine,
        atomic_ops=atomic_ops,
        audit_logger=audit_logger,
        dry_run=dry_run
    )


def execute_with_retry(operation, file_path: str, max_retries: int = MAX_RETRY_ATTEMPTS, delay_base: int = RETRY_DELAY_BASE):
    """
    Execute operation with retry logic. Skip file on persistent failure.

    Args:
        operation: Callable to execute
        file_path: Path of file being processed (for logging)
        max_retries: Maximum retry attempts
        delay_base: Base delay for exponential backoff

    Returns:
        Tuple of (success: bool, result: Any, error_reason: str | None)
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            result = operation()
            return (True, result, None)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = delay_base * (attempt + 1)  # 2, 4, 6 seconds
                logger.warning(f"Retry {attempt + 1}/{max_retries} for {file_path}: {e}")
                time.sleep(delay)

    # All retries failed
    error_reason = f"Failed after {max_retries} attempts: {last_error}"
    return (False, None, error_reason)


def update_job_progress(
    db: Session,
    job: FileOrganizationJob,
    progress: float = None,
    current_action: str = None,
    files_processed: int = None,
    commit: bool = True
):
    """Update job progress and heartbeat"""
    if progress is not None:
        job.progress_percent = progress
    if current_action is not None:
        job.current_action = current_action
    if files_processed is not None:
        job.files_processed = files_processed
    job.last_heartbeat_at = datetime.now(timezone.utc)
    if commit:
        db.commit()


def save_checkpoint(job_logger: JobLogger, job_id: str, checkpoint_data: dict):
    """Save checkpoint data for job recovery"""
    checkpoint_file = f"/app/logs/checkpoint_{job_id}.json"
    try:
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f)
        job_logger.log_debug(f"Checkpoint saved at file_index={checkpoint_data.get('file_index', 0)}")
    except Exception as e:
        job_logger.log_warning(f"Failed to save checkpoint: {e}")


def load_checkpoint(job_id: str) -> dict:
    """Load checkpoint data for job recovery"""
    checkpoint_file = f"/app/logs/checkpoint_{job_id}.json"
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def write_migration_logs(
    job_id: str,
    success_log: list,
    failed_log: list,
    skipped_log: list,
    ponder_queue: list,
    job_logger: JobLogger
):
    """Write migration result logs to files"""
    log_dir = "/app/logs"

    # Write success log
    success_file = f"{log_dir}/migration_{job_id}_success.json"
    with open(success_file, 'w') as f:
        json.dump({
            "count": len(success_log),
            "files": success_log
        }, f, indent=2, default=str)

    # Write failed log
    failed_file = f"{log_dir}/migration_{job_id}_failed.json"
    with open(failed_file, 'w') as f:
        json.dump({
            "count": len(failed_log),
            "files": failed_log
        }, f, indent=2, default=str)

    # Write skipped log
    skipped_file = f"{log_dir}/migration_{job_id}_skipped.json"
    with open(skipped_file, 'w') as f:
        json.dump({
            "count": len(skipped_log),
            "files": skipped_log
        }, f, indent=2, default=str)

    # Write ponder queue
    ponder_file = f"{log_dir}/migration_{job_id}_ponder_queue.json"
    with open(ponder_file, 'w') as f:
        json.dump({
            "count": len(ponder_queue),
            "files": ponder_queue
        }, f, indent=2, default=str)

    # Log summary
    job_logger.log_info("=" * 60)
    job_logger.log_info("MIGRATION RESULTS SUMMARY")
    job_logger.log_info("=" * 60)
    job_logger.log_info(f"SUCCESS: {len(success_log)} files migrated")
    job_logger.log_info(f"FAILED: {len(failed_log)} files (operation errors after 3 retries)")
    job_logger.log_info(f"SKIPPED: {len(skipped_log)} files (could not be processed)")
    job_logger.log_info(f"PONDER QUEUE: {len(ponder_queue)} files (for fingerprint identification)")
    job_logger.log_info("=" * 60)
    job_logger.log_info(f"Log files written to: {log_dir}/migration_{job_id}_*.json")


def validate_and_correct_metadata(
    file_path: str,
    recording_mbid: str,
    mb_client,
    options: dict
) -> dict:
    """
    Validate file metadata against MusicBrainz and correct if needed.

    Returns:
        Dict with:
            - status: str (VALIDATED, CORRECTED, ERROR)
            - confidence: int (0-100)
            - track_context: TrackContext (for file organization)
            - corrections_made: list (if any)
    """
    result = {
        'status': 'ERROR',
        'confidence': 0,
        'track_context': None,
        'corrections_made': []
    }

    # Get recording details from MusicBrainz
    recording = mb_client.get_recording(recording_mbid, includes=['artists', 'releases'])
    if not recording:
        result['error'] = f"Could not fetch recording {recording_mbid} from MusicBrainz"
        return result

    # Extract metadata from file
    file_metadata = MetadataExtractor.extract(file_path)

    # Score the match
    score_result = MBIDConfidenceScorer.score_match(file_metadata, recording)
    result['confidence'] = score_result['total_score']

    # Extract MusicBrainz data
    mb_title = recording.get('title', '')
    artist_credits = recording.get('artist-credit', [])
    mb_artist = ''
    mb_artist_mbid = None
    if artist_credits:
        parts = []
        for credit in artist_credits:
            if isinstance(credit, dict):
                artist_name = credit.get('artist', {}).get('name', '') or credit.get('name', '')
                parts.append(artist_name + credit.get('joinphrase', ''))
                if not mb_artist_mbid and isinstance(credit.get('artist'), dict):
                    mb_artist_mbid = credit['artist'].get('id')
        mb_artist = ''.join(parts)

    # Get release info
    releases = recording.get('releases', [])
    mb_album = ''
    mb_release_mbid = None
    mb_release_group_mbid = None
    mb_year = None
    mb_track_number = None
    mb_disc_number = None

    if releases:
        release = releases[0]
        mb_album = release.get('title', '')
        mb_release_mbid = release.get('id')
        mb_release_group_mbid = release.get('release-group', {}).get('id')
        mb_year = release.get('date', '')[:4] if release.get('date') else None

        # Try to get track position
        media = release.get('media', [])
        if media:
            for medium_idx, medium in enumerate(media, 1):
                tracks = medium.get('tracks', [])
                for track in tracks:
                    if track.get('recording', {}).get('id') == recording_mbid:
                        mb_track_number = track.get('position', track.get('number'))
                        mb_disc_number = medium.get('position', medium_idx)
                        break

    # Determine if corrections needed
    corrections_needed = []
    if options.get('correct_metadata', True):
        if file_metadata.get('title') != mb_title:
            corrections_needed.append(('title', file_metadata.get('title'), mb_title))
        if file_metadata.get('artist') != mb_artist:
            corrections_needed.append(('artist', file_metadata.get('artist'), mb_artist))
        if file_metadata.get('album') != mb_album:
            corrections_needed.append(('album', file_metadata.get('album'), mb_album))

    # Set status based on confidence and corrections
    if result['confidence'] >= 90:
        result['status'] = 'VALIDATED' if not corrections_needed else 'CORRECTED'
    else:
        result['status'] = 'CORRECTED' if corrections_needed else 'VALIDATED'

    result['corrections_made'] = corrections_needed

    # Build TrackContext for file organization
    ext = Path(file_path).suffix
    result['track_context'] = TrackContext(
        artist_name=mb_artist,
        album_title=mb_album,
        track_title=mb_title,
        track_number=mb_track_number or file_metadata.get('track_number') or 1,
        disc_number=mb_disc_number or file_metadata.get('disc_number') or 1,
        total_tracks=file_metadata.get('total_tracks'),
        total_discs=file_metadata.get('total_discs'),
        release_year=int(mb_year) if mb_year and mb_year.isdigit() else file_metadata.get('year'),
        file_extension=ext.lstrip('.')
    )

    # Store MBIDs for later use
    result['artist_mbid'] = mb_artist_mbid
    result['release_mbid'] = mb_release_mbid
    result['release_group_mbid'] = mb_release_group_mbid
    result['mb_metadata'] = {
        'title': mb_title,
        'artist': mb_artist,
        'album': mb_album,
        'year': mb_year,
        'track_number': mb_track_number,
        'disc_number': mb_disc_number
    }

    return result


# ========================================
# Main Migration Task
# ========================================

@shared_task(bind=True, base=CheckpointableTask, soft_time_limit=14400, time_limit=14460)
def library_migration_task(self, job_id: str, source_library_id: str, destination_library_id: str, options: dict = None):
    """
    Fully automated library migration - NO USER INTERVENTION REQUIRED.

    Pipeline for each file:
    1. Check for existing MBID in Comments field
    2. If no MBID: Lookup via centralized MusicBrainz API service
    3. If confidence >= 80%: Validate/correct metadata → Write validation tag → Move file
    4. If confidence < 80% or no match: Add to Ponder queue
    5. Auto-dispatch fingerprint job for Ponder queue (NOT PAUSED)

    Args:
        job_id: FileOrganizationJob UUID
        source_library_id: Source LibraryPath UUID
        destination_library_id: Destination LibraryPath UUID
        options: Dict with:
            - min_confidence: int (default 80)
            - correct_metadata: bool (default True)
            - create_metadata_files: bool (default True)
    """
    if options is None:
        options = {}

    confidence_threshold = options.get('min_confidence', CONFIDENCE_THRESHOLD)
    db = SessionLocal()

    try:
        # Get job
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()

        if not job:
            logger.error(f"Job {job_id} not found")
            return

        # Start job
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.celery_task_id = self.request.id
        db.commit()

        # Initialize logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_info("=" * 60)
        job_logger.log_info("LIBRARY MIGRATION STARTED")
        job_logger.log_info("=" * 60)
        job_logger.log_info(f"Job ID: {job_id}")
        job_logger.log_info(f"Confidence threshold: {confidence_threshold}%")
        job_logger.log_info(f"Correct metadata: {options.get('correct_metadata', True)}")

        # Get libraries
        source_library = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(source_library_id)
        ).first()

        destination_library = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(destination_library_id)
        ).first()

        if not source_library or not destination_library:
            job.status = JobStatus.FAILED
            job.error_message = "Source or destination library not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        job_logger.log_info(f"Source library: {source_library.path}")
        job_logger.log_info(f"Destination library: {destination_library.path}")

        # Phase 1: Get all files from source library
        update_job_progress(db, job, progress=0, current_action="Scanning source library...")

        files = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == source_library.id
        ).all()

        job.files_total = len(files)
        db.commit()

        job_logger.log_info(f"Found {len(files)} files to process")

        if len(files) == 0:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.progress_percent = 100
            job.current_action = "No files to migrate"
            db.commit()
            return

        # Check for existing checkpoint
        checkpoint = load_checkpoint(job_id)
        start_index = 0
        if checkpoint:
            start_index = checkpoint.get('file_index', 0)
            job_logger.log_info(f"Resuming from checkpoint at file index {start_index}")

        # Initialize result logs
        success_log = checkpoint.get('success_log', []) if checkpoint else []
        failed_log = checkpoint.get('failed_log', []) if checkpoint else []
        skipped_log = checkpoint.get('skipped_log', []) if checkpoint else []
        ponder_queue = checkpoint.get('ponder_queue', []) if checkpoint else []

        # Initialize services
        mb_client = get_musicbrainz_client()
        file_organizer = get_file_organizer(db, dry_run=False)
        metadata_file_manager = MetadataFileManager(db=db)

        # Phase 2: Process each file
        job_logger.log_info("=" * 60)
        job_logger.log_info("PROCESSING FILES")
        job_logger.log_info("=" * 60)

        for i, library_file in enumerate(files[start_index:], start=start_index):
            file_path = library_file.file_path

            # Checkpoint every N files
            if (i + 1) % CHECKPOINT_INTERVAL == 0:
                save_checkpoint(job_logger, job_id, {
                    'file_index': i + 1,
                    'success_log': success_log,
                    'failed_log': failed_log,
                    'skipped_log': skipped_log,
                    'ponder_queue': ponder_queue
                })

            # Update progress (5% to 90% for file processing)
            progress = 5 + ((i + 1) / len(files) * 85)
            update_job_progress(
                db, job,
                progress=progress,
                current_action=f"Processing file {i + 1}/{len(files)}",
                files_processed=i + 1
            )

            # ========== Step 1: Check for existing MBID ==========
            success, mbid_result, skip_reason = execute_with_retry(
                lambda: MetadataWriter.verify_mbid_in_file(file_path),
                file_path
            )
            if not success:
                skipped_log.append({
                    'file_path': file_path,
                    'reason': skip_reason,
                    'ponder_eligible': False,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                job_logger.log_warning(f"SKIPPED (read error): {file_path}")
                continue

            recording_mbid = mbid_result.get('recording_mbid')
            has_mbid = mbid_result.get('has_mbid', False)

            # ========== Step 2: MBID Lookup if not present ==========
            if not has_mbid:
                # Extract metadata for lookup
                success, file_metadata, error = execute_with_retry(
                    lambda: MetadataExtractor.extract(file_path),
                    file_path
                )
                if not success:
                    skipped_log.append({
                        'file_path': file_path,
                        'reason': f"Metadata extraction failed: {error}",
                        'ponder_eligible': True,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    ponder_queue.append({
                        'file_path': file_path,
                        'reason': 'Metadata extraction failed'
                    })
                    job_logger.log_warning(f"SKIPPED (metadata error): {file_path}")
                    continue

                artist = file_metadata.get('artist')
                title = file_metadata.get('title')
                album = file_metadata.get('album')

                if not artist or not title:
                    skipped_log.append({
                        'file_path': file_path,
                        'reason': 'Missing artist or title metadata',
                        'ponder_eligible': True,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    ponder_queue.append({
                        'file_path': file_path,
                        'reason': 'Missing artist/title metadata'
                    })
                    job_logger.log_warning(f"SKIPPED (missing metadata): {file_path}")
                    continue

                # MusicBrainz lookup
                success, recordings, error = execute_with_retry(
                    lambda: mb_client.search_recording(
                        artist=artist,
                        title=title,
                        release=album,
                        limit=5
                    ),
                    file_path
                )

                if not success or not recordings:
                    skipped_log.append({
                        'file_path': file_path,
                        'reason': 'No MusicBrainz results',
                        'ponder_eligible': True,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    ponder_queue.append({
                        'file_path': file_path,
                        'reason': 'No MusicBrainz results'
                    })
                    job_logger.log_info(f"PONDER QUEUE (no MB results): {file_path}")
                    continue

                # Score matches and get best
                best_match = None
                best_score = 0
                for rec in recordings:
                    score_result = MBIDConfidenceScorer.score_match(file_metadata, rec)
                    if score_result['total_score'] > best_score:
                        best_score = score_result['total_score']
                        best_match = rec
                        best_match['_confidence'] = best_score

                if not best_match or best_score < confidence_threshold:
                    skipped_log.append({
                        'file_path': file_path,
                        'reason': f"Confidence {best_score}% < {confidence_threshold}%",
                        'ponder_eligible': True,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    ponder_queue.append({
                        'file_path': file_path,
                        'reason': f'Low confidence ({best_score}%)'
                    })
                    job_logger.log_info(f"PONDER QUEUE (low confidence {best_score}%): {file_path}")
                    continue

                # Write MBID to Comments field
                recording_mbid = best_match.get('id')
                artist_credits = best_match.get('artist-credit', [])
                artist_mbid = None
                if artist_credits and isinstance(artist_credits[0], dict):
                    artist_mbid = artist_credits[0].get('artist', {}).get('id')

                releases = best_match.get('releases', [])
                release_mbid = releases[0].get('id') if releases else None
                release_group_mbid = releases[0].get('release-group', {}).get('id') if releases else None

                success, _, error = execute_with_retry(
                    lambda: MetadataWriter.write_mbids(
                        file_path,
                        recording_mbid=recording_mbid,
                        artist_mbid=artist_mbid,
                        release_mbid=release_mbid,
                        release_group_mbid=release_group_mbid,
                        overwrite=True
                    ),
                    file_path
                )
                if not success:
                    failed_log.append({
                        'file_path': file_path,
                        'operation': 'write_mbid',
                        'error': error,
                        'attempts': MAX_RETRY_ATTEMPTS,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    job_logger.log_error(f"FAILED (write MBID): {file_path} - {error}")
                    continue

                job.files_mbid_fetched = (job.files_mbid_fetched or 0) + 1
                job_logger.log_info(f"MBID FETCHED ({best_score}%): {file_path}")

            else:
                job.files_with_mbid = (job.files_with_mbid or 0) + 1

            # ========== Step 3: Validate/correct metadata ==========
            success, validation_result, error = execute_with_retry(
                lambda: validate_and_correct_metadata(file_path, recording_mbid, mb_client, options),
                file_path
            )
            if not success or validation_result.get('status') == 'ERROR':
                failed_log.append({
                    'file_path': file_path,
                    'operation': 'validate_metadata',
                    'error': error or validation_result.get('error'),
                    'attempts': MAX_RETRY_ATTEMPTS,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                job_logger.log_error(f"FAILED (validate): {file_path}")
                continue

            # Correct metadata if needed
            if validation_result.get('corrections_made') and options.get('correct_metadata', True):
                mb_meta = validation_result.get('mb_metadata', {})
                success, _, error = execute_with_retry(
                    lambda: MetadataWriter.write_metadata(
                        file_path,
                        title=mb_meta.get('title'),
                        artist=mb_meta.get('artist'),
                        album=mb_meta.get('album'),
                        year=int(mb_meta.get('year')) if mb_meta.get('year') else None,
                        track_number=mb_meta.get('track_number'),
                        disc_number=mb_meta.get('disc_number'),
                        overwrite=True
                    ),
                    file_path
                )
                if not success:
                    failed_log.append({
                        'file_path': file_path,
                        'operation': 'correct_metadata',
                        'error': error,
                        'attempts': MAX_RETRY_ATTEMPTS,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    job_logger.log_error(f"FAILED (correct metadata): {file_path}")
                    continue

                job.files_metadata_corrected = (job.files_metadata_corrected or 0) + 1

            job.files_validated = (job.files_validated or 0) + 1

            # ========== Step 4: Write validation tag ==========
            success, _, error = execute_with_retry(
                lambda: MetadataWriter.write_validation_tag(
                    file_path,
                    status=validation_result['status'],
                    confidence=validation_result['confidence']
                ),
                file_path
            )
            if not success:
                failed_log.append({
                    'file_path': file_path,
                    'operation': 'write_validation_tag',
                    'error': error,
                    'attempts': MAX_RETRY_ATTEMPTS,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                job_logger.log_error(f"FAILED (validation tag): {file_path}")
                continue

            # ========== Step 5: Move file to destination ==========
            track_context = validation_result['track_context']

            success, move_result, error = execute_with_retry(
                lambda: file_organizer.organize_track_file(
                    file_path=file_path,
                    track_context=track_context,
                    library_root=destination_library.path,
                    file_id=library_file.id,
                    recording_mbid=UUID(recording_mbid) if recording_mbid else None,
                    release_mbid=UUID(validation_result.get('release_mbid')) if validation_result.get('release_mbid') else None,
                    job_id=UUID(job_id)
                ),
                file_path
            )
            if not success or (move_result and not move_result.success):
                error_msg = error or (move_result.error_message if move_result else 'Unknown error')
                failed_log.append({
                    'file_path': file_path,
                    'operation': 'move_file',
                    'error': error_msg,
                    'attempts': MAX_RETRY_ATTEMPTS,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                job_logger.log_error(f"FAILED (move): {file_path} - {error_msg}")
                continue

            # ========== SUCCESS ==========
            destination_path = move_result.destination_path if move_result else file_path
            success_log.append({
                'source_path': file_path,
                'destination_path': destination_path,
                'recording_mbid': recording_mbid,
                'artist_mbid': validation_result.get('artist_mbid'),
                'confidence_score': validation_result['confidence'],
                'validation_status': validation_result['status'],
                'validation_tag': f"S54:{validation_result['status']}@{validation_result['confidence']}",
                'file_renamed': str(Path(file_path).name) != str(Path(destination_path).name),
                'directory_created': str(Path(file_path).parent) != str(Path(destination_path).parent),
                'metadata_corrected': len(validation_result.get('corrections_made', [])) > 0,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })

            job.files_moved = (job.files_moved or 0) + 1
            job.files_renamed = (job.files_renamed or 0) + 1
            db.commit()

            job_logger.log_info(f"SUCCESS: {file_path} -> {destination_path}")

        # Phase 3: Auto-dispatch Ponder job if needed
        update_job_progress(db, job, progress=90, current_action="Creating follow-up job...")

        followup_job_id = None
        if ponder_queue:
            job_logger.log_info("=" * 60)
            job_logger.log_info(f"AUTO-DISPATCHING PONDER JOB for {len(ponder_queue)} files")
            job_logger.log_info("=" * 60)

            followup_job_id = dispatch_ponder_followup(
                db, job, ponder_queue, destination_library_id, job_logger
            )

            if followup_job_id:
                job.followup_job_id = followup_job_id
                job_logger.log_info(f"Ponder job created: {followup_job_id}")

        # Write final logs
        write_migration_logs(job_id, success_log, failed_log, skipped_log, ponder_queue, job_logger)

        # Complete job
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.progress_percent = 100
        job.current_action = f"Migration complete: {len(success_log)} files migrated"
        job.files_failed = len(failed_log)
        db.commit()

        # Clean up checkpoint
        checkpoint_file = f"/app/logs/checkpoint_{job_id}.json"
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)

        job_logger.log_info("=" * 60)
        job_logger.log_info("LIBRARY MIGRATION COMPLETED")
        job_logger.log_info("=" * 60)

    except SoftTimeLimitExceeded:
        logger.warning(f"Migration job {job_id} soft time limit exceeded")
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = "Job exceeded time limit - can be resumed"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        logger.error(f"Migration job {job_id} failed: {e}\n{traceback.format_exc()}")
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.last_error_details = traceback.format_exc()
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


def dispatch_ponder_followup(
    db: Session,
    parent_job: FileOrganizationJob,
    ponder_queue: list,
    destination_library_id: str,
    job_logger: JobLogger
) -> UUID:
    """
    Create and immediately dispatch Ponder job for files that couldn't be matched.
    Job is created with status=PENDING and Celery task dispatched immediately.
    NO PAUSED STATE - fully automated.
    """
    if not ponder_queue:
        job_logger.log_info("No files for Ponder - all files matched via MusicBrainz API")
        return None

    # Create job in PENDING state (NOT PAUSED!)
    followup_job = FileOrganizationJob(
        job_type=JobType.MIGRATION_FINGERPRINT,
        status=JobStatus.PENDING,
        source_library_path_id=parent_job.source_library_path_id,
        destination_library_path_id=UUID(destination_library_id),
        parent_job_id=parent_job.id,
        files_total=len(ponder_queue),
        files_without_mbid=len(ponder_queue),
        files_without_mbid_json=json.dumps(ponder_queue)
    )
    db.add(followup_job)
    db.commit()

    # Immediately dispatch Celery task
    try:
        result = migration_fingerprint_task.delay(
            str(followup_job.id),
            str(parent_job.id)
        )
        followup_job.celery_task_id = result.id
        db.commit()

        job_logger.log_info(f"Auto-dispatched Ponder job {followup_job.id} for {len(ponder_queue)} files")
        return followup_job.id

    except Exception as e:
        job_logger.log_error(f"Failed to dispatch Ponder job: {e}")
        followup_job.status = JobStatus.FAILED
        followup_job.error_message = f"Failed to dispatch: {e}"
        db.commit()
        return followup_job.id


# ========================================
# Fingerprint Follow-up Task
# ========================================

@shared_task(bind=True, base=CheckpointableTask, soft_time_limit=7200, time_limit=7260)
def migration_fingerprint_task(self, job_id: str, parent_job_id: str):
    """
    Follow-up task for files that couldn't be matched via MusicBrainz API.
    Uses MUSE Ponder service for Chromaprint audio fingerprint identification.

    AUTOMATICALLY DISPATCHED AND RUNS IMMEDIATELY - NO PAUSED STATE.
    """
    db = SessionLocal()

    try:
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()

        if not job:
            logger.error(f"Ponder job {job_id} not found")
            return

        # Start job
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.celery_task_id = self.request.id
        db.commit()

        # Initialize logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_info("=" * 60)
        job_logger.log_info("PONDER FINGERPRINT JOB STARTED")
        job_logger.log_info("=" * 60)
        job_logger.log_info(f"Job ID: {job_id}")
        job_logger.log_info(f"Parent job: {parent_job_id}")

        # Get destination library
        destination_library = db.query(LibraryPath).filter(
            LibraryPath.id == job.destination_library_path_id
        ).first()

        if not destination_library:
            job.status = JobStatus.FAILED
            job.error_message = "Destination library not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Load files to process
        ponder_queue = json.loads(job.files_without_mbid_json or '[]')
        job_logger.log_info(f"Processing {len(ponder_queue)} files via Ponder fingerprinting")

        if not ponder_queue:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.progress_percent = 100
            job.current_action = "No files to process"
            db.commit()
            return

        # Initialize services
        ponder_client = get_ponder_client()
        file_organizer = get_file_organizer(db, dry_run=False)
        mb_client = get_musicbrainz_client()

        success_log = []
        failed_log = []

        for i, item in enumerate(ponder_queue):
            file_path = item.get('file_path')

            # Update progress
            progress = (i + 1) / len(ponder_queue) * 100
            update_job_progress(
                db, job,
                progress=progress,
                current_action=f"Fingerprinting file {i + 1}/{len(ponder_queue)}",
                files_processed=i + 1
            )

            job_logger.log_info(f"Processing: {file_path}")

            # Try Ponder identification
            try:
                ponder_result = ponder_client.identify_file(
                    file_path,
                    use_fingerprint=True,
                    overwrite_existing=True
                )

                if not ponder_result.get('success'):
                    failed_log.append({
                        'file_path': file_path,
                        'operation': 'ponder_identify',
                        'error': ponder_result.get('error', 'Unknown error'),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    job.files_failed = (job.files_failed or 0) + 1
                    job_logger.log_warning(f"FAILED (Ponder): {file_path}")
                    continue

                recording_mbid = ponder_result.get('recording_mbid')
                if not recording_mbid:
                    failed_log.append({
                        'file_path': file_path,
                        'operation': 'ponder_identify',
                        'error': 'No recording MBID returned',
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    job.files_failed = (job.files_failed or 0) + 1
                    job_logger.log_warning(f"FAILED (no MBID): {file_path}")
                    continue

                job_logger.log_info(f"Ponder match: {recording_mbid} ({ponder_result.get('match_method')})")

                # Validate and correct metadata
                validation_result = validate_and_correct_metadata(
                    file_path, recording_mbid, mb_client, {'correct_metadata': True}
                )

                if validation_result.get('status') == 'ERROR':
                    failed_log.append({
                        'file_path': file_path,
                        'operation': 'validate_metadata',
                        'error': validation_result.get('error'),
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    job.files_failed = (job.files_failed or 0) + 1
                    continue

                # Write validation tag with FINGERPRINT status
                MetadataWriter.write_validation_tag(
                    file_path,
                    status='FINGERPRINT',
                    confidence=ponder_result.get('match_score', 80)
                )

                # Move file to destination
                track_context = validation_result['track_context']
                move_result = file_organizer.organize_track_file(
                    file_path=file_path,
                    track_context=track_context,
                    library_root=destination_library.path,
                    recording_mbid=UUID(recording_mbid),
                    job_id=UUID(job_id)
                )

                if not move_result.success:
                    failed_log.append({
                        'file_path': file_path,
                        'operation': 'move_file',
                        'error': move_result.error_message,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
                    job.files_failed = (job.files_failed or 0) + 1
                    continue

                # Success
                success_log.append({
                    'source_path': file_path,
                    'destination_path': move_result.destination_path,
                    'recording_mbid': recording_mbid,
                    'match_method': ponder_result.get('match_method'),
                    'match_score': ponder_result.get('match_score'),
                    'validation_tag': f"S54:FINGERPRINT@{ponder_result.get('match_score', 80)}",
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })

                job.files_moved = (job.files_moved or 0) + 1
                job.files_renamed = (job.files_renamed or 0) + 1
                db.commit()

                job_logger.log_info(f"SUCCESS: {file_path} -> {move_result.destination_path}")

            except PonderClientError as e:
                failed_log.append({
                    'file_path': file_path,
                    'operation': 'ponder_identify',
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                job.files_failed = (job.files_failed or 0) + 1
                job_logger.log_error(f"FAILED (Ponder error): {file_path} - {e}")

            except Exception as e:
                failed_log.append({
                    'file_path': file_path,
                    'operation': 'unknown',
                    'error': str(e),
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                job.files_failed = (job.files_failed or 0) + 1
                job_logger.log_error(f"FAILED (exception): {file_path} - {e}")

        # Write logs
        log_dir = "/app/logs"
        with open(f"{log_dir}/ponder_{job_id}_success.json", 'w') as f:
            json.dump({"count": len(success_log), "files": success_log}, f, indent=2, default=str)
        with open(f"{log_dir}/ponder_{job_id}_failed.json", 'w') as f:
            json.dump({"count": len(failed_log), "files": failed_log}, f, indent=2, default=str)

        # Complete job
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.progress_percent = 100
        job.current_action = f"Ponder complete: {len(success_log)} files migrated, {len(failed_log)} failed"
        db.commit()

        job_logger.log_info("=" * 60)
        job_logger.log_info("PONDER FINGERPRINT JOB COMPLETED")
        job_logger.log_info(f"SUCCESS: {len(success_log)} files")
        job_logger.log_info(f"FAILED: {len(failed_log)} files")
        job_logger.log_info("=" * 60)

    except SoftTimeLimitExceeded:
        logger.warning(f"Ponder job {job_id} soft time limit exceeded")
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = "Job exceeded time limit"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        logger.error(f"Ponder job {job_id} failed: {e}\n{traceback.format_exc()}")
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.last_error_details = traceback.format_exc()
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()
