"""
Integration Tests for PathValidator Service

Tests path validation and structure analysis:
- Artist structure validation
- Library structure validation
- Misnamed file detection
- Misplaced file detection
- Incorrect directory detection
- Correction plan generation
"""

import pytest
import tempfile
from pathlib import Path
from uuid import uuid4, UUID
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy.orm import Session

from shared_services.path_validator import (
    PathValidator,
    ValidationResult,
    MisnamedFile,
    MisplacedFile,
    IncorrectDirectory
)
from shared_services.naming_engine import NamingEngine, TrackContext


# ========================================
# Fixtures
# ========================================

@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock(spec=Session)
    db.execute = Mock()
    return db


@pytest.fixture
def naming_engine():
    """Real NamingEngine instance for testing"""
    return NamingEngine()


@pytest.fixture
def path_validator(mock_db, naming_engine):
    """PathValidator instance with mock database"""
    return PathValidator(db=mock_db, naming_engine=naming_engine)


@pytest.fixture
def temp_library():
    """Temporary library structure for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        library_root = Path(tmpdir)

        # Create various artist directories
        artists = {
            'correct': library_root / "The Beatles",
            'incorrect': library_root / "Beatles, The",
            'multi_artist': library_root / "Pink Floyd"
        }

        for artist_dir in artists.values():
            artist_dir.mkdir(parents=True)

        yield {
            'root': str(library_root),
            'artists': artists
        }


@pytest.fixture
def sample_artist_data():
    """Sample artist data for mocking database queries"""
    artist_id = uuid4()
    return {
        'id': str(artist_id),
        'name': 'The Beatles',
        'musicbrainz_id': 'b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d'
    }


@pytest.fixture
def sample_tracks_data():
    """Sample track data for validation tests"""
    return [
        {
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': '/music/The Beatles/Abbey Road (1969)/The Beatles - Abbey Road - 01 - Come Together.flac'
        },
        {
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Something',
            'track_number': 2,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': '/music/The Beatles/Abbey Road (1969)/The Beatles - Abbey Road - 02 - Something.flac'
        }
    ]


# ========================================
# Test: Artist Structure Validation
# ========================================

class TestArtistStructureValidation:
    """Tests for validating artist directory structures"""

    def test_validate_artist_all_correct(self, path_validator, sample_artist_data, sample_tracks_data, temp_library):
        """Test validation when all files are correctly organized"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Create correct directory structure
        artist_dir = Path(library_root) / "The Beatles"
        album_dir = artist_dir / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)

        # Create correctly named files
        for track in sample_tracks_data:
            file_path = Path(track['file_path'])
            filename = file_path.name
            full_path = album_dir / filename
            full_path.write_text("audio data")

            # Update track data with actual paths
            track['file_path'] = str(full_path)

        # Mock database queries
        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=sample_tracks_data):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert result.is_valid is True
        assert result.total_files == 2
        assert result.valid_files == 2
        assert len(result.misnamed_files) == 0
        assert len(result.misplaced_files) == 0
        assert len(result.incorrect_directories) == 0

    def test_validate_artist_misnamed_files(self, path_validator, sample_artist_data, temp_library):
        """Test validation detects misnamed files"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Create directory structure
        artist_dir = Path(library_root) / "The Beatles"
        album_dir = artist_dir / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)

        # Create file with incorrect naming
        wrong_filename = album_dir / "01 - Come Together.flac"  # Missing artist and album in filename
        wrong_filename.write_text("audio data")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(wrong_filename)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert result.is_valid is False
        assert len(result.misnamed_files) == 1
        assert result.misnamed_files[0].current_filename == "01 - Come Together.flac"
        assert "The Beatles - Abbey Road - 01 - Come Together.flac" in result.misnamed_files[0].expected_filename

    def test_validate_artist_misplaced_files(self, path_validator, sample_artist_data, temp_library):
        """Test validation detects files in wrong directories"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Create directory structure
        artist_dir = Path(library_root) / "The Beatles"
        wrong_album_dir = artist_dir / "Let It Be (1970)"
        wrong_album_dir.mkdir(parents=True)

        # File is in wrong album directory
        wrong_location = wrong_album_dir / "The Beatles - Abbey Road - 01 - Come Together.flac"
        wrong_location.write_text("audio data")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',  # Should be in Abbey Road, not Let It Be
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(wrong_location)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert result.is_valid is False
        assert len(result.misplaced_files) == 1
        assert "Let It Be (1970)" in result.misplaced_files[0].current_directory
        assert "Abbey Road (1969)" in result.misplaced_files[0].expected_directory

    def test_validate_artist_incorrect_artist_directory(self, path_validator, sample_artist_data, temp_library):
        """Test validation detects incorrectly named artist directory"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Create directory with wrong artist name format
        wrong_artist_dir = Path(library_root) / "Beatles, The"  # Should be "The Beatles"
        album_dir = wrong_artist_dir / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)

        # Create correctly named file in wrong artist directory
        correct_filename = album_dir / "The Beatles - Abbey Road - 01 - Come Together.flac"
        correct_filename.write_text("audio data")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(correct_filename)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert result.is_valid is False
        assert len(result.incorrect_directories) == 1
        assert result.incorrect_directories[0].current_name == "Beatles, The"
        assert result.incorrect_directories[0].expected_name == "The Beatles"
        assert result.incorrect_directories[0].directory_type == 'artist'

    def test_validate_artist_no_tracks(self, path_validator, sample_artist_data, temp_library):
        """Test validation of artist with no tracks"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=[]):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert result.is_valid is True
        assert result.total_files == 0
        assert result.valid_files == 0

    def test_validate_artist_not_found(self, path_validator, temp_library):
        """Test validation when artist not found in database"""
        artist_id = uuid4()
        library_root = temp_library['root']

        with patch.object(path_validator, '_get_artist_info', return_value=None):
            result = path_validator.validate_artist_structure(
                artist_id=artist_id,
                library_root=library_root
            )

        assert result.is_valid is False


