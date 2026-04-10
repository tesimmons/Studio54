"""
Library Import Tasks
Orchestrates complete library import workflow

Supports:
- Parallel Phase 3 via chord-based batch dispatch (sync_import_batch)
- Pause/resume at any phase via checkpoint manager
- Resume from failed/paused state (skips already-completed work)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from uuid import UUID

from celery import chord
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.library import LibraryPath, LibraryFile
from app.models.library_import import LibraryImportJob, LibraryArtistMatch
from app.models.artist import Artist
from app.services.artist_import_service import ArtistImportService
from app.tasks.scan_coordinator_v2 import scan_library_v2
from app.tasks.sync_tasks import sync_artist_albums
from app.services.album_file_matcher import AlbumFileMatcher
from app.services.mbid_file_matcher import MBIDFileMatcher
from app.services.book_file_matcher import BookFileMatcher
from app.shared_services.job_logger import JobLogger
from app.services.job_checkpoint_manager import JobCheckpointManager

logger = logging.getLogger(__name__)

# Batch size for parallel Phase 3 sync
SYNC_BATCH_SIZE = 50


@celery_app.task(
    name="app.tasks.import_tasks.orchestrate_library_import",
    soft_time_limit=43200,   # 12 hours soft limit
    time_limit=43500,        # 12 hours + 5 min hard limit
)
def orchestrate_library_import(
    library_path_id: str,
    import_job_id: str,
    config: Optional[Dict] = None
) -> Dict:
    """
    Orchestrate complete library import workflow

    Phases:
    1. File Scanning - Walk directory and extract metadata
    2. Artist Matching - Match library artists to Studio54/MusicBrainz
    3. Metadata Sync - Download artist/album/track data from MusicBrainz
    4. Folder Matching - Match directory structure to albums
    5. Track Matching - Match audio files to tracks via MBID
    6. Finalization - Calculate statistics and mark complete

    Args:
        library_path_id: LibraryPath UUID
        import_job_id: LibraryImportJob UUID
        config: Import configuration dict

    Returns:
        Import result summary
    """
    db = SessionLocal()
    job_logger = None
    try:
        logger.info(f"🚀 Starting library import: {import_job_id}")

        # Get import job
        import_job = db.query(LibraryImportJob).filter(
            LibraryImportJob.id == UUID(import_job_id)
        ).first()

        if not import_job:
            logger.error(f"Import job not found: {import_job_id}")
            return {"error": "Import job not found"}

        # Guard against duplicate runs
        if import_job.status == 'completed':
            logger.warning(f"Import job {import_job_id} already completed, skipping")
            return {"skipped": True, "reason": "already completed"}
        if import_job.status == 'running':
            logger.warning(f"Import job {import_job_id} already running, skipping")
            return {"skipped": True, "reason": "already running"}

        # Get library path for logging
        library_path = db.query(LibraryPath).filter(
            LibraryPath.id == UUID(library_path_id)
        ).first()
        library_name = library_path.name if library_path else library_path_id

        # Detect resume from a previous failed or paused run
        is_resume = import_job.status in ('failed', 'paused')
        resume_phase = import_job.current_phase if is_resume else None

        # Initialize checkpoint manager for pause/resume support
        checkpoint_mgr = JobCheckpointManager(import_job_id)

        # Initialize job logger for comprehensive activity tracking
        job_logger = JobLogger(job_type="import", job_id=import_job_id)
        if is_resume and import_job.log_file_path:
            # Append to existing log file
            job_logger.log_file_path = import_job.log_file_path
            job_logger._write_entry("")
            job_logger._write_entry("=" * 80)
            job_logger._write_entry(f"RESUMING IMPORT (previous phase: {resume_phase})")
            job_logger._write_entry("=" * 80)
            logger.info(f"Resuming import job {import_job_id} from phase: {resume_phase}")
        else:
            job_logger.log_job_start("import", library_name)
            if library_path:
                job_logger.log_info(f"Library Path: {library_path.path}")

        # Save log file path to import job
        import_job.log_file_path = str(job_logger.log_file_path)

        # Update job status
        import_job.status = 'running'
        import_job.error_message = None
        if not is_resume:
            import_job.started_at = datetime.now(timezone.utc)
        import_job.current_phase = 'scanning'
        import_job.phase_scanning = 'running'
        db.commit()

        # Get configuration
        config = config or {}
        auto_match_artists = config.get('auto_match_artists', import_job.auto_match_artists)
        auto_assign_folders = config.get('auto_assign_folders', import_job.auto_assign_folders)
        auto_match_tracks = config.get('auto_match_tracks', import_job.auto_match_tracks)
        confidence_threshold = config.get('confidence_threshold', import_job.confidence_threshold)

        # Determine library type from library path
        library_type = getattr(library_path, 'library_type', 'music') if library_path else 'music'
        library_type = config.get('library_type', library_type)
        is_audiobook = library_type == 'audiobook'
        if is_audiobook:
            job_logger.log_info(f"Library type: audiobook (Reading Room)")
            logger.info(f"📚 Audiobook library import mode")

        # -------------------------------------------------------------------
        # PHASE 1: File Scanning
        # -------------------------------------------------------------------
        skip_scan = config.get('skip_scan', False)

        if skip_scan:
            # Files already scanned - just count existing library files
            from sqlalchemy import func
            files_count = db.query(func.count(LibraryFile.id)).filter(
                LibraryFile.library_path_id == UUID(library_path_id)
            ).scalar() or 0

            logger.info(f"📂 Phase 1: Skipping scan (already scanned, {files_count} files)")
            job_logger.log_import_phase_start("file_scanning")
            job_logger.log_info(f"Using existing scan results - {files_count} files already indexed")

            import_job.files_scanned = files_count
            import_job.phase_scanning = 'completed'
            import_job.progress_percent = 15.0
            import_job.current_action = f"Using {files_count} previously scanned files"
            db.commit()

            job_logger.stats.files_total = files_count
            logger.info(f"✅ Using existing scan: {files_count} files indexed")
        else:
            logger.info("📂 Phase 1: File Scanning")
            job_logger.log_import_phase_start("file_scanning")
            import_job.current_action = "Scanning library files..."
            import_job.progress_percent = 5.0
            db.commit()

            # Use existing scan_library_v2 task (synchronously)
            from app.models.library import ScanJob

            # Create scan job
            scan_job = ScanJob(
                library_path_id=UUID(library_path_id),
                status='pending'
            )
            db.add(scan_job)
            db.commit()

            # Run scan
            scan_result = scan_library_v2(
                library_path_id=library_path_id,
                scan_job_id=str(scan_job.id),
                incremental=False,
                batch_size=100
            )

            if 'error' in scan_result:
                job_logger.log_error(f"File scanning failed: {scan_result['error']}")
                raise Exception(f"File scanning failed: {scan_result['error']}")

            import_job.files_scanned = scan_result.get('total_files', 0)
            import_job.phase_scanning = 'completed'
            import_job.progress_percent = 15.0
            db.commit()

            job_logger.stats.files_total = import_job.files_scanned
            job_logger.log_info(f"Phase 1 complete: {import_job.files_scanned} files indexed")
            logger.info(f"✅ Scanning complete: {import_job.files_scanned} files indexed")

        # -------------------------------------------------------------------
        # PHASE 2: Artist Matching
        # -------------------------------------------------------------------
        logger.info("🎤 Phase 2: Artist Matching")
        job_logger.log_import_phase_start("artist_matching")
        import_job.current_phase = 'artist_matching'
        import_job.phase_artist_matching = 'running'
        import_job.current_action = "Matching artists..."
        import_job.progress_percent = 20.0
        db.commit()

        artist_service = ArtistImportService(db)

        # Get unique artists from library
        library_artists = artist_service.get_library_artists(library_path_id)

        # On resume, skip artists already matched in a previous run
        already_matched_names = set()
        if is_resume:
            existing_matches = db.query(LibraryArtistMatch.library_artist_name).filter(
                LibraryArtistMatch.import_job_id == UUID(import_job_id),
                LibraryArtistMatch.status == 'matched'
            ).all()
            already_matched_names = {m[0] for m in existing_matches}
            if already_matched_names:
                job_logger.log_info(f"Resume: skipping {len(already_matched_names)} already-matched artists")

        # Reset counters on fresh run, keep on resume
        if not is_resume:
            import_job.artists_found = len(library_artists)
            import_job.artists_matched = 0
            import_job.artists_created = 0
            import_job.artists_pending = 0
        else:
            import_job.artists_found = len(library_artists)
        db.commit()

        job_logger.stats.artists_found = len(library_artists)
        job_logger.log_info(f"Found {len(library_artists)} unique artists")
        logger.info(f"Found {len(library_artists)} unique artists")

        matched_artists = []
        newly_created_ids = set()

        # On resume, pre-populate matched_artists from previous run
        if is_resume and already_matched_names:
            existing_artist_ids = db.query(LibraryArtistMatch.matched_artist_id).filter(
                LibraryArtistMatch.import_job_id == UUID(import_job_id),
                LibraryArtistMatch.status == 'matched',
                LibraryArtistMatch.matched_artist_id.isnot(None)
            ).distinct().all()
            for (aid,) in existing_artist_ids:
                artist_obj = db.query(Artist).filter(Artist.id == aid).first()
                if artist_obj:
                    matched_artists.append(artist_obj)

        for idx, lib_artist in enumerate(library_artists):
            # Skip already-matched artists on resume
            if lib_artist['name'] in already_matched_names:
                continue

            # Check for cancellation or pause
            db.refresh(import_job)
            if import_job.cancel_requested:
                logger.info("Import cancelled by user")
                import_job.status = 'cancelled'
                import_job.completed_at = datetime.now(timezone.utc)
                db.commit()
                return {"cancelled": True}

            if import_job.pause_requested or checkpoint_mgr.is_pause_requested():
                logger.info("Import paused by user during artist matching")
                import_job.status = 'paused'
                import_job.pause_requested = False
                db.commit()
                checkpoint_mgr.clear_pause_request()
                job_logger.log_info(f"Paused during artist matching at {idx}/{len(library_artists)}")
                return {"paused": True, "phase": "artist_matching", "progress": idx}

            # Update progress
            progress = 20.0 + (idx / len(library_artists)) * 20.0  # 20% to 40%
            import_job.progress_percent = progress
            import_job.current_action = f"Matching artist {idx+1}/{len(library_artists)}: {lib_artist['name']}"
            db.commit()

            # Match artist
            matched_artist, match_record = artist_service.match_library_artist(
                lib_artist,
                confidence_threshold=confidence_threshold,
                auto_create=auto_match_artists
            )

            # Link match record to import job
            match_record.import_job_id = UUID(import_job_id)
            db.add(match_record)

            if matched_artist:
                matched_artists.append(matched_artist)
                import_job.artists_matched += 1
                # Track newly created vs matched to existing
                if matched_artist.id not in newly_created_ids:
                    # Check if this was a pre-existing artist (added before this import started)
                    if hasattr(matched_artist, 'added_at') and matched_artist.added_at and import_job.started_at:
                        if matched_artist.added_at >= import_job.started_at:
                            import_job.artists_created += 1
                            newly_created_ids.add(matched_artist.id)
                    else:
                        # No added_at — assume newly created if match_record was just created
                        import_job.artists_created += 1
                        newly_created_ids.add(matched_artist.id)
            elif is_audiobook:
                # For audiobooks, create a local artist even without MusicBrainz match.
                # Audiobook authors often aren't in MusicBrainz, but we still need
                # Artist records to anchor Book/Chapter creation from file metadata.
                import uuid as uuid_mod
                local_mbid = f"local-{uuid_mod.uuid4()}"
                try:
                    local_artist = Artist(
                        name=lib_artist['name'],
                        musicbrainz_id=local_mbid,
                        is_monitored=False,
                    )
                    db.add(local_artist)
                    db.flush()

                    # Update match record
                    match_record.status = 'matched'
                    match_record.matched_artist_id = local_artist.id
                    match_record.musicbrainz_id = local_mbid
                    match_record.confidence_score = 0.0

                    matched_artists.append(local_artist)
                    import_job.artists_matched += 1
                    import_job.artists_created += 1
                    newly_created_ids.add(local_artist.id)

                    job_logger.log_info(
                        f"  Created local author: {lib_artist['name']} (no MusicBrainz match)"
                    )
                    logger.info(f"Created local audiobook author: {lib_artist['name']}")
                except Exception as e:
                    logger.error(f"Failed to create local author {lib_artist['name']}: {e}")
                    import_job.artists_pending += 1
            else:
                import_job.artists_pending += 1

            db.commit()

            # Log with rejection reason for failures
            if matched_artist:
                job_logger.log_import_match(
                    item_type="artist",
                    local_name=lib_artist['name'],
                    matched_name=matched_artist.name,
                    confidence=float(match_record.confidence_score or 0),
                    auto_matched=match_record.status == 'auto_matched'
                )
            else:
                reason = getattr(match_record, 'rejection_reason', None) or match_record.status
                job_logger.log_import_match(
                    item_type="artist",
                    local_name=lib_artist['name'],
                    matched_name=None,
                    confidence=float(match_record.confidence_score or 0),
                )
                # Log failure reason
                if reason:
                    job_logger._write_entry(f"  Reason: {reason}")
                # Log sample file paths for debugging
                sample_paths = lib_artist.get('sample_file_paths', [])
                if sample_paths:
                    job_logger._write_entry(f"  Files: {sample_paths[0]}")

            logger.info(
                f"Artist {idx+1}/{len(library_artists)}: {lib_artist['name']} - "
                f"Status: {match_record.status}, Confidence: {match_record.confidence_score}%"
            )

        import_job.phase_artist_matching = 'completed'
        import_job.progress_percent = 40.0
        db.commit()

        job_logger.stats.artists_matched = import_job.artists_matched
        job_logger.stats.artists_created = import_job.artists_created
        job_logger.log_info(f"\nPhase 2 complete:")
        job_logger.log_info(f"  Artists matched: {import_job.artists_matched}")
        job_logger.log_info(f"  Artists created: {import_job.artists_created}")
        job_logger.log_info(f"  Artists pending: {import_job.artists_pending}")
        logger.info(
            f"✅ Artist matching complete: {import_job.artists_matched} matched, "
            f"{import_job.artists_created} created, {import_job.artists_pending} pending"
        )

        # -------------------------------------------------------------------
        # PHASE 3: Metadata Sync + Rapid MBID File Matching
        # -------------------------------------------------------------------
        logger.info("📚 Phase 3: Metadata Sync + Rapid MBID Matching")
        job_logger.log_import_phase_start("metadata_sync")
        import_job.current_phase = 'metadata_sync'
        import_job.phase_metadata_sync = 'running'
        import_job.current_action = "Syncing artist metadata..."
        import_job.progress_percent = 45.0
        db.commit()

        # For audiobook libraries, ensure Author records exist for each matched Artist.
        # Phase 2 creates Artist records, but audiobook sync needs Author records.
        if is_audiobook and matched_artists:
            from app.models.author import Author
            authors_created = 0
            for artist in matched_artists:
                existing_author = db.query(Author).filter(
                    Author.musicbrainz_id == artist.musicbrainz_id
                ).first()
                if not existing_author:
                    # Also check by name to avoid duplicates
                    existing_author = db.query(Author).filter(
                        Author.name == artist.name
                    ).first()
                if not existing_author:
                    new_author = Author(
                        id=artist.id,  # Use same UUID for easy cross-reference
                        name=artist.name,
                        musicbrainz_id=artist.musicbrainz_id,
                        is_monitored=False,
                        root_folder_path=artist.root_folder_path,
                        import_source='studio54',
                        studio54_library_path_id=UUID(library_path_id),
                    )
                    db.add(new_author)
                    authors_created += 1
            if authors_created > 0:
                db.commit()
                logger.info(f"📖 Created {authors_created} Author records for audiobook import")
                job_logger.log_info(f"Created {authors_created} Author records from matched artists")

        # Initialize MBID matcher
        mbid_matcher = MBIDFileMatcher(db)

        # Sync each matched artist/author
        from app.models.album import Album
        from app.tasks.sync_tasks import sync_artist_albums_standalone
        if is_audiobook:
            from app.tasks.sync_tasks import sync_author_books_standalone

        artists_skipped_sync = 0
        for idx, artist in enumerate(matched_artists):
            # Check for cancellation or pause
            db.refresh(import_job)
            if import_job.cancel_requested:
                logger.info("Import cancelled by user")
                import_job.status = 'cancelled'
                import_job.completed_at = datetime.now(timezone.utc)
                db.commit()
                return {"cancelled": True}

            if import_job.pause_requested or checkpoint_mgr.is_pause_requested():
                logger.info("Import paused by user during metadata sync")
                import_job.status = 'paused'
                import_job.pause_requested = False
                db.commit()
                checkpoint_mgr.clear_pause_request()
                job_logger.log_info(f"Paused during metadata sync at {idx}/{len(matched_artists)}")
                return {"paused": True, "phase": "metadata_sync", "progress": idx}

            # Update progress
            progress = 45.0 + (idx / len(matched_artists)) * 25.0  # 45% to 70%
            import_job.progress_percent = progress
            import_job.current_action = f"Syncing {idx+1}/{len(matched_artists)}: {artist.name}"
            db.commit()

            try:
                # Skip local-only artists (no real MusicBrainz ID) — they'll be
                # handled by Phase 3a metadata-based book creation
                if artist.musicbrainz_id and artist.musicbrainz_id.startswith("local-"):
                    artists_skipped_sync += 1
                    logger.info(f"Skipping MB sync for local author: {artist.name}")
                    continue

                # Skip artists that already have albums AND tracks synced (from previous run)
                # Artists with albums but 0 tracks need re-sync (e.g. previous sync failed)
                from app.models.track import Track
                existing_album_count = db.query(Album).filter(
                    Album.artist_id == artist.id
                ).count()
                existing_track_count = 0
                if existing_album_count > 0:
                    existing_track_count = db.query(Track).join(Album).filter(
                        Album.artist_id == artist.id
                    ).limit(1).count()

                if existing_album_count > 0 and existing_track_count > 0:
                    artists_skipped_sync += 1
                    # Still do MBID file matching even if albums already synced
                    match_stats = mbid_matcher.match_artist_files(
                        artist_id=artist.id,
                        library_path_id=UUID(library_path_id)
                    )
                    tracks_matched = match_stats.get('matched', 0)
                    if tracks_matched > 0:
                        import_job.tracks_matched += tracks_matched
                        job_logger.stats.tracks_matched += tracks_matched
                    continue

                # Heartbeat callback to keep import_job updated during long syncs
                def _import_heartbeat(step: str):
                    import_job.current_action = f"Syncing {idx+1}/{len(matched_artists)}: {artist.name} - {step}"
                    db.commit()

                # Sync albums/books from MusicBrainz (use standalone function to avoid Celery task nesting)
                if is_audiobook:
                    sync_result = sync_author_books_standalone(db, str(artist.id), heartbeat_fn=_import_heartbeat)
                else:
                    sync_result = sync_artist_albums_standalone(db, str(artist.id), heartbeat_fn=_import_heartbeat)

                if sync_result.get('success'):
                    albums_synced = sync_result.get('albums_found', 0)
                    import_job.albums_synced += albums_synced
                    job_logger.log_album_sync(
                        album_title=f"{albums_synced} albums",
                        artist_name=artist.name,
                        action="synced"
                    )
                    logger.info(f"Synced {albums_synced} albums for {artist.name}")

                    # RAPID MBID MATCHING - Match files immediately after metadata sync
                    logger.info(f"Starting rapid MBID matching for {artist.name}")
                    import_job.current_action = f"Matching files for {artist.name} via MBID..."
                    db.commit()

                    match_stats = mbid_matcher.match_artist_files(
                        artist_id=artist.id,
                        library_path_id=UUID(library_path_id)
                    )

                    # Update statistics
                    tracks_matched = match_stats.get('matched', 0)
                    import_job.tracks_matched += tracks_matched
                    job_logger.stats.tracks_matched += tracks_matched
                    job_logger.log_track_match(
                        track_title=f"{tracks_matched} tracks via MBID",
                        file_path="",
                        action="matched",
                        confidence=100.0
                    )
                    logger.info(
                        f"Rapid MBID matching for {artist.name}: "
                        f"{tracks_matched} tracks matched"
                    )
                else:
                    logger.warning(f"Failed to sync albums for {artist.name}")
                    job_logger.log_warning(f"Failed to sync albums for {artist.name}")

            except Exception as e:
                logger.error(f"Error syncing {artist.name}: {e}")
                continue

            db.commit()

        import_job.phase_metadata_sync = 'completed'
        import_job.progress_percent = 70.0
        db.commit()

        job_logger.stats.albums_synced = import_job.albums_synced
        job_logger.log_info(f"\nPhase 3 complete:")
        job_logger.log_info(f"  Albums synced: {import_job.albums_synced}")
        job_logger.log_info(f"  Artists skipped (already synced): {artists_skipped_sync}")
        job_logger.log_info(f"  Tracks matched via MBID: {import_job.tracks_matched}")
        logger.info(
            f"✅ Metadata sync complete: {import_job.albums_synced} albums synced, "
            f"{artists_skipped_sync} skipped, {import_job.tracks_matched} tracks matched via MBID"
        )

        # -------------------------------------------------------------------
        # PHASE 3a: Create Books from File Metadata (Audiobooks)
        # -------------------------------------------------------------------
        # For audiobook libraries, when MusicBrainz sync yields no books for
        # an author (common for Audible/OpenAudible libraries), create Book
        # and Chapter records directly from file metadata.
        if is_audiobook and matched_artists:
            try:
                from app.services.book_from_metadata import create_books_from_file_metadata

                logger.info("📖 Phase 3a: Creating audiobooks from file metadata")
                job_logger.log_info("\nPhase 3a: Creating audiobooks from file metadata")
                import_job.current_action = "Creating audiobooks from file metadata..."
                db.commit()

                total_books_created = 0
                total_chapters_created = 0
                total_files_matched = 0

                for artist in matched_artists:
                    try:
                        meta_stats = create_books_from_file_metadata(
                            db=db,
                            author_id=artist.id,
                            library_path_id=UUID(library_path_id),
                        )
                        books_created = meta_stats.get("books_created", 0)
                        chapters_created = meta_stats.get("chapters_created", 0)
                        files_matched = meta_stats.get("files_matched", 0)

                        total_books_created += books_created
                        total_chapters_created += chapters_created
                        total_files_matched += files_matched

                        if books_created > 0:
                            import_job.albums_synced += books_created
                            import_job.tracks_matched += files_matched
                            job_logger.log_info(
                                f"  {artist.name}: {books_created} books, "
                                f"{chapters_created} chapters from file metadata"
                            )
                    except Exception as e:
                        logger.error(f"Metadata book creation failed for {artist.name}: {e}")

                db.commit()
                job_logger.log_info(
                    f"  Phase 3a complete: {total_books_created} books, "
                    f"{total_chapters_created} chapters created from metadata, "
                    f"{total_files_matched} files matched"
                )
                logger.info(
                    f"✅ Audiobook metadata creation: {total_books_created} books, "
                    f"{total_chapters_created} chapters, {total_files_matched} files matched"
                )
            except Exception as e:
                logger.warning(f"Phase 3a metadata book creation failed (non-fatal): {e}")
                db.rollback()

        # -------------------------------------------------------------------
        # PHASE 3a-2: Metadata-Based File Matching for Audiobooks
        # -------------------------------------------------------------------
        # For files that weren't matched during book creation (e.g. when
        # books existed from MB but files lacked MBIDs), do a metadata pass.
        if is_audiobook and matched_artists:
            try:
                logger.info("📖 Phase 3a-2: Metadata-based audiobook file matching")
                job_logger.log_info("\nPhase 3a-2: Metadata-based audiobook file matching")
                import_job.current_action = "Matching audiobook files by metadata..."
                db.commit()

                book_matcher = BookFileMatcher(db)
                metadata_matched_total = 0

                for artist in matched_artists:
                    try:
                        meta_stats = book_matcher.match_author_files(
                            author_id=artist.id,
                            library_path_id=UUID(library_path_id),
                        )
                        meta_matched = meta_stats.get("matched", 0)
                        if meta_matched > 0:
                            metadata_matched_total += meta_matched
                            import_job.tracks_matched += meta_matched
                            job_logger.log_info(
                                f"  Metadata matched {meta_matched} chapters for {artist.name}"
                            )
                    except Exception as e:
                        logger.error(f"Metadata matching failed for {artist.name}: {e}")

                db.commit()
                job_logger.log_info(
                    f"  Phase 3a-2 complete: {metadata_matched_total} additional chapters matched via metadata"
                )
                logger.info(
                    f"✅ Audiobook metadata matching: {metadata_matched_total} chapters matched"
                )
            except Exception as e:
                logger.warning(f"Phase 3a-2 metadata matching failed (non-fatal): {e}")
                db.rollback()

        # -------------------------------------------------------------------
        # PHASE 3b: Auto-Import Missing Albums for Unmatched Files
        # -------------------------------------------------------------------
        # For files that still have no matching track after MBID matching,
        # check if their release group is missing from our DB and import it.
        try:
            from app.services.album_importer import import_release_group
            from app.services.musicbrainz_client import get_musicbrainz_client as _get_mb_client
            from app.models.track import Track

            missing_albums_sql = text("""
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
                  AND lf.library_path_id = :library_path_id
            """)
            missing_rows = db.execute(missing_albums_sql, {'library_path_id': library_path_id}).fetchall()

            if missing_rows:
                import_job.current_action = f"Auto-importing {len(missing_rows)} missing albums..."
                db.commit()

                mb_client = _get_mb_client()
                auto_imported = 0
                auto_import_tracks = 0

                for idx, row in enumerate(missing_rows):
                    try:
                        album = import_release_group(db, row.artist_id, row.rg_mbid, mb_client)
                        if album:
                            auto_imported += 1
                            track_count = db.query(Track).filter(Track.album_id == album.id).count()
                            auto_import_tracks += track_count
                            db.commit()

                            if idx % 5 == 0:
                                import_job.current_action = f"Auto-import: {idx+1}/{len(missing_rows)} albums"
                                db.commit()
                    except Exception as e:
                        logger.warning(f"Failed to auto-import RG {row.rg_mbid}: {e}")
                        db.rollback()

                job_logger.log_info(f"\nPhase 3b: Auto-imported {auto_imported} albums ({auto_import_tracks} tracks)")
                import_job.albums_synced += auto_imported

                # Re-run MBID matching for newly imported tracks
                if auto_imported > 0:
                    additional_matched = 0
                    for artist in matched_artists:
                        try:
                            match_stats = mbid_matcher.match_artist_files(
                                artist_id=artist.id,
                                library_path_id=UUID(library_path_id)
                            )
                            additional_matched += match_stats.get('matched', 0)
                        except Exception:
                            pass

                    if additional_matched > 0:
                        import_job.tracks_matched += additional_matched
                        job_logger.log_info(f"  Re-match after auto-import: {additional_matched} additional tracks matched")
                        logger.info(f"Auto-import re-match: {additional_matched} additional tracks matched")

                db.commit()
            else:
                job_logger.log_info("\nPhase 3b: No missing albums to auto-import")
        except Exception as e:
            logger.warning(f"Phase 3b auto-import failed (non-fatal): {e}")
            db.rollback()

        # -------------------------------------------------------------------
        # PHASE 4: Folder Matching
        # -------------------------------------------------------------------
        if auto_assign_folders:
            logger.info("📁 Phase 4: Folder Matching")
            import_job.current_phase = 'folder_matching'
            import_job.phase_folder_matching = 'running'
            import_job.current_action = "Matching folder structures..."
            import_job.progress_percent = 75.0
            db.commit()

            # For each matched artist, scan their folder
            folders_matched = 0
            for idx, artist in enumerate(matched_artists):
                # Check for cancellation or pause
                db.refresh(import_job)
                if import_job.cancel_requested:
                    logger.info("Import cancelled by user")
                    import_job.status = 'cancelled'
                    import_job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return {"cancelled": True}

                if import_job.pause_requested or checkpoint_mgr.is_pause_requested():
                    logger.info("Import paused by user during folder matching")
                    import_job.status = 'paused'
                    import_job.pause_requested = False
                    db.commit()
                    checkpoint_mgr.clear_pause_request()
                    return {"paused": True, "phase": "folder_matching", "progress": idx}

                # Update progress
                progress = 75.0 + (idx / len(matched_artists)) * 10.0  # 75% to 85%
                import_job.progress_percent = progress
                import_job.current_action = f"Scanning folders {idx+1}/{len(matched_artists)}: {artist.name}"
                db.commit()

                try:
                    # Get artist match record to find sample file paths
                    match = db.query(LibraryArtistMatch).filter(
                        LibraryArtistMatch.import_job_id == UUID(import_job_id),
                        LibraryArtistMatch.matched_artist_id == artist.id
                    ).first()

                    if match and match.sample_file_paths:
                        # Infer artist folder from file paths
                        from pathlib import Path
                        sample_path = Path(match.sample_file_paths[0])

                        # Try to find artist folder (usually parent of album folder)
                        # E.g., /music/Artist Name/Album Name/track.flac
                        potential_artist_folder = sample_path.parent.parent

                        if potential_artist_folder.exists() and potential_artist_folder.is_dir():
                            # Use the artist folder scanning endpoint logic
                            from app.api.artists import scan_artist_folder as folder_scan_logic

                            # Import the folder scanning function (we'll need to refactor this into a service)
                            # For now, set root_folder_path manually
                            artist.root_folder_path = str(potential_artist_folder)
                            db.commit()

                            folders_matched += 1
                            logger.info(f"Identified artist folder for {artist.name}: {potential_artist_folder}")

                except Exception as e:
                    logger.error(f"Error matching folders for {artist.name}: {e}")
                    continue

            import_job.phase_folder_matching = 'completed'
            import_job.progress_percent = 85.0
            db.commit()

            logger.info(f"✅ Folder matching complete: {folders_matched} artist folders identified")
        else:
            import_job.phase_folder_matching = 'skipped'
            import_job.progress_percent = 85.0
            db.commit()

        # -------------------------------------------------------------------
        # PHASE 5: Track Matching
        # -------------------------------------------------------------------
        if auto_match_tracks:
            logger.info("🎵 Phase 5: Track Matching")
            import_job.current_phase = 'track_matching'
            import_job.phase_track_matching = 'running'
            import_job.current_action = "Matching tracks to files..."
            import_job.progress_percent = 87.0
            db.commit()

            # Match tracks for albums with folder paths
            from app.models.album import Album

            albums_with_paths = db.query(Album).filter(
                Album.artist_id.in_([a.id for a in matched_artists]),
                Album.custom_folder_path.isnot(None)
            ).all()

            matcher = AlbumFileMatcher(db)

            for idx, album in enumerate(albums_with_paths):
                # Check for cancellation or pause
                db.refresh(import_job)
                if import_job.cancel_requested:
                    logger.info("Import cancelled by user")
                    import_job.status = 'cancelled'
                    import_job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return {"cancelled": True}

                if import_job.pause_requested or checkpoint_mgr.is_pause_requested():
                    logger.info("Import paused by user during track matching")
                    import_job.status = 'paused'
                    import_job.pause_requested = False
                    db.commit()
                    checkpoint_mgr.clear_pause_request()
                    return {"paused": True, "phase": "track_matching", "progress": idx}

                # Update progress
                progress = 87.0 + (idx / len(albums_with_paths)) * 8.0  # 87% to 95%
                import_job.progress_percent = progress
                import_job.current_action = f"Matching tracks {idx+1}/{len(albums_with_paths)}: {album.title}"
                db.commit()

                try:
                    # Match tracks for this album
                    match_result = matcher.match_and_assign_tracks(str(album.id))

                    if match_result.get('success'):
                        matched_count = match_result.get('matched_tracks', 0)
                        import_job.tracks_matched += matched_count
                        import_job.tracks_unmatched += match_result.get('unmatched_tracks', 0)

                        logger.info(
                            f"Matched {matched_count} tracks for {album.title}"
                        )

                except Exception as e:
                    logger.error(f"Error matching tracks for {album.title}: {e}")
                    continue

                db.commit()

            import_job.phase_track_matching = 'completed'
            import_job.progress_percent = 95.0
            db.commit()

            logger.info(
                f"✅ Track matching complete: {import_job.tracks_matched} matched, "
                f"{import_job.tracks_unmatched} unmatched"
            )
        else:
            import_job.phase_track_matching = 'skipped'
            import_job.progress_percent = 95.0
            db.commit()

        # -------------------------------------------------------------------
        # PHASE 6: Finalization
        # -------------------------------------------------------------------
        logger.info("🎉 Phase 6: Finalization")
        job_logger.log_import_phase_start("finalization")
        import_job.current_phase = 'finalization'
        import_job.phase_finalization = 'running'
        import_job.current_action = "Calculating statistics..."
        import_job.progress_percent = 97.0
        db.commit()

        # Calculate final statistics
        # (Already tracked during import)

        import_job.phase_finalization = 'completed'
        import_job.status = 'completed'
        import_job.progress_percent = 100.0
        import_job.completed_at = datetime.now(timezone.utc)
        import_job.current_action = "Import complete"
        db.commit()

        # Log final summary
        job_logger.log_info(f"\n{'='*50}")
        job_logger.log_info(f"IMPORT COMPLETE")
        job_logger.log_info(f"{'='*50}")
        job_logger.log_info(f"Files scanned: {import_job.files_scanned}")
        job_logger.log_info(f"Artists found: {import_job.artists_found}")
        job_logger.log_info(f"Artists matched: {import_job.artists_matched}")
        job_logger.log_info(f"Artists created: {import_job.artists_created}")
        job_logger.log_info(f"Artists pending: {import_job.artists_pending}")
        job_logger.log_info(f"Albums synced: {import_job.albums_synced}")
        job_logger.log_info(f"Tracks matched: {import_job.tracks_matched}")
        job_logger.log_info(f"Tracks unmatched: {import_job.tracks_unmatched}")
        job_logger.log_job_complete()

        logger.info("✅ Library import completed successfully!")

        # Send notification
        try:
            from app.services.notification_service import send_notification
            send_notification("album_imported", {
                "message": f"Library import completed: {import_job.artists_matched} artists, {import_job.tracks_matched} tracks matched",
                "library_path": library_name,
                "files_scanned": import_job.files_scanned,
                "artists_matched": import_job.artists_matched,
                "tracks_matched": import_job.tracks_matched,
            })
        except Exception as e:
            logger.debug(f"Notification send failed: {e}")

        # Trigger file organization for successfully imported files (if enabled)
        try:
            import os
            auto_organize = os.getenv("STUDIO54_AUTO_ORG_AFTER_IMPORT", "false").lower() == "true"

            if auto_organize and import_job.tracks_matched > 0:
                logger.info(f"Auto-organizing {import_job.tracks_matched} successfully matched tracks...")

                from app.tasks.organization_tasks import organize_library_files_task
                from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

                # Create organization job record
                org_job = FileOrganizationJob(
                    job_type=JobType.ORGANIZE_LIBRARY,
                    status=OrgJobStatus.PENDING,
                    library_path_id=library_path_id
                )
                db.add(org_job)
                db.commit()
                db.refresh(org_job)

                # Create organization options
                org_options = {
                    'dry_run': False,
                    'create_metadata_files': True,
                    'backup_before_move': True,
                    'only_with_mbid': True,
                    'only_unorganized': True
                }

                # Queue organization task
                organize_library_files_task.delay(
                    job_id=str(org_job.id),
                    library_path_id=str(library_path_id),
                    options=org_options
                )

                logger.info(f"File organization job {org_job.id} queued for library path {library_path_id}")
        except Exception as e:
            logger.error(f"Failed to trigger file organization: {e}")
            # Don't fail the import job if organization fails to queue

        # Trigger associate & organize (walk filesystem, match to DB tracks, move/rename/link)
        try:
            auto_associate = os.getenv("STUDIO54_AUTO_ASSOCIATE_AFTER_IMPORT", "false").lower() == "true"

            if auto_associate and import_job.tracks_matched > 0:
                logger.info(f"Auto-associate & organize for {import_job.tracks_matched} matched tracks...")

                from app.tasks.organization_tasks import associate_and_organize_library_task
                from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

                assoc_job = FileOrganizationJob(
                    job_type=JobType.ASSOCIATE_AND_ORGANIZE,
                    status=OrgJobStatus.PENDING,
                    library_path_id=library_path_id
                )
                db.add(assoc_job)
                db.commit()
                db.refresh(assoc_job)

                assoc_options = {
                    'dry_run': False,
                    'create_metadata_files': True,
                }

                associate_and_organize_library_task.delay(
                    job_id=str(assoc_job.id),
                    library_path_id=str(library_path_id),
                    options=assoc_options
                )

                logger.info(f"Associate & organize job {assoc_job.id} queued for library path {library_path_id}")
        except Exception as e:
            logger.error(f"Failed to trigger associate & organize: {e}")
            # Don't fail the import job if associate & organize fails to queue

        # Auto-queue FETCH_METADATA for files without MBIDs
        try:
            from sqlalchemy import or_
            from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

            unmatched_count = db.query(LibraryFile).filter(
                LibraryFile.library_path_id == UUID(library_path_id),
                or_(
                    LibraryFile.mbid_in_file == False,
                    LibraryFile.mbid_in_file.is_(None),
                    LibraryFile.musicbrainz_trackid.is_(None),
                    LibraryFile.musicbrainz_trackid == ''
                )
            ).count()

            if unmatched_count > 0:
                logger.info(f"Auto-queuing FETCH_METADATA for {unmatched_count} files without MBIDs...")

                from app.tasks.organization_tasks import fetch_metadata_task

                fetch_job = FileOrganizationJob(
                    job_type=JobType.FETCH_METADATA,
                    status=OrgJobStatus.PENDING,
                    library_path_id=library_path_id,
                    parent_job_id=UUID(import_job_id),
                    files_total=unmatched_count,
                    progress_percent=0.0
                )
                db.add(fetch_job)
                db.commit()
                db.refresh(fetch_job)

                celery_result = fetch_metadata_task.delay(str(fetch_job.id))
                fetch_job.celery_task_id = celery_result.id
                db.commit()

                logger.info(f"FETCH_METADATA job {fetch_job.id} queued for {unmatched_count} unmatched files")
                job_logger.log_info(f"Auto-queued FETCH_METADATA job {fetch_job.id} for {unmatched_count} files without MBIDs")
            else:
                logger.info("All files have MBIDs - no FETCH_METADATA job needed")
                job_logger.log_info("All files have MBIDs - no FETCH_METADATA job needed")
        except Exception as e:
            logger.error(f"Failed to auto-queue FETCH_METADATA: {e}")
            # Don't fail the import job if FETCH_METADATA fails to queue

        return {
            'success': True,
            'import_job_id': import_job_id,
            'statistics': {
                'files_scanned': import_job.files_scanned,
                'artists_found': import_job.artists_found,
                'artists_matched': import_job.artists_matched,
                'artists_created': import_job.artists_created,
                'artists_pending': import_job.artists_pending,
                'albums_synced': import_job.albums_synced,
                'tracks_matched': import_job.tracks_matched,
                'tracks_unmatched': import_job.tracks_unmatched
            }
        }

    except SoftTimeLimitExceeded:
        logger.error(f"❌ Library import hit soft time limit: {import_job_id}")

        # Save progress for potential resume
        if job_logger:
            job_logger.log_error("Soft time limit exceeded - saving progress for resume")
            job_logger.log_job_complete()

        try:
            import_job_ref = db.query(LibraryImportJob).filter(
                LibraryImportJob.id == UUID(import_job_id)
            ).first()

            if import_job_ref:
                import_job_ref.status = 'failed'
                import_job_ref.error_message = (
                    f"Time limit exceeded during {import_job_ref.current_phase}. "
                    f"Progress: {import_job_ref.artists_matched}/{import_job_ref.artists_found} artists matched, "
                    f"{import_job_ref.albums_synced} albums synced. "
                    f"Re-run import to resume from where it left off (already-matched artists will be skipped)."
                )
                import_job_ref.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass

        return {'error': 'Soft time limit exceeded', 'import_job_id': import_job_id}

    except Exception as e:
        import traceback
        logger.error(f"❌ Library import failed: {e}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")

        # Log error to job logger
        if job_logger:
            job_logger.log_error(str(e))
            job_logger.log_job_complete()

        # Update job status
        try:
            import_job_ref = db.query(LibraryImportJob).filter(
                LibraryImportJob.id == UUID(import_job_id)
            ).first()

            if import_job_ref:
                import_job_ref.status = 'failed'
                import_job_ref.error_message = str(e)
                import_job_ref.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass

        return {'error': str(e)}

    finally:
        db.close()


@celery_app.task(
    name="app.tasks.import_tasks.sync_import_batch",
    soft_time_limit=7200,    # 2 hours per batch
    time_limit=7500,
)
def sync_import_batch(
    artist_ids: List[str],
    library_path_id: str,
    import_job_id: str,
    batch_index: int = 0,
) -> Dict:
    """
    Sync a batch of artists from MusicBrainz + rapid MBID file matching.

    Designed to run in parallel across multiple workers via chord dispatch.
    Each batch processes ~50 artists independently.

    Args:
        artist_ids: List of Artist UUID strings to sync
        library_path_id: LibraryPath UUID
        import_job_id: Import job UUID for progress tracking
        batch_index: Batch number for logging

    Returns:
        Batch result summary
    """
    db = SessionLocal()
    try:
        from app.models.album import Album
        from app.tasks.sync_tasks import sync_artist_albums_standalone

        mbid_matcher = MBIDFileMatcher(db)
        checkpoint_mgr = JobCheckpointManager(import_job_id)

        batch_stats = {
            "batch_index": batch_index,
            "artists_processed": 0,
            "artists_skipped": 0,
            "albums_synced": 0,
            "tracks_matched": 0,
            "errors": 0,
        }

        for artist_id in artist_ids:
            # Check for pause/cancel
            if checkpoint_mgr.is_pause_requested():
                logger.info(f"Batch {batch_index}: pause requested, stopping early")
                batch_stats["paused"] = True
                break

            import_job = db.query(LibraryImportJob).filter(
                LibraryImportJob.id == UUID(import_job_id)
            ).first()
            if import_job and (import_job.cancel_requested or import_job.pause_requested):
                batch_stats["paused"] = True
                break

            artist = db.query(Artist).filter(Artist.id == UUID(artist_id)).first()
            if not artist:
                batch_stats["errors"] += 1
                continue

            try:
                # Skip artists that already have albums synced
                existing_album_count = db.query(Album).filter(
                    Album.artist_id == artist.id
                ).count()

                if existing_album_count > 0:
                    batch_stats["artists_skipped"] += 1
                    # Still do MBID file matching
                    match_stats = mbid_matcher.match_artist_files(
                        artist_id=artist.id,
                        library_path_id=UUID(library_path_id)
                    )
                    batch_stats["tracks_matched"] += match_stats.get('matched', 0)
                    continue

                # Sync albums from MusicBrainz
                sync_result = sync_artist_albums_standalone(db, str(artist.id))

                if sync_result.get('success'):
                    albums_synced = sync_result.get('albums_found', 0)
                    batch_stats["albums_synced"] += albums_synced

                    # Rapid MBID matching
                    match_stats = mbid_matcher.match_artist_files(
                        artist_id=artist.id,
                        library_path_id=UUID(library_path_id)
                    )
                    batch_stats["tracks_matched"] += match_stats.get('matched', 0)

                    logger.info(
                        f"Batch {batch_index}: Synced {albums_synced} albums, "
                        f"matched {match_stats.get('matched', 0)} tracks for {artist.name}"
                    )

                batch_stats["artists_processed"] += 1

            except Exception as e:
                logger.error(f"Batch {batch_index}: Error syncing {artist.name}: {e}")
                batch_stats["errors"] += 1
                continue

            db.commit()

        # Update import job with batch results
        try:
            import_job = db.query(LibraryImportJob).filter(
                LibraryImportJob.id == UUID(import_job_id)
            ).first()
            if import_job:
                import_job.albums_synced += batch_stats["albums_synced"]
                import_job.tracks_matched += batch_stats["tracks_matched"]
                db.commit()
        except Exception as e:
            logger.error(f"Batch {batch_index}: Failed to update import job: {e}")

        return batch_stats

    except Exception as e:
        logger.error(f"Batch {batch_index} failed: {e}")
        return {"batch_index": batch_index, "error": str(e)}

    finally:
        db.close()


@celery_app.task(
    name="app.tasks.import_tasks.finalize_import_sync",
    soft_time_limit=3600,
    time_limit=3900,
)
def finalize_import_sync(
    batch_results: List[Dict],
    import_job_id: str,
    library_path_id: str,
    matched_artist_ids: List[str],
    config: Optional[Dict] = None,
) -> Dict:
    """
    Chord callback: aggregate batch results and run Phases 4-6.

    Called automatically after all sync_import_batch tasks complete.
    Handles folder matching, track matching, and finalization.

    Args:
        batch_results: List of results from sync_import_batch tasks
        import_job_id: Import job UUID
        library_path_id: LibraryPath UUID
        matched_artist_ids: List of matched artist IDs for Phase 4-5
        config: Import configuration dict

    Returns:
        Final import result summary
    """
    db = SessionLocal()
    job_logger = None
    try:
        import_job = db.query(LibraryImportJob).filter(
            LibraryImportJob.id == UUID(import_job_id)
        ).first()

        if not import_job:
            return {"error": "Import job not found"}

        # Check if paused during batch processing
        if import_job.cancel_requested:
            import_job.status = 'cancelled'
            import_job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return {"cancelled": True}

        if import_job.pause_requested:
            import_job.status = 'paused'
            import_job.pause_requested = False
            db.commit()
            return {"paused": True, "phase": "metadata_sync"}

        # Aggregate batch results
        total_albums = sum(r.get("albums_synced", 0) for r in batch_results if isinstance(r, dict))
        total_tracks = sum(r.get("tracks_matched", 0) for r in batch_results if isinstance(r, dict))
        total_errors = sum(r.get("errors", 0) for r in batch_results if isinstance(r, dict))
        total_skipped = sum(r.get("artists_skipped", 0) for r in batch_results if isinstance(r, dict))

        # Initialize job logger
        job_logger = JobLogger(job_type="import", job_id=import_job_id)
        if import_job.log_file_path:
            job_logger.log_file_path = import_job.log_file_path

        job_logger.log_info(f"\nPhase 3 complete (parallel sync):")
        job_logger.log_info(f"  Albums synced: {total_albums}")
        job_logger.log_info(f"  Artists skipped (already synced): {total_skipped}")
        job_logger.log_info(f"  Tracks matched via MBID: {total_tracks}")
        job_logger.log_info(f"  Batch errors: {total_errors}")

        import_job.phase_metadata_sync = 'completed'
        import_job.progress_percent = 70.0
        db.commit()

        logger.info(
            f"Phase 3 parallel sync complete: {total_albums} albums, "
            f"{total_tracks} tracks matched, {total_errors} errors"
        )

        # Load matched artists for Phases 4-5
        matched_artists = []
        for aid in matched_artist_ids:
            artist = db.query(Artist).filter(Artist.id == UUID(aid)).first()
            if artist:
                matched_artists.append(artist)

        config = config or {}
        auto_assign_folders = config.get('auto_assign_folders', import_job.auto_assign_folders)
        auto_match_tracks = config.get('auto_match_tracks', import_job.auto_match_tracks)
        checkpoint_mgr = JobCheckpointManager(import_job_id)

        # ---- PHASE 4: Folder Matching ----
        if auto_assign_folders:
            logger.info("Phase 4: Folder Matching")
            import_job.current_phase = 'folder_matching'
            import_job.phase_folder_matching = 'running'
            import_job.current_action = "Matching folder structures..."
            import_job.progress_percent = 75.0
            db.commit()

            folders_matched = 0
            for idx, artist in enumerate(matched_artists):
                db.refresh(import_job)
                if import_job.cancel_requested:
                    import_job.status = 'cancelled'
                    import_job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return {"cancelled": True}

                if import_job.pause_requested or checkpoint_mgr.is_pause_requested():
                    import_job.status = 'paused'
                    import_job.pause_requested = False
                    db.commit()
                    checkpoint_mgr.clear_pause_request()
                    return {"paused": True, "phase": "folder_matching"}

                progress = 75.0 + (idx / max(len(matched_artists), 1)) * 10.0
                import_job.progress_percent = progress
                import_job.current_action = f"Scanning folders {idx+1}/{len(matched_artists)}: {artist.name}"
                db.commit()

                try:
                    match = db.query(LibraryArtistMatch).filter(
                        LibraryArtistMatch.import_job_id == UUID(import_job_id),
                        LibraryArtistMatch.matched_artist_id == artist.id
                    ).first()

                    if match and match.sample_file_paths:
                        from pathlib import Path
                        sample_path = Path(match.sample_file_paths[0])
                        potential_artist_folder = sample_path.parent.parent

                        if potential_artist_folder.exists() and potential_artist_folder.is_dir():
                            artist.root_folder_path = str(potential_artist_folder)
                            db.commit()
                            folders_matched += 1
                except Exception as e:
                    logger.error(f"Error matching folders for {artist.name}: {e}")
                    continue

            import_job.phase_folder_matching = 'completed'
            import_job.progress_percent = 85.0
            db.commit()
        else:
            import_job.phase_folder_matching = 'skipped'
            import_job.progress_percent = 85.0
            db.commit()

        # ---- PHASE 5: Track Matching ----
        if auto_match_tracks:
            logger.info("Phase 5: Track Matching")
            import_job.current_phase = 'track_matching'
            import_job.phase_track_matching = 'running'
            import_job.current_action = "Matching tracks to files..."
            import_job.progress_percent = 87.0
            db.commit()

            from app.models.album import Album

            albums_with_paths = db.query(Album).filter(
                Album.artist_id.in_([a.id for a in matched_artists]),
                Album.custom_folder_path.isnot(None)
            ).all()

            matcher = AlbumFileMatcher(db)

            for idx, album in enumerate(albums_with_paths):
                db.refresh(import_job)
                if import_job.cancel_requested:
                    import_job.status = 'cancelled'
                    import_job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return {"cancelled": True}

                if import_job.pause_requested or checkpoint_mgr.is_pause_requested():
                    import_job.status = 'paused'
                    import_job.pause_requested = False
                    db.commit()
                    checkpoint_mgr.clear_pause_request()
                    return {"paused": True, "phase": "track_matching"}

                progress = 87.0 + (idx / max(len(albums_with_paths), 1)) * 8.0
                import_job.progress_percent = progress
                import_job.current_action = f"Matching tracks {idx+1}/{len(albums_with_paths)}: {album.title}"
                db.commit()

                try:
                    match_result = matcher.match_and_assign_tracks(str(album.id))
                    if match_result.get('success'):
                        matched_count = match_result.get('matched_tracks', 0)
                        import_job.tracks_matched += matched_count
                        import_job.tracks_unmatched += match_result.get('unmatched_tracks', 0)
                except Exception as e:
                    logger.error(f"Error matching tracks for {album.title}: {e}")
                    continue

                db.commit()

            import_job.phase_track_matching = 'completed'
            import_job.progress_percent = 95.0
            db.commit()
        else:
            import_job.phase_track_matching = 'skipped'
            import_job.progress_percent = 95.0
            db.commit()

        # ---- PHASE 6: Finalization ----
        logger.info("Phase 6: Finalization")
        job_logger.log_import_phase_start("finalization")
        import_job.current_phase = 'finalization'
        import_job.phase_finalization = 'running'
        import_job.current_action = "Calculating statistics..."
        import_job.progress_percent = 97.0
        db.commit()

        import_job.phase_finalization = 'completed'
        import_job.status = 'completed'
        import_job.progress_percent = 100.0
        import_job.completed_at = datetime.now(timezone.utc)
        import_job.current_action = "Import complete"
        db.commit()

        # Log final summary
        job_logger.log_info(f"\n{'='*50}")
        job_logger.log_info(f"IMPORT COMPLETE (parallel mode)")
        job_logger.log_info(f"{'='*50}")
        job_logger.log_info(f"Files scanned: {import_job.files_scanned}")
        job_logger.log_info(f"Artists matched: {import_job.artists_matched}")
        job_logger.log_info(f"Albums synced: {import_job.albums_synced}")
        job_logger.log_info(f"Tracks matched: {import_job.tracks_matched}")
        job_logger.log_job_complete()

        logger.info("Library import completed successfully (parallel mode)!")

        # Trigger post-import tasks (same as sequential path)
        _trigger_post_import_tasks(db, import_job, import_job_id, library_path_id, job_logger)

        return {
            'success': True,
            'import_job_id': import_job_id,
            'mode': 'parallel',
            'statistics': {
                'files_scanned': import_job.files_scanned,
                'artists_matched': import_job.artists_matched,
                'albums_synced': import_job.albums_synced,
                'tracks_matched': import_job.tracks_matched,
                'tracks_unmatched': import_job.tracks_unmatched,
            }
        }

    except Exception as e:
        import traceback
        logger.error(f"Finalize import sync failed: {e}\n{traceback.format_exc()}")

        if job_logger:
            job_logger.log_error(str(e))

        try:
            import_job_ref = db.query(LibraryImportJob).filter(
                LibraryImportJob.id == UUID(import_job_id)
            ).first()
            if import_job_ref:
                import_job_ref.status = 'failed'
                import_job_ref.error_message = str(e)
                import_job_ref.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass

        return {'error': str(e)}

    finally:
        db.close()


def _trigger_post_import_tasks(db, import_job, import_job_id, library_path_id, job_logger):
    """Trigger post-import tasks (organize, associate, fetch metadata)"""
    import os

    library_path = db.query(LibraryPath).filter(
        LibraryPath.id == UUID(library_path_id)
    ).first()
    library_name = library_path.name if library_path else library_path_id

    # Notification
    try:
        from app.services.notification_service import send_notification
        send_notification("album_imported", {
            "message": f"Library import completed: {import_job.artists_matched} artists, {import_job.tracks_matched} tracks matched",
            "library_path": library_name,
            "files_scanned": import_job.files_scanned,
            "artists_matched": import_job.artists_matched,
            "tracks_matched": import_job.tracks_matched,
        })
    except Exception as e:
        logger.debug(f"Notification send failed: {e}")

    # Auto-organize
    try:
        auto_organize = os.getenv("STUDIO54_AUTO_ORG_AFTER_IMPORT", "false").lower() == "true"
        if auto_organize and import_job.tracks_matched > 0:
            from app.tasks.organization_tasks import organize_library_files_task
            from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

            org_job = FileOrganizationJob(
                job_type=JobType.ORGANIZE_LIBRARY,
                status=OrgJobStatus.PENDING,
                library_path_id=library_path_id
            )
            db.add(org_job)
            db.commit()
            db.refresh(org_job)

            organize_library_files_task.delay(
                job_id=str(org_job.id),
                library_path_id=str(library_path_id),
                options={
                    'dry_run': False,
                    'create_metadata_files': True,
                    'backup_before_move': True,
                    'only_with_mbid': True,
                    'only_unorganized': True
                }
            )
    except Exception as e:
        logger.error(f"Failed to trigger file organization: {e}")

    # Auto-associate & organize
    try:
        auto_associate = os.getenv("STUDIO54_AUTO_ASSOCIATE_AFTER_IMPORT", "false").lower() == "true"
        if auto_associate and import_job.tracks_matched > 0:
            from app.tasks.organization_tasks import associate_and_organize_library_task
            from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

            assoc_job = FileOrganizationJob(
                job_type=JobType.ASSOCIATE_AND_ORGANIZE,
                status=OrgJobStatus.PENDING,
                library_path_id=library_path_id
            )
            db.add(assoc_job)
            db.commit()
            db.refresh(assoc_job)

            associate_and_organize_library_task.delay(
                job_id=str(assoc_job.id),
                library_path_id=str(library_path_id),
                options={'dry_run': False, 'create_metadata_files': True}
            )
    except Exception as e:
        logger.error(f"Failed to trigger associate & organize: {e}")

    # Auto-queue FETCH_METADATA for unmatched files
    try:
        from sqlalchemy import or_
        from app.models.file_organization_job import FileOrganizationJob, JobStatus as OrgJobStatus, JobType

        unmatched_count = db.query(LibraryFile).filter(
            LibraryFile.library_path_id == UUID(library_path_id),
            or_(
                LibraryFile.mbid_in_file == False,
                LibraryFile.mbid_in_file.is_(None),
                LibraryFile.musicbrainz_trackid.is_(None),
                LibraryFile.musicbrainz_trackid == ''
            )
        ).count()

        if unmatched_count > 0:
            from app.tasks.organization_tasks import fetch_metadata_task

            fetch_job = FileOrganizationJob(
                job_type=JobType.FETCH_METADATA,
                status=OrgJobStatus.PENDING,
                library_path_id=library_path_id,
                parent_job_id=UUID(import_job_id),
                files_total=unmatched_count,
                progress_percent=0.0
            )
            db.add(fetch_job)
            db.commit()
            db.refresh(fetch_job)

            celery_result = fetch_metadata_task.delay(str(fetch_job.id))
            fetch_job.celery_task_id = celery_result.id
            db.commit()

            if job_logger:
                job_logger.log_info(f"Auto-queued FETCH_METADATA job for {unmatched_count} files")
    except Exception as e:
        logger.error(f"Failed to auto-queue FETCH_METADATA: {e}")
