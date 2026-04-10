"""
File Organization Tasks
Celery tasks for MBID-based file organization, validation, and rollback
"""

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
import traceback
import logging

from app.database import SessionLocal
from app.models.library import LibraryPath, LibraryFile
from app.models.file_organization_job import FileOrganizationJob, JobStatus, JobType
from app.services.metadata_writer import MetadataWriter
from app.shared_services import (
    FileOrganizer,
    NamingEngine,
    AtomicFileOps,
    AuditLogger,
    MetadataFileManager,
    PathValidator,
    TrackContext
)
from app.shared_services.job_logger import JobLogger
from app.tasks.checkpoint_mixin import CheckpointableTask

import threading

logger = logging.getLogger(__name__)

# Bulk operation batch size - minimum 100 files per batch with detailed logging
BATCH_SIZE = 100  # Process files in batches of 100


class BackgroundHeartbeat:
    """
    Background thread that keeps job heartbeat alive during long-running operations.

    Uses its own DB session to update last_heartbeat_at independently of the main
    processing thread. This prevents stall detection when blocking on MusicBrainz API
    calls, file I/O, or other long operations.

    Usage:
        with BackgroundHeartbeat(job_id, FileOrganizationJob, interval=60):
            # ... long-running processing ...
    """

    def __init__(self, job_id: str, job_model_class, interval: int = 60):
        self.job_id = job_id
        self.job_model_class = job_model_class
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _heartbeat_loop(self):
        while not self._stop_event.wait(self.interval):
            try:
                heartbeat_db = SessionLocal()
                try:
                    job = heartbeat_db.query(self.job_model_class).filter(
                        self.job_model_class.id == self.job_id
                    ).first()
                    if job:
                        job.last_heartbeat_at = datetime.now(timezone.utc)
                        heartbeat_db.commit()
                finally:
                    heartbeat_db.close()
            except Exception:
                pass  # Don't let heartbeat errors crash the main task


# ========================================
# Error Categorization for Non-Fatal Errors
# ========================================

class ErrorCategory:
    """Categorize errors as fatal or non-fatal for job failure tracking"""
    FILE_NOT_EXIST = "file_not_exist"
    ALREADY_EXISTS = "already_exists"
    PERMISSION_ERROR = "permission_error"
    OTHER = "other"

    # Non-fatal errors - don't count toward job failure threshold
    NON_FATAL_CATEGORIES = {FILE_NOT_EXIST, ALREADY_EXISTS}


class ErrorTracker:
    """
    Track and categorize errors during file organization.
    Non-fatal errors (file not exist, already exists) are logged but don't fail the job.
    """

    def __init__(self):
        self.errors = {
            ErrorCategory.FILE_NOT_EXIST: [],
            ErrorCategory.ALREADY_EXISTS: [],
            ErrorCategory.PERMISSION_ERROR: [],
            ErrorCategory.OTHER: [],
        }
        self.fatal_error_count = 0

    def categorize_error(self, error_message: str) -> str:
        """Categorize an error message into a category"""
        error_lower = error_message.lower()

        if "does not exist" in error_lower or "not found" in error_lower or "no such file" in error_lower:
            return ErrorCategory.FILE_NOT_EXIST
        elif "already exists" in error_lower or "file exists" in error_lower:
            return ErrorCategory.ALREADY_EXISTS
        elif "permission" in error_lower or "access denied" in error_lower:
            return ErrorCategory.PERMISSION_ERROR
        else:
            return ErrorCategory.OTHER

    def add_error(self, file_path: str, error_message: str) -> bool:
        """
        Add an error and return True if it's a fatal error (counts toward job failure).

        Returns:
            True if this is a fatal error that should count toward MAX_MOVE_FAILURES
            False if this is a non-fatal error (file not exist, already exists)
        """
        category = self.categorize_error(error_message)
        self.errors[category].append({
            'file_path': file_path,
            'error': error_message
        })

        # Only count as fatal if not in non-fatal categories
        is_fatal = category not in ErrorCategory.NON_FATAL_CATEGORIES
        if is_fatal:
            self.fatal_error_count += 1

        return is_fatal

    def get_total_errors(self) -> int:
        """Get total number of all errors (including non-fatal)"""
        return sum(len(errors) for errors in self.errors.values())

    def get_fatal_error_count(self) -> int:
        """Get count of fatal errors only"""
        return self.fatal_error_count

    def generate_report(self, job_logger) -> dict:
        """
        Generate an error report and log it.

        Returns dict with error statistics and details.
        """
        report = {
            'total_errors': self.get_total_errors(),
            'fatal_errors': self.fatal_error_count,
            'non_fatal_errors': self.get_total_errors() - self.fatal_error_count,
            'by_category': {}
        }

        # Log report header
        job_logger.log_info("=" * 60)
        job_logger.log_info("ERROR REPORT SUMMARY")
        job_logger.log_info("=" * 60)

        for category, errors in self.errors.items():
            if errors:
                is_non_fatal = category in ErrorCategory.NON_FATAL_CATEGORIES
                category_label = f"{category} ({'non-fatal' if is_non_fatal else 'FATAL'})"

                report['by_category'][category] = {
                    'count': len(errors),
                    'is_fatal': not is_non_fatal,
                    'files': [e['file_path'] for e in errors]
                }

                job_logger.log_info(f"\n{category_label}: {len(errors)} error(s)")

                # Log first 10 files for each category
                for i, err in enumerate(errors[:10]):
                    job_logger.log_info(f"  - {err['file_path']}")
                    job_logger.log_info(f"    Error: {err['error']}")

                if len(errors) > 10:
                    job_logger.log_info(f"  ... and {len(errors) - 10} more")

        job_logger.log_info("=" * 60)
        job_logger.log_info(f"TOTALS: {report['total_errors']} total errors")
        job_logger.log_info(f"  - Non-fatal (file not exist/already exists): {report['non_fatal_errors']}")
        job_logger.log_info(f"  - Fatal (counted toward job failure): {report['fatal_errors']}")
        job_logger.log_info("=" * 60)

        return report


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


def acquire_job_with_lock(
    db: Session,
    job_id: str,
    celery_task_id: str = None,
    allow_resume: bool = False
) -> FileOrganizationJob:
    """
    Acquire a job with row-level locking to prevent race conditions.

    Uses SELECT ... FOR UPDATE to ensure only one worker can acquire the job.
    Only acquires jobs in PENDING status (or FAILED status if allow_resume=True).

    Args:
        db: Database session
        job_id: Job UUID string
        celery_task_id: Celery task ID for tracking
        allow_resume: If True, also allow acquiring FAILED jobs for resumption

    Returns:
        FileOrganizationJob if successfully acquired, None otherwise
    """
    try:
        # Lock the row and check status atomically
        job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).with_for_update(nowait=True).first()

        if not job:
            logger.error(f"Job {job_id} not found")
            return None

        # Only acquire if job is in valid status
        valid_statuses = [JobStatus.PENDING]
        if allow_resume:
            valid_statuses.append(JobStatus.FAILED)

        if job.status not in valid_statuses:
            logger.warning(f"Job {job_id} is not in valid status for acquisition (status: {job.status}), skipping")
            return None

        # Track if this is a resume
        is_resume = job.status == JobStatus.FAILED

        # Update status atomically while holding the lock
        job.status = JobStatus.RUNNING
        # Only update started_at for new jobs, not resumes
        if not is_resume or not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        job.last_heartbeat_at = datetime.now(timezone.utc)
        if celery_task_id:
            job.celery_task_id = celery_task_id

        db.commit()
        logger.info(f"Successfully acquired job {job_id} (resume={is_resume})")
        return job

    except Exception as e:
        # Lock acquisition failed (another worker has it) or other error
        db.rollback()
        logger.warning(f"Failed to acquire job {job_id}: {e}")
        return None


def update_job_progress(
    db: Session,
    job: FileOrganizationJob,
    progress_percent: float = None,
    current_action: str = None,
    files_processed: int = None,
    files_renamed: int = None,
    files_moved: int = None,
    files_failed: int = None
):
    """Update job progress in database with heartbeat"""
    try:
        if progress_percent is not None:
            job.progress_percent = progress_percent
        if current_action is not None:
            job.current_action = current_action
        if files_processed is not None:
            job.files_processed = files_processed
        if files_renamed is not None:
            job.files_renamed += files_renamed
        if files_moved is not None:
            job.files_moved += files_moved
        if files_failed is not None:
            job.files_failed += files_failed

        # Always update heartbeat to indicate job is still alive
        job.last_heartbeat_at = datetime.now(timezone.utc)

        db.commit()
    except Exception as e:
        logger.error(f"Error updating job progress: {e}")
        db.rollback()


def cleanup_empty_directories(
    source_paths: list,
    library_root: str,
    job_logger=None
) -> int:
    """
    Remove empty directories left behind after files are moved.

    Walks up from each source file's parent directory, removing empty dirs
    until reaching the library root or a non-empty directory.

    Args:
        source_paths: List of original file paths that were moved
        library_root: Root library path (will NOT be removed)
        job_logger: Optional JobLogger for logging

    Returns:
        Number of directories removed
    """
    deleted_count = 0
    root = Path(library_root).resolve()
    already_checked = set()

    # Collect unique parent directories from source paths
    parent_dirs = set()
    for file_path in source_paths:
        parent = Path(file_path).parent
        parent_dirs.add(parent)

    # Sort deepest first so we clean children before parents
    sorted_dirs = sorted(parent_dirs, key=lambda p: len(p.parts), reverse=True)

    for dir_path in sorted_dirs:
        # Walk up from this directory toward the library root
        current = dir_path
        while True:
            try:
                resolved = current.resolve()
            except OSError:
                break

            # Don't remove the library root or go above it
            if resolved == root or not str(resolved).startswith(str(root)):
                break

            # Skip if already checked
            if resolved in already_checked:
                break
            already_checked.add(resolved)

            # Skip if doesn't exist or is not empty
            if not current.exists() or not current.is_dir():
                break
            if any(current.iterdir()):
                break

            # Remove empty directory
            try:
                current.rmdir()
                deleted_count += 1
                if job_logger:
                    job_logger.log_info(f"Removed empty directory: {current}")
                logger.info(f"Removed empty directory: {current}")
            except OSError as e:
                logger.warning(f"Could not remove directory {current}: {e}")
                break

            # Move up to parent
            current = current.parent

    if deleted_count > 0 and job_logger:
        job_logger.log_info(f"Cleaned up {deleted_count} empty directories")

    return deleted_count


def get_library_files_for_organization(
    db: Session,
    library_path_id: UUID = None,
    artist_id: UUID = None,
    album_id: UUID = None,
    album_mbid: str = None,
    only_with_mbid: bool = True,
    only_unorganized: bool = True
) -> list:
    """
    Get library files that need organization from Studio54 database

    Uses metadata directly from library_files table (extracted from ID3 tags).
    Does NOT require matching tracks table entries.

    Returns list of dicts with file metadata for organization
    """
    where_clauses = []
    params = {}

    if library_path_id:
        where_clauses.append("lf.library_path_id = :library_path_id")
        params['library_path_id'] = str(library_path_id)

    if artist_id:
        where_clauses.append("lf.musicbrainz_artistid = (SELECT musicbrainz_id FROM artists WHERE id = :artist_id)")
        params['artist_id'] = str(artist_id)

    if album_id:
        where_clauses.append("lf.musicbrainz_albumid = (SELECT musicbrainz_id FROM albums WHERE id = :album_id)")
        params['album_id'] = str(album_id)

    if album_mbid:
        where_clauses.append("lf.musicbrainz_releasegroupid = :album_mbid")
        params['album_mbid'] = album_mbid

    if only_with_mbid:
        where_clauses.append("lf.musicbrainz_trackid IS NOT NULL")

    if only_unorganized:
        where_clauses.append("(lf.is_organized = false OR lf.is_organized IS NULL)")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Query uses metadata directly from library_files (from ID3 tags)
    # No join with tracks table required
    query = text(f"""
        SELECT
            lf.id as file_id,
            lf.file_path,
            COALESCE(lf.album_artist, lf.artist, 'Unknown Artist') as artist_name,
            COALESCE(lf.album, 'Unknown Album') as album_title,
            COALESCE(lf.title, lf.file_name) as track_title,
            COALESCE(lf.track_number, 1) as track_number,
            lf.year as release_year,
            COALESCE(lf.disc_number, 1) as disc_number,
            1 as total_discs,
            'Album' as album_type,
            false as is_compilation,
            LOWER(lf.format) as file_extension,
            lf.musicbrainz_trackid as recording_mbid,
            lf.musicbrainz_albumid as release_mbid,
            lf.musicbrainz_releasegroupid as release_group_mbid,
            lf.musicbrainz_artistid as artist_mbid
        FROM library_files lf
        WHERE {where_sql}
        ORDER BY artist_name, album_title, disc_number, track_number
    """)

    result = db.execute(query, params)
    rows = result.fetchall()

    return [
        {
            'file_id': row[0],
            'file_path': row[1],
            'artist_name': row[2],
            'album_title': row[3],
            'track_title': row[4],
            'track_number': row[5],
            'release_year': row[6],
            'disc_number': row[7],
            'total_discs': row[8],
            'album_type': row[9],
            'is_compilation': row[10],
            'file_extension': row[11],
            'recording_mbid': row[12],
            'release_mbid': row[13],
            'release_group_mbid': row[14],
            'artist_mbid': row[15]  # Now using MBID from library_files
        }
        for row in rows
    ]


# ========================================
# Organization Tasks
# ========================================

