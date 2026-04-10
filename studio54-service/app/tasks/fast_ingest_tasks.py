"""
Fast Ingest Tasks - Phase 1 of Two-Phase Scan (V2 Scanner)

Extracts minimal metadata and inserts files into database immediately.
Files become searchable within 2-5 minutes.

Based on MUSE V2 fast ingestion implementation.
"""

import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from uuid import UUID

from celery import chord
from sqlalchemy.orm import Session
from sqlalchemy import update, func

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.library import LibraryPath, LibraryFile, ScanJob
from app.services.fast_metadata_extractor import FastMetadataExtractor
from app.shared_services.job_logger import JobLogger

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.fast_ingest_tasks.fast_ingest_batch")
def fast_ingest_batch(
    library_path_id: str,
    scan_job_id: str,
    file_paths: List[str],
    batch_number: int,
    total_batches: int,
    start_time: float = None
) -> Dict:
    """
    Fast ingest a batch of files (Phase 1)

    Args:
        library_path_id: LibraryPath UUID
        scan_job_id: ScanJob UUID
        file_paths: List of file paths to process
        batch_number: Current batch number (1-indexed)
        total_batches: Total number of batches

    Returns:
        {
            'batch_number': int,
            'files_processed': int,
            'files_ingested': int,
            'files_skipped': int,
            'errors': int,
            'skip_details': List[str]
        }
    """
    import time
    batch_start_time = time.time()

    logger.info(
        f"⚡ fast_ingest_batch ENTRY: batch {batch_number}/{total_batches}, "
        f"received {len(file_paths)} files"
    )

    db = SessionLocal()
    try:
        # Get scan job
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if not scan_job:
            logger.error(f"❌ Scan job {scan_job_id} not found")
            return {"error": "Scan job not found"}

        # Check for pause request
        if scan_job.pause_requested:
            logger.info(f"⏸️  Pause requested for scan job {scan_job_id}, stopping batch")
            return {
                'batch_number': batch_number,
                'files_processed': 0,
                'files_ingested': 0,
                'files_skipped': 0,
                'paused': True
            }

        logger.info(
            f"Fast ingesting batch {batch_number}/{total_batches} "
            f"({len(file_paths)} files) for library_path {library_path_id}"
        )

        # Get library_type from parent LibraryPath
        library_path_obj = db.query(LibraryPath).filter(LibraryPath.id == UUID(library_path_id)).first()
        library_type = getattr(library_path_obj, 'library_type', 'music') if library_path_obj else 'music'

        # Track statistics
        files_ingested = 0
        files_skipped = 0
        errors = 0
        skip_details = []

        # Process each file
        for file_path in file_paths:
            try:
                # Check if should skip file
                should_skip, skip_reason = FastMetadataExtractor.should_skip_file(file_path)
                if should_skip:
                    files_skipped += 1
                    skip_details.append(f"{file_path} ({skip_reason})")
                    continue

                # Extract fast metadata
                metadata = FastMetadataExtractor.extract_fast(file_path)

                # Check if file already exists
                existing_file = db.query(LibraryFile).filter(
                    LibraryFile.library_path_id == UUID(library_path_id),
                    LibraryFile.file_path == metadata['file_path']
                ).first()

                if existing_file:
                    # Update existing file with fast metadata
                    existing_file.title = metadata['title']
                    existing_file.artist = metadata['artist']
                    existing_file.album = metadata['album']
                    existing_file.duration_seconds = metadata['duration_seconds']
                    existing_file.file_size_bytes = metadata['file_size_bytes']
                    existing_file.format = metadata['format']
                    existing_file.file_modified_at = metadata['file_modified_at']
                    existing_file.updated_at = datetime.now(timezone.utc)
                    # Update MBIDs if newly extracted (don't overwrite existing with None)
                    if metadata.get('musicbrainz_trackid'):
                        existing_file.musicbrainz_trackid = metadata['musicbrainz_trackid']
                    if metadata.get('musicbrainz_albumid'):
                        existing_file.musicbrainz_albumid = metadata['musicbrainz_albumid']
                    if metadata.get('musicbrainz_artistid'):
                        existing_file.musicbrainz_artistid = metadata['musicbrainz_artistid']
                    if metadata.get('musicbrainz_releasegroupid'):
                        existing_file.musicbrainz_releasegroupid = metadata['musicbrainz_releasegroupid']
                    if metadata.get('mbid_in_file'):
                        existing_file.mbid_in_file = True
                    if metadata.get('metadata_json') and not existing_file.metadata_json:
                        existing_file.metadata_json = metadata['metadata_json']
                else:
                    # Create new file record
                    library_file = LibraryFile(
                        library_path_id=UUID(library_path_id),
                        file_path=metadata['file_path'],
                        file_name=metadata['file_name'],
                        file_size_bytes=metadata['file_size_bytes'],
                        file_modified_at=metadata['file_modified_at'],
                        format=metadata['format'],
                        duration_seconds=metadata['duration_seconds'],
                        title=metadata['title'],
                        artist=metadata['artist'],
                        album=metadata['album'],
                        library_type=library_type,
                        # MBID fields (extracted from comment tag in Phase 1)
                        musicbrainz_trackid=metadata.get('musicbrainz_trackid'),
                        musicbrainz_albumid=metadata.get('musicbrainz_albumid'),
                        musicbrainz_artistid=metadata.get('musicbrainz_artistid'),
                        musicbrainz_releasegroupid=metadata.get('musicbrainz_releasegroupid'),
                        mbid_in_file=metadata.get('mbid_in_file', False),
                        metadata_json=metadata.get('metadata_json'),
                        # Phase 2 fields (None for now)
                        album_artist=None,
                        track_number=None,
                        disc_number=None,
                        year=None,
                        genre=None,
                        bitrate_kbps=None,
                        sample_rate_hz=None,
                        has_embedded_artwork=False,
                        album_art_fetched=False,
                        album_art_url=None,
                        artist_image_fetched=False,
                        artist_image_url=None
                    )
                    db.add(library_file)

                files_ingested += 1

            except Exception as e:
                logger.error(f"❌ Error processing file {file_path}: {e}")
                errors += 1
                continue

        # Commit batch to database
        try:
            db.commit()
            logger.info(
                f"✅ Batch commit successful: {files_ingested} files ingested, "
                f"{files_skipped} skipped, {errors} errors"
            )
        except Exception as commit_error:
            logger.error(f"❌ Batch commit failed: {commit_error}")
            db.rollback()
            raise

        # Calculate batch performance metrics
        batch_duration = time.time() - batch_start_time
        files_per_second = len(file_paths) / batch_duration if batch_duration > 0 else 0

        # Calculate overall time estimates
        current_time = time.time()
        elapsed_seconds = 0
        estimated_remaining_seconds = 0

        if start_time:
            elapsed_seconds = int(current_time - start_time)

            # Get current progress to calculate estimates
            scan_job_check = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
            if scan_job_check:
                files_processed_so_far = scan_job_check.files_scanned + len(file_paths)
                total_files = scan_job_check.files_scanned + (total_batches * 100)  # Approximate

                if files_processed_so_far > 0 and elapsed_seconds > 0:
                    avg_seconds_per_file = elapsed_seconds / files_processed_so_far
                    files_remaining = total_files - files_processed_so_far
                    estimated_remaining_seconds = int(files_remaining * avg_seconds_per_file)

        # Update scan job progress atomically (prevents race conditions)
        db.execute(
            update(ScanJob)
            .where(ScanJob.id == UUID(scan_job_id))
            .values(
                files_scanned=ScanJob.files_scanned + len(file_paths),
                files_added=ScanJob.files_added + files_ingested,
                files_skipped=ScanJob.files_skipped + files_skipped,
                files_failed=ScanJob.files_failed + errors,
                elapsed_seconds=elapsed_seconds,
                estimated_remaining_seconds=estimated_remaining_seconds
            )
        )
        db.commit()

        # Format time for logging
        time_str = ""
        if elapsed_seconds > 0:
            if estimated_remaining_seconds > 0:
                # Format remaining time
                hours = estimated_remaining_seconds // 3600
                minutes = (estimated_remaining_seconds % 3600) // 60
                seconds = estimated_remaining_seconds % 60

                if hours > 0:
                    time_str = f" • {hours}h {minutes}m remaining"
                elif minutes > 0:
                    time_str = f" • {minutes}m {seconds}s remaining"
                else:
                    time_str = f" • {seconds}s remaining"

        logger.info(
            f"✅ Batch {batch_number}/{total_batches} complete: "
            f"{files_ingested} ingested, {files_skipped} skipped, {errors} errors "
            f"({batch_duration:.1f}s @ {files_per_second:.1f} files/sec){time_str}"
        )

        # Log skip details (first 100 only)
        if skip_details:
            logger.info(f"Skipped files in batch {batch_number} ({len(skip_details)} total):")
            for detail in skip_details[:100]:
                logger.info(f"  SKIPPED: {detail}")

        return {
            'batch_number': batch_number,
            'files_processed': len(file_paths),
            'files_ingested': files_ingested,
            'files_skipped': files_skipped,
            'errors': errors,
            'skip_details': skip_details[:100]  # Limit to 100
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ Fast ingest batch {batch_number} failed: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        db.rollback()
        return {
            'batch_number': batch_number,
            'files_processed': 0,
            'files_ingested': 0,
            'files_skipped': 0,
            'error': str(e)
        }

    finally:
        db.close()


@celery_app.task(name="app.tasks.fast_ingest_tasks.start_fast_ingestion")
def start_fast_ingestion(
    library_path_id: str,
    scan_job_id: str,
    file_paths: List[str],
    batch_size: int = 100
) -> Dict:
    """
    Start fast ingestion process for a library path

    Splits files into batches and processes them in parallel across workers.
    Uses Celery chord for batch synchronization with finalize callback.

    Args:
        library_path_id: LibraryPath UUID
        scan_job_id: ScanJob UUID
        file_paths: List of all file paths to ingest
        batch_size: Number of files per batch (default: 100)

    Returns:
        {
            'total_files': int,
            'total_batches': int,
            'batches_submitted': int
        }
    """
    db = SessionLocal()
    try:
        logger.info(
            f"🚀 Starting fast ingestion for library_path {library_path_id}: "
            f"{len(file_paths)} files in batches of {batch_size}"
        )

        # Update scan job status
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if not scan_job:
            logger.error(f"❌ Scan job {scan_job_id} not found")
            return {"error": "Scan job not found"}

        import time
        start_time = time.time()

        scan_job.status = 'running'
        scan_job.started_at = datetime.now(timezone.utc)

        # Save checkpoint data with start time
        scan_job.checkpoint_data = {
            'phase': 'fast_ingestion',
            'total_files': len(file_paths),
            'started_at': datetime.now(timezone.utc).isoformat(),
            'start_time': start_time
        }

        db.commit()

        # Split files into batches
        batches = []
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i + batch_size]
            batches.append(batch)

        total_batches = len(batches)
        logger.info(f"📦 Created {total_batches} batches of ~{batch_size} files each")

        # Submit batches as parallel tasks using Celery chord with finalize callback
        batch_tasks = []
        for batch_number, batch_files in enumerate(batches, start=1):
            task = fast_ingest_batch.s(
                library_path_id=library_path_id,
                scan_job_id=scan_job_id,
                file_paths=batch_files,
                batch_number=batch_number,
                total_batches=total_batches,
                start_time=start_time  # Pass start time for progress calculation
            )
            batch_tasks.append(task)

        # Execute batches in parallel with callback to finalize when all complete
        callback = finalize_fast_ingestion.si(scan_job_id)
        job = chord(batch_tasks)(callback)

        logger.info(
            f"✅ Submitted {len(batch_tasks)} fast ingest batches with finalize callback"
        )

        return {
            'total_files': len(file_paths),
            'total_batches': total_batches,
            'batches_submitted': len(batch_tasks),
            'group_id': job.id
        }

    except Exception as e:
        logger.error(f"❌ Failed to start fast ingestion: {e}")
        db.rollback()
        return {'error': str(e)}

    finally:
        db.close()


