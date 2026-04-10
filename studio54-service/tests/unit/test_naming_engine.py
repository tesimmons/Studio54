"""
Tests for app.services.naming_template_engine — track filename generation,
multi-disc, special characters, case transformation, sanitization.

Engine behavior notes:
- Regex matches single words ({track}) or word-separator-word ({Artist-Name})
- Separators [-._] cause spaces in values to be replaced with that separator
- {Artist_Name} → "Pink_Floyd", {Artist-Name} → "Pink-Floyd"
- Space-separated tokens like {Artist Name} do NOT match the regex (literal passthrough)
- Token aliases: {track} → track_number, {year} → release_year, etc.
"""
import pytest
from app.services.naming_template_engine import NamingTemplateEngine, DEFAULT_TEMPLATES


@pytest.fixture
def engine():
    return NamingTemplateEngine()


@pytest.fixture
def sample_metadata():
    return {
        "artist_name": "Pink Floyd",
        "album_title": "Dark Side of the Moon",
        "release_year": 1973,
        "track_number": 1,
        "track_title": "Speak to Me",
        "disc_number": 1,
        "quality_title": "FLAC",
        "album_type": "Album",
        "mediainfo_audiocodec": "FLAC",
        "mediainfo_audiobitrate": "1411 kbps",
    }


class TestBuildPath:
    """Tests for NamingTemplateEngine.build_path()"""

    def test_underscore_separator(self, engine, sample_metadata):
        """Underscore tokens replace spaces with underscores in values"""
        template = "{Artist_Name}/{Album_Title} ({Release_Year})"
        result = engine.build_path(template, sample_metadata, is_folder=True)
        assert result == "Pink_Floyd/Dark_Side_of_the_Moon (1973)"

    def test_hyphen_separator(self, engine, sample_metadata):
        """Hyphen tokens replace spaces with hyphens in values"""
        template = "{Artist-Name}/{Album-Title}"
        result = engine.build_path(template, sample_metadata)
        assert result == "Pink-Floyd/Dark-Side-of-the-Moon"

    def test_multi_disc_format(self, engine, sample_metadata):
        sample_metadata["disc_number"] = 2
        sample_metadata["track_number"] = 5
        template = "{disc:0}-{track:00} - {Track_Title}"
        result = engine.build_path(template, sample_metadata)
        assert result == "2-05 - Speak_to_Me"

    def test_zero_padding(self, engine, sample_metadata):
        sample_metadata["track_number"] = 3
        template = "{track:000}"
        result = engine.build_path(template, sample_metadata)
        assert result == "003"

    def test_single_digit_padding(self, engine, sample_metadata):
        template = "{track:00}"
        result = engine.build_path(template, sample_metadata)
        assert result == "01"

    def test_missing_token_becomes_empty(self, engine):
        template = "{Artist_Name} - {nonexistent_token}"
        result = engine.build_path(template, {"artist_name": "Test"})
        assert "Test" in result

    def test_token_alias_track(self, engine, sample_metadata):
        """'track' is alias for 'track_number'"""
        template = "{track:00}"
        result = engine.build_path(template, sample_metadata)
        assert result == "01"

    def test_token_alias_year(self, engine, sample_metadata):
        """'year' is alias for 'release_year'"""
        template = "({year})"
        result = engine.build_path(template, sample_metadata)
        assert result == "(1973)"

    def test_token_alias_disc(self, engine, sample_metadata):
        """'disc' and 'medium' are aliases for 'disc_number'"""
        template = "{disc:0}"
        result = engine.build_path(template, sample_metadata)
        assert result == "1"

    def test_case_lower(self, engine, sample_metadata):
        """All-lowercase token → lowercase output"""
        template = "{artist_name}"
        result = engine.build_path(template, sample_metadata)
        assert result == "pink_floyd"

    def test_case_upper(self, engine, sample_metadata):
        """All-uppercase token → uppercase output"""
        template = "{ARTIST_NAME}"
        result = engine.build_path(template, sample_metadata)
        assert result == "PINK_FLOYD"

    def test_mixed_case_preserves(self, engine, sample_metadata):
        """Mixed case → preserves original value casing"""
        template = "{Artist_Name}"
        result = engine.build_path(template, sample_metadata)
        assert result == "Pink_Floyd"

    def test_escaped_braces(self, engine, sample_metadata):
        template = "{{literal}} {Artist-Name}"
        result = engine.build_path(template, sample_metadata)
        assert "Pink-Floyd" in result

    def test_none_value_produces_empty(self, engine):
        template = "{Artist_Name} - {Album_Title}"
        result = engine.build_path(template, {"artist_name": "Test"})
        assert "Test" in result

    def test_full_track_path(self, engine, sample_metadata):
        """Full track path with multiple components"""
        template = "{Artist-Name}/{Album-Title} ({year})/{track:00} - {Track-Title}"
        result = engine.build_path(template, sample_metadata)
        assert result == "Pink-Floyd/Dark-Side-of-the-Moon (1973)/01 - Speak-to-Me"


