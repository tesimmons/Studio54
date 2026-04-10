"""
Unit tests for AtomicFileOps service

Tests cover:
- Successful file moves
- Copy verification failures
- Rollback on error
- Backup creation and restoration
- Directory creation
- Batch operations
- Concurrent access
- Recycle bin operations
- Edge cases
"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from atomic_file_ops import AtomicFileOps, FileOperationResult, OperationType


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        source_dir = test_dir / "source"
        dest_dir = test_dir / "destination"
        backup_dir = test_dir / "backups"
        recycle_dir = test_dir / "recycle"

        source_dir.mkdir()
        dest_dir.mkdir()

        yield {
            'source': source_dir,
            'dest': dest_dir,
            'backup': backup_dir,
            'recycle': recycle_dir,
            'root': test_dir
        }


@pytest.fixture
def file_ops(temp_dirs):
    """Create AtomicFileOps instance with test directories"""
    return AtomicFileOps(
        backup_dir=str(temp_dirs['backup']),
        recycle_bin_dir=str(temp_dirs['recycle']),
        recycle_retention_days=30,
        verification_method="checksum"
    )


class TestFileMove:
    """Tests for move_file operation"""

    def test_successful_move(self, file_ops, temp_dirs):
        """Test successful file move with checksum verification"""
        # Create source file
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Hello World")

        dest_file = temp_dirs['dest'] / "test.txt"

        # Move file
        result = file_ops.move_file(str(source_file), str(dest_file))

        assert result.success is True
        assert result.operation_type == OperationType.MOVE
        assert result.checksum_verified is True
        assert result.bytes_transferred == 11
        assert not source_file.exists()
        assert dest_file.exists()
        assert dest_file.read_text() == "Hello World"

    def test_move_creates_destination_directory(self, file_ops, temp_dirs):
        """Test that move creates destination directory if needed"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Test content")

        dest_file = temp_dirs['dest'] / "subdir" / "nested" / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file))

        assert result.success is True
        assert dest_file.exists()
        assert dest_file.parent.exists()

    def test_move_with_backup(self, file_ops, temp_dirs):
        """Test that backup is created during move"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Important data")

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file), backup=True)

        assert result.success is True
        assert result.backup_path is not None
        # Backup should be cleaned up after successful move
        assert not Path(result.backup_path).exists()

    def test_move_without_backup(self, file_ops, temp_dirs):
        """Test move without backup creation"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Data")

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file), backup=False)

        assert result.success is True
        assert result.backup_path is None

    def test_move_source_not_exists(self, file_ops, temp_dirs):
        """Test error when source file doesn't exist"""
        source_file = temp_dirs['source'] / "nonexistent.txt"
        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file))

        assert result.success is False
        assert "does not exist" in result.error_message.lower()

    def test_move_destination_exists_no_overwrite(self, file_ops, temp_dirs):
        """Test error when destination exists and overwrite=False"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Source")

        dest_file = temp_dirs['dest'] / "test.txt"
        dest_file.write_text("Existing")

        result = file_ops.move_file(str(source_file), str(dest_file), overwrite=False)

        assert result.success is False
        assert "already exists" in result.error_message.lower()
        assert source_file.exists()  # Source unchanged
        assert dest_file.read_text() == "Existing"  # Dest unchanged

    def test_move_with_overwrite(self, file_ops, temp_dirs):
        """Test successful overwrite of existing destination"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("New content")

        dest_file = temp_dirs['dest'] / "test.txt"
        dest_file.write_text("Old content")

        result = file_ops.move_file(str(source_file), str(dest_file), overwrite=True)

        assert result.success is True
        assert dest_file.read_text() == "New content"

    def test_move_source_is_directory(self, file_ops, temp_dirs):
        """Test error when source is a directory"""
        source_dir = temp_dirs['source'] / "subdir"
        source_dir.mkdir()

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_dir), str(dest_file))

        assert result.success is False
        assert "not a file" in result.error_message.lower()

    @patch('shared-services.atomic_file_ops.AtomicFileOps._verify_copy')
    def test_move_verification_failure(self, mock_verify, file_ops, temp_dirs):
        """Test rollback when checksum verification fails"""
        mock_verify.return_value = False

        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Test data")

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file))

        assert result.success is False
        assert "verification failed" in result.error_message.lower()
        assert result.checksum_verified is False
        assert source_file.exists()  # Source not deleted
        assert not dest_file.exists()  # Dest cleaned up

    @patch('shutil.copy2')
    def test_move_rollback_on_copy_error(self, mock_copy, file_ops, temp_dirs):
        """Test rollback when copy fails"""
        mock_copy.side_effect = IOError("Disk full")

        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Data")

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file), backup=True)

        assert result.success is False
        assert "disk full" in result.error_message.lower()
        assert source_file.exists()  # Source still exists


