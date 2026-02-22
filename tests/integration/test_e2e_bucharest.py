"""End-to-end smoke test: ingest real events for Bucharest and spatial-query them.

Requires:
  - Full test stack running (PostgREST + PostGIS + Redis)
  - MAPBOX_ACCESS_TOKEN env var with a valid Mapbox token
  - At least one of: TICKETMASTER_API_KEY, PREDICTHQ_API_KEY, MEETUP_API_KEY

Marked with ``e2e`` so it only runs on nightly / manual dispatch.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.e2e

BUCHAREST_LAT = 44.4268
BUCHAREST_LNG = 26.1025


def _has_real_mapbox_token() -> bool:
    token = os.environ.get("MAPBOX_ACCESS_TOKEN", "")
    return token.startswith("pk.") and "placeholder" not in token


def _has_any_api_key() -> bool:
    return any(
        os.environ.get(k)
        for k in ("TICKETMASTER_API_KEY", "PREDICTHQ_API_KEY", "MEETUP_API_KEY")
    )


@pytest.mark.skipif(
    not _has_real_mapbox_token(),
    reason="MAPBOX_ACCESS_TOKEN is missing or is a placeholder",
)
class TestE2EBucharestSmoke:
    """Ordered test class: ingest then query.

    Tests rely on class-level state so they must run in definition order.
    """

    _inserted_count: int = 0

    def test_01_trigger_ingest(self, supabase_client, clean_tables, integration_env):
        """Run the ingest pipeline for Bucharest with capped events."""
        from app.jobs.ingest_job import run_ingest_job

        summary = run_ingest_job(
            area_id="bucharest",
            dry_run=False,
            max_events=10,
        )
        TestE2EBucharestSmoke._inserted_count = summary.get("inserted", 0)
        # Ingest may return 0 if no sources are enabled for bucharest
        # on the main branch; the test still validates that the pipeline
        # runs end-to-end without error.
        assert isinstance(summary, dict)
        assert "inserted" in summary

    def test_02_events_exist_in_database(self, supabase_client):
        """If ingest inserted events, they should be queryable."""
        if TestE2EBucharestSmoke._inserted_count == 0:
            pytest.skip("No events were inserted by the ingest pipeline")

        resp = (
            supabase_client.table("events")
            .select("id,title,location_lat,location_lng,external_source_url,external_provider")
            .limit(50)
            .execute()
        )
        rows = resp.data or []
        assert len(rows) > 0

    def test_03_events_have_coordinates(self, supabase_client):
        """Every inserted event must have lat/lng populated."""
        if TestE2EBucharestSmoke._inserted_count == 0:
            pytest.skip("No events were inserted by the ingest pipeline")

        resp = (
            supabase_client.table("events")
            .select("id,location_lat,location_lng")
            .limit(50)
            .execute()
        )
        for row in resp.data or []:
            assert row["location_lat"] is not None, f"Event {row['id']} missing lat"
            assert row["location_lng"] is not None, f"Event {row['id']} missing lng"

    def test_04_events_have_source_metadata(self, supabase_client):
        """Every inserted event must have provider and source URL."""
        if TestE2EBucharestSmoke._inserted_count == 0:
            pytest.skip("No events were inserted by the ingest pipeline")

        resp = (
            supabase_client.table("events")
            .select("id,external_provider,external_source_url")
            .limit(50)
            .execute()
        )
        for row in resp.data or []:
            assert row["external_provider"] is not None, f"Event {row['id']} missing provider"
            assert row["external_source_url"] is not None, f"Event {row['id']} missing source URL"

    def test_05_spatial_query_finds_inserted_events(self, supabase_client):
        """find_map_pins should return the ingested events near Bucharest."""
        if TestE2EBucharestSmoke._inserted_count == 0:
            pytest.skip("No events were inserted by the ingest pipeline")

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=60)

        resp = supabase_client.rpc(
            "find_map_pins",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 50_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
                "p_limit": 200,
            },
        ).execute()
        pins = resp.data or []
        assert len(pins) > 0, "Spatial query returned no pins after ingest"
