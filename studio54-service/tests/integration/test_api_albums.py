"""
Integration tests for Albums API endpoints.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from tests.conftest import (
    create_test_artist,
    create_test_album,
    create_test_track,
    create_test_download,
    create_test_indexer,
    create_test_download_client,
)


class TestListAlbums:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/albums")
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 0

    def test_list_with_status_filter(self, client, db_session):
        artist = create_test_artist(db_session)
        create_test_album(db_session, artist.id, title="Wanted Album", status="wanted")
        create_test_album(db_session, artist.id, title="Downloaded Album", status="downloaded")

        resp = client.get("/api/v1/albums?status_filter=wanted")
        data = resp.json()
        assert data["total_count"] == 1
        assert data["albums"][0]["title"] == "Wanted Album"

    def test_list_with_artist_filter(self, client, db_session):
        a1 = create_test_artist(db_session, name="Artist One")
        a2 = create_test_artist(db_session, name="Artist Two")
        create_test_album(db_session, a1.id, title="A1 Album")
        create_test_album(db_session, a2.id, title="A2 Album")

        resp = client.get(f"/api/v1/albums?artist_id={a1.id}")
        assert resp.json()["total_count"] == 1
        assert resp.json()["albums"][0]["artist_name"] == "Artist One"


class TestGetAlbum:
    def test_get_existing(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, title="My Album")
        create_test_track(db_session, album.id, title="Track 1", track_number=1)

        resp = client.get(f"/api/v1/albums/{album.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "My Album"
        assert len(data["tracks"]) == 1
        assert data["tracks"][0]["title"] == "Track 1"

    def test_get_missing_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/albums/{fake_id}")
        assert resp.status_code == 404


class TestUpdateAlbum:
    def test_update_monitored(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, monitored=False)

        resp = client.patch(f"/api/v1/albums/{album.id}", json={"monitored": True})
        assert resp.status_code == 200
        assert resp.json()["monitored"] is True

    def test_update_status(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="wanted")

        resp = client.patch(f"/api/v1/albums/{album.id}", json={"status": "downloaded"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "downloaded"


class TestDownloadCleanupPreview:
    def test_preview_counts(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="downloaded")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)

        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_title="Old Complete", status="completed",
            completed_at=old_date
        )
        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_title="Old Failed", status="failed",
            completed_at=old_date
        )
        # Recent download - should not be eligible
        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_title="Recent Complete", status="completed",
            completed_at=datetime.now(timezone.utc)
        )

        resp = client.get("/api/v1/downloads/cleanup/preview?retention_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_eligible"] == 1
        assert data["failed_eligible"] == 1
        assert data["total_eligible"] == 2

    def test_preview_preserves_wanted_album_failed_downloads(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="wanted")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)

        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_title="Failed for wanted", status="failed",
            completed_at=old_date
        )

        resp = client.get("/api/v1/downloads/cleanup/preview?retention_days=30")
        data = resp.json()
        assert data["failed_eligible"] == 0
        assert data["failed_preserved"] == 1


class TestDownloadCleanupExecute:
    def test_execute_cleanup(self, client, db_session):
        artist = create_test_artist(db_session)
        album = create_test_album(db_session, artist.id, status="downloaded")
        indexer = create_test_indexer(db_session)
        dl_client = create_test_download_client(db_session)

        old_date = datetime.now(timezone.utc) - timedelta(days=60)
        create_test_download(
            db_session, album.id, indexer.id, dl_client.id,
            nzb_title="Old Complete", status="completed",
            completed_at=old_date
        )

        resp = client.post("/api/v1/downloads/cleanup?retention_days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["total_deleted"] == 1
        assert data["completed_deleted"] == 1
