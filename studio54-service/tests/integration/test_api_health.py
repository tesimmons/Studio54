"""
Integration tests for health and stats endpoints.
Smoke-tests that the app starts and core endpoints respond.
"""
import pytest


class TestRootEndpoint:
    """Tests for GET /"""

    def test_root_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "version" in data

    def test_root_has_docs_link(self, client):
        response = client.get("/")
        data = response.json()
        assert data["docs"] == "/docs"


class TestHealthEndpoint:
    """Tests for GET /health"""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "database" in data

    def test_health_database_connected(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["database"] == "connected"


class TestStatsEndpoint:
    """Tests for GET /stats"""

    def test_stats_returns_200(self, client):
        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_artists" in data
        assert "total_albums" in data
        assert "wanted_albums" in data
        assert "active_downloads" in data

    def test_stats_empty_db_zeros(self, client):
        response = client.get("/stats")
        data = response.json()
        assert data["total_artists"] == 0
        assert data["total_albums"] == 0
        assert data["active_downloads"] == 0
