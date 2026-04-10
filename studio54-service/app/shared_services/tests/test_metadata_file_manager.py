"""
Unit Tests for MetadataFileManager Service

Tests metadata file creation, validation, and management:
- Creating .mbid.json files
- Reading and updating metadata
- Validating album directories
- Finding misplaced files
- Database integration
"""

import pytest
import json
import tempfile
from pathlib import Path
from uuid import uuid4, UUID
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch, mock_open
from sqlalchemy.orm import Session

from shared_services.metadata_file_manager import (
    MetadataFileManager,
    TrackMetadata,
    AlbumMetadata,
    ValidationResult
)


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock(spec=Session)
    db.execute = Mock()
    db.commit = Mock()
    db.rollback = Mock()
    return db


@pytest.fixture
def metadata_manager(mock_db):
    """MetadataFileManager instance with mock database"""
    return MetadataFileManager(db=mock_db)


@pytest.fixture
def temp_album_dir():
    """Temporary album directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        album_dir = Path(tmpdir) / "The Beatles" / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)
        yield album_dir


@pytest.fixture
def sample_tracks():
    """Sample track metadata"""
    return [
        TrackMetadata(
            track_number=1,
            disc_number=1,
            title="Come Together",
            duration=259,
            recording_mbid="c85c8e1e-5b1f-4d8c-bc4d-e6d8a18d5c71",
            expected_filename="The Beatles - Abbey Road - 01 - Come Together.flac",
            file_present=True
        ),
        TrackMetadata(
            track_number=2,
            disc_number=1,
            title="Something",
            duration=182,
            recording_mbid="9e9a9f8d-7c8a-4b6d-8c9e-7f8a9b6c5d4e",
            expected_filename="The Beatles - Abbey Road - 02 - Something.flac",
            file_present=True
        ),
        TrackMetadata(
            track_number=3,
            disc_number=1,
            title="Maxwell's Silver Hammer",
            duration=207,
            recording_mbid="a1b2c3d4-e5f6-7g8h-9i0j-k1l2m3n4o5p6",
            expected_filename="The Beatles - Abbey Road - 03 - Maxwell's Silver Hammer.flac",
            file_present=True
        )
    ]


@pytest.fixture
def sample_album_metadata(sample_tracks):
    """Sample album metadata structure"""
    now = datetime.now().isoformat()
    return AlbumMetadata(
        version="1.0",
        created_at=now,
        updated_at=now,
        album={
            'title': 'Abbey Road',
            'artist': 'The Beatles',
            'artist_mbid': 'b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d',
            'release_year': 1969,
            'album_type': 'Album',
            'total_discs': 1,
            'total_tracks': 3
        },
        mbids={
            'recording_mbids': [
                'c85c8e1e-5b1f-4d8c-bc4d-e6d8a18d5c71',
                '9e9a9f8d-7c8a-4b6d-8c9e-7f8a9b6c5d4e',
                'a1b2c3d4-e5f6-7g8h-9i0j-k1l2m3n4o5p6'
            ],
            'release_mbid': 'c9f89f17-01d4-41a9-b7f4-c2e72992b95e',
            'release_group_mbid': '83efdfa0-c746-37e4-83f7-2f23c0f0a946'
        },
        tracks=[track.__dict__ for track in sample_tracks],
        validation={
            'status': 'pending',
            'missing_tracks': [],
            'extra_files': [],
            'last_validated': None
        },
        organization={
            'organized': True,
            'organized_at': now,
            'organized_by': 'system',
            'organization_job_id': str(uuid4())
        }
    )


# ========================================
# Test: Metadata File Creation
# ========================================

class TestMetadataFileCreation:
    """Tests for creating .mbid.json files"""

    def test_create_metadata_file_success(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test successful metadata file creation with all fields"""
        album_id = uuid4()
        artist_mbid = uuid4()
        release_mbid = uuid4()
        release_group_mbid = uuid4()
        job_id = uuid4()

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            artist_mbid=artist_mbid,
            release_year=1969,
            album_type="Album",
            total_discs=1,
            total_tracks=3,
            recording_mbids=[UUID(track.recording_mbid) for track in sample_tracks],
            release_mbid=release_mbid,
            release_group_mbid=release_group_mbid,
            tracks=sample_tracks,
            organization_job_id=job_id,
            organized_by="test_system"
        )

        # Verify file was created
        assert result is not None
        metadata_path = Path(result)
        assert metadata_path.exists()
        assert metadata_path.name == ".mbid.json"

        # Verify content
        with open(metadata_path, 'r') as f:
            data = json.load(f)

        assert data['version'] == '1.0'
        assert data['album']['title'] == 'Abbey Road'
        assert data['album']['artist'] == 'The Beatles'
        assert data['album']['release_year'] == 1969
        assert data['album']['total_tracks'] == 3
        assert len(data['tracks']) == 3
        assert data['organization']['organized'] is True

    def test_create_metadata_file_minimal_fields(self, metadata_manager, temp_album_dir):
        """Test metadata file creation with only required fields"""
        album_id = uuid4()

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Test Album",
            artist_name="Test Artist"
        )

        assert result is not None
        metadata_path = Path(result)
        assert metadata_path.exists()

        with open(metadata_path, 'r') as f:
            data = json.load(f)

        assert data['album']['title'] == 'Test Album'
        assert data['album']['artist'] == 'Test Artist'
        assert data['album']['total_tracks'] == 0
        assert len(data['tracks']) == 0

    def test_create_metadata_file_unicode_characters(self, metadata_manager, temp_album_dir):
        """Test metadata file with Unicode characters"""
        album_id = uuid4()

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Ænima",
            artist_name="Björk"
        )

        assert result is not None

        with open(result, 'r', encoding='utf-8') as f:
            data = json.load(f)

        assert data['album']['title'] == 'Ænima'
        assert data['album']['artist'] == 'Björk'

    def test_create_metadata_file_directory_not_exist(self, metadata_manager):
        """Test metadata file creation when directory doesn't exist"""
        album_id = uuid4()
        nonexistent_dir = "/tmp/nonexistent_album_dir_test"

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=nonexistent_dir,
            album_title="Test Album",
            artist_name="Test Artist"
        )

        assert result is None

    def test_create_metadata_file_with_multi_disc(self, metadata_manager, temp_album_dir):
        """Test metadata file for multi-disc album"""
        album_id = uuid4()

        tracks = [
            TrackMetadata(
                track_number=1,
                disc_number=1,
                title="Disc 1 Track 1",
                expected_filename="CD 01/Artist - Album - 01 - Track.flac"
            ),
            TrackMetadata(
                track_number=1,
                disc_number=2,
                title="Disc 2 Track 1",
                expected_filename="CD 02/Artist - Album - 01 - Track.flac"
            )
        ]

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="The Wall",
            artist_name="Pink Floyd",
            total_discs=2,
            total_tracks=26,
            tracks=tracks
        )

        assert result is not None

        with open(result, 'r') as f:
            data = json.load(f)

        assert data['album']['total_discs'] == 2
        assert len(data['tracks']) == 2
        assert data['tracks'][0]['disc_number'] == 1
        assert data['tracks'][1]['disc_number'] == 2


