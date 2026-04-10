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
    def test_respects_max_retries(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="wanted")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="failed", retry_count=3
        )

        # Should not increment retry_count or trigger search
        _trigger_auto_retry(db_session, download)
        assert download.retry_count == 3  # unchanged

    def test_increments_retry_count(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry
        from unittest.mock import patch

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="wanted")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="failed", retry_count=1
        )

        with patch("app.tasks.download_tasks.search_album.apply_async"):
            _trigger_auto_retry(db_session, download)

        assert download.retry_count == 2

    def test_skips_non_wanted_album(self, db_session):
        from app.tasks.download_tasks import _trigger_auto_retry

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="downloaded")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)
        download = create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            status="failed", retry_count=0
        )

        _trigger_auto_retry(db_session, download)
        # Should increment but not trigger search (album not WANTED/FAILED)
        assert download.retry_count == 1