class TestFileRename:
    """Tests for rename_file operation"""

    def test_successful_rename(self, file_ops, temp_dirs):
        """Test successful file rename"""
        old_file = temp_dirs['source'] / "old_name.txt"
        old_file.write_text("Content")

        result = file_ops.rename_file(str(old_file), "new_name.txt")

        new_file = temp_dirs['source'] / "new_name.txt"

        assert result.success is True
        assert result.operation_type == OperationType.MOVE
        assert not old_file.exists()
        assert new_file.exists()
        assert new_file.read_text() == "Content"

    def test_rename_preserves_directory(self, file_ops, temp_dirs):
        """Test that rename keeps file in same directory"""
        subdir = temp_dirs['source'] / "subdir"
        subdir.mkdir()

        old_file = subdir / "old.txt"
        old_file.write_text("Data")

        result = file_ops.rename_file(str(old_file), "new.txt")

        new_file = subdir / "new.txt"

        assert result.success is True
        assert new_file.exists()
        assert new_file.parent == subdir


class TestFileDelete:
    """Tests for delete_file operation"""

    def test_delete_to_recycle_bin(self, file_ops, temp_dirs):
        """Test file moved to recycle bin"""
        file_to_delete = temp_dirs['source'] / "delete_me.txt"
        file_to_delete.write_text("To be deleted")

        result = file_ops.delete_file(str(file_to_delete), use_recycle_bin=True)

        assert result.success is True
        assert result.operation_type == OperationType.DELETE
        assert not file_to_delete.exists()
        assert result.destination_path is not None
        assert Path(result.destination_path).exists()

    def test_permanent_delete(self, file_ops, temp_dirs):
        """Test permanent file deletion"""
        file_to_delete = temp_dirs['source'] / "permanent.txt"
        file_to_delete.write_text("Gone forever")

        result = file_ops.delete_file(str(file_to_delete), use_recycle_bin=False)

        assert result.success is True
        assert not file_to_delete.exists()
        assert result.destination_path is None

    def test_delete_nonexistent_file(self, file_ops, temp_dirs):
        """Test error when deleting nonexistent file"""
        result = file_ops.delete_file(str(temp_dirs['source'] / "ghost.txt"))

        assert result.success is False
        assert "does not exist" in result.error_message.lower()


class TestDirectoryCreation:
    """Tests for create_directory operation"""

    def test_create_directory(self, file_ops, temp_dirs):
        """Test simple directory creation"""
        new_dir = temp_dirs['root'] / "new_directory"

        result = file_ops.create_directory(str(new_dir))

        assert result.success is True
        assert result.operation_type == OperationType.MKDIR
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_create_nested_directories(self, file_ops, temp_dirs):
        """Test nested directory creation"""
        nested_dir = temp_dirs['root'] / "level1" / "level2" / "level3"

        result = file_ops.create_directory(str(nested_dir), parents=True)

        assert result.success is True
        assert nested_dir.exists()

    def test_create_existing_directory(self, file_ops, temp_dirs):
        """Test creating already existing directory (should succeed)"""
        existing_dir = temp_dirs['source']

        result = file_ops.create_directory(str(existing_dir))

        assert result.success is True