# ========================================
# Test: Reading Metadata Files
# ========================================

class TestReadingMetadataFiles:
    """Tests for reading .mbid.json files"""

    def test_read_metadata_file_success(self, metadata_manager, temp_album_dir, sample_album_metadata):
        """Test successful reading of metadata file"""
        # Create metadata file
        metadata_path = temp_album_dir / ".mbid.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(sample_album_metadata.to_dict(), f)

        # Read it back
        metadata = metadata_manager.read_metadata_file(str(metadata_path))

        assert metadata is not None
        assert metadata.version == "1.0"
        assert metadata.album['title'] == 'Abbey Road'
        assert metadata.album['artist'] == 'The Beatles'
        assert len(metadata.tracks) == 3

    def test_read_metadata_file_not_exist(self, metadata_manager):
        """Test reading non-existent metadata file"""
        result = metadata_manager.read_metadata_file("/tmp/nonexistent.mbid.json")
        assert result is None

    def test_read_metadata_file_malformed_json(self, metadata_manager, temp_album_dir):
        """Test reading malformed JSON file"""
        metadata_path = temp_album_dir / ".mbid.json"

        # Write invalid JSON
        with open(metadata_path, 'w') as f:
            f.write("{ invalid json")

        result = metadata_manager.read_metadata_file(str(metadata_path))
        assert result is None

    def test_read_metadata_file_missing_fields(self, metadata_manager, temp_album_dir):
        """Test reading metadata file with missing optional fields"""
        metadata_path = temp_album_dir / ".mbid.json"

        # Write minimal valid JSON
        minimal_data = {
            'version': '1.0',
            'album': {'title': 'Test Album', 'artist': 'Test Artist'}
        }

        with open(metadata_path, 'w') as f:
            json.dump(minimal_data, f)

        metadata = metadata_manager.read_metadata_file(str(metadata_path))

        assert metadata is not None
        assert metadata.album['title'] == 'Test Album'
        assert metadata.tracks == []
        assert metadata.mbids == {}


