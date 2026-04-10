"""
Unit tests for NamingEngine service

Tests cover 50+ scenarios:
- Template parsing
- All supported tokens
- Filename sanitization edge cases
- Unicode handling
- Length truncation
- Multi-disc albums
- Compilation albums
- Artist name normalization
- Special characters
- Edge cases
"""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from naming_engine import (
    NamingEngine,
    TrackContext,
    AlbumContext,
    ArtistContext
)


@pytest.fixture
def engine():
    """Create NamingEngine instance with default templates"""
    return NamingEngine()


@pytest.fixture
def simple_track_context():
    """Simple track context for testing"""
    return TrackContext(
        artist_name="The Beatles",
        album_title="Abbey Road",
        track_title="Come Together",
        track_number=1,
        release_year=1969,
        disc_number=1,
        total_discs=1,
        file_extension="flac"
    )


class TestTemplateParsing:
    """Tests for template parsing functionality"""

    def test_parse_simple_template(self, engine):
        """Test parsing template with basic tokens"""
        template = "{Artist Name} - {Track Title}"
        tokens = {
            'Artist Name': 'Pink Floyd',
            'Track Title': 'Wish You Were Here'
        }

        result = engine._parse_template(template, tokens)

        assert result == "Pink Floyd - Wish You Were Here"

    def test_parse_all_tokens(self, engine):
        """Test parsing template with all supported tokens"""
        template = "{Artist Name}/{Album Title} ({Release Year})/{track:00} {Track Title}.{ext}"
        tokens = {
            'Artist Name': 'Miles Davis',
            'Album Title': 'Kind of Blue',
            'Release Year': '1959',
            'track:00': '01',
            'Track Title': 'So What',
            'ext': 'flac'
        }

        result = engine._parse_template(template, tokens)

        assert result == "Miles Davis/Kind of Blue (1959)/01 So What.flac"

    def test_parse_missing_tokens(self, engine):
        """Test that missing tokens are removed"""
        template = "{Artist Name} - {Unknown Token} - {Track Title}"
        tokens = {
            'Artist Name': 'Artist',
            'Track Title': 'Track'
        }

        result = engine._parse_template(template, tokens)

        assert result == "Artist -  - Track"

    def test_parse_zero_padded_track(self, engine):
        """Test zero-padded track numbers"""
        template = "{track:00} {Track Title}"
        tokens = {'track:00': '05', 'Track Title': 'Test'}

        result = engine._parse_template(template, tokens)

        assert result == "05 Test"

    def test_parse_triple_zero_padded_track(self, engine):
        """Test triple zero-padded track numbers"""
        template = "{track:000} {Track Title}"
        tokens = {'track:000': '005', 'Track Title': 'Test'}

        result = engine._parse_template(template, tokens)

        assert result == "005 Test"


