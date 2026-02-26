"""Deterministic dedupe integration test using snapshot HTML with JSON-LD.

Runs the pipeline twice on the exact same input and asserts run2 inserts 0.
Requires the docker-compose PostgREST stack.
"""
from __future__ import annotations

import pytest

from app.domain.models import AreaConfig, RawPage
from app.domain.run_diff import compute_run_diff

pytestmark = pytest.mark.integration

SNAPSHOT_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Test Events Page</title></head>
<body>
<script type="application/ld+json">
[
  {
    "@context": "https://schema.org",
    "@type": "Event",
    "name": "Bucharest Night Run 2026",
    "startDate": "2026-09-15T19:00:00+03:00",
    "endDate": "2026-09-15T22:00:00+03:00",
    "location": {
      "@type": "Place",
      "name": "Herastrau Park",
      "address": "Bucharest, Romania",
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": 44.4730,
        "longitude": 26.0780
      }
    },
    "description": "Annual night running event in Bucharest.",
    "url": "https://example.com/bucharest-night-run"
  },
  {
    "@context": "https://schema.org",
    "@type": "Event",
    "name": "Bucharest Jazz Festival",
    "startDate": "2026-09-20T18:00:00+03:00",
    "location": {
      "@type": "Place",
      "name": "Sala Palatului",
      "address": "Str. Ion Campineanu 28, Bucharest",
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": 44.4395,
        "longitude": 26.0966
      }
    },
    "description": "International jazz festival.",
    "url": "https://example.com/bucharest-jazz"
  }
]
</script>
</body>
</html>
"""

SNAPSHOT_PAGES = [
    RawPage(
        area_id="bucharest",
        provider="example.com",
        sport_hint=None,
        url="https://example.com/events",
        html=SNAPSHOT_HTML,
    ),
]

TEST_AREA = AreaConfig(
    area_id="bucharest",
    lat=44.4268,
    lng=26.1025,
    radius_km=50,
    timezone="Europe/Bucharest",
    horizon_days=90,
)


def test_dedupe_deterministic_two_runs(integration_env, wait_for_postgrest, clean_tables):
    """Run pipeline twice on identical input; run2 must insert 0."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    from app.jobs.ingest_pipeline import run_pipeline_from_pages

    r1 = run_pipeline_from_pages(SNAPSHOT_PAGES, TEST_AREA, settings, dry_run=False)
    assert r1["inserted"] > 0, f"Run1 should insert events, got {r1}"

    r2 = run_pipeline_from_pages(SNAPSHOT_PAGES, TEST_AREA, settings, dry_run=False)

    diff = compute_run_diff(
        r1_candidates=r1["candidate_ids"],
        r1_inserted=r1["inserted_ids"],
        r2_candidates=r2["candidate_ids"],
        r2_inserted=r2["inserted_ids"],
    )

    assert diff.duplicate_leaks_in_run2 == [], (
        f"Dedupe leak detected: {diff.duplicate_leaks_in_run2}"
    )
    assert r2["inserted"] == 0, (
        f"Run2 inserted {r2['inserted']} events on identical input; "
        f"diff: leaks={diff.duplicate_leaks_in_run2}, "
        f"new_discovery={diff.new_discovery_in_run2}"
    )