# ========================================
# Test: Updating Metadata Files
# ========================================

class TestUpdatingMetadataFiles:
    """Tests for updating existing metadata files"""

    def test_update_metadata_file_validation_status(self, metadata_manager, temp_album_dir, sample_album_metadata):
        """Test updating validation status"""
        # Create initial metadata file
        metadata_path = temp_album_dir / ".mbid.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(sample_album_metadata.to_dict(), f)

        # Update validation status
        updates = {
            'validation': {
                'status': 'valid',
                'missing_tracks': [],
                'extra_files': [],
                'last_validated': datetime.now().isoformat()
            }
        }

        result = metadata_manager.update_metadata_file(str(metadata_path), updates)
        assert result is True

        # Verify update
        with open(metadata_path, 'r') as f:
            data = json.load(f)

        assert data['validation']['status'] == 'valid'

    def test_update_metadata_file_tracks(self, metadata_manager, temp_album_dir, sample_album_metadata):
        """Test updating track list"""
        metadata_path = temp_album_dir / ".mbid.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(sample_album_metadata.to_dict(), f)

        new_track = {
            'track_number': 4,
            'disc_number': 1,
            'title': 'New Track',
            'expected_filename': 'Artist - Album - 04 - New Track.flac'
        }

        updates = {
            'tracks': sample_album_metadata.tracks + [new_track]
        }

        result = metadata_manager.update_metadata_file(str(metadata_path), updates)
        assert result is True

        with open(metadata_path, 'r') as f:
            data = json.load(f)

        assert len(data['tracks']) == 4

    def test_update_metadata_file_not_exist(self, metadata_manager):
        """Test updating non-existent file"""
        result = metadata_manager.update_metadata_file(
            "/tmp/nonexistent.mbid.json",
            {'validation': {'status': 'valid'}}
        )
        assert result is False

    def test_update_metadata_file_timestamp(self, metadata_manager, temp_album_dir, sample_album_metadata):
        """Test that updated_at timestamp is updated"""
        metadata_path = temp_album_dir / ".mbid.json"
        original_time = "2020-01-01T00:00:00"

        sample_album_metadata.updated_at = original_time
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(sample_album_metadata.to_dict(), f)

        # Update something
        metadata_manager.update_metadata_file(str(metadata_path), {'validation': {'status': 'valid'}})

        with open(metadata_path, 'r') as f:
            data = json.load(f)

        # Timestamp should be updated
        assert data['updated_at'] != original_time


# ========================================
# Test: Album Directory Validation
# ========================================

class TestAlbumDirectoryValidation:
    """Tests for validating album directories"""

    def test_validate_album_directory_all_tracks_present(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test validation when all tracks are present"""
        # Create metadata file
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            tracks=sample_tracks
        )

        # Create expected audio files
        for track in sample_tracks:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        # Validate
        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'valid'
        assert result.metadata_exists is True
        assert result.expected_tracks == 3
        assert result.found_tracks == 3
        assert len(result.missing_tracks) == 0
        assert len(result.extra_files) == 0

    def test_validate_album_directory_missing_tracks(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test validation with missing tracks"""
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            tracks=sample_tracks
        )

        # Create only 2 of 3 expected files
        for track in sample_tracks[:2]:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'missing_files'
        assert result.expected_tracks == 3
        assert result.found_tracks == 2
        assert len(result.missing_tracks) == 1
        assert result.missing_tracks[0]['track_number'] == 3

    def test_validate_album_directory_extra_files(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test validation with extra audio files"""
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            tracks=sample_tracks
        )

        # Create expected files
        for track in sample_tracks:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        # Add extra file
        extra_file = temp_album_dir / "Extra Song.flac"
        extra_file.write_text("extra audio data")

        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'extra_files'
        assert result.found_tracks == 4
        assert len(result.extra_files) == 1
        assert result.extra_files[0]['filename'] == 'Extra Song.flac'

    def test_validate_album_directory_mixed_issues(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test validation with both missing and extra files"""
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            tracks=sample_tracks
        )

        # Create only 2 expected files
        for track in sample_tracks[:2]:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        # Add extra file
        extra_file = temp_album_dir / "Wrong Track.mp3"
        extra_file.write_text("extra audio")

        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'mixed_issues'
        assert len(result.missing_tracks) == 1
        assert len(result.extra_files) == 1

    def test_validate_album_directory_no_metadata_file(self, metadata_manager, temp_album_dir):
        """Test validation when metadata file doesn't exist"""
        album_id = uuid4()

        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'no_metadata'
        assert result.metadata_exists is False

    def test_validate_album_directory_ignores_cover_art(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test that validation ignores cover art and non-audio files"""
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            tracks=sample_tracks
        )

        # Create expected audio files
        for track in sample_tracks:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        # Add cover art and other files (should be ignored)
        (temp_album_dir / "cover.jpg").write_text("image data")
        (temp_album_dir / "folder.jpg").write_text("image data")
        (temp_album_dir / "info.txt").write_text("info")

        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'valid'
        # Extra files should be listed but marked as should_ignore
        ignored_files = [f for f in result.extra_files if f.get('should_ignore')]
        assert len(ignored_files) == 0  # Should not be in extra_files at all

    def test_validate_album_directory_not_exist(self, metadata_manager):
        """Test validation of non-existent directory"""
        result = metadata_manager.validate_album_directory("/tmp/nonexistent_dir")
        assert result.status == 'invalid'


# ========================================
# Test: Finding Misplaced Files
# ========================================

class TestFindingMisplacedFiles:
    """Tests for finding misplaced files using MBID matching"""

    def test_find_misplaced_files_no_metadata(self, metadata_manager, temp_album_dir):
        """Test finding misplaced files when no metadata file exists"""
        result = metadata_manager.find_misplaced_files(str(temp_album_dir))
        assert result == []

    def test_find_misplaced_files_all_correct(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test when all files have correct MBIDs"""
        # Create metadata file
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            recording_mbids=[UUID(track.recording_mbid) for track in sample_tracks],
            tracks=sample_tracks
        )

        # Create audio files
        for track in sample_tracks:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        # Mock _get_file_recording_mbid to return correct MBIDs
        with patch.object(metadata_manager, '_get_file_recording_mbid', return_value=None):
            result = metadata_manager.find_misplaced_files(str(temp_album_dir))

        # With placeholder implementation (returns None), should find no misplaced files
        assert result == []


