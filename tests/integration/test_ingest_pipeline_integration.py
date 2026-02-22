"""Real integration tests for ingest API endpoints."""
from __future__ import annotations

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