class TestBatchOperations:
    """Tests for batch_operations"""

    def test_batch_move_success(self, file_ops, temp_dirs):
        """Test batch move of multiple files"""
        # Create source files
        files = []
        for i in range(5):
            f = temp_dirs['source'] / f"file{i}.txt"
            f.write_text(f"Content {i}")
            files.append(f)

        operations = [
            {
                'operation': 'move',
                'source': str(f),
                'destination': str(temp_dirs['dest'] / f.name)
            }
            for f in files
        ]

        result = file_ops.batch_operations(operations)

        assert result.success is True
        assert result.total_operations == 5
        assert result.successful_operations == 5
        assert result.failed_operations == 0

        # Verify all files moved
        for f in files:
            assert not f.exists()
            assert (temp_dirs['dest'] / f.name).exists()

    def test_batch_mixed_operations(self, file_ops, temp_dirs):
        """Test batch with different operation types"""
        # Setup
        move_file = temp_dirs['source'] / "move.txt"
        move_file.write_text("Move me")

        rename_file = temp_dirs['source'] / "old.txt"
        rename_file.write_text("Rename me")

        delete_file = temp_dirs['source'] / "delete.txt"
        delete_file.write_text("Delete me")

        operations = [
            {
                'operation': 'move',
                'source': str(move_file),
                'destination': str(temp_dirs['dest'] / "moved.txt")
            },
            {
                'operation': 'rename',
                'file_path': str(rename_file),
                'new_name': 'new.txt'
            },
            {
                'operation': 'delete',
                'file_path': str(delete_file)
            },
            {
                'operation': 'mkdir',
                'directory_path': str(temp_dirs['root'] / "new_dir")
            }
        ]

        result = file_ops.batch_operations(operations)

        assert result.success is True
        assert result.successful_operations == 4

    def test_batch_rollback_on_failure(self, file_ops, temp_dirs):
        """Test that batch operations rollback on failure"""
        # Create source files
        file1 = temp_dirs['source'] / "file1.txt"
        file1.write_text("File 1")

        file2 = temp_dirs['source'] / "file2.txt"
        file2.write_text("File 2")

        operations = [
            {
                'operation': 'move',
                'source': str(file1),
                'destination': str(temp_dirs['dest'] / "file1.txt")
            },
            {
                'operation': 'move',
                'source': str(temp_dirs['source'] / "nonexistent.txt"),  # This will fail
                'destination': str(temp_dirs['dest'] / "fail.txt")
            },
            {
                'operation': 'move',
                'source': str(file2),
                'destination': str(temp_dirs['dest'] / "file2.txt")
            }
        ]

        result = file_ops.batch_operations(operations, rollback_on_failure=True)

        assert result.success is False
        assert result.rollback_performed is True
        # All files should be back in original location
        assert file1.exists()
        assert file2.exists()

    def test_batch_no_rollback_on_failure(self, file_ops, temp_dirs):
        """Test batch continues without rollback when rollback_on_failure=False"""
        file1 = temp_dirs['source'] / "file1.txt"
        file1.write_text("File 1")

        operations = [
            {
                'operation': 'move',
                'source': str(file1),
                'destination': str(temp_dirs['dest'] / "file1.txt")
            },
            {
                'operation': 'move',
                'source': str(temp_dirs['source'] / "nonexistent.txt"),
                'destination': str(temp_dirs['dest'] / "fail.txt")
            }
        ]

        result = file_ops.batch_operations(operations, rollback_on_failure=False)

        assert result.success is False
        assert result.successful_operations == 1
        assert result.failed_operations == 1
        assert result.rollback_performed is False
        # First file should still be moved
        assert not file1.exists()
        assert (temp_dirs['dest'] / "file1.txt").exists()


class TestChecksumVerification:
    """Tests for checksum calculation and verification"""

    def test_checksum_calculation(self, file_ops, temp_dirs):
        """Test SHA-256 checksum calculation"""
        test_file = temp_dirs['source'] / "test.txt"
        test_file.write_text("Test content for checksum")

        checksum = file_ops._calculate_checksum(str(test_file))

        assert checksum is not None
        assert len(checksum) == 64  # SHA-256 hex digest length

    def test_checksum_verification_success(self, file_ops, temp_dirs):
        """Test successful checksum verification"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Identical content")

        dest_file = temp_dirs['dest'] / "test.txt"
        shutil.copy2(source_file, dest_file)

        source_checksum = file_ops._calculate_checksum(str(source_file))
        result = file_ops._verify_copy(str(source_file), str(dest_file), source_checksum)

        assert result is True

    def test_checksum_verification_failure(self, file_ops, temp_dirs):
        """Test checksum verification detects corruption"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Original content")

        dest_file = temp_dirs['dest'] / "test.txt"
        dest_file.write_text("Modified content")  # Different content

        source_checksum = file_ops._calculate_checksum(str(source_file))
        result = file_ops._verify_copy(str(source_file), str(dest_file), source_checksum)

        assert result is False


