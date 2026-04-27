"""Integration tests for albums retry-control and download-history endpoints."""
import uuid
from datetime import datetime, timezone

import pytest

from tests.conftest import create_test_artist, create_test_album


class TestRetryControl:
    def test_disable_retry(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=True)

        resp = client.post(
            f"/api/v1/albums/{album.id}/retry-control",
            json={"retry_enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["retry_enabled"] is False
        assert body["next_retry_at"] is None

    def test_enable_retry_schedules_1h(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=False)

        resp = client.post(
            f"/api/v1/albums/{album.id}/retry-control",
            json={"retry_enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["retry_enabled"] is True
        assert body["next_retry_at"] is not None

    def test_returns_404_for_unknown_album(self, client, db_session):
        resp = client.post(
            f"/api/v1/albums/{uuid.uuid4()}/retry-control",
            json={"retry_enabled": False},
        )
        assert resp.status_code == 404

    def test_disable_clears_next_retry_at(self, client, db_session):
        from app.models.album import Album

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, retry_enabled=True)
        # Set a pending retry
        album.next_retry_at = datetime.now(timezone.utc)
        db_session.commit()

        resp = client.post(
            f"/api/v1/albums/{album.id}/retry-control",
            json={"retry_enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["next_retry_at"] is None

    def test_returns_retry_count(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, download_retry_count=3)

        resp = client.post(
            f"/api/v1/albums/{album.id}/retry-control",
            json={"retry_enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["download_retry_count"] == 3

    def test_invalid_uuid_returns_400(self, client, db_session):
        resp = client.post(
            "/api/v1/albums/not-a-uuid/retry-control",
            json={"retry_enabled": False},
        )
        assert resp.status_code == 400


class TestDownloadHistory:
    def test_returns_empty_events_for_new_album(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)

        resp = client.get(f"/api/v1/albums/{album.id}/download-history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["album_id"] == str(album.id)
        assert body["events"] == []
        assert body["retry_enabled"] is True
        assert body["download_retry_count"] == 0

    def test_returns_history_events(self, client, db_session):
        from app.models.download_decision import DownloadHistory, DownloadEventType

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)

        event = DownloadHistory(
            album_id=album.id,
            artist_id=artist.id,
            event_type=DownloadEventType.DOWNLOAD_FAILED,
            release_title='Artist - Album FLAC',
            message='Encrypted / Passworded',
            occurred_at=datetime.now(timezone.utc),
        )
        db_session.add(event)
        db_session.commit()

        resp = client.get(f"/api/v1/albums/{album.id}/download-history")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "download_failed"
        assert body["events"][0]["message"] == "Encrypted / Passworded"

    def test_returns_404_for_unknown_album(self, client, db_session):
        resp = client.get(f"/api/v1/albums/{uuid.uuid4()}/download-history")
        assert resp.status_code == 404

    def test_invalid_uuid_returns_400(self, client, db_session):
        resp = client.get("/api/v1/albums/not-a-uuid/download-history")
        assert resp.status_code == 400

    def test_events_ordered_newest_first(self, client, db_session):
        from app.models.download_decision import DownloadHistory, DownloadEventType
        from datetime import timedelta

        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id)

        now = datetime.now(timezone.utc)
        older = DownloadHistory(
            album_id=album.id,
            artist_id=artist.id,
            event_type=DownloadEventType.GRABBED,
            release_title='Old grab',
            occurred_at=now - timedelta(hours=2),
        )
        newer = DownloadHistory(
            album_id=album.id,
            artist_id=artist.id,
            event_type=DownloadEventType.DOWNLOAD_FAILED,
            release_title='New failure',
            occurred_at=now,
        )
        db_session.add_all([older, newer])
        db_session.commit()

        resp = client.get(f"/api/v1/albums/{album.id}/download-history")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 2
        assert events[0]["event_type"] == "download_failed"
        assert events[1]["event_type"] == "grabbed"
