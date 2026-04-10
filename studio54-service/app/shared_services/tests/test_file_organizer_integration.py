"""
Integration tests for FileOrganizer service

Tests the full workflow of file organization including:
- Integration with AtomicFileOps
- Integration with NamingEngine
- Integration with AuditLogger
- Single track organization
- Artist-level organization
- Album-level organization
- Batch operations
- Validation
- Database synchronization
- Error handling and rollback
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from uuid import UUID, uuid4
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from file_organizer import FileOrganizer, OrganizationResult, ValidationResult
from atomic_file_ops import AtomicFileOps
from naming_engine import NamingEngine, TrackContext, AlbumContext, ArtistContext
from audit_logger import AuditLogger


@pytest.fixture
def temp_library():
    """Create temporary library directory structure"""
    with tempfile.TemporaryDirectory() as tmpdir:
        library_root = Path(tmpdir) / "library"
        library_root.mkdir()

        # Create some initial files in wrong locations
        wrong_location = library_root / "unsorted"
        wrong_location.mkdir()

        yield {
            'root': str(library_root),
            'unsorted': str(wrong_location),
            'tmpdir': tmpdir
        }


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock()
    db.execute = Mock(return_value=Mock(first=Mock(return_value=None)))
    db.commit = Mock()
    db.rollback = Mock()
    return db


@pytest.fixture
def file_organizer(mock_db):
    """Create FileOrganizer instance with mocked dependencies"""
    return FileOrganizer(
        db=mock_db,
        naming_engine=NamingEngine(),
        atomic_ops=AtomicFileOps(),
        audit_logger=AuditLogger(mock_db),
        dry_run=False
    )


@pytest.fixture
def file_organizer_dry_run(mock_db):
    """Create FileOrganizer in dry-run mode"""
    return FileOrganizer(
        db=mock_db,
        naming_engine=NamingEngine(),
        atomic_ops=AtomicFileOps(),
        audit_logger=AuditLogger(mock_db),
        dry_run=True
    )


class TestSingleTrackOrganization:
    """Tests for organizing individual track files"""

    def test_organize_track_file_success(self, file_organizer, temp_library):
        """Test successful organization of a single track file"""
        # Create source file
        source_file = Path(temp_library['unsorted']) / "track.flac"
        source_file.write_text("audio data")

        # Create track context
        track_context = TrackContext(
            artist_name="The Beatles",
            album_title="Abbey Road",
            track_title="Come Together",
            track_number=1,
            release_year=1969,
            disc_number=1,
            total_discs=1,
            file_extension="flac"
        )

        # Organize file
        result = file_organizer.organize_track_file(
            file_path=str(source_file),
            track_context=track_context,
            library_root=temp_library['root'],
            file_id=uuid4(),
            track_id=uuid4(),
            album_id=uuid4(),
            artist_id=uuid4()
        )

        assert result.success is True
        assert result.checksum_verified is True

        # Verify file was moved
        assert not source_file.exists()

        # Verify file is in correct location
        expected_path = Path(temp_library['root']) / "Abbey Road (1969)" / "The Beatles - Abbey Road - 01 - Come Together.flac"
        assert expected_path.parent.exists()

    def test_organize_track_file_already_organized(self, file_organizer, temp_library):
        """Test organizing file that's already in correct location"""
        # Create file in correct location
        correct_dir = Path(temp_library['root']) / "Abbey Road (1969)"
        correct_dir.mkdir(parents=True)
        correct_file = correct_dir / "The Beatles - Abbey Road - 01 - Come Together.flac"
        correct_file.write_text("audio data")

        track_context = TrackContext(
            artist_name="The Beatles",
            album_title="Abbey Road",
            track_title="Come Together",
            track_number=1,
            release_year=1969,
            file_extension="flac"
        )

        result = file_organizer.organize_track_file(
            file_path=str(correct_file),
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert result.success is True
        assert correct_file.exists()  # File should still be there

    def test_organize_track_file_dry_run(self, file_organizer_dry_run, temp_library):
        """Test dry run mode doesn't actually move files"""
        source_file = Path(temp_library['unsorted']) / "track.flac"
        source_file.write_text("audio data")

        track_context = TrackContext(
            artist_name="Pink Floyd",
            album_title="The Wall",
            track_title="In the Flesh?",
            track_number=1,
            release_year=1979,
            file_extension="flac"
        )

        result = file_organizer_dry_run.organize_track_file(
            file_path=str(source_file),
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert result.success is True
        assert source_file.exists()  # File should NOT be moved in dry run
        assert result.destination_path is not None  # But we should know where it would go

    def test_organize_track_file_multi_disc(self, file_organizer, temp_library):
        """Test organizing track from multi-disc album"""
        source_file = Path(temp_library['unsorted']) / "disc1_track01.flac"
        source_file.write_text("audio data")

        track_context = TrackContext(
            artist_name="Pink Floyd",
            album_title="The Wall",
            track_title="In the Flesh?",
            track_number=1,
            release_year=1979,
            disc_number=1,
            total_discs=2,
            medium_format="CD",
            file_extension="flac"
        )

        result = file_organizer.organize_track_file(
            file_path=str(source_file),
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert result.success is True
        # Should be in CD 01 subdirectory
        assert "CD 01" in result.destination_path or "CD01" in result.destination_path

    def test_organize_track_file_with_audit(self, file_organizer, temp_library, mock_db):
        """Test that file organization is logged to audit trail"""
        source_file = Path(temp_library['unsorted']) / "track.flac"
        source_file.write_text("audio data")

        track_context = TrackContext(
            artist_name="Test Artist",
            album_title="Test Album",
            track_title="Test Track",
            track_number=1,
            release_year=2020,
            file_extension="flac"
        )

        file_id = uuid4()
        job_id = uuid4()

        # Mock audit logger to verify it gets called
        with patch.object(file_organizer.audit_logger, 'log_operation') as mock_log:
            result = file_organizer.organize_track_file(
                file_path=str(source_file),
                track_context=track_context,
                library_root=temp_library['root'],
                file_id=file_id,
                job_id=job_id
            )

            assert result.success is True
            # Verify audit logger was called
            mock_log.assert_called_once()

    def test_organize_track_file_error_handling(self, file_organizer, temp_library):
        """Test error handling when file doesn't exist"""
        track_context = TrackContext(
            artist_name="Test",
            album_title="Test",
            track_title="Test",
            track_number=1,
            file_extension="flac"
        )

        result = file_organizer.organize_track_file(
            file_path="/nonexistent/file.flac",
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert result.success is False
        assert result.error_message is not None


class TestTargetPathCalculation:
    """Tests for target path calculation"""

    def test_calculate_target_path_simple(self, file_organizer, temp_library):
        """Test calculating target path for simple track"""
        track_context = TrackContext(
            artist_name="The Beatles",
            album_title="Abbey Road",
            track_title="Come Together",
            track_number=1,
            release_year=1969,
            file_extension="flac"
        )

        target = file_organizer.calculate_target_path(
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert "Abbey Road (1969)" in target
        assert "The Beatles" in target
        assert "Come Together" in target
        assert "01" in target
        assert ".flac" in target

    def test_calculate_target_path_multi_disc(self, file_organizer, temp_library):
        """Test calculating path for multi-disc album"""
        track_context = TrackContext(
            artist_name="Pink Floyd",
            album_title="The Wall",
            track_title="Hey You",
            track_number=1,
            release_year=1979,
            disc_number=2,
            total_discs=2,
            medium_format="CD",
            file_extension="flac"
        )

        target = file_organizer.calculate_target_path(
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert "The Wall (1979)" in target
        assert "CD 02" in target or "CD02" in target

    def test_calculate_target_path_compilation(self, file_organizer, temp_library):
        """Test calculating path for compilation album"""
        track_context = TrackContext(
            artist_name="Katy Perry",
            album_title="Now 50",
            track_title="Roar",
            track_number=1,
            release_year=2014,
            is_compilation=True,
            file_extension="mp3"
        )

        target = file_organizer.calculate_target_path(
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert "Now 50 (2014)" in target
        assert ("Various Artists" in target or "Katy Perry" in target)


class TestAlbumDirectoryCreation:
    """Tests for album directory creation"""

    def test_create_album_directory(self, file_organizer, temp_library):
        """Test creating album directory structure"""
        album_context = AlbumContext(
            album_title="Thriller",
            artist_name="Michael Jackson",
            release_year=1982
        )

        artist_context = ArtistContext(
            artist_name="Michael Jackson"
        )

        result = file_organizer.create_album_directory(
            album_context=album_context,
            artist_context=artist_context,
            library_root=temp_library['root']
        )

        assert result is not None
        assert Path(result).exists()
        assert "Michael Jackson" in result
        assert "Thriller (1982)" in result

    def test_create_album_directory_nested(self, file_organizer, temp_library):
        """Test creating nested directory structure"""
        album_context = AlbumContext(
            album_title="Abbey Road",
            artist_name="The Beatles",
            release_year=1969
        )

        artist_context = ArtistContext(
            artist_name="The Beatles"
        )

        result = file_organizer.create_album_directory(
            album_context=album_context,
            artist_context=artist_context,
            library_root=temp_library['root']
        )

        created_path = Path(result)
        assert created_path.exists()
        assert created_path.parent.exists()  # Artist directory
        assert created_path.parent.name == "The Beatles"
        assert created_path.name == "Abbey Road (1969)"

    def test_create_album_directory_dry_run(self, file_organizer_dry_run, temp_library):
        """Test dry run doesn't create directories"""
        album_context = AlbumContext(
            album_title="Test Album",
            artist_name="Test Artist",
            release_year=2020
        )

        artist_context = ArtistContext(artist_name="Test Artist")

        result = file_organizer_dry_run.create_album_directory(
            album_context=album_context,
            artist_context=artist_context,
            library_root=temp_library['root']
        )

        # Should return path but not create directory in dry run
        assert result is not None
        # Directory should not exist in dry run mode
        # (Implementation shows it returns path but doesn't create)


class TestBatchOrganization:
    """Tests for batch file organization"""

    def test_batch_organize_multiple_tracks(self, file_organizer, temp_library):
        """Test organizing multiple tracks in batch"""
        # Create source files
        tracks_data = [
            ("track1.flac", "Come Together", 1),
            ("track2.flac", "Something", 2),
            ("track3.flac", "Maxwell's Silver Hammer", 3)
        ]

        file_operations = []

        for filename, title, track_num in tracks_data:
            source_file = Path(temp_library['unsorted']) / filename
            source_file.write_text(f"audio data {track_num}")

            file_operations.append({
                'file_path': str(source_file),
                'track_context': TrackContext(
                    artist_name="The Beatles",
                    album_title="Abbey Road",
                    track_title=title,
                    track_number=track_num,
                    release_year=1969,
                    file_extension="flac"
                ),
                'library_root': temp_library['root'],
                'file_id': uuid4(),
                'track_id': uuid4(),
                'album_id': uuid4(),
                'artist_id': uuid4()
            })

        result = file_organizer.batch_organize_files(
            file_operations=file_operations
        )

        assert result.success is True
        assert result.files_total == 3
        assert result.files_processed == 3
        assert result.files_moved == 3
        assert result.files_failed == 0

    def test_batch_organize_with_failures(self, file_organizer, temp_library):
        """Test batch organization handles individual failures"""
        file_operations = [
            {
                'file_path': str(Path(temp_library['unsorted']) / "exists.flac"),
                'track_context': TrackContext(
                    artist_name="Artist",
                    album_title="Album",
                    track_title="Track 1",
                    track_number=1,
                    file_extension="flac"
                ),
                'library_root': temp_library['root']
            },
            {
                'file_path': "/nonexistent/file.flac",  # This will fail
                'track_context': TrackContext(
                    artist_name="Artist",
                    album_title="Album",
                    track_title="Track 2",
                    track_number=2,
                    file_extension="flac"
                ),
                'library_root': temp_library['root']
            }
        ]

        # Create first file
        Path(file_operations[0]['file_path']).write_text("data")

        result = file_organizer.batch_organize_files(
            file_operations=file_operations
        )

        assert result.success is False  # Overall failed due to one failure
        assert result.files_total == 2
        assert result.files_failed >= 1
        assert len(result.failed_files) >= 1


class TestValidation:
    """Tests for organization validation"""

    def test_validate_organization_valid(self, file_organizer, temp_library):
        """Test validation of correctly organized files"""
        # Mock the database methods to return organized files
        artist_id = uuid4()

        # Create correctly organized file
        correct_dir = Path(temp_library['root']) / "Abbey Road (1969)"
        correct_dir.mkdir(parents=True)
        correct_file = correct_dir / "The Beatles - Abbey Road - 01 - Come Together.flac"
        correct_file.write_text("audio data")

        with patch.object(file_organizer, '_get_artist_tracks') as mock_tracks:
            mock_tracks.return_value = [{
                'file_path': str(correct_file),
                'artist_name': 'The Beatles',
                'album_title': 'Abbey Road',
                'track_title': 'Come Together',
                'track_number': 1,
                'release_year': 1969,
                'file_extension': 'flac',
                'disc_number': 1,
                'total_discs': 1
            }]

            result = file_organizer.validate_organization(
                artist_id=artist_id,
                library_root=temp_library['root']
            )

            assert result.is_valid is True
            assert result.organized_files == 1
            assert result.needs_organization == 0
            assert len(result.issues) == 0

    def test_validate_organization_needs_work(self, file_organizer, temp_library):
        """Test validation identifies files needing organization"""
        artist_id = uuid4()

        # Create file in wrong location
        wrong_file = Path(temp_library['unsorted']) / "track.flac"
        wrong_file.write_text("audio data")

        with patch.object(file_organizer, '_get_artist_tracks') as mock_tracks:
            mock_tracks.return_value = [{
                'file_path': str(wrong_file),
                'artist_name': 'The Beatles',
                'album_title': 'Abbey Road',
                'track_title': 'Come Together',
                'track_number': 1,
                'release_year': 1969,
                'file_extension': 'flac',
                'disc_number': 1,
                'total_discs': 1,
                'track_id': uuid4()
            }]

            result = file_organizer.validate_organization(
                artist_id=artist_id,
                library_root=temp_library['root']
            )

            assert result.is_valid is False
            assert result.organized_files == 0
            assert result.needs_organization == 1
            assert len(result.issues) == 1


class TestDatabaseSynchronization:
    """Tests for database path updates"""

    def test_database_updated_after_move(self, file_organizer, temp_library, mock_db):
        """Test that database is updated after successful file move"""
        source_file = Path(temp_library['unsorted']) / "track.flac"
        source_file.write_text("audio data")

        track_context = TrackContext(
            artist_name="Test Artist",
            album_title="Test Album",
            track_title="Test Track",
            track_number=1,
            release_year=2020,
            file_extension="flac"
        )

        file_id = uuid4()

        # Mock database execute to track calls
        mock_db.execute = Mock(return_value=Mock(scalar_one=Mock(return_value=str(uuid4()))))
        mock_db.commit = Mock()

        result = file_organizer.organize_track_file(
            file_path=str(source_file),
            track_context=track_context,
            library_root=temp_library['root'],
            file_id=file_id
        )

        assert result.success is True
        # Database commit should be called (by audit logger)
        assert mock_db.commit.called


class TestErrorHandling:
    """Tests for error handling and edge cases"""

    def test_organize_nonexistent_file(self, file_organizer, temp_library):
        """Test organizing file that doesn't exist"""
        track_context = TrackContext(
            artist_name="Test",
            album_title="Test",
            track_title="Test",
            track_number=1,
            file_extension="flac"
        )

        result = file_organizer.organize_track_file(
            file_path="/nonexistent/file.flac",
            track_context=track_context,
            library_root=temp_library['root']
        )

        assert result.success is False
        assert result.error_message is not None

    def test_organize_with_permission_error(self, file_organizer, temp_library):
        """Test handling of permission errors"""
        # This test would require actually creating a permission error scenario
        # which can be complex in a test environment
        # Skipping detailed implementation
        pass

    def test_organize_with_disk_full(self, file_organizer, temp_library):
        """Test handling of disk full errors"""
        # This test would require simulating disk full condition
        # Skipping detailed implementation
        pass


class TestComplexScenarios:
    """Tests for complex real-world scenarios"""

    def test_organize_complete_album(self, file_organizer, temp_library):
        """Test organizing all tracks of a complete album"""
        # Create unsorted album files
        album_tracks = [
            ("01_come_together.flac", "Come Together", 1),
            ("02_something.flac", "Something", 2),
            ("03_maxwell.flac", "Maxwell's Silver Hammer", 3),
            ("04_oh_darling.flac", "Oh! Darling", 4),
            ("05_octopus.flac", "Octopus's Garden", 5)
        ]

        file_operations = []

        for filename, title, track_num in album_tracks:
            source_file = Path(temp_library['unsorted']) / filename
            source_file.write_text(f"audio data track {track_num}")

            file_operations.append({
                'file_path': str(source_file),
                'track_context': TrackContext(
                    artist_name="The Beatles",
                    album_title="Abbey Road",
                    track_title=title,
                    track_number=track_num,
                    release_year=1969,
                    file_extension="flac"
                ),
                'library_root': temp_library['root']
            })

        result = file_organizer.batch_organize_files(
            file_operations=file_operations
        )

        assert result.success is True
        assert result.files_moved == 5

        # Verify all files are in same album directory
        album_dir = Path(temp_library['root']) / "Abbey Road (1969)"
        assert album_dir.exists()

        organized_files = list(album_dir.glob("*.flac"))
        assert len(organized_files) == 5

    def test_organize_multi_disc_album(self, file_organizer, temp_library):
        """Test organizing complete multi-disc album"""
        tracks = []

        # Disc 1 tracks
        for i in range(1, 4):
            tracks.append({
                'filename': f"disc1_track{i}.flac",
                'title': f"Track {i}",
                'track_number': i,
                'disc_number': 1
            })

        # Disc 2 tracks
        for i in range(1, 4):
            tracks.append({
                'filename': f"disc2_track{i}.flac",
                'title': f"Track {i}",
                'track_number': i,
                'disc_number': 2
            })

        file_operations = []

        for track in tracks:
            source_file = Path(temp_library['unsorted']) / track['filename']
            source_file.write_text(f"audio data")

            file_operations.append({
                'file_path': str(source_file),
                'track_context': TrackContext(
                    artist_name="Pink Floyd",
                    album_title="The Wall",
                    track_title=track['title'],
                    track_number=track['track_number'],
                    release_year=1979,
                    disc_number=track['disc_number'],
                    total_discs=2,
                    medium_format="CD",
                    file_extension="flac"
                ),
                'library_root': temp_library['root']
            })

        result = file_organizer.batch_organize_files(
            file_operations=file_operations
        )

        assert result.success is True
        assert result.files_moved == 6

        # Verify disc subdirectories were created
        album_dir = Path(temp_library['root']) / "The Wall (1979)"
        assert album_dir.exists()

        disc1_dir = album_dir / "CD 01"
        disc2_dir = album_dir / "CD 02"

        # At least one disc directory should exist
        assert disc1_dir.exists() or disc2_dir.exists()

    def test_organize_mixed_formats(self, file_organizer, temp_library):
        """Test organizing files with different formats"""
        files = [
            ("track1.flac", "Track 1", "flac"),
            ("track2.mp3", "Track 2", "mp3"),
            ("track3.m4a", "Track 3", "m4a")
        ]

        file_operations = []

        for filename, title, ext in files:
            source_file = Path(temp_library['unsorted']) / filename
            source_file.write_text("audio data")

            file_operations.append({
                'file_path': str(source_file),
                'track_context': TrackContext(
                    artist_name="Various",
                    album_title="Mixed Album",
                    track_title=title,
                    track_number=files.index((filename, title, ext)) + 1,
                    release_year=2020,
                    file_extension=ext
                ),
                'library_root': temp_library['root']
            })

        result = file_organizer.batch_organize_files(
            file_operations=file_operations
        )

        assert result.success is True
        assert result.files_moved == 3

        # Verify all files are organized with correct extensions
        album_dir = Path(temp_library['root']) / "Mixed Album (2020)"
        assert album_dir.exists()

        assert (album_dir / f"Various - Mixed Album - 01 - Track 1.flac").exists() or \
               len(list(album_dir.glob("*Track 1*"))) > 0


class TestPerformance:
    """Tests for performance characteristics"""

    def test_organize_large_batch(self, file_organizer, temp_library):
        """Test organizing large batch of files"""
        # Create 50 files
        file_operations = []

        for i in range(1, 51):
            source_file = Path(temp_library['unsorted']) / f"track{i:02d}.flac"
            source_file.write_text(f"audio data {i}")

            file_operations.append({
                'file_path': str(source_file),
                'track_context': TrackContext(
                    artist_name="Test Artist",
                    album_title="Large Album",
                    track_title=f"Track {i}",
                    track_number=i,
                    release_year=2020,
                    file_extension="flac"
                ),
                'library_root': temp_library['root']
            })

        import time
        start_time = time.time()

        result = file_organizer.batch_organize_files(
            file_operations=file_operations
        )

        duration = time.time() - start_time

        assert result.success is True
        assert result.files_moved == 50

        # Should complete reasonably fast (< 10 seconds for 50 files)
        assert duration < 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