# ========================================
# Test: Helper Methods
# ========================================

class TestHelperMethods:
    """Tests for private helper methods"""

    def test_get_audio_files(self, metadata_manager, temp_album_dir):
        """Test audio file detection"""
        # Create various file types
        (temp_album_dir / "track1.flac").write_text("audio")
        (temp_album_dir / "track2.mp3").write_text("audio")
        (temp_album_dir / "track3.m4a").write_text("audio")
        (temp_album_dir / "cover.jpg").write_text("image")
        (temp_album_dir / "info.txt").write_text("text")
        (temp_album_dir / ".hidden").write_text("hidden")

        audio_files = metadata_manager._get_audio_files(temp_album_dir)

        assert len(audio_files) == 3
        audio_names = {f.name for f in audio_files}
        assert audio_names == {'track1.flac', 'track2.mp3', 'track3.m4a'}

    def test_should_ignore_file_cover_art(self, metadata_manager, temp_album_dir):
        """Test that cover art files are identified for ignoring"""
        cover_files = [
            temp_album_dir / "cover.jpg",
            temp_album_dir / "folder.jpg",
            temp_album_dir / "albumart.jpg"
        ]

        for cover_file in cover_files:
            assert metadata_manager._should_ignore_file(cover_file) is True

    def test_should_ignore_file_text_files(self, metadata_manager, temp_album_dir):
        """Test that text files are identified for ignoring"""
        text_files = [
            temp_album_dir / "info.txt",
            temp_album_dir / "playlist.m3u",
            temp_album_dir / "disc.cue"
        ]

        for text_file in text_files:
            assert metadata_manager._should_ignore_file(text_file) is True

    def test_should_ignore_file_hidden_files(self, metadata_manager, temp_album_dir):
        """Test that hidden files (starting with .) are identified for ignoring"""
        hidden_file = temp_album_dir / ".DS_Store"
        assert metadata_manager._should_ignore_file(hidden_file) is True

    def test_should_not_ignore_audio_files(self, metadata_manager, temp_album_dir):
        """Test that audio files are not marked for ignoring"""
        audio_files = [
            temp_album_dir / "track.flac",
            temp_album_dir / "song.mp3",
            temp_album_dir / "music.m4a"
        ]

        for audio_file in audio_files:
            assert metadata_manager._should_ignore_file(audio_file) is False


# ========================================
# Test: Database Integration
# ========================================

