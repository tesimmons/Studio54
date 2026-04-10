"""
Book Import Task
Simplified 3-phase import for audiobook libraries.

Scans files → creates Authors → creates Books & Chapters from file metadata.
No MusicBrainz dependency — purely metadata-driven.
"""

import logging
import uuid as uuid_mod
from typing import Dict, Optional
from datetime import datetime, timezone
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.library import LibraryPath, LibraryFile
from app.models.library_import import LibraryImportJob
from app.models.artist import Artist
from app.models.author import Author
from app.services.book_from_metadata import create_books_from_file_metadata
from app.tasks.scan_coordinator_v2 import walk_directory_v2
from app.services.fast_metadata_extractor import FastMetadataExtractor
from app.shared_services.job_logger import JobLogger

logger = logging.getLogger(__name__)


def _check_cancel(db: Session, import_job: LibraryImportJob) -> bool:
    """Check if cancellation was requested. Returns True if cancelled."""
    db.refresh(import_job)
    if import_job.cancel_requested:
        import_job.status = 'cancelled'
        import_job.completed_at = datetime.now(timezone.utc)
        db.commit()
        return True
    return False


@celery_app.task(
    name="app.tasks.book_import_task.orchestrate_book_import",
    soft_time_limit=43200,
    time_limit=43500,
)
def orchestrate_book_import(
    library_path_id: str,
    import_job_id: str,
) -> Dict:
    """
    Orchestrate simplified book import workflow.

    Phase 1: File Scanning — walk directory, extract metadata, store LibraryFile records
    Phase 2: Author Discovery — find unique artists, create Author records
    Phase 3: Book & Chapter Creation — group by album, create Book + Chapter records

    Args:
        library_path_id: LibraryPath UUID
        import_job_id: LibraryImportJob UUID

    Returns:
        Import result summary
    """
    db = SessionLocal()
    job_logger = None
    try:
        import_job = db.query(LibraryImportJob).filter(
            LibraryImportJob.id == UUID(import_job_id)
        ).first()

        if not import_job:
            logger.error(f"Import job not found: {import_job_id}")
            return {"error": "Import job not found"}

        if import_job.status == 'completed':
            return {"skipped": True, "reason": "already completed"}
        if import_job.status == 'running':
            return {"skipped": True, "reason": "already running"}

        library_path = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(library_path_id)
        ).first()

        if not library_path:
            import_job.status = 'failed'
            import_job.error_message = "Library path not found"
            db.commit()
            return {"error": "Library path not found"}

        # Initialize
        job_logger = JobLogger(job_type="book_import", job_id=import_job_id)
        job_logger.log_job_start("book_import", library_path.name)

        import_job.status = 'running'
        import_job.started_at = datetime.now(timezone.utc)
        import_job.log_file_path = str(job_logger.log_file_path)
        import_job.progress_percent = 0
        import_job.current_action = "Starting book import..."
        db.commit()

        # =====================================================================
        # PHASE 1: File Scanning (0-33%)
        # =====================================================================
        import_job.current_phase = 'scanning'
        import_job.phase_scanning = 'running'
        import_job.current_action = "Scanning audiobook library..."
        import_job.progress_percent = 2
        db.commit()

        job_logger.log_info(f"Phase 1: Scanning {library_path.path}")

        walk_result = walk_directory_v2(library_path.path)
        audio_files = walk_result['files']
        skip_stats = walk_result['skipped']

        job_logger.log_info(
            f"Found {len(audio_files)} audio files, skipped {skip_stats['total']}"
        )

        if not audio_files:
            import_job.status = 'completed'
            import_job.phase_scanning = 'completed'
            import_job.current_action = "No audio files found"
            import_job.progress_percent = 100
            import_job.completed_at = datetime.now(timezone.utc)
            db.commit()
            job_logger.log_job_complete()
            return {"files_found": 0, "message": "No audio files found"}

        if _check_cancel(db, import_job):
            return {"cancelled": True}

        # Extract metadata and create/update LibraryFile records
        import_job.current_action = f"Extracting metadata from {len(audio_files)} files..."
        import_job.progress_percent = 5
        db.commit()

        files_created = 0
        files_updated = 0
        BATCH_SIZE = 100

        for batch_start in range(0, len(audio_files), BATCH_SIZE):
            batch = audio_files[batch_start:batch_start + BATCH_SIZE]

            for file_path in batch:
                try:
                    # Check if file already exists in DB
                    existing = db.query(LibraryFile).filter(
                        LibraryFile.file_path == file_path,
                        LibraryFile.library_path_id == UUID(library_path_id),
                    ).first()

                    if existing:
                        files_updated += 1
                        continue

                    # Extract metadata
                    metadata = FastMetadataExtractor.extract_fast(file_path)
                    if not metadata:
                        continue

                    import os
                    file_stat = os.stat(file_path)

                    lib_file = LibraryFile(
                        library_path_id=UUID(library_path_id),
                        file_path=file_path,
                        file_name=os.path.basename(file_path),
                        file_size_bytes=file_stat.st_size,
                        file_modified_at=datetime.fromtimestamp(
                            file_stat.st_mtime, tz=timezone.utc
                        ),
                        format=metadata.get('format', '').upper() or None,
                        title=metadata.get('title'),
                        artist=metadata.get('artist'),
                        album_artist=metadata.get('album_artist'),
                        album=metadata.get('album'),
                        track_number=metadata.get('track_number'),
                        disc_number=metadata.get('disc_number'),
                        year=metadata.get('year'),
                        duration_seconds=metadata.get('duration'),
                        musicbrainz_trackid=metadata.get('musicbrainz_trackid'),
                        musicbrainz_albumid=metadata.get('musicbrainz_albumid'),
                        musicbrainz_artistid=metadata.get('musicbrainz_artistid'),
                    )
                    db.add(lib_file)
                    files_created += 1

                except Exception as e:
                    logger.warning(f"Failed to process file {file_path}: {e}")
                    continue

            db.commit()

            # Update progress (Phase 1: 5-30%)
            progress = 5 + (batch_start / len(audio_files)) * 25
            import_job.progress_percent = min(progress, 30)
            import_job.files_scanned = files_created + files_updated
            import_job.current_action = (
                f"Scanned {files_created + files_updated}/{len(audio_files)} files..."
            )
            db.commit()

            if _check_cancel(db, import_job):
                return {"cancelled": True}

        import_job.files_scanned = files_created + files_updated
        import_job.phase_scanning = 'completed'
        import_job.progress_percent = 33
        db.commit()

        job_logger.log_info(
            f"Phase 1 complete: {files_created} new files, {files_updated} existing"
        )

        # =====================================================================
        # PHASE 2: Author Discovery & Creation (33-66%)
        # =====================================================================
        import_job.current_phase = 'artist_matching'
        import_job.phase_artist_matching = 'running'
        import_job.current_action = "Discovering authors from file metadata..."
        import_job.progress_percent = 35
        db.commit()

        job_logger.log_info("Phase 2: Author discovery")

        # Get unique artist names from library files
        artist_query = db.query(
            func.coalesce(LibraryFile.album_artist, LibraryFile.artist).label('artist_name'),
            func.count(LibraryFile.id).label('file_count'),
        ).filter(
            LibraryFile.library_path_id == UUID(library_path_id),
            func.coalesce(LibraryFile.album_artist, LibraryFile.artist).isnot(None),
        ).group_by(
            func.coalesce(LibraryFile.album_artist, LibraryFile.artist)
        ).all()

        unique_artists = [
            {"name": row.artist_name, "file_count": row.file_count}
            for row in artist_query
            if row.artist_name and row.artist_name.strip()
        ]

        import_job.artists_found = len(unique_artists)
        db.commit()

        job_logger.log_info(f"Found {len(unique_artists)} unique authors")

        authors_created = 0
        authors_existing = 0

        for idx, artist_info in enumerate(unique_artists):
            artist_name = artist_info['name'].strip()

            if _check_cancel(db, import_job):
                return {"cancelled": True}

            # Check if Author already exists (by name, case-insensitive)
            existing_author = db.query(Author).filter(
                func.lower(Author.name) == artist_name.lower()
            ).first()

            if existing_author:
                authors_existing += 1
                job_logger.log_info(f"Author already exists: {artist_name}")
            else:
                try:
                    # Check if there's a matching Artist record
                    existing_artist = db.query(Artist).filter(
                        func.lower(Artist.name) == artist_name.lower()
                    ).first()

                    if existing_artist:
                        # Create Author from existing Artist
                        new_author = Author(
                            id=existing_artist.id,
                            name=existing_artist.name,
                            musicbrainz_id=existing_artist.musicbrainz_id,
                            is_monitored=False,
                            import_source='studio54',
                            studio54_library_path_id=UUID(library_path_id),
                        )
                    else:
                        # Create new Author with local MBID
                        local_mbid = f"local-{uuid_mod.uuid4()}"

                        # Also create a matching Artist record (cross-reference)
                        new_artist = Artist(
                            name=artist_name,
                            musicbrainz_id=local_mbid,
                            is_monitored=False,
                        )
                        db.add(new_artist)
                        db.flush()

                        new_author = Author(
                            id=new_artist.id,
                            name=artist_name,
                            musicbrainz_id=local_mbid,
                            is_monitored=False,
                            import_source='studio54',
                            studio54_library_path_id=UUID(library_path_id),
                        )

                    db.add(new_author)
                    db.commit()
                    authors_created += 1
                    job_logger.log_info(f"Created author: {artist_name}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"Failed to create author '{artist_name}': {e}")
                    job_logger.log_error(f"Failed to create author '{artist_name}': {e}")

            # Update progress (Phase 2: 35-63%)
            progress = 35 + ((idx + 1) / len(unique_artists)) * 28
            import_job.progress_percent = min(progress, 63)
            import_job.artists_created = authors_created
            import_job.artists_matched = authors_existing
            import_job.current_action = (
                f"Processing author {idx + 1}/{len(unique_artists)}: {artist_name}"
            )
            db.commit()

        import_job.phase_artist_matching = 'completed'
        import_job.progress_percent = 66
        db.commit()

        job_logger.log_info(
            f"Phase 2 complete: {authors_created} created, {authors_existing} existing"
        )

        # =====================================================================
        # PHASE 3: Book & Chapter Creation (66-100%)
        # =====================================================================
        import_job.current_phase = 'finalization'
        import_job.phase_finalization = 'running'
        import_job.current_action = "Creating books and chapters from metadata..."
        import_job.progress_percent = 68
        db.commit()

        job_logger.log_info("Phase 3: Book & chapter creation")

        # Get all authors for this library path
        authors = db.query(Author).filter(
            Author.studio54_library_path_id == UUID(library_path_id)
        ).all()

        # Also include authors matched by name to files in this library
        if not authors:
            # Fallback: get authors by matching names in unique_artists
            author_names = [a['name'].strip().lower() for a in unique_artists]
            authors = db.query(Author).filter(
                func.lower(Author.name).in_(author_names)
            ).all()

        total_books_created = 0
        total_chapters_created = 0
        total_files_matched = 0

        for idx, author in enumerate(authors):
            if _check_cancel(db, import_job):
                return {"cancelled": True}

            import_job.current_action = (
                f"Creating books for {author.name} ({idx + 1}/{len(authors)})..."
            )
            db.commit()

            try:
                stats = create_books_from_file_metadata(
                    db=db,
                    author_id=author.id,
                    library_path_id=UUID(library_path_id),
                )
                total_books_created += stats.get('books_created', 0)
                total_chapters_created += stats.get('chapters_created', 0)
                total_files_matched += stats.get('files_matched', 0)

                if stats.get('books_created', 0) > 0:
                    job_logger.log_info(
                        f"  {author.name}: {stats['books_created']} books, "
                        f"{stats['chapters_created']} chapters"
                    )

            except Exception as e:
                logger.error(f"Error creating books for {author.name}: {e}")
                job_logger.log_error(
                    f"Failed to create books for {author.name}: {e}"
                )
                continue

            # Update progress (Phase 3: 68-98%)
            progress = 68 + ((idx + 1) / max(len(authors), 1)) * 30
            import_job.progress_percent = min(progress, 98)
            import_job.albums_synced = total_books_created
            import_job.tracks_matched = total_chapters_created
            db.commit()

        # =====================================================================
        # Auto-detect series from file metadata
        # =====================================================================
        job_logger.log_info("Detecting series from file metadata...")
        from app.services.book_from_metadata import detect_and_create_series

        for author in authors:
            try:
                series_stats = detect_and_create_series(db, author.id)
                if series_stats.get('series_created', 0) > 0:
                    job_logger.log_info(
                        f"  {author.name}: {series_stats['series_created']} series detected, "
                        f"{series_stats['books_linked']} books linked"
                    )
            except Exception as e:
                logger.warning(f"Series detection failed for {author.name}: {e}")

        # =====================================================================
        # Auto-create series playlists for any series with new books
        # =====================================================================
        try:
            from app.models.book import Book as BookModel
            from app.tasks.playlist_tasks import create_series_playlist_task

            series_ids = db.query(BookModel.series_id).filter(
                BookModel.series_id.isnot(None),
                BookModel.author_id.in_([a.id for a in authors])
            ).distinct().all()

            for (sid,) in series_ids:
                create_series_playlist_task.delay(str(sid))
                logger.info(f"Dispatched series playlist creation for series {sid}")
        except Exception as e:
            logger.warning(f"Failed to dispatch series playlist tasks: {e}")

        # =====================================================================
        # Finalization
        # =====================================================================
        import_job.status = 'completed'
        import_job.phase_finalization = 'completed'
        import_job.progress_percent = 100
        import_job.current_action = "Book import complete"
        import_job.completed_at = datetime.now(timezone.utc)
        db.commit()

        summary = {
            "files_scanned": import_job.files_scanned,
            "authors_found": len(unique_artists),
            "authors_created": authors_created,
            "books_created": total_books_created,
            "chapters_created": total_chapters_created,
            "files_matched": total_files_matched,
        }

        job_logger.log_info(f"Book import complete: {summary}")
        job_logger.log_job_complete()

        logger.info(f"Book import {import_job_id} completed: {summary}")
        return summary

    except SoftTimeLimitExceeded:
        logger.error(f"Book import {import_job_id} hit time limit")
        if import_job:
            import_job.status = 'failed'
            import_job.error_message = (
                f"Time limit exceeded during {import_job.current_phase}. "
                f"Re-run to resume from where it left off."
            )
            import_job.completed_at = datetime.now(timezone.utc)
            db.commit()
        return {"error": "Time limit exceeded"}

    except Exception as e:
        import traceback
        logger.error(f"Book import {import_job_id} failed: {e}\n{traceback.format_exc()}")
        if import_job:
            import_job.status = 'failed'
            import_job.error_message = str(e)
            import_job.completed_at = datetime.now(timezone.utc)
            db.commit()
        if job_logger:
            job_logger.log_error(f"Book import failed: {e}")
        return {"error": str(e)}

    finally:
        db.close()
