"""Lean real integration tests for PostGIS RPC functions."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

BUCHAREST_LAT = 44.4268
BUCHAREST_LNG = 26.1025
BANEASA_LAT = 44.5100
BANEASA_LNG = 26.0800
PLOIESTI_LAT = 44.9500
PLOIESTI_LNG = 26.0300


def _future(days: int = 7) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _insert_event(supabase_client, *, title: str, lat: float, lng: float) -> None:
    payload = {
        "title": title,
        "location_name": f"Location for {title}",
        "location_lat": lat,
        "location_lng": lng,
        "start_time": _future(3).isoformat(),
        "status": "upcoming",
        "external_provider": "test",
        "external_event_id": f"test-{title.lower().replace(' ', '-')}",
    }
    supabase_client.table("events").insert(payload).execute()


@pytest.fixture()
def _seed_spatial_events(supabase_client, clean_tables):
    _insert_event(supabase_client, title="Bucharest Centre Run", lat=BUCHAREST_LAT, lng=BUCHAREST_LNG)
    _insert_event(supabase_client, title="Baneasa Park Yoga", lat=BANEASA_LAT, lng=BANEASA_LNG)
    _insert_event(supabase_client, title="Ploiesti Cycling", lat=PLOIESTI_LAT, lng=PLOIESTI_LNG)


def test_find_events_nearby_filters_and_orders(supabase_client, _seed_spatial_events):
    start = datetime.now(timezone.utc)
    end = _future(14)
    rows = (
        supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 20_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
                "p_limit": 50,
                "p_offset": 0,
            },
        ).execute().data
        or []
    )

    titles = {r["title"] for r in rows}
    assert "Bucharest Centre Run" in titles
    assert "Baneasa Park Yoga" in titles
    assert "Ploiesti Cycling" not in titles
    assert len(rows) >= 2
    assert rows[0]["distance_km"] <= rows[1]["distance_km"]


def test_find_events_in_bbox_filters(supabase_client, _seed_spatial_events):
    start = datetime.now(timezone.utc)
    end = _future(14)
    rows = (
        supabase_client.rpc(
            "find_events_in_bbox",
            {
                "p_min_lng": 25.9,
                "p_min_lat": 44.3,
                "p_max_lng": 26.3,
                "p_max_lat": 44.6,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute().data
        or []
    )
    titles = {r["title"] for r in rows}
    assert "Bucharest Centre Run" in titles
    assert "Baneasa Park Yoga" in titles
    assert "Ploiesti Cycling" not in titles


def test_find_map_pins_returns_expected_fields(supabase_client, _seed_spatial_events):
    start = datetime.now(timezone.utc)
    end = _future(14)
    rows = (
        supabase_client.rpc(
            "find_map_pins",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 100_000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
                "p_limit": 200,
            },
        ).execute().data
        or []
    )
    assert len(rows) >= 1
    pin = rows[0]
    assert {"id", "location_lat", "location_lng", "title", "start_time"}.issubset(pin.keys())


def test_location_point_trigger_applies_on_insert(supabase_client, clean_tables):
    _insert_event(supabase_client, title="Trigger Test", lat=BUCHAREST_LAT, lng=BUCHAREST_LNG)
    start = datetime.now(timezone.utc)
    end = _future(14)
    rows = (
        supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 1000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute().data
        or []
    )
    titles = {r["title"] for r in rows}
    assert "Trigger Test" in titles


def test_date_only_round_trips_through_db(supabase_client, clean_tables):
    """Insert an event with date_only=True, query via RPC, assert it comes back."""
    payload = {
        "title": "All-Day Festival",
        "location_name": "Parcul Tineretului",
        "location_lat": BUCHAREST_LAT,
        "location_lng": BUCHAREST_LNG,
        "start_time": _future(5).isoformat(),
        "status": "upcoming",
        "external_provider": "test",
        "external_event_id": "test-date-only-roundtrip",
        "date_only": True,
    }
    supabase_client.table("events").insert(payload).execute()

    start = datetime.now(timezone.utc)
    end = _future(14)
    rows = (
        supabase_client.rpc(
            "find_events_nearby",
            {
                "p_lat": BUCHAREST_LAT,
                "p_lng": BUCHAREST_LNG,
                "p_radius_meters": 1000,
                "p_start_date": start.isoformat(),
                "p_end_date": end.isoformat(),
            },
        ).execute().data
        or []
    )

    matched = [r for r in rows if r["title"] == "All-Day Festival"]
    assert len(matched) == 1
    assert matched[0]["date_only"] is True


def test_date_only_present_in_api_response(supabase_client, clean_tables, test_client):
    """date_only=True inserted via DB must surface in the /v1/events/nearby JSON response."""
    payload = {
        "title": "All-Day API Festival",
        "location_name": "Parcul Tineretului",
        "location_lat": BUCHAREST_LAT,
        "location_lng": BUCHAREST_LNG,
        "start_time": _future(5).isoformat(),
        "status": "upcoming",
        "external_provider": "test",
        "external_event_id": "test-date-only-api",
        "date_only": True,
    }
    supabase_client.table("events").insert(payload).execute()

    response = test_client.get(
        "/v1/events/nearby",
        params={
            "lat": BUCHAREST_LAT,
            "lng": BUCHAREST_LNG,
            "radius_km": 1,
            "days": 14,
            "limit": 50,
        },
    )
    assert response.status_code == 200

    body = response.json()
    matched = [e for e in body["events"] if e["title"] == "All-Day API Festival"]
    assert len(matched) == 1, f"Expected 1 matching event, got {len(matched)}: {body['events']}"
    assert matched[0]["date_only"] is True, (
        f"Expected date_only=True in API response, got: {matched[0]}"
    )
