"""Live freshness test: full ingest with real Brave Search.

Runs run_ingest_job() twice and uses compute_run_diff() to verify
that dedupe holds -- any run2 inserts must be new discoveries, not leaks.

Skips if BRAVE_SEARCH_API_KEY is not set.
"""
from __future__ import annotations

import os

import pytest

from app.domain.run_diff import compute_run_diff

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("BRAVE_SEARCH_API_KEY"),
        reason="BRAVE_SEARCH_API_KEY not set",
    ),
]


def test_live_freshness_no_dedupe_leaks(integration_env, wait_for_postgrest, clean_tables):
    """Two live ingest runs must produce zero duplicate leaks."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.jobs.ingest_job import run_ingest_job

    r1 = run_ingest_job(dry_run=False)
    assert r1["inserted"] > 0, f"Run1 inserted 0 events: {r1}"

    r2 = run_ingest_job(dry_run=False)

    diff = compute_run_diff(
        r1_candidates=r1.get("candidate_ids", []),
        r1_inserted=r1.get("inserted_ids", []),
        r2_candidates=r2.get("candidate_ids", []),
        r2_inserted=r2.get("inserted_ids", []),
    )

    assert diff.duplicate_leaks_in_run2 == [], (
        f"Dedupe leak: {diff.duplicate_leaks_in_run2}"
    )

    if diff.run2_inserted_count > 0:
        assert len(diff.new_discovery_in_run2) == diff.run2_inserted_count, (
            f"run2 inserted {diff.run2_inserted_count} events but only "
            f"{len(diff.new_discovery_in_run2)} are new discoveries; "
            f"leaks={diff.duplicate_leaks_in_run2}"
        )