@shared_task(bind=True, soft_time_limit=43200, time_limit=43500)  # 12 hour limit for large libraries
def organize_library_files_task(self, job_id: str, library_path_id: str, options: dict):
    """
    Organize all files in a library

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Library UUID
        options: Organization options dict
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting library organization job {job_id} for library path {library_path_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Update heartbeat during initialization
        update_job_progress(db, job, current_action="Initializing job...")

        # Get library path
        from app.models.library import LibraryPath
        library_path = db.query(LibraryPath).filter(LibraryPath.id == UUID(library_path_id)).first()
        if not library_path:
            job_logger.log_job_error(f"Library path {library_path_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Library path {library_path_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Log job start
        job_logger.log_job_start("organize_library", library_path.path)

        # Get files to organize
        job_logger.log_phase_start("File Discovery", f"Scanning library path: {library_path.path}")
        update_job_progress(db, job, current_action=f"Discovering files in {library_path.path}...")

        files = get_library_files_for_organization(
            db=db,
            library_path_id=UUID(library_path_id),
            only_with_mbid=options.get('only_with_mbid', True),
            only_unorganized=options.get('only_unorganized', True)
        )

        # Update heartbeat and file count after discovery
        job.files_total = len(files)
        update_job_progress(db, job, current_action=f"Found {len(files)} files to organize")

        logger.info(f"Found {len(files)} files to organize")
        job_logger.log_phase_complete("File Discovery", count=len(files))

        if len(files) == 0:
            job_logger.log_info("No files found to organize")
            job_logger.log_job_complete({
                'files_total': 0,
                'files_processed': 0,
                'files_renamed': 0,
                'files_moved': 0,
                'files_failed': 0
            })
            job.status = JobStatus.COMPLETED
            job.progress_percent = 100.0
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Initialize file organizer with dry_run mode
        file_organizer = get_file_organizer(db, dry_run=options.get('dry_run', False))

        # Start organization phase
        job_logger.log_phase_start(
            "File Organization",
            f"Organizing {len(files)} files in batches of {BATCH_SIZE}"
        )

        # Process files in batches
        # CRITICAL: Track move failures - fail job if >5 FATAL moves fail
        # Non-fatal errors (file not exist, already exists) are logged but don't fail job
        MAX_MOVE_FAILURES = 5
        error_tracker = ErrorTracker()
        total_batches = (len(files) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(files))
            batch = files[start_idx:end_idx]

            job_logger.log_batch_operation(
                "organize",
                count=len(batch),
                description=f"Batch {batch_num + 1}/{total_batches}"
            )

            for idx, file_data in enumerate(batch):
                global_idx = start_idx + idx

                try:
                    file_name = Path(file_data['file_path']).name
                    update_job_progress(
                        db, job,
                        current_action=f"Organizing {file_name}"
                    )

                    # Build track context
                    track_context = TrackContext(
                        artist_name=file_data['artist_name'] or 'Unknown Artist',
                        album_title=file_data['album_title'] or 'Unknown Album',
                        track_title=file_data['track_title'] or 'Unknown Track',
                        track_number=file_data['track_number'] or 1,
                        release_year=file_data['release_year'],
                        disc_number=file_data['disc_number'] or 1,
                        total_discs=file_data['total_discs'] or 1,
                        medium_format='CD',  # Default to CD
                        album_type=file_data['album_type'] or 'Album',
                        file_extension=file_data['file_extension'] or 'flac',
                        is_compilation=file_data['is_compilation'] or False
                    )

                    # Organize file (moves validated via checksum, no backup)
                    file_id_uuid = UUID(str(file_data['file_id'])) if file_data.get('file_id') else None
                    result = file_organizer.organize_track_file(
                        file_path=file_data['file_path'],
                        track_context=track_context,
                        library_root=library_path.path,
                        file_id=file_id_uuid,
                        job_id=UUID(job_id)
                    )

                    if result.success:
                        # Update Track.file_path if file was moved/renamed
                        if result.destination_path and result.destination_path != file_data['file_path']:
                            try:
                                db.execute(
                                    text("UPDATE tracks SET file_path = :new_path WHERE file_path = :old_path"),
                                    {'new_path': result.destination_path, 'old_path': file_data['file_path']}
                                )
                                db.commit()
                            except Exception as track_err:
                                logger.warning(f"Could not update Track.file_path: {track_err}")
                                db.rollback()

                        # Log successful operations based on operation type
                        from app.shared_services.atomic_file_ops import OperationType
                        if result.operation_type == OperationType.RENAME:
                            update_job_progress(db, job, files_renamed=1)
                            job_logger.log_file_operation(
                                operation="rename",
                                source_path=file_data['file_path'],
                                destination_path=result.destination_path,
                                success=True
                            )
                        elif result.operation_type == OperationType.MOVE:
                            update_job_progress(db, job, files_moved=1)
                            job_logger.log_file_operation(
                                operation="move",
                                source_path=file_data['file_path'],
                                destination_path=result.destination_path,
                                success=True
                            )
                        else:
                            # File was already in correct location
                            job_logger.log_file_operation(
                                operation="skip",
                                source_path=file_data['file_path'],
                                success=True
                            )
                    else:
                        # TRACK ERRORS - categorize as fatal or non-fatal
                        is_fatal = error_tracker.add_error(file_data['file_path'], result.error_message)
                        update_job_progress(db, job, files_failed=1)
                        job_logger.log_file_operation(
                            operation="organize",
                            source_path=file_data['file_path'],
                            success=False,
                            error=result.error_message
                        )

                        if is_fatal:
                            job_logger.log_warning(
                                f"ALERT: Fatal error {error_tracker.get_fatal_error_count()}/{MAX_MOVE_FAILURES} - "
                                f"Failed to organize {file_data['file_path']}: {result.error_message}"
                            )
                            logger.warning(f"Fatal error {error_tracker.get_fatal_error_count()}: {file_data['file_path']}")

                            # FAIL JOB if more than 5 FATAL move failures
                            if error_tracker.get_fatal_error_count() > MAX_MOVE_FAILURES:
                                # Generate error report before failing
                                error_tracker.generate_report(job_logger)
                                error_msg = (
                                    f"CRITICAL: Job failed - exceeded maximum fatal errors ({MAX_MOVE_FAILURES}). "
                                    f"Fatal errors: {error_tracker.get_fatal_error_count()}, "
                                    f"Non-fatal errors: {error_tracker.get_total_errors() - error_tracker.get_fatal_error_count()}. "
                                    f"Stopping job to prevent data loss."
                                )
                                job_logger.log_error(error_msg)
                                logger.error(error_msg)
                                job.status = JobStatus.FAILED
                                job.error_message = error_msg
                                job.completed_at = datetime.now(timezone.utc)
                                db.commit()
                                return
                        else:
                            # Non-fatal error (file not exist, already exists) - log but continue
                            job_logger.log_info(
                                f"Non-fatal error (skipping): {file_data['file_path']}: {result.error_message}"
                            )

                    # Update progress
                    progress = ((global_idx + 1) / len(files)) * 100
                    update_job_progress(db, job, progress_percent=progress, files_processed=global_idx + 1)

                except Exception as e:
                    # Categorize exception errors too
                    is_fatal = error_tracker.add_error(file_data['file_path'], str(e))
                    logger.error(f"Error organizing file {file_data['file_path']}: {e}")
                    update_job_progress(db, job, files_failed=1)
                    job_logger.log_file_operation(
                        operation="organize",
                        source_path=file_data['file_path'],
                        success=False,
                        error=str(e)
                    )

                    if is_fatal:
                        job_logger.log_warning(
                            f"ALERT: Fatal error {error_tracker.get_fatal_error_count()}/{MAX_MOVE_FAILURES} - Exception: {e}"
                        )

                        # FAIL JOB if more than 5 FATAL move failures
                        if error_tracker.get_fatal_error_count() > MAX_MOVE_FAILURES:
                            # Generate error report before failing
                            error_tracker.generate_report(job_logger)
                            error_msg = (
                                f"CRITICAL: Job failed - exceeded maximum fatal errors ({MAX_MOVE_FAILURES}). "
                                f"Fatal errors: {error_tracker.get_fatal_error_count()}, "
                                f"Non-fatal errors: {error_tracker.get_total_errors() - error_tracker.get_fatal_error_count()}. "
                                f"Stopping job to prevent data loss."
                            )
                            job_logger.log_error(error_msg)
                            logger.error(error_msg)
                            job.status = JobStatus.FAILED
                            job.error_message = error_msg
                            job.completed_at = datetime.now(timezone.utc)
                            db.commit()
                            return
                    else:
                        # Non-fatal error (file not exist, already exists) - log but continue
                        job_logger.log_info(
                            f"Non-fatal error (skipping): {file_data['file_path']}: {e}"
                        )

            # Log batch completion
            job_logger.log_info(f"Completed batch {batch_num + 1}/{total_batches}")

        job_logger.log_phase_complete("File Organization", count=len(files))

        # MANDATORY: Create .mbid.json metadata files for organized albums
        # This is required but errors should not fail the entire job
        if not options.get('dry_run', False):
            job_logger.log_phase_start("Metadata Creation", "Creating album metadata files (MANDATORY)")
            logger.info("Creating album metadata files (MANDATORY)")
            update_job_progress(db, job, current_action="Creating album metadata files")

            metadata_manager = MetadataFileManager(db=db)
            metadata_success = 0
            metadata_failed = 0

            # Get unique albums that were organized - group by album directory
            organized_albums = db.execute(text("""
                SELECT DISTINCT
                    al.id as album_id,
                    a.name as artist_name,
                    a.musicbrainz_id as artist_mbid,
                    al.title as album_title,
                    al.musicbrainz_id as release_mbid,
                    al.release_group_mbid,
                    EXTRACT(YEAR FROM al.release_date)::int as release_year,
                    al.album_type,
                    lf.file_path
                FROM library_files lf
                JOIN tracks t ON t.file_path = lf.file_path
                JOIN albums al ON t.album_id = al.id
                JOIN artists a ON al.artist_id = a.id
                WHERE lf.library_path_id = :library_path_id
                AND lf.is_organized = true
                ORDER BY a.name, al.title
            """), {'library_path_id': str(library_path_id)}).fetchall()

            # Group by album to get unique albums
            albums_by_id = {}
            for row in organized_albums:
                album_id = row[0]
                if album_id not in albums_by_id:
                    albums_by_id[album_id] = {
                        'album_id': album_id,
                        'artist_name': row[1],
                        'artist_mbid': row[2],
                        'album_title': row[3],
                        'release_mbid': row[4],
                        'release_group_mbid': row[5],
                        'release_year': row[6],
                        'album_type': row[7] or 'Album',
                        'sample_file_path': row[8]
                    }

            job_logger.log_info(f"Creating metadata files for {len(albums_by_id)} unique albums")

            for album_id, album_info in albums_by_id.items():
                try:
                    # Determine album directory from sample file path
                    album_dir = str(Path(album_info['sample_file_path']).parent)

                    # Create metadata file
                    result = metadata_manager.create_album_metadata_file(
                        album_id=album_id,
                        album_directory=album_dir,
                        album_title=album_info['album_title'],
                        artist_name=album_info['artist_name'],
                        artist_mbid=album_info['artist_mbid'],
                        release_year=album_info['release_year'],
                        album_type=album_info['album_type'],
                        release_mbid=album_info['release_mbid'],
                        release_group_mbid=album_info['release_group_mbid'],
                        organization_job_id=UUID(job_id),
                        organized_by='organization_task'
                    )

                    if result:
                        metadata_success += 1
                        job_logger.log_info(f"Created .mbid.json for: {album_info['artist_name']} - {album_info['album_title']}")
                    else:
                        metadata_failed += 1
                        # ALERT: Log warning but continue processing
                        job_logger.log_warning(
                            f"ALERT: Failed to create .mbid.json for album {album_info['album_title']} "
                            f"in {album_dir} - continuing with other albums"
                        )
                        logger.warning(f"ALERT: Failed to create .mbid.json for {album_info['album_title']}")

                except Exception as e:
                    metadata_failed += 1
                    # ALERT: Log error but continue processing
                    job_logger.log_error(
                        f"ALERT: Error creating .mbid.json for album {album_info['album_title']}: {e} "
                        f"- continuing with other albums"
                    )
                    logger.error(f"ALERT: Error creating .mbid.json for {album_info['album_title']}: {e}")
                    # Continue processing - don't fail the job

            job_logger.log_phase_complete("Metadata Creation", count=metadata_success)
            job_logger.log_info(
                f"Metadata file creation complete: {metadata_success} created, {metadata_failed} failed"
            )

            # Log alert summary if any failures
            if metadata_failed > 0:
                job_logger.log_warning(
                    f"ALERT SUMMARY: {metadata_failed} metadata file(s) could not be created. "
                    f"Check logs for details. Job will continue."
                )

        # Generate error report if any errors occurred
        if error_tracker.get_total_errors() > 0:
            error_tracker.generate_report(job_logger)

        # Complete job
        job_logger.log_job_complete({
            'files_total': job.files_total,
            'files_processed': job.files_processed,
            'files_renamed': job.files_renamed,
            'files_moved': job.files_moved,
            'files_failed': job.files_failed,
            'fatal_errors': error_tracker.get_fatal_error_count(),
            'non_fatal_errors': error_tracker.get_total_errors() - error_tracker.get_fatal_error_count()
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = "Organization complete"
        db.commit()

        logger.info(f"Completed library organization job {job_id}")

    except SoftTimeLimitExceeded:
        logger.warning(f"Job {job_id} exceeded time limit")
        if 'job_logger' in locals():
            job_logger.log_job_error("Job exceeded time limit")
        job.status = JobStatus.FAILED
        job.error_message = "Job exceeded time limit"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        logger.error(f"Error in library organization job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)  # 1 hour limit
def organize_artist_files_task(self, job_id: str, artist_id: str, options: dict):
    """
    Organize all files for a specific artist

    Args:
        job_id: FileOrganizationJob ID
        artist_id: Artist UUID
        options: Organization options dict
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting artist organization job {job_id} for artist {artist_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Update heartbeat during initialization
        update_job_progress(db, job, current_action="Initializing job...")

        # Get artist info
        artist_query = text("SELECT name FROM artists WHERE id = :artist_id")
        result = db.execute(artist_query, {'artist_id': artist_id})
        artist = result.first()

        if not artist:
            job_logger.log_job_error(f"Artist {artist_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Artist {artist_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        artist_name = artist[0]
        job_logger.log_job_start("organize_artist", artist_name)

        # Update heartbeat after getting artist info
        update_job_progress(db, job, current_action=f"Looking up library for {artist_name}...")

        # Get library for this artist (from first file)
        # Join library_files with library_paths, matching by artist's MusicBrainz ID
        library_query = text("""
            SELECT DISTINCT lp.id, lp.path
            FROM library_paths lp
            JOIN library_files lf ON lf.library_path_id = lp.id
            WHERE lf.musicbrainz_artistid = (SELECT musicbrainz_id FROM artists WHERE id = :artist_id)
            LIMIT 1
        """)
        result = db.execute(library_query, {'artist_id': artist_id})
        library_row = result.first()

        if not library_row:
            job.status = JobStatus.FAILED
            job.error_message = f"No library found for artist {artist_id}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        library_path = library_row[1]

        # Get files to organize
        job_logger.log_phase_start("File Discovery", f"Scanning files for artist: {artist_name}")
        update_job_progress(db, job, current_action=f"Discovering files for {artist_name}...")

        files = get_library_files_for_organization(
            db=db,
            artist_id=UUID(artist_id),
            only_with_mbid=options.get('only_with_mbid', True),
            only_unorganized=options.get('only_unorganized', True)
        )

        # Update heartbeat and file count after discovery
        job.files_total = len(files)
        update_job_progress(db, job, current_action=f"Found {len(files)} files to organize")

        logger.info(f"Found {len(files)} files to organize for artist {artist_name}")
        job_logger.log_phase_complete("File Discovery", count=len(files))

        if len(files) == 0:
            job_logger.log_info("No files found to organize")
            job_logger.log_job_complete({
                'files_total': 0,
                'files_processed': 0,
                'files_renamed': 0,
                'files_moved': 0,
                'files_failed': 0
            })
            job.status = JobStatus.COMPLETED
            job.progress_percent = 100.0
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Initialize file organizer with dry_run mode
        file_organizer = get_file_organizer(db, dry_run=options.get('dry_run', False))

        # Start organization phase
        job_logger.log_phase_start(
            "File Organization",
            f"Organizing {len(files)} files for {artist_name} in batches of {BATCH_SIZE}"
        )

        # Process files in batches (same logic as library organization)
        # Track errors - non-fatal errors (file not exist, already exists) don't fail job
        error_tracker = ErrorTracker()
        moved_source_paths = []  # Track source paths for empty directory cleanup
        total_batches = (len(files) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(files))
            batch = files[start_idx:end_idx]

            job_logger.log_batch_operation(
                "organize",
                count=len(batch),
                description=f"Batch {batch_num + 1}/{total_batches}"
            )

            for idx, file_data in enumerate(batch):
                global_idx = start_idx + idx

                try:
                    file_name = Path(file_data['file_path']).name
                    update_job_progress(
                        db, job,
                        current_action=f"Organizing {file_name}"
                    )

                    # Build track context
                    track_context = TrackContext(
                        artist_name=file_data['artist_name'] or 'Unknown Artist',
                        album_title=file_data['album_title'] or 'Unknown Album',
                        track_title=file_data['track_title'] or 'Unknown Track',
                        track_number=file_data['track_number'] or 1,
                        release_year=file_data['release_year'],
                        disc_number=file_data['disc_number'] or 1,
                        total_discs=file_data['total_discs'] or 1,
                        medium_format='CD',
                        album_type=file_data['album_type'] or 'Album',
                        file_extension=file_data['file_extension'] or 'flac',
                        is_compilation=file_data['is_compilation'] or False
                    )

                    # Organize file
                    file_id_uuid = UUID(str(file_data['file_id'])) if file_data.get('file_id') else None
                    result = file_organizer.organize_track_file(
                        file_path=file_data['file_path'],
                        track_context=track_context,
                        library_root=library_path,
                        file_id=file_id_uuid,
                        job_id=UUID(job_id)
                    )

                    if result.success:
                        # Update Track.file_path if file was moved/renamed
                        if result.destination_path and result.destination_path != file_data['file_path']:
                            try:
                                db.execute(
                                    text("UPDATE tracks SET file_path = :new_path WHERE file_path = :old_path"),
                                    {'new_path': result.destination_path, 'old_path': file_data['file_path']}
                                )
                                db.commit()
                            except Exception as track_err:
                                logger.warning(f"Could not update Track.file_path: {track_err}")
                                db.rollback()

                        from app.shared_services.atomic_file_ops import OperationType
                        if result.operation_type == OperationType.RENAME:
                            update_job_progress(db, job, files_renamed=1)
                            job_logger.log_file_operation(
                                operation="rename",
                                source_path=file_data['file_path'],
                                destination_path=result.destination_path,
                                success=True
                            )
                        elif result.operation_type == OperationType.MOVE:
                            moved_source_paths.append(file_data['file_path'])
                            update_job_progress(db, job, files_moved=1)
                            job_logger.log_file_operation(
                                operation="move",
                                source_path=file_data['file_path'],
                                destination_path=result.destination_path,
                                success=True
                            )
                    else:
                        # Categorize error as fatal or non-fatal
                        is_fatal = error_tracker.add_error(file_data['file_path'], result.error_message)
                        update_job_progress(db, job, files_failed=1)
                        job_logger.log_file_operation(
                            operation="organize",
                            source_path=file_data['file_path'],
                            success=False,
                            error=result.error_message
                        )
                        if not is_fatal:
                            job_logger.log_info(
                                f"Non-fatal error (skipping): {file_data['file_path']}: {result.error_message}"
                            )

                    # Update progress
                    progress = ((global_idx + 1) / len(files)) * 100
                    update_job_progress(db, job, progress_percent=progress, files_processed=global_idx + 1)

                except Exception as e:
                    # Categorize exception errors too
                    is_fatal = error_tracker.add_error(file_data['file_path'], str(e))
                    logger.error(f"Error organizing file {file_data['file_path']}: {e}")
                    update_job_progress(db, job, files_failed=1)
                    job_logger.log_file_operation(
                        operation="organize",
                        source_path=file_data['file_path'],
                        success=False,
                        error=str(e)
                    )
                    if not is_fatal:
                        job_logger.log_info(
                            f"Non-fatal error (skipping): {file_data['file_path']}: {e}"
                        )

            # Log batch completion
            job_logger.log_info(f"Completed batch {batch_num + 1}/{total_batches}")

        job_logger.log_phase_complete("File Organization", count=len(files))

        # Clean up empty directories left behind by moved files
        if moved_source_paths and not options.get('dry_run', False):
            job_logger.log_phase_start("Directory Cleanup", f"Checking {len(moved_source_paths)} source paths for empty directories")
            update_job_progress(db, job, current_action="Cleaning up empty directories...")
            dirs_removed = cleanup_empty_directories(moved_source_paths, library_path, job_logger)
            job_logger.log_phase_complete("Directory Cleanup", count=dirs_removed)

        # Generate error report if any errors occurred
        if error_tracker.get_total_errors() > 0:
            error_tracker.generate_report(job_logger)

        # Complete job
        job_logger.log_job_complete({
            'files_total': job.files_total,
            'files_processed': job.files_processed,
            'files_renamed': job.files_renamed,
            'files_moved': job.files_moved,
            'files_failed': job.files_failed,
            'fatal_errors': error_tracker.get_fatal_error_count(),
            'non_fatal_errors': error_tracker.get_total_errors() - error_tracker.get_fatal_error_count()
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Organization complete for {artist_name}"
        db.commit()

        logger.info(f"Completed artist organization job {job_id}")

    except Exception as e:
        logger.error(f"Error in artist organization job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)  # 1 hour limit
def organize_album_files_task(self, job_id: str, album_id: str, options: dict):
    """
    Organize all files for a specific album

    Args:
        job_id: FileOrganizationJob ID
        album_id: Album UUID
        options: Organization options dict
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting album organization job {job_id} for album {album_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Get album info
        album_query = text("""
            SELECT a.title, a.musicbrainz_id, ar.name as artist_name, ar.id as artist_id
            FROM albums a
            JOIN artists ar ON a.artist_id = ar.id
            WHERE a.id = :album_id
        """)
        result = db.execute(album_query, {'album_id': album_id})
        album = result.first()

        if not album:
            job_logger.log_job_error(f"Album {album_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Album {album_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        album_title = album[0]
        album_mbid = album[1]
        artist_name = album[2]
        artist_id = album[3]

        job_logger.log_job_start("organize_album", f"{album_title} by {artist_name}")

        # Get library for this album (from first file)
        library_query = text("""
            SELECT DISTINCT lp.id, lp.path
            FROM library_paths lp
            JOIN library_files lf ON lf.library_path_id = lp.id
            WHERE lf.musicbrainz_releasegroupid = :album_mbid
            LIMIT 1
        """)
        result = db.execute(library_query, {'album_mbid': album_mbid})
        library_row = result.first()

        if not library_row:
            job.status = JobStatus.FAILED
            job.error_message = f"No library found for album {album_id}"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        library_path = library_row[1]

        # Get files to organize for this album
        job_logger.log_phase_start("File Discovery", f"Scanning files for album: {album_title}")

        files = get_library_files_for_organization(
            db=db,
            album_mbid=album_mbid,
            only_with_mbid=options.get('only_with_mbid', True),
            only_unorganized=options.get('only_unorganized', True)
        )

        job.files_total = len(files)
        db.commit()

        logger.info(f"Found {len(files)} files to organize for album {album_title}")
        job_logger.log_phase_complete("File Discovery", count=len(files))

        if len(files) == 0:
            job_logger.log_info("No files found to organize")
            job_logger.log_job_complete({
                'files_total': 0,
                'files_processed': 0,
                'files_renamed': 0,
                'files_moved': 0,
                'files_failed': 0
            })
            job.status = JobStatus.COMPLETED
            job.progress_percent = 100.0
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Initialize file organizer with dry_run mode
        file_organizer = get_file_organizer(db, dry_run=options.get('dry_run', False))

        # Start organization phase
        job_logger.log_phase_start(
            "File Organization",
            f"Organizing {len(files)} files for {album_title} in batches of {BATCH_SIZE}"
        )

        # Process files in batches
        # Track errors - non-fatal errors (file not exist, already exists) don't fail job
        error_tracker = ErrorTracker()
        moved_source_paths = []  # Track source paths for empty directory cleanup
        total_batches = (len(files) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, len(files))
            batch = files[start_idx:end_idx]

            job_logger.log_batch_operation(
                "organize",
                count=len(batch),
                description=f"Batch {batch_num + 1}/{total_batches}"
            )

            for idx, file_data in enumerate(batch):
                global_idx = start_idx + idx

                try:
                    file_name = Path(file_data['file_path']).name
                    update_job_progress(
                        db, job,
                        current_action=f"Organizing {file_name}"
                    )

                    # Build track context
                    track_context = TrackContext(
                        artist_name=file_data['artist_name'] or artist_name,
                        album_title=file_data['album_title'] or album_title,
                        track_title=file_data['track_title'] or 'Unknown Track',
                        track_number=file_data['track_number'] or 1,
                        release_year=file_data['release_year'],
                        disc_number=file_data['disc_number'] or 1,
                        total_discs=file_data['total_discs'] or 1,
                        medium_format='CD',
                        album_type=file_data['album_type'] or 'Album',
                        file_extension=file_data['file_extension'] or 'flac',
                        is_compilation=file_data['is_compilation'] or False
                    )

                    # Organize file
                    file_id_uuid = UUID(str(file_data['file_id'])) if file_data.get('file_id') else None
                    result = file_organizer.organize_track_file(
                        file_path=file_data['file_path'],
                        track_context=track_context,
                        library_root=library_path,
                        file_id=file_id_uuid,
                        job_id=UUID(job_id)
                    )

                    if result.success:
                        # Update Track.file_path if file was moved/renamed
                        if result.destination_path and result.destination_path != file_data['file_path']:
                            try:
                                db.execute(
                                    text("UPDATE tracks SET file_path = :new_path WHERE file_path = :old_path"),
                                    {'new_path': result.destination_path, 'old_path': file_data['file_path']}
                                )
                                db.commit()
                            except Exception as track_err:
                                logger.warning(f"Could not update Track.file_path: {track_err}")
                                db.rollback()

                        from app.shared_services.atomic_file_ops import OperationType
                        if result.operation_type == OperationType.RENAME:
                            update_job_progress(db, job, files_renamed=1)
                            job_logger.log_file_operation(
                                operation="rename",
                                source_path=file_data['file_path'],
                                destination_path=result.destination_path,
                                success=True
                            )
                        elif result.operation_type == OperationType.MOVE:
                            moved_source_paths.append(file_data['file_path'])
                            update_job_progress(db, job, files_moved=1)
                            job_logger.log_file_operation(
                                operation="move",
                                source_path=file_data['file_path'],
                                destination_path=result.destination_path,
                                success=True
                            )
                    else:
                        # Categorize error as fatal or non-fatal
                        is_fatal = error_tracker.add_error(file_data['file_path'], result.error_message)
                        update_job_progress(db, job, files_failed=1)
                        job_logger.log_file_operation(
                            operation="organize",
                            source_path=file_data['file_path'],
                            success=False,
                            error=result.error_message
                        )
                        if not is_fatal:
                            job_logger.log_info(
                                f"Non-fatal error (skipping): {file_data['file_path']}: {result.error_message}"
                            )

                    # Update progress
                    progress = ((global_idx + 1) / len(files)) * 100
                    update_job_progress(db, job, progress_percent=progress, files_processed=global_idx + 1)

                except Exception as e:
                    # Categorize exception errors too
                    is_fatal = error_tracker.add_error(file_data['file_path'], str(e))
                    logger.error(f"Error organizing file {file_data['file_path']}: {e}")
                    update_job_progress(db, job, files_failed=1)
                    job_logger.log_file_operation(
                        operation="organize",
                        source_path=file_data['file_path'],
                        success=False,
                        error=str(e)
                    )
                    if not is_fatal:
                        job_logger.log_info(
                            f"Non-fatal error (skipping): {file_data['file_path']}: {e}"
                        )

            # Log batch completion
            job_logger.log_info(f"Completed batch {batch_num + 1}/{total_batches}")

        job_logger.log_phase_complete("File Organization", count=len(files))

        # Clean up empty directories left behind by moved files
        if moved_source_paths and not options.get('dry_run', False):
            job_logger.log_phase_start("Directory Cleanup", f"Checking {len(moved_source_paths)} source paths for empty directories")
            update_job_progress(db, job, current_action="Cleaning up empty directories...")
            dirs_removed = cleanup_empty_directories(moved_source_paths, library_path, job_logger)
            job_logger.log_phase_complete("Directory Cleanup", count=dirs_removed)

        # Create .mbid.json file if requested
        if options.get('create_metadata_files', True) and not options.get('dry_run', False):
            try:
                job_logger.log_phase_start("Metadata File Creation", f"Creating .mbid.json for {album_title}")
                # Album metadata file creation would go here
                job_logger.log_phase_complete("Metadata File Creation", count=1)
            except Exception as e:
                job_logger.log_warning(f"Failed to create .mbid.json: {str(e)}")

        # Generate error report if any errors occurred
        if error_tracker.get_total_errors() > 0:
            error_tracker.generate_report(job_logger)

        # Complete job
        job_logger.log_job_complete({
            'files_total': job.files_total,
            'files_processed': job.files_processed,
            'files_renamed': job.files_renamed,
            'files_moved': job.files_moved,
            'files_failed': job.files_failed,
            'fatal_errors': error_tracker.get_fatal_error_count(),
            'non_fatal_errors': error_tracker.get_total_errors() - error_tracker.get_fatal_error_count()
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Organization complete for {album_title}"
        db.commit()

        logger.info(f"Completed album organization job {job_id}")

    except Exception as e:
        logger.error(f"Error in album organization job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        job.status = JobStatus.FAILED
        job.error_message = str(e)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()


def _extract_mbids_from_files(
    db,
    library_path_id: UUID,
    library_root: str,
    job_logger,
    job: FileOrganizationJob = None
) -> dict:
    """
    Extract MusicBrainz IDs from file metadata comments and update the database.

    Scans files that don't have MBIDs in the database, reads their metadata,
    extracts MBIDs from the comment field (MUSE Ponder format), and updates
    the library_files table.

    Args:
        db: Database session
        library_path_id: Library path UUID
        library_root: Root path of the library
        job_logger: JobLogger instance for logging
        job: FileOrganizationJob for progress updates (optional)

    Returns:
        dict with statistics: files_scanned, files_updated, files_failed, files_without_mbid_paths
    """
    from app.models.library import LibraryFile
    from app.services.metadata_extractor import MetadataExtractor
    from pathlib import Path
    import os

    stats = {
        'files_scanned': 0,
        'files_updated': 0,
        'files_failed': 0,
        'artists_found': set(),
        'files_without_mbid_paths': []
    }

    try:
        # Update heartbeat before starting large query (query can take time for large libraries)
        if job:
            update_job_progress(
                db, job,
                current_action=f"MBID Extraction: Querying files without MusicBrainz IDs..."
            )

        # Get all files without musicbrainz_artistid
        files_without_mbid = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id,
            LibraryFile.musicbrainz_artistid.is_(None)
        ).all()

        total_files = len(files_without_mbid)
        job_logger.log_info(f"Found {total_files} files without MusicBrainz artist IDs")

        # Update heartbeat after query completes (query can take time for large libraries)
        if job:
            update_job_progress(
                db, job,
                current_action=f"MBID Extraction: Starting scan of {total_files} files"
            )

        batch_size = BATCH_SIZE  # Use global batch size (100 minimum)
        last_heartbeat_time = datetime.now(timezone.utc)
        HEARTBEAT_INTERVAL = 30  # Update heartbeat at least every 30 seconds

        for i, library_file in enumerate(files_without_mbid):
            stats['files_scanned'] += 1

            try:
                file_path = library_file.file_path

                # Progress update every batch_size files (Phase 1 is 0-50% of total job progress)
                # Also update heartbeat every 30 seconds to prevent stall detection
                now = datetime.now(timezone.utc)
                time_since_heartbeat = (now - last_heartbeat_time).total_seconds()

                if job and ((i + 1) % batch_size == 0 or time_since_heartbeat >= HEARTBEAT_INTERVAL):
                    progress = (i + 1) / total_files * 50  # First phase is 50% of total
                    update_job_progress(
                        db, job,
                        progress_percent=progress,
                        current_action=f"MBID Extraction: {i + 1}/{total_files} files processed"
                    )
                    last_heartbeat_time = now

                # Check if file exists
                if not os.path.exists(file_path):
                    logger.warning(f"File not found: {file_path}")
                    continue

                # Extract metadata from file
                metadata = MetadataExtractor.extract(file_path)

                if not metadata:
                    continue

                # Check if we found any MBIDs
                updated = False

                if metadata.get('musicbrainz_artistid') and not library_file.musicbrainz_artistid:
                    library_file.musicbrainz_artistid = metadata['musicbrainz_artistid']
                    stats['artists_found'].add(metadata['musicbrainz_artistid'])
                    updated = True

                if metadata.get('musicbrainz_albumid') and not library_file.musicbrainz_albumid:
                    library_file.musicbrainz_albumid = metadata['musicbrainz_albumid']
                    updated = True

                if metadata.get('musicbrainz_trackid') and not library_file.musicbrainz_trackid:
                    library_file.musicbrainz_trackid = metadata['musicbrainz_trackid']
                    updated = True

                if metadata.get('musicbrainz_releasegroupid') and not library_file.musicbrainz_releasegroupid:
                    library_file.musicbrainz_releasegroupid = metadata['musicbrainz_releasegroupid']
                    updated = True

                if updated:
                    stats['files_updated'] += 1

                # Commit in batches
                if (i + 1) % batch_size == 0:
                    db.commit()
                    job_logger.log_info(f"Processed {i + 1}/{total_files} files, updated {stats['files_updated']} with MBIDs")

            except Exception as e:
                stats['files_failed'] += 1
                logger.warning(f"Error extracting metadata from {library_file.file_path}: {e}")
                continue

        # Final commit
        db.commit()

        job_logger.log_info(f"Found {len(stats['artists_found'])} unique artists from extracted MBIDs")

        # Get files still without MBID after extraction
        files_still_without_mbid = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id,
            LibraryFile.musicbrainz_artistid.is_(None)
        ).all()

        stats['files_without_mbid_paths'] = [f.file_path for f in files_still_without_mbid]
        stats['files_without_mbid_count'] = len(files_still_without_mbid)
        job_logger.log_info(f"Files still without MBID after extraction: {stats['files_without_mbid_count']}")

    except Exception as e:
        logger.error(f"Error in MBID extraction: {e}")
        job_logger.log_error(f"MBID extraction error: {e}")

    return stats


@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def validate_library_structure_task(self, job_id: str, library_path_id: str):
    """
    Validate library structure and identify issues

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Library UUID
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting validation job {job_id} for library {library_path_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Get library path
        library_path = db.query(LibraryPath).filter(LibraryPath.id == UUID(library_path_id)).first()
        if not library_path:
            job_logger.log_job_error(f"Library path {library_path_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Library path {library_path_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Log job start
        job_logger.log_job_start("validate_structure", library_path.name)

        # Phase 1: Extract MBIDs from file metadata for files missing MBIDs in database
        job_logger.log_phase_start("MBID Extraction", f"Scanning files for MusicBrainz IDs in metadata")
        update_job_progress(db, job, current_action="Extracting MBIDs from file metadata", progress_percent=0.0)

        mbid_stats = _extract_mbids_from_files(
            db=db,
            library_path_id=UUID(library_path_id),
            library_root=library_path.path,
            job_logger=job_logger,
            job=job  # Pass job for progress updates
        )

        job_logger.log_info(f"MBID Extraction: Scanned {mbid_stats['files_scanned']} files, updated {mbid_stats['files_updated']} with MBIDs")
        job_logger.log_phase_complete("MBID Extraction", count=mbid_stats['files_updated'])

        # Update progress to 50% after Phase 1
        update_job_progress(db, job, progress_percent=50.0)

        # Initialize path validator
        path_validator = PathValidator(db=db)

        # Phase 2: Validate library structure
        job_logger.log_phase_start("Structure Validation", f"Validating library: {library_path.name}")
        update_job_progress(db, job, current_action="Validating library structure")

        validation_result = path_validator.validate_library_structure(
            library_path_id=UUID(library_path_id),
            library_root=library_path.path
        )

        # Log validation results
        logger.info(
            f"Validation complete: {validation_result.valid_files}/{validation_result.total_files} valid, "
            f"{len(validation_result.misnamed_files)} misnamed, "
            f"{len(validation_result.misplaced_files)} misplaced, "
            f"{len(validation_result.incorrect_directories)} incorrect directories"
        )

        job_logger.log_info(
            f"Found {validation_result.valid_files}/{validation_result.total_files} valid files"
        )

        # Log issues
        for file_info in validation_result.misnamed_files:
            job_logger.log_validation_issue(
                issue_type="misnamed_file",
                description=f"Expected: {file_info.expected_filename}",
                file_path=file_info.current_path
            )

        for file_info in validation_result.misplaced_files:
            job_logger.log_validation_issue(
                issue_type="misplaced_file",
                description=f"Should be in: {file_info.expected_directory}",
                file_path=file_info.current_path
            )

        for dir_info in validation_result.incorrect_directories:
            job_logger.log_validation_issue(
                issue_type="incorrect_directory",
                description=f"Expected: {dir_info.expected_name}",
                file_path=dir_info.current_path
            )

        job_logger.log_phase_complete("Structure Validation", count=validation_result.total_files)

        # Update progress to 90%
        update_job_progress(db, job, progress_percent=90.0)

        # Phase 3: Create follow-up FETCH_METADATA job if there are files without MBID
        files_without_mbid_count = mbid_stats.get('files_without_mbid_count', 0)
        files_without_mbid_paths = mbid_stats.get('files_without_mbid_paths', [])

        # Store files without MBID in current job
        job.files_without_mbid = files_without_mbid_count
        if files_without_mbid_paths:
            import json
            job.files_without_mbid_json = json.dumps(files_without_mbid_paths[:10000])  # Limit to 10K paths

        fetch_metadata_job_id = None
        if files_without_mbid_count > 0:
            job_logger.log_phase_start("Create Follow-up Job", f"Creating fetch metadata job for {files_without_mbid_count} files")

            # Create a FETCH_METADATA job in PAUSED state
            fetch_metadata_job = FileOrganizationJob(
                job_type=JobType.FETCH_METADATA,
                status=JobStatus.PAUSED,
                library_path_id=UUID(library_path_id),
                parent_job_id=UUID(job_id),
                files_total=files_without_mbid_count,
                files_without_mbid=files_without_mbid_count,
                files_without_mbid_json=job.files_without_mbid_json,
                current_action=f"Waiting to fetch metadata for {files_without_mbid_count} files"
            )
            db.add(fetch_metadata_job)
            db.commit()

            fetch_metadata_job_id = str(fetch_metadata_job.id)
            job_logger.log_info(f"Created FETCH_METADATA job {fetch_metadata_job_id} in PAUSED state")
            job_logger.log_phase_complete("Create Follow-up Job", count=1)

        # Generate summary report
        summary_report = _generate_summary_report(
            job=job,
            job_logger=job_logger,
            mbid_stats=mbid_stats,
            validation_result=validation_result,
            fetch_metadata_job_id=fetch_metadata_job_id
        )

        # Complete job
        job_logger.log_job_complete({
            'files_total': validation_result.total_files,
            'files_processed': validation_result.total_files,
            'files_renamed': 0,
            'files_moved': 0,
            'files_failed': len(validation_result.misnamed_files) + len(validation_result.misplaced_files),
            'files_without_mbid': files_without_mbid_count,
            'fetch_metadata_job_id': fetch_metadata_job_id
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.files_total = validation_result.total_files
        job.files_processed = validation_result.total_files
        job.files_failed = len(validation_result.misnamed_files) + len(validation_result.misplaced_files)
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = "Validation complete" + (f" - {files_without_mbid_count} files need metadata fetch" if files_without_mbid_count > 0 else "")
        db.commit()

        logger.info(f"Completed validation job {job_id}" + (f" - Created fetch metadata job {fetch_metadata_job_id}" if fetch_metadata_job_id else ""))

    except Exception as e:
        logger.error(f"Error in validation job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


def _generate_summary_report(
    job: FileOrganizationJob,
    job_logger: JobLogger,
    mbid_stats: dict,
    validation_result,
    fetch_metadata_job_id: str = None
) -> dict:
    """
    Generate a summary report for the validation job.

    Args:
        job: FileOrganizationJob being completed
        job_logger: JobLogger for logging
        mbid_stats: Statistics from MBID extraction phase
        validation_result: Results from structure validation
        fetch_metadata_job_id: ID of created fetch metadata job (if any)

    Returns:
        dict containing the summary report
    """
    import json
    import os

    report = {
        "job_id": str(job.id),
        "job_type": job.job_type.value if hasattr(job.job_type, 'value') else str(job.job_type),
        "status": "completed",
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "phases": {
            "mbid_extraction": {
                "files_scanned": mbid_stats.get('files_scanned', 0),
                "files_updated": mbid_stats.get('files_updated', 0),
                "files_failed": mbid_stats.get('files_failed', 0),
                "unique_artists_found": len(mbid_stats.get('artists_found', set()))
            },
            "structure_validation": {
                "total_files": validation_result.total_files,
                "valid_files": validation_result.valid_files,
                "misnamed_files": len(validation_result.misnamed_files),
                "misplaced_files": len(validation_result.misplaced_files),
                "incorrect_directories": len(validation_result.incorrect_directories)
            }
        },
        "files_without_mbid": {
            "count": mbid_stats.get('files_without_mbid_count', 0),
            "sample_paths": mbid_stats.get('files_without_mbid_paths', [])[:100]  # First 100 paths
        },
        "issues": [],
        "follow_up_job": {
            "created": fetch_metadata_job_id is not None,
            "job_id": fetch_metadata_job_id,
            "status": "paused" if fetch_metadata_job_id else None
        }
    }

    # Add issues to report
    for file_info in validation_result.misnamed_files[:50]:  # Limit to 50
        report["issues"].append({
            "type": "misnamed_file",
            "path": file_info.current_path,
            "expected": file_info.expected_filename
        })

    for file_info in validation_result.misplaced_files[:50]:
        report["issues"].append({
            "type": "misplaced_file",
            "path": file_info.current_path,
            "expected_directory": file_info.expected_directory
        })

    for dir_info in validation_result.incorrect_directories[:50]:
        report["issues"].append({
            "type": "incorrect_directory",
            "path": dir_info.current_path,
            "expected_name": dir_info.expected_name
        })

    # Write report to file
    try:
        report_dir = "/app/logs"
        os.makedirs(report_dir, exist_ok=True)
        report_path = f"{report_dir}/summary_report_{job.id}.json"

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        job.summary_report_path = report_path
        job_logger.log_info(f"Summary report saved to: {report_path}")
    except Exception as e:
        logger.error(f"Error saving summary report: {e}")
        job_logger.log_error(f"Failed to save summary report: {e}")

    # Log summary to job log
    job_logger.log_info("=" * 50)
    job_logger.log_info("SUMMARY REPORT")
    job_logger.log_info("=" * 50)
    job_logger.log_info(f"MBID Extraction:")
    job_logger.log_info(f"  - Files scanned: {mbid_stats.get('files_scanned', 0)}")
    job_logger.log_info(f"  - Files with MBID found: {mbid_stats.get('files_updated', 0)}")
    job_logger.log_info(f"  - Files still without MBID: {mbid_stats.get('files_without_mbid_count', 0)}")
    job_logger.log_info(f"Structure Validation:")
    job_logger.log_info(f"  - Total files: {validation_result.total_files}")
    job_logger.log_info(f"  - Valid files: {validation_result.valid_files}")
    job_logger.log_info(f"  - Misnamed files: {len(validation_result.misnamed_files)}")
    job_logger.log_info(f"  - Misplaced files: {len(validation_result.misplaced_files)}")
    job_logger.log_info(f"  - Incorrect directories: {len(validation_result.incorrect_directories)}")
    if fetch_metadata_job_id:
        job_logger.log_info(f"Follow-up Job:")
        job_logger.log_info(f"  - Fetch Metadata Job ID: {fetch_metadata_job_id}")
        job_logger.log_info(f"  - Status: PAUSED (waiting for user action)")
    job_logger.log_info("=" * 50)

    return report


@shared_task(bind=True, soft_time_limit=43200, time_limit=43500)  # 12 hour limit for large libraries
def fetch_metadata_task(self, job_id: str):
    """
    Fetch MBIDs from MusicBrainz for files without metadata.

    Uses search_recording() to find matches based on existing file tags
    (artist, title, album).

    Args:
        job_id: FileOrganizationJob ID
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting fetch metadata job {job_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_job_start("fetch_metadata", f"Fetching MusicBrainz metadata for {job.files_total} files")

        # Import services
        import json
        import time
        from app.services.metadata_extractor import MetadataExtractor
        from app.services.musicbrainz_client import MusicBrainzClient
        from app.models.library import LibraryFile, LibraryPath

        # Load files without MBID - prefer JSON if available, otherwise query database
        files_to_process = []
        if job.files_without_mbid_json:
            files_to_process = json.loads(job.files_without_mbid_json)
            job_logger.log_info(f"Loaded {len(files_to_process)} files from job JSON data")

        if not files_to_process:
            # Query database for files without MBID in comments
            job_logger.log_info("No files in JSON, querying database for files without MBID in comments...")

            # Get library_path_id from job
            library_path_id = job.library_path_id
            if not library_path_id:
                job_logger.log_error("No library_path_id on job, cannot query files")
                job.status = JobStatus.FAILED
                job.error_message = "No library_path_id on job"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                return {'error': 'No library_path_id on job'}

            # Query files where mbid_in_file is False or NULL
            files_without_mbid = db.query(LibraryFile.file_path).filter(
                LibraryFile.library_path_id == library_path_id,
                (LibraryFile.mbid_in_file == False) | (LibraryFile.mbid_in_file.is_(None))
            ).all()

            files_to_process = [f[0] for f in files_without_mbid]
            job_logger.log_info(f"Found {len(files_to_process)} files without MBID in comments from database")

            # Update job with file count
            job.files_total = len(files_to_process)
            job.files_without_mbid = len(files_to_process)
            db.commit()

        if not files_to_process:
            job_logger.log_warning("No files to process - all files have MBID in comments")
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.current_action = "No files to process - all files have MBID"
            db.commit()
            return {'status': 'completed', 'message': 'All files already have MBID in comments'}

        mb_client = MusicBrainzClient()

        total_files = len(files_to_process)
        files_updated = 0
        files_failed = 0
        files_still_without_mbid = []  # List of dicts: {'file_path': ..., 'reason': ...}

        job_logger.log_phase_start("MusicBrainz Search", f"Searching MusicBrainz for {total_files} files")

        # Background heartbeat thread prevents stall detection during
        # long-running MusicBrainz API calls (can block 375s with retries)
        heartbeat_keeper = BackgroundHeartbeat(job_id, FileOrganizationJob, interval=60)
        heartbeat_keeper.__enter__()

        for i, file_path in enumerate(files_to_process):
            try:
                # Progress update with heartbeat (every file - MusicBrainz lookups can block 125s+)
                progress = (i + 1) / total_files * 100
                job.progress_percent = progress
                job.current_action = f"Fetching metadata: {i + 1}/{total_files}"
                job.files_processed = i + 1
                job.current_file_path = file_path
                job.last_heartbeat_at = datetime.now(timezone.utc)
                db.commit()

                # PRE-CHECK: Verify if MBID already exists in file before API call
                from app.services.metadata_writer import MetadataWriter
                existing_mbid = MetadataWriter.verify_mbid_in_file(file_path)

                if existing_mbid.get('has_mbid') and existing_mbid.get('recording_mbid'):
                    # File already has MBID - update database without API call
                    library_file = db.query(LibraryFile).filter(
                        LibraryFile.file_path == file_path
                    ).first()

                    if library_file:
                        # Update database with existing MBIDs from file
                        if existing_mbid.get('artist_mbid'):
                            library_file.musicbrainz_artistid = existing_mbid.get('artist_mbid')
                        if existing_mbid.get('recording_mbid'):
                            library_file.musicbrainz_trackid = existing_mbid.get('recording_mbid')
                        if existing_mbid.get('release_mbid'):
                            library_file.musicbrainz_albumid = existing_mbid.get('release_mbid')
                        if existing_mbid.get('release_group_mbid'):
                            library_file.musicbrainz_releasegroupid = existing_mbid.get('release_group_mbid')
                        library_file.mbid_in_file = True
                        library_file.mbid_verified_at = datetime.now(timezone.utc)
                        files_updated += 1
                        job_logger.log_info(f"Skipped API call - MBID already in file: {file_path} (Recording: {existing_mbid.get('recording_mbid')})")
                    else:
                        files_failed += 1
                        files_still_without_mbid.append({'file_path': file_path, 'reason': 'Library file not found in DB'})
                        job_logger.log_warning(f"Library file not found in DB (but has MBID): {file_path}")
                    continue

                # Extract existing metadata from file
                metadata = MetadataExtractor.extract(file_path)
                if not metadata:
                    files_failed += 1
                    files_still_without_mbid.append({'file_path': file_path, 'reason': 'Metadata extraction failed'})
                    job_logger.log_warning(f"Could not extract metadata from: {file_path}")
                    continue

                artist = metadata.get('artist')
                title = metadata.get('title')
                album = metadata.get('album')

                if not artist or not title:
                    files_failed += 1
                    files_still_without_mbid.append({'file_path': file_path, 'reason': 'Missing artist/title'})
                    job_logger.log_warning(f"Missing artist/title for: {file_path}")
                    continue

                # Search MusicBrainz (with rate limiting - 1 req/sec)
                job_logger.log_info(f"Searching MusicBrainz: {artist} - {title}" + (f" ({album})" if album else ""))
                recordings = mb_client.search_recording(
                    artist=artist,
                    title=title,
                    release=album,
                    limit=3
                )

                # Rate limit: MusicBrainz allows 1 request per second
                time.sleep(1.0)

                if recordings and len(recordings) > 0:
                    # Use confidence scorer to evaluate matches
                    from app.services.mbid_confidence_scorer import MBIDConfidenceScorer

                    file_meta = {
                        'title': title,
                        'artist': artist,
                        'album': album,
                        'duration': metadata.get('duration') or metadata.get('length')
                    }

                    # Score all matches and get best one above minimum threshold
                    scored_match = MBIDConfidenceScorer.get_best_match(
                        file_meta,
                        recordings,
                        min_score=50  # Minimum acceptable score
                    )

                    if not scored_match:
                        # No match above confidence threshold
                        files_failed += 1
                        files_still_without_mbid.append({'file_path': file_path, 'reason': 'Below confidence threshold'})
                        job_logger.log_warning(f"No confident match for: {artist} - {title} (best score below 50)")
                        continue

                    confidence_score = scored_match['total_score']
                    confidence_level = scored_match['confidence_level']
                    best_match = recordings[0]  # Get original recording for MBIDs

                    # Find the matching recording by MBID
                    for rec in recordings:
                        if rec.get('id') == scored_match['recording_mbid']:
                            best_match = rec
                            break

                    # Extract MBIDs from best match
                    recording_mbid = scored_match.get('recording_mbid') or best_match.get('id')
                    artist_mbid = scored_match.get('artist_mbid')
                    if not artist_mbid:
                        artist_credit = best_match.get('artist-credit', [{}])[0]
                        artist_mbid = artist_credit.get('artist', {}).get('id') if isinstance(artist_credit, dict) else None
                    releases = best_match.get('releases', [{}])
                    release_mbid = scored_match.get('release_mbid') or (releases[0].get('id') if releases else None)
                    release_group_mbid = releases[0].get('release-group', {}).get('id') if releases else None

                    # Log confidence details
                    job_logger.log_info(f"Match confidence: {confidence_score}/100 ({confidence_level}) for {artist} - {title}")

                    # CRITICAL: Write MBIDs to the audio file itself
                    write_result = MetadataWriter.write_mbids(
                        file_path=file_path,
                        recording_mbid=recording_mbid,
                        artist_mbid=artist_mbid,
                        release_mbid=release_mbid,
                        release_group_mbid=release_group_mbid,
                        overwrite=False  # Don't overwrite existing MBIDs
                    )

                    if write_result.success:
                        job_logger.log_info(f"Wrote MBIDs to file: {file_path}")
                    else:
                        job_logger.log_warning(f"Failed to write MBIDs to file {file_path}: {write_result.error}")

                    # Update library_file in database
                    library_file = db.query(LibraryFile).filter(
                        LibraryFile.file_path == file_path
                    ).first()

                    if library_file:
                        if artist_mbid:
                            library_file.musicbrainz_artistid = artist_mbid
                        if recording_mbid:
                            library_file.musicbrainz_trackid = recording_mbid
                        if release_mbid:
                            library_file.musicbrainz_albumid = release_mbid
                        if release_group_mbid:
                            library_file.musicbrainz_releasegroupid = release_group_mbid

                        # Update mbid_in_file flag based on write result
                        if write_result.success and write_result.mbids_written:
                            library_file.mbid_in_file = True
                            library_file.mbid_verified_at = datetime.now(timezone.utc)

                        files_updated += 1
                        job_logger.log_info(f"Found MBID for: {artist} - {title} (Confidence: {confidence_score}/100, Level: {confidence_level}, Written: {write_result.success})")
                    else:
                        files_failed += 1
                        files_still_without_mbid.append({'file_path': file_path, 'reason': 'Library file not found in DB'})
                        job_logger.log_warning(f"Library file not found in DB: {file_path}")
                else:
                    files_failed += 1
                    files_still_without_mbid.append({'file_path': file_path, 'reason': 'No MusicBrainz match'})
                    job_logger.log_warning(f"No MusicBrainz match for: {artist} - {title}")

            except Exception as e:
                files_failed += 1
                files_still_without_mbid.append({'file_path': file_path, 'reason': f'Error: {str(e)[:200]}'})
                logger.warning(f"Error processing file {file_path}: {e}")
                job_logger.log_error(f"Error processing {file_path}: {e}")
                # Keep heartbeat alive even on errors
                try:
                    job.last_heartbeat_at = datetime.now(timezone.utc)
                    db.commit()
                except Exception:
                    db.rollback()
                continue

        # Stop background heartbeat thread
        heartbeat_keeper.__exit__(None, None, None)

        # Final commit
        db.commit()

        job_logger.log_phase_complete("MusicBrainz Search", count=files_updated)

        # Update job with final statistics
        job.files_renamed = files_updated  # Using renamed as "updated" count
        job.files_failed = files_failed

        # Store remaining files without MBID
        if files_still_without_mbid:
            job.files_without_mbid = len(files_still_without_mbid)
            # Store file paths only in JSON for backward compatibility
            paths_only = [entry['file_path'] for entry in files_still_without_mbid]
            job.files_without_mbid_json = json.dumps(paths_only[:10000])

        # Generate summary report
        job_logger.log_info("=" * 50)
        job_logger.log_info("FETCH METADATA SUMMARY")
        job_logger.log_info("=" * 50)
        job_logger.log_info(f"Total files processed: {total_files}")
        job_logger.log_info(f"Files with MBID found: {files_updated}")
        job_logger.log_info(f"Files still without MBID: {files_failed}")
        job_logger.log_info("=" * 50)

        # List files still without MBID
        if files_still_without_mbid:
            job_logger.log_info("FILES STILL WITHOUT MBID:")
            for entry in files_still_without_mbid[:100]:
                job_logger.log_info(f"  - {entry['file_path']} ({entry['reason']})")
            if len(files_still_without_mbid) > 100:
                job_logger.log_info(f"  ... and {len(files_still_without_mbid) - 100} more")

        # Generate CSV report of unmatched files
        if files_still_without_mbid:
            try:
                import csv
                import os
                os.makedirs("/app/logs/jobs", exist_ok=True)
                csv_path = f"/app/logs/jobs/{job_id}_unmatched.csv"

                with open(csv_path, 'w', newline='') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(['file_path', 'file_name', 'artist', 'title', 'album', 'reason'])

                    for entry in files_still_without_mbid:
                        fp = entry['file_path']
                        reason = entry['reason']
                        file_name = os.path.basename(fp)

                        # Look up metadata from DB
                        lib_file = db.query(LibraryFile).filter(
                            LibraryFile.file_path == fp
                        ).first()

                        artist_name = lib_file.artist if lib_file else ''
                        title_name = lib_file.title if lib_file else ''
                        album_name = lib_file.album if lib_file else ''

                        writer.writerow([fp, file_name, artist_name, title_name, album_name, reason])

                job.summary_report_path = csv_path
                job_logger.log_info(f"CSV report generated: {csv_path}")
                logger.info(f"Unmatched files CSV report: {csv_path}")
            except Exception as csv_err:
                logger.error(f"Failed to generate CSV report: {csv_err}")
                job_logger.log_warning(f"Failed to generate CSV report: {csv_err}")

        # Complete job
        job_logger.log_job_complete({
            'files_total': total_files,
            'files_processed': total_files,
            'files_renamed': files_updated,
            'files_moved': 0,
            'files_failed': files_failed
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Complete: {files_updated} MBIDs found, {files_failed} still missing"
        job.last_heartbeat_at = datetime.now(timezone.utc)
        job.current_file_path = None
        db.commit()

        logger.info(f"Completed fetch metadata job {job_id}: {files_updated} updated, {files_failed} failed")

    except Exception as e:
        logger.error(f"Error in fetch metadata job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            job.last_heartbeat_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        # Ensure background heartbeat is stopped
        if 'heartbeat_keeper' in locals():
            heartbeat_keeper.__exit__(None, None, None)
        db.close()


@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def rollback_organization_job_task(self, job_id: str):
    """
    Rollback a completed organization job

    Args:
        job_id: FileOrganizationJob ID to rollback
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting rollback for job {job_id}")

        # Get original job
        original_job = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.id == UUID(job_id)
        ).first()

        if not original_job:
            logger.error(f"Job {job_id} not found")
            return

        if original_job.status != JobStatus.COMPLETED:
            logger.error(f"Can only rollback completed jobs. Job status: {original_job.status}")
            return

        # Get all operations for this job from audit log
        from sqlalchemy import text

        operations_query = text("""
            SELECT id, operation_type, source_path, destination_path, rollback_possible
            FROM file_operation_audit
            WHERE job_id = :job_id
            AND success = true
            AND rollback_possible = true
            AND rolled_back = false
            ORDER BY performed_at DESC
        """)

        operations = db.execute(operations_query, {'job_id': job_id}).fetchall()

        logger.info(f"Found {len(operations)} operations to rollback")

        # Initialize atomic operations
        atomic_ops = AtomicFileOps()

        rollback_count = 0
        failed_count = 0

        for op in operations:
            op_id, op_type, source_path, dest_path, rollback_possible = op

            try:
                if op_type == 'move' and dest_path:
                    # Reverse the move
                    result = atomic_ops.move_file(dest_path, source_path, backup=False)

                    if result.success:
                        # Mark as rolled back in audit log
                        update_query = text("""
                            UPDATE file_operation_audit
                            SET rolled_back = true
                            WHERE id = :op_id
                        """)
                        db.execute(update_query, {'op_id': str(op_id)})
                        rollback_count += 1
                    else:
                        logger.error(f"Failed to rollback operation {op_id}: {result.error_message}")
                        failed_count += 1

            except Exception as e:
                logger.error(f"Error rolling back operation {op_id}: {e}")
                failed_count += 1

        # Update original job status
        original_job.status = JobStatus.ROLLED_BACK
        db.commit()

        logger.info(f"Rollback complete: {rollback_count} operations reversed, {failed_count} failed")

    except Exception as e:
        logger.error(f"Error in rollback job: {e}\n{traceback.format_exc()}")

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=43200, time_limit=43500)  # 12 hour limit for large libraries
def validate_mbid_task(self, job_id: str, library_path_id: str, resume: bool = False):
    """
    Validate MBID Presence in Files

    Scans all files in a library and verifies whether MBIDs are written
    to the file comment tags. Updates the mbid_in_file column in the database.

    Features:
    - Heartbeat tracking for stall detection (every 30 seconds)
    - Current file tracking for debugging
    - Resumable - skips files already verified in this session
    - Detailed error logging with file paths and tracebacks

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Library UUID
        resume: If True, skip files already processed (based on files_processed count)
    """
    db = SessionLocal()
    job = None
    job_logger = None
    last_heartbeat_time = datetime.now(timezone.utc)
    HEARTBEAT_INTERVAL = 30  # seconds

    def update_heartbeat():
        """Update heartbeat and current file in database"""
        nonlocal last_heartbeat_time
        now = datetime.now(timezone.utc)
        if (now - last_heartbeat_time).total_seconds() >= HEARTBEAT_INTERVAL:
            job.last_heartbeat_at = now
            db.commit()
            last_heartbeat_time = now

    try:
        logger.info(f"Starting MBID validation job {job_id} for library {library_path_id} (resume={resume})")

        # Acquire job with row-level locking to prevent race conditions
        # Allow resume from FAILED status if resume=True
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id, allow_resume=resume)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return {"error": "Could not acquire job"}

        # Check if resuming a previously failed job
        start_index = 0
        if resume and job.files_processed > 0:
            start_index = job.files_processed
            logger.info(f"Resuming from file index {start_index}")

        job.current_action = "Initializing..."
        db.commit()

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Get library path
        library_path = db.query(LibraryPath).filter(LibraryPath.id == UUID(library_path_id)).first()
        if not library_path:
            job_logger.log_job_error(f"Library path {library_path_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Library path {library_path_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return {"error": "Library path not found"}

        if resume:
            job_logger.log_info(f"RESUMING job from file index {start_index}")
        else:
            job_logger.log_job_start("validate_mbid", library_path.name)

        # First, get the count (fast query) and update progress
        job.current_action = "Counting files in library..."
        db.commit()

        files_count = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == UUID(library_path_id)
        ).count()

        job.files_total = files_count
        job.current_action = f"Found {files_count} files, starting validation..."
        job.last_heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        job_logger.log_phase_start("MBID Validation", f"Checking {files_count} files for MBID in comments (starting at {start_index})")

        files_with_mbid = 0
        files_without_mbid = 0
        files_updated = 0
        files_failed = 0
        files_skipped = start_index
        files_without_mbid_paths = []

        # Use pagination to avoid loading all files at once and to allow commits between batches
        PAGE_SIZE = 500
        current_offset = start_index
        global_index = start_index

        while current_offset < files_count:
            # Fetch next batch
            batch = db.query(LibraryFile).filter(
                LibraryFile.library_path_id == UUID(library_path_id)
            ).order_by(LibraryFile.id).offset(current_offset).limit(PAGE_SIZE).all()

            if not batch:
                break

            for library_file in batch:
                try:
                    # Update current file being processed (for debugging stalls)
                    job.current_file_path = library_file.file_path
                    job.current_file_index = global_index

                    # Update heartbeat periodically
                    update_heartbeat()

                    # Progress update every BATCH_SIZE files
                    if (global_index + 1) % BATCH_SIZE == 0:
                        progress = (global_index + 1) / files_count * 100
                        job.progress_percent = progress
                        job.current_action = f"Validating MBID: {global_index + 1}/{files_count}"
                        job.files_processed = global_index + 1
                        job.last_heartbeat_at = datetime.now(timezone.utc)
                        db.commit()
                        job_logger.log_info(f"Processed {global_index + 1}/{files_count} files")

                    # Verify MBID in file
                    verification = MetadataWriter.verify_mbid_in_file(library_file.file_path)

                    # Update database
                    if verification['has_mbid']:
                        files_with_mbid += 1
                        if not library_file.mbid_in_file:
                            library_file.mbid_in_file = True
                            library_file.mbid_verified_at = datetime.now(timezone.utc)
                            files_updated += 1
                            job_logger.log_info(f"MBID found in file: {library_file.file_path}")
                    else:
                        files_without_mbid += 1
                        if library_file.mbid_in_file:
                            library_file.mbid_in_file = False
                            files_updated += 1
                        files_without_mbid_paths.append(library_file.file_path)

                    # Always update verification timestamp
                    library_file.mbid_verified_at = datetime.now(timezone.utc)

                    # Track last successfully processed file for resumability
                    job.last_processed_file_id = library_file.id
                    job.files_processed = global_index + 1

                except Exception as e:
                    files_failed += 1
                    error_details = traceback.format_exc()
                    logger.warning(f"Error verifying MBID in {library_file.file_path}: {e}")
                    job_logger.log_error(f"Error verifying {library_file.file_path}: {e}\n{error_details}")

                    # Track the error for debugging
                    job.last_error_file = library_file.file_path
                    job.last_error_details = f"{e}\n{error_details}"

                global_index += 1

            # Commit after each batch and move to next page
            db.commit()
            current_offset += PAGE_SIZE

        # Final commit
        job.current_file_path = None  # Clear current file
        db.commit()

        job_logger.log_phase_complete("MBID Validation", count=files_count)

        # Store files without MBID
        job.files_without_mbid = files_without_mbid
        if files_without_mbid_paths:
            import json
            job.files_without_mbid_json = json.dumps(files_without_mbid_paths[:10000])

        # Create follow-up FETCH_METADATA job if there are files without MBID
        fetch_metadata_job_id = None
        if files_without_mbid > 0:
            job_logger.log_info(f"Creating follow-up FETCH_METADATA job for {files_without_mbid} files")

            fetch_metadata_job = FileOrganizationJob(
                job_type=JobType.FETCH_METADATA,
                status=JobStatus.PAUSED,
                library_path_id=UUID(library_path_id),
                parent_job_id=UUID(job_id),
                files_total=files_without_mbid,
                files_without_mbid=files_without_mbid,
                files_without_mbid_json=job.files_without_mbid_json,
                current_action=f"Waiting to fetch metadata for {files_without_mbid} files"
            )
            db.add(fetch_metadata_job)
            db.commit()
            fetch_metadata_job_id = str(fetch_metadata_job.id)
            job_logger.log_info(f"Created FETCH_METADATA job {fetch_metadata_job_id} in PAUSED state")

        # Log summary
        job_logger.log_info("=" * 60)
        job_logger.log_info("MBID VALIDATION SUMMARY")
        job_logger.log_info("=" * 60)
        job_logger.log_info(f"Total files in library: {files_count}")
        job_logger.log_info(f"Files skipped (resumed): {files_skipped}")
        job_logger.log_info(f"Files processed this run: {files_count - files_skipped}")
        job_logger.log_info(f"Files with MBID in comments: {files_with_mbid}")
        job_logger.log_info(f"Files without MBID: {files_without_mbid}")
        job_logger.log_info(f"Database records updated: {files_updated}")
        job_logger.log_info(f"Files failed: {files_failed}")
        if fetch_metadata_job_id:
            job_logger.log_info(f"Follow-up job created: {fetch_metadata_job_id} (PAUSED)")
        job_logger.log_info("=" * 60)

        # Complete job
        job_logger.log_job_complete({
            'files_total': files_count,
            'files_processed': files_count,
            'files_skipped': files_skipped,
            'files_with_mbid': files_with_mbid,
            'files_without_mbid': files_without_mbid,
            'files_updated': files_updated,
            'files_failed': files_failed
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.files_processed = files_count
        job.files_renamed = files_with_mbid  # Using renamed to track files with MBID
        job.files_failed = files_failed
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Complete: {files_with_mbid} files have MBID, {files_without_mbid} missing"
        job.last_heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"Completed MBID validation job {job_id}: {files_with_mbid} with MBID, {files_without_mbid} without")

        return {
            'status': 'completed',
            'files_total': files_count,
            'files_with_mbid': files_with_mbid,
            'files_without_mbid': files_without_mbid,
            'fetch_metadata_job_id': fetch_metadata_job_id
        }

    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error in MBID validation job {job_id}: {e}\n{error_details}")
        if job_logger:
            job_logger.log_job_error(f"{e}\n{error_details}")
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.last_error_details = error_details
            job.completed_at = datetime.now(timezone.utc)
            job.last_heartbeat_at = datetime.now(timezone.utc)
            db.commit()
        return {'error': str(e)}

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=43200, time_limit=43260)
def link_files_task(self, job_id: str, library_path_id: str = None, artist_id: str = None, album_id: str = None, auto_import_artists: bool = False):
    """
    Link Files to Album Tracks

    Links library files that have MBIDs to their corresponding album track records.
    Uses Recording MBID for accurate track matching.

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Library UUID (optional)
        artist_id: Artist UUID (optional)
        album_id: Album UUID (optional)
        auto_import_artists: If True, import unlinked artists after linking
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting file linking job {job_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_job_start("link_files", f"Linking files to album tracks")

        # Use BackgroundHeartbeat to prevent false stall detection
        with BackgroundHeartbeat(job_id, FileOrganizationJob, interval=60):
            # Build library path filter for all bulk queries
            path_filter = ""
            bulk_params = {}
            if library_path_id:
                path_filter = "AND lf.library_path_id = :library_path_id"
                bulk_params['library_path_id'] = library_path_id
            if artist_id:
                artist_mbid_val = db.execute(
                    text("SELECT musicbrainz_id FROM artists WHERE id = :artist_id"),
                    {'artist_id': artist_id}
                ).scalar()
                if artist_mbid_val:
                    path_filter += " AND lf.musicbrainz_artistid = :artist_mbid_filter"
                    bulk_params['artist_mbid_filter'] = artist_mbid_val

            # Count total files with MBIDs
            total_count_sql = text(f"""
                SELECT COUNT(*) FROM library_files lf
                WHERE lf.musicbrainz_trackid IS NOT NULL
                {path_filter}
            """)
            total_files = db.execute(total_count_sql, bulk_params).scalar() or 0
            job.files_total = total_files
            db.commit()

            job_logger.log_phase_start("File Linking", f"Processing {total_files} files with MBID (bulk)")

            # Step 1: Fast path - Bulk UPDATE for unambiguous MBIDs
            # (Recording MBID matches exactly one track in DB)
            job.current_action = f"Bulk linking {total_files} files to tracks (unambiguous fast path)..."
            db.commit()

            bulk_update_sql = text(f"""
                UPDATE tracks
                SET file_path = lf.file_path, has_file = true
                FROM library_files lf
                WHERE tracks.musicbrainz_id = lf.musicbrainz_trackid
                  AND lf.musicbrainz_trackid IS NOT NULL
                  AND (tracks.file_path IS DISTINCT FROM lf.file_path)
                  AND lf.musicbrainz_trackid IN (
                      SELECT t2.musicbrainz_id FROM tracks t2
                      WHERE t2.musicbrainz_id IS NOT NULL
                      GROUP BY t2.musicbrainz_id
                      HAVING COUNT(*) = 1
                  )
                  {path_filter}
            """)
            update_result = db.execute(bulk_update_sql, bulk_params)
            tracks_updated = update_result.rowcount
            db.commit()

            job_logger.log_info(f"Fast path: {tracks_updated} tracks linked (unambiguous MBIDs)")

            # Step 2: Gather ambiguous candidates (Recording MBID matches multiple tracks)
            job.current_action = "Resolving ambiguous MBID matches with album-aware scoring..."
            db.commit()

            ambiguous_sql = text(f"""
                SELECT
                    lf.id AS file_id,
                    lf.file_path,
                    lf.musicbrainz_trackid AS recording_mbid,
                    lf.musicbrainz_releasegroupid AS file_rg_mbid,
                    t.id AS track_id,
                    t.album_id,
                    a.musicbrainz_id AS album_rg_mbid,
                    a.secondary_types AS album_secondary_types
                FROM library_files lf
                JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                JOIN albums a ON a.id = t.album_id
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND (t.file_path IS DISTINCT FROM lf.file_path)
                  AND lf.musicbrainz_trackid IN (
                      SELECT t2.musicbrainz_id FROM tracks t2
                      WHERE t2.musicbrainz_id IS NOT NULL
                      GROUP BY t2.musicbrainz_id
                      HAVING COUNT(*) > 1
                  )
                  {path_filter}
                ORDER BY lf.id, t.id
            """)
            ambiguous_rows = db.execute(ambiguous_sql, bulk_params).fetchall()

            if ambiguous_rows:
                # Step 3: Score and resolve ambiguous matches in Python
                from collections import defaultdict

                # Group candidates by file
                file_candidates = defaultdict(list)
                for row in ambiguous_rows:
                    file_candidates[str(row.file_id)].append({
                        'file_id': str(row.file_id),
                        'file_path': row.file_path,
                        'recording_mbid': row.recording_mbid,
                        'file_rg_mbid': row.file_rg_mbid,
                        'track_id': str(row.track_id),
                        'album_id': str(row.album_id),
                        'album_rg_mbid': row.album_rg_mbid,
                        'album_secondary_types': row.album_secondary_types,
                    })

                # Two-pass scoring
                album_match_counts = defaultdict(int)  # album_id -> count of files assigned
                resolved = {}  # file_id -> chosen candidate

                def _is_compilation(secondary_types):
                    if not secondary_types:
                        return False
                    return 'compilation' in secondary_types.lower()

                def _score_candidate(candidate, use_cohort=True):
                    score = 0
                    # Release Group MBID match
                    if candidate['file_rg_mbid'] and candidate['album_rg_mbid']:
                        if candidate['file_rg_mbid'] == candidate['album_rg_mbid']:
                            score += 1000
                    # Non-compilation preference
                    if not _is_compilation(candidate['album_secondary_types']):
                        score += 50
                    # Cohort score
                    if use_cohort:
                        score += album_match_counts.get(candidate['album_id'], 0)
                    return score

                # Pass 1: Assign files with definitive release-group matches (score >= 1000)
                for file_id, candidates in file_candidates.items():
                    best = max(candidates, key=lambda c: _score_candidate(c, use_cohort=False))
                    if _score_candidate(best, use_cohort=False) >= 1000:
                        resolved[file_id] = best
                        album_match_counts[best['album_id']] += 1

                # Pass 2: Assign remaining files using cohort + album-type preference
                for file_id, candidates in file_candidates.items():
                    if file_id in resolved:
                        continue
                    best = max(candidates, key=lambda c: _score_candidate(c, use_cohort=True))
                    resolved[file_id] = best
                    album_match_counts[best['album_id']] += 1

                # Batch UPDATE resolved ambiguous matches
                ambiguous_updated = 0
                for file_id, chosen in resolved.items():
                    db.execute(
                        text("UPDATE tracks SET file_path = :file_path, has_file = true WHERE id = CAST(:track_id AS uuid) AND (file_path IS DISTINCT FROM :file_path)"),
                        {'file_path': chosen['file_path'], 'track_id': chosen['track_id']}
                    )
                    ambiguous_updated += 1
                db.commit()

                tracks_updated += ambiguous_updated
                job_logger.log_info(f"Album-aware scoring: {ambiguous_updated} tracks linked (ambiguous MBIDs from {len(file_candidates)} files)")

            # Count unique library files that are now linked to at least one track
            linked_files_sql = text(f"""
                SELECT COUNT(DISTINCT lf.id) FROM library_files lf
                JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND t.has_file = true
                  {path_filter}
            """)
            linked_count = db.execute(linked_files_sql, bulk_params).scalar() or 0

            # Count already-linked files (unique library files where file_path already matched)
            # This is: linked_count minus files that were just updated
            # But simpler: total linked files - we already have linked_count above
            # For "already linked" we want files that were linked BEFORE this run
            # Since we can't easily distinguish, report total linked files
            already_linked = linked_count  # Total unique files linked (includes newly + previously)

            # Count unmatched files (MBID exists in library but not in tracks)
            no_match_sql = text(f"""
                SELECT COUNT(*) FROM library_files lf
                LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND t.id IS NULL
                  {path_filter}
            """)
            no_match = db.execute(no_match_sql, bulk_params).scalar() or 0
            failed_count = 0

        job_logger.log_phase_complete("File Linking", count=tracks_updated)

        # Log summary - report unique file counts, not track row counts
        job_logger.log_info("=" * 50)
        job_logger.log_info("FILE LINKING SUMMARY")
        job_logger.log_info("=" * 50)
        job_logger.log_info(f"Total library files with MBID: {total_files}")
        job_logger.log_info(f"Files linked to tracks: {linked_count}")
        job_logger.log_info(f"Files with no matching track: {no_match}")
        job_logger.log_info(f"Track rows updated: {tracks_updated}")
        job_logger.log_info(f"Files failed: {failed_count}")
        job_logger.log_info("=" * 50)

        # ── Release Group Fallback Matching ──
        # For files with a Recording MBID that didn't match any track directly,
        # look up the recording's release group in the local MB DB and fuzzy-match
        # against album tracks in our DB. This handles cases where MusicBrainz has
        # multiple Recording MBIDs for the same song across different releases.
        rg_fallback_linked = 0
        try:
            from app.services.musicbrainz_local import get_musicbrainz_local_db
            local_db = get_musicbrainz_local_db()
            if local_db and no_match > 0:
                import re as _re
                from difflib import SequenceMatcher

                def _normalize_title(s):
                    if not s:
                        return ""
                    s = s.lower()
                    s = _re.sub(r'[^\w\s]', '', s)
                    s = _re.sub(r'\s+', ' ', s).strip()
                    return s

                job_logger.log_phase_start("Release Group Fallback", f"Attempting fuzzy match for {no_match} unlinked files via release group lookup")
                job.current_action = "Release group fallback matching..."
                db.commit()

                BATCH_SIZE = 1000
                MB_BATCH_SIZE = 500
                offset = 0

                while True:
                    # Fetch batch of unlinked files (have MBID but no matching track)
                    unlinked_sql = text(f"""
                        SELECT lf.id, lf.file_path, lf.title, lf.musicbrainz_trackid, lf.duration_seconds
                        FROM library_files lf
                        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                        WHERE lf.musicbrainz_trackid IS NOT NULL
                          AND t.id IS NULL
                          {path_filter}
                        ORDER BY lf.id
                        LIMIT :batch_limit OFFSET :batch_offset
                    """)
                    batch_params = {**bulk_params, 'batch_limit': BATCH_SIZE, 'batch_offset': offset}
                    unlinked_rows = db.execute(unlinked_sql, batch_params).fetchall()

                    if not unlinked_rows:
                        break

                    # Collect unique recording MBIDs from this batch
                    recording_mbids = list(set(row.musicbrainz_trackid for row in unlinked_rows if row.musicbrainz_trackid))

                    if not recording_mbids:
                        offset += BATCH_SIZE
                        continue

                    # Query local MB DB: recording -> release_group mapping (in sub-batches)
                    recording_to_rg = {}  # recording_gid -> [(release_group_gid, recording_name)]
                    for i in range(0, len(recording_mbids), MB_BATCH_SIZE):
                        mb_batch = recording_mbids[i:i + MB_BATCH_SIZE]
                        try:
                            with local_db.engine.connect() as mb_conn:
                                rg_sql = text("""
                                    SELECT DISTINCT
                                        r.gid::text AS recording_gid,
                                        r.name AS recording_name,
                                        rg.gid::text AS release_group_gid
                                    FROM musicbrainz.recording r
                                    JOIN musicbrainz.track t ON t.recording = r.id
                                    JOIN musicbrainz.medium m ON m.id = t.medium
                                    JOIN musicbrainz.release rel ON rel.id = m.release
                                    JOIN musicbrainz.release_group rg ON rg.id = rel.release_group
                                    WHERE r.gid = ANY(CAST(:recording_mbids AS uuid[]))
                                """)
                                rg_rows = mb_conn.execute(rg_sql, {'recording_mbids': mb_batch}).fetchall()
                                for rg_row in rg_rows:
                                    rec_gid = rg_row.recording_gid
                                    if rec_gid not in recording_to_rg:
                                        recording_to_rg[rec_gid] = []
                                    recording_to_rg[rec_gid].append({
                                        'release_group_gid': rg_row.release_group_gid,
                                        'recording_name': rg_row.recording_name
                                    })
                        except Exception as mb_err:
                            logger.warning(f"Release group fallback MB query failed: {mb_err}")
                            continue

                    if not recording_to_rg:
                        offset += BATCH_SIZE
                        continue

                    # Collect all unique release group GIDs and find matching albums in our DB
                    all_rg_gids = list(set(
                        info['release_group_gid']
                        for infos in recording_to_rg.values()
                        for info in infos
                    ))

                    # Batch lookup: which release groups match albums in our DB?
                    rg_to_album = {}  # release_group_gid -> album_id
                    for i in range(0, len(all_rg_gids), MB_BATCH_SIZE):
                        rg_batch = all_rg_gids[i:i + MB_BATCH_SIZE]
                        album_sql = text("""
                            SELECT id, musicbrainz_id FROM albums
                            WHERE musicbrainz_id = ANY(:rg_gids)
                        """)
                        album_rows = db.execute(album_sql, {'rg_gids': rg_batch}).fetchall()
                        for arow in album_rows:
                            rg_to_album[arow.musicbrainz_id] = str(arow.id)

                    if not rg_to_album:
                        offset += BATCH_SIZE
                        continue

                    # For each unlinked file, try to fuzzy-match against album tracks
                    # Pre-fetch tracks for all matched albums
                    matched_album_ids = list(set(rg_to_album.values()))
                    album_tracks_map = {}  # album_id -> [(track_id, title, duration_ms, musicbrainz_id, file_path, has_file)]
                    for i in range(0, len(matched_album_ids), MB_BATCH_SIZE):
                        aid_batch = matched_album_ids[i:i + MB_BATCH_SIZE]
                        tracks_sql = text("""
                            SELECT id, album_id, title, duration_ms, musicbrainz_id, file_path, has_file
                            FROM tracks
                            WHERE album_id = ANY(CAST(:album_ids AS uuid[]))
                            ORDER BY album_id, disc_number, track_number
                        """)
                        track_rows = db.execute(tracks_sql, {'album_ids': aid_batch}).fetchall()
                        for trow in track_rows:
                            aid = str(trow.album_id)
                            if aid not in album_tracks_map:
                                album_tracks_map[aid] = []
                            album_tracks_map[aid].append({
                                'id': str(trow.id),
                                'title': trow.title,
                                'duration_ms': trow.duration_ms,
                                'musicbrainz_id': trow.musicbrainz_id,
                                'file_path': trow.file_path,
                                'has_file': trow.has_file,
                            })

                    # Match files to tracks
                    updates = []  # (track_id, file_path) pairs to update
                    for row in unlinked_rows:
                        rec_mbid = row.musicbrainz_trackid
                        rg_infos = recording_to_rg.get(rec_mbid)
                        if not rg_infos:
                            continue

                        # Find which release groups have albums in our DB
                        candidate_album_ids = []
                        mb_recording_name = None
                        for info in rg_infos:
                            album_id = rg_to_album.get(info['release_group_gid'])
                            if album_id:
                                candidate_album_ids.append(album_id)
                                if not mb_recording_name:
                                    mb_recording_name = info['recording_name']

                        if not candidate_album_ids:
                            continue

                        # Use file title, fall back to MB recording name
                        file_title = row.title or mb_recording_name
                        if not file_title:
                            continue
                        file_title_norm = _normalize_title(file_title)
                        # library_files stores seconds, tracks stores ms
                        file_duration_ms = (row.duration_seconds * 1000) if row.duration_seconds else None

                        best_track_id = None
                        best_score = 0.0

                        for album_id in candidate_album_ids:
                            tracks_list = album_tracks_map.get(album_id, [])
                            for trk in tracks_list:
                                # Skip tracks that already have a file
                                if trk['has_file'] and trk['file_path']:
                                    continue

                                track_title_norm = _normalize_title(trk['title'])
                                ratio = SequenceMatcher(None, file_title_norm, track_title_norm).ratio()

                                if ratio >= 0.6:
                                    # Duration bonus
                                    if file_duration_ms and trk['duration_ms']:
                                        duration_diff = abs(file_duration_ms - trk['duration_ms'])
                                        if duration_diff <= 5000:
                                            ratio += 0.05

                                    if ratio > best_score:
                                        best_score = ratio
                                        best_track_id = trk['id']

                        if best_track_id:
                            updates.append((best_track_id, row.file_path))
                            # Mark track as taken so we don't double-assign
                            for album_id in candidate_album_ids:
                                for trk in album_tracks_map.get(album_id, []):
                                    if trk['id'] == best_track_id:
                                        trk['has_file'] = True
                                        trk['file_path'] = row.file_path
                                        break

                    # Bulk update matched tracks
                    if updates:
                        for track_id, file_path in updates:
                            db.execute(
                                text("UPDATE tracks SET file_path = :file_path, has_file = true WHERE id = CAST(:track_id AS uuid) AND (file_path IS DISTINCT FROM :file_path)"),
                                {'file_path': file_path, 'track_id': track_id}
                            )
                        db.commit()
                        rg_fallback_linked += len(updates)

                    offset += BATCH_SIZE

                    # Update job progress
                    job.current_action = f"Release group fallback: {rg_fallback_linked} files linked so far..."
                    db.commit()

                # Update the no_match count after fallback
                no_match_after = db.execute(no_match_sql, bulk_params).scalar() or 0

                job_logger.log_info("=" * 50)
                job_logger.log_info("RELEASE GROUP FALLBACK SUMMARY")
                job_logger.log_info("=" * 50)
                job_logger.log_info(f"Files attempted: {no_match}")
                job_logger.log_info(f"Files linked via release group: {rg_fallback_linked}")
                job_logger.log_info(f"Remaining unlinked: {no_match_after}")
                job_logger.log_info("=" * 50)
                job_logger.log_phase_complete("Release Group Fallback", count=rg_fallback_linked)

                # Update running totals
                linked_count += rg_fallback_linked
                no_match = no_match_after
                tracks_updated += rg_fallback_linked
            elif not local_db:
                job_logger.log_info("Skipping release group fallback (local MusicBrainz DB not available)")
        except Exception as e:
            logger.error(f"Release group fallback failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Release group fallback failed (non-fatal): {e}")
            db.rollback()

        # ── Auto-Import Missing Albums ──
        # For files categorized as album_not_in_db where:
        # - The artist exists in our DB
        # - The file has a musicbrainz_releasegroupid
        # Import the release group as Album + Tracks, then re-link
        auto_import_albums_linked = 0
        try:
            if no_match > 0:
                from app.services.album_importer import import_release_group, bulk_import_release_groups
                from app.services.musicbrainz_client import get_musicbrainz_client as _get_mb_client

                # Find distinct (artist_id, release_group_mbid) pairs for album_not_in_db files
                missing_albums_sql = text(f"""
                    SELECT DISTINCT lf.musicbrainz_releasegroupid AS rg_mbid, a.id AS artist_id
                    FROM library_files lf
                    JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
                    LEFT JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid
                    LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                    WHERE lf.musicbrainz_trackid IS NOT NULL
                      AND t.id IS NULL
                      AND lf.musicbrainz_releasegroupid IS NOT NULL
                      AND lf.musicbrainz_releasegroupid != ''
                      AND a.id IS NOT NULL
                      AND al.id IS NULL
                      {path_filter}
                """)
                missing_rows = db.execute(missing_albums_sql, bulk_params).fetchall()

                if missing_rows:
                    job_logger.log_phase_start(
                        "Auto-Import Albums",
                        f"Importing {len(missing_rows)} missing release groups"
                    )
                    job.current_action = f"Auto-importing {len(missing_rows)} missing albums..."
                    db.commit()

                    mb_client = _get_mb_client()
                    artist_rg_pairs = [(row.artist_id, row.rg_mbid) for row in missing_rows]

                    def _auto_import_progress(imported, total, title):
                        job.current_action = f"Auto-import: {imported}/{total} albums ({title})"
                        try:
                            db.commit()
                        except Exception:
                            pass

                    import_stats = bulk_import_release_groups(
                        db, artist_rg_pairs, mb_client, progress_callback=_auto_import_progress
                    )

                    job_logger.log_info("=" * 50)
                    job_logger.log_info("AUTO-IMPORT ALBUMS SUMMARY")
                    job_logger.log_info("=" * 50)
                    job_logger.log_info(f"Release groups found: {len(missing_rows)}")
                    job_logger.log_info(f"Albums imported: {import_stats['albums_imported']}")
                    job_logger.log_info(f"Tracks created: {import_stats['tracks_created']}")
                    job_logger.log_info(f"Skipped (already exist): {import_stats['skipped']}")
                    job_logger.log_info(f"Failed: {import_stats['failed']}")
                    job_logger.log_info("=" * 50)
                    job_logger.log_phase_complete("Auto-Import Albums", count=import_stats['albums_imported'])

                    # Re-run MBID matching for newly imported tracks
                    if import_stats['albums_imported'] > 0:
                        job.current_action = "Re-linking files after auto-import..."
                        db.commit()

                        # Fast path re-match
                        relink_result = db.execute(bulk_update_sql, bulk_params)
                        relink_count = relink_result.rowcount
                        db.commit()

                        job_logger.log_info(f"Re-link after auto-import: {relink_count} additional files linked via fast path")
                        auto_import_albums_linked += relink_count
                        linked_count += relink_count
                        tracks_updated += relink_count

                        # Update no_match count
                        no_match = db.execute(no_match_sql, bulk_params).scalar() or 0
                        job_logger.log_info(f"Remaining unlinked after auto-import: {no_match}")
                else:
                    job_logger.log_info("No missing albums to auto-import (all release groups already in DB or no artist match)")

        except Exception as e:
            logger.error(f"Auto-import albums failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Auto-import albums failed (non-fatal): {e}")
            db.rollback()

        # ── Populate unlinked_files table ──
        try:
            job_logger.log_phase_start("Categorize Unlinked", "Recording unlinked files with reasons")
            job.current_action = "Categorizing unlinked files..."
            db.commit()

            # Step 1: Mark files that just got linked as resolved
            resolve_sql = text(f"""
                UPDATE unlinked_files uf
                SET resolved_at = now()
                FROM library_files lf
                JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                WHERE uf.library_file_id = lf.id
                  AND uf.resolved_at IS NULL
                  {path_filter.replace('lf.library_path_id', 'lf.library_path_id')}
            """)
            resolve_result = db.execute(resolve_sql, bulk_params)
            resolved_count = resolve_result.rowcount
            db.commit()

            # Step 2: Upsert files with MBID but no matching track (with detailed reason)
            upsert_mbid_sql = text(f"""
                INSERT INTO unlinked_files (library_file_id, file_path, artist, album, title, musicbrainz_trackid, reason, reason_detail, job_id, detected_at)
                SELECT
                    lf.id,
                    lf.file_path,
                    lf.artist,
                    lf.album,
                    lf.title,
                    lf.musicbrainz_trackid,
                    CASE
                        WHEN lf.musicbrainz_artistid IS NOT NULL AND a.id IS NULL THEN 'artist_not_in_db'
                        WHEN a.id IS NOT NULL AND al.id IS NULL THEN 'album_not_in_db'
                        ELSE 'no_matching_track'
                    END,
                    CASE
                        WHEN lf.musicbrainz_artistid IS NOT NULL AND a.id IS NULL
                            THEN 'Artist MBID ' || lf.musicbrainz_artistid || ' not imported'
                        WHEN a.id IS NOT NULL AND al.id IS NULL
                            THEN 'Artist exists but album not imported (release group: ' || COALESCE(lf.musicbrainz_releasegroupid, 'unknown') || ')'
                        ELSE 'Track MBID exists in file but no matching track record in database'
                    END,
                    CAST(:job_id AS uuid),
                    now()
                FROM library_files lf
                LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                LEFT JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
                LEFT JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid AND al.artist_id = a.id
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND t.id IS NULL
                  {path_filter}
                ON CONFLICT (library_file_id) DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    artist = EXCLUDED.artist,
                    album = EXCLUDED.album,
                    title = EXCLUDED.title,
                    musicbrainz_trackid = EXCLUDED.musicbrainz_trackid,
                    reason = EXCLUDED.reason,
                    reason_detail = EXCLUDED.reason_detail,
                    job_id = EXCLUDED.job_id,
                    detected_at = now(),
                    resolved_at = NULL
            """)
            mbid_params = {**bulk_params, 'job_id': job_id}
            upsert_mbid_result = db.execute(upsert_mbid_sql, mbid_params)
            upserted_mbid_count = upsert_mbid_result.rowcount
            db.commit()

            # Step 3: Upsert files with no MBID at all
            upsert_no_mbid_sql = text(f"""
                INSERT INTO unlinked_files (library_file_id, file_path, artist, album, title, musicbrainz_trackid, reason, reason_detail, job_id, detected_at)
                SELECT
                    lf.id,
                    lf.file_path,
                    lf.artist,
                    lf.album,
                    lf.title,
                    NULL,
                    'no_mbid',
                    'File has no MusicBrainz Recording ID in metadata',
                    CAST(:job_id_no_mbid AS uuid),
                    now()
                FROM library_files lf
                WHERE lf.musicbrainz_trackid IS NULL
                  {path_filter}
                ON CONFLICT (library_file_id) DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    artist = EXCLUDED.artist,
                    album = EXCLUDED.album,
                    title = EXCLUDED.title,
                    reason = EXCLUDED.reason,
                    reason_detail = EXCLUDED.reason_detail,
                    job_id = EXCLUDED.job_id,
                    detected_at = now(),
                    resolved_at = NULL
            """)
            no_mbid_params = {**bulk_params, 'job_id_no_mbid': job_id}
            upsert_no_mbid_result = db.execute(upsert_no_mbid_sql, no_mbid_params)
            upserted_no_mbid_count = upsert_no_mbid_result.rowcount
            db.commit()

            # Step 4: Log summary by reason
            reason_counts_sql = text("""
                SELECT reason, COUNT(*) as cnt
                FROM unlinked_files
                WHERE resolved_at IS NULL
                GROUP BY reason
                ORDER BY cnt DESC
            """)
            reason_counts = db.execute(reason_counts_sql).fetchall()

            job_logger.log_info("UNLINKED FILES BREAKDOWN:")
            total_unlinked = 0
            for reason, cnt in reason_counts:
                job_logger.log_info(f"  {reason}: {cnt}")
                total_unlinked += cnt
            job_logger.log_info(f"  Total unlinked: {total_unlinked}")
            if resolved_count > 0:
                job_logger.log_info(f"  Newly resolved: {resolved_count}")

            job_logger.log_phase_complete("Categorize Unlinked", count=total_unlinked)

        except Exception as e:
            logger.error(f"Failed to populate unlinked_files: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Failed to categorize unlinked files: {e}")
            db.rollback()

        # Auto-import unlinked artists if requested
        auto_imported_count = 0
        resolved_artist_mbids = 0
        if auto_import_artists and no_match > 0:
            try:
                from app.models.artist import Artist
                from app.models.track import Track
                from app.services.musicbrainz_client import get_musicbrainz_client
                from app.tasks.sync_tasks import sync_artist_albums_standalone
                from sqlalchemy import distinct, func
                import time as time_module

                mb_client = get_musicbrainz_client()

                # ── Phase A: Resolve Artist MBIDs from Recording MBIDs ──
                job_logger.log_phase_start("Resolve Artist MBIDs", "Looking up artist info from recording MBIDs")

                # Group files by artist name where we have recording MBID but no artist MBID
                artist_groups = db.query(
                    LibraryFile.artist,
                    func.min(LibraryFile.musicbrainz_trackid).label('sample_recording_mbid'),
                    func.count(LibraryFile.id).label('file_count')
                ).filter(
                    LibraryFile.musicbrainz_trackid.isnot(None),
                    LibraryFile.musicbrainz_trackid != '',
                    (LibraryFile.musicbrainz_artistid.is_(None)) | (LibraryFile.musicbrainz_artistid == ''),
                    LibraryFile.artist.isnot(None),
                    LibraryFile.artist != ''
                )
                if library_path_id:
                    artist_groups = artist_groups.filter(
                        LibraryFile.library_path_id == UUID(library_path_id)
                    )
                artist_groups = artist_groups.group_by(LibraryFile.artist).all()

                total_groups = len(artist_groups)
                job_logger.log_info(f"Found {total_groups} artist groups needing MBID resolution")

                for idx, (artist_name, sample_mbid, file_count) in enumerate(artist_groups):
                    try:
                        recording = mb_client.get_recording(sample_mbid, includes=['artists'])
                        if not recording:
                            continue
                        credits = recording.get('artist-credit', [])
                        if not credits or not isinstance(credits[0], dict):
                            continue
                        artist_mbid = credits[0].get('artist', {}).get('id')
                        if not artist_mbid:
                            continue

                        # Batch-update all files with this artist name
                        update_filter = db.query(LibraryFile).filter(
                            LibraryFile.artist == artist_name,
                            (LibraryFile.musicbrainz_artistid.is_(None)) | (LibraryFile.musicbrainz_artistid == ''),
                            LibraryFile.musicbrainz_trackid.isnot(None)
                        )
                        if library_path_id:
                            update_filter = update_filter.filter(
                                LibraryFile.library_path_id == UUID(library_path_id)
                            )
                        update_filter.update(
                            {LibraryFile.musicbrainz_artistid: artist_mbid},
                            synchronize_session=False
                        )
                        db.commit()
                        resolved_artist_mbids += 1

                        # Progress update
                        job.current_action = f"Resolving artist MBIDs: {idx + 1}/{total_groups} ({artist_name})"
                        db.commit()

                        time_module.sleep(1.0)  # MusicBrainz rate limit

                    except Exception as e:
                        logger.warning(f"Failed to resolve artist MBID for '{artist_name}' via recording {sample_mbid}: {e}")
                        db.rollback()

                job_logger.log_phase_complete("Resolve Artist MBIDs", count=resolved_artist_mbids)
                job_logger.log_info(f"Resolved artist MBIDs for {resolved_artist_mbids}/{total_groups} artist groups")

                # ── Phase B: Import New Artists & Sync Albums/Tracks ──
                job_logger.log_phase_start("Auto-Import Artists", "Importing artists for unlinked files")

                # Find unique artist MBIDs from unlinked files
                unlinked_artist_query = db.query(
                    distinct(LibraryFile.musicbrainz_artistid).label('artist_mbid')
                ).filter(
                    LibraryFile.musicbrainz_trackid.isnot(None),
                    LibraryFile.musicbrainz_artistid.isnot(None),
                    LibraryFile.musicbrainz_artistid != '',
                    ~LibraryFile.musicbrainz_trackid.in_(
                        db.query(Track.musicbrainz_id).filter(Track.musicbrainz_id.isnot(None))
                    )
                )
                if library_path_id:
                    unlinked_artist_query = unlinked_artist_query.filter(
                        LibraryFile.library_path_id == UUID(library_path_id)
                    )

                artist_mbids = [r.artist_mbid for r in unlinked_artist_query.all() if r.artist_mbid]

                # Filter out existing artists
                new_artist_ids = []
                if artist_mbids:
                    existing_mbids = {
                        r[0] for r in
                        db.query(Artist.musicbrainz_id).filter(
                            Artist.musicbrainz_id.in_(artist_mbids)
                        ).all()
                    }
                    new_mbids = [m for m in artist_mbids if m not in existing_mbids]
                    total_new = len(new_mbids)
                    job_logger.log_info(f"Found {len(artist_mbids)} unique artist MBIDs, {total_new} new to import")

                    for idx, mbid in enumerate(new_mbids):
                        try:
                            artist_info = mb_client.get_artist(mbid)
                            if not artist_info:
                                continue

                            artist_name = artist_info.get("name", f"Unknown ({mbid})")
                            new_artist = Artist(
                                name=artist_name,
                                musicbrainz_id=mbid,
                                is_monitored=False,
                                import_source="studio54",
                                studio54_library_path_id=library_path_id,
                                added_at=datetime.now(timezone.utc)
                            )
                            db.add(new_artist)
                            db.commit()
                            db.refresh(new_artist)
                            new_artist_ids.append(str(new_artist.id))

                            # Sync albums/tracks synchronously so tracks exist for re-linking
                            job.current_action = f"Importing artist {idx + 1}/{total_new}: {artist_name}"
                            db.commit()

                            try:
                                sync_result = sync_artist_albums_standalone(db, str(new_artist.id))
                                track_count = sync_result.get('tracks_synced', 0) if sync_result else 0
                                job_logger.log_info(f"Imported artist: {artist_name} ({track_count} tracks synced)")
                            except Exception as e:
                                logger.warning(f"Album sync failed for {artist_name}: {e}")
                                job_logger.log_info(f"Imported artist: {artist_name} (sync failed: {e})")

                            auto_imported_count += 1

                        except Exception as e:
                            error_str = str(e).lower()
                            if "duplicate key" not in error_str and "unique constraint" not in error_str:
                                logger.warning(f"Failed to auto-import artist MBID {mbid}: {e}")
                            db.rollback()

                job_logger.log_phase_complete("Auto-Import Artists", count=auto_imported_count)
                job_logger.log_info(f"Auto-imported {auto_imported_count} new artists")

                # ── Phase B2: Re-sync existing artists with zero-track albums ──
                resync_count = 0
                try:
                    job_logger.log_phase_start("Re-Sync Zero-Track Albums", "Backfilling tracks for existing artists")

                    # Find existing artists that have unlinked files with 'no_matching_track' reason
                    resync_sql = text(f"""
                        SELECT DISTINCT a.id as artist_id, a.name as artist_name, a.musicbrainz_id as artist_mbid
                        FROM library_files lf
                        JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
                        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                        WHERE lf.musicbrainz_trackid IS NOT NULL
                          AND t.id IS NULL
                          AND lf.musicbrainz_artistid IS NOT NULL
                          {path_filter}
                    """)
                    artists_to_resync = db.execute(resync_sql, bulk_params).fetchall()
                    total_resync = len(artists_to_resync)
                    job_logger.log_info(f"Found {total_resync} existing artists with unlinked files needing re-sync")

                    for idx, row in enumerate(artists_to_resync):
                        try:
                            job.current_action = f"Re-syncing artist {idx + 1}/{total_resync}: {row.artist_name}"
                            db.commit()

                            sync_result = sync_artist_albums_standalone(db, str(row.artist_id))
                            backfilled = sync_result.get('tracks_backfilled', 0) if sync_result else 0
                            job_logger.log_info(f"Re-synced: {row.artist_name} (backfilled {backfilled} tracks)")
                            resync_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to re-sync artist {row.artist_name}: {e}")
                            db.rollback()

                    job_logger.log_phase_complete("Re-Sync Zero-Track Albums", count=resync_count)
                except Exception as e:
                    logger.error(f"Re-sync zero-track albums failed: {e}\n{traceback.format_exc()}")
                    job_logger.log_error(f"Re-sync phase failed: {e}")

                # ── Phase C: Re-link files to newly created tracks (bulk) ──
                job_logger.log_phase_start("Re-Link Files", "Matching files to newly synced tracks (bulk)")

                relink_params = {}
                relink_filter = ""
                if library_path_id:
                    relink_filter = "AND lf.library_path_id = :relink_lp_id"
                    relink_params['relink_lp_id'] = library_path_id

                relink_sql = text(f"""
                    UPDATE tracks
                    SET file_path = lf.file_path, has_file = true
                    FROM library_files lf
                    WHERE tracks.musicbrainz_id = lf.musicbrainz_trackid
                      AND lf.musicbrainz_trackid IS NOT NULL
                      AND (tracks.file_path IS DISTINCT FROM lf.file_path)
                      {relink_filter}
                """)
                relink_result = db.execute(relink_sql, relink_params)
                relinked_count = relink_result.rowcount
                db.commit()

                job_logger.log_phase_complete("Re-Link Files", count=relinked_count)
                job_logger.log_info(f"Re-linked {relinked_count} track rows to newly synced tracks")

                # Recount unique linked files after relink
                recount_sql = text(f"""
                    SELECT COUNT(DISTINCT lf.id) FROM library_files lf
                    JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                    WHERE lf.musicbrainz_trackid IS NOT NULL
                      AND t.has_file = true
                      {path_filter}
                """)
                linked_count = db.execute(recount_sql, bulk_params).scalar() or 0

            except Exception as e:
                logger.error(f"Auto-import artists failed: {e}\n{traceback.format_exc()}")
                job_logger.log_error(f"Auto-import artists failed: {e}")

        # Count current unlinked totals for the summary
        try:
            unlinked_total = db.execute(text("SELECT COUNT(*) FROM unlinked_files WHERE resolved_at IS NULL")).scalar() or 0
        except Exception:
            unlinked_total = no_match

        # Recount no_match after any auto-import/relink phases
        no_match_final = db.execute(text(f"""
            SELECT COUNT(*) FROM library_files lf
            LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
            WHERE lf.musicbrainz_trackid IS NOT NULL
              AND t.id IS NULL
              {path_filter}
        """), bulk_params).scalar() or 0

        # Complete job - use standard stat keys for log_job_complete template
        complete_stats = {
            'files_total': total_files,
            'files_processed': total_files,
            'files_added': linked_count,
            'files_failed': failed_count,
        }

        # Log custom linking summary before the generic template
        job_logger.log_info("")
        job_logger.log_info("LINKING RESULTS:")
        job_logger.log_info(f"  Files linked:          {linked_count} of {total_files}")
        job_logger.log_info(f"  Files unlinked:        {unlinked_total}")
        job_logger.log_info(f"    No matching track:   {no_match_final}")
        job_logger.log_info(f"    No MBID:             {total_files - (linked_count + no_match_final) if total_files > linked_count + no_match_final else 0}")
        if resolved_artist_mbids > 0:
            job_logger.log_info(f"  Artist MBIDs resolved: {resolved_artist_mbids}")
        if auto_imported_count > 0:
            job_logger.log_info(f"  Artists auto-imported:  {auto_imported_count}")

        job_logger.log_job_complete(complete_stats)

        job.status = JobStatus.COMPLETED
        job.error_message = None  # Clear any stale stall detection messages
        job.progress_percent = 100.0
        job.files_processed = total_files
        job.files_renamed = linked_count   # Tracks unique files linked
        job.files_moved = 0
        job.files_failed = failed_count
        job.completed_at = datetime.now(timezone.utc)
        action_msg = f"Complete: {linked_count} of {total_files} files linked, {unlinked_total} unlinked"
        if auto_imported_count > 0:
            action_msg += f", {auto_imported_count} artists imported"
        if resolved_artist_mbids > 0:
            action_msg += f", {resolved_artist_mbids} artist MBIDs resolved"
        job.current_action = action_msg
        db.commit()

        logger.info(f"Completed file linking job {job_id}: {linked_count} linked")

    except Exception as e:
        logger.error(f"Error in file linking job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=43200, time_limit=43500)  # 12 hour limit for large libraries
def reindex_albums_task(self, job_id: str, library_path_id: str = None, artist_id: str = None):
    """
    Reindex Albums and Singles from File Metadata

    Scans library files and updates album/single records based on file metadata.
    Keeps singles separate from albums and updates statistics.

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Library UUID (optional)
        artist_id: Artist UUID (optional)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting album reindex job {job_id}")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_job_start("reindex_albums", "Reindexing albums and singles from file metadata")

        # Build query for files
        query = db.query(LibraryFile)
        if library_path_id:
            query = query.filter(LibraryFile.library_path_id == UUID(library_path_id))

        files = query.all()
        job.files_total = len(files)
        db.commit()

        job_logger.log_phase_start("Album Reindex", f"Processing {len(files)} files")

        # Group files by album
        albums_data = {}
        for library_file in files:
            album_key = (library_file.musicbrainz_albumid or library_file.album, library_file.artist)
            if album_key not in albums_data:
                albums_data[album_key] = {
                    'mbid': library_file.musicbrainz_albumid,
                    'title': library_file.album,
                    'artist': library_file.artist,
                    'artist_mbid': library_file.musicbrainz_artistid,
                    'year': library_file.year,
                    'files': [],
                    'track_count': 0
                }
            albums_data[album_key]['files'].append(library_file)
            albums_data[album_key]['track_count'] += 1

        albums_updated = 0
        singles_found = 0
        albums_found = 0
        stats_updated = 0

        job_logger.log_info(f"Found {len(albums_data)} unique album groups")

        for i, (album_key, album_info) in enumerate(albums_data.items()):
            try:
                # Progress update
                if (i + 1) % 10 == 0:
                    progress = (i + 1) / len(albums_data) * 100
                    job.progress_percent = progress
                    job.current_action = f"Reindexing: {i + 1}/{len(albums_data)} albums"
                    db.commit()

                # Determine if this is a single (1 track) or album
                is_single = album_info['track_count'] == 1

                if is_single:
                    singles_found += 1
                    album_type = 'Single'
                else:
                    albums_found += 1
                    album_type = 'Album'

                # Find or update album in database
                if album_info['mbid']:
                    # Try to find by MBID
                    album_query = text("""
                        SELECT id, album_type, track_count FROM albums
                        WHERE musicbrainz_id = :mbid
                    """)
                    result = db.execute(album_query, {'mbid': album_info['mbid']}).first()

                    if result:
                        album_id, current_type, current_track_count = result

                        # Update album type and track count if needed
                        updates = []
                        params = {'album_id': str(album_id)}

                        if current_type != album_type:
                            updates.append("album_type = :album_type")
                            params['album_type'] = album_type

                        if current_track_count != album_info['track_count']:
                            updates.append("track_count = :track_count")
                            params['track_count'] = album_info['track_count']

                        if updates:
                            update_query = text(f"""
                                UPDATE albums SET {', '.join(updates)}
                                WHERE id = :album_id
                            """)
                            db.execute(update_query, params)
                            albums_updated += 1
                            job_logger.log_info(
                                f"Updated album: {album_info['title']} "
                                f"(type: {album_type}, tracks: {album_info['track_count']})"
                            )

                # Commit periodically
                if (i + 1) % 50 == 0:
                    db.commit()

            except Exception as e:
                logger.warning(f"Error processing album {album_info['title']}: {e}")
                job_logger.log_error(f"Error processing {album_info['title']}: {e}")

        # Update artist statistics
        job_logger.log_phase_start("Statistics Update", "Updating artist album/single counts")

        artist_stats_query = text("""
            UPDATE artists a SET
                album_count = (
                    SELECT COUNT(*) FROM albums
                    WHERE artist_id = a.id AND album_type != 'Single'
                ),
                single_count = (
                    SELECT COUNT(*) FROM albums
                    WHERE artist_id = a.id AND album_type = 'Single'
                )
            WHERE a.id IN (
                SELECT DISTINCT artist_id FROM albums
            )
            RETURNING a.id
        """)
        result = db.execute(artist_stats_query)
        stats_updated = result.rowcount

        db.commit()

        job_logger.log_phase_complete("Statistics Update", count=stats_updated)

        # Log summary
        job_logger.log_info("=" * 50)
        job_logger.log_info("ALBUM REINDEX SUMMARY")
        job_logger.log_info("=" * 50)
        job_logger.log_info(f"Total files processed: {len(files)}")
        job_logger.log_info(f"Album groups found: {len(albums_data)}")
        job_logger.log_info(f"Albums (2+ tracks): {albums_found}")
        job_logger.log_info(f"Singles (1 track): {singles_found}")
        job_logger.log_info(f"Albums updated: {albums_updated}")
        job_logger.log_info(f"Artist stats updated: {stats_updated}")
        job_logger.log_info("=" * 50)

        # Complete job
        job_logger.log_job_complete({
            'files_total': len(files),
            'albums_found': albums_found,
            'singles_found': singles_found,
            'albums_updated': albums_updated,
            'stats_updated': stats_updated
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.files_processed = len(files)
        job.files_renamed = albums_updated
        job.files_moved = singles_found
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Complete: {albums_found} albums, {singles_found} singles"
        db.commit()

        logger.info(f"Completed album reindex job {job_id}")

    except Exception as e:
        logger.error(f"Error in album reindex job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=43200, time_limit=43500)  # 12 hour limit for large libraries
def verify_audio_task(self, job_id: str, days_back: int = 90):
    """
    Verify Audio Match of Downloaded Files

    Verifies that downloaded files within the past N days have matching
    audio content by comparing fingerprints.

    Args:
        job_id: FileOrganizationJob ID
        days_back: Number of days to look back for downloads (default 90)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting audio verification job {job_id} (last {days_back} days)")

        # Acquire job with row-level locking to prevent race conditions
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_job_start("verify_audio", f"Verifying audio files downloaded in last {days_back} days")

        # Get files downloaded within the time period
        from datetime import timedelta
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        files_query = text("""
            SELECT lf.id, lf.file_path, lf.title, lf.artist,
                   lf.musicbrainz_trackid, lf.duration_seconds
            FROM library_files lf
            WHERE lf.indexed_at >= :cutoff_date
            AND lf.musicbrainz_trackid IS NOT NULL
            ORDER BY lf.indexed_at DESC
        """)
        result = db.execute(files_query, {'cutoff_date': cutoff_date})
        files = result.fetchall()

        job.files_total = len(files)
        db.commit()

        job_logger.log_phase_start("Audio Verification", f"Verifying {len(files)} files")

        verified_count = 0
        mismatch_count = 0
        failed_count = 0
        mismatched_files = []

        for i, file_row in enumerate(files):
            file_id, file_path, title, artist, recording_mbid, duration = file_row

            try:
                # Progress update
                if (i + 1) % BATCH_SIZE == 0:
                    progress = (i + 1) / len(files) * 100
                    job.progress_percent = progress
                    job.current_action = f"Verifying: {i + 1}/{len(files)}"
                    job.files_processed = i + 1
                    db.commit()
                    job_logger.log_info(f"Verified {i + 1}/{len(files)} files")

                # Check if file exists
                import os
                if not os.path.exists(file_path):
                    job_logger.log_warning(f"File not found: {file_path}")
                    failed_count += 1
                    continue

                # Verify MBID is present in file
                verification = MetadataWriter.verify_mbid_in_file(file_path)

                if verification['has_mbid']:
                    # Check if MBID matches
                    file_recording_mbid = verification.get('recording_mbid')
                    if file_recording_mbid and file_recording_mbid != recording_mbid:
                        mismatch_count += 1
                        mismatched_files.append({
                            'file_path': file_path,
                            'expected_mbid': recording_mbid,
                            'found_mbid': file_recording_mbid,
                            'artist': artist,
                            'title': title
                        })
                        job_logger.log_warning(
                            f"MBID mismatch: {artist} - {title} "
                            f"(expected: {recording_mbid}, found: {file_recording_mbid})"
                        )
                    else:
                        verified_count += 1
                else:
                    # MBID not in file - this is a concern for downloaded files
                    mismatch_count += 1
                    mismatched_files.append({
                        'file_path': file_path,
                        'expected_mbid': recording_mbid,
                        'found_mbid': None,
                        'artist': artist,
                        'title': title,
                        'issue': 'MBID not written to file'
                    })
                    job_logger.log_warning(f"No MBID in downloaded file: {artist} - {title}")

            except Exception as e:
                failed_count += 1
                logger.warning(f"Error verifying file {file_path}: {e}")
                job_logger.log_error(f"Error verifying {file_path}: {e}")

        db.commit()

        job_logger.log_phase_complete("Audio Verification", count=verified_count)

        # Store mismatched files
        if mismatched_files:
            import json
            job.files_without_mbid = len(mismatched_files)
            job.files_without_mbid_json = json.dumps(mismatched_files[:1000])

        # Log summary
        job_logger.log_info("=" * 50)
        job_logger.log_info("AUDIO VERIFICATION SUMMARY")
        job_logger.log_info("=" * 50)
        job_logger.log_info(f"Time period: Last {days_back} days")
        job_logger.log_info(f"Total files checked: {len(files)}")
        job_logger.log_info(f"Files verified (MBID matches): {verified_count}")
        job_logger.log_info(f"Files with mismatches/issues: {mismatch_count}")
        job_logger.log_info(f"Files failed to verify: {failed_count}")
        job_logger.log_info("=" * 50)

        if mismatched_files:
            job_logger.log_info("MISMATCHED FILES:")
            for mf in mismatched_files[:50]:
                job_logger.log_info(f"  - {mf['artist']} - {mf['title']}: {mf.get('issue', 'MBID mismatch')}")
            if len(mismatched_files) > 50:
                job_logger.log_info(f"  ... and {len(mismatched_files) - 50} more")

        # Complete job
        job_logger.log_job_complete({
            'files_total': len(files),
            'files_verified': verified_count,
            'files_mismatched': mismatch_count,
            'files_failed': failed_count
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.files_processed = len(files)
        job.files_renamed = verified_count  # Using renamed for verified count
        job.files_failed = mismatch_count + failed_count
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Complete: {verified_count} verified, {mismatch_count} mismatches"
        db.commit()

        logger.info(f"Completed audio verification job {job_id}: {verified_count} verified, {mismatch_count} mismatches")

    except Exception as e:
        logger.error(f"Error in audio verification job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


# ========================================
# Log Cleanup Task
# ========================================

@shared_task(bind=True, soft_time_limit=1800, time_limit=1860)
def cleanup_old_logs_task(self, retention_days: int = 120):
    """
    Clean up job log files older than specified days
    
    This task should be run periodically (e.g., daily via Celery beat)
    to remove old log files and keep disk usage under control.
    
    Args:
        retention_days: Number of days to retain log files (default: 120)
    
    Returns:
        dict: Summary of cleanup results
    """
    db = SessionLocal()
    
    try:
        from datetime import timedelta
        import os
        import glob
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        log_dir = Path("/app/logs/jobs")
        
        logger.info(f"Starting log cleanup - removing files older than {retention_days} days (before {cutoff_date.date()})")
        
        deleted_count = 0
        failed_count = 0
        space_freed = 0
        db_updated_count = 0
        
        # Method 1: Clean up based on database records
        # Find completed/failed jobs older than retention period with log files
        old_jobs = db.query(FileOrganizationJob).filter(
            FileOrganizationJob.completed_at < cutoff_date,
            FileOrganizationJob.log_file_path.isnot(None),
            FileOrganizationJob.status.in_([JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.ROLLED_BACK])
        ).all()
        
        logger.info(f"Found {len(old_jobs)} old jobs with log files in database")
        
        for job in old_jobs:
            try:
                log_path = Path(job.log_file_path)
                
                if log_path.exists():
                    file_size = log_path.stat().st_size
                    log_path.unlink()
                    deleted_count += 1
                    space_freed += file_size
                    logger.debug(f"Deleted log file: {log_path}")
                
                # Also delete summary report if exists
                if job.summary_report_path:
                    summary_path = Path(job.summary_report_path)
                    if summary_path.exists():
                        summary_size = summary_path.stat().st_size
                        summary_path.unlink()
                        space_freed += summary_size
                        logger.debug(f"Deleted summary report: {summary_path}")
                
                # Clear paths in database
                job.log_file_path = None
                job.summary_report_path = None
                db_updated_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to delete log for job {job.id}: {e}")
                failed_count += 1
        
        db.commit()
        
        # Method 2: Clean up orphan log files not in database
        # This handles cases where jobs were deleted but logs remain
        if log_dir.exists():
            for log_file in log_dir.glob("*.log"):
                try:
                    # Check file modification time
                    file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime, tz=timezone.utc)
                    
                    if file_mtime < cutoff_date:
                        # Verify this log file is not in database
                        job_id_str = log_file.stem  # filename without extension
                        try:
                            job_uuid = UUID(job_id_str)
                            existing_job = db.query(FileOrganizationJob).filter(
                                FileOrganizationJob.id == job_uuid
                            ).first()
                            
                            if not existing_job:
                                # Orphan file - safe to delete
                                file_size = log_file.stat().st_size
                                log_file.unlink()
                                deleted_count += 1
                                space_freed += file_size
                                logger.debug(f"Deleted orphan log file: {log_file}")
                        except (ValueError, Exception):
                            # Invalid UUID format - likely not a job log, skip
                            pass
                
                except Exception as e:
                    logger.warning(f"Failed to process log file {log_file}: {e}")
                    failed_count += 1
        
        # Convert space freed to human-readable format
        if space_freed >= 1024 * 1024 * 1024:
            space_freed_str = f"{space_freed / (1024 * 1024 * 1024):.2f} GB"
        elif space_freed >= 1024 * 1024:
            space_freed_str = f"{space_freed / (1024 * 1024):.2f} MB"
        elif space_freed >= 1024:
            space_freed_str = f"{space_freed / 1024:.2f} KB"
        else:
            space_freed_str = f"{space_freed} bytes"
        
        logger.info(
            f"Log cleanup complete: {deleted_count} files deleted, "
            f"{db_updated_count} DB records updated, "
            f"{space_freed_str} freed, {failed_count} failures"
        )
        
        return {
            'success': True,
            'retention_days': retention_days,
            'cutoff_date': cutoff_date.isoformat(),
            'deleted_files': deleted_count,
            'db_records_updated': db_updated_count,
            'space_freed_bytes': space_freed,
            'space_freed_human': space_freed_str,
            'failed_count': failed_count
        }
        
    except Exception as e:
        logger.error(f"Error in log cleanup task: {e}\n{traceback.format_exc()}")
        return {
            'success': False,
            'error': str(e)
        }

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=43200, time_limit=43500, base=CheckpointableTask)  # 12 hour limit for large libraries
def validate_mbid_metadata_task(self, job_id: str):
    """
    Validate MBID Metadata Task

    For files that have MBIDs in their comment tags, this task:
    1. Reads the MBID from the file
    2. Looks up the recording on MusicBrainz
    3. Compares file metadata with MusicBrainz metadata
    4. Calculates confidence score
    5. Optionally updates file metadata if mismatched
    6. Updates database with validation results

    Args:
        job_id: FileOrganizationJob ID
    """
    db = SessionLocal()
    job_logger = None

    try:
        import time
        import json
        from app.services.metadata_extractor import MetadataExtractor
        from app.services.metadata_writer import MetadataWriter
        from app.services.musicbrainz_client import MusicBrainzClient
        from app.services.mbid_confidence_scorer import MBIDConfidenceScorer
        from app.models.library import LibraryFile, LibraryPath

        logger.info(f"Starting MBID metadata validation job {job_id}")

        # Initialize checkpoint
        self.init_checkpoint(job_id)

        # Load checkpoint for resume
        checkpoint = self.load_checkpoint()
        start_index = checkpoint.get('last_processed_index', 0)
        stats = checkpoint.get('stats', {
            'files_validated': 0,
            'files_metadata_correct': 0,
            'files_metadata_updated': 0,
            'files_low_confidence': 0,
            'files_failed': 0
        })

        # Acquire job with row-level locking to prevent race conditions
        # Allow resume from FAILED status if checkpoint has progress
        allow_resume = start_index > 0
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id, allow_resume=allow_resume)

        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return {"error": "Could not acquire job"}

        # Initialize job logger with correct job type
        job_logger = JobLogger(job_id=job_id, job_type="validate_mbid_metadata")
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Get library path
        library_path_id = job.library_path_id
        if not library_path_id:
            job_logger.log_error("No library_path_id on job")
            job.status = JobStatus.FAILED
            job.error_message = "No library_path_id on job"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return {"error": "No library_path_id"}

        library_path = db.query(LibraryPath).filter(LibraryPath.id == library_path_id).first()
        if not library_path:
            job_logger.log_error(f"Library path {library_path_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Library path {library_path_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return {"error": "Library path not found"}

        if start_index > 0:
            job_logger.log_info(f"RESUMING from index {start_index}")
        else:
            job_logger.log_job_start("validate_mbid_metadata", library_path.name)

        # Update heartbeat before starting large query (query can take time for large libraries)
        update_job_progress(
            db, job,
            current_action="Querying files with MBIDs..."
        )

        # Get all files with MBID in comments
        files_with_mbid = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id,
            LibraryFile.mbid_in_file == True
        ).all()

        total_files = len(files_with_mbid)
        job.files_total = total_files
        job.current_action = f"Validating metadata for {total_files} files with MBID"
        db.commit()

        job_logger.log_phase_start("MBID Metadata Validation", f"Checking {total_files} files with MBID")

        mb_client = MusicBrainzClient()
        low_confidence_files = []

        # Use background heartbeat thread to prevent stall detection during
        # long-running MusicBrainz API calls (can block 125s+ per request with retries)
        with BackgroundHeartbeat(job_id, FileOrganizationJob, interval=60):
            for i, library_file in enumerate(files_with_mbid):
                # Skip already processed (resume)
                if i < start_index:
                    continue

                # Check for pause request
                if self.should_pause():
                    self.save_checkpoint_and_pause({
                        'last_processed_index': i,
                        'stats': stats
                    })
                    job.status = JobStatus.PAUSED
                    job.current_action = f"Paused at file {i}/{total_files}"
                    job.files_processed = i
                    db.commit()
                    job_logger.log_info(f"Job paused at index {i}")
                    return {'status': 'paused', 'index': i}

                try:
                    file_path = library_file.file_path

                    # Progress update with heartbeat BEFORE the MusicBrainz lookup
                    # (lookups can wait in queue for extended time)
                    progress = (i + 1) / total_files * 100
                    job.progress_percent = progress
                    job.current_action = f"Validating: {i + 1}/{total_files}"
                    job.files_processed = i + 1
                    job.current_file_path = file_path
                    job.last_heartbeat_at = datetime.now(timezone.utc)
                    db.commit()

                    # Read MBID from file (can block on slow/corrupt files)
                    mbid_data = MetadataWriter.verify_mbid_in_file(file_path)

                    recording_mbid = mbid_data.get('recording_mbid')

                    if not recording_mbid:
                        stats['files_failed'] += 1
                        job_logger.log_warning(f"No recording MBID found in: {file_path}")
                        continue

                    # Look up recording on MusicBrainz (can wait up to 375s with retries)
                    job_logger.log_info(f"Looking up MBID: {recording_mbid}")
                    try:
                        mb_recording = mb_client.get_recording(
                            recording_mbid,
                            includes=['artists', 'releases']
                        )
                    except Exception as e:
                        stats['files_failed'] += 1
                        job_logger.log_error(f"MusicBrainz lookup failed for {recording_mbid}: {e}")
                        continue

                    if not mb_recording:
                        stats['files_failed'] += 1
                        job_logger.log_warning(f"Recording not found on MusicBrainz: {recording_mbid}")
                        continue

                    # Extract file metadata (can block on large/corrupt files)
                    file_metadata = MetadataExtractor.extract(file_path)

                    if not file_metadata:
                        stats['files_failed'] += 1
                        job_logger.log_warning(f"Could not extract metadata from: {file_path}")
                        continue

                    # Calculate confidence score
                    score_result = MBIDConfidenceScorer.score_match(
                        file_metadata={
                            'title': file_metadata.get('title'),
                            'artist': file_metadata.get('artist'),
                            'album': file_metadata.get('album'),
                            'duration': file_metadata.get('duration') or file_metadata.get('length')
                        },
                        mb_recording=mb_recording
                    )

                    confidence_score = score_result['total_score']
                    confidence_level = score_result['confidence_level']
                    breakdown = score_result['breakdown']

                    stats['files_validated'] += 1

                    # Log confidence details
                    job_logger.log_info(
                        f"Validation: {file_metadata.get('artist')} - {file_metadata.get('title')} | "
                        f"Score: {confidence_score}/100 ({confidence_level})"
                    )

                    # High confidence - metadata matches
                    if confidence_score >= MBIDConfidenceScorer.HIGH_CONFIDENCE:
                        stats['files_metadata_correct'] += 1
                        job_logger.log_info(f"  ✓ Metadata matches MusicBrainz")

                    # Medium confidence - acceptable but note differences
                    elif confidence_score >= MBIDConfidenceScorer.MEDIUM_CONFIDENCE:
                        stats['files_metadata_correct'] += 1
                        job_logger.log_info(f"  ✓ Metadata acceptable (minor differences)")
                        # Log differences
                        if breakdown['title']['score'] < breakdown['title']['max'] * 0.9:
                            job_logger.log_info(f"    Title: '{breakdown['title']['file']}' vs MB: '{breakdown['title']['mb']}'")
                        if breakdown['artist']['score'] < breakdown['artist']['max'] * 0.9:
                            job_logger.log_info(f"    Artist: '{breakdown['artist']['file']}' vs MB: '{breakdown['artist']['mb']}'")

                    # Low confidence - needs review or update
                    else:
                        stats['files_low_confidence'] += 1
                        low_confidence_files.append({
                            'file_path': file_path,
                            'score': confidence_score,
                            'level': confidence_level,
                            'file_title': file_metadata.get('title'),
                            'file_artist': file_metadata.get('artist'),
                            'mb_title': breakdown['title']['mb'],
                            'mb_artist': breakdown['artist']['mb'],
                            'recording_mbid': recording_mbid
                        })
                        job_logger.log_warning(
                            f"  ⚠ Low confidence ({confidence_score}/100) - may need review:\n"
                            f"    File:  {file_metadata.get('artist')} - {file_metadata.get('title')}\n"
                            f"    MB:    {breakdown['artist']['mb']} - {breakdown['title']['mb']}"
                        )

                    # Update library_file with validation info
                    library_file.mbid_verified_at = datetime.now(timezone.utc)

                    # Save checkpoint periodically
                    if (i + 1) % 100 == 0:
                        self.save_checkpoint({
                            'last_processed_index': i + 1,
                            'stats': stats
                        })

                except Exception as e:
                    stats['files_failed'] += 1
                    logger.warning(f"Error validating {library_file.file_path}: {e}")
                    job_logger.log_error(f"Error validating {library_file.file_path}: {e}")
                    # Keep heartbeat alive even on errors
                    try:
                        job.last_heartbeat_at = datetime.now(timezone.utc)
                        db.commit()
                    except Exception:
                        db.rollback()
                    continue

        # Final commit
        db.commit()

        # Clear checkpoint on successful completion
        self.clear_checkpoint()

        job_logger.log_phase_complete("MBID Metadata Validation", count=stats['files_validated'])

        # Store low confidence files list
        if low_confidence_files:
            job.files_without_mbid = len(low_confidence_files)
            job.files_without_mbid_json = json.dumps(low_confidence_files[:10000])

        # Generate summary report
        job_logger.log_info("=" * 50)
        job_logger.log_info("MBID METADATA VALIDATION SUMMARY")
        job_logger.log_info("=" * 50)
        job_logger.log_info(f"Total files checked: {total_files}")
        job_logger.log_info(f"Files validated: {stats['files_validated']}")
        job_logger.log_info(f"Files with correct metadata: {stats['files_metadata_correct']}")
        job_logger.log_info(f"Files with low confidence: {stats['files_low_confidence']}")
        job_logger.log_info(f"Files failed: {stats['files_failed']}")
        job_logger.log_info("=" * 50)

        if low_confidence_files:
            job_logger.log_info("\nLOW CONFIDENCE FILES (may need manual review):")
            for item in low_confidence_files[:50]:
                job_logger.log_info(f"  [{item['score']}/100] {item['file_path']}")
                job_logger.log_info(f"    File:  {item['file_artist']} - {item['file_title']}")
                job_logger.log_info(f"    MB:    {item['mb_artist']} - {item['mb_title']}")
            if len(low_confidence_files) > 50:
                job_logger.log_info(f"  ... and {len(low_confidence_files) - 50} more")

        # Complete job
        job_logger.log_job_complete({
            'files_total': total_files,
            'files_validated': stats['files_validated'],
            'files_metadata_correct': stats['files_metadata_correct'],
            'files_low_confidence': stats['files_low_confidence'],
            'files_failed': stats['files_failed']
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = f"Complete: {stats['files_validated']} validated, {stats['files_low_confidence']} low confidence"
        job.last_heartbeat_at = datetime.now(timezone.utc)
        job.current_file_path = None
        job.files_renamed = stats['files_metadata_correct']
        job.files_failed = stats['files_failed']
        db.commit()

        logger.info(f"Completed MBID metadata validation job {job_id}")
        return {
            'status': 'completed',
            'files_validated': stats['files_validated'],
            'files_metadata_correct': stats['files_metadata_correct'],
            'files_low_confidence': stats['files_low_confidence']
        }

    except Exception as e:
        logger.error(f"Error in MBID metadata validation job {job_id}: {e}\n{traceback.format_exc()}")
        if job_logger:
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            job.last_heartbeat_at = datetime.now(timezone.utc)
            db.commit()
        return {'error': str(e)}

    finally:
        db.close()


# ========================================
# Associate and Organize Tasks
# ========================================

MAX_FATAL_ERRORS = 5  # Max fatal errors before failing job


@shared_task(bind=True, soft_time_limit=43200, time_limit=43500)  # 12 hour limit for large libraries
def associate_and_organize_library_task(self, job_id: str, library_path_id: str, options: dict):
    """
    Associate and organize all artist files in a library path.

    Walks each artist directory, reads file metadata, matches to DB tracks,
    moves/renames to naming convention, and updates Track.file_path + has_file.

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: LibraryPath UUID string
        options: Organization options dict (dry_run, create_metadata_files)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting associate & organize library job {job_id} for library path {library_path_id}")

        # Acquire job with row-level locking
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)
        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Get library path
        library_path = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(library_path_id)
        ).first()

        if not library_path:
            job_logger.log_job_error(f"Library path {library_path_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Library path {library_path_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        library_root = library_path.path
        job_logger.log_job_start("associate_and_organize", f"Library: {library_root}")

        # Get all monitored artists
        from app.models.artist import Artist
        artists = db.query(Artist).filter(
            Artist.is_monitored == True  # noqa: E712
        ).order_by(Artist.name).all()

        if not artists:
            job_logger.log_info("No monitored artists found")
            job.status = JobStatus.COMPLETED
            job.progress_percent = 100.0
            job.completed_at = datetime.now(timezone.utc)
            job.current_action = "No artists to process"
            db.commit()
            return

        job.files_total = len(artists)  # Use as artist count initially
        db.commit()

        job_logger.log_info(f"Processing {len(artists)} monitored artists against {library_root}")

        # Initialize the service
        from app.services.associate_and_organize import AssociateAndOrganizeService
        dry_run = options.get('dry_run', False)
        service = AssociateAndOrganizeService(
            db=db,
            audit_logger=AuditLogger(db=db),
            dry_run=dry_run
        )

        error_tracker = ErrorTracker()
        total_files_found = 0
        total_files_matched = 0
        total_files_moved = 0
        total_files_renamed = 0
        total_tracks_linked = 0
        artists_processed = 0

        for idx, artist in enumerate(artists):
            # Update heartbeat and progress
            progress = (idx / len(artists)) * 100
            update_job_progress(
                db, job,
                progress_percent=progress,
                current_action=f"Processing artist {idx+1}/{len(artists)}: {artist.name}"
            )

            try:
                def progress_cb(file_idx, total, file_path):
                    update_job_progress(
                        db, job,
                        current_action=f"{artist.name}: file {file_idx+1}/{total}"
                    )

                result = service.process_artist(
                    artist_id=str(artist.id),
                    library_root=library_root,
                    job_logger=job_logger,
                    progress_callback=progress_cb
                )

                total_files_found += result.files_found
                total_files_matched += result.files_matched
                total_files_moved += result.files_moved
                total_files_renamed += result.files_renamed
                total_tracks_linked += result.tracks_linked

                if result.files_found > 0:
                    artists_processed += 1

                # Count failures
                for mr in result.match_results:
                    if mr.error:
                        is_fatal = error_tracker.add_error(mr.file_path, mr.error)
                        if is_fatal and error_tracker.get_fatal_error_count() > MAX_FATAL_ERRORS:
                            raise Exception(
                                f"Too many fatal errors ({error_tracker.get_fatal_error_count()}), aborting"
                            )

            except Exception as e:
                logger.error(f"Error processing artist {artist.name}: {e}")
                job_logger.log_info(f"ERROR processing {artist.name}: {e}")
                error_tracker.add_error(f"artist:{artist.name}", str(e))
                if error_tracker.get_fatal_error_count() > MAX_FATAL_ERRORS:
                    raise

        # Update final counts
        job.files_total = total_files_found
        job.files_processed = total_files_matched
        job.files_moved = total_files_moved
        job.files_renamed = total_files_renamed

        # Generate error report
        if error_tracker.get_total_errors() > 0:
            error_tracker.generate_report(job_logger)

        # Complete job
        job_logger.log_job_complete({
            'artists_processed': artists_processed,
            'files_found': total_files_found,
            'files_matched': total_files_matched,
            'files_moved': total_files_moved,
            'files_renamed': total_files_renamed,
            'tracks_linked': total_tracks_linked,
            'fatal_errors': error_tracker.get_fatal_error_count(),
            'non_fatal_errors': error_tracker.get_total_errors() - error_tracker.get_fatal_error_count()
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = (
            f"Complete: {total_files_matched} files matched, "
            f"{total_tracks_linked} tracks linked"
        )
        db.commit()

        logger.info(f"Completed associate & organize library job {job_id}")

    except Exception as e:
        logger.error(f"Error in associate & organize library job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)  # 1 hour limit
def associate_and_organize_artist_task(self, job_id: str, artist_id: str, options: dict):
    """
    Associate and organize files for a single artist.

    Args:
        job_id: FileOrganizationJob ID
        artist_id: Artist UUID string
        options: Organization options dict (dry_run, create_metadata_files)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting associate & organize artist job {job_id} for artist {artist_id}")

        # Acquire job with row-level locking
        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)
        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        # Initialize job logger
        job_logger = JobLogger(job_id=job_id)
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        # Get artist info
        from app.models.artist import Artist
        artist = db.query(Artist).filter(Artist.id == UUID(artist_id)).first()

        if not artist:
            job_logger.log_job_error(f"Artist {artist_id} not found")
            job.status = JobStatus.FAILED
            job.error_message = f"Artist {artist_id} not found"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        job_logger.log_job_start("associate_and_organize", f"Artist: {artist.name}")

        # Get library root from artist's root_folder_path or library_path_id
        library_root = None

        if artist.root_folder_path:
            # Use parent of artist's root folder as library root
            library_root = str(Path(artist.root_folder_path).parent)

        if not library_root and job.library_path_id:
            lp = db.query(LibraryPath).filter(
                LibraryPath.id == job.library_path_id
            ).first()
            if lp:
                library_root = lp.path

        if not library_root:
            # Try to find from any library path that is a root folder
            lp = db.query(LibraryPath).filter(
                LibraryPath.is_root_folder == True  # noqa: E712
            ).first()
            if lp:
                library_root = lp.path

        if not library_root:
            job_logger.log_job_error("No library root found for artist")
            job.status = JobStatus.FAILED
            job.error_message = "No library root found for artist"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Initialize the service
        from app.services.associate_and_organize import AssociateAndOrganizeService
        dry_run = options.get('dry_run', False)
        service = AssociateAndOrganizeService(
            db=db,
            audit_logger=AuditLogger(db=db),
            dry_run=dry_run
        )

        error_tracker = ErrorTracker()

        def progress_cb(file_idx, total, file_path):
            progress = (file_idx / total) * 100 if total > 0 else 0
            update_job_progress(
                db, job,
                progress_percent=progress,
                current_action=f"Processing file {file_idx+1}/{total}: {Path(file_path).name}"
            )

        result = service.process_artist(
            artist_id=str(artist.id),
            library_root=library_root,
            job_logger=job_logger,
            progress_callback=progress_cb
        )

        # Track errors
        for mr in result.match_results:
            if mr.error:
                error_tracker.add_error(mr.file_path, mr.error)

        # Update job stats
        job.files_total = result.files_found
        job.files_processed = result.files_matched
        job.files_moved = result.files_moved
        job.files_renamed = result.files_renamed
        job.files_failed = result.files_failed

        # Generate error report
        if error_tracker.get_total_errors() > 0:
            error_tracker.generate_report(job_logger)

        # Complete job
        job_logger.log_job_complete({
            'files_found': result.files_found,
            'files_matched': result.files_matched,
            'files_moved': result.files_moved,
            'files_renamed': result.files_renamed,
            'files_already_organized': result.files_already_organized,
            'files_skipped': result.files_skipped,
            'files_failed': result.files_failed,
            'tracks_linked': result.tracks_linked,
            'albums_with_metadata': result.albums_with_metadata
        })

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = (
            f"Complete: {result.files_matched} matched, "
            f"{result.tracks_linked} linked for {artist.name}"
        )
        db.commit()

        logger.info(f"Completed associate & organize artist job {job_id}")

    except Exception as e:
        logger.error(f"Error in associate & organize artist job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


# ========================================
# Validate File Links Task
# ========================================

@shared_task(
    bind=True,
    soft_time_limit=3600,
    time_limit=3660,
    name="app.tasks.organization_tasks.validate_file_links_task"
)
def validate_file_links_task(self, job_id: str, library_path_id: str = None):
    """
    Validate that all linked track files still exist on disk.

    Mount-point safety: Before checking individual files, validates that each
    library path root is accessible. If a mount is down, files under it are
    skipped rather than having their links cleared.

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Optional - limit to specific library path
    """
    import os

    db = SessionLocal()

    try:
        logger.info(f"Starting validate file links job {job_id}")

        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)
        if not job:
            logger.warning(f"Could not acquire job {job_id} - already running or not found")
            return

        job_logger = JobLogger(job_id=job_id, job_type='validate_file_links')
        job.log_file_path = job_logger.get_log_file_path()
        db.commit()

        job_logger.log_job_start("validate_file_links", "Validating linked track files exist on disk")

        # Step 1: Pre-flight — validate mount points
        from app.models.library import LibraryPath as LP
        if library_path_id:
            lib_paths = db.query(LP).filter(LP.id == UUID(library_path_id)).all()
        else:
            lib_paths = db.query(LP).filter(LP.is_enabled == True).all()

        inaccessible_roots = []
        accessible_roots = []

        for lp in lib_paths:
            if os.path.exists(lp.path) and os.path.isdir(lp.path):
                accessible_roots.append(lp.path)
                job_logger.log_info(f"Library path accessible: {lp.path}")
            else:
                inaccessible_roots.append(lp.path)
                job_logger.log_warning(f"Library path INACCESSIBLE (mount offline?): {lp.path}")

        if not accessible_roots and inaccessible_roots:
            error_msg = (
                f"No library paths are accessible ({len(inaccessible_roots)} offline) — "
                "possible mount issue. Aborting to prevent mass link removal."
            )
            job_logger.log_job_error(error_msg)
            job.status = JobStatus.FAILED
            job.error_message = error_msg
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Step 2: Query tracks with files linked
        from app.models.track import Track
        query = db.query(Track).filter(
            Track.has_file == True,
            Track.file_path.isnot(None)
        )

        if library_path_id:
            lp = db.query(LP).filter(LP.id == UUID(library_path_id)).first()
            if lp:
                query = query.filter(Track.file_path.like(f"{lp.path}%"))

        tracks = query.all()
        total_tracks = len(tracks)

        job.files_total = total_tracks
        job.current_action = f"Checking {total_tracks} linked tracks"
        db.commit()

        job_logger.log_phase_start("File Link Validation", f"Checking {total_tracks} tracks")

        valid_count = 0
        cleared_count = 0
        skipped_mount_count = 0

        for i, track in enumerate(tracks):
            file_path = track.file_path

            # Check if file is under an inaccessible root
            under_inaccessible = False
            for root in inaccessible_roots:
                if file_path.startswith(root):
                    under_inaccessible = True
                    skipped_mount_count += 1
                    break

            if under_inaccessible:
                continue

            if os.path.exists(file_path):
                valid_count += 1
            else:
                track.has_file = False
                track.file_path = None
                cleared_count += 1
                job_logger.log_warning(f"Stale link cleared: {file_path}")

            # Batch commit and progress
            if (i + 1) % BATCH_SIZE == 0:
                db.commit()
                progress = (i + 1) / total_tracks * 100
                job.progress_percent = progress
                job.files_processed = i + 1
                job.current_action = f"Checked {i + 1}/{total_tracks} tracks ({cleared_count} stale)"
                job.last_heartbeat_at = datetime.now(timezone.utc)
                db.commit()

        # Final commit
        db.commit()

        # Summary
        summary = (
            f"File link validation complete: "
            f"{total_tracks} checked, {valid_count} valid, "
            f"{cleared_count} stale links cleared, "
            f"{skipped_mount_count} skipped (mount offline)"
        )
        job_logger.log_info(summary)
        job_logger.log_job_complete()

        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.files_processed = total_tracks
        job.files_moved = cleared_count  # Reuse field for "cleared" count
        job.completed_at = datetime.now(timezone.utc)

        if inaccessible_roots:
            job.current_action = f"Completed with warnings: {len(inaccessible_roots)} mount(s) offline, {skipped_mount_count} tracks skipped"
        else:
            job.current_action = summary

        db.commit()
        logger.info(f"Completed validate file links job {job_id}: {summary}")

    except SoftTimeLimitExceeded:
        logger.error(f"Validate file links job {job_id} timed out")
        if 'job_logger' in locals():
            job_logger.log_job_error("Job timed out (soft time limit exceeded)")
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = "Job timed out"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        logger.error(f"Error in validate file links job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()


@shared_task(bind=True, soft_time_limit=43200, time_limit=43260)
def resolve_unlinked_files_task(self, job_id: str, library_path_id: str = None):
    """
    Bulk resolution of unlinked files.

    Standalone task that can be triggered on-demand to resolve the maximum number
    of unlinked files through multiple strategies:

    Phase 1: Auto-import missing albums (album_not_in_db files)
    Phase 2: Re-run MBID matching (fast path + ambiguous)
    Phase 3: Re-run RG fallback matching
    Phase 4: Fuzzy matching for no_mbid files (title + artist + duration)
    Phase 5: Re-categorize remaining unlinked files

    Args:
        job_id: FileOrganizationJob ID
        library_path_id: Library UUID (optional, resolves all libraries if omitted)
    """
    db = SessionLocal()

    try:
        logger.info(f"Starting resolve unlinked files job {job_id}")

        job = acquire_job_with_lock(db, job_id, celery_task_id=self.request.id)
        if not job:
            logger.warning(f"Could not acquire job {job_id}")
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.last_heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        job_logger = JobLogger(job_type="resolve_unlinked", job_id=job_id)
        job_logger.log_job_start("resolve_unlinked", "Resolve Unlinked Files")
        job.log_file_path = str(job_logger.log_file_path)
        db.commit()

        # Build path filter
        path_filter = ""
        bulk_params = {}
        if library_path_id:
            path_filter = "AND lf.library_path_id = :library_path_id"
            bulk_params['library_path_id'] = library_path_id

        # Count initial unlinked
        initial_unlinked_sql = text(f"""
            SELECT COUNT(*) FROM library_files lf
            LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
            WHERE lf.musicbrainz_trackid IS NOT NULL AND t.id IS NULL
            {path_filter}
        """)
        initial_unlinked = db.execute(initial_unlinked_sql, bulk_params).scalar() or 0
        initial_no_mbid_sql = text(f"""
            SELECT COUNT(*) FROM library_files lf
            WHERE lf.musicbrainz_trackid IS NULL
            {path_filter}
        """)
        initial_no_mbid = db.execute(initial_no_mbid_sql, bulk_params).scalar() or 0

        job.files_total = initial_unlinked + initial_no_mbid
        job_logger.log_info(f"Initial state: {initial_unlinked} unlinked with MBID, {initial_no_mbid} with no MBID")
        db.commit()

        total_linked = 0

        # ── Phase 1: Auto-Import Missing Albums ──
        job_logger.log_phase_start("Phase 1: Auto-Import", "Importing missing release groups")
        job.current_action = "Phase 1: Auto-importing missing albums..."
        job.progress_percent = 5.0
        db.commit()

        phase1_albums = 0
        try:
            from app.services.album_importer import bulk_import_release_groups
            from app.services.musicbrainz_client import get_musicbrainz_client

            missing_albums_sql = text(f"""
                SELECT DISTINCT lf.musicbrainz_releasegroupid AS rg_mbid, a.id AS artist_id
                FROM library_files lf
                JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
                LEFT JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid
                LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND t.id IS NULL
                  AND lf.musicbrainz_releasegroupid IS NOT NULL
                  AND lf.musicbrainz_releasegroupid != ''
                  AND a.id IS NOT NULL
                  AND al.id IS NULL
                  {path_filter}
            """)
            missing_rows = db.execute(missing_albums_sql, bulk_params).fetchall()

            if missing_rows:
                mb_client = get_musicbrainz_client()
                artist_rg_pairs = [(row.artist_id, row.rg_mbid) for row in missing_rows]

                def _progress_p1(imported, total, title):
                    pct = 5.0 + (imported / total) * 20.0
                    job.current_action = f"Phase 1: Importing {imported}/{total} ({title})"
                    job.progress_percent = pct
                    try:
                        db.commit()
                    except Exception:
                        pass

                import_stats = bulk_import_release_groups(
                    db, artist_rg_pairs, mb_client, progress_callback=_progress_p1
                )
                phase1_albums = import_stats['albums_imported']

                job_logger.log_info(f"Phase 1 results: {import_stats['albums_imported']} albums imported, "
                                    f"{import_stats['tracks_created']} tracks created, "
                                    f"{import_stats['skipped']} skipped, {import_stats['failed']} failed")
            else:
                job_logger.log_info("Phase 1: No missing albums to import")

            job_logger.log_phase_complete("Phase 1: Auto-Import", count=phase1_albums)
        except Exception as e:
            logger.error(f"Phase 1 failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Phase 1 failed (non-fatal): {e}")
            db.rollback()

        # ── Phase 2: MBID Matching (fast path + ambiguous) ──
        job_logger.log_phase_start("Phase 2: MBID Matching", "Direct MBID matching")
        job.current_action = "Phase 2: MBID matching..."
        job.progress_percent = 30.0
        db.commit()

        phase2_linked = 0
        try:
            # Fast path: unambiguous MBID match
            fast_sql = text(f"""
                UPDATE tracks
                SET file_path = lf.file_path, has_file = true
                FROM library_files lf
                WHERE tracks.musicbrainz_id = lf.musicbrainz_trackid
                  AND lf.musicbrainz_trackid IS NOT NULL
                  AND (tracks.file_path IS DISTINCT FROM lf.file_path)
                  AND lf.musicbrainz_trackid IN (
                      SELECT t2.musicbrainz_id FROM tracks t2
                      WHERE t2.musicbrainz_id IS NOT NULL
                      GROUP BY t2.musicbrainz_id
                      HAVING COUNT(*) = 1
                  )
                  {path_filter}
            """)
            fast_result = db.execute(fast_sql, bulk_params)
            fast_count = fast_result.rowcount
            db.commit()
            phase2_linked += fast_count
            job_logger.log_info(f"Fast path: {fast_count} tracks linked")

            # Ambiguous MBID resolution
            ambiguous_sql = text(f"""
                SELECT
                    lf.id AS file_id, lf.file_path,
                    lf.musicbrainz_trackid AS recording_mbid,
                    lf.musicbrainz_releasegroupid AS file_rg_mbid,
                    t.id AS track_id, t.album_id,
                    a.musicbrainz_id AS album_rg_mbid,
                    a.secondary_types AS album_secondary_types
                FROM library_files lf
                JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                JOIN albums a ON a.id = t.album_id
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND (t.file_path IS DISTINCT FROM lf.file_path)
                  AND lf.musicbrainz_trackid IN (
                      SELECT t2.musicbrainz_id FROM tracks t2
                      WHERE t2.musicbrainz_id IS NOT NULL
                      GROUP BY t2.musicbrainz_id
                      HAVING COUNT(*) > 1
                  )
                  {path_filter}
                ORDER BY lf.id, t.id
            """)
            ambiguous_rows = db.execute(ambiguous_sql, bulk_params).fetchall()

            if ambiguous_rows:
                from collections import defaultdict

                def _is_compilation(secondary_types):
                    if not secondary_types:
                        return False
                    return 'compilation' in secondary_types.lower()

                file_candidates = defaultdict(list)
                for row in ambiguous_rows:
                    file_candidates[str(row.file_id)].append({
                        'file_id': str(row.file_id),
                        'file_path': row.file_path,
                        'file_rg_mbid': row.file_rg_mbid,
                        'track_id': str(row.track_id),
                        'album_id': str(row.album_id),
                        'album_rg_mbid': row.album_rg_mbid,
                        'album_secondary_types': row.album_secondary_types,
                    })

                album_match_counts = defaultdict(int)

                def _score_candidate(c, use_cohort=True):
                    score = 0
                    if c['file_rg_mbid'] and c['album_rg_mbid']:
                        if c['file_rg_mbid'] == c['album_rg_mbid']:
                            score += 1000
                    if not _is_compilation(c['album_secondary_types']):
                        score += 50
                    if use_cohort:
                        score += album_match_counts.get(c['album_id'], 0)
                    return score

                resolved = {}
                for file_id, candidates in file_candidates.items():
                    best = max(candidates, key=lambda c: _score_candidate(c, use_cohort=False))
                    if _score_candidate(best, use_cohort=False) >= 1000:
                        resolved[file_id] = best
                        album_match_counts[best['album_id']] += 1

                for file_id, candidates in file_candidates.items():
                    if file_id in resolved:
                        continue
                    best = max(candidates, key=lambda c: _score_candidate(c, use_cohort=True))
                    resolved[file_id] = best
                    album_match_counts[best['album_id']] += 1

                ambiguous_count = 0
                for file_id, match in resolved.items():
                    db.execute(
                        text("UPDATE tracks SET file_path = :file_path, has_file = true WHERE id = CAST(:track_id AS uuid) AND (file_path IS DISTINCT FROM :file_path)"),
                        {'file_path': match['file_path'], 'track_id': match['track_id']}
                    )
                    ambiguous_count += 1
                db.commit()
                phase2_linked += ambiguous_count
                job_logger.log_info(f"Ambiguous resolution: {ambiguous_count} tracks linked")

            total_linked += phase2_linked
            job_logger.log_phase_complete("Phase 2: MBID Matching", count=phase2_linked)

        except Exception as e:
            logger.error(f"Phase 2 failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Phase 2 failed (non-fatal): {e}")
            db.rollback()

        # ── Phase 3: Release Group Fallback ──
        job_logger.log_phase_start("Phase 3: RG Fallback", "Fuzzy match via release group lookup")
        job.current_action = "Phase 3: Release group fallback..."
        job.progress_percent = 50.0
        db.commit()

        phase3_linked = 0
        try:
            from app.services.musicbrainz_local import get_musicbrainz_local_db
            import re as _re
            from difflib import SequenceMatcher

            local_db_inst = get_musicbrainz_local_db()
            if local_db_inst:
                def _normalize_title(s):
                    if not s:
                        return ""
                    s = s.lower()
                    s = _re.sub(r'[^\w\s]', '', s)
                    s = _re.sub(r'\s+', ' ', s).strip()
                    return s

                BATCH_SZ = 1000
                MB_BATCH_SZ = 500
                rg_offset = 0

                while True:
                    unlinked_sql = text(f"""
                        SELECT lf.id, lf.file_path, lf.title, lf.musicbrainz_trackid, lf.duration_seconds
                        FROM library_files lf
                        LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                        WHERE lf.musicbrainz_trackid IS NOT NULL
                          AND t.id IS NULL
                          {path_filter}
                        ORDER BY lf.id
                        LIMIT :batch_limit OFFSET :batch_offset
                    """)
                    batch_params = {**bulk_params, 'batch_limit': BATCH_SZ, 'batch_offset': rg_offset}
                    unlinked_rows = db.execute(unlinked_sql, batch_params).fetchall()

                    if not unlinked_rows:
                        break

                    recording_mbids = list(set(r.musicbrainz_trackid for r in unlinked_rows if r.musicbrainz_trackid))
                    if not recording_mbids:
                        rg_offset += BATCH_SZ
                        continue

                    recording_to_rg = {}
                    for i in range(0, len(recording_mbids), MB_BATCH_SZ):
                        mb_batch = recording_mbids[i:i + MB_BATCH_SZ]
                        try:
                            with local_db_inst.engine.connect() as mb_conn:
                                rg_sql = text("""
                                    SELECT DISTINCT
                                        r.gid::text AS recording_gid,
                                        r.name AS recording_name,
                                        rg.gid::text AS release_group_gid
                                    FROM musicbrainz.recording r
                                    JOIN musicbrainz.track t ON t.recording = r.id
                                    JOIN musicbrainz.medium m ON m.id = t.medium
                                    JOIN musicbrainz.release rel ON rel.id = m.release
                                    JOIN musicbrainz.release_group rg ON rg.id = rel.release_group
                                    WHERE r.gid = ANY(CAST(:recording_mbids AS uuid[]))
                                """)
                                rg_rows = mb_conn.execute(rg_sql, {'recording_mbids': mb_batch}).fetchall()
                                for rg_row in rg_rows:
                                    rec_gid = rg_row.recording_gid
                                    if rec_gid not in recording_to_rg:
                                        recording_to_rg[rec_gid] = []
                                    recording_to_rg[rec_gid].append({
                                        'release_group_gid': rg_row.release_group_gid,
                                        'recording_name': rg_row.recording_name,
                                    })
                        except Exception as mb_err:
                            logger.warning(f"RG fallback MB query failed: {mb_err}")
                            continue

                    if not recording_to_rg:
                        rg_offset += BATCH_SZ
                        continue

                    all_rg_gids = list(set(
                        info['release_group_gid']
                        for infos in recording_to_rg.values()
                        for info in infos
                    ))

                    rg_to_album = {}
                    for i in range(0, len(all_rg_gids), MB_BATCH_SZ):
                        rg_batch = all_rg_gids[i:i + MB_BATCH_SZ]
                        album_sql = text("SELECT id, musicbrainz_id FROM albums WHERE musicbrainz_id = ANY(:rg_gids)")
                        album_rows = db.execute(album_sql, {'rg_gids': rg_batch}).fetchall()
                        for arow in album_rows:
                            rg_to_album[arow.musicbrainz_id] = str(arow.id)

                    if not rg_to_album:
                        rg_offset += BATCH_SZ
                        continue

                    matched_album_ids = list(set(rg_to_album.values()))
                    album_tracks_map = {}
                    for i in range(0, len(matched_album_ids), MB_BATCH_SZ):
                        aid_batch = matched_album_ids[i:i + MB_BATCH_SZ]
                        tracks_sql = text("""
                            SELECT id, album_id, title, duration_ms, musicbrainz_id, file_path, has_file
                            FROM tracks WHERE album_id = ANY(CAST(:album_ids AS uuid[]))
                            ORDER BY album_id, disc_number, track_number
                        """)
                        track_rows = db.execute(tracks_sql, {'album_ids': aid_batch}).fetchall()
                        for trow in track_rows:
                            aid = str(trow.album_id)
                            if aid not in album_tracks_map:
                                album_tracks_map[aid] = []
                            album_tracks_map[aid].append({
                                'id': str(trow.id), 'title': trow.title,
                                'duration_ms': trow.duration_ms, 'musicbrainz_id': trow.musicbrainz_id,
                                'file_path': trow.file_path, 'has_file': trow.has_file,
                            })

                    updates = []
                    for row in unlinked_rows:
                        rg_infos = recording_to_rg.get(row.musicbrainz_trackid)
                        if not rg_infos:
                            continue

                        candidate_album_ids = []
                        mb_recording_name = None
                        for info in rg_infos:
                            album_id = rg_to_album.get(info['release_group_gid'])
                            if album_id:
                                candidate_album_ids.append(album_id)
                                if not mb_recording_name:
                                    mb_recording_name = info['recording_name']

                        if not candidate_album_ids:
                            continue

                        file_title = row.title or mb_recording_name
                        if not file_title:
                            continue
                        file_title_norm = _normalize_title(file_title)
                        file_duration_ms = (row.duration_seconds * 1000) if row.duration_seconds else None

                        best_track_id = None
                        best_score = 0.0
                        for album_id in candidate_album_ids:
                            for trk in album_tracks_map.get(album_id, []):
                                if trk['has_file'] and trk['file_path']:
                                    continue
                                ratio = SequenceMatcher(None, file_title_norm, _normalize_title(trk['title'])).ratio()
                                if ratio >= 0.6:
                                    if file_duration_ms and trk['duration_ms']:
                                        if abs(file_duration_ms - trk['duration_ms']) <= 5000:
                                            ratio += 0.05
                                    if ratio > best_score:
                                        best_score = ratio
                                        best_track_id = trk['id']

                        if best_track_id:
                            updates.append((best_track_id, row.file_path))
                            for album_id in candidate_album_ids:
                                for trk in album_tracks_map.get(album_id, []):
                                    if trk['id'] == best_track_id:
                                        trk['has_file'] = True
                                        trk['file_path'] = row.file_path
                                        break

                    if updates:
                        for track_id, file_path in updates:
                            db.execute(
                                text("UPDATE tracks SET file_path = :file_path, has_file = true WHERE id = CAST(:track_id AS uuid) AND (file_path IS DISTINCT FROM :file_path)"),
                                {'file_path': file_path, 'track_id': track_id}
                            )
                        db.commit()
                        phase3_linked += len(updates)

                    rg_offset += BATCH_SZ
                    job.current_action = f"Phase 3: RG fallback - {phase3_linked} linked so far..."
                    db.commit()

            else:
                job_logger.log_info("Skipping RG fallback (local MusicBrainz DB not available)")

            total_linked += phase3_linked
            job_logger.log_info(f"Phase 3: {phase3_linked} files linked via release group fallback")
            job_logger.log_phase_complete("Phase 3: RG Fallback", count=phase3_linked)

        except Exception as e:
            logger.error(f"Phase 3 failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Phase 3 failed (non-fatal): {e}")
            db.rollback()

        # ── Phase 4: Fuzzy Matching for no_mbid Files ──
        job_logger.log_phase_start("Phase 4: Fuzzy Match", "Matching files without MBIDs by title + artist + duration")
        job.current_action = "Phase 4: Fuzzy matching for no-MBID files..."
        job.progress_percent = 70.0
        db.commit()

        phase4_linked = 0
        try:
            import re as _re
            from difflib import SequenceMatcher

            def _normalize_title_p4(s):
                if not s:
                    return ""
                s = s.lower()
                s = _re.sub(r'[^\w\s]', '', s)
                s = _re.sub(r'\s+', ' ', s).strip()
                return s

            FUZZY_BATCH = 500
            fuzzy_offset = 0

            while True:
                no_mbid_sql = text(f"""
                    SELECT lf.id, lf.file_path, lf.title, lf.artist, lf.album_artist,
                           lf.duration_seconds, lf.album
                    FROM library_files lf
                    WHERE lf.musicbrainz_trackid IS NULL
                      AND lf.title IS NOT NULL AND lf.title != ''
                      AND (lf.artist IS NOT NULL AND lf.artist != ''
                           OR lf.album_artist IS NOT NULL AND lf.album_artist != '')
                      {path_filter}
                    ORDER BY lf.id
                    LIMIT :batch_limit OFFSET :batch_offset
                """)
                no_mbid_params = {**bulk_params, 'batch_limit': FUZZY_BATCH, 'batch_offset': fuzzy_offset}
                no_mbid_rows = db.execute(no_mbid_sql, no_mbid_params).fetchall()

                if not no_mbid_rows:
                    break

                from collections import defaultdict
                artist_files = defaultdict(list)
                for row in no_mbid_rows:
                    artist_name = (row.artist or row.album_artist or "").strip().lower()
                    if artist_name:
                        artist_files[artist_name].append(row)

                unique_artists = list(artist_files.keys())
                if unique_artists:
                    from app.models.artist import Artist

                    for artist_name_lower in unique_artists:
                        artist = db.query(Artist).filter(
                            Artist.name.ilike(artist_name_lower)
                        ).first()

                        if not artist:
                            continue

                        artist_tracks_sql = text("""
                            SELECT t.id, t.title, t.duration_ms, t.file_path, t.has_file, a.title AS album_title
                            FROM tracks t
                            JOIN albums a ON a.id = t.album_id
                            WHERE a.artist_id = CAST(:artist_id AS uuid)
                              AND (t.has_file = false OR t.file_path IS NULL)
                            ORDER BY a.title, t.disc_number, t.track_number
                        """)
                        artist_track_rows = db.execute(
                            artist_tracks_sql, {'artist_id': str(artist.id)}
                        ).fetchall()

                        if not artist_track_rows:
                            continue

                        available_tracks = []
                        for trow in artist_track_rows:
                            available_tracks.append({
                                'id': str(trow.id),
                                'title': trow.title,
                                'title_norm': _normalize_title_p4(trow.title),
                                'duration_ms': trow.duration_ms,
                                'album_title': trow.album_title,
                                'taken': False,
                            })

                        files = artist_files[artist_name_lower]
                        for file_row in files:
                            file_title_norm = _normalize_title_p4(file_row.title)
                            file_duration_ms = (file_row.duration_seconds * 1000) if file_row.duration_seconds else None

                            best_track = None
                            best_score = 0.0

                            for trk in available_tracks:
                                if trk['taken']:
                                    continue

                                ratio = SequenceMatcher(None, file_title_norm, trk['title_norm']).ratio()

                                if ratio >= 0.7:
                                    if file_duration_ms and trk['duration_ms']:
                                        duration_diff = abs(file_duration_ms - trk['duration_ms'])
                                        if duration_diff <= 5000:
                                            ratio += 0.1
                                        elif duration_diff <= 10000:
                                            ratio += 0.03

                                    if file_row.album and trk['album_title']:
                                        album_ratio = SequenceMatcher(
                                            None,
                                            _normalize_title_p4(file_row.album),
                                            _normalize_title_p4(trk['album_title'])
                                        ).ratio()
                                        if album_ratio >= 0.7:
                                            ratio += 0.05

                                    if ratio > best_score:
                                        best_score = ratio
                                        best_track = trk

                            if best_track:
                                db.execute(
                                    text("UPDATE tracks SET file_path = :file_path, has_file = true WHERE id = CAST(:track_id AS uuid)"),
                                    {'file_path': file_row.file_path, 'track_id': best_track['id']}
                                )
                                best_track['taken'] = True
                                phase4_linked += 1

                    db.commit()

                fuzzy_offset += FUZZY_BATCH
                job.current_action = f"Phase 4: Fuzzy match - {phase4_linked} linked so far..."
                db.commit()

            total_linked += phase4_linked
            job_logger.log_info(f"Phase 4: {phase4_linked} files linked via fuzzy matching (no-MBID)")
            job_logger.log_phase_complete("Phase 4: Fuzzy Match", count=phase4_linked)

        except Exception as e:
            logger.error(f"Phase 4 failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Phase 4 failed (non-fatal): {e}")
            db.rollback()

        # ── Phase 5: Re-Categorize Unlinked Files ──
        job_logger.log_phase_start("Phase 5: Categorize", "Updating unlinked files table")
        job.current_action = "Phase 5: Re-categorizing remaining unlinked files..."
        job.progress_percent = 90.0
        db.commit()

        try:
            # Mark newly resolved files (MBID-matched)
            resolve_sql = text(f"""
                UPDATE unlinked_files uf
                SET resolved_at = now()
                FROM library_files lf
                JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid AND t.file_path = lf.file_path
                WHERE uf.library_file_id = lf.id
                  AND uf.resolved_at IS NULL
                  {path_filter.replace('lf.library_path_id', 'lf.library_path_id') if path_filter else ''}
            """)
            resolve_result = db.execute(resolve_sql, bulk_params)
            resolved_count = resolve_result.rowcount
            db.commit()

            # Also resolve files matched by fuzzy (linked by file_path)
            resolve_no_mbid_sql = text(f"""
                UPDATE unlinked_files uf
                SET resolved_at = now()
                FROM library_files lf
                JOIN tracks t ON t.file_path = lf.file_path AND t.has_file = true
                WHERE uf.library_file_id = lf.id
                  AND uf.resolved_at IS NULL
                  AND lf.musicbrainz_trackid IS NULL
                  {path_filter.replace('lf.library_path_id', 'lf.library_path_id') if path_filter else ''}
            """)
            resolve_no_mbid_result = db.execute(resolve_no_mbid_sql, bulk_params)
            resolved_count += resolve_no_mbid_result.rowcount
            db.commit()

            # Upsert remaining unlinked with MBID
            upsert_mbid_sql = text(f"""
                INSERT INTO unlinked_files (library_file_id, file_path, artist, album, title, musicbrainz_trackid, reason, reason_detail, job_id, detected_at)
                SELECT
                    lf.id, lf.file_path, lf.artist, lf.album, lf.title, lf.musicbrainz_trackid,
                    CASE
                        WHEN lf.musicbrainz_artistid IS NOT NULL AND a.id IS NULL THEN 'artist_not_in_db'
                        WHEN a.id IS NOT NULL AND al.id IS NULL THEN 'album_not_in_db'
                        ELSE 'no_matching_track'
                    END,
                    CASE
                        WHEN lf.musicbrainz_artistid IS NOT NULL AND a.id IS NULL
                            THEN 'Artist MBID ' || lf.musicbrainz_artistid || ' not imported'
                        WHEN a.id IS NOT NULL AND al.id IS NULL
                            THEN 'Artist exists but album not imported (release group: ' || COALESCE(lf.musicbrainz_releasegroupid, 'unknown') || ')'
                        ELSE 'Track MBID exists in file but no matching track record in database'
                    END,
                    CAST(:job_id AS uuid),
                    now()
                FROM library_files lf
                LEFT JOIN tracks t ON t.musicbrainz_id = lf.musicbrainz_trackid
                LEFT JOIN artists a ON a.musicbrainz_id = lf.musicbrainz_artistid
                LEFT JOIN albums al ON al.musicbrainz_id = lf.musicbrainz_releasegroupid AND al.artist_id = a.id
                WHERE lf.musicbrainz_trackid IS NOT NULL
                  AND t.id IS NULL
                  {path_filter}
                ON CONFLICT (library_file_id) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    reason_detail = EXCLUDED.reason_detail,
                    job_id = EXCLUDED.job_id,
                    detected_at = now(),
                    resolved_at = NULL
            """)
            db.execute(upsert_mbid_sql, {**bulk_params, 'job_id': job_id})
            db.commit()

            # Upsert remaining no-MBID files
            upsert_no_mbid_sql = text(f"""
                INSERT INTO unlinked_files (library_file_id, file_path, artist, album, title, musicbrainz_trackid, reason, reason_detail, job_id, detected_at)
                SELECT
                    lf.id, lf.file_path, lf.artist, lf.album, lf.title, NULL,
                    'no_mbid',
                    'File has no MusicBrainz Recording ID in metadata',
                    CAST(:job_id AS uuid),
                    now()
                FROM library_files lf
                LEFT JOIN tracks t ON t.file_path = lf.file_path AND t.has_file = true
                WHERE lf.musicbrainz_trackid IS NULL
                  AND t.id IS NULL
                  {path_filter}
                ON CONFLICT (library_file_id) DO UPDATE SET
                    reason = EXCLUDED.reason,
                    reason_detail = EXCLUDED.reason_detail,
                    job_id = EXCLUDED.job_id,
                    detected_at = now(),
                    resolved_at = NULL
            """)
            db.execute(upsert_no_mbid_sql, {**bulk_params, 'job_id': job_id})
            db.commit()

            # Summary
            reason_counts = db.execute(text("""
                SELECT reason, COUNT(*) as cnt FROM unlinked_files
                WHERE resolved_at IS NULL GROUP BY reason ORDER BY cnt DESC
            """)).fetchall()

            job_logger.log_info("FINAL UNLINKED FILES BREAKDOWN:")
            total_remaining = 0
            for reason, cnt in reason_counts:
                job_logger.log_info(f"  {reason}: {cnt}")
                total_remaining += cnt
            job_logger.log_info(f"  Total remaining unlinked: {total_remaining}")
            job_logger.log_info(f"  Newly resolved: {resolved_count}")
            job_logger.log_phase_complete("Phase 5: Categorize", count=resolved_count)

        except Exception as e:
            logger.error(f"Phase 5 failed: {e}\n{traceback.format_exc()}")
            job_logger.log_error(f"Phase 5 failed (non-fatal): {e}")
            db.rollback()

        # ── Complete ──
        job.status = JobStatus.COMPLETED
        job.progress_percent = 100.0
        job.files_processed = total_linked
        job.completed_at = datetime.now(timezone.utc)
        job.current_action = (
            f"Complete: {total_linked} files linked "
            f"(Phase 2: {phase2_linked}, Phase 3: {phase3_linked}, Phase 4: {phase4_linked})"
        )
        job.last_heartbeat_at = datetime.now(timezone.utc)
        db.commit()

        job_logger.log_info("=" * 50)
        job_logger.log_info("RESOLVE UNLINKED FILES COMPLETE")
        job_logger.log_info("=" * 50)
        job_logger.log_info(f"Total files linked: {total_linked}")
        job_logger.log_info(f"  Phase 1 albums imported: {phase1_albums}")
        job_logger.log_info(f"  Phase 2 (MBID matching): {phase2_linked}")
        job_logger.log_info(f"  Phase 3 (RG fallback): {phase3_linked}")
        job_logger.log_info(f"  Phase 4 (Fuzzy no-MBID): {phase4_linked}")
        job_logger.log_info("=" * 50)
        job_logger.log_job_complete()

        logger.info(f"Completed resolve unlinked files job {job_id}: {total_linked} files linked")

    except SoftTimeLimitExceeded:
        logger.error(f"Resolve unlinked files job {job_id} timed out")
        if 'job_logger' in locals():
            job_logger.log_job_error("Job timed out (soft time limit exceeded)")
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = "Job timed out"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    except Exception as e:
        logger.error(f"Error in resolve unlinked files job {job_id}: {e}\n{traceback.format_exc()}")
        if 'job_logger' in locals():
            job_logger.log_job_error(str(e))
        if 'job' in locals() and job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

    finally:
        db.close()
