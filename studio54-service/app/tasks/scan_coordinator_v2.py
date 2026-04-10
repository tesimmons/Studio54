"""
Scan Coordinator V2 - Entry point for two-phase library scanning

Orchestrates the complete V2 scanning process:
- Phase 1: Fast ingestion (2-5 minutes for 100K files)
- Phase 2: Background processing (full metadata, images, hashes)

Based on MUSE V2 scanner architecture.
"""

import os
import logging
from typing import List, Dict
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.library import LibraryPath, ScanJob, LibraryFile
from app.services.fast_metadata_extractor import FastMetadataExtractor
from app.tasks.fast_ingest_tasks import start_fast_ingestion
from app.shared_services.job_logger import JobLogger

logger = logging.getLogger(__name__)


def walk_directory_v2(root_path: str, scan_job: ScanJob = None, db: Session = None) -> Dict[str, any]:
    """
    Walk directory and collect audio file paths with skip statistics

    Args:
        root_path: Root directory to scan
        scan_job: Optional ScanJob to update with progress
        db: Optional database session for committing progress updates

    Returns:
        {
            'files': List[str],  # Valid audio file paths
            'skipped': {
                'total': int,
                'resource_fork': int,
                'hidden': int,
                'system': int,
                'unsupported': int,
                'details': List[str]  # First 100 skipped files
            }
        }
    """
    logger.info(f"🔍 Walking directory: {root_path}")

    audio_files = []
    skip_counts = {
        'resource_fork': 0,
        'hidden': 0,
        'system': 0,
        'unsupported': 0
    }
    skipped_details = []
    files_checked = 0
    dirs_walked = 0
    last_log_count = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Skip hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        dirs_walked += 1

        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            files_checked += 1

            # Check if should skip file
            should_skip, skip_reason = FastMetadataExtractor.should_skip_file(file_path)
            if should_skip:
                skip_counts[skip_reason] = skip_counts.get(skip_reason, 0) + 1
                if len(skipped_details) < 100:  # Limit to first 100
                    skipped_details.append(f"{file_path} ({skip_reason})")
                continue

            # Valid audio file
            audio_files.append(file_path)

        # Log progress every 5000 files checked
        if files_checked - last_log_count >= 5000:
            logger.info(f"📂 Walk progress: {files_checked} files checked, {len(audio_files)} audio files found, {dirs_walked} directories")
            last_log_count = files_checked

            # Update scan job with current action if provided
            if scan_job and db:
                scan_job.current_action = f"Walking directory: {files_checked} files checked, {len(audio_files)} audio found"
                try:
                    db.commit()
                except Exception as e:
                    logger.warning(f"Failed to update scan job progress: {e}")

    total_skipped = sum(skip_counts.values())

    logger.info(
        f"📁 Directory walk complete: {len(audio_files)} audio files found, "
        f"{total_skipped} files skipped"
    )

    # Log skip statistics
    if total_skipped > 0:
        logger.info(f"Skip statistics:")
        for reason, count in skip_counts.items():
            if count > 0:
                logger.info(f"  {reason}: {count} files")

    return {
        'files': audio_files,
        'skipped': {
            'total': total_skipped,
            **skip_counts,
            'details': skipped_details
        }
    }


