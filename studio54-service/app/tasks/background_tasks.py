"""
Background Processing Tasks - Phase 2 of Two-Phase Scan (V2 Scanner)

Runs in the background after Phase 1 completes to extract full metadata,
fetch images, and calculate hashes. Files are already searchable during this phase.

Based on MUSE V2 background processing implementation.
"""

import os
import logging
from typing import List, Dict, Optional
from datetime import datetime, timezone
from uuid import UUID

from celery import group
from sqlalchemy.orm import Session
from sqlalchemy import update

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.library import LibraryPath, LibraryFile, ScanJob
from app.services.metadata_extractor import MetadataExtractor
from app.services.musicbrainz_images import MusicBrainzImageFetcher

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.background_tasks.index_metadata_batch")
def index_metadata_batch(
    library_path_id: str,
    file_ids: List[str],
    batch_number: int,
    total_batches: int
) -> Dict:
    """
    Extract full metadata for a batch of files (Phase 2)

    Updates existing records with:
    - Full tags (album_artist, track_number, disc_number, year, genre)
    - Audio quality (bitrate_kbps, sample_rate_hz)
    - MusicBrainz IDs (all 4 types)
    - Embedded artwork detection
    - Raw metadata JSON

    Args:
        library_path_id: LibraryPath UUID
        file_ids: List of LibraryFile UUIDs to process
        batch_number: Current batch number (1-indexed)
        total_batches: Total number of batches

    Returns:
        {
            'batch_number': int,
            'files_processed': int,
            'files_updated': int,
            'errors': int
        }
    """
    import time
    batch_start_time = time.time()

    logger.info(
        f"📇 index_metadata_batch ENTRY: batch {batch_number}/{total_batches}, "
        f"received {len(file_ids)} files"
    )

    db = SessionLocal()
    extractor = MetadataExtractor()

    try:
        files_processed = 0
        files_updated = 0
        errors = 0

        # Process each file
        for file_id in file_ids:
            try:
                # Get file record
                library_file = db.query(LibraryFile).filter(
                    LibraryFile.id == UUID(file_id)
                ).first()

                if not library_file:
                    logger.warning(f"File {file_id} not found")
                    errors += 1
                    continue

                # Skip if file doesn't exist on disk
                if not os.path.exists(library_file.file_path):
                    logger.warning(f"File not found on disk: {library_file.file_path}")
                    errors += 1
                    continue

                # Extract full metadata
                metadata = extractor.extract(library_file.file_path)

                # Update record with full metadata
                library_file.album_artist = metadata.get('album_artist')
                library_file.track_number = metadata.get('track_number')
                library_file.disc_number = metadata.get('disc_number')
                library_file.year = metadata.get('year')
                library_file.genre = metadata.get('genre')
                library_file.bitrate_kbps = metadata.get('bitrate_kbps')
                library_file.sample_rate_hz = metadata.get('sample_rate_hz')
                library_file.musicbrainz_trackid = metadata.get('musicbrainz_trackid')
                library_file.musicbrainz_albumid = metadata.get('musicbrainz_albumid')
                library_file.musicbrainz_artistid = metadata.get('musicbrainz_artistid')
                library_file.musicbrainz_releasegroupid = metadata.get('musicbrainz_releasegroupid')
                library_file.has_embedded_artwork = metadata.get('has_embedded_artwork', False)
                library_file.metadata_json = metadata.get('metadata_json')
                library_file.updated_at = datetime.now(timezone.utc)

                files_updated += 1
                files_processed += 1

            except Exception as e:
                logger.error(f"❌ Error processing file {file_id}: {e}")
                errors += 1
                continue

        # Commit batch
        try:
            db.commit()

            # Calculate performance metrics
            batch_duration = time.time() - batch_start_time
            files_per_second = files_processed / batch_duration if batch_duration > 0 else 0

            logger.info(
                f"✅ Metadata batch {batch_number}/{total_batches} complete: "
                f"{files_updated} files updated, {errors} errors "
                f"({batch_duration:.1f}s @ {files_per_second:.1f} files/sec)"
            )
        except Exception as commit_error:
            logger.error(f"❌ Batch commit failed: {commit_error}")
            db.rollback()
            raise

        return {
            'batch_number': batch_number,
            'files_processed': files_processed,
            'files_updated': files_updated,
            'errors': errors
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ Metadata batch {batch_number} failed: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        db.rollback()
        return {
            'batch_number': batch_number,
            'files_processed': 0,
            'files_updated': 0,
            'error': str(e)
        }

    finally:
        db.close()


@celery_app.task(name="app.tasks.background_tasks.fetch_images_batch")
def fetch_images_batch(
    library_path_id: str,
    file_ids: List[str],
    batch_number: int,
    total_batches: int,
    fanart_api_key: Optional[str] = None
) -> Dict:
    """
    Fetch album art and artist images for a batch of files (Phase 2)

    Args:
        library_path_id: LibraryPath UUID
        file_ids: List of LibraryFile UUIDs to process
        batch_number: Current batch number (1-indexed)
        total_batches: Total number of batches
        fanart_api_key: Optional Fanart.tv API key

    Returns:
        {
            'batch_number': int,
            'files_processed': int,
            'album_art_fetched': int,
            'artist_images_fetched': int,
            'errors': int
        }
    """
    import time
    batch_start_time = time.time()

    logger.info(
        f"🖼️  fetch_images_batch ENTRY: batch {batch_number}/{total_batches}, "
        f"received {len(file_ids)} files"
    )

    db = SessionLocal()
    image_fetcher = MusicBrainzImageFetcher(fanart_api_key=fanart_api_key)

    try:
        files_processed = 0
        album_art_fetched = 0
        artist_images_fetched = 0
        errors = 0

        # Process each file
        for file_id in file_ids:
            try:
                # Get file record
                library_file = db.query(LibraryFile).filter(
                    LibraryFile.id == UUID(file_id)
                ).first()

                if not library_file:
                    logger.warning(f"File {file_id} not found")
                    errors += 1
                    continue

                # Fetch album art if not already fetched and has MusicBrainz album ID
                if not library_file.album_art_fetched and library_file.musicbrainz_albumid:
                    try:
                        album_art_url = image_fetcher.fetch_album_art_sync(
                            library_file.musicbrainz_albumid
                        )
                        if album_art_url:
                            library_file.album_art_url = album_art_url
                            album_art_fetched += 1

                        library_file.album_art_fetched = True
                    except Exception as e:
                        logger.error(f"Error fetching album art for {library_file.file_path}: {e}")

                # Fetch artist image if not already fetched and has MusicBrainz artist ID
                if not library_file.artist_image_fetched and library_file.musicbrainz_artistid:
                    try:
                        artist_image_url = image_fetcher.fetch_artist_image_sync(
                            library_file.musicbrainz_artistid
                        )
                        if artist_image_url:
                            library_file.artist_image_url = artist_image_url
                            artist_images_fetched += 1

                        library_file.artist_image_fetched = True
                    except Exception as e:
                        logger.error(f"Error fetching artist image for {library_file.file_path}: {e}")

                library_file.updated_at = datetime.now(timezone.utc)
                files_processed += 1

            except Exception as e:
                logger.error(f"❌ Error processing file {file_id}: {e}")
                errors += 1
                continue

        # Commit batch
        try:
            db.commit()

            # Calculate performance metrics
            batch_duration = time.time() - batch_start_time
            files_per_second = files_processed / batch_duration if batch_duration > 0 else 0

            logger.info(
                f"✅ Images batch {batch_number}/{total_batches} complete: "
                f"{album_art_fetched} album art, {artist_images_fetched} artist images, {errors} errors "
                f"({batch_duration:.1f}s @ {files_per_second:.1f} files/sec)"
            )
        except Exception as commit_error:
            logger.error(f"❌ Batch commit failed: {commit_error}")
            db.rollback()
            raise

        return {
            'batch_number': batch_number,
            'files_processed': files_processed,
            'album_art_fetched': album_art_fetched,
            'artist_images_fetched': artist_images_fetched,
            'errors': errors
        }

    except Exception as e:
        import traceback
        logger.error(f"❌ Images batch {batch_number} failed: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        db.rollback()
        return {
            'batch_number': batch_number,
            'files_processed': 0,
            'album_art_fetched': 0,
            'artist_images_fetched': 0,
            'error': str(e)
        }

    finally:
        db.close()


@celery_app.task(name="app.tasks.background_tasks.start_background_processing")
def start_background_processing(
    scan_job_id: str,
    batch_size: int = 100,
    fanart_api_key: Optional[str] = None
) -> Dict:
    """
    Start Phase 2 background processing for a scan job

    Runs two parallel job streams:
    1. Metadata indexing (extract full metadata)
    2. Image fetching (album art + artist images)

    Args:
        scan_job_id: ScanJob UUID
        batch_size: Files per batch (default: 100)
        fanart_api_key: Optional Fanart.tv API key

    Returns:
        {
            'scan_job_id': str,
            'total_files': int,
            'metadata_batches': int,
            'image_batches': int
        }
    """
    db = SessionLocal()

    try:
        logger.info(f"🚀 Starting background processing for scan job {scan_job_id}")

        # Get scan job
        scan_job = db.query(ScanJob).filter(ScanJob.id == UUID(scan_job_id)).first()
        if not scan_job:
            logger.error(f"❌ Scan job {scan_job_id} not found")
            return {"error": "Scan job not found"}

        # Get all files for this library path that need processing
        files = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == scan_job.library_path_id
        ).all()

        if not files:
            logger.warning(f"No files found for library_path {scan_job.library_path_id}")
            return {
                'scan_job_id': scan_job_id,
                'total_files': 0,
                'metadata_batches': 0,
                'image_batches': 0
            }

        file_ids = [str(f.id) for f in files]
        total_files = len(file_ids)

        logger.info(f"📊 Found {total_files} files for background processing")

        # Split into batches
        batches = []
        for i in range(0, len(file_ids), batch_size):
            batch = file_ids[i:i + batch_size]
            batches.append(batch)

        total_batches = len(batches)

        # Create metadata indexing tasks
        metadata_tasks = []
        for batch_number, batch_ids in enumerate(batches, start=1):
            task = index_metadata_batch.s(
                library_path_id=str(scan_job.library_path_id),
                file_ids=batch_ids,
                batch_number=batch_number,
                total_batches=total_batches
            )
            metadata_tasks.append(task)

        # Create image fetching tasks
        image_tasks = []
        for batch_number, batch_ids in enumerate(batches, start=1):
            task = fetch_images_batch.s(
                library_path_id=str(scan_job.library_path_id),
                file_ids=batch_ids,
                batch_number=batch_number,
                total_batches=total_batches,
                fanart_api_key=fanart_api_key
            )
            image_tasks.append(task)

        # Execute both job streams in parallel
        metadata_group = group(metadata_tasks)
        image_group = group(image_tasks)

        metadata_result = metadata_group.apply_async()
        image_result = image_group.apply_async()

        logger.info(
            f"✅ Background processing started: "
            f"{total_batches} metadata batches, {total_batches} image batches"
        )

        return {
            'scan_job_id': scan_job_id,
            'total_files': total_files,
            'metadata_batches': total_batches,
            'image_batches': total_batches,
            'metadata_group_id': metadata_result.id,
            'image_group_id': image_result.id
        }

    except Exception as e:
        logger.error(f"❌ Failed to start background processing: {e}")
        return {'error': str(e)}

    finally:
        db.close()