# ========================================
# Test: Library Structure Validation
# ========================================

class TestLibraryStructureValidation:
    """Tests for validating entire library structures"""

    def test_validate_library_multiple_artists(self, path_validator, temp_library):
        """Test validation of library with multiple artists"""
        library_path_id = uuid4()
        library_root = temp_library['root']

        # Mock multiple artists
        artists_data = [
            {'artist_id': str(uuid4()), 'name': 'The Beatles'},
            {'artist_id': str(uuid4()), 'name': 'Pink Floyd'}
        ]

        # Mock empty track lists for simplicity
        with patch.object(path_validator, '_get_library_artists', return_value=artists_data):
            with patch.object(path_validator, 'validate_artist_structure') as mock_validate:
                # Mock each artist validation to return valid results
                mock_validate.return_value = ValidationResult(
                    is_valid=True,
                    total_files=10,
                    valid_files=10,
                    issues_summary={'total_issues': 0}
                )

                result = path_validator.validate_library_structure(
                    library_path_id=library_path_id,
                    library_root=library_root
                )

        assert result.is_valid is True
        assert result.total_files == 20  # 10 per artist * 2 artists
        assert result.valid_files == 20
        assert mock_validate.call_count == 2

    def test_validate_library_with_issues(self, path_validator, temp_library):
        """Test library validation aggregates issues from multiple artists"""
        library_path_id = uuid4()
        library_root = temp_library['root']

        artists_data = [
            {'artist_id': str(uuid4()), 'name': 'Artist 1'},
            {'artist_id': str(uuid4()), 'name': 'Artist 2'}
        ]

        # Mock artist validations with different issues
        validation_results = [
            ValidationResult(
                is_valid=False,
                total_files=10,
                valid_files=8,
                misnamed_files=[MisnamedFile(
                    file_id=uuid4(),
                    current_path="/music/Artist 1/wrong.flac",
                    expected_path="/music/Artist 1/correct.flac",
                    current_filename="wrong.flac",
                    expected_filename="correct.flac",
                    issue_type="incorrect_format"
                )],
                misplaced_files=[],
                incorrect_directories=[],
                issues_summary={'total_issues': 2}
            ),
            ValidationResult(
                is_valid=False,
                total_files=15,
                valid_files=14,
                misnamed_files=[],
                misplaced_files=[MisplacedFile(
                    file_id=uuid4(),
                    current_path="/music/Artist 2/wrong_album/file.flac",
                    expected_path="/music/Artist 2/correct_album/file.flac",
                    current_directory="/music/Artist 2/wrong_album",
                    expected_directory="/music/Artist 2/correct_album",
                    reason="wrong_album"
                )],
                incorrect_directories=[],
                issues_summary={'total_issues': 1}
            )
        ]

        with patch.object(path_validator, '_get_library_artists', return_value=artists_data):
            with patch.object(path_validator, 'validate_artist_structure', side_effect=validation_results):
                result = path_validator.validate_library_structure(
                    library_path_id=library_path_id,
                    library_root=library_root
                )

        assert result.is_valid is False
        assert result.total_files == 25
        assert result.valid_files == 22
        assert len(result.misnamed_files) == 1
        assert len(result.misplaced_files) == 1
        assert result.issues_summary['total_issues'] == 2


