"""
Tests for sync_tasks helper functions.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from tests.conftest import create_test_artist, create_test_album


class TestParseMbDate:
    """Tests for _parse_mb_date()"""

    def test_full_date(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("2024-03-15") == date(2024, 3, 15)

    def test_year_month(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("2024-03") == date(2024, 3, 1)

    def test_year_only(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("2024") == date(2024, 1, 1)

    def test_none_input(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date(None) is None

    def test_empty_string(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("") is None

    def test_invalid_string(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("not-a-date") is None

    def test_invalid_month(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("2024-13-01") is None

    def test_invalid_day(self):
        from app.tasks.sync_tasks import _parse_mb_date
        assert _parse_mb_date("2024-02-30") is None

    def test_zero_year(self):
        from app.tasks.sync_tasks import _parse_mb_date
        # Year 0 is not valid for date(), should return None
        assert _parse_mb_date("0000") is None


class TestShouldMonitorAlbum:
    """Tests for should_monitor_album()"""

    def _make_artist(self, is_monitored=True, monitor_type="all_albums"):
        artist = MagicMock()
        artist.is_monitored = is_monitored
        artist.monitor_type = monitor_type
        return artist

    def test_unmonitored_artist_returns_false(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(is_monitored=False)
        assert should_monitor_album(artist) is False

    def test_all_albums(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="all_albums")
        assert should_monitor_album(artist) is True

    def test_none_monitor_type(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="none")
        assert should_monitor_album(artist) is False

    def test_future_only_with_future_date(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="future_only")
        future = date.today() + timedelta(days=30)
        assert should_monitor_album(artist, release_date=future) is True

    def test_future_only_with_past_date(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="future_only")
        past = date.today() - timedelta(days=30)
        assert should_monitor_album(artist, release_date=past) is False

    def test_future_only_with_today(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="future_only")
        assert should_monitor_album(artist, release_date=date.today()) is False

    def test_future_only_no_date(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="future_only")
        assert should_monitor_album(artist, release_date=None) is False

    def test_existing_only_with_local_files(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="existing_only")
        assert should_monitor_album(artist, has_local_files=True) is True

    def test_existing_only_without_local_files(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="existing_only")
        assert should_monitor_album(artist, has_local_files=False) is False

    def test_first_album_index_zero(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="first_album")
        assert should_monitor_album(artist, album_index=0, total_albums=5) is True

    def test_first_album_index_nonzero(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="first_album")
        assert should_monitor_album(artist, album_index=2, total_albums=5) is False

    def test_latest_album_last_index(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="latest_album")
        assert should_monitor_album(artist, album_index=4, total_albums=5) is True

    def test_latest_album_not_last_index(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="latest_album")
        assert should_monitor_album(artist, album_index=0, total_albums=5) is False

    def test_latest_album_zero_total(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="latest_album")
        # When total_albums=0, should return True (fallback)
        assert should_monitor_album(artist, album_index=0, total_albums=0) is True

    def test_unknown_monitor_type_defaults_true(self):
        from app.tasks.sync_tasks import should_monitor_album
        artist = self._make_artist(monitor_type="unknown_type")
        assert should_monitor_album(artist) is True


class TestUpdateArtistStats:
    """Tests for _update_artist_stats()"""

    def test_counts_albums_and_singles(self, db_session):
        from app.tasks.sync_tasks import _update_artist_stats

        artist = create_test_artist(db_session, name="Stats Artist")
        create_test_album(db_session, artist.id, title="Album 1", album_type="Album", track_count=10)
        create_test_album(db_session, artist.id, title="Album 2", album_type="Album", track_count=12)
        create_test_album(db_session, artist.id, title="Single 1", album_type="Single", track_count=1)

        _update_artist_stats(db_session, artist)

        assert artist.album_count == 2
        assert artist.single_count == 1
        assert artist.track_count == 23

    def test_empty_artist(self, db_session):
        from app.tasks.sync_tasks import _update_artist_stats

        artist = create_test_artist(db_session, name="Empty Artist")
        _update_artist_stats(db_session, artist)

        assert artist.album_count == 0
        assert artist.single_count == 0
        assert artist.track_count == 0
