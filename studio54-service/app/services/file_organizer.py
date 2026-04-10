"""
File Organization Service for Studio54
Lidarr-inspired file management with atomic operations

Handles:
- File moving/copying with transaction-like behavior
- Recycle bin for safe deletions
- Directory structure creation
- Permission management
- Duplicate file handling
"""

import shutil
import os
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Constants for atomic operations
CHECKSUM_CHUNK_SIZE = 8192  # 8KB chunks for checksum calculation
MAX_CHECKSUM_SIZE = 100 * 1024 * 1024  # Only checksum first 100MB for large files


class TransferMode(Enum):
    """File transfer mode."""
    MOVE = "move"
    COPY = "copy"
    HARDLINK = "hardlink"


class FileOperation(Enum):
    """Type of file operation."""
    IMPORT = "import"
    RENAME = "rename"
    UPGRADE = "upgrade"
    DELETE = "delete"


@dataclass
class FileTransferResult:
    """Result of a file transfer operation."""
    success: bool
    source_path: Path
    dest_path: Optional[Path] = None
    error: Optional[str] = None
    operation: Optional[FileOperation] = None
    backed_up: bool = False
    backup_path: Optional[Path] = None


class FileOrganizer:
    """
    Handles file organization operations with atomic guarantees.

    Improvements over Lidarr:
    - Transaction-like behavior with automatic rollback
    - Backup creation before destructive operations
    - Better error handling and logging
    """

    def __init__(
        self,
        music_library_path: Path,
        recycle_bin_path: Optional[Path] = None,
        use_hardlinks: bool = False,
        recycle_bin_days: int = 30,
    ):
        """
        Initialize the file organizer.

        Args:
            music_library_path: Root path for organized music library
            recycle_bin_path: Path for deleted files (None = permanent delete)
            use_hardlinks: Use hardlinks instead of copying (saves space)
            recycle_bin_days: Days to keep files in recycle bin before cleanup
        """
        self.music_library_path = Path(music_library_path)
        self.recycle_bin_path = Path(recycle_bin_path) if recycle_bin_path else None
        self.use_hardlinks = use_hardlinks
        self.recycle_bin_days = recycle_bin_days

        # Ensure music library exists
        self.music_library_path.mkdir(parents=True, exist_ok=True)

        # Ensure recycle bin exists
        if self.recycle_bin_path:
            self.recycle_bin_path.mkdir(parents=True, exist_ok=True)

    def import_file(
        self,
        source_path: Path,
        dest_relative_path: str,
        transfer_mode: TransferMode = TransferMode.MOVE,
        create_backup: bool = True,
    ) -> FileTransferResult:
        """
        Import a file into the music library.

        This is an atomic operation that will rollback on failure.

        Args:
            source_path: Path to source file
            dest_relative_path: Relative path within music library (e.g., "Artist/Album/01 - Track.flac")
            transfer_mode: How to transfer the file (move, copy, hardlink)
            create_backup: Create backup if destination exists

        Returns:
            FileTransferResult with operation details
        """
        source = Path(source_path)
        dest = self.music_library_path / dest_relative_path

        # Validate source exists
        if not source.exists():
            return FileTransferResult(
                success=False,
                source_path=source,
                error=f"Source file does not exist: {source}"
            )

        # Check if source and destination are the same
        if source.resolve() == dest.resolve():
            logger.info(f"Source and destination are identical, skipping: {source}")
            return FileTransferResult(
                success=True,
                source_path=source,
                dest_path=dest,
                operation=FileOperation.IMPORT
            )

        backup_path = None
        original_dest_existed = dest.exists()

        try:
            # Create destination directory
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Backup existing file if it exists
            if dest.exists() and create_backup:
                backup_path = dest.with_suffix(f'.backup.{datetime.now(timezone.utc).timestamp()}')
                logger.info(f"Creating backup: {dest} -> {backup_path}")
                shutil.move(str(dest), str(backup_path))

            # Transfer the file
            if transfer_mode == TransferMode.MOVE:
                logger.info(f"Moving file (copy-verify-delete): {source} -> {dest}")
                # Use copy-verify-delete pattern for safety
                # Step 1: Calculate source checksum
                source_checksum = self._calculate_checksum(source)
                logger.debug(f"Source checksum: {source_checksum}")

                # Step 2: Copy file to destination
                shutil.copy2(str(source), str(dest))

                # Step 3: Verify destination checksum matches
                dest_checksum = self._calculate_checksum(dest)
                logger.debug(f"Destination checksum: {dest_checksum}")

                if source_checksum != dest_checksum:
                    # Checksum mismatch - delete corrupted destination and raise error
                    if dest.exists():
                        dest.unlink()
                    raise IOError(
                        f"Checksum verification failed: source={source_checksum}, "
                        f"dest={dest_checksum}. File may be corrupted."
                    )

                # Step 4: Delete source only after successful verification
                try:
                    source.unlink()
                    logger.debug(f"Source file deleted after verified copy")
                except PermissionError:
                    logger.warning(f"Could not delete source (permission denied), copy verified OK: {source}")

            elif transfer_mode == TransferMode.COPY:
                logger.info(f"Copying file: {source} -> {dest}")
                shutil.copy2(str(source), str(dest))

            elif transfer_mode == TransferMode.HARDLINK:
                logger.info(f"Creating hardlink: {source} -> {dest}")
                try:
                    os.link(str(source), str(dest))
                except OSError as e:
                    # Hardlink failed (cross-device?), fall back to copy
                    logger.warning(f"Hardlink failed, falling back to copy: {e}")
                    shutil.copy2(str(source), str(dest))

            # Verify destination exists
            if not dest.exists():
                raise FileNotFoundError(f"Transfer completed but destination not found: {dest}")

            # Clean up backup on success
            if backup_path and backup_path.exists():
                logger.info(f"Removing backup after successful transfer: {backup_path}")
                backup_path.unlink()

            return FileTransferResult(
                success=True,
                source_path=source,
                dest_path=dest,
                operation=FileOperation.IMPORT,
                backed_up=backup_path is not None,
            )

        except Exception as e:
            logger.error(f"File import failed: {e}", exc_info=True)

            # Rollback: restore backup if we created one
            if backup_path and backup_path.exists():
                logger.info(f"Rolling back: restoring backup {backup_path} -> {dest}")
                try:
                    # Remove failed destination
                    if dest.exists():
                        dest.unlink()
                    # Restore backup
                    shutil.move(str(backup_path), str(dest))
                except Exception as rollback_error:
                    logger.error(f"Rollback failed: {rollback_error}", exc_info=True)

            # Rollback: restore source if we moved it
            if transfer_mode == TransferMode.MOVE and not source.exists() and dest.exists():
                logger.info(f"Rolling back: restoring source {dest} -> {source}")
                try:
                    shutil.move(str(dest), str(source))
                except Exception as rollback_error:
                    logger.error(f"Rollback failed: {rollback_error}", exc_info=True)

            return FileTransferResult(
                success=False,
                source_path=source,
                dest_path=dest,
                error=str(e),
                operation=FileOperation.IMPORT,
                backup_path=backup_path,
            )

    def rename_file(
        self,
        current_path: Path,
        new_relative_path: str,
    ) -> FileTransferResult:
        """
        Rename/move a file within the music library.

        Args:
            current_path: Current absolute path to file
            new_relative_path: New relative path within music library

        Returns:
            FileTransferResult with operation details
        """
        source = Path(current_path)
        dest = self.music_library_path / new_relative_path

        # Validate source exists and is within library
        if not source.exists():
            return FileTransferResult(
                success=False,
                source_path=source,
                error=f"Source file does not exist: {source}"
            )

        if not self._is_in_library(source):
            return FileTransferResult(
                success=False,
                source_path=source,
                error=f"Source file is not in music library: {source}"
            )

        # Use import_file with MOVE mode
        result = self.import_file(
            source_path=source,
            dest_relative_path=new_relative_path,
            transfer_mode=TransferMode.MOVE,
            create_backup=True,
        )
        result.operation = FileOperation.RENAME
        return result

    def delete_file(
        self,
        file_path: Path,
        use_recycle_bin: bool = True,
        subfolder: str = "",
    ) -> FileTransferResult:
        """
        Delete a file (move to recycle bin or permanent delete).

        Args:
            file_path: Path to file to delete
            use_recycle_bin: Move to recycle bin instead of permanent delete
            subfolder: Subfolder within recycle bin (e.g., "duplicates")

        Returns:
            FileTransferResult with operation details
        """
        source = Path(file_path)

        if not source.exists():
            return FileTransferResult(
                success=False,
                source_path=source,
                error=f"File does not exist: {source}"
            )

        try:
            if use_recycle_bin and self.recycle_bin_path:
                # Move to recycle bin
                dest_name = source.name
                dest_dir = self.recycle_bin_path / subfolder

                # Create destination directory
                dest_dir.mkdir(parents=True, exist_ok=True)

                # Handle filename collisions
                dest = dest_dir / dest_name
                counter = 1
                while dest.exists():
                    stem = source.stem
                    suffix = source.suffix
                    dest_name = f"{stem}_{counter}{suffix}"
                    dest = dest_dir / dest_name
                    counter += 1

                logger.info(f"Moving to recycle bin (copy-verify-delete): {source} -> {dest}")
                # Use copy-verify-delete pattern for safety
                source_checksum = self._calculate_checksum(source)
                shutil.copy2(str(source), str(dest))
                dest_checksum = self._calculate_checksum(dest)

                if source_checksum != dest_checksum:
                    if dest.exists():
                        dest.unlink()
                    raise IOError(
                        f"Checksum verification failed during recycle: source={source_checksum}, "
                        f"dest={dest_checksum}"
                    )

                # Delete source only after verified copy
                source.unlink()

                # Update timestamp
                dest.touch()

                return FileTransferResult(
                    success=True,
                    source_path=source,
                    dest_path=dest,
                    operation=FileOperation.DELETE,
                    backed_up=True,
                    backup_path=dest,
                )
            else:
                # Permanent delete
                logger.warning(f"Permanently deleting file: {source}")
                source.unlink()

                return FileTransferResult(
                    success=True,
                    source_path=source,
                    operation=FileOperation.DELETE,
                )

        except Exception as e:
            logger.error(f"File deletion failed: {e}", exc_info=True)
            return FileTransferResult(
                success=False,
                source_path=source,
                error=str(e),
                operation=FileOperation.DELETE,
            )

    def cleanup_recycle_bin(self) -> Dict[str, Any]:
        """
        Clean up old files from recycle bin.

        Removes files older than recycle_bin_days.

        Returns:
            Dictionary with cleanup statistics
        """
        if not self.recycle_bin_path or not self.recycle_bin_path.exists():
            return {'deleted_files': 0, 'deleted_size': 0}

        cutoff_time = datetime.now(timezone.utc).timestamp() - (self.recycle_bin_days * 86400)
        deleted_files = 0
        deleted_size = 0

        logger.info(f"Cleaning up recycle bin (older than {self.recycle_bin_days} days)")

        try:
            for file_path in self.recycle_bin_path.rglob('*'):
                if file_path.is_file():
                    # Check file age
                    file_mtime = file_path.stat().st_mtime
                    if file_mtime < cutoff_time:
                        size = file_path.stat().st_size
                        logger.debug(f"Deleting old file: {file_path}")
                        file_path.unlink()
                        deleted_files += 1
                        deleted_size += size

            # Remove empty directories
            for dir_path in sorted(self.recycle_bin_path.rglob('*'), reverse=True):
                if dir_path.is_dir() and not any(dir_path.iterdir()):
                    logger.debug(f"Removing empty directory: {dir_path}")
                    dir_path.rmdir()

            logger.info(
                f"Recycle bin cleanup complete: {deleted_files} files, "
                f"{deleted_size / 1024 / 1024:.2f} MB freed"
            )

            return {
                'deleted_files': deleted_files,
                'deleted_size': deleted_size,
            }

        except Exception as e:
            logger.error(f"Recycle bin cleanup failed: {e}", exc_info=True)
            return {
                'deleted_files': deleted_files,
                'deleted_size': deleted_size,
                'error': str(e),
            }

    def delete_empty_folders(
        self,
        root_path: Optional[Path] = None
    ) -> int:
        """
        Delete empty folders in music library.

        Args:
            root_path: Root path to start from (defaults to music_library_path)

        Returns:
            Number of folders deleted
        """
        if root_path is None:
            root_path = self.music_library_path

        deleted_count = 0

        try:
            # Walk bottom-up to delete child folders first
            for dir_path in sorted(Path(root_path).rglob('*'), reverse=True):
                if dir_path.is_dir() and dir_path != root_path:
                    # Check if directory is empty
                    if not any(dir_path.iterdir()):
                        logger.info(f"Deleting empty folder: {dir_path}")
                        dir_path.rmdir()
                        deleted_count += 1

            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} empty folders")

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to delete empty folders: {e}", exc_info=True)
            return deleted_count

    def get_library_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the music library.

        Returns:
            Dictionary with library statistics
        """
        try:
            total_files = 0
            total_size = 0
            total_dirs = 0

            for item in self.music_library_path.rglob('*'):
                if item.is_file():
                    total_files += 1
                    total_size += item.stat().st_size
                elif item.is_dir():
                    total_dirs += 1

            return {
                'total_files': total_files,
                'total_size': total_size,
                'total_size_mb': round(total_size / 1024 / 1024, 2),
                'total_size_gb': round(total_size / 1024 / 1024 / 1024, 2),
                'total_directories': total_dirs,
                'library_path': str(self.music_library_path),
            }

        except Exception as e:
            logger.error(f"Failed to get library stats: {e}", exc_info=True)
            return {'error': str(e)}

    def _is_in_library(self, path: Path) -> bool:
        """Check if a path is within the music library."""
        try:
            path.resolve().relative_to(self.music_library_path.resolve())
            return True
        except ValueError:
            return False

    def _calculate_checksum(self, file_path: Path, max_size: int = MAX_CHECKSUM_SIZE) -> str:
        """
        Calculate MD5 checksum of a file.

        For large files, only checksums the first max_size bytes for performance.

        Args:
            file_path: Path to the file
            max_size: Maximum bytes to read (default 100MB)

        Returns:
            MD5 hex digest string
        """
        md5 = hashlib.md5()
        bytes_read = 0

        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(CHECKSUM_CHUNK_SIZE)
                if not chunk:
                    break
                md5.update(chunk)
                bytes_read += len(chunk)
                if bytes_read >= max_size:
                    break

        return md5.hexdigest()

    def verify_file_integrity(self, file_path: Path) -> bool:
        """
        Verify a file's integrity (exists, readable, non-zero size).

        Args:
            file_path: Path to file to verify

        Returns:
            True if file is valid
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return False
            if not path.is_file():
                return False
            if path.stat().st_size == 0:
                return False
            # Try to open the file
            with path.open('rb') as f:
                f.read(1)
            return True
        except Exception as e:
            logger.warning(f"File integrity check failed for {file_path}: {e}")
            return False


def get_file_organizer(
    music_library_path: str,
    recycle_bin_path: Optional[str] = None,
    use_hardlinks: bool = False,
    recycle_bin_days: int = 30,
) -> FileOrganizer:
    """
    Factory function to create FileOrganizer instance.

    Args:
        music_library_path: Root path for music library
        recycle_bin_path: Path for recycle bin (optional)
        use_hardlinks: Use hardlinks for copying
        recycle_bin_days: Days to keep files in recycle bin

    Returns:
        FileOrganizer instance
    """
    return FileOrganizer(
        music_library_path=Path(music_library_path),
        recycle_bin_path=Path(recycle_bin_path) if recycle_bin_path else None,
        use_hardlinks=use_hardlinks,
        recycle_bin_days=recycle_bin_days,
    )
