"""
Tests for notification service formatting and dispatch logic.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.services.notification_service import (
    _format_webhook,
    _format_discord,
    _format_slack,
    _event_title,
    _event_color,
    _event_description,
    send_notification,
)


class TestFormatWebhook:
    def test_structure(self):
        result = _format_webhook("album_downloaded", {"message": "test"})
        assert result["event"] == "album_downloaded"
        assert "timestamp" in result
        assert result["data"] == {"message": "test"}

    def test_empty_payload(self):
        result = _format_webhook("test", {})
        assert result["data"] == {}
        assert result["event"] == "test"


class TestFormatDiscord:
    def test_has_embeds(self):
        result = _format_discord("album_downloaded", {"artist_name": "Beatles"})
        assert "embeds" in result
        assert len(result["embeds"]) == 1

    def test_embed_color(self):
        result = _format_discord("album_downloaded", {"message": "done"})
        embed = result["embeds"][0]
        assert embed["color"] == 0x2ECC71  # green

    def test_embed_fields_exclude_message(self):
        payload = {"message": "hello", "artist_name": "Beatles", "album_title": "Abbey Road"}
        result = _format_discord("album_downloaded", payload)
        field_names = [f["name"] for f in result["embeds"][0]["fields"]]
        assert "message" not in field_names
        assert "artist_name" in field_names

    def test_embed_footer(self):
        result = _format_discord("test", {"x": 1})
        assert result["embeds"][0]["footer"]["text"] == "Studio54"


class TestFormatSlack:
    def test_block_kit_structure(self):
        result = _format_slack("album_downloaded", {"message": "done"})
        assert "blocks" in result
        types = [b["type"] for b in result["blocks"]]
        assert "header" in types
        assert "section" in types
        assert "context" in types

    def test_header_text(self):
        result = _format_slack("album_downloaded", {"message": "ok"})
        header = result["blocks"][0]
        assert header["text"]["text"] == "Album Downloaded"

    def test_fields_section(self):
        result = _format_slack("test", {"artist_name": "X", "album_title": "Y"})
        field_blocks = [b for b in result["blocks"] if b["type"] == "section" and "fields" in b]
        assert len(field_blocks) == 1


class TestEventHelpers:
    def test_event_title_known(self):
        assert _event_title("album_downloaded") == "Album Downloaded"
        assert _event_title("album_failed") == "Album Download Failed"
        assert _event_title("job_failed") == "Job Failed"

    def test_event_title_unknown(self):
        assert _event_title("some_custom_event") == "Some Custom Event"

    def test_event_color_known(self):
        assert _event_color("album_downloaded") == 0x2ECC71
        assert _event_color("album_failed") == 0xE74C3C
        assert _event_color("artist_added") == 0x9B59B6

    def test_event_color_unknown_returns_gray(self):
        assert _event_color("unknown_event") == 0x95A5A6

    def test_event_description_with_message(self):
        assert _event_description("x", {"message": "hello"}) == "hello"

    def test_event_description_artist_album(self):
        desc = _event_description("x", {"artist_name": "A", "album_title": "B"})
        assert desc == "A - B"

    def test_event_description_fallback(self):
        desc = _event_description("album_downloaded", {})
        assert desc == "Album Downloaded"


class TestSendNotification:
    @patch("app.services.notification_service._send_to_profile")
    def test_sends_to_matching_profiles(self, mock_send, db_session):
        from tests.conftest import create_test_notification_profile

        profile = create_test_notification_profile(
            db_session, events=["album_downloaded"]
        )
        send_notification("album_downloaded", {"message": "test"}, db=db_session)
        mock_send.assert_called_once()

    @patch("app.services.notification_service._send_to_profile")
    def test_skips_non_matching_event(self, mock_send, db_session):
        from tests.conftest import create_test_notification_profile

        create_test_notification_profile(
            db_session, events=["job_failed"]
        )
        send_notification("album_downloaded", {"message": "test"}, db=db_session)
        mock_send.assert_not_called()

    @patch("app.services.notification_service._send_to_profile")
    def test_skips_disabled_profiles(self, mock_send, db_session):
        from tests.conftest import create_test_notification_profile

        create_test_notification_profile(
            db_session, is_enabled=False, events=["album_downloaded"]
        )
        send_notification("album_downloaded", {"message": "test"}, db=db_session)
        mock_send.assert_not_called()