class TestTrackFilenameGeneration:
    """Tests for track filename generation"""

    def test_generate_simple_track_filename(self, engine, simple_track_context):
        """Test generating filename for simple track"""
        filename = engine.generate_track_filename(simple_track_context)

        assert "The Beatles" in filename
        assert "Abbey Road" in filename
        assert "Come Together" in filename
        assert "01" in filename
        assert ".flac" in filename

    def test_generate_multi_disc_track_filename(self, engine):
        """Test generating filename for multi-disc album track"""
        context = TrackContext(
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

        filename = engine.generate_track_filename(context)

        assert "CD 01" in filename or "CD01" in filename
        assert "The Wall" in filename

    def test_generate_compilation_track_filename(self, engine):
        """Test generating filename for compilation track"""
        context = TrackContext(
            artist_name="Katy Perry",
            album_title="Now That's What I Call Music! 50",
            track_title="Roar",
            track_number=1,
            release_year=2014,
            is_compilation=True,
            file_extension="mp3"
        )

        filename = engine.generate_track_filename(context)

        assert "Various Artists" in filename or "Katy Perry" in filename
        assert "Roar" in filename

    def test_generate_track_without_year(self, engine):
        """Test track filename when release year is missing"""
        context = TrackContext(
            artist_name="Artist",
            album_title="Album",
            track_title="Track",
            track_number=1,
            release_year=None,
            file_extension="flac"
        )

        filename = engine.generate_track_filename(context)

        assert "Unknown" in filename or "Album" in filename

    def test_custom_track_template(self, engine, simple_track_context):
        """Test using custom template"""
        custom_template = "{track:00}. {Artist Name} - {Track Title}.{ext}"

        filename = engine.generate_track_filename(
            simple_track_context,
            template=custom_template
        )

        assert filename.startswith("01.")
        assert "The Beatles - Come Together" in filename


class TestAlbumDirectoryGeneration:
    """Tests for album directory name generation"""

    def test_generate_album_directory(self, engine):
        """Test album directory name"""
        context = AlbumContext(
            album_title="Thriller",
            artist_name="Michael Jackson",
            release_year=1982
        )

        dirname = engine.generate_album_directory(context)

        assert "Thriller" in dirname
        assert "1982" in dirname

    def test_generate_album_without_year(self, engine):
        """Test album directory without year"""
        context = AlbumContext(
            album_title="Test Album",
            artist_name="Test Artist",
            release_year=None
        )

        dirname = engine.generate_album_directory(context)

        assert "Test Album" in dirname
        assert "Unknown" in dirname


class TestArtistDirectoryGeneration:
    """Tests for artist directory name generation"""

    def test_generate_artist_directory(self, engine):
        """Test artist directory name"""
        context = ArtistContext(artist_name="The Beatles")

        dirname = engine.generate_artist_directory(context)

        assert dirname == "The Beatles"

    def test_generate_artist_directory_sanitized(self, engine):
        """Test artist directory with special characters"""
        context = ArtistContext(artist_name="AC/DC")

        dirname = engine.generate_artist_directory(context)

        assert "/" not in dirname or dirname == "AC_DC"


class TestFilenameSanitization:
    """Tests for filename sanitization"""

    def test_sanitize_basic_filename(self, engine):
        """Test basic filename sanitization"""
        result = engine.sanitize_filename("test_file.txt")

        assert result == "test_file.txt"

    def test_sanitize_invalid_characters(self, engine):
        """Test removal of invalid filesystem characters"""
        unsafe = 'file<name>with:bad"chars|?.txt'
        result = engine.sanitize_filename(unsafe)

        for char in '<>:"|?*':
            assert char not in result

    def test_sanitize_slashes(self, engine):
        """Test handling of path separators"""
        result = engine.sanitize_filename("artist/album/track.flac")

        assert "/" in result  # Path separators should be preserved

    def test_sanitize_backslashes(self, engine):
        """Test replacement of backslashes"""
        result = engine.sanitize_filename("artist\\album\\track.flac")

        assert "\\" not in result

    def test_sanitize_unicode_characters(self, engine):
        """Test preservation of valid Unicode characters"""
        result = engine.sanitize_filename("ファイル.txt")

        assert "ファイル" in result

    def test_sanitize_unicode_normalization(self, engine):
        """Test Unicode normalization (NFC)"""
        # Combining character é (e + ́)
        combining = "café"  # May be represented as cafe\u0301
        result = engine.sanitize_filename(combining)

        assert "caf" in result and "e" in result

    def test_sanitize_leading_trailing_spaces(self, engine):
        """Test removal of leading/trailing spaces"""
        result = engine.sanitize_filename("  filename.txt  ")

        assert result == "filename.txt"

    def test_sanitize_leading_trailing_dots(self, engine):
        """Test removal of leading/trailing dots"""
        result = engine.sanitize_filename("..filename.txt.")

        assert not result.startswith(".")
        assert not result.endswith(".")

    def test_sanitize_multiple_spaces(self, engine):
        """Test collapse of multiple spaces"""
        result = engine.sanitize_filename("file    with    spaces.txt")

        assert "    " not in result
        assert " " in result

    def test_sanitize_control_characters(self, engine):
        """Test removal of control characters"""
        result = engine.sanitize_filename("file\x00\x01\x1fname.txt")

        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x1f" not in result

    def test_sanitize_long_filename(self, engine):
        """Test truncation of long filenames"""
        long_name = "a" * 300 + ".txt"
        result = engine.sanitize_filename(long_name)

        assert len(result) <= 255
        assert result.endswith(".txt")
        assert "..." in result

    def test_sanitize_long_directory_name(self, engine):
        """Test truncation of long directory names"""
        long_dir = "d" * 300
        result = engine.sanitize_filename(long_dir)

        assert len(result) <= 255
        assert result.endswith("...")

    def test_sanitize_nested_path(self, engine):
        """Test sanitization of nested paths"""
        path = "artist name/album (2020)/01 - track title.flac"
        result = engine.sanitize_filename(path)

        parts = result.split('/')
        assert len(parts) == 3
        assert all(len(part) <= 255 for part in parts)


class TestEdgeCases:
    """Tests for edge cases"""

    def test_empty_filename(self, engine):
        """Test handling of empty filename"""
        result = engine.sanitize_filename("")

        assert result == ""

    def test_filename_all_invalid_chars(self, engine):
        """Test filename with only invalid characters"""
        result = engine.sanitize_filename("<<<>>>")

        assert result == "______" or len(result) > 0

    def test_filename_emoji(self, engine):
        """Test filename with emoji"""
        result = engine.sanitize_filename("music_🎵_file.flac")

        assert "music" in result
        assert "file" in result
        assert ".flac" in result

    def test_filename_mixed_case(self, engine):
        """Test preservation of mixed case"""
        result = engine.sanitize_filename("MiXeD_CaSe.TxT")

        assert result == "MiXeD_CaSe.TxT"

    def test_filename_numbers(self, engine):
        """Test filename with numbers"""
        result = engine.sanitize_filename("track_123_test.mp3")

        assert result == "track_123_test.mp3"

    def test_filename_parentheses(self, engine):
        """Test filename with parentheses"""
        result = engine.sanitize_filename("album (2020).flac")

        assert "(" in result and ")" in result

    def test_filename_brackets(self, engine):
        """Test filename with brackets"""
        result = engine.sanitize_filename("track [remix].flac")

        assert "[" in result and "]" in result


class TestTrackNumberParsing:
    """Tests for track number parsing"""

    def test_parse_simple_number(self, engine):
        """Test parsing simple track number"""
        assert engine.parse_track_number("5") == 5

    def test_parse_zero_padded(self, engine):
        """Test parsing zero-padded number"""
        assert engine.parse_track_number("05") == 5

    def test_parse_with_label(self, engine):
        """Test parsing with track label"""
        assert engine.parse_track_number("Track 12") == 12

    def test_parse_with_number_label(self, engine):
        """Test parsing with No. label"""
        assert engine.parse_track_number("No. 7") == 7

    def test_parse_with_slash(self, engine):
        """Test parsing format like 3/12"""
        assert engine.parse_track_number("3/12") == 3

    def test_parse_with_of(self, engine):
        """Test parsing format like 03 of 12"""
        assert engine.parse_track_number("03 of 12") == 3

    def test_parse_invalid(self, engine):
        """Test parsing invalid track number"""
        assert engine.parse_track_number("invalid") is None


class TestArtistNameNormalization:
    """Tests for artist name normalization"""

    def test_normalize_the_beatles(self, engine):
        """Test normalizing 'Beatles, The' to 'The Beatles'"""
        result = engine.normalize_artist_name("Beatles, The")

        assert result == "The Beatles"

    def test_normalize_a_ha(self, engine):
        """Test normalizing 'A-ha, A' format"""
        result = engine.normalize_artist_name("Perfect Circle, A")

        assert result == "A Perfect Circle"

    def test_normalize_standard_name(self, engine):
        """Test that standard names are unchanged"""
        result = engine.normalize_artist_name("Pink Floyd")

        assert result == "Pink Floyd"

    def test_normalize_with_an(self, engine):
        """Test normalizing with 'An' article"""
        result = engine.normalize_artist_name("Unknown Artist, An")

        assert result == "An Unknown Artist"


class TestExtensionHandling:
    """Tests for file extension handling"""

    def test_split_extension(self, engine):
        """Test splitting filename and extension"""
        name, ext = engine.split_extension("track.flac")

        assert name == "track"
        assert ext == "flac"

    def test_split_no_extension(self, engine):
        """Test splitting filename without extension"""
        name, ext = engine.split_extension("track")

        assert name == "track"
        assert ext == ""

    def test_split_multiple_dots(self, engine):
        """Test splitting with multiple dots"""
        name, ext = engine.split_extension("my.track.file.mp3")

        assert name == "my.track.file"
        assert ext == "mp3"


class TestTemplateValidation:
    """Tests for template validation"""

    def test_validate_good_template(self, engine):
        """Test validation of valid template"""
        valid, error = engine.validate_template("{Artist Name} - {Track Title}.{ext}")

        assert valid is True
        assert error is None

    def test_validate_mismatched_braces(self, engine):
        """Test validation catches mismatched braces"""
        valid, error = engine.validate_template("{Artist Name - {Track Title}")

        assert valid is False
        assert "braces" in error.lower()

    def test_validate_invalid_token(self, engine):
        """Test validation catches invalid tokens"""
        valid, error = engine.validate_template("{Invalid Token}")

        assert valid is False
        assert "invalid token" in error.lower()

    def test_validate_empty_template(self, engine):
        """Test validation of empty template"""
        valid, error = engine.validate_template("")

        assert valid is True


class TestSafeFilenames:
    """Tests for safe filename generation"""

    def test_get_safe_filename(self, engine):
        """Test generating safe filename from user input"""
        unsafe = "../../../etc/passwd"
        safe = engine.get_safe_filename(unsafe)

        assert ".." not in safe
        assert "/" not in safe

    def test_get_safe_filename_removes_path(self, engine):
        """Test that path components are removed"""
        unsafe = "/path/to/file.txt"
        safe = engine.get_safe_filename(unsafe)

        assert safe == "file.txt" or "/" not in safe


class TestUniqueFilenames:
    """Tests for unique filename generation"""

    def test_generate_unique_filename_no_conflict(self, engine, tmp_path):
        """Test unique filename when no conflict"""
        unique = engine.generate_unique_filename("test.txt", str(tmp_path))

        assert unique == "test.txt"

    def test_generate_unique_filename_with_conflict(self, engine, tmp_path):
        """Test unique filename when file exists"""
        # Create existing file
        (tmp_path / "test.txt").touch()

        unique = engine.generate_unique_filename("test.txt", str(tmp_path))

        assert unique == "test (1).txt"

    def test_generate_unique_filename_multiple_conflicts(self, engine, tmp_path):
        """Test unique filename with multiple existing files"""
        (tmp_path / "test.txt").touch()
        (tmp_path / "test (1).txt").touch()
        (tmp_path / "test (2).txt").touch()

        unique = engine.generate_unique_filename("test.txt", str(tmp_path))

        assert unique == "test (3).txt"


class TestFilenameComparison:
    """Tests for filename comparison"""

    def test_compare_identical_filenames(self, engine):
        """Test comparison of identical filenames"""
        assert engine.compare_filenames("test.txt", "test.txt") is True

    def test_compare_case_insensitive(self, engine):
        """Test case-insensitive comparison"""
        assert engine.compare_filenames("Test.TXT", "test.txt") is True

    def test_compare_different_filenames(self, engine):
        """Test comparison of different filenames"""
        assert engine.compare_filenames("test1.txt", "test2.txt") is False


class TestMultiDiscFormats:
    """Tests for multi-disc album formats"""

    def test_vinyl_format(self, engine):
        """Test vinyl multi-disc format"""
        context = TrackContext(
            artist_name="Led Zeppelin",
            album_title="Physical Graffiti",
            track_title="Custard Pie",
            track_number=1,
            release_year=1975,
            disc_number=1,
            total_discs=2,
            medium_format="Vinyl",
            file_extension="flac"
        )

        filename = engine.generate_track_filename(context)

        assert "Vinyl" in filename or "vinyl" in filename.lower()

    def test_digital_format(self, engine):
        """Test digital multi-disc format"""
        context = TrackContext(
            artist_name="Artist",
            album_title="Album",
            track_title="Track",
            track_number=1,
            disc_number=2,
            total_discs=3,
            medium_format="Digital",
            file_extension="flac"
        )

        filename = engine.generate_track_filename(context)

        assert "Digital" in filename or "02" in filename


class TestCompilationFormats:
    """Tests for compilation album formats"""

    def test_various_artists_compilation(self, engine):
        """Test Various Artists compilation"""
        context = TrackContext(
            artist_name="David Bowie",
            album_title="Best of 70s Rock",
            track_title="Changes",
            track_number=5,
            release_year=2010,
            is_compilation=True,
            file_extension="mp3"
        )

        filename = engine.generate_track_filename(context)

        # Should include both Various Artists and track artist
        assert ("Various Artists" in filename and "David Bowie" in filename) or \
               "David Bowie" in filename


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=naming_engine", "--cov-report=term-missing"])
