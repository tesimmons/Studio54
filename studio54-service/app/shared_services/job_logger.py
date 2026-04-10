"""
Job Logger Service
Handles logging of all job operations to job-specific log files

Supports:
- File Organization jobs
- Scan jobs
- Sync jobs
- Download jobs
- Import jobs
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from threading import Lock
from contextlib import contextmanager
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class JobStats:
    """Statistics tracked during job execution"""
    files_total: int = 0
    files_processed: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    files_renamed: int = 0
    files_moved: int = 0
    files_deleted: int = 0
    directories_created: int = 0
    directories_modified: int = 0
    artists_found: int = 0
    artists_matched: int = 0
    artists_created: int = 0
    albums_found: int = 0
    albums_synced: int = 0
    tracks_found: int = 0
    tracks_matched: int = 0
    bytes_processed: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class JobLogger:
    """
    Thread-safe logger for all job types

    Creates and manages log files for tracking all operations
    during file organization, scanning, syncing, downloading, and importing.
    """

    # Job type display names
    JOB_TYPE_NAMES = {
        'organize_library': 'Library Organization',
        'organize_artist': 'Artist Organization',
        'scan': 'Library Scan',
        'sync': 'Artist Sync',
        'download': 'Album Download',
        'import': 'Library Import',
        'enrichment': 'Metadata Enrichment',
        'index_metadata': 'Metadata Indexing',
        'fetch_images': 'Image Fetch',
        'calculate_hashes': 'Hash Calculation',
        'validate_mbid_metadata': 'MBID Metadata Validation',
        'validate_mbid': 'MBID Validation',
        'validate_structure': 'Structure Validation',
        'fetch_metadata': 'Metadata Fetch',
        'link_files': 'File Linking',
        'reindex_albums': 'Album Reindex',
        'verify_audio': 'Audio Verification',
        'validate_file_links': 'File Link Validation',
    }

    def __init__(
        self,
        job_id: str,
        job_type: str = 'generic',
        log_dir: str = "/app/logs/jobs"
    ):
        """
        Initialize job logger

        Args:
            job_id: UUID of the job
            job_type: Type of job (organize_library, scan, sync, download, import)
            log_dir: Directory where log files will be stored
        """
        self.job_id = job_id
        self.job_type = job_type
        self.log_dir = Path(log_dir)
        self.log_file_path = self.log_dir / f"{job_id}.log"
        self._lock = Lock()
        self.stats = JobStats()
        self._file_operations: List[Dict[str, Any]] = []

        # Ensure log directory exists
        self._ensure_log_directory()

        # Initialize log file
        self._initialize_log_file()

    def _ensure_log_directory(self):
        """Create log directory if it doesn't exist"""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Log directory ensured: {self.log_dir}")
        except Exception as e:
            logger.error(f"Failed to create log directory {self.log_dir}: {e}")
            raise

    def _initialize_log_file(self):
        """Initialize log file with header"""
        timestamp = datetime.now(timezone.utc).isoformat()
        job_type_name = self.JOB_TYPE_NAMES.get(self.job_type, self.job_type.replace('_', ' ').title())
        header = f"""{'='*80}
{job_type_name} Job Log
Job ID: {self.job_id}
Job Type: {self.job_type}
Started: {timestamp}
{'='*80}

"""
        try:
            with open(self.log_file_path, 'w') as f:
                f.write(header)
            logger.info(f"Initialized log file: {self.log_file_path}")
        except Exception as e:
            logger.error(f"Failed to initialize log file {self.log_file_path}: {e}")
            raise

    @contextmanager
    def _write_lock(self):
        """Context manager for thread-safe writing"""
        self._lock.acquire()
        try:
            yield
        finally:
            self._lock.release()

    def _write_entry(self, message: str):
        """
        Write a log entry with timestamp

        Args:
            message: Log message to write
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"[{timestamp}] {message}\n"

        with self._write_lock():
            try:
                with open(self.log_file_path, 'a') as f:
                    f.write(entry)
            except Exception as e:
                logger.error(f"Failed to write to log file {self.log_file_path}: {e}")

    def log_job_start(self, job_type: str, target: str):
        """
        Log job start

        Args:
            job_type: Type of job (organize_library, organize_artist, etc.)
            target: Target being processed (library name, artist name, etc.)
        """
        message = f"JOB START: {job_type} - Target: {target}"
        self._write_entry(message)
        self._write_entry("-" * 80)

    def log_job_complete(self, stats: dict = None):
        """
        Log job completion with comprehensive statistics

        Args:
            stats: Dictionary of job statistics (uses self.stats if not provided)
        """
        if stats is None:
            stats = {
                'files_total': self.stats.files_total,
                'files_processed': self.stats.files_processed,
                'files_added': self.stats.files_added,
                'files_updated': self.stats.files_updated,
                'files_skipped': self.stats.files_skipped,
                'files_failed': self.stats.files_failed,
                'files_renamed': self.stats.files_renamed,
                'files_moved': self.stats.files_moved,
                'files_deleted': self.stats.files_deleted,
                'directories_created': self.stats.directories_created,
                'directories_modified': self.stats.directories_modified,
            }

        self._write_entry("")
        self._write_entry("-" * 80)
        self._write_entry("JOB COMPLETE - SUMMARY")
        self._write_entry("-" * 80)

        # File statistics
        self._write_entry("")
        self._write_entry("FILE STATISTICS:")
        self._write_entry(f"  Total Files:      {stats.get('files_total', 0)}")
        self._write_entry(f"  Files Processed:  {stats.get('files_processed', 0)}")

        if stats.get('files_added', 0) > 0:
            self._write_entry(f"  Files Added:      {stats.get('files_added', 0)}")
        if stats.get('files_updated', 0) > 0:
            self._write_entry(f"  Files Updated:    {stats.get('files_updated', 0)}")
        if stats.get('files_skipped', 0) > 0:
            self._write_entry(f"  Files Skipped:    {stats.get('files_skipped', 0)}")
        if stats.get('files_renamed', 0) > 0:
            self._write_entry(f"  Files Renamed:    {stats.get('files_renamed', 0)}")
        if stats.get('files_moved', 0) > 0:
            self._write_entry(f"  Files Moved:      {stats.get('files_moved', 0)}")
        if stats.get('files_deleted', 0) > 0:
            self._write_entry(f"  Files Deleted:    {stats.get('files_deleted', 0)}")
        if stats.get('files_failed', 0) > 0:
            self._write_entry(f"  Files Failed:     {stats.get('files_failed', 0)}")

        # Directory statistics
        dirs_created = stats.get('directories_created', 0)
        dirs_modified = stats.get('directories_modified', 0)
        if dirs_created > 0 or dirs_modified > 0:
            self._write_entry("")
            self._write_entry("DIRECTORY STATISTICS:")
            if dirs_created > 0:
                self._write_entry(f"  Directories Created:  {dirs_created}")
            if dirs_modified > 0:
                self._write_entry(f"  Directories Modified: {dirs_modified}")

        # Artist/Album statistics (for import/sync jobs)
        if stats.get('artists_found', 0) > 0 or stats.get('albums_found', 0) > 0:
            self._write_entry("")
            self._write_entry("LIBRARY STATISTICS:")
            if stats.get('artists_found', 0) > 0:
                self._write_entry(f"  Artists Found:    {stats.get('artists_found', 0)}")
            if stats.get('artists_matched', 0) > 0:
                self._write_entry(f"  Artists Matched:  {stats.get('artists_matched', 0)}")
            if stats.get('artists_created', 0) > 0:
                self._write_entry(f"  Artists Created:  {stats.get('artists_created', 0)}")
            if stats.get('albums_found', 0) > 0:
                self._write_entry(f"  Albums Found:     {stats.get('albums_found', 0)}")
            if stats.get('albums_synced', 0) > 0:
                self._write_entry(f"  Albums Synced:    {stats.get('albums_synced', 0)}")
            if stats.get('tracks_found', 0) > 0:
                self._write_entry(f"  Tracks Found:     {stats.get('tracks_found', 0)}")
            if stats.get('tracks_matched', 0) > 0:
                self._write_entry(f"  Tracks Matched:   {stats.get('tracks_matched', 0)}")

        # Errors summary
        if stats.get('files_failed', 0) > 0 or len(self.stats.errors) > 0:
            self._write_entry("")
            self._write_entry(f"ERRORS: {max(stats.get('files_failed', 0), len(self.stats.errors))}")

        self._write_entry("")
        self._write_entry("=" * 80)

    def log_job_error(self, error: str):
        """
        Log job error

        Args:
            error: Error message
        """
        self._write_entry("-" * 80)
        self._write_entry(f"JOB ERROR: {error}")
        self._write_entry("=" * 80)

    def log_phase_start(self, phase_name: str, description: str = ""):
        """
        Log start of a job phase

        Args:
            phase_name: Name of the phase
            description: Optional description
        """
        self._write_entry("")
        self._write_entry(f"PHASE: {phase_name}")
        if description:
            self._write_entry(f"  {description}")
        self._write_entry("-" * 40)

    def log_phase_complete(self, phase_name: str, count: int = 0):
        """
        Log completion of a job phase

        Args:
            phase_name: Name of the phase
            count: Number of items processed
        """
        if count > 0:
            self._write_entry(f"PHASE COMPLETE: {phase_name} - {count} items processed")
        else:
            self._write_entry(f"PHASE COMPLETE: {phase_name}")
        self._write_entry("")

    def log_file_operation(
        self,
        operation: str,
        source_path: str,
        destination_path: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None
    ):
        """
        Log a file operation

        Args:
            operation: Operation type (rename, move, delete, copy, validate)
            source_path: Source file path
            destination_path: Destination path (for move/copy operations)
            success: Whether operation succeeded
            error: Error message if operation failed
        """
        status = "SUCCESS" if success else "FAILED"

        if destination_path:
            message = f"{operation.upper()}: {status}\n  From: {source_path}\n  To:   {destination_path}"
        else:
            message = f"{operation.upper()}: {status}\n  File: {source_path}"

        if error:
            message += f"\n  Error: {error}"

        self._write_entry(message)

    def log_validation_issue(self, issue_type: str, description: str, file_path: str = ""):
        """
        Log a validation issue

        Args:
            issue_type: Type of issue (missing_file, incorrect_name, misplaced, etc.)
            description: Issue description
            file_path: Related file path (if applicable)
        """
        message = f"VALIDATION ISSUE: {issue_type}\n  {description}"
        if file_path:
            message += f"\n  File: {file_path}"
        self._write_entry(message)

    def log_batch_operation(self, operation: str, count: int, description: str = ""):
        """
        Log a batch operation

        Args:
            operation: Operation type
            count: Number of files in batch
            description: Optional description
        """
        message = f"BATCH {operation.upper()}: {count} files"
        if description:
            message += f" - {description}"
        self._write_entry(message)

    def log_info(self, message: str):
        """
        Log an informational message

        Args:
            message: Info message
        """
        self._write_entry(f"INFO: {message}")

    def log_warning(self, message: str):
        """
        Log a warning message

        Args:
            message: Warning message
        """
        self._write_entry(f"WARNING: {message}")

    def log_error(self, message: str):
        """
        Log an error message

        Args:
            message: Error message
        """
        self._write_entry(f"ERROR: {message}")

    def get_log_file_path(self) -> str:
        """
        Get the path to the log file

        Returns:
            Absolute path to log file
        """
        return str(self.log_file_path.absolute())

    def get_log_file_size(self) -> int:
        """
        Get the size of the log file in bytes

        Returns:
            File size in bytes, or 0 if file doesn't exist
        """
        try:
            return self.log_file_path.stat().st_size
        except FileNotFoundError:
            return 0

    @staticmethod
    def delete_log_file(log_file_path: str) -> bool:
        """
        Delete a job log file

        Args:
            log_file_path: Path to log file to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            path = Path(log_file_path)
            if path.exists():
                path.unlink()
                logger.info(f"Deleted log file: {log_file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete log file {log_file_path}: {e}")
            return False

    @staticmethod
    def cleanup_old_logs(log_dir: str = "/app/logs/jobs", days: int = 30) -> int:
        """
        Clean up log files older than specified days

        Args:
            log_dir: Directory containing log files
            days: Delete logs older than this many days

        Returns:
            Number of files deleted
        """
        try:
            log_path = Path(log_dir)
            if not log_path.exists():
                return 0

            import time
            cutoff_time = time.time() - (days * 24 * 60 * 60)
            deleted_count = 0

            for log_file in log_path.glob("*.log"):
                try:
                    if log_file.stat().st_mtime < cutoff_time:
                        log_file.unlink()
                        deleted_count += 1
                except Exception as e:
                    logger.error(f"Failed to delete old log file {log_file}: {e}")

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old log files from {log_dir}")

            return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup old logs in {log_dir}: {e}")
            return 0

    # ========================================
    # Directory Tracking Methods
    # ========================================

    def log_directory_created(self, directory_path: str):
        """Log creation of a new directory"""
        self.stats.directories_created += 1
        self._write_entry(f"DIR CREATE: {directory_path}")

    def log_directory_modified(self, directory_path: str, action: str = "modified"):
        """Log modification of a directory"""
        self.stats.directories_modified += 1
        self._write_entry(f"DIR {action.upper()}: {directory_path}")

    # ========================================
    # Scan Job Methods
    # ========================================

    def log_scan_file(
        self,
        file_path: str,
        action: str,  # added, updated, skipped, failed
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """
        Log a file scan operation

        Args:
            file_path: Path to the scanned file
            action: What happened (added, updated, skipped, failed)
            metadata: Extracted metadata (optional)
            error: Error message if failed
        """
        # Update stats
        if action == 'added':
            self.stats.files_added += 1
        elif action == 'updated':
            self.stats.files_updated += 1
        elif action == 'skipped':
            self.stats.files_skipped += 1
        elif action == 'failed':
            self.stats.files_failed += 1
            if error:
                self.stats.errors.append(f"{file_path}: {error}")

        self.stats.files_processed += 1

        # Build log message
        status = action.upper()
        message = f"SCAN {status}: {file_path}"

        if metadata:
            if metadata.get('artist'):
                message += f"\n  Artist: {metadata.get('artist')}"
            if metadata.get('album'):
                message += f"\n  Album: {metadata.get('album')}"
            if metadata.get('title'):
                message += f"\n  Title: {metadata.get('title')}"

        if error:
            message += f"\n  Error: {error}"

        self._write_entry(message)

    # ========================================
    # Sync Job Methods
    # ========================================

    def log_artist_sync(
        self,
        artist_name: str,
        action: str,  # found, matched, created, updated, failed
        mbid: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Log an artist sync operation"""
        if action == 'found':
            self.stats.artists_found += 1
        elif action == 'matched':
            self.stats.artists_matched += 1
        elif action == 'created':
            self.stats.artists_created += 1
        elif action == 'failed':
            if error:
                self.stats.errors.append(f"Artist {artist_name}: {error}")

        message = f"ARTIST {action.upper()}: {artist_name}"
        if mbid:
            message += f" (MBID: {mbid})"
        if error:
            message += f"\n  Error: {error}"

        self._write_entry(message)

    def log_album_sync(
        self,
        album_title: str,
        artist_name: str,
        action: str,  # found, synced, downloaded, failed
        mbid: Optional[str] = None,
        error: Optional[str] = None
    ):
        """Log an album sync operation"""
        if action == 'found':
            self.stats.albums_found += 1
        elif action == 'synced':
            self.stats.albums_synced += 1
        elif action == 'failed':
            if error:
                self.stats.errors.append(f"Album {album_title}: {error}")

        message = f"ALBUM {action.upper()}: {artist_name} - {album_title}"
        if mbid:
            message += f" (MBID: {mbid})"
        if error:
            message += f"\n  Error: {error}"

        self._write_entry(message)

    def log_track_match(
        self,
        file_path: str,
        track_title: str,
        action: str,  # matched, unmatched, failed
        mbid: Optional[str] = None,
        confidence: Optional[float] = None,
        error: Optional[str] = None
    ):
        """Log a track matching operation"""
        if action == 'matched':
            self.stats.tracks_matched += 1
        elif action == 'found':
            self.stats.tracks_found += 1
        elif action == 'failed':
            if error:
                self.stats.errors.append(f"Track {track_title}: {error}")

        message = f"TRACK {action.upper()}: {track_title}"
        if mbid:
            message += f" (MBID: {mbid})"
        if confidence is not None:
            message += f" [Confidence: {confidence:.1f}%]"
        message += f"\n  File: {file_path}"
        if error:
            message += f"\n  Error: {error}"

        self._write_entry(message)

    # ========================================
    # Download Job Methods
    # ========================================

    def log_download_start(self, source: str, album_title: str, artist_name: str):
        """Log start of a download"""
        self._write_entry(f"DOWNLOAD START: {artist_name} - {album_title}")
        self._write_entry(f"  Source: {source}")

    def log_download_progress(self, percent: float, current_file: Optional[str] = None):
        """Log download progress"""
        message = f"DOWNLOAD PROGRESS: {percent:.1f}%"
        if current_file:
            message += f" - {current_file}"
        self._write_entry(message)

    def log_download_complete(
        self,
        album_title: str,
        artist_name: str,
        files_count: int,
        destination_path: str
    ):
        """Log completion of a download"""
        self._write_entry(f"DOWNLOAD COMPLETE: {artist_name} - {album_title}")
        self._write_entry(f"  Files: {files_count}")
        self._write_entry(f"  Destination: {destination_path}")

    # ========================================
    # Import Job Methods
    # ========================================

    def log_import_phase_start(self, phase_name: str, items_count: int = 0):
        """Log start of an import phase"""
        self._write_entry("")
        self._write_entry(f"IMPORT PHASE: {phase_name}")
        if items_count > 0:
            self._write_entry(f"  Items to process: {items_count}")
        self._write_entry("-" * 40)

    def log_import_match(
        self,
        item_type: str,  # artist, album, track
        local_name: str,
        matched_name: Optional[str] = None,
        confidence: Optional[float] = None,
        auto_matched: bool = False
    ):
        """Log an import match result"""
        if matched_name:
            status = "AUTO-MATCHED" if auto_matched else "MATCHED"
            message = f"IMPORT {status}: {item_type.upper()} '{local_name}' -> '{matched_name}'"
        else:
            message = f"IMPORT UNMATCHED: {item_type.upper()} '{local_name}'"

        if confidence is not None:
            message += f" [Confidence: {confidence:.1f}%]"

        self._write_entry(message)

    # ========================================
    # Stats Management Methods
    # ========================================

    def increment_stat(self, stat_name: str, amount: int = 1):
        """Increment a stat counter"""
        if hasattr(self.stats, stat_name):
            setattr(self.stats, stat_name, getattr(self.stats, stat_name) + amount)

    def get_stats(self) -> Dict[str, Any]:
        """Get all stats as a dictionary"""
        return {
            'files_total': self.stats.files_total,
            'files_processed': self.stats.files_processed,
            'files_added': self.stats.files_added,
            'files_updated': self.stats.files_updated,
            'files_skipped': self.stats.files_skipped,
            'files_failed': self.stats.files_failed,
            'files_renamed': self.stats.files_renamed,
            'files_moved': self.stats.files_moved,
            'files_deleted': self.stats.files_deleted,
            'directories_created': self.stats.directories_created,
            'directories_modified': self.stats.directories_modified,
            'artists_found': self.stats.artists_found,
            'artists_matched': self.stats.artists_matched,
            'artists_created': self.stats.artists_created,
            'albums_found': self.stats.albums_found,
            'albums_synced': self.stats.albums_synced,
            'tracks_found': self.stats.tracks_found,
            'tracks_matched': self.stats.tracks_matched,
            'errors_count': len(self.stats.errors),
            'warnings_count': len(self.stats.warnings),
        }


# Example usage in organization tasks:
"""
from app.shared_services.job_logger import JobLogger

# In organize_library_files_task:
job_logger = JobLogger(job_id=str(job.id))
job_logger.log_job_start("organize_library", library.name)

# Update job with log file path
job.log_file_path = job_logger.get_log_file_path()
db.commit()

# Log phases
job_logger.log_phase_start("File Discovery", "Scanning library for audio files")
# ... discover files ...
job_logger.log_phase_complete("File Discovery", count=len(files))

# Log operations
for file in files:
    try:
        # ... perform operation ...
        job_logger.log_file_operation(
            operation="move",
            source_path=file.old_path,
            destination_path=file.new_path,
            success=True
        )
    except Exception as e:
        job_logger.log_file_operation(
            operation="move",
            source_path=file.old_path,
            destination_path=file.new_path,
            success=False,
            error=str(e)
        )

# Complete job
job_logger.log_job_complete({
    'files_total': job.files_total,
    'files_processed': job.files_processed,
    'files_renamed': job.files_renamed,
    'files_moved': job.files_moved,
    'files_failed': job.files_failed
})
"""
