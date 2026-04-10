"""
Tests for app.services.sabnzbd_client — response parsing, error handling.
All HTTP calls are mocked.
"""
import pytest
from unittest.mock import patch, MagicMock
from app.services.sabnzbd_client import (
    SABnzbdClient,
    AddNzbResult,
    DownloadStatusResult,
)


@pytest.fixture
def client():
    return SABnzbdClient("http://localhost:8080", "test-api-key")


class TestAddNzbUrl:
    """Tests for SABnzbdClient.add_nzb_url()"""

    def test_successful_add(self, client):
        mock_response = {"status": True, "nzo_ids": ["SABnzbd_nzo_abc123"]}
        with patch.object(client, "_make_request", return_value=mock_response):
            with patch.object(client, "_get_raw_history_item", return_value=None):
                result = client.add_nzb_url("http://example.com/test.nzb", nzb_name="Test NZB")

        assert isinstance(result, AddNzbResult)
        assert result.success is True
        assert result.nzo_id == "SABnzbd_nzo_abc123"
        assert result.duplicate is False

    def test_connection_failure(self, client):
        with patch.object(client, "_make_request", return_value=None):
            result = client.add_nzb_url("http://example.com/test.nzb")

        assert result.success is False
        assert "connection failed" in result.error.lower()

    def test_api_error_response(self, client):
        mock_response = {"error": "API key incorrect", "status": False}
        with patch.object(client, "_make_request", return_value=mock_response):
            result = client.add_nzb_url("http://example.com/test.nzb")

        assert result.success is False
        assert "API" in result.error

    def test_discard_duplicate(self, client):
        """no_dupes=1: SABnzbd returns empty nzo_ids, status False"""
        mock_response = {"status": False, "nzo_ids": []}
        with patch.object(client, "_make_request", return_value=mock_response):
            result = client.add_nzb_url("http://example.com/test.nzb")

        assert result.success is False
        assert result.duplicate is True

    def test_fail_to_history_duplicate(self, client):
        """no_dupes=3: Returns nzo_id but job is already Failed in history"""
        mock_response = {"status": True, "nzo_ids": ["SABnzbd_nzo_dup1"]}
        mock_history = {
            "status": "Failed",
            "fail_message": "Duplicate NZB detected",
        }
        with patch.object(client, "_make_request", return_value=mock_response):
            with patch.object(client, "_get_raw_history_item", return_value=mock_history):
                result = client.add_nzb_url("http://example.com/test.nzb", nzb_name="Test")

        assert result.success is False
        assert result.duplicate is True
        assert result.nzo_id == "SABnzbd_nzo_dup1"


class TestGetDownloadStatus:
    """Tests for SABnzbdClient.get_download_status()"""

    def test_found_in_queue(self, client):
        queue_result = DownloadStatusResult(
            found=True,
            nzo_id="nzo_abc",
            name="Test Download",
            status="Downloading",
            percentage=45.0,
            in_history=False,
        )
        with patch.object(client, "_check_queue_for_nzo", return_value=queue_result):
            result = client.get_download_status("nzo_abc")

        assert result.found is True
        assert result.percentage == 45.0
        assert result.in_history is False

    def test_found_in_history(self, client):
        queue_not_found = DownloadStatusResult(found=False, nzo_id="nzo_abc")
        history_result = DownloadStatusResult(
            found=True,
            nzo_id="nzo_abc",
            name="Test Download",
            status="Completed",
            completed=True,
            in_history=True,
        )
        with patch.object(client, "_check_queue_for_nzo", return_value=queue_not_found):
            with patch.object(client, "_check_history_for_nzo", return_value=history_result):
                result = client.get_download_status("nzo_abc")

        assert result.found is True
        assert result.completed is True
        assert result.in_history is True

    def test_not_found_anywhere(self, client):
        not_found = DownloadStatusResult(found=False, nzo_id="nzo_gone")
        with patch.object(client, "_check_queue_for_nzo", return_value=not_found):
            with patch.object(client, "_check_history_for_nzo", return_value=not_found):
                result = client.get_download_status("nzo_gone")

        assert result.found is False