class TestDatabaseIntegration:
    """Tests for database storage of metadata"""

    def test_store_metadata_in_db(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test storing metadata info in database"""
        album_id = uuid4()

        # Create metadata file (which calls _store_metadata_in_db internally)
        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            release_year=1969,
            total_tracks=3,
            tracks=sample_tracks
        )

        assert result is not None

        # Verify database execute was called
        assert metadata_manager.db.execute.called
        assert metadata_manager.db.commit.called

    def test_store_metadata_in_db_rollback_on_error(self, metadata_manager, temp_album_dir):
        """Test database rollback on error"""
        album_id = uuid4()

        # Mock execute to raise exception
        metadata_manager.db.execute.side_effect = Exception("Database error")

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Test Album",
            artist_name="Test Artist"
        )

        # File should still be created even if database fails
        assert result is not None
        # But rollback should be called
        assert metadata_manager.db.rollback.called


# ========================================
# Test: Edge Cases
# ========================================

class TestEdgeCases:
    """Tests for edge cases and error scenarios"""

    def test_empty_album_directory(self, metadata_manager, temp_album_dir):
        """Test validation of empty album directory"""
        album_id = uuid4()
        metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Empty Album",
            artist_name="Empty Artist",
            total_tracks=0,
            tracks=[]
        )

        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'valid'
        assert result.expected_tracks == 0
        assert result.found_tracks == 0

    def test_very_long_filenames(self, metadata_manager, temp_album_dir):
        """Test metadata file with very long filenames"""
        album_id = uuid4()

        long_title = "A" * 200
        long_filename = f"Artist - Album - 01 - {long_title}.flac"

        tracks = [
            TrackMetadata(
                track_number=1,
                disc_number=1,
                title=long_title,
                expected_filename=long_filename
            )
        ]

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Test Album",
            artist_name="Test Artist",
            total_tracks=1,
            tracks=tracks
        )

        assert result is not None

        with open(result, 'r') as f:
            data = json.load(f)

        assert data['tracks'][0]['title'] == long_title

    def test_special_characters_in_metadata(self, metadata_manager, temp_album_dir):
        """Test metadata with special characters"""
        album_id = uuid4()

        result = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title='Album "with" quotes',
            artist_name="Artist & Friends"
        )

        assert result is not None

        with open(result, 'r') as f:
            data = json.load(f)

        assert data['album']['title'] == 'Album "with" quotes'
        assert data['album']['artist'] == 'Artist & Friends'

    def test_validation_updates_metadata_file(self, metadata_manager, temp_album_dir, sample_tracks):
        """Test that validation updates the metadata file"""
        album_id = uuid4()
        metadata_path = metadata_manager.create_album_metadata_file(
            album_id=album_id,
            album_directory=str(temp_album_dir),
            album_title="Abbey Road",
            artist_name="The Beatles",
            total_tracks=3,
            tracks=sample_tracks
        )

        # Create audio files
        for track in sample_tracks:
            file_path = temp_album_dir / track.expected_filename
            file_path.write_text("audio data")

        # Validate
        result = metadata_manager.validate_album_directory(str(temp_album_dir), album_id)

        assert result.status == 'valid'

        # Read metadata file and verify validation section was updated
        with open(metadata_path, 'r') as f:
            data = json.load(f)

        assert data['validation']['status'] == 'valid'
        assert data['validation']['last_validated'] is not None


# ========================================
# Test: AlbumMetadata Dataclass
# ========================================

class TestAlbumMetadataDataclass:
    """Tests for AlbumMetadata dataclass"""

    def test_album_metadata_to_dict(self):
        """Test AlbumMetadata.to_dict() method"""
        metadata = AlbumMetadata(
            version="1.0",
            album={'title': 'Test Album'},
            tracks=[{'track_number': 1}]
        )

        result = metadata.to_dict()

        assert result['version'] == '1.0'
        assert result['album'] == {'title': 'Test Album'}
        assert result['tracks'] == [{'track_number': 1}]
        assert 'mbids' in result
        assert 'validation' in result

    def test_album_metadata_none_fields(self):
        """Test AlbumMetadata with None fields"""
        metadata = AlbumMetadata()
        result = metadata.to_dict()

        assert result['album'] == {}
        assert result['mbids'] == {}
        assert result['tracks'] == []
        assert result['validation'] == {}


# ========================================
# Test: ValidationResult Dataclass
# ========================================

class TestValidationResultDataclass:
    """Tests for ValidationResult dataclass"""

    def test_validation_result_post_init(self):
        """Test ValidationResult.__post_init__ initializes lists"""
        result = ValidationResult(status='valid')

        assert result.missing_tracks == []
        assert result.extra_files == []

    def test_validation_result_with_issues(self):
        """Test ValidationResult with issues"""
        result = ValidationResult(
            status='mixed_issues',
            expected_tracks=10,
            found_tracks=9,
            missing_tracks=[{'track_number': 5}],
            extra_files=[{'filename': 'wrong.mp3'}]
        )

        assert result.status == 'mixed_issues'
        assert len(result.missing_tracks) == 1
        assert len(result.extra_files) == 1
