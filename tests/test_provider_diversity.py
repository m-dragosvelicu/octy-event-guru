"""Unit tests for provider diversity metrics in IngestSummary.

Uses fake RawPage objects with inline JSON-LD HTML so no network
calls, no Supabase, and no Mapbox geocoding are required.
"""
from __future__ import annotations

import logging
import os

import pytest

from app.domain.models import AreaConfig, RawPage


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_area(**kwargs) -> AreaConfig:
    defaults = dict(
        area_id="test-area",
        lat=44.4268,
        lng=26.1025,
        radius_km=50,
        timezone="UTC",
        horizon_days=365,
        per_domain_cap=None,
    )
    defaults.update(kwargs)
    return AreaConfig(**defaults)


def _make_settings():
    """Return a Settings instance with dummy credentials (no Supabase, no Brave)."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    os.environ.setdefault("BRAVE_SEARCH_API_KEY", "test-key-placeholder")
    # Clear Supabase so the pipeline skips the DB branch.
    os.environ["SUPABASE_URL"] = ""
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
    settings = get_settings()
    get_settings.cache_clear()
    return settings


def _event_html(events: list[dict]) -> str:
    """Build a minimal HTML page embedding events as JSON-LD."""
    import json

    items = []
    for ev in events:
        items.append(
            {
                "@context": "https://schema.org",
                "@type": "Event",
                "name": ev["name"],
                "startDate": ev.get("startDate", "2026-09-15T19:00:00+00:00"),
                "location": {
                    "@type": "Place",
                    "name": ev.get("location_name", "Test Venue"),
                    "address": ev.get("address", "Test City"),
                    "geo": {
                        "@type": "GeoCoordinates",
                        "latitude": ev.get("lat", 44.4268),
                        "longitude": ev.get("lng", 26.1025),
                    },
                },
                "url": ev.get("url", f"https://example.com/{ev['name'].lower().replace(' ', '-')}"),
            }
        )

    payload = json.dumps(items)
    return f"""\
<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<script type="application/ld+json">{payload}</script>
</body>
</html>
"""


def _make_page(provider: str, events: list[dict]) -> RawPage:
    return RawPage(
        area_id="test-area",
        provider=provider,
        sport_hint=None,
        url=f"https://{provider}/events",
        html=_event_html(events),
    )


# ---------------------------------------------------------------------------
# Test 1: three providers -- verify provider_count and top_provider_pct
# ---------------------------------------------------------------------------

def test_provider_diversity_three_providers() -> None:
    """With events from 3 providers the metrics must reflect the distribution."""
    settings = _make_settings()
    area = _make_area()

    # provider-a: 4 events, provider-b: 3 events, provider-c: 3 events -> total 10
    pages = [
        _make_page(
            "provider-a.com",
            [
                {"name": "Event A1", "url": "https://provider-a.com/a1"},
                {"name": "Event A2", "url": "https://provider-a.com/a2"},
                {"name": "Event A3", "url": "https://provider-a.com/a3"},
                {"name": "Event A4", "url": "https://provider-a.com/a4"},
            ],
        ),
        _make_page(
            "provider-b.com",
            [
                {"name": "Event B1", "url": "https://provider-b.com/b1"},
                {"name": "Event B2", "url": "https://provider-b.com/b2"},
                {"name": "Event B3", "url": "https://provider-b.com/b3"},
            ],
        ),
        _make_page(
            "provider-c.com",
            [
                {"name": "Event C1", "url": "https://provider-c.com/c1"},
                {"name": "Event C2", "url": "https://provider-c.com/c2"},
                {"name": "Event C3", "url": "https://provider-c.com/c3"},
            ],
        ),
    ]

    from app.jobs.ingest_pipeline import run_pipeline_from_pages

    result = run_pipeline_from_pages(pages, area, settings, dry_run=True)

    assert result["provider_count"] == 3, (
        f"Expected 3 distinct providers, got {result['provider_count']}"
    )

    # top provider is provider-a.com with 4/10 = 40%
    assert result["accepted"] == 10
    expected_pct = round(4 / 10 * 100, 2)
    assert result["top_provider_pct"] == pytest.approx(expected_pct, abs=0.1), (
        f"Expected top_provider_pct ~{expected_pct}, got {result['top_provider_pct']}"
    )
    # Sanity: 40% is below the default 80% threshold so no warning needed
    assert result["top_provider_pct"] < 80.0


# ---------------------------------------------------------------------------
# Test 2: single provider -- verify warning is logged
# ---------------------------------------------------------------------------

def test_provider_diversity_single_provider_logs_warning(caplog) -> None:
    """When only one provider supplies events a WARNING must be logged."""
    settings = _make_settings()
    # Use the default warn threshold (80%). One provider = 100% -> triggers warning.
    area = _make_area(provider_diversity_warn_pct=80)

    pages = [
        _make_page(
            "monopoly-source.com",
            [
                {"name": "Solo Event 1", "url": "https://monopoly-source.com/e1"},
                {"name": "Solo Event 2", "url": "https://monopoly-source.com/e2"},
                {"name": "Solo Event 3", "url": "https://monopoly-source.com/e3"},
            ],
        ),
    ]

    from app.jobs.ingest_pipeline import run_pipeline_from_pages

    with caplog.at_level(logging.WARNING, logger="app.jobs.ingest_pipeline"):
        result = run_pipeline_from_pages(pages, area, settings, dry_run=True)

    assert result["provider_count"] == 1, (
        f"Expected 1 provider, got {result['provider_count']}"
    )
    assert result["top_provider_pct"] == pytest.approx(100.0, abs=0.01), (
        f"Expected 100% top provider, got {result['top_provider_pct']}"
    )

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("monopoly-source.com" in msg for msg in warning_messages), (
        f"Expected a diversity warning mentioning 'monopoly-source.com', "
        f"got warnings: {warning_messages}"
    )
    assert any("diversity" in msg.lower() for msg in warning_messages), (
        f"Expected warning to mention diversity, got: {warning_messages}"
    )


# ---------------------------------------------------------------------------
# Test 3: single provider below a custom threshold -- no warning
# ---------------------------------------------------------------------------

def test_provider_diversity_no_warning_when_below_threshold(caplog) -> None:
    """When top_provider_pct is below the configured threshold no WARNING is emitted."""
    settings = _make_settings()
    # Raise the threshold high enough that 100% still does not warn
    area = _make_area(provider_diversity_warn_pct=100)

    pages = [
        _make_page(
            "sole-source.com",
            [
                {"name": "Event X1", "url": "https://sole-source.com/x1"},
                {"name": "Event X2", "url": "https://sole-source.com/x2"},
            ],
        ),
    ]

    from app.jobs.ingest_pipeline import run_pipeline_from_pages

    with caplog.at_level(logging.WARNING, logger="app.jobs.ingest_pipeline"):
        result = run_pipeline_from_pages(pages, area, settings, dry_run=True)

    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("diversity" in msg.lower() for msg in warning_messages), (
        f"No diversity warning expected at threshold=100%, got: {warning_messages}"
    )
    assert result["provider_count"] == 1
    assert result["top_provider_pct"] == pytest.approx(100.0, abs=0.01)