@celery_app.task(name="app.tasks.scan_coordinator_v2.scan_library_v2")
def scan_library_v2(
    library_path_id: str,
    scan_job_id: str,
    incremental: bool = False,
    batch_size: int = 100
) -> Dict:
    """
    Scan a library path using V2 two-phase architecture

    Phase 1: Fast ingestion (this task)
      - Walk directory
      - Collect all audio files
      - Trigger parallel batch processing

    Phase 2: Background processing (triggered by finalize_fast_ingestion)
      - Full metadata extraction
      - Image fetching
      - Hash calculation

    Args:
        library_path_id: LibraryPath UUID
        scan_job_id: ScanJob UUID
        incremental: Skip unchanged files (TODO: Phase 2 feature)
        batch_size: Files per batch (default: 100)

    Returns:
        {
            'library_path_id': str,
            'scan_job_id': str,
            'total_files': int,
            'skipped_files': int,
            'batches': int
        }
    """
    db = SessionLocal()
    job_logger = None
    try:
        logger.info(
            f"🚀 Starting V2 scan for library_path {library_path_id} "
            f"(incremental={incremental})"
        )

        # Get library path
        library_path = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(library_path_id)
        ).first()

        if not library_path:
            logger.error(f"❌ LibraryPath {library_path_id} not found")
            return {"error": "LibraryPath not found"}

        # Validate path exists
        if not os.path.exists(library_path.path):
            logger.error(f"❌ Path does not exist: {library_path.path}")
            return {"error": f"Path does not exist: {library_path.path}"}

        # Get scan job
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if not scan_job:
            logger.error(f"❌ ScanJob {scan_job_id} not found")
            return {"error": "ScanJob not found"}

        # Initialize job logger for comprehensive activity tracking
        job_logger = JobLogger(job_type="scan", job_id=scan_job_id)
        job_logger.log_job_start("library_scan", library_path.name)
        job_logger.log_info(f"Library Path: {library_path.path}")
        job_logger.log_info(f"Incremental: {incremental}")

        # Save log file path to scan job (convert Path to string for database)
        scan_job.log_file_path = str(job_logger.log_file_path)
        scan_job.status = 'running'
        scan_job.started_at = datetime.now(timezone.utc)
        db.commit()

        # Walk directory to collect all audio files
        job_logger.log_phase_start("Directory Walking", "Scanning for audio files")
        scan_job.current_action = "Walking directory..."
        db.commit()
        walk_result = walk_directory_v2(library_path.path, scan_job=scan_job, db=db)
        audio_files = walk_result['files']
        skip_stats = walk_result['skipped']

        logger.info(
            f"📊 Found {len(audio_files)} audio files, "
            f"skipped {skip_stats['total']} files"
        )

        job_logger.log_info(f"Found {len(audio_files)} audio files")
        job_logger.log_info(f"Skipped {skip_stats['total']} files:")
        if skip_stats.get('resource_fork', 0) > 0:
            job_logger.log_info(f"  - Resource fork files: {skip_stats['resource_fork']}")
        if skip_stats.get('hidden', 0) > 0:
            job_logger.log_info(f"  - Hidden files: {skip_stats['hidden']}")
        if skip_stats.get('system', 0) > 0:
            job_logger.log_info(f"  - System files: {skip_stats['system']}")
        if skip_stats.get('unsupported', 0) > 0:
            job_logger.log_info(f"  - Unsupported formats: {skip_stats['unsupported']}")

        # Update job logger stats
        job_logger.stats.files_total = len(audio_files)
        job_logger.stats.files_skipped = skip_stats['total']

        # Update scan job with skip statistics
        scan_job.skip_statistics = skip_stats
        scan_job.files_skipped = skip_stats['total']
        db.commit()

        # Log skip details
        if skip_stats['details']:
            logger.info(f"Skipped files ({len(skip_stats['details'])} shown):")
            for detail in skip_stats['details']:
                logger.info(f"  SKIPPED: {detail}")

        # Detect and remove orphaned files (exist in DB but not on disk)
        job_logger.log_phase_start("Orphan Detection", "Checking for files no longer on disk")
        files_on_disk = set(audio_files)

        # Get existing files from database
        existing_db_files = db.query(LibraryFile.file_path).filter(
            LibraryFile.library_path_id == UUID(library_path_id)
        ).all()
        existing_db_paths = {f[0] for f in existing_db_files}

        # Find orphaned files
        orphaned_files = existing_db_paths - files_on_disk
        files_removed = 0

        if orphaned_files:
            logger.info(f"🗑️ Found {len(orphaned_files)} orphaned files to remove")
            job_logger.log_info(f"Found {len(orphaned_files)} orphaned files (no longer on disk)")

            # Delete orphaned files in batches
            BATCH_SIZE = 100
            orphaned_list = list(orphaned_files)

            for i in range(0, len(orphaned_list), BATCH_SIZE):
                batch_paths = orphaned_list[i:i + BATCH_SIZE]
                try:
                    deleted = db.query(LibraryFile).filter(
                        LibraryFile.library_path_id == UUID(library_path_id),
                        LibraryFile.file_path.in_(batch_paths)
                    ).delete(synchronize_session=False)
                    files_removed += deleted
                    db.commit()
                except Exception as e:
                    logger.error(f"Error removing orphaned files batch: {e}")
                    db.rollback()

            job_logger.log_info(f"Removed {files_removed} orphaned files from database")
            logger.info(f"✅ Removed {files_removed} orphaned files")

            # Update scan job
            scan_job.files_removed = files_removed
            db.commit()
        else:
            job_logger.log_info(f"No orphaned files found")

        # Start fast ingestion (Phase 1)
        # This will process files in parallel batches across Celery workers
        job_logger.log_phase_start("Fast Ingestion", "Processing files in parallel batches")
        job_logger.log_info(f"Batch size: {batch_size}")

        ingestion_result = start_fast_ingestion(
            library_path_id=library_path_id,
            scan_job_id=scan_job_id,
            file_paths=audio_files,
            batch_size=batch_size
        )

        total_batches = ingestion_result.get('total_batches', 0)
        logger.info(
            f"✅ V2 scan initiated: {ingestion_result.get('total_files', 0)} files "
            f"in {total_batches} batches"
        )

        job_logger.log_info(f"Created {total_batches} batches for parallel processing")
        job_logger.log_info(f"Scan continues in background workers...")

        return {
            'library_path_id': library_path_id,
            'scan_job_id': scan_job_id,
            'total_files': len(audio_files),
            'skipped_files': skip_stats['total'],
            'files_removed': files_removed,
            'batches': total_batches,
            'skip_statistics': skip_stats,
            'log_file_path': job_logger.log_file_path
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ V2 scan failed: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")

        # Log error to job logger
        if job_logger:
            job_logger.log_error(str(e))
            job_logger.log_job_complete()

        # Update scan job status
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if scan_job:
            scan_job.status = 'failed'
            scan_job.error_message = str(e)
            scan_job.completed_at = datetime.now(timezone.utc)
            db.commit()

        return {'error': str(e)}

    finally:
        db.close()


@celery_app.task(name="app.tasks.scan_coordinator_v2.cancel_scan_v2")
def cancel_scan_v2(
    scan_job_id: str,
    delete_partial_files: bool = False
) -> Dict:
    """
    Cancel a running V2 scan

    Args:
        scan_job_id: ScanJob UUID
        delete_partial_files: If True, delete all files ingested during this scan

    Returns:
        {
            'cancelled': bool,
            'files_kept': int,
            'files_deleted': int
        }
    """
    db = SessionLocal()
    try:
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if not scan_job:
            logger.error(f"❌ ScanJob {scan_job_id} not found")
            return {"error": "ScanJob not found"}

        # Set pause flag (workers will check and stop)
        scan_job.pause_requested = True
        scan_job.status = 'cancelled'
        scan_job.completed_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(f"🛑 Scan job {scan_job_id} cancelled (pause_requested=True)")

        # Optionally delete partial files
        files_deleted = 0
        if delete_partial_files:
            # TODO: Implement cleanup - delete all files with indexed_at >= scan_job.started_at
            logger.warning("⚠️  Partial file deletion not yet implemented")

        return {
            'cancelled': True,
            'files_kept': scan_job.files_added,
            'files_deleted': files_deleted
        }

    except Exception as e:
        logger.error(f"❌ Failed to cancel scan: {e}")
        return {'error': str(e)}

    finally:
        db.close()
