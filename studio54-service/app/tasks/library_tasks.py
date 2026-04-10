"""
Library Scanner Celery Tasks
Async background tasks for library scanning
"""
import logging
from celery import Task
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.tasks.base_task import JobTrackedTask
from app.database import get_db
from app.models.library import LibraryPath, ScanJob
from app.models.job_state import JobType
from app.services.library_scanner import LibraryScanner
from app.config import settings

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task with database session management (legacy, use JobTrackedTask instead)"""
    _db = None

    @property
    def db(self) -> Session:
        if self._db is None:
            self._db = next(get_db())
        return self._db

    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    bind=True,
    base=JobTrackedTask,
    name="library.scan_path",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(OSError, IOError)
)
def scan_library_path(
    self,
    library_path_id: str,
    scan_job_id: str,
    incremental: bool = True,
    fetch_images: bool = True,
    job_id: str = None
):
    """
    Scan a library path and index all audio files (with job tracking)

    Args:
        library_path_id: UUID of LibraryPath
        scan_job_id: UUID of ScanJob
        incremental: Skip unchanged files
        fetch_images: Fetch MusicBrainz images
        job_id: Optional job ID for resuming

    Returns:
        Dict with scan statistics
    """
    logger.info(f"Starting library scan task: {library_path_id}")

    # Use self.db from JobTrackedTask
    db = self.db

    try:
        # Update progress: Starting
        self.update_progress(
            percent=5.0,
            step=f"Initializing library scan",
            items_processed=0
        )

        # Get library path
        library_path = db.query(LibraryPath).filter(
            LibraryPath.id == library_path_id
        ).first()

        if not library_path:
            raise ValueError(f"Library path not found: {library_path_id}")

        # Get scan job
        scan_job = db.query(ScanJob).filter(
            ScanJob.id == scan_job_id
        ).first()

        if not scan_job:
            raise ValueError(f"Scan job not found: {scan_job_id}")

        # Update scan job with Celery task ID
        scan_job.celery_task_id = self.request.id
        db.commit()

        # Update progress: Starting scan
        self.update_progress(
            percent=10.0,
            step=f"Scanning library path: {library_path.path}"
        )

        # Run scanner with progress callback
        fanart_api_key = getattr(settings, 'fanart_api_key', None)
        scanner = LibraryScanner(db=db, fanart_api_key=fanart_api_key)

        # Define progress callback for scanner
        def progress_callback(current: int, total: int, step: str):
            """Called by scanner to report progress"""
            if total > 0:
                # Scanner progress: 10% to 90%
                scan_percent = (current / total) * 80.0
                overall_percent = 10.0 + scan_percent
                self.update_progress(
                    percent=overall_percent,
                    step=step,
                    items_processed=current,
                    items_total=total
                )

        stats = scanner.scan_path(
            library_path=library_path,
            scan_job=scan_job,
            incremental=incremental,
            fetch_images=fetch_images,
            progress_callback=progress_callback if hasattr(scanner.scan_path, 'progress_callback') else None
        )

        # Update progress: Complete
        self.update_progress(
            percent=100.0,
            step=f"Scan complete - {stats.get('files_processed', 0)} files processed",
            items_processed=stats.get('files_processed', 0),
            items_total=stats.get('files_processed', 0)
        )

        logger.info(f"Library scan completed: {stats}")
        return stats

    except Exception as e:
        db.rollback()
        logger.error(f"Library scan failed: {e}")

        # Update scan job status
        try:
            scan_job = db.query(ScanJob).filter(ScanJob.id == scan_job_id).first()
            if scan_job:
                scan_job.status = 'failed'
                scan_job.error_message = str(e)
                db.commit()
        except:
            pass

        # Re-raise exception so JobTrackedTask.on_failure() is called
        raise


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="library.fetch_images",
    max_retries=3
)
def fetch_missing_images(
    self,
    library_path_id: str,
    batch_size: int = 100
):
    """
    Fetch missing album art and artist images for a library

    Args:
        library_path_id: UUID of LibraryPath
        batch_size: Number of images to fetch per run

    Returns:
        Dict with fetch statistics
    """
    logger.info(f"Fetching missing images for library: {library_path_id}")

    try:
        library_path = self.db.query(LibraryPath).filter(
            LibraryPath.id == library_path_id
        ).first()

        if not library_path:
            raise ValueError(f"Library path not found: {library_path_id}")

        fanart_api_key = getattr(settings, 'fanart_api_key', None)
        scanner = LibraryScanner(db=self.db, fanart_api_key=fanart_api_key)

        stats = scanner._fetch_images(library_path_id)

        logger.info(f"Image fetch completed: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Image fetch failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="library.cleanup_orphaned_files"
)
def cleanup_orphaned_files(self, library_path_id: str):
    """
    Remove database entries for files that no longer exist on disk

    Args:
        library_path_id: UUID of LibraryPath

    Returns:
        Number of files removed
    """
    logger.info(f"Cleaning up orphaned files for library: {library_path_id}")

    try:
        from app.models.library import LibraryFile
        import os

        files = self.db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id
        ).all()

        removed_count = 0

        for file_record in files:
            if not os.path.exists(file_record.file_path):
                self.db.delete(file_record)
                removed_count += 1

                if removed_count % 100 == 0:
                    self.db.commit()
                    logger.info(f"Removed {removed_count} orphaned files...")

        self.db.commit()

        logger.info(f"Cleanup completed: {removed_count} files removed")
        return removed_count

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise


@celery_app.task(
    bind=True,
    base=DatabaseTask,
    name="library.rescan_files",
    max_retries=1
)
def rescan_files(self, file_ids: list):
    """
    Rescan multiple files to refresh metadata

    Args:
        file_ids: List of LibraryFile UUIDs

    Returns:
        Dict with rescan statistics
    """
    from app.models.library import LibraryFile
    from app.services.metadata_extractor import MetadataExtractor
    from datetime import datetime, timezone
    import os

    logger.info(f"Rescanning {len(file_ids)} files")

    stats = {
        'rescanned': 0,
        'failed': 0,
        'not_found': 0
    }

    try:
        for file_id in file_ids:
            try:
                file_record = self.db.query(LibraryFile).filter(
                    LibraryFile.id == file_id
                ).first()

                if not file_record:
                    stats['not_found'] += 1
                    continue

                if not os.path.exists(file_record.file_path):
                    stats['not_found'] += 1
                    continue

                # Extract fresh metadata
                metadata = MetadataExtractor.extract(file_record.file_path)
                file_stat = os.stat(file_record.file_path)

                # Update file record
                file_record.file_size_bytes = file_stat.st_size
                file_record.file_modified_at = datetime.fromtimestamp(
                    file_stat.st_mtime, tz=timezone.utc
                )

                # Update metadata fields
                for key, value in metadata.items():
                    if hasattr(file_record, key):
                        setattr(file_record, key, value)

                file_record.updated_at = datetime.now(timezone.utc)
                stats['rescanned'] += 1

                # Commit every 50 files
                if stats['rescanned'] % 50 == 0:
                    self.db.commit()
                    logger.info(f"Rescanned {stats['rescanned']}/{len(file_ids)} files")

            except Exception as e:
                logger.error(f"Failed to rescan file {file_id}: {e}")
                stats['failed'] += 1

        self.db.commit()
        logger.info(f"Rescan completed: {stats}")
        return stats

    except Exception as e:
        logger.error(f"Rescan task failed: {e}")
        raise
