"""Unit tests for app.observability.health_checks.check_ingest_health."""
from __future__ import annotations

import pytest

from app.observability.health_checks import check_ingest_health


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_summary(**overrides) -> dict:
    """Return a minimal healthy run summary, optionally overriding fields."""
    base = {
        "fetched": 10,
        "parsed": 8,
        "accepted": 5,
        "inserted": 5,
        "skipped_duplicates": 0,
        "dropped_no_coords": 1,
        "with_source_coords": 5,
        "date_only_count": 0,
        "domain_stats": {"source_a": 3, "source_b": 2},
        "provider_count": 2,
        "top_provider_pct": 60.0,
        "candidate_ids": [],
        "inserted_ids": [],
    }
    base.update(overrides)
    return base


def _conditions(alerts: list[dict]) -> list[str]:
    return [a["condition"] for a in alerts]


def _severities(alerts: list[dict]) -> list[str]:
    return [a["severity"] for a in alerts]


# ---------------------------------------------------------------------------
# Healthy run -- zero alerts
# ---------------------------------------------------------------------------

class TestHealthyRun:
    def test_healthy_run_produces_no_alerts(self):
        summary = _base_summary()
        alerts = check_ingest_health(summary)
        assert alerts == []

    def test_healthy_run_multiple_providers(self):
        summary = _base_summary(provider_count=5, inserted=20)
        alerts = check_ingest_health(summary)
        assert alerts == []

    def test_drop_rate_exactly_50_pct_is_not_an_alert(self):
        # 4/8 = 0.5 exactly -- threshold is *strictly greater than* 0.5
        summary = _base_summary(parsed=8, dropped_no_coords=4, inserted=5)
        alerts = check_ingest_health(summary)
        assert "high_coord_drop_rate" not in _conditions(alerts)


# ---------------------------------------------------------------------------
# Alert: no events inserted (critical)
# ---------------------------------------------------------------------------

class TestNoEventsInserted:
    def test_zero_inserted_raises_critical_alert(self):
        summary = _base_summary(inserted=0)
        alerts = check_ingest_health(summary)
        assert "no_events_inserted" in _conditions(alerts)

    def test_no_events_alert_is_critical(self):
        summary = _base_summary(inserted=0)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "no_events_inserted"]
        assert matching[0]["severity"] == "critical"

    def test_no_events_alert_current_value_is_zero(self):
        summary = _base_summary(inserted=0)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "no_events_inserted"]
        assert matching[0]["current_value"] == 0.0

    def test_no_events_alert_threshold_is_one(self):
        summary = _base_summary(inserted=0)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "no_events_inserted"]
        assert matching[0]["threshold"] == 1.0

    def test_one_event_inserted_does_not_trigger_alert(self):
        summary = _base_summary(inserted=1)
        alerts = check_ingest_health(summary)
        assert "no_events_inserted" not in _conditions(alerts)


# ---------------------------------------------------------------------------
# Alert: single provider (warning)
# ---------------------------------------------------------------------------

class TestSingleProvider:
    def test_single_provider_raises_warning(self):
        summary = _base_summary(provider_count=1, domain_stats={"only_source": 5})
        alerts = check_ingest_health(summary)
        assert "single_provider" in _conditions(alerts)

    def test_single_provider_alert_is_warning(self):
        summary = _base_summary(provider_count=1)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "single_provider"]
        assert matching[0]["severity"] == "warning"

    def test_single_provider_current_value_is_one(self):
        summary = _base_summary(provider_count=1)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "single_provider"]
        assert matching[0]["current_value"] == 1.0

    def test_single_provider_threshold_is_two(self):
        summary = _base_summary(provider_count=1)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "single_provider"]
        assert matching[0]["threshold"] == 2.0

    def test_two_providers_does_not_trigger_alert(self):
        summary = _base_summary(provider_count=2)
        alerts = check_ingest_health(summary)
        assert "single_provider" not in _conditions(alerts)

    def test_no_provider_count_field_skips_check(self):
        summary = _base_summary()
        del summary["provider_count"]
        alerts = check_ingest_health(summary)
        assert "single_provider" not in _conditions(alerts)


