"""Integration tests for source connectors with real API keys.

Each test is skipped if the required API key is not set.
Covers the feat/source-connectors branch.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

# Bucharest search parameters
BUCHAREST_LAT = 44.4268
BUCHAREST_LNG = 26.1025
RADIUS_KM = 30.0


def _future(days: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _run_async(coro):
    """Convenience wrapper to run an async function from sync test code."""
    return asyncio.get_event_loop().run_until_complete(coro)


# -- Ticketmaster -----------------------------------------------------------

_tm_key = os.environ.get("TICKETMASTER_API_KEY")


@pytest.mark.skipif(not _tm_key, reason="TICKETMASTER_API_KEY not set")
class TestTicketmasterConnector:
    def _make_connector(self):
        from app.sources.connectors.ticketmaster import TicketmasterConnector
        return TicketmasterConnector(api_key=_tm_key, area_id="bucharest")

    def test_health_check(self):
        connector = self._make_connector()
        assert _run_async(connector.health_check()) is True

    def test_fetch_events_near_bucharest(self):
        connector = self._make_connector()
        events = _run_async(
            connector.fetch_events(
                lat=BUCHAREST_LAT,
                lng=BUCHAREST_LNG,
                radius_km=RADIUS_KM,
                start_date=_future(0),
                end_date=_future(30),
                max_events=5,
            )
        )
        # We may not always get events, but the call should succeed
        assert isinstance(events, list)


# -- PredictHQ -------------------------------------------------------------

_phq_key = os.environ.get("PREDICTHQ_API_KEY")


@pytest.mark.skipif(not _phq_key, reason="PREDICTHQ_API_KEY not set")
class TestPredictHQConnector:
    def _make_connector(self):
        from app.sources.connectors.predicthq import PredictHQConnector
        return PredictHQConnector(api_key=_phq_key, area_id="bucharest")

    def test_health_check(self):
        connector = self._make_connector()
        assert _run_async(connector.health_check()) is True

    def test_fetch_events_near_bucharest(self):
        connector = self._make_connector()
        events = _run_async(
            connector.fetch_events(
                lat=BUCHAREST_LAT,
                lng=BUCHAREST_LNG,
                radius_km=RADIUS_KM,
                start_date=_future(0),
                end_date=_future(30),
                max_events=5,
            )
        )
        assert isinstance(events, list)


# -- Meetup -----------------------------------------------------------------

_meetup_key = os.environ.get("MEETUP_API_KEY")


@pytest.mark.skipif(not _meetup_key, reason="MEETUP_API_KEY not set")
class TestMeetupConnector:
    def _make_connector(self):
        from app.sources.connectors.meetup import MeetupConnector
        return MeetupConnector(api_key=_meetup_key, area_id="bucharest")

    def test_health_check(self):
        connector = self._make_connector()
        assert _run_async(connector.health_check()) is True

    def test_fetch_events_near_bucharest(self):
        connector = self._make_connector()
        events = _run_async(
            connector.fetch_events(
                lat=BUCHAREST_LAT,
                lng=BUCHAREST_LNG,
                radius_km=RADIUS_KM,
                start_date=_future(0),
                end_date=_future(30),
                max_events=5,
            )
        )
        assert isinstance(events, list)