class TestCheckQueueForNzo:
    """Tests for SABnzbdClient._check_queue_for_nzo()"""

    def test_parses_queue_slot(self, client):
        mock_response = {
            "queue": {
                "slots": [
                    {
                        "nzo_id": "nzo_test",
                        "filename": "Test.Album-FLAC",
                        "status": "Downloading",
                        "percentage": "72",
                        "mb": "500.0",
                        "mbleft": "140.0",
                        "timeleft": "0:05:30",
                        "cat": "music",
                        "labels": [],
                    }
                ]
            }
        }
        with patch.object(client, "_make_request", return_value=mock_response):
            result = client._check_queue_for_nzo("nzo_test")

        assert result.found is True
        assert result.percentage == 72.0
        assert result.name == "Test.Album-FLAC"
        assert result.category == "music"

    def test_duplicate_label_detection(self, client):
        mock_response = {
            "queue": {
                "slots": [
                    {
                        "nzo_id": "nzo_dup",
                        "filename": "Duplicate.Album",
                        "status": "Paused",
                        "percentage": "0",
                        "mb": "0",
                        "mbleft": "0",
                        "labels": ["DUPLICATE"],
                        "cat": "music",
                    }
                ]
            }
        }
        with patch.object(client, "_make_request", return_value=mock_response):
            result = client._check_queue_for_nzo("nzo_dup")

        assert result.is_duplicate is True

    def test_empty_queue(self, client):
        mock_response = {"queue": {"slots": []}}
        with patch.object(client, "_make_request", return_value=mock_response):
            result = client._check_queue_for_nzo("nzo_missing")

        assert result.found is False


class TestCheckHistoryForNzo:
    """Tests for SABnzbdClient._check_history_for_nzo()"""

    def test_completed_download(self, client):
        mock_history = {
            "nzo_id": "nzo_done",
            "name": "Complete.Album",
            "status": "Completed",
            "bytes": 524288000,
            "storage": "/downloads/music/Complete.Album",
            "category": "music",
            "fail_message": "",
            "stage_log": [],
        }
        with patch.object(client, "_get_raw_history_item", return_value=mock_history):
            result = client._check_history_for_nzo("nzo_done")

        assert result.found is True
        assert result.completed is True
        assert result.download_path == "/downloads/music/Complete.Album"
        assert result.fail_message is None  # empty string becomes None

    def test_failed_download_with_message(self, client):
        mock_history = {
            "nzo_id": "nzo_fail",
            "name": "Failed.Album",
            "status": "Failed",
            "bytes": 0,
            "storage": "",
            "category": "music",
            "fail_message": "Out of disk space",
            "stage_log": [],
        }
        with patch.object(client, "_get_raw_history_item", return_value=mock_history):
            result = client._check_history_for_nzo("nzo_fail")

        assert result.found is True
        assert result.completed is False
        assert result.fail_message == "Out of disk space"


class TestGetQueue:
    """Tests for SABnzbdClient.get_queue()"""

    def test_parses_multiple_slots(self, client):
        mock_response = {
            "queue": {
                "slots": [
                    {"nzo_id": "a", "filename": "A", "status": "Downloading",
                     "percentage": "50", "mb": "100", "mbleft": "50",
                     "timeleft": "0:01:00", "priority": "0", "cat": "music",
                     "labels": []},
                    {"nzo_id": "b", "filename": "B", "status": "Queued",
                     "percentage": "0", "mb": "200", "mbleft": "200",
                     "timeleft": "0:10:00", "priority": "0", "cat": "music",
                     "labels": []},
                ]
            }
        }
        with patch.object(client, "_make_request", return_value=mock_response):
            result = client.get_queue()

        assert len(result) == 2
        assert result[0]["nzo_id"] == "a"
        assert result[1]["nzo_id"] == "b"

    def test_empty_response(self, client):
        with patch.object(client, "_make_request", return_value=None):
            result = client.get_queue()
        assert result == []


class TestTestConnection:
    """Tests for SABnzbdClient.test_connection()"""

    def test_successful_connection(self, client):
        with patch.object(client, "_make_request", return_value={"version": "4.2.1"}):
            assert client.test_connection() is True

    def test_failed_connection(self, client):
        with patch.object(client, "_make_request", return_value=None):
            assert client.test_connection() is False