class TestRecycleBin:
    """Tests for recycle bin functionality"""

    def test_recycle_bin_path_generation(self, file_ops, temp_dirs):
        """Test unique recycle bin path generation"""
        file_path = "/path/to/file.txt"

        recycle_path = file_ops._get_recycle_path(file_path)

        assert recycle_path.name == "file.txt"
        assert str(recycle_path).startswith(str(temp_dirs['recycle']))

    def test_cleanup_recycle_bin(self, file_ops, temp_dirs):
        """Test recycle bin cleanup removes old files"""
        import time
        from datetime import datetime, timedelta

        # Create old file in recycle bin
        old_dir = temp_dirs['recycle'] / "20200101_120000"
        old_dir.mkdir(parents=True)
        old_file = old_dir / "old.txt"
        old_file.write_text("Old file")

        # Set modification time to 60 days ago
        old_timestamp = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_file, (old_timestamp, old_timestamp))

        # Create recent file
        recent_dir = temp_dirs['recycle'] / "20260110_120000"
        recent_dir.mkdir(parents=True)
        recent_file = recent_dir / "recent.txt"
        recent_file.write_text("Recent file")

        result = file_ops.cleanup_recycle_bin()

        assert result['files_deleted'] == 1
        assert not old_file.exists()
        assert recent_file.exists()


class TestEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_move_large_file(self, file_ops, temp_dirs):
        """Test moving a large file (>1MB)"""
        large_file = temp_dirs['source'] / "large.bin"

        # Create 2MB file
        with open(large_file, 'wb') as f:
            f.write(b'0' * (2 * 1024 * 1024))

        dest_file = temp_dirs['dest'] / "large.bin"

        result = file_ops.move_file(str(large_file), str(dest_file))

        assert result.success is True
        assert result.bytes_transferred == 2 * 1024 * 1024

    def test_move_empty_file(self, file_ops, temp_dirs):
        """Test moving an empty file"""
        empty_file = temp_dirs['source'] / "empty.txt"
        empty_file.touch()

        dest_file = temp_dirs['dest'] / "empty.txt"

        result = file_ops.move_file(str(empty_file), str(dest_file))

        assert result.success is True
        assert result.bytes_transferred == 0

    def test_move_special_characters_filename(self, file_ops, temp_dirs):
        """Test moving file with special characters in name"""
        special_file = temp_dirs['source'] / "file with spaces & (parens).txt"
        special_file.write_text("Special")

        dest_file = temp_dirs['dest'] / "file with spaces & (parens).txt"

        result = file_ops.move_file(str(special_file), str(dest_file))

        assert result.success is True
        assert dest_file.exists()

    def test_move_unicode_filename(self, file_ops, temp_dirs):
        """Test moving file with Unicode characters"""
        unicode_file = temp_dirs['source'] / "файл_тест_🎵.txt"
        unicode_file.write_text("Unicode content")

        dest_file = temp_dirs['dest'] / "файл_тест_🎵.txt"

        result = file_ops.move_file(str(unicode_file), str(dest_file))

        assert result.success is True
        assert dest_file.exists()


class TestBackupAndRestore:
    """Tests for backup and restore functionality"""

    def test_backup_creation(self, file_ops, temp_dirs):
        """Test that backup is created correctly"""
        test_file = temp_dirs['source'] / "test.txt"
        test_file.write_text("Important data")

        backup_path = file_ops._create_backup(str(test_file))

        assert backup_path.exists()
        assert backup_path.read_text() == "Important data"
        assert "test.txt" in backup_path.name

    def test_backup_cleanup(self, file_ops, temp_dirs):
        """Test backup cleanup after successful operation"""
        test_file = temp_dirs['source'] / "test.txt"
        test_file.write_text("Data")

        backup_path = file_ops._create_backup(str(test_file))
        assert backup_path.exists()

        file_ops._cleanup_backup(backup_path)

        assert not backup_path.exists()


class TestOperationResults:
    """Tests for operation result tracking"""

    def test_result_includes_timing(self, file_ops, temp_dirs):
        """Test that operation results include timing information"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Time me")

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file))

        assert result.duration_ms >= 0
        assert isinstance(result.duration_ms, int)

    def test_result_includes_all_paths(self, file_ops, temp_dirs):
        """Test that result includes source, dest, and backup paths"""
        source_file = temp_dirs['source'] / "test.txt"
        source_file.write_text("Paths")

        dest_file = temp_dirs['dest'] / "test.txt"

        result = file_ops.move_file(str(source_file), str(dest_file), backup=True)

        assert result.source_path == str(source_file)
        assert result.destination_path == str(dest_file)
        assert result.backup_path is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=atomic_file_ops", "--cov-report=term-missing"])
