"""
Integration tests for the Artists API endpoints.
Tests CRUD operations and artist management via the FastAPI TestClient.
"""
import uuid
import pytest
from tests.conftest import create_test_artist, create_test_album


class TestGetArtist:
    """Tests for GET /api/v1/artists/{id}"""

    def test_get_existing(self, client, db_session):
        artist = create_test_artist(db_session, name="Test Artist")

        response = client.get(f"/api/v1/artists/{artist.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Artist"
        assert data["is_monitored"] is True
        assert data["monitor_type"] == "all_albums"

    def test_get_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/artists/{fake_id}")
        assert response.status_code == 404

    def test_get_invalid_uuid(self, client):
        response = client.get("/api/v1/artists/not-a-uuid")
        assert response.status_code == 400

    def test_get_includes_albums(self, client, db_session):
        artist = create_test_artist(db_session, name="Artist With Albums")
        create_test_album(db_session, artist_id=artist.id, title="Album One")
        create_test_album(db_session, artist_id=artist.id, title="Album Two")

        response = client.get(f"/api/v1/artists/{artist.id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["albums"]) == 2


class TestDeleteArtist:
    """Tests for DELETE /api/v1/artists/{id}"""

    def test_delete_existing(self, client, db_session):
        artist = create_test_artist(db_session, name="To Delete")

        response = client.delete(f"/api/v1/artists/{artist.id}")
        assert response.status_code == 200

        # Verify deleted
        response = client.get(f"/api/v1/artists/{artist.id}")
        assert response.status_code == 404

    def test_delete_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/artists/{fake_id}")
        assert response.status_code == 404


class TestUpdateArtist:
    """Tests for PATCH /api/v1/artists/{id} — uses query params, not JSON body"""

    def test_update_monitoring(self, client, db_session):
        artist = create_test_artist(db_session, name="Update Me", is_monitored=True)

        # The PATCH endpoint uses query params
        response = client.patch(
            f"/api/v1/artists/{artist.id}?is_monitored=false"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_monitored"] is False

    def test_update_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        response = client.patch(
            f"/api/v1/artists/{fake_id}?is_monitored=false"
        )
        assert response.status_code == 404
