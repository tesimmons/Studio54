"""
File Organizer Service

Core service for organizing files based on MBID metadata:
- Analyze file metadata and MBIDs
- Determine target folder structure
- Execute safe file moves with rollback
- Update database records after moves
- Generate audit logs
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.orm import Session

from .atomic_file_ops import AtomicFileOps, FileOperationResult, OperationType
from .naming_engine import NamingEngine, TrackContext, AlbumContext, ArtistContext
from .audit_logger import AuditLogger


logger = logging.getLogger(__name__)


@dataclass
class OrganizationResult:
    """Result of file organization operation"""
    success: bool
    files_total: int = 0
    files_processed: int = 0
    files_renamed: int = 0
    files_moved: int = 0
    files_failed: int = 0
    directories_created: int = 0
    error_message: Optional[str] = None
    failed_files: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.failed_files is None:
            self.failed_files = []


@dataclass
class ValidationResult:
    """Result of organization validation"""
    is_valid: bool
    total_files: int = 0
    organized_files: int = 0
    needs_organization: int = 0
    issues: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class FileOrganizer:
    """
    Core service for organizing files based on MBID metadata

    Features:
    - Calculate target paths using naming templates
    - Move files to correct locations
    - Update database records
    - Create album directories
    - Log all operations
    - Rollback on failure
    """

    def __init__(
        self,
        db: Session,
        naming_engine: Optional[NamingEngine] = None,
        atomic_ops: Optional[AtomicFileOps] = None,
        audit_logger: Optional[AuditLogger] = None,
        dry_run: bool = False
    ):
        """
        Initialize FileOrganizer service

        Args:
            db: Database session
            naming_engine: NamingEngine instance (creates default if None)
            atomic_ops: AtomicFileOps instance (creates default if None)
            audit_logger: AuditLogger instance (creates default if None)
            dry_run: If True, only calculate changes without executing
        """
        self.db = db
        self.naming_engine = naming_engine or NamingEngine()
        self.atomic_ops = atomic_ops or AtomicFileOps()
        self.audit_logger = audit_logger or AuditLogger(db)
        self.dry_run = dry_run

        logger.info(f"FileOrganizer initialized (dry_run={dry_run})")

    def organize_track_file(
        self,
        file_path: str,
        track_context: TrackContext,
        library_root: str,
        file_id: Optional[UUID] = None,
        track_id: Optional[UUID] = None,
        album_id: Optional[UUID] = None,
        artist_id: Optional[UUID] = None,
        recording_mbid: Optional[UUID] = None,
        release_mbid: Optional[UUID] = None,
        job_id: Optional[UUID] = None
    ) -> FileOperationResult:
        """
        Organize a single track file

        Args:
            file_path: Current file path
            track_context: Track metadata context
            library_root: Root directory of library
            file_id: Database file record ID
            track_id: Database track record ID
            album_id: Database album record ID
            artist_id: Database artist record ID
            recording_mbid: MusicBrainz Recording ID
            release_mbid: MusicBrainz Release ID
            job_id: Organization job ID

        Returns:
            FileOperationResult with operation details
        """
        try:
            # Calculate target path
            target_path = self.calculate_target_path(track_context, library_root)

            current_path = Path(file_path)

            # Check if file already in correct location
            if str(current_path) == target_path:
                logger.debug(f"File already organized: {file_path}")
                # Mark as organized in DB even though no move needed
                if file_id and not self.dry_run:
                    self._update_file_path_in_db(file_id, target_path)
                return FileOperationResult(
                    success=True,
                    operation_type=OperationType.MOVE,
                    source_path=file_path,
                    destination_path=target_path
                )

            logger.info(f"Organizing file: {file_path} -> {target_path}")

            # Dry run mode
            if self.dry_run:
                logger.info(f"[DRY RUN] Would move: {file_path} -> {target_path}")
                return FileOperationResult(
                    success=True,
                    operation_type=OperationType.MOVE,
                    source_path=file_path,
                    destination_path=target_path
                )

            # Execute move
            result = self.atomic_ops.move_file(
                source_path=file_path,
                destination_path=target_path,
                backup=True
            )

            # Log operation
            if self.audit_logger:
                self.audit_logger.log_operation(
                    operation_result=result,
                    file_id=file_id,
                    artist_id=artist_id,
                    album_id=album_id,
                    track_id=track_id,
                    recording_mbid=recording_mbid,
                    release_mbid=release_mbid,
                    job_id=job_id
                )

            # Update database if successful
            if result.success and file_id:
                self._update_file_path_in_db(file_id, target_path)

            return result

        except Exception as e:
            logger.error(f"Error organizing track file {file_path}: {e}")
            return FileOperationResult(
                success=False,
                operation_type=OperationType.MOVE,
                source_path=file_path,
                error_message=str(e)
            )

    def organize_artist_files(
        self,
        artist_id: UUID,
        library_root: str,
        job_id: Optional[UUID] = None
    ) -> OrganizationResult:
        """
        Organize all files for an artist

        Steps:
        1. Get all tracks for artist with MBIDs
        2. For each track with file_path:
           a. Generate target path using naming engine
           b. Compare with current path
           c. If different, move file
        3. Update database with new paths
        4. Log all operations

        Args:
            artist_id: Artist UUID
            library_root: Root directory of library
            job_id: Optional organization job ID

        Returns:
            OrganizationResult with statistics
        """
        result = OrganizationResult(success=True)

        try:
            # This would be implemented differently for Studio54 vs MUSE
            # Here's a generic structure:

            logger.info(f"Organizing files for artist {artist_id}")

            # Get artist details from database
            # This is a placeholder - actual implementation depends on schema
            artist_name = self._get_artist_name(artist_id)

            # Get all tracks with file paths
            tracks = self._get_artist_tracks(artist_id)
            result.files_total = len(tracks)

            logger.info(f"Found {result.files_total} tracks for artist {artist_name}")

            # Process each track
            for track in tracks:
                try:
                    # Build track context
                    track_context = self._build_track_context(track)

                    # Organize file
                    op_result = self.organize_track_file(
                        file_path=track['file_path'],
                        track_context=track_context,
                        library_root=library_root,
                        file_id=track.get('file_id'),
                        track_id=track.get('track_id'),
                        album_id=track.get('album_id'),
                        artist_id=artist_id,
                        recording_mbid=track.get('recording_mbid'),
                        release_mbid=track.get('release_mbid'),
                        job_id=job_id
                    )

                    result.files_processed += 1

                    if op_result.success:
                        if op_result.source_path != op_result.destination_path:
                            result.files_moved += 1
                    else:
                        result.files_failed += 1
                        result.failed_files.append({
                            'file_path': track['file_path'],
                            'error': op_result.error_message
                        })

                except Exception as e:
                    logger.error(f"Error organizing track {track.get('track_id')}: {e}")
                    result.files_failed += 1
                    result.failed_files.append({
                        'file_path': track.get('file_path', 'unknown'),
                        'error': str(e)
                    })

            result.success = result.files_failed == 0

            logger.info(
                f"Artist organization complete: {result.files_moved} moved, "
                f"{result.files_failed} failed out of {result.files_total}"
            )

            return result

        except Exception as e:
            logger.error(f"Error organizing artist {artist_id}: {e}")
            result.success = False
            result.error_message = str(e)
            return result

    def organize_album_files(
        self,
        album_id: UUID,
        library_root: str,
        create_metadata_file: bool = True,
        job_id: Optional[UUID] = None
    ) -> OrganizationResult:
        """
        Organize files for a specific album

        Args:
            album_id: Album UUID
            library_root: Root directory of library
            create_metadata_file: Create .mbid.json file
            job_id: Optional organization job ID

        Returns:
            OrganizationResult with statistics
        """
        result = OrganizationResult(success=True)

        try:
            logger.info(f"Organizing files for album {album_id}")

            # Get album details
            album_info = self._get_album_info(album_id)

            # Get all tracks
            tracks = self._get_album_tracks(album_id)
            result.files_total = len(tracks)

            # Process each track
            for track in tracks:
                try:
                    track_context = self._build_track_context(track)

                    op_result = self.organize_track_file(
                        file_path=track['file_path'],
                        track_context=track_context,
                        library_root=library_root,
                        file_id=track.get('file_id'),
                        track_id=track.get('track_id'),
                        album_id=album_id,
                        artist_id=track.get('artist_id'),
                        recording_mbid=track.get('recording_mbid'),
                        release_mbid=album_info.get('release_mbid'),
                        job_id=job_id
                    )

                    result.files_processed += 1

                    if op_result.success:
                        if op_result.source_path != op_result.destination_path:
                            result.files_moved += 1
                    else:
                        result.files_failed += 1
                        result.failed_files.append({
                            'file_path': track['file_path'],
                            'error': op_result.error_message
                        })

                except Exception as e:
                    logger.error(f"Error organizing track: {e}")
                    result.files_failed += 1

            result.success = result.files_failed == 0

            logger.info(f"Album organization complete: {result.files_moved} moved, {result.files_failed} failed")

            return result

        except Exception as e:
            logger.error(f"Error organizing album {album_id}: {e}")
            result.success = False
            result.error_message = str(e)
            return result

    def calculate_target_path(
        self,
        track_context: TrackContext,
        library_root: str
    ) -> str:
        """
        Calculate ideal file path for a track

        Uses:
        - Artist name
        - Album title and year
        - Track number and title
        - Disc number (if multi-disc)
        - File extension

        Args:
            track_context: Track metadata context
            library_root: Root directory of library

        Returns:
            Absolute path where file should be located
        """
        # Generate filename using naming engine
        filename = self.naming_engine.generate_track_filename(track_context)

        # Construct full path
        library_path = Path(library_root)
        target_path = library_path / filename

        return str(target_path)

    def validate_organization(
        self,
        artist_id: UUID,
        library_root: str
    ) -> ValidationResult:
        """
        Check if artist files are correctly organized

        Args:
            artist_id: Artist UUID
            library_root: Root directory of library

        Returns:
            ValidationResult with status and issues
        """
        result = ValidationResult(is_valid=True)

        try:
            # Get all tracks
            tracks = self._get_artist_tracks(artist_id)
            result.total_files = len(tracks)

            for track in tracks:
                # Calculate where file should be
                track_context = self._build_track_context(track)
                target_path = self.calculate_target_path(track_context, library_root)

                current_path = track.get('file_path', '')

                if current_path == target_path:
                    result.organized_files += 1
                else:
                    result.needs_organization += 1
                    result.issues.append({
                        'track_id': track.get('track_id'),
                        'track_title': track.get('track_title'),
                        'current_path': current_path,
                        'expected_path': target_path,
                        'issue_type': 'incorrect_location'
                    })

            result.is_valid = result.needs_organization == 0

            logger.info(
                f"Validation result: {result.organized_files}/{result.total_files} files correctly organized"
            )

            return result

        except Exception as e:
            logger.error(f"Error validating organization: {e}")
            result.is_valid = False
            return result

    def create_album_directory(
        self,
        album_context: AlbumContext,
        artist_context: ArtistContext,
        library_root: str
    ) -> Optional[str]:
        """
        Create album directory structure

        Args:
            album_context: Album metadata context
            artist_context: Artist metadata context
            library_root: Root directory of library

        Returns:
            Created directory path or None if failed
        """
        try:
            # Generate artist directory name
            artist_dir = self.naming_engine.generate_artist_directory(artist_context)

            # Generate album directory name
            album_dir = self.naming_engine.generate_album_directory(album_context)

            # Construct full path
            full_path = Path(library_root) / artist_dir / album_dir

            # Create directory
            if not self.dry_run:
                result = self.atomic_ops.create_directory(str(full_path))
                if result.success:
                    logger.info(f"Created album directory: {full_path}")
                    return str(full_path)
                else:
                    logger.error(f"Failed to create directory: {result.error_message}")
                    return None
            else:
                logger.info(f"[DRY RUN] Would create directory: {full_path}")
                return str(full_path)

        except Exception as e:
            logger.error(f"Error creating album directory: {e}")
            return None

    # ========================================
    # Private helper methods
    # ========================================

    def _get_artist_name(self, artist_id: UUID) -> str:
        """Get artist name from database"""
        # Placeholder - implement based on schema
        from sqlalchemy import text
        try:
            query = text("SELECT name FROM artists WHERE id = :artist_id")
            result = self.db.execute(query, {'artist_id': str(artist_id)}).first()
            return result[0] if result else "Unknown Artist"
        except:
            return "Unknown Artist"

    def _get_artist_tracks(self, artist_id: UUID) -> List[Dict[str, Any]]:
        """Get all tracks for an artist"""
        # Placeholder - implement based on schema
        # This would query tracks joined with albums, files, etc.
        return []

    def _get_album_info(self, album_id: UUID) -> Dict[str, Any]:
        """Get album information"""
        # Placeholder - implement based on schema
        return {}

    def _get_album_tracks(self, album_id: UUID) -> List[Dict[str, Any]]:
        """Get all tracks for an album"""
        # Placeholder - implement based on schema
        return []

    def _build_track_context(self, track: Dict[str, Any]) -> TrackContext:
        """Build TrackContext from database track record"""
        return TrackContext(
            artist_name=track.get('artist_name', 'Unknown Artist'),
            album_title=track.get('album_title', 'Unknown Album'),
            track_title=track.get('track_title', 'Unknown Track'),
            track_number=track.get('track_number', 1),
            release_year=track.get('release_year'),
            disc_number=track.get('disc_number', 1),
            total_discs=track.get('total_discs', 1),
            medium_format=track.get('medium_format', 'CD'),
            album_type=track.get('album_type', 'Album'),
            file_extension=track.get('file_extension', 'flac'),
            is_compilation=track.get('is_compilation', False)
        )

    def _update_file_path_in_db(self, file_id: UUID, new_path: str):
        """Update file path in database"""
        try:
            from sqlalchemy import text

            # Update for library_files (Studio54) or music_files (MUSE)
            # Try both tables
            queries = [
                text("UPDATE library_files SET file_path = :new_path, is_organized = true WHERE id = :file_id"),
                text("UPDATE music_files SET file_path = :new_path WHERE id = :file_id")
            ]

            for query in queries:
                try:
                    result = self.db.execute(query, {'file_id': str(file_id), 'new_path': new_path})
                    self.db.commit()
                    if result.rowcount > 0:
                        logger.debug(f"Updated file path in database: {file_id} -> {new_path}")
                        return
                except Exception:
                    self.db.rollback()
                    continue

        except Exception as e:
            logger.error(f"Error updating file path in database: {e}")
            self.db.rollback()

    def batch_organize_files(
        self,
        file_operations: List[Dict[str, Any]],
        job_id: Optional[UUID] = None
    ) -> OrganizationResult:
        """
        Organize multiple files in batch

        Args:
            file_operations: List of file operation dicts with track contexts
            job_id: Optional organization job ID

        Returns:
            OrganizationResult with statistics
        """
        result = OrganizationResult(success=True)
        result.files_total = len(file_operations)

        operation_results = []

        for op in file_operations:
            try:
                op_result = self.organize_track_file(
                    file_path=op['file_path'],
                    track_context=op['track_context'],
                    library_root=op['library_root'],
                    file_id=op.get('file_id'),
                    track_id=op.get('track_id'),
                    album_id=op.get('album_id'),
                    artist_id=op.get('artist_id'),
                    recording_mbid=op.get('recording_mbid'),
                    release_mbid=op.get('release_mbid'),
                    job_id=job_id
                )

                operation_results.append(op_result)
                result.files_processed += 1

                if op_result.success:
                    if op_result.source_path != op_result.destination_path:
                        result.files_moved += 1
                else:
                    result.files_failed += 1
                    result.failed_files.append({
                        'file_path': op['file_path'],
                        'error': op_result.error_message
                    })

            except Exception as e:
                logger.error(f"Error in batch operation: {e}")
                result.files_failed += 1
                result.failed_files.append({
                    'file_path': op.get('file_path', 'unknown'),
                    'error': str(e)
                })

        result.success = result.files_failed == 0

        logger.info(
            f"Batch organization complete: {result.files_moved} moved, "
            f"{result.files_failed} failed out of {result.files_total}"
        )

        return result
