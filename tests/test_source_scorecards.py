"""Unit tests for source_scorecards population logic."""
from __future__ import annotations

from unittest.mock import MagicMock, call

from app.jobs.ingest_job import _write_source_scorecards


def _base_result(**overrides) -> dict:
    base = {
        "fetched": 10,
        "parsed": 8,
        "accepted": 6,
        "inserted": 5,
        "skipped_duplicates": 1,
        "dropped_no_coords": 2,
        "with_source_coords": 6,
        "date_only_count": 0,
        "domain_stats": {"source_a": 4, "source_b": 2},
        "provider_count": 2,
        "top_provider_pct": 66.67,
        "candidate_ids": [],
        "inserted_ids": [],
    }
    base.update(overrides)
    return base


class TestWriteSourceScorecards:
    def test_upserts_one_row_per_provider(self):
        writer = MagicMock()
        result = _base_result()
        _write_source_scorecards(writer, "bucharest", result, [])

        assert writer.upsert_source_scorecard.call_count == 2
        providers = {c.kwargs["provider"] for c in writer.upsert_source_scorecard.call_args_list}
        assert providers == {"source_a", "source_b"}

    def test_all_providers_get_correct_area_id(self):
        writer = MagicMock()
        result = _base_result()
        _write_source_scorecards(writer, "bucharest", result, [])

        for c in writer.upsert_source_scorecard.call_args_list:
            assert c.kwargs["area_id"] == "bucharest"

    def test_healthy_status_when_no_alerts(self):
        writer = MagicMock()
        result = _base_result()
        _write_source_scorecards(writer, "bucharest", result, [])

        for c in writer.upsert_source_scorecard.call_args_list:
            assert c.kwargs["health_status"] == "healthy"

    def test_warning_status_when_warning_alert_present(self):
        writer = MagicMock()
        result = _base_result()
        alerts = [{"severity": "warning", "condition": "single_provider"}]
        _write_source_scorecards(writer, "bucharest", result, alerts)

        for c in writer.upsert_source_scorecard.call_args_list:
            assert c.kwargs["health_status"] == "warning"

    def test_critical_status_when_critical_alert_present(self):
        writer = MagicMock()
        result = _base_result()
        alerts = [{"severity": "critical", "condition": "no_events_inserted"}]
        _write_source_scorecards(writer, "bucharest", result, alerts)

        for c in writer.upsert_source_scorecard.call_args_list:
            assert c.kwargs["health_status"] == "critical"

    def test_critical_overrides_warning(self):
        writer = MagicMock()
        result = _base_result()
        alerts = [
            {"severity": "warning", "condition": "single_provider"},
            {"severity": "critical", "condition": "no_events_inserted"},
        ]
        _write_source_scorecards(writer, "bucharest", result, alerts)

        for c in writer.upsert_source_scorecard.call_args_list:
            assert c.kwargs["health_status"] == "critical"

    def test_metrics_contain_required_fields(self):
        writer = MagicMock()
        result = _base_result()
        _write_source_scorecards(writer, "bucharest", result, [])

        required_keys = {
            "fetched", "parsed", "accepted", "inserted",
            "dropped_no_coords", "provider_event_count", "provider_share_pct",
        }
        for c in writer.upsert_source_scorecard.call_args_list:
            metrics = c.kwargs["metrics"]
            missing = required_keys - metrics.keys()
            assert not missing, f"Missing metrics keys: {missing}"

    def test_provider_share_pct_is_correct(self):
        writer = MagicMock()
        result = _base_result(domain_stats={"source_a": 4, "source_b": 2}, accepted=6)
        _write_source_scorecards(writer, "bucharest", result, [])

        calls_by_provider = {
            c.kwargs["provider"]: c.kwargs["metrics"]
            for c in writer.upsert_source_scorecard.call_args_list
        }
        assert abs(calls_by_provider["source_a"]["provider_share_pct"] - 66.67) < 0.01
        assert abs(calls_by_provider["source_b"]["provider_share_pct"] - 33.33) < 0.01

    def test_no_domain_stats_skips_scorecards(self):
        writer = MagicMock()
        result = _base_result(domain_stats={})
        _write_source_scorecards(writer, "bucharest", result, [])

        writer.upsert_source_scorecard.assert_not_called()

    def test_single_provider_still_writes_scorecard(self):
        writer = MagicMock()
        result = _base_result(domain_stats={"only_source": 5}, accepted=5)
        _write_source_scorecards(writer, "bucharest", result, [])

        assert writer.upsert_source_scorecard.call_count == 1
        c = writer.upsert_source_scorecard.call_args
        assert c.kwargs["provider"] == "only_source"
        assert c.kwargs["metrics"]["provider_share_pct"] == 100.0