# ---------------------------------------------------------------------------
# Alert: high coord drop rate (warning)
# ---------------------------------------------------------------------------

class TestHighCoordDropRate:
    def test_drop_rate_above_50_pct_raises_warning(self):
        # 5 dropped / 8 parsed = 62.5%
        summary = _base_summary(parsed=8, dropped_no_coords=5, inserted=3)
        alerts = check_ingest_health(summary)
        assert "high_coord_drop_rate" in _conditions(alerts)

    def test_coord_drop_alert_is_warning(self):
        summary = _base_summary(parsed=8, dropped_no_coords=5)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "high_coord_drop_rate"]
        assert matching[0]["severity"] == "warning"

    def test_coord_drop_alert_current_value_is_rate(self):
        summary = _base_summary(parsed=8, dropped_no_coords=5)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "high_coord_drop_rate"]
        assert abs(matching[0]["current_value"] - round(5 / 8, 4)) < 1e-6

    def test_coord_drop_alert_threshold_is_half(self):
        summary = _base_summary(parsed=8, dropped_no_coords=5)
        alerts = check_ingest_health(summary)
        matching = [a for a in alerts if a["condition"] == "high_coord_drop_rate"]
        assert matching[0]["threshold"] == 0.5

    def test_100_pct_drop_rate_raises_alert(self):
        summary = _base_summary(parsed=10, dropped_no_coords=10, inserted=0)
        alerts = check_ingest_health(summary)
        assert "high_coord_drop_rate" in _conditions(alerts)

    def test_zero_parsed_skips_coord_drop_check(self):
        summary = _base_summary(parsed=0, dropped_no_coords=0)
        alerts = check_ingest_health(summary)
        assert "high_coord_drop_rate" not in _conditions(alerts)

    def test_drop_rate_below_50_pct_is_clean(self):
        # 3/8 = 37.5%
        summary = _base_summary(parsed=8, dropped_no_coords=3, inserted=5)
        alerts = check_ingest_health(summary)
        assert "high_coord_drop_rate" not in _conditions(alerts)


# ---------------------------------------------------------------------------
# Alert schema / shape validation
# ---------------------------------------------------------------------------

class TestAlertSchema:
    REQUIRED_KEYS = {"id", "severity", "condition", "message", "current_value", "threshold", "created_at"}

    def test_alert_has_all_required_keys(self):
        summary = _base_summary(inserted=0)
        alerts = check_ingest_health(summary)
        for alert in alerts:
            missing = self.REQUIRED_KEYS - alert.keys()
            assert not missing, f"Alert is missing keys: {missing}"

    def test_alert_id_is_unique_across_multiple_alerts(self):
        # Trigger all three alerts at once
        summary = _base_summary(inserted=0, provider_count=1, parsed=8, dropped_no_coords=7)
        alerts = check_ingest_health(summary)
        ids = [a["id"] for a in alerts]
        assert len(ids) == len(set(ids)), "Duplicate alert IDs detected"

    def test_multiple_alerts_can_fire_simultaneously(self):
        # zero inserted + single provider + high drop rate
        summary = _base_summary(inserted=0, provider_count=1, parsed=10, dropped_no_coords=9)
        alerts = check_ingest_health(summary)
        conditions = _conditions(alerts)
        assert "no_events_inserted" in conditions
        assert "single_provider" in conditions
        assert "high_coord_drop_rate" in conditions
        assert len(alerts) == 3

    def test_severity_values_are_valid(self):
        summary = _base_summary(inserted=0, provider_count=1, parsed=10, dropped_no_coords=9)
        alerts = check_ingest_health(summary)
        valid_severities = {"critical", "warning", "info"}
        for alert in alerts:
            assert alert["severity"] in valid_severities

    def test_message_is_non_empty_string(self):
        summary = _base_summary(inserted=0)
        alerts = check_ingest_health(summary)
        for alert in alerts:
            assert isinstance(alert["message"], str)
            assert len(alert["message"]) > 0