# ========================================
# Test: Specific Issue Detection
# ========================================

class TestSpecificIssueDetection:
    """Tests for identifying specific types of issues"""

    def test_identify_misnamed_files(self, path_validator, sample_artist_data, temp_library):
        """Test identifying misnamed files"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Setup structure with misnamed files
        artist_dir = Path(library_root) / "The Beatles"
        album_dir = artist_dir / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)

        wrong_file = album_dir / "track_01.flac"
        wrong_file.write_text("audio")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(wrong_file)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.identify_misnamed_files(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert len(result) == 1
        assert result[0].current_filename == "track_01.flac"

    def test_identify_misplaced_files(self, path_validator, sample_artist_data, temp_library):
        """Test identifying files in wrong directories"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # File in wrong album directory
        artist_dir = Path(library_root) / "The Beatles"
        wrong_dir = artist_dir / "Wrong Album (2000)"
        wrong_dir.mkdir(parents=True)

        misplaced_file = wrong_dir / "The Beatles - Abbey Road - 01 - Come Together.flac"
        misplaced_file.write_text("audio")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(misplaced_file)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.identify_misplaced_files(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert len(result) == 1
        assert "Wrong Album (2000)" in result[0].current_directory

    def test_identify_incorrect_directories(self, path_validator, sample_artist_data, temp_library):
        """Test identifying incorrectly named directories"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Wrong artist directory name
        wrong_dir = Path(library_root) / "Beatles, The"
        album_dir = wrong_dir / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)

        file_path = album_dir / "The Beatles - Abbey Road - 01 - Come Together.flac"
        file_path.write_text("audio")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(file_path)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.identify_incorrect_directories(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert len(result) == 1
        assert result[0].current_name == "Beatles, The"
        assert result[0].expected_name == "The Beatles"


# ========================================
# Test: Correction Plan Generation
# ========================================

class TestCorrectionPlanGeneration:
    """Tests for generating correction plans"""

    def test_generate_correction_plan_directory_renames(self, path_validator):
        """Test correction plan prioritizes directory renames"""
        validation_result = ValidationResult(
            is_valid=False,
            total_files=10,
            valid_files=8,
            incorrect_directories=[
                IncorrectDirectory(
                    current_path="/music/Beatles, The",
                    expected_path="/music/The Beatles",
                    current_name="Beatles, The",
                    expected_name="The Beatles",
                    directory_type='artist',
                    affected_files=10
                )
            ]
        )

        plan = path_validator.generate_correction_plan(validation_result)

        assert len(plan) == 1
        assert plan[0]['operation'] == 'rename_directory'
        assert plan[0]['priority'] == 1
        assert plan[0]['affected_files'] == 10

    def test_generate_correction_plan_file_operations(self, path_validator):
        """Test correction plan includes file moves and renames"""
        file_id = uuid4()
        track_id = uuid4()

        validation_result = ValidationResult(
            is_valid=False,
            total_files=10,
            valid_files=8,
            misplaced_files=[
                MisplacedFile(
                    file_id=file_id,
                    current_path="/music/Artist/Wrong Album/file.flac",
                    expected_path="/music/Artist/Correct Album/file.flac",
                    current_directory="/music/Artist/Wrong Album",
                    expected_directory="/music/Artist/Correct Album",
                    reason="wrong_album",
                    track_id=track_id
                )
            ],
            misnamed_files=[
                MisnamedFile(
                    file_id=file_id,
                    current_path="/music/Artist/Album/wrong.flac",
                    expected_path="/music/Artist/Album/correct.flac",
                    current_filename="wrong.flac",
                    expected_filename="correct.flac",
                    issue_type="incorrect_format",
                    track_id=track_id
                )
            ]
        )

        plan = path_validator.generate_correction_plan(validation_result)

        assert len(plan) == 2

        # Check operations are ordered by priority
        operations = {op['operation']: op for op in plan}
        assert 'move_file' in operations
        assert 'rename_file' in operations

        # Move should have higher priority than rename
        move_op = next(op for op in plan if op['operation'] == 'move_file')
        rename_op = next(op for op in plan if op['operation'] == 'rename_file')
        assert move_op['priority'] < rename_op['priority']

    def test_generate_correction_plan_comprehensive(self, path_validator):
        """Test comprehensive correction plan with all issue types"""
        validation_result = ValidationResult(
            is_valid=False,
            total_files=20,
            valid_files=15,
            incorrect_directories=[
                IncorrectDirectory(
                    current_path="/music/Wrong Artist",
                    expected_path="/music/Correct Artist",
                    current_name="Wrong Artist",
                    expected_name="Correct Artist",
                    directory_type='artist',
                    affected_files=5
                )
            ],
            misplaced_files=[
                MisplacedFile(
                    file_id=uuid4(),
                    current_path="/music/Artist/Wrong/file1.flac",
                    expected_path="/music/Artist/Correct/file1.flac",
                    current_directory="/music/Artist/Wrong",
                    expected_directory="/music/Artist/Correct",
                    reason="wrong_album",
                    track_id=uuid4()
                )
            ],
            misnamed_files=[
                MisnamedFile(
                    file_id=uuid4(),
                    current_path="/music/Artist/Album/bad_name.flac",
                    expected_path="/music/Artist/Album/good_name.flac",
                    current_filename="bad_name.flac",
                    expected_filename="good_name.flac",
                    issue_type="incorrect_format",
                    track_id=uuid4()
                )
            ]
        )

        plan = path_validator.generate_correction_plan(validation_result)

        assert len(plan) == 3

        # Verify priority ordering: directory > move > rename
        assert plan[0]['operation'] == 'rename_directory'
        assert plan[0]['priority'] == 1
        assert plan[1]['operation'] == 'move_file'
        assert plan[1]['priority'] == 2
        assert plan[2]['operation'] == 'rename_file'
        assert plan[2]['priority'] == 3


# ========================================
# Test: Issue Type Determination
# ========================================

class TestIssueTypeDetermination:
    """Tests for determining specific issue types"""

    def test_determine_filename_issue_wrong_track_number(self, path_validator):
        """Test identifying wrong track number issues"""
        current = "The Beatles - Abbey Road - 02 - Come Together.flac"
        expected = "The Beatles - Abbey Road - 01 - Come Together.flac"

        issue_type = path_validator._determine_filename_issue(current, expected)

        assert issue_type == 'wrong_track_number'

    def test_determine_filename_issue_wrong_title(self, path_validator):
        """Test identifying wrong title issues"""
        current = "The Beatles - Abbey Road - 01 - Wrong Title.flac"
        expected = "The Beatles - Abbey Road - 01 - Come Together.flac"

        issue_type = path_validator._determine_filename_issue(current, expected)

        assert issue_type == 'wrong_title'

    def test_determine_filename_issue_incorrect_format(self, path_validator):
        """Test identifying format/template issues"""
        current = "01 Come Together.flac"
        expected = "The Beatles - Abbey Road - 01 - Come Together.flac"

        issue_type = path_validator._determine_filename_issue(current, expected)

        assert issue_type == 'incorrect_format'

    def test_determine_misplacement_reason_wrong_album(self, path_validator):
        """Test identifying wrong album placement"""
        current_dir = "/music/The Beatles/Let It Be (1970)"
        expected_dir = "/music/The Beatles/Abbey Road (1969)"

        reason = path_validator._determine_misplacement_reason(current_dir, expected_dir)

        assert reason == 'wrong_album'

    def test_determine_misplacement_reason_wrong_artist(self, path_validator):
        """Test identifying wrong artist placement"""
        current_dir = "/music/Pink Floyd/Album"
        expected_dir = "/music/The Beatles/Album"

        reason = path_validator._determine_misplacement_reason(current_dir, expected_dir)

        assert reason == 'wrong_artist'


# ========================================
# Test: Multi-Disc Album Validation
# ========================================

class TestMultiDiscValidation:
    """Tests for validating multi-disc album structures"""

    def test_validate_multi_disc_album_correct_structure(self, path_validator, sample_artist_data, temp_library):
        """Test validation of correctly organized multi-disc album"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Create multi-disc structure
        artist_dir = Path(library_root) / "Pink Floyd"
        album_dir = artist_dir / "The Wall (1979)"
        disc1_dir = album_dir / "CD 01"
        disc2_dir = album_dir / "CD 02"
        disc1_dir.mkdir(parents=True)
        disc2_dir.mkdir(parents=True)

        # Create correctly named files
        disc1_file = disc1_dir / "Pink Floyd - The Wall - 01 - In the Flesh.flac"
        disc2_file = disc2_dir / "Pink Floyd - The Wall - 01 - Hey You.flac"
        disc1_file.write_text("audio")
        disc2_file.write_text("audio")

        tracks_data = [
            {
                'track_id': str(uuid4()),
                'file_id': str(uuid4()),
                'album_id': str(uuid4()),
                'artist_name': 'Pink Floyd',
                'album_title': 'The Wall',
                'track_title': 'In the Flesh?',
                'track_number': 1,
                'release_year': 1979,
                'disc_number': 1,
                'total_discs': 2,
                'medium_format': 'CD',
                'album_type': 'Album',
                'file_extension': 'flac',
                'is_compilation': False,
                'file_path': str(disc1_file)
            },
            {
                'track_id': str(uuid4()),
                'file_id': str(uuid4()),
                'album_id': str(uuid4()),
                'artist_name': 'Pink Floyd',
                'album_title': 'The Wall',
                'track_title': 'Hey You',
                'track_number': 1,
                'release_year': 1979,
                'disc_number': 2,
                'total_discs': 2,
                'medium_format': 'CD',
                'album_type': 'Album',
                'file_extension': 'flac',
                'is_compilation': False,
                'file_path': str(disc2_file)
            }
        ]

        artist_data = {
            'id': str(artist_id),
            'name': 'Pink Floyd',
            'musicbrainz_id': str(uuid4())
        }

        with patch.object(path_validator, '_get_artist_info', return_value=artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert result.is_valid is True
        assert result.total_files == 2
        assert result.valid_files == 2


# ========================================
# Test: Edge Cases
# ========================================

class TestEdgeCases:
    """Tests for edge cases and error scenarios"""

    def test_validate_empty_library(self, path_validator, temp_library):
        """Test validation of empty library"""
        library_path_id = uuid4()

        with patch.object(path_validator, '_get_library_artists', return_value=[]):
            result = path_validator.validate_library_structure(
                library_path_id=library_path_id,
                library_root=temp_library['root']
            )

        assert result.is_valid is True
        assert result.total_files == 0

    def test_validation_result_summary(self, path_validator, sample_artist_data, temp_library):
        """Test that validation result includes proper summary"""
        artist_id = UUID(sample_artist_data['id'])
        library_root = temp_library['root']

        # Create mixed issues
        artist_dir = Path(library_root) / "Beatles, The"  # Wrong name
        album_dir = artist_dir / "Abbey Road (1969)"
        album_dir.mkdir(parents=True)

        wrong_file = album_dir / "wrong_name.flac"  # Wrong filename
        wrong_file.write_text("audio")

        tracks_data = [{
            'track_id': str(uuid4()),
            'file_id': str(uuid4()),
            'album_id': str(uuid4()),
            'artist_name': 'The Beatles',
            'album_title': 'Abbey Road',
            'track_title': 'Come Together',
            'track_number': 1,
            'release_year': 1969,
            'disc_number': 1,
            'total_discs': 1,
            'medium_format': 'CD',
            'album_type': 'Album',
            'file_extension': 'flac',
            'is_compilation': False,
            'file_path': str(wrong_file)
        }]

        with patch.object(path_validator, '_get_artist_info', return_value=sample_artist_data):
            with patch.object(path_validator, '_get_artist_tracks', return_value=tracks_data):
                result = path_validator.validate_artist_structure(
                    artist_id=artist_id,
                    library_root=library_root
                )

        assert 'misnamed_files' in result.issues_summary
        assert 'incorrect_directories' in result.issues_summary
        assert 'total_issues' in result.issues_summary
        assert result.issues_summary['total_issues'] > 0

    def test_correction_plan_empty_validation(self, path_validator):
        """Test correction plan with no issues"""
        validation_result = ValidationResult(
            is_valid=True,
            total_files=10,
            valid_files=10
        )

        plan = path_validator.generate_correction_plan(validation_result)

        assert len(plan) == 0
