"""
Atomic File Operations Service

Provides safe file operations with automatic rollback capability:
- Copy-verify-delete pattern for file moves
- Automatic backup before modification
- Checksum verification
- Transaction-based batch operations
- Recycle bin for deleted files
"""

import os
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


class OperationType(Enum):
    """File operation types"""
    MOVE = "move"
    RENAME = "rename"
    DELETE = "delete"
    COPY = "copy"
    MKDIR = "mkdir"


@dataclass
class FileOperationResult:
    """Result of a file operation"""
    success: bool
    operation_type: OperationType
    source_path: str
    destination_path: Optional[str] = None
    backup_path: Optional[str] = None
    error_message: Optional[str] = None
    checksum_verified: bool = False
    bytes_transferred: int = 0
    duration_ms: int = 0


@dataclass
class BatchOperationResult:
    """Result of a batch file operation"""
    success: bool
    total_operations: int
    successful_operations: int
    failed_operations: int
    operations: List[FileOperationResult]
    rollback_performed: bool = False
    error_message: Optional[str] = None


class AtomicFileOps:
    """
    Service for executing file operations safely with automatic rollback

    Features:
    - Copy-verify-delete pattern (never direct move)
    - Automatic backup before destructive operations
    - SHA-256 checksum verification
    - Transaction-based batch operations
    - Recycle bin for deleted files (30 day retention)
    - Automatic rollback on failure
    """

    def __init__(
        self,
        backup_dir: str = "/tmp/file_ops_backups",
        recycle_bin_dir: str = "/tmp/file_ops_recycle",
        recycle_retention_days: int = 30,
        verification_method: str = "checksum"  # "checksum" or "timestamp"
    ):
        """
        Initialize AtomicFileOps service

        Args:
            backup_dir: Directory for temporary backups
            recycle_bin_dir: Directory for deleted files
            recycle_retention_days: Days to keep files in recycle bin
            verification_method: Method to verify file copies ("checksum" or "timestamp")
        """
        self.backup_dir = Path(backup_dir)
        self.recycle_bin_dir = Path(recycle_bin_dir)
        self.recycle_retention_days = recycle_retention_days
        self.verification_method = verification_method

        # Ensure directories exist
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.recycle_bin_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"AtomicFileOps initialized: backup_dir={backup_dir}, recycle_bin={recycle_bin_dir}")

    def move_file(
        self,
        source_path: str,
        destination_path: str,
        backup: bool = False,  # No backup by default - validate move instead
        overwrite: bool = False
    ) -> FileOperationResult:
        """
        Move file using copy-verify-delete pattern

        Steps:
        1. Verify source exists and is readable
        2. Create backup if requested (disabled by default)
        3. Create destination directory if needed
        4. Copy to destination
        5. Verify checksums match (MANDATORY validation)
        6. Delete source only if validation passes
        7. Clean up backup if used

        On failure:
        - Delete incomplete destination
        - Restore from backup if available
        - Log error details

        Args:
            source_path: Source file path
            destination_path: Destination file path
            backup: Create backup before operation (default: False - rely on validation)
            overwrite: Overwrite destination if exists

        Returns:
            FileOperationResult with operation details
        """
        start_time = datetime.now()
        backup_path = None

        try:
            source = Path(source_path)
            destination = Path(destination_path)

            # Validate source
            if not source.exists():
                return FileOperationResult(
                    success=False,
                    operation_type=OperationType.MOVE,
                    source_path=source_path,
                    destination_path=destination_path,
                    error_message=f"Source file does not exist: {source_path}"
                )

            if not source.is_file():
                return FileOperationResult(
                    success=False,
                    operation_type=OperationType.MOVE,
                    source_path=source_path,
                    destination_path=destination_path,
                    error_message=f"Source is not a file: {source_path}"
                )

            # Check if destination exists
            if destination.exists() and not overwrite:
                return FileOperationResult(
                    success=False,
                    operation_type=OperationType.MOVE,
                    source_path=source_path,
                    destination_path=destination_path,
                    error_message=f"Destination already exists: {destination_path}"
                )

            # Create backup if requested
            if backup:
                backup_path = self._create_backup(source_path)
                logger.debug(f"Created backup: {backup_path}")

            # Create destination directory
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Calculate source checksum
            source_checksum = self._calculate_checksum(source_path)
            source_size = source.stat().st_size

            # Copy file with retry logic for checksum failures
            MAX_COPY_RETRIES = 3
            RETRY_DELAY_SECONDS = 1
            copy_verified = False
            last_error = None

            for attempt in range(1, MAX_COPY_RETRIES + 1):
                # Copy file
                logger.debug(f"Copying {source_path} to {destination_path} (attempt {attempt}/{MAX_COPY_RETRIES})")

                # Remove any partial copy from previous attempt
                if destination.exists():
                    destination.unlink()

                shutil.copy2(source, destination)

                # Verify copy
                if self._verify_copy(source_path, destination_path, source_checksum):
                    copy_verified = True
                    if attempt > 1:
                        logger.info(f"Copy verification succeeded on attempt {attempt} for {source_path}")
                    break
                else:
                    last_error = f"Checksum verification failed (attempt {attempt}/{MAX_COPY_RETRIES})"
                    logger.warning(f"{last_error} for {source_path}")

                    if attempt < MAX_COPY_RETRIES:
                        # Wait before retry - helps with network/disk issues
                        import time
                        time.sleep(RETRY_DELAY_SECONDS)
                        # Re-read source checksum in case file was being written to
                        source_checksum = self._calculate_checksum(source_path)

            if not copy_verified:
                # All retries failed - cleanup and abort
                destination.unlink(missing_ok=True)
                return FileOperationResult(
                    success=False,
                    operation_type=OperationType.MOVE,
                    source_path=source_path,
                    destination_path=destination_path,
                    backup_path=str(backup_path) if backup_path else None,
                    error_message=f"Checksum verification failed after {MAX_COPY_RETRIES} attempts",
                    checksum_verified=False
                )

            # Delete source
            logger.debug(f"Deleting source: {source_path}")
            source.unlink()

            # Clean up backup
            if backup_path:
                self._cleanup_backup(backup_path)

            duration = (datetime.now() - start_time).total_seconds() * 1000

            logger.info(f"Successfully moved file: {source_path} -> {destination_path} ({source_size} bytes, {duration:.0f}ms)")

            return FileOperationResult(
                success=True,
                operation_type=OperationType.MOVE,
                source_path=source_path,
                destination_path=destination_path,
                backup_path=str(backup_path) if backup_path else None,
                checksum_verified=True,
                bytes_transferred=source_size,
                duration_ms=int(duration)
            )

        except Exception as e:
            logger.error(f"Error moving file {source_path} to {destination_path}: {e}")

            # Attempt cleanup and rollback
            try:
                # Remove incomplete destination
                if destination_path and Path(destination_path).exists():
                    Path(destination_path).unlink()

                # Restore from backup if source was deleted
                if backup_path and not Path(source_path).exists():
                    shutil.copy2(backup_path, source_path)
                    logger.info(f"Restored file from backup: {source_path}")
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup/rollback: {cleanup_error}")

            duration = (datetime.now() - start_time).total_seconds() * 1000

            return FileOperationResult(
                success=False,
                operation_type=OperationType.MOVE,
                source_path=source_path,
                destination_path=destination_path,
                backup_path=str(backup_path) if backup_path else None,
                error_message=str(e),
                duration_ms=int(duration)
            )

    def rename_file(
        self,
        file_path: str,
        new_name: str,
        backup: bool = False  # No backup by default - rely on validation
    ) -> FileOperationResult:
        """
        Rename file in place

        Args:
            file_path: Current file path
            new_name: New filename (without directory)
            backup: Create backup before operation

        Returns:
            FileOperationResult with operation details
        """
        try:
            file = Path(file_path)
            new_path = file.parent / new_name

            return self.move_file(
                source_path=str(file),
                destination_path=str(new_path),
                backup=backup
            )

        except Exception as e:
            logger.error(f"Error renaming file {file_path} to {new_name}: {e}")
            return FileOperationResult(
                success=False,
                operation_type=OperationType.RENAME,
                source_path=file_path,
                error_message=str(e)
            )

    def delete_file(
        self,
        file_path: str,
        use_recycle_bin: bool = True
    ) -> FileOperationResult:
        """
        Delete file (move to recycle bin by default)

        Args:
            file_path: File to delete
            use_recycle_bin: Move to recycle bin instead of permanent delete

        Returns:
            FileOperationResult with operation details
        """
        start_time = datetime.now()

        try:
            file = Path(file_path)

            if not file.exists():
                return FileOperationResult(
                    success=False,
                    operation_type=OperationType.DELETE,
                    source_path=file_path,
                    error_message=f"File does not exist: {file_path}"
                )

            if use_recycle_bin:
                # Move to recycle bin
                recycle_path = self._get_recycle_path(file_path)
                recycle_path.parent.mkdir(parents=True, exist_ok=True)

                shutil.move(str(file), str(recycle_path))

                logger.info(f"Moved file to recycle bin: {file_path} -> {recycle_path}")

                duration = (datetime.now() - start_time).total_seconds() * 1000

                return FileOperationResult(
                    success=True,
                    operation_type=OperationType.DELETE,
                    source_path=file_path,
                    destination_path=str(recycle_path),
                    duration_ms=int(duration)
                )
            else:
                # Permanent delete
                file.unlink()

                logger.info(f"Permanently deleted file: {file_path}")

                duration = (datetime.now() - start_time).total_seconds() * 1000

                return FileOperationResult(
                    success=True,
                    operation_type=OperationType.DELETE,
                    source_path=file_path,
                    duration_ms=int(duration)
                )

        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")
            duration = (datetime.now() - start_time).total_seconds() * 1000
            return FileOperationResult(
                success=False,
                operation_type=OperationType.DELETE,
                source_path=file_path,
                error_message=str(e),
                duration_ms=int(duration)
            )

    def create_directory(
        self,
        directory_path: str,
        parents: bool = True
    ) -> FileOperationResult:
        """
        Create directory structure recursively

        Args:
            directory_path: Directory to create
            parents: Create parent directories if needed

        Returns:
            FileOperationResult with operation details
        """
        try:
            directory = Path(directory_path)
            directory.mkdir(parents=parents, exist_ok=True)

            logger.debug(f"Created directory: {directory_path}")

            return FileOperationResult(
                success=True,
                operation_type=OperationType.MKDIR,
                source_path=directory_path
            )

        except Exception as e:
            logger.error(f"Error creating directory {directory_path}: {e}")
            return FileOperationResult(
                success=False,
                operation_type=OperationType.MKDIR,
                source_path=directory_path,
                error_message=str(e)
            )

    def batch_operations(
        self,
        operations: List[Dict[str, Any]],
        rollback_on_failure: bool = True
    ) -> BatchOperationResult:
        """
        Execute multiple file operations atomically

        If rollback_on_failure=True, all operations are reversed if any fail.

        Args:
            operations: List of operation dicts with keys:
                        - operation: "move", "rename", "delete", "mkdir"
                        - Additional parameters for the operation
            rollback_on_failure: Rollback all operations if any fail

        Returns:
            BatchOperationResult with overall results
        """
        results: List[FileOperationResult] = []
        successful_ops: List[FileOperationResult] = []

        try:
            # Execute all operations
            for op in operations:
                operation_type = op.get('operation')

                if operation_type == 'move':
                    result = self.move_file(
                        source_path=op['source'],
                        destination_path=op['destination'],
                        backup=op.get('backup', True)
                    )
                elif operation_type == 'rename':
                    result = self.rename_file(
                        file_path=op['file_path'],
                        new_name=op['new_name'],
                        backup=op.get('backup', True)
                    )
                elif operation_type == 'delete':
                    result = self.delete_file(
                        file_path=op['file_path'],
                        use_recycle_bin=op.get('use_recycle_bin', True)
                    )
                elif operation_type == 'mkdir':
                    result = self.create_directory(
                        directory_path=op['directory_path']
                    )
                else:
                    result = FileOperationResult(
                        success=False,
                        operation_type=OperationType.MOVE,
                        source_path="",
                        error_message=f"Unknown operation type: {operation_type}"
                    )

                results.append(result)

                if result.success:
                    successful_ops.append(result)
                elif rollback_on_failure:
                    # Operation failed - rollback all successful operations
                    logger.warning(f"Operation failed, rolling back {len(successful_ops)} successful operations")
                    self._rollback_operations(successful_ops)

                    return BatchOperationResult(
                        success=False,
                        total_operations=len(operations),
                        successful_operations=0,
                        failed_operations=len(operations),
                        operations=results,
                        rollback_performed=True,
                        error_message=result.error_message
                    )

            # All operations successful
            successful_count = sum(1 for r in results if r.success)
            failed_count = len(results) - successful_count

            return BatchOperationResult(
                success=failed_count == 0,
                total_operations=len(operations),
                successful_operations=successful_count,
                failed_operations=failed_count,
                operations=results
            )

        except Exception as e:
            logger.error(f"Error in batch operations: {e}")

            # Rollback if requested
            if rollback_on_failure and successful_ops:
                self._rollback_operations(successful_ops)

            return BatchOperationResult(
                success=False,
                total_operations=len(operations),
                successful_operations=0,
                failed_operations=len(operations),
                operations=results,
                rollback_performed=rollback_on_failure,
                error_message=str(e)
            )

    def cleanup_recycle_bin(self) -> Dict[str, int]:
        """
        Clean up old files from recycle bin

        Removes files older than recycle_retention_days

        Returns:
            Dict with cleanup statistics
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=self.recycle_retention_days)
            deleted_count = 0
            total_size = 0

            for item in self.recycle_bin_dir.rglob('*'):
                if item.is_file():
                    mtime = datetime.fromtimestamp(item.stat().st_mtime)
                    if mtime < cutoff_date:
                        size = item.stat().st_size
                        item.unlink()
                        deleted_count += 1
                        total_size += size

            # Remove empty directories
            for item in sorted(self.recycle_bin_dir.rglob('*'), reverse=True):
                if item.is_dir() and not any(item.iterdir()):
                    item.rmdir()

            logger.info(f"Cleaned up recycle bin: deleted {deleted_count} files ({total_size} bytes)")

            return {
                'files_deleted': deleted_count,
                'bytes_freed': total_size
            }

        except Exception as e:
            logger.error(f"Error cleaning up recycle bin: {e}")
            return {
                'files_deleted': 0,
                'bytes_freed': 0,
                'error': str(e)
            }

    # ========================================
    # Private helper methods
    # ========================================

    def _calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA-256 checksum of file"""
        sha256 = hashlib.sha256()

        with open(file_path, 'rb') as f:
            while True:
                data = f.read(65536)  # 64KB chunks
                if not data:
                    break
                sha256.update(data)

        return sha256.hexdigest()

    def _verify_copy(
        self,
        source_path: str,
        destination_path: str,
        expected_checksum: Optional[str] = None
    ) -> bool:
        """Verify file was copied correctly"""
        try:
            if self.verification_method == "checksum":
                dest_checksum = self._calculate_checksum(destination_path)
                source_checksum = expected_checksum or self._calculate_checksum(source_path)
                return dest_checksum == source_checksum
            else:
                # Timestamp and size verification
                source = Path(source_path)
                dest = Path(destination_path)
                return (source.stat().st_size == dest.stat().st_size and
                        abs(source.stat().st_mtime - dest.stat().st_mtime) < 2)
        except Exception as e:
            logger.error(f"Error verifying copy: {e}")
            return False

    def _create_backup(self, file_path: str) -> Path:
        """Create backup of file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = Path(file_path).name
        backup_path = self.backup_dir / f"{timestamp}_{filename}"
        shutil.copy2(file_path, backup_path)
        return backup_path

    def _cleanup_backup(self, backup_path: Path):
        """Remove backup file"""
        try:
            if backup_path.exists():
                backup_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to cleanup backup {backup_path}: {e}")

    def _get_recycle_path(self, file_path: str) -> Path:
        """Generate path in recycle bin"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = Path(file_path).name
        return self.recycle_bin_dir / timestamp / filename

    def _rollback_operations(self, operations: List[FileOperationResult]):
        """Rollback a list of successful operations"""
        for op in reversed(operations):
            try:
                if op.operation_type == OperationType.MOVE:
                    # Move file back to source
                    if op.destination_path and Path(op.destination_path).exists():
                        if op.backup_path and Path(op.backup_path).exists():
                            shutil.copy2(op.backup_path, op.source_path)
                            Path(op.destination_path).unlink()
                        else:
                            shutil.move(op.destination_path, op.source_path)
                    logger.debug(f"Rolled back move: {op.destination_path} -> {op.source_path}")

                elif op.operation_type == OperationType.DELETE:
                    # Restore from recycle bin
                    if op.destination_path and Path(op.destination_path).exists():
                        shutil.move(op.destination_path, op.source_path)
                    logger.debug(f"Rolled back delete: restored {op.source_path}")

                elif op.operation_type == OperationType.MKDIR:
                    # Remove directory if empty
                    dir_path = Path(op.source_path)
                    if dir_path.exists() and dir_path.is_dir() and not any(dir_path.iterdir()):
                        dir_path.rmdir()
                    logger.debug(f"Rolled back mkdir: removed {op.source_path}")

            except Exception as e:
                logger.error(f"Error rolling back operation: {e}")
