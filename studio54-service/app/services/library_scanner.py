"""
Library Scanner Service
High-performance file system scanner for large music collections

Optimized for 100,000+ files with:
- Incremental scanning (skip unchanged files)
- Batch database operations
- Async image fetching
- Progress tracking
"""
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.library import LibraryPath, LibraryFile, ScanJob
from app.services.metadata_extractor import MetadataExtractor
from app.services.musicbrainz_images import MusicBrainzImageFetcher

logger = logging.getLogger(__name__)


class LibraryScanner:
    """
    High-performance library scanner

    Features:
    - Recursive directory scanning
    - Incremental updates (skip unchanged files)
    - Batch database inserts (100 records at a time)
    - Metadata extraction
    - MusicBrainz image fetching
    """

    # Performance settings
    BATCH_SIZE = 100  # Insert 100 files at a time
    IMAGE_FETCH_BATCH_SIZE = 50  # Fetch images in batches of 50
    COMMIT_INTERVAL = 500  # Commit every 500 files

    def __init__(self, db: Session, fanart_api_key: Optional[str] = None):
        """
        Initialize scanner

        Args:
            db: Database session
            fanart_api_key: Optional Fanart.tv API key for artist images
        """
        self.db = db
        self.image_fetcher = MusicBrainzImageFetcher(fanart_api_key=fanart_api_key)
        self.extractor = MetadataExtractor()

    def scan_path(
        self,
        library_path: LibraryPath,
        scan_job: ScanJob,
        incremental: bool = True,
        fetch_images: bool = True
    ) -> Dict[str, int]:
        """
        Scan a library path and index all audio files

        Args:
            library_path: LibraryPath database object
            scan_job: ScanJob for tracking progress
            incremental: Skip files that haven't changed
            fetch_images: Fetch album/artist images from MusicBrainz

        Returns:
            Dict with scan statistics
        """
        logger.info(f"Starting scan of: {library_path.path} (incremental={incremental})")

        stats = {
            'files_scanned': 0,
            'files_added': 0,
            'files_updated': 0,
            'files_skipped': 0,
            'files_failed': 0,
            'files_removed': 0,  # Files no longer on disk
        }

        # Update scan job status
        scan_job.status = 'running'
        scan_job.started_at = datetime.now(timezone.utc)
        self.db.commit()

        try:
            # Build existing files index for incremental scanning AND orphan detection
            existing_files = self._build_file_index(library_path.id)
            logger.info(f"Found {len(existing_files)} existing files in database")

            # Track which files we find on disk (for orphan detection)
            files_found_on_disk = set()

            # Scan directory
            batch = []
            files_to_update = []
            commit_counter = 0

            for file_path in self._walk_directory(library_path.path):
                stats['files_scanned'] += 1
                commit_counter += 1
                files_found_on_disk.add(file_path)

                try:
                    # Check if file exists in database
                    if file_path in existing_files:
                        if incremental:
                            file_record = existing_files[file_path]
                            file_stat = os.stat(file_path)

                            # Skip if file hasn't changed
                            if file_stat.st_mtime == file_record.file_modified_at.timestamp():
                                stats['files_skipped'] += 1
                                continue

                            # File changed - mark for update
                            files_to_update.append((file_record, file_path))
                            stats['files_updated'] += 1
                        else:
                            stats['files_skipped'] += 1
                    else:
                        # New file - add to batch
                        file_data = self._process_file(file_path, library_path.id)
                        if file_data:
                            batch.append(file_data)
                            stats['files_added'] += 1

                    # Batch insert when batch is full
                    if len(batch) >= self.BATCH_SIZE:
                        self._insert_batch(batch)
                        batch = []

                    # Update modified files in batches
                    if len(files_to_update) >= self.BATCH_SIZE:
                        self._update_batch(files_to_update)
                        files_to_update = []

                    # Periodic commit
                    if commit_counter >= self.COMMIT_INTERVAL:
                        self.db.commit()
                        commit_counter = 0

                        # Update scan job progress
                        scan_job.files_scanned = stats['files_scanned']
                        scan_job.files_added = stats['files_added']
                        scan_job.files_updated = stats['files_updated']
                        scan_job.files_skipped = stats['files_skipped']
                        scan_job.files_failed = stats['files_failed']
                        self.db.commit()

                        logger.info(f"Progress: {stats['files_scanned']} scanned, {stats['files_added']} added, {stats['files_skipped']} skipped")

                except Exception as e:
                    logger.error(f"Error processing {file_path}: {e}")
                    stats['files_failed'] += 1
                    continue

            # Insert remaining batch
            if batch:
                self._insert_batch(batch)

            # Update remaining modified files
            if files_to_update:
                self._update_batch(files_to_update)

            # Remove orphaned files (exist in database but not on disk)
            orphaned_files = set(existing_files.keys()) - files_found_on_disk
            if orphaned_files:
                stats['files_removed'] = self._remove_orphaned_files(orphaned_files, library_path.id)
                logger.info(f"Removed {stats['files_removed']} orphaned files from database")

            # Fetch images if requested
            if fetch_images:
                logger.info("Fetching album art and artist images...")
                image_stats = self._fetch_images(library_path.id)
                stats.update(image_stats)

            # Update library path stats
            library_path.total_files = stats['files_added'] + len(existing_files)
            library_path.last_scan_at = datetime.now(timezone.utc)

            # Mark scan as completed
            scan_job.status = 'completed'
            scan_job.completed_at = datetime.now(timezone.utc)
            scan_job.files_scanned = stats['files_scanned']
            scan_job.files_added = stats['files_added']
            scan_job.files_updated = stats['files_updated']
            scan_job.files_skipped = stats['files_skipped']
            scan_job.files_failed = stats['files_failed']

            self.db.commit()

            logger.info(f"Scan completed: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Scan failed: {e}")
            scan_job.status = 'failed'
            scan_job.error_message = str(e)
            scan_job.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise

    def _walk_directory(self, root_path: str):
        """
        Walk directory and yield audio file paths

        Yields:
            Full path to audio files
        """
        logger.info(f"Walking directory: {root_path}")

        for dirpath, dirnames, filenames in os.walk(root_path):
            # Skip hidden directories
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]

            for filename in filenames:
                file_path = os.path.join(dirpath, filename)

                # Check if supported audio file
                if self.extractor.is_supported(file_path):
                    yield file_path

    def _build_file_index(self, library_path_id: str) -> Dict[str, LibraryFile]:
        """
        Build index of existing files for incremental scanning

        Args:
            library_path_id: Library path UUID

        Returns:
            Dict mapping file_path -> LibraryFile record
        """
        files = self.db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id
        ).all()

        return {f.file_path: f for f in files}

    def _process_file(self, file_path: str, library_path_id: str) -> Optional[Dict[str, Any]]:
        """
        Extract metadata from file

        Args:
            file_path: Path to audio file
            library_path_id: Parent library path UUID

        Returns:
            Dict with file data ready for database insert
        """
        try:
            metadata = self.extractor.extract(file_path)

            return {
                'library_path_id': library_path_id,
                **metadata
            }

        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            return None

    def _insert_batch(self, batch: List[Dict[str, Any]]):
        """
        Batch insert files into database

        Args:
            batch: List of file data dicts
        """
        if not batch:
            return

        logger.debug(f"Inserting batch of {len(batch)} files")

        try:
            # Bulk insert
            self.db.bulk_insert_mappings(LibraryFile, batch)
            self.db.commit()
        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            self.db.rollback()
            raise

    def _update_batch(self, files_to_update: List[tuple]):
        """
        Batch update modified files

        Args:
            files_to_update: List of (LibraryFile, file_path) tuples
        """
        if not files_to_update:
            return

        logger.debug(f"Updating batch of {len(files_to_update)} files")

        for file_record, file_path in files_to_update:
            try:
                metadata = self.extractor.extract(file_path)

                # Update record
                for key, value in metadata.items():
                    if key not in ['library_path_id']:
                        setattr(file_record, key, value)

                file_record.updated_at = datetime.now(timezone.utc)

            except Exception as e:
                logger.error(f"Error updating {file_path}: {e}")
                continue

        self.db.commit()

    def _remove_orphaned_files(self, orphaned_paths: set, library_path_id: str) -> int:
        """
        Remove files from database that no longer exist on disk

        Args:
            orphaned_paths: Set of file paths that exist in DB but not on disk
            library_path_id: Library path UUID

        Returns:
            Number of files removed
        """
        if not orphaned_paths:
            return 0

        logger.info(f"Removing {len(orphaned_paths)} orphaned files from database")

        # Delete in batches to avoid memory issues
        removed_count = 0
        orphaned_list = list(orphaned_paths)

        for i in range(0, len(orphaned_list), self.BATCH_SIZE):
            batch_paths = orphaned_list[i:i + self.BATCH_SIZE]

            try:
                deleted = self.db.query(LibraryFile).filter(
                    LibraryFile.library_path_id == library_path_id,
                    LibraryFile.file_path.in_(batch_paths)
                ).delete(synchronize_session=False)

                removed_count += deleted
                self.db.commit()

                logger.debug(f"Deleted batch of {deleted} orphaned files")

            except Exception as e:
                logger.error(f"Error removing orphaned files batch: {e}")
                self.db.rollback()
                continue

        return removed_count

    def _fetch_images(self, library_path_id: str) -> Dict[str, int]:
        """
        Fetch album art and artist images for files with MusicBrainz IDs

        Args:
            library_path_id: Library path UUID

        Returns:
            Dict with fetch statistics
        """
        stats = {
            'album_art_fetched': 0,
            'artist_images_fetched': 0,
        }

        # Fetch album art for files with MusicBrainz album IDs
        files_needing_album_art = self.db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id,
            LibraryFile.musicbrainz_albumid.isnot(None),
            LibraryFile.album_art_fetched == False
        ).limit(self.IMAGE_FETCH_BATCH_SIZE).all()

        for file_record in files_needing_album_art:
            try:
                album_art_url = self.image_fetcher.fetch_album_art_sync(file_record.musicbrainz_albumid)
                if album_art_url:
                    file_record.album_art_url = album_art_url
                    stats['album_art_fetched'] += 1

                file_record.album_art_fetched = True
            except Exception as e:
                logger.error(f"Error fetching album art for {file_record.file_path}: {e}")

        # Fetch artist images for files with MusicBrainz artist IDs
        files_needing_artist_image = self.db.query(LibraryFile).filter(
            LibraryFile.library_path_id == library_path_id,
            LibraryFile.musicbrainz_artistid.isnot(None),
            LibraryFile.artist_image_fetched == False
        ).limit(self.IMAGE_FETCH_BATCH_SIZE).all()

        for file_record in files_needing_artist_image:
            try:
                artist_image_url = self.image_fetcher.fetch_artist_image_sync(file_record.musicbrainz_artistid)
                if artist_image_url:
                    file_record.artist_image_url = artist_image_url
                    stats['artist_images_fetched'] += 1

                file_record.artist_image_fetched = True
            except Exception as e:
                logger.error(f"Error fetching artist image for {file_record.file_path}: {e}")

        self.db.commit()
        logger.info(f"Image fetch stats: {stats}")

        return stats
