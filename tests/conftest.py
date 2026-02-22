"""Root-level test fixtures shared across the entire test suite.

Session-scoped fixtures spin up the integration environment (env vars,
clients, health-check waits).  Function-scoped fixtures handle per-test
cleanup so tests are hermetic.

All integration-only imports are deferred so that unit tests can run
without jwt / redis / requests / psycopg2 installed.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

# ── JWT helper ────────────────────────────────────────────────────────

_JWT_SECRET = "super-secret-jwt-key-for-testing-only-do-not-use-in-prod"


def _generate_test_jwt(role: str = "service_role") -> str:
    """Create an HS256 JWT that PostgREST will accept."""
    import jwt

    payload = {"role": role, "iss": "event-guru-tests"}
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


# ── Session-scoped fixtures ──────────────────────────────────────────


@pytest.fixture(scope="session")
def integration_env() -> dict[str, str]:
    """Set environment variables for the local PostgREST stack.

    Returns the dict of variables that were injected so tests can
    reference them directly if needed.
    """
    test_host_id = str(uuid.uuid4())
    test_api_token = "test-ingest-api-token"
    service_jwt = _generate_test_jwt("service_role")

    env = {
        "SUPABASE_URL": "http://localhost:8089",
        "SUPABASE_SERVICE_ROLE_KEY": service_jwt,
        "EVENT_GURU_HOST_USER_ID": test_host_id,
        "MAPBOX_ACCESS_TOKEN": os.environ.get("MAPBOX_ACCESS_TOKEN", "pk.test-placeholder"),
        "MAPBOX_PERMANENT": "false",
        "INGEST_API_TOKEN": test_api_token,
        "DEFAULT_AREA_ID": "bucharest",
        "REDIS_URL": "redis://localhost:6379/0",
        "CELERY_BROKER_URL": "redis://localhost:6379/0",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    }
    for key, value in env.items():
        os.environ[key] = value

    return env


@pytest.fixture(scope="session")
def wait_for_postgrest(integration_env: dict[str, str]) -> None:
    """Block until the PostgREST proxy responds (max 30 s)."""
    import requests

    url = f"{integration_env['SUPABASE_URL']}/rest/v1/activities"
    headers = {
        "apikey": integration_env["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {integration_env['SUPABASE_SERVICE_ROLE_KEY']}",
    }
    deadline = time.monotonic() + 30
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = requests.get(url, headers=headers, timeout=2)
            if resp.status_code < 500:
                return
        except Exception as exc:
            last_err = exc
        time.sleep(0.5)
    raise RuntimeError(
        f"PostgREST not healthy after 30 s: {last_err}"
    )


@pytest.fixture(scope="session")
def supabase_client(integration_env: dict[str, str], wait_for_postgrest: None):
    """Real supabase-py Client pointing at the local PostgREST proxy."""
    from supabase import create_client

    return create_client(
        integration_env["SUPABASE_URL"],
        integration_env["SUPABASE_SERVICE_ROLE_KEY"],
    )


@pytest.fixture(scope="session")
def redis_client(integration_env: dict[str, str]):
    """Real Redis client connected to the test stack."""
    import redis as redis_lib

    client = redis_lib.Redis.from_url(
        integration_env["REDIS_URL"], decode_responses=True,
    )
    client.ping()
    return client


# ── Function-scoped fixtures ─────────────────────────────────────────


@pytest.fixture(autouse=False)
def clean_tables(supabase_client):
    """Truncate test data before and after each test that opts in."""
    supabase_client.rpc("truncate_test_tables", {}).execute()
    yield
    supabase_client.rpc("truncate_test_tables", {}).execute()


@pytest.fixture()
def test_client(integration_env: dict[str, str]):
    """FastAPI TestClient with a fresh settings cache."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.main import app

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client

    get_settings.cache_clear()
