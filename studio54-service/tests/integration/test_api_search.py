"""
Integration tests for Search and Queue API endpoints.
"""
import uuid

import pytest

from tests.conftest import (
    create_test_artist,
    create_test_album,
    create_test_download,
    create_test_indexer,
    create_test_download_client,
)


# ── Search Endpoints ──────────────────────────────────────────

class TestSearchMissing:
    """Tests for POST /api/v1/search/missing"""

    def test_search_missing_no_wanted(self, client, db_session):
        """When no albums are wanted, should return quickly"""
        artist = create_test_artist(db_session)
        create_test_album(db_session, artist.id, status="downloaded")

        response = client.post("/api/v1/search/missing")
        assert response.status_code == 200

    def test_search_missing_with_artist_filter(self, client, db_session):
        """Filter search to a specific artist"""
        artist = create_test_artist(db_session, name="Filtered Artist")
        create_test_album(db_session, artist.id, status="wanted", title="Wanted Album")

        response = client.post(
            f"/api/v1/search/missing?artist_id={artist.id}"
        )
        assert response.status_code == 200

    def test_search_missing_invalid_artist_id(self, client):
        response = client.post(
            "/api/v1/search/missing?artist_id=not-a-uuid"
        )
        assert response.status_code == 400


# ── Queue Endpoints ───────────────────────────────────────────

class TestQueueList:
    """Tests for GET /api/v1/queue"""

    def test_empty_queue(self, client):
        response = client.get("/api/v1/queue")
        assert response.status_code == 200

    def test_queue_item_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/queue/{fake_id}")
        assert response.status_code == 404


class TestQueueHistory:
    """Tests for GET /api/v1/queue/history"""

    def test_empty_history(self, client):
        response = client.get("/api/v1/queue/history")
        assert response.status_code == 200
