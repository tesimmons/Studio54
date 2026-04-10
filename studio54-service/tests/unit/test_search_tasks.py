"""
Tests for search_tasks helper functions (Redis locks, constants).
"""
from unittest.mock import MagicMock, patch
import time

import pytest


class TestSearchLockConstants:
    """Tests for search lock configuration"""

    def test_lock_ttl(self):
        from app.tasks.search_tasks import SEARCH_LOCK_TTL
        assert SEARCH_LOCK_TTL == 300  # 5 minutes


class TestAcquireSearchLock:
    """Tests for _acquire_search_lock()"""

    @patch("app.tasks.search_tasks._get_redis")
    def test_acquires_when_free(self, mock_get_redis):
        from app.tasks.search_tasks import _acquire_search_lock

        mock_redis = MagicMock()
        mock_redis.set.return_value = True
        mock_get_redis.return_value = mock_redis

        assert _acquire_search_lock("album-123", "task-1") is True
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "search:album:album-123"
        assert call_args[1]["nx"] is True
        assert call_args[1]["ex"] == 300

    @patch("app.tasks.search_tasks._get_redis")
    def test_fails_when_locked(self, mock_get_redis):
        from app.tasks.search_tasks import _acquire_search_lock

        mock_redis = MagicMock()
        mock_redis.set.return_value = False
        mock_redis.get.return_value = b"other-task:12345"
        mock_get_redis.return_value = mock_redis

        assert _acquire_search_lock("album-123", "task-2") is False

    @patch("app.tasks.search_tasks._get_redis")
    def test_key_format(self, mock_get_redis):
        from app.tasks.search_tasks import _acquire_search_lock

        mock_redis = MagicMock()
        mock_redis.set.return_value = True
        mock_get_redis.return_value = mock_redis

        _acquire_search_lock("my-album-uuid", "task-x")
        key = mock_redis.set.call_args[0][0]
        assert key == "search:album:my-album-uuid"


class TestReleaseSearchLock:
    """Tests for _release_search_lock()"""

    @patch("app.tasks.search_tasks._get_redis")
    def test_deletes_lock_key(self, mock_get_redis):
        from app.tasks.search_tasks import _release_search_lock

        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        _release_search_lock("album-456")
        mock_redis.delete.assert_called_once_with("search:album:album-456")