def update_library_path_statistics(library_path_id: UUID, db: Session) -> Dict:
    """
    Update LibraryPath statistics from library_files table

    Args:
        library_path_id: LibraryPath UUID
        db: Database session

    Returns:
        {
            'total_files': int,
            'total_size_bytes': int
        }
    """
    # Calculate aggregates from library_files table
    stats = db.query(
        func.count(LibraryFile.id).label('total_files'),
        func.coalesce(func.sum(LibraryFile.file_size_bytes), 0).label('total_size_bytes')
    ).filter(
        LibraryFile.library_path_id == library_path_id
    ).first()

    total_files = stats.total_files or 0
    total_size_bytes = stats.total_size_bytes or 0

    # Update library_path record
    db.query(LibraryPath).filter(LibraryPath.id == library_path_id).update({
        'total_files': total_files,
        'total_size_bytes': total_size_bytes,
        'last_scan_at': datetime.now(timezone.utc)
    })

    logger.info(
        f"📊 Updated library_path {library_path_id} statistics: "
        f"{total_files} files, {total_size_bytes / (1024**3):.2f} GB"
    )

    return {
        'total_files': total_files,
        'total_size_bytes': total_size_bytes
    }


@celery_app.task(name="app.tasks.fast_ingest_tasks.finalize_fast_ingestion")
def finalize_fast_ingestion(scan_job_id: str) -> Dict:
    """
    Finalize fast ingestion phase (Phase 1)

    Called after all batches complete. Updates scan job status,
    library statistics, and optionally triggers Phase 2 background processing.

    Args:
        scan_job_id: ScanJob UUID

    Returns:
        {
            'phase': str,
            'files_added': int,
            'duration_seconds': float
        }
    """
    db = SessionLocal()
    job_logger = None
    try:
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if not scan_job:
            logger.error(f"❌ Scan job {scan_job_id} not found")
            return {"error": "Scan job not found"}

        # Resume job logger if log file exists
        if scan_job.log_file_path:
            job_logger = JobLogger(job_type="scan", job_id=scan_job_id)
            # Override log file path to append to existing log
            job_logger.log_file_path = scan_job.log_file_path
            job_logger.log_info("--- Fast Ingestion Complete ---")

        # Update library path statistics (total_files, total_size_bytes)
        logger.info(f"📊 Updating library statistics for library_path {scan_job.library_path_id}")
        lib_stats = update_library_path_statistics(scan_job.library_path_id, db)
        db.commit()

        # Mark Phase 1 complete
        scan_job.status = 'completed'
        scan_job.completed_at = datetime.now(timezone.utc)

        # Update checkpoint data
        if scan_job.checkpoint_data:
            scan_job.checkpoint_data['phase'] = 'completed'
            scan_job.checkpoint_data['completed_at'] = datetime.now(timezone.utc).isoformat()

        # Calculate Phase 1 duration
        if scan_job.started_at:
            duration = (datetime.now(timezone.utc) - scan_job.started_at).total_seconds()
            scan_job.elapsed_seconds = int(duration)
        else:
            duration = 0

        # Update job_state progress to 100% if linked
        if getattr(scan_job, 'job_state_id', None):
            from app.models.job_state import JobState, JobStatus as JSStatus
            job_state = db.query(JobState).filter(JobState.id == scan_job.job_state_id).first()
            if job_state:
                job_state.progress_percent = 100.0
                job_state.status = JSStatus.COMPLETED
                job_state.items_processed = scan_job.files_scanned
                job_state.items_total = scan_job.files_scanned
                job_state.completed_at = datetime.now(timezone.utc)
                job_state.current_step = "Scan complete"
                logger.info(f"✅ Updated job_state {job_state.id} progress to 100%")

        db.commit()

        logger.info(
            f"✅ Fast ingestion complete for scan job {scan_job_id}: "
            f"{scan_job.files_added} files ingested, {scan_job.files_skipped} skipped "
            f"in {duration:.1f}s"
        )

        # Log summary to job log
        if job_logger:
            job_logger.log_info("Scan Summary:")
            job_logger.log_info(f"  Files scanned: {scan_job.files_scanned}")
            job_logger.log_info(f"  Files added: {scan_job.files_added}")
            job_logger.log_info(f"  Files updated: {scan_job.files_updated}")
            job_logger.log_info(f"  Files skipped: {scan_job.files_skipped}")
            job_logger.log_info(f"  Files failed: {scan_job.files_failed}")
            job_logger.log_info(f"  Duration: {duration:.1f} seconds")
            job_logger.log_info("Library Statistics:")
            job_logger.log_info(f"  Total files: {lib_stats.get('total_files', 0)}")
            job_logger.log_info(f"  Total size: {lib_stats.get('total_size_bytes', 0) / (1024**3):.2f} GB")
            job_logger.log_job_complete()

        # Trigger Phase 2: Background processing (metadata + images)
        logger.info(f"🚀 Triggering Phase 2 background processing...")
        from app.tasks.background_tasks import start_background_processing
        start_background_processing.delay(scan_job_id)

        # Auto-trigger library import (artist/album/track matching via MusicBrainz)
        if scan_job.files_added > 0 and scan_job.library_path_id:
            try:
                from app.models.library_import import LibraryImportJob
                from app.tasks.import_tasks import orchestrate_library_import

                # Check no import already running for this library
                active_import = db.query(LibraryImportJob).filter(
                    LibraryImportJob.library_path_id == scan_job.library_path_id,
                    LibraryImportJob.status.in_(['pending', 'running'])
                ).first()

                if not active_import:
                    import_job = LibraryImportJob(
                        library_path_id=scan_job.library_path_id,
                        status='pending',
                        auto_match_artists=True,
                        auto_assign_folders=True,
                        auto_match_tracks=True,
                        confidence_threshold=85
                    )
                    db.add(import_job)
                    db.commit()
                    db.refresh(import_job)

                    orchestrate_library_import.delay(
                        library_path_id=str(scan_job.library_path_id),
                        import_job_id=str(import_job.id),
                        config={
                            'auto_match_artists': True,
                            'auto_assign_folders': True,
                            'auto_match_tracks': True,
                            'confidence_threshold': 85,
                            'skip_scan': True,  # Files already scanned
                        }
                    )
                    logger.info(f"🚀 Auto-triggered library import {import_job.id} for library_path {scan_job.library_path_id}")
                    if job_logger:
                        job_logger.log_info(f"Auto-triggered library import: {import_job.id}")
                else:
                    logger.info(f"⏭️ Skipping auto-import - import already active: {active_import.id}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to auto-trigger library import: {e}")

        return {
            'phase': 'fast_ingestion_complete',
            'files_added': scan_job.files_added,
            'files_skipped': scan_job.files_skipped,
            'duration_seconds': duration,
            'library_stats': lib_stats
        }

    except Exception as e:
        logger.error(f"❌ Failed to finalize fast ingestion: {e}")
        if job_logger:
            job_logger.log_error(str(e))
            job_logger.log_job_complete(success=False)
        db.rollback()
        return {'error': str(e)}

    finally:
        db.close()
