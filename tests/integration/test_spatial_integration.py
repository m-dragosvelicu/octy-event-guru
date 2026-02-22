"""Integration tests for PostGIS spatial queries.

Validates find_events_nearby, find_events_in_bbox, count_events_nearby,
count_events_in_bbox, and find_map_pins against a real PostgREST+PostGIS
stack.  Covers the feat/geo-time-query branch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# Bucharest centre
BUCHAREST_LAT = 44.4268
BUCHAREST_LNG = 26.1025

# ~15 km north (Baneasa area)
BANEASA_LAT = 44.5100
BANEASA_LNG = 26.0800

# ~80 km away (Ploiesti)
PLOIESTI_LAT = 44.9500
PLOIESTI_LNG = 26.0300


def _future(days: int = 7) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _insert_event(
    supabase_client,
    *,
    title: str,
    lat: float,
    lng: float,
    start_time: datetime | None = None,
    activity_id: str | None = None,
) -> dict:
    """Insert a test event via PostgREST and return the row."""
    if start_time is None:
        start_time = _future(3)

    payload = {
        "title": title,
        "location_name": f"Test location for {title}",
        "location_lat": lat,
        "location_lng": lng,
        "start_time": start_time.isoformat(),
        "status": "upcoming",
        "external_provider": "test",
        "external_event_id": f"test-{title.lower().replace(' ', '-')}",
    }
    if activity_id:
        payload["activity_id"] = activity_id

    resp = supabase_client.table("events").insert(payload).execute()
    return resp.data[0]


@pytest.fixture()
def _seed_spatial_events(supabase_client, clean_tables):
    """Insert events at known locations for spatial tests."""
    future = _future(3)

    _insert_event(
        supabase_client,
        title="Bucharest Centre Run",
        lat=BUCHAREST_LAT,
        lng=BUCHAREST_LNG,
        start_time=future,
    )
    _insert_event(
        supabase_client,
        title="Baneasa Park Yoga",
        lat=BANEASA_LAT,
        lng=BANEASA_LNG,
        start_time=future + timedelta(hours=2),
    )
    _insert_event(
        supabase_client,
        title="Ploiesti Cycling",
        lat=PLOIESTI_LAT,
        lng=PLOIESTI_LNG,
        start_time=future + timedelta(hours=4),
    )


class TestFindEventsNearby:
    def test_returns_events_within_radius(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)

        resp = supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 20_000,  # 20 km
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
                "p_limit": 50,
                "p_offset": 0,
            },
        ).execute()
        rows = resp.data or []

        titles = {r["title"] for r in rows}
        assert "Bucharest Centre Run" in titles
        assert "Baneasa Park Yoga" in titles
        assert "Ploiesti Cycling" not in titles

    def test_ordered_by_distance(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)

        resp = supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 20_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()
        rows = resp.data or []

        assert len(rows) >= 2
        assert rows[0]["distance_km"] <= rows[1]["distance_km"]

    def test_empty_result_for_tiny_radius(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)

        resp = supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": 0.0,
                "p_lng": 0.0,
                "p_radius_meters": 1,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()
        assert resp.data == [] or resp.data is None


class TestCountEventsNearby:
    def test_count_matches_find(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)

        find_resp = supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 20_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()

        count_resp = supabase_client.rpc(
            "count_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 20_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()

        find_count = len(find_resp.data or [])
        raw_count = count_resp.data
        if isinstance(raw_count, list) and raw_count:
            count_value = int(raw_count[0].get("count", 0))
        elif isinstance(raw_count, int):
            count_value = raw_count
        else:
            count_value = 0

        assert find_count == count_value


class TestFindEventsInBbox:
    def test_bbox_filters_correctly(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)

        # Bbox covering Bucharest + Baneasa but not Ploiesti
        resp = supabase_client.rpc(
            "find_events_in_bbox",
            {
                "p_min_lng": 25.9,
                "p_min_lat": 44.3,
                "p_max_lng": 26.3,
                "p_max_lat": 44.6,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()
        rows = resp.data or []

        titles = {r["title"] for r in rows}
        assert "Bucharest Centre Run" in titles
        assert "Baneasa Park Yoga" in titles
        assert "Ploiesti Cycling" not in titles


class TestCountEventsInBbox:
    def test_bbox_count_matches_find(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)
        bbox_params = {
            "p_min_lng": 25.9,
            "p_min_lat": 44.3,
            "p_max_lng": 26.3,
            "p_max_lat": 44.6,
            "p_start_date": start.isoformat(),
            "p_end_date": end.isoformat(),
        }

        find_resp = supabase_client.rpc(
            "find_events_in_bbox", bbox_params
        ).execute()

        count_resp = supabase_client.rpc(
            "count_events_in_bbox", bbox_params
        ).execute()

        find_count = len(find_resp.data or [])
        raw_count = count_resp.data
        if isinstance(raw_count, list) and raw_count:
            count_value = int(raw_count[0].get("count", 0))
        elif isinstance(raw_count, int):
            count_value = raw_count
        else:
            count_value = 0

        assert find_count == count_value


class TestFindMapPins:
    def test_returns_lightweight_fields(
        self, supabase_client, _seed_spatial_events
    ):
        start = datetime.now(timezone.utc)
        end = _future(14)

        resp = supabase_client.rpc(
            "find_map_pins",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 100_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()
        rows = resp.data or []

        assert len(rows) >= 1
        pin = rows[0]
        assert "id" in pin
        assert "location_lat" in pin
        assert "location_lng" in pin
        assert "title" in pin
        assert "start_time" in pin


class TestTimeWindowFiltering:
    def test_past_events_excluded(self, supabase_client, clean_tables):
        past = datetime.now(timezone.utc) - timedelta(days=30)
        _insert_event(
            supabase_client,
            title="Past Event",
            lat=BUCHAREST_LAT,
            lng=BUCHAREST_LNG,
            start_time=past,
        )

        start = datetime.now(timezone.utc)
        end = _future(14)
        resp = supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 50_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()

        titles = {r["title"] for r in (resp.data or [])}
        assert "Past Event" not in titles


class TestLocationPointTrigger:
    def test_trigger_populates_location_point(self, supabase_client, clean_tables):
        """The INSERT trigger should auto-create location_point from lat/lng."""
        row = _insert_event(
            supabase_client,
            title="Trigger Test",
            lat=BUCHAREST_LAT,
            lng=BUCHAREST_LNG,
        )
        # The trigger ran server-side; verify by querying the spatial function
        start = datetime.now(timezone.utc)
        end = _future(14)
        resp = supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 1000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute()
        titles = {r["title"] for r in (resp.data or [])}
        assert "Trigger Test" in titles
