"""
Integration tests for Notifications API endpoints.
"""
import pytest
from unittest.mock import patch


class TestCreateNotification:
    def test_create_valid(self, client):
        resp = client.post("/api/v1/notifications", json={
            "name": "My Discord",
            "provider": "discord",
            "webhook_url": "https://discord.com/api/webhooks/123/abc",
            "events": ["album_downloaded", "album_failed"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "My Discord"
        assert data["provider"] == "discord"
        assert "album_downloaded" in data["events"]
        assert "id" in data

    def test_create_duplicate_name(self, client):
        payload = {
            "name": "Duplicate",
            "provider": "webhook",
            "webhook_url": "https://example.com/hook",
            "events": [],
        }
        resp1 = client.post("/api/v1/notifications", json=payload)
        assert resp1.status_code == 200
        resp2 = client.post("/api/v1/notifications", json=payload)
        assert resp2.status_code == 409

    def test_create_invalid_provider(self, client):
        resp = client.post("/api/v1/notifications", json={
            "name": "Bad Provider",
            "provider": "telegram",
            "webhook_url": "https://example.com",
            "events": [],
        })
        assert resp.status_code == 400
        assert "Invalid provider" in resp.json()["detail"]

    def test_create_invalid_event(self, client):
        resp = client.post("/api/v1/notifications", json={
            "name": "Bad Event",
            "provider": "webhook",
            "webhook_url": "https://example.com",
            "events": ["nonexistent_event"],
        })
        assert resp.status_code == 400
        assert "Invalid event" in resp.json()["detail"]


class TestListNotifications:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 0
        assert data["notifications"] == []

    def test_list_returns_all(self, client):
        for i in range(3):
            client.post("/api/v1/notifications", json={
                "name": f"Profile {i}",
                "provider": "webhook",
                "webhook_url": f"https://example.com/{i}",
                "events": [],
            })
        resp = client.get("/api/v1/notifications")
        assert resp.json()["total_count"] == 3


class TestUpdateNotification:
    def _create(self, client, name="Updatable"):
        resp = client.post("/api/v1/notifications", json={
            "name": name,
            "provider": "webhook",
            "webhook_url": "https://example.com",
            "events": ["album_downloaded"],
            "is_enabled": True,
        })
        return resp.json()["id"]

    def test_update_name(self, client):
        nid = self._create(client)
        resp = client.patch(f"/api/v1/notifications/{nid}", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    def test_update_events(self, client):
        nid = self._create(client)
        resp = client.patch(f"/api/v1/notifications/{nid}", json={
            "events": ["job_failed", "job_completed"]
        })
        assert resp.status_code == 200
        assert set(resp.json()["events"]) == {"job_failed", "job_completed"}

    def test_toggle_enabled(self, client):
        nid = self._create(client)
        resp = client.patch(f"/api/v1/notifications/{nid}", json={"is_enabled": False})
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False

    def test_update_nonexistent(self, client):
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = client.patch(f"/api/v1/notifications/{fake_id}", json={"name": "X"})
        assert resp.status_code == 404


class TestDeleteNotification:
    def test_delete_existing(self, client):
        resp = client.post("/api/v1/notifications", json={
            "name": "ToDelete",
            "provider": "webhook",
            "webhook_url": "https://example.com",
            "events": [],
        })
        nid = resp.json()["id"]
        resp = client.delete(f"/api/v1/notifications/{nid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify deleted
        list_resp = client.get("/api/v1/notifications")
        assert list_resp.json()["total_count"] == 0

    def test_delete_nonexistent(self, client):
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = client.delete(f"/api/v1/notifications/{fake_id}")
        assert resp.status_code == 404


class TestTestNotification:
    @patch("app.services.notification_service.requests.post")
    def test_send_test(self, mock_post, client):
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None

        resp = client.post("/api/v1/notifications", json={
            "name": "TestHook",
            "provider": "webhook",
            "webhook_url": "https://example.com/hook",
            "events": [],
        })
        nid = resp.json()["id"]

        resp = client.post(f"/api/v1/notifications/{nid}/test")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_post.assert_called_once()
