"""
Tests for app.security module — pure functions, no DB needed.
"""
import pytest
from fastapi import HTTPException


class TestValidateUuid:
    """Tests for validate_uuid()"""

    def test_valid_uuid_v4(self):
        from app.security import validate_uuid
        assert validate_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uuid_no_hyphens(self):
        from app.security import validate_uuid
        assert validate_uuid("550e8400e29b41d4a716446655440000") is True

    def test_invalid_uuid_raises(self):
        from app.security import validate_uuid
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("not-a-uuid")
        assert exc_info.value.status_code == 400

    def test_empty_string_raises(self):
        from app.security import validate_uuid
        with pytest.raises(HTTPException):
            validate_uuid("")

    def test_none_raises(self):
        from app.security import validate_uuid
        with pytest.raises(HTTPException):
            validate_uuid(None)

    def test_custom_field_name_in_error(self):
        from app.security import validate_uuid
        with pytest.raises(HTTPException) as exc_info:
            validate_uuid("bad", field_name="Artist ID")
        assert "Artist ID" in exc_info.value.detail


class TestValidateMbid:
    """Tests for validate_mbid()"""

    def test_valid_mbid(self):
        from app.security import validate_mbid
        assert validate_mbid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_short_mbid_raises(self):
        from app.security import validate_mbid
        with pytest.raises(HTTPException):
            validate_mbid("short")

    def test_empty_mbid_raises(self):
        from app.security import validate_mbid
        with pytest.raises(HTTPException):
            validate_mbid("")


class TestSanitizeFilename:
    """Tests for sanitize_filename()"""

    def test_basic_passthrough(self):
        from app.security import sanitize_filename
        assert sanitize_filename("hello.mp3") == "hello.mp3"

    def test_removes_path_separators(self):
        from app.security import sanitize_filename
        result = sanitize_filename("path/to\\file.mp3")
        assert "/" not in result
        assert "\\" not in result

    def test_removes_null_bytes(self):
        from app.security import sanitize_filename
        result = sanitize_filename("hello\x00world.mp3")
        assert "\x00" not in result

    def test_replaces_dangerous_chars(self):
        from app.security import sanitize_filename
        result = sanitize_filename('file<>:"|?*.mp3')
        assert all(c not in result for c in '<>:"|?*')

    def test_strips_leading_trailing_dots_spaces(self):
        from app.security import sanitize_filename
        assert sanitize_filename("  .file.mp3. ") == "file.mp3"

    def test_empty_becomes_unnamed(self):
        from app.security import sanitize_filename
        assert sanitize_filename("...") == "unnamed"
        assert sanitize_filename("") == "unnamed"

    def test_truncation_preserves_extension(self):
        from app.security import sanitize_filename
        long_name = "a" * 300 + ".mp3"
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) <= 255
        assert result.endswith(".mp3")

    def test_truncation_without_extension(self):
        from app.security import sanitize_filename
        long_name = "a" * 300
        result = sanitize_filename(long_name, max_length=255)
        assert len(result) == 255


class TestValidatePagination:
    """Tests for validate_pagination()"""

    def test_valid_params(self):
        from app.security import validate_pagination
        limit, offset = validate_pagination(50, 0)
        assert limit == 50
        assert offset == 0

    def test_zero_limit_raises(self):
        from app.security import validate_pagination
        with pytest.raises(HTTPException):
            validate_pagination(0, 0)

    def test_negative_offset_raises(self):
        from app.security import validate_pagination
        with pytest.raises(HTTPException):
            validate_pagination(10, -1)

    def test_over_max_limit_raises(self):
        from app.security import validate_pagination
        with pytest.raises(HTTPException):
            validate_pagination(20000, 0, max_limit=10000)


class TestValidateUrl:
    """Tests for validate_url()"""

    def test_valid_http(self):
        from app.security import validate_url
        assert validate_url("http://example.com") is True

    def test_valid_https(self):
        from app.security import validate_url
        assert validate_url("https://example.com") is True

    def test_no_scheme_raises(self):
        from app.security import validate_url
        with pytest.raises(HTTPException):
            validate_url("example.com")

    def test_empty_raises(self):
        from app.security import validate_url
        with pytest.raises(HTTPException):
            validate_url("")


class TestValidateApiKey:
    """Tests for validate_api_key()"""

    def test_valid_key(self):
        from app.security import validate_api_key
        assert validate_api_key("abcdefghij1234567890") is True

    def test_short_key_raises(self):
        from app.security import validate_api_key
        with pytest.raises(HTTPException):
            validate_api_key("short")

    def test_empty_key_raises(self):
        from app.security import validate_api_key
        with pytest.raises(HTTPException):
            validate_api_key("")

    def test_dangerous_chars_raise(self):
        from app.security import validate_api_key
        with pytest.raises(HTTPException):
            validate_api_key("abcdefghij\x00abcdefgh")
        with pytest.raises(HTTPException):
            validate_api_key("abcdefghij;drop table")
