"""
Integration tests for Settings-related API endpoints:
- Quality Profiles
- Download Clients
- Indexers
- Root Folders (limited due to filesystem dependency)
"""
import uuid
from unittest.mock import patch

import pytest

from tests.conftest import (
    create_test_indexer,
    create_test_download_client,
)


# ── Quality Profiles ──────────────────────────────────────────

class TestQualityProfiles:
    """Tests for /api/v1/quality-profiles"""

    def test_list_auto_seeds_defaults(self, client):
        response = client.get("/api/v1/quality-profiles")
        assert response.status_code == 200
        data = response.json()
        assert "quality_profiles" in data
        # Auto-seed creates default profiles on first call
        assert len(data["quality_profiles"]) >= 1

    def test_create_profile(self, client):
        payload = {
            "name": "Test FLAC Only",
            "allowed_formats": ["FLAC"],
            "preferred_formats": ["FLAC"],
            "min_bitrate": 800,
            "upgrade_enabled": False,
            "is_default": False,
        }
        response = client.post("/api/v1/quality-profiles", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test FLAC Only"
        assert "FLAC" in data["allowed_formats"]

    def test_create_and_list(self, client):
        # Create a profile
        payload = {
            "name": "Custom MP3",
            "allowed_formats": ["MP3"],
            "preferred_formats": [],
        }
        client.post("/api/v1/quality-profiles", json=payload)

        # List should include it
        response = client.get("/api/v1/quality-profiles")
        names = [p["name"] for p in response.json()["quality_profiles"]]
        assert "Custom MP3" in names

    def test_delete_profile(self, client):
        # Create then delete
        payload = {
            "name": "To Delete",
            "allowed_formats": ["FLAC", "MP3"],
        }
        create_resp = client.post("/api/v1/quality-profiles", json=payload)
        profile_id = create_resp.json()["id"]

        del_resp = client.delete(f"/api/v1/quality-profiles/{profile_id}")
        assert del_resp.status_code == 200

    def test_delete_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/quality-profiles/{fake_id}")
        assert response.status_code == 404


# ── Download Clients ──────────────────────────────────────────

class TestDownloadClients:
    """Tests for /api/v1/download-clients"""

    def test_add_client(self, client):
        payload = {
            "name": "Test SABnzbd",
            "host": "192.168.1.100",
            "port": 8080,
            "api_key": "test-key-123",
            "is_default": True,
        }
        response = client.post("/api/v1/download-clients", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test SABnzbd"
        assert data["host"] == "192.168.1.100"
        assert data["is_default"] is True
        # API key should NOT be returned in list responses
        assert "api_key" not in data or data.get("api_key") is None

    def test_list_clients(self, client, db_session):
        create_test_download_client(db_session, name="Client A")
        create_test_download_client(db_session, name="Client B", is_default=False)

        response = client.get("/api/v1/download-clients")
        assert response.status_code == 200
        data = response.json()
        assert len(data["clients"]) >= 2

    def test_get_client_by_id(self, client, db_session):
        dl_client = create_test_download_client(db_session, name="Specific Client")

        response = client.get(f"/api/v1/download-clients/{dl_client.id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Specific Client"

    def test_get_nonexistent_client(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/download-clients/{fake_id}")
        assert response.status_code == 404

    def test_delete_client(self, client, db_session):
        dl_client = create_test_download_client(db_session, name="Delete Me")

        response = client.delete(f"/api/v1/download-clients/{dl_client.id}")
        assert response.status_code == 200

        # Verify gone
        response = client.get(f"/api/v1/download-clients/{dl_client.id}")
        assert response.status_code == 404


# ── Indexers ──────────────────────────────────────────────────

class TestIndexers:
    """Tests for /api/v1/indexers"""

    def test_add_indexer(self, client):
        payload = {
            "name": "Test NZB Indexer",
            "base_url": "https://nzb.example.com",
            "api_key": "indexer-key-456",
            "is_enabled": True,
        }
        response = client.post("/api/v1/indexers", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test NZB Indexer"
        assert data["base_url"] == "https://nzb.example.com"

    def test_list_indexers(self, client, db_session):
        create_test_indexer(db_session, name="Indexer A")
        create_test_indexer(db_session, name="Indexer B")

        response = client.get("/api/v1/indexers")
        assert response.status_code == 200
        data = response.json()
        assert len(data["indexers"]) >= 2

    def test_get_indexer_by_id(self, client, db_session):
        indexer = create_test_indexer(db_session, name="Specific Indexer")

        response = client.get(f"/api/v1/indexers/{indexer.id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Specific Indexer"

    def test_get_nonexistent_indexer(self, client):
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/indexers/{fake_id}")
        assert response.status_code == 404

    def test_delete_indexer(self, client, db_session):
        indexer = create_test_indexer(db_session, name="Delete Me")

        response = client.delete(f"/api/v1/indexers/{indexer.id}")
        assert response.status_code == 200

        response = client.get(f"/api/v1/indexers/{indexer.id}")
        assert response.status_code == 404

    def test_get_indexer_api_key(self, client, db_session):
        indexer = create_test_indexer(db_session, name="Key Test", api_key="secret-key-789")

        response = client.get(f"/api/v1/indexers/{indexer.id}/api-key")
        assert response.status_code == 200
        data = response.json()
        assert data["api_key"] == "secret-key-789"


# ── Root Folders ──────────────────────────────────────────────

class TestRootFolders:
    """Tests for /api/v1/root-folders"""

    def test_list_empty(self, client):
        response = client.get("/api/v1/root-folders")
        assert response.status_code == 200
        data = response.json()
        assert "root_folders" in data

    def test_add_requires_existing_path(self, client):
        payload = {"path": "/nonexistent/path/for/testing"}
        response = client.post("/api/v1/root-folders", json=payload)
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]

    def test_add_empty_path(self, client):
        payload = {"path": ""}
        response = client.post("/api/v1/root-folders", json=payload)
        assert response.status_code == 400

    @patch("app.api.root_folders.os.path.exists", return_value=True)
    @patch("app.api.root_folders.os.path.isdir", return_value=True)
    def test_add_root_folder_with_mock_path(self, mock_isdir, mock_exists, client):
        payload = {"path": "/music/library", "name": "My Music"}
        response = client.post("/api/v1/root-folders", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "/music/library"

    def test_delete_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        response = client.delete(f"/api/v1/root-folders/{fake_id}")
        assert response.status_code == 404