class TestSanitization:
    """Tests for path sanitization in NamingTemplateEngine"""

    def test_colon_smart_strategy(self, engine):
        result = engine._sanitize_component("Title: Subtitle")
        assert ":" not in result
        assert "Title - Subtitle" == result

    def test_colon_dash_strategy(self):
        engine = NamingTemplateEngine(colon_strategy="dash")
        result = engine._sanitize_component("Title:Subtitle")
        assert result == "Title-Subtitle"

    def test_colon_delete_strategy(self):
        engine = NamingTemplateEngine(colon_strategy="delete")
        result = engine._sanitize_component("Title:Subtitle")
        assert result == "TitleSubtitle"

    def test_redundant_separators_collapsed(self, engine):
        result = engine._sanitize_component("foo...bar--baz")
        assert ".." not in result
        assert "--" not in result

    def test_reserved_names_handled(self, engine):
        result = engine._sanitize_component("CON.txt")
        assert "." not in result or "_" in result

    def test_strip_leading_trailing(self, engine):
        result = engine._sanitize_component("  .hello. ")
        assert not result.startswith(".")
        assert not result.endswith(".")
        assert "hello" in result

    def test_illegal_chars_replaced(self, engine):
        result = engine._sanitize_component('file<>name')
        assert "<" not in result
        assert ">" not in result

    def test_backslash_replaced(self, engine):
        result = engine._sanitize_component('back\\slash')
        assert "\\" not in result

    def test_pipe_replaced(self, engine):
        result = engine._sanitize_component("file|name")
        assert "|" not in result

    def test_sanitize_path_splits_on_slash(self, engine):
        result = engine._sanitize_path("Artist/Album/track.mp3")
        parts = result.split("/")
        assert len(parts) == 3


class TestGetCleanName:
    """Tests for get_clean_name()"""

    def test_removes_the(self, engine):
        assert engine.get_clean_name("The Beatles") == "beatles"

    def test_no_the(self, engine):
        assert engine.get_clean_name("Pink Floyd") == "pink floyd"

    def test_removes_special_chars(self, engine):
        assert engine.get_clean_name("AC/DC") == "acdc"

    def test_lowercase(self, engine):
        assert engine.get_clean_name("METALLICA") == "metallica"


class TestGetNameThe:
    """Tests for get_name_the()"""

    def test_moves_the_to_end(self, engine):
        assert engine.get_name_the("The Beatles") == "Beatles, The"

    def test_no_the_unchanged(self, engine):
        assert engine.get_name_the("Pink Floyd") == "Pink Floyd"

    def test_case_insensitive(self, engine):
        assert engine.get_name_the("the Rolling Stones") == "Rolling Stones, the"


class TestValidateTemplate:
    """Tests for validate_template()"""

    def test_valid_underscore_template(self, engine):
        valid, error = engine.validate_template("{Artist_Name}/{Album_Title}")
        assert valid is True
        assert error is None

    def test_unmatched_braces(self, engine):
        valid, error = engine.validate_template("{Artist_Name/{Album_Title}")
        assert valid is False
        assert "brace" in error.lower()

    def test_single_word_token(self, engine):
        valid, error = engine.validate_template("{track:00}")
        assert valid is True

    def test_valid_with_format_spec(self, engine):
        valid, error = engine.validate_template("{disc:0}-{track:00}")
        assert valid is True


class TestDefaultTemplates:
    """Verify default template structure"""

    def test_all_defaults_have_required_keys(self):
        required_keys = {"name", "artist_folder", "album_folder", "track_file", "description"}
        for key, tmpl in DEFAULT_TEMPLATES.items():
            assert required_keys.issubset(tmpl.keys()), f"Template '{key}' missing keys"

    def test_standard_template_uses_artist(self):
        tmpl = DEFAULT_TEMPLATES["standard"]
        assert "Artist" in tmpl["artist_folder"]

    def test_quality_template_has_quality_token(self):
        tmpl = DEFAULT_TEMPLATES["quality"]
        assert "Quality" in tmpl["album_folder"]

    def test_get_example_output_with_hyphen(self, engine):
        """get_example_output uses sample metadata - hyphens work"""
        result = engine.get_example_output("{Artist-Name}")
        assert "Pink-Floyd" in result
