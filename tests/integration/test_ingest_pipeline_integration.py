"""Integration tests for ingest pipeline API endpoints.

Validates the FastAPI endpoints against real PostgREST and Redis.
Covers the feat/ingest-orchestration branch.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean(clean_tables, redis_client):
    """Ensure tables and Redis are clean before each test."""
    redis_client.flushdb()
    yield
    redis_client.flushdb()


class TestIngestRunEndpoint:
    def test_dry_run_returns_200(self, test_client, integration_env):
        resp = test_client.post(
            "/v1/ingest/run",
            json={"area_id": "bucharest", "dry_run": True},
            headers={"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        assert "summary" in body

    def test_max_events_capping(self, test_client, integration_env):
        resp = test_client.post(
            "/v1/ingest/run",
            json={"area_id": "bucharest", "dry_run": True, "max_events": 3},
            headers={"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["max_events"] == 3

    def test_missing_auth_returns_401(self, test_client):
        resp = test_client.post(
            "/v1/ingest/run",
            json={"area_id": "bucharest", "dry_run": True},
        )
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, test_client):
        resp = test_client.post(
            "/v1/ingest/run",
            json={"area_id": "bucharest", "dry_run": True},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


class TestPreviewEndpoint:
    def test_preview_forces_dry_run(self, test_client, integration_env):
        resp = test_client.post(
            "/v1/ingest/preview",
            json={"area_id": "bucharest", "dry_run": False},
            headers={"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True


class TestAreaWatchCRUD:
    def test_create_watch(self, test_client, integration_env):
        resp = test_client.post(
            "/v1/ingest/watch",
            json={
                "area_id": "integ-test-watch",
                "lat": 44.4268,
                "lng": 26.1025,
                "timezone": "Europe/Bucharest",
                "horizon_days": 7,
                "radius_km": 25.0,
            },
            headers={"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["area_id"] == "integ-test-watch"
        assert body["status"] == "active"

    def test_get_watch(self, test_client, integration_env):
        # Create first
        test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "get-test", "lat": 44.0, "lng": 26.0},
            headers={"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"},
        )
        # Get
        resp = test_client.get(
            "/v1/ingest/watch/get-test",
            headers={"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"},
        )
        assert resp.status_code == 200
        assert resp.json()["area_id"] == "get-test"

    def test_list_watches(self, test_client, integration_env):
        headers = {"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"}
        test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "list-a", "lat": 44.0, "lng": 26.0},
            headers=headers,
        )
        test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "list-b", "lat": 45.0, "lng": 25.0},
            headers=headers,
        )
        resp = test_client.get("/v1/ingest/watch", headers=headers)
        assert resp.status_code == 200
        area_ids = {w["area_id"] for w in resp.json()}
        assert "list-a" in area_ids
        assert "list-b" in area_ids

    def test_update_watch(self, test_client, integration_env):
        headers = {"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"}
        test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "update-test", "lat": 44.0, "lng": 26.0},
            headers=headers,
        )
        resp = test_client.patch(
            "/v1/ingest/watch/update-test",
            json={"status": "paused", "horizon_days": 14},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"
        assert resp.json()["horizon_days"] == 14

    def test_delete_watch(self, test_client, integration_env):
        headers = {"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"}
        test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "delete-test", "lat": 44.0, "lng": 26.0},
            headers=headers,
        )
        resp = test_client.delete(
            "/v1/ingest/watch/delete-test",
            headers=headers,
        )
        assert resp.status_code == 204

        resp = test_client.get(
            "/v1/ingest/watch/delete-test",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_duplicate_watch_returns_409(self, test_client, integration_env):
        headers = {"Authorization": f"Bearer {integration_env['INGEST_API_TOKEN']}"}
        test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "dup-test", "lat": 44.0, "lng": 26.0},
            headers=headers,
        )
        resp = test_client.post(
            "/v1/ingest/watch",
            json={"area_id": "dup-test", "lat": 44.0, "lng": 26.0},
            headers=headers,
        )
        assert resp.status_code == 409
