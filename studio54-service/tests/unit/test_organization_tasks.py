"""
Tests for organization_tasks helper classes and functions.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest


class TestErrorCategory:
    """Tests for ErrorCategory constants and NON_FATAL_CATEGORIES"""

    def test_file_not_exist_is_non_fatal(self):
        from app.tasks.organization_tasks import ErrorCategory
        assert ErrorCategory.FILE_NOT_EXIST in ErrorCategory.NON_FATAL_CATEGORIES

    def test_already_exists_is_non_fatal(self):
        from app.tasks.organization_tasks import ErrorCategory
        assert ErrorCategory.ALREADY_EXISTS in ErrorCategory.NON_FATAL_CATEGORIES

    def test_permission_error_is_fatal(self):
        from app.tasks.organization_tasks import ErrorCategory
        assert ErrorCategory.PERMISSION_ERROR not in ErrorCategory.NON_FATAL_CATEGORIES

    def test_other_is_fatal(self):
        from app.tasks.organization_tasks import ErrorCategory
        assert ErrorCategory.OTHER not in ErrorCategory.NON_FATAL_CATEGORIES


class TestErrorTracker:
    """Tests for ErrorTracker categorization and tracking"""

    def test_categorize_file_not_found(self):
        from app.tasks.organization_tasks import ErrorTracker, ErrorCategory
        tracker = ErrorTracker()
        assert tracker.categorize_error("File does not exist") == ErrorCategory.FILE_NOT_EXIST
        assert tracker.categorize_error("No such file or directory") == ErrorCategory.FILE_NOT_EXIST
        assert tracker.categorize_error("Track not found in DB") == ErrorCategory.FILE_NOT_EXIST

    def test_categorize_already_exists(self):
        from app.tasks.organization_tasks import ErrorTracker, ErrorCategory
        tracker = ErrorTracker()
        assert tracker.categorize_error("Destination already exists") == ErrorCategory.ALREADY_EXISTS
        assert tracker.categorize_error("Target file exists") == ErrorCategory.ALREADY_EXISTS

    def test_categorize_permission_error(self):
        from app.tasks.organization_tasks import ErrorTracker, ErrorCategory
        tracker = ErrorTracker()
        assert tracker.categorize_error("Permission denied") == ErrorCategory.PERMISSION_ERROR
        assert tracker.categorize_error("Access denied to path") == ErrorCategory.PERMISSION_ERROR

    def test_categorize_other(self):
        from app.tasks.organization_tasks import ErrorTracker, ErrorCategory
        tracker = ErrorTracker()
        assert tracker.categorize_error("Some unknown error") == ErrorCategory.OTHER

    def test_add_non_fatal_returns_false(self):
        from app.tasks.organization_tasks import ErrorTracker
        tracker = ErrorTracker()
        is_fatal = tracker.add_error("/path/to/file.mp3", "File does not exist")
        assert is_fatal is False

    def test_add_fatal_returns_true(self):
        from app.tasks.organization_tasks import ErrorTracker
        tracker = ErrorTracker()
        is_fatal = tracker.add_error("/path/to/file.mp3", "Permission denied")
        assert is_fatal is True

    def test_fatal_error_count(self):
        from app.tasks.organization_tasks import ErrorTracker
        tracker = ErrorTracker()
        tracker.add_error("/a.mp3", "Permission denied")
        tracker.add_error("/b.mp3", "File does not exist")  # non-fatal
        tracker.add_error("/c.mp3", "Some random error")     # fatal (OTHER)
        assert tracker.get_fatal_error_count() == 2
        assert tracker.get_total_errors() == 3


class TestBackgroundHeartbeat:
    """Tests for BackgroundHeartbeat context manager lifecycle"""

    def test_enter_starts_thread(self):
        from app.tasks.organization_tasks import BackgroundHeartbeat
        hb = BackgroundHeartbeat("test-job-id", MagicMock, interval=60)
        hb.__enter__()
        assert hb._thread is not None
        # Thread is running the heartbeat loop (blocked on _stop_event.wait)
        assert hb._thread.is_alive()
        hb.__exit__(None, None, None)

    def test_exit_stops_thread(self):
        from app.tasks.organization_tasks import BackgroundHeartbeat
        hb = BackgroundHeartbeat("test-job-id", MagicMock, interval=60)
        with patch.object(hb, '_heartbeat_loop'):
            hb.__enter__()
            hb.__exit__(None, None, None)
            assert hb._stop_event.is_set()

    def test_context_manager_protocol(self):
        from app.tasks.organization_tasks import BackgroundHeartbeat
        with patch.object(BackgroundHeartbeat, '_heartbeat_loop'):
            with BackgroundHeartbeat("test-job-id", MagicMock, interval=60) as hb:
                assert hb._thread is not None
            assert hb._stop_event.is_set()


class TestConstants:
    """Tests for module constants"""

    def test_batch_size(self):
        from app.tasks.organization_tasks import BATCH_SIZE
        assert BATCH_SIZE == 100

    def test_max_fatal_errors(self):
        from app.tasks.organization_tasks import MAX_FATAL_ERRORS
        assert MAX_FATAL_ERRORS == 5
