"""
Tests for download task helper functions.
"""
import uuid
from datetime import datetime, timezone

import pytest

from tests.conftest import (
    create_test_artist,
    create_test_album,
    create_test_download,
    create_test_indexer,
    create_test_download_client,
)


class TestGetAttemptedGuidsForAlbum:
    def test_aggregates_across_downloads(self, db_session):
        from app.tasks.download_tasks import _get_attempted_guids_for_album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)

        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_guid="guid-1", status="failed",
            attempted_nzb_guids=["guid-1", "guid-2"]
        )
        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_guid="guid-3", status="failed",
            attempted_nzb_guids=["guid-3", "guid-4"]
        )

        guids = _get_attempted_guids_for_album(db_session, str(album.id))
        assert guids == {"guid-1", "guid-2", "guid-3", "guid-4"}

    def test_empty_for_no_downloads(self, db_session):
        from app.tasks.download_tasks import _get_attempted_guids_for_album

        guids = _get_attempted_guids_for_album(db_session, str(uuid.uuid4()))
        assert guids == set()

    def test_handles_null_attempted_guids(self, db_session):
        from app.tasks.download_tasks import _get_attempted_guids_for_album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)

        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_guid="guid-only", status="completed",
            attempted_nzb_guids=None
        )

        guids = _get_attempted_guids_for_album(db_session, str(album.id))
        assert "guid-only" in guids


class TestMarkDownloadFailed:
    def test_sets_status_and_error(self, db_session):
        from app.tasks.download_tasks import _mark_download_failed

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="downloading")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="downloading"
        )

        _mark_download_failed(
            db_session, download,
            error_message="Test failure",
            sab_fail_message="SAB: duplicate",
            reset_album_to_wanted=False
        )
        db_session.commit()

        assert download.status.value == "failed"
        assert download.error_message == "Test failure"
        assert download.sab_fail_message == "SAB: duplicate"

    def test_resets_album_to_wanted(self, db_session):
        from app.tasks.download_tasks import _mark_download_failed
        from app.models.album import Album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="downloading")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="downloading"
        )

        _mark_download_failed(
            db_session, download,
            error_message="dup",
            reset_album_to_wanted=True
        )
        db_session.commit()

        refreshed = db_session.query(Album).filter(Album.id == album.id).first()
        assert refreshed.status.value == "wanted"


class TestTriggerAutoRetry:
    """Legacy tests updated to reflect Phase 1/2 rewrite behavior."""

    def test_skips_when_retry_disabled_legacy(self, db_session):
        """Verify the function returns early when retry_enabled=False."""
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.album import Album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="wanted",
                                  retry_enabled=False)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="failed"
        )

        _trigger_auto_retry(db_session, download)

        db_session.refresh(album)
        assert album.next_retry_at is None  # nothing was scheduled

    def test_phase2_sets_next_retry_at_legacy(self, db_session):
        """With retry_enabled=True and no pending_alternates, next_retry_at is set."""
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.album import Album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="wanted",
                                  retry_enabled=True, download_retry_count=0)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="failed"
        )

        _trigger_auto_retry(db_session, download)
        db_session.commit()  # persist next_retry_at before refresh

        db_session.refresh(album)
        assert album.next_retry_at is not None

    def test_phase1_uses_pending_alternates_legacy(self, db_session):
        """With pending_alternates set, add_download is dispatched immediately."""
        from unittest.mock import patch, MagicMock
        from app.tasks.download_tasks import _trigger_auto_retry

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="failed",
                                  retry_enabled=True, download_retry_count=0)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="failed",
            pending_alternates=[{
                'nzb_url': 'http://alt', 'nzb_title': 'Alt',
                'nzb_guid': 'guid-alt', 'indexer_id': str(indexer.id),
                'size_bytes': 500,
            }],
        )

        mock_add = MagicMock()
        with patch('app.tasks.download_tasks.add_download', mock_add):
            _trigger_auto_retry(db_session, download)

        mock_add.apply_async.assert_called_once()
        assert download.pending_alternates is None


class TestTriggerAutoRetryRewrite:
    def test_phase1_uses_pending_alternates(self, db_session):
        from unittest.mock import patch, MagicMock
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.download_decision import DownloadHistory, DownloadEventType

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id,
                                  retry_enabled=True, download_retry_count=0)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status='failed',
            pending_alternates=[{
                'nzb_url': 'http://alt1', 'nzb_title': 'Alt 1',
                'nzb_guid': 'guid-alt-1', 'indexer_id': str(indexer.id),
                'size_bytes': 1000,
            }],
        )

        mock_add = MagicMock()
        with patch('app.tasks.download_tasks.add_download', mock_add):
            _trigger_auto_retry(db_session, download)

        db_session.commit()  # flush pending adds so we can query them

        mock_add.apply_async.assert_called_once()
        call_kwargs = mock_add.apply_async.call_args[1]['kwargs']
        assert call_kwargs['nzb_guid'] == 'guid-alt-1'
        assert download.pending_alternates is None

        event = db_session.query(DownloadHistory).filter(
            DownloadHistory.album_id == album.id,
            DownloadHistory.event_type == DownloadEventType.RETRY_SCHEDULED,
        ).first()
        assert event is not None
        assert event.data['phase'] == 'quick'

    def test_phase2_sets_next_retry_at_on_first_failure(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry
        from app.models.download_decision import DownloadHistory, DownloadEventType
        from datetime import timedelta, timezone
        from datetime import datetime

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id,
                                  retry_enabled=True, download_retry_count=0)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(db_session, album.id, indexer.id, dl_client.id,
                                        status='failed')

        before = datetime.now(timezone.utc)
        _trigger_auto_retry(db_session, download)
        db_session.commit()  # persist next_retry_at and RETRY_SCHEDULED event

        db_session.refresh(album)
        assert album.next_retry_at is not None
        # SQLite may return naive datetimes; normalise to UTC for comparison
        next_retry = album.next_retry_at
        if next_retry.tzinfo is None:
            next_retry = next_retry.replace(tzinfo=timezone.utc)
        delta = (next_retry - before).total_seconds()
        assert 3590 < delta < 3620  # ~1 hour

        event = db_session.query(DownloadHistory).filter(
            DownloadHistory.event_type == DownloadEventType.RETRY_SCHEDULED
        ).first()
        assert event is not None
        assert event.data['phase'] == 'fresh'

    def test_phase2_progressive_delay_at_count_1(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry
        from datetime import datetime, timezone

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id,
                                  retry_enabled=True, download_retry_count=1)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(db_session, album.id, indexer.id, dl_client.id,
                                        status='failed')

        before = datetime.now(timezone.utc)
        _trigger_auto_retry(db_session, download)
        db_session.commit()  # persist next_retry_at

        db_session.refresh(album)
        next_retry = album.next_retry_at
        if next_retry.tzinfo is None:
            next_retry = next_retry.replace(tzinfo=timezone.utc)
        delta = (next_retry - before).total_seconds()
        assert 21590 < delta < 21620  # ~6 hours

    def test_skips_when_retry_disabled(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=False)
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(db_session, album.id, indexer.id, dl_client.id,
                                        status='failed')

        _trigger_auto_retry(db_session, download)

        db_session.refresh(album)
        assert album.next_retry_at is None
