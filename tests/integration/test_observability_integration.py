"""Integration tests for the observability subsystem.

Validates run reports, dashboard, and alerts against real PostgREST.
Covers the feat/quality-observability branch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


class TestRunReports:
    def test_save_and_list_run_reports(self, supabase_client, clean_tables):
        from app.observability.run_reports import (
            IngestRunReport,
            list_run_reports,
            save_run_report,
        )

        now = datetime.now(timezone.utc)
        report = IngestRunReport(
            area_id="bucharest",
            started_at=now - timedelta(minutes=5),
            finished_at=now,
            duration_seconds=300.0,
            status="success",
            summary={"fetched": 10, "inserted": 5},
        )
        save_run_report(report, supabase_client)

        reports = list_run_reports(supabase_client, area_id="bucharest")
        assert len(reports) >= 1
        found = [r for r in reports if r.run_id == report.run_id]
        assert len(found) == 1
        assert found[0].status == "success"
        assert found[0].summary["inserted"] == 5

    def test_list_reports_empty_area(self, supabase_client, clean_tables):
        from app.observability.run_reports import list_run_reports

        reports = list_run_reports(supabase_client, area_id="nonexistent")
        assert reports == []


class TestDashboard:
    def test_build_dashboard_with_events(self, supabase_client, clean_tables):
        from app.observability.dashboard import build_dashboard

        # Insert some test events
        future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        for i in range(3):
            supabase_client.table("events").insert({
                "title": f"Dashboard Test Event {i}",
                "location_name": "Test Location",
                "location_lat": 44.4268,
                "location_lng": 26.1025,
                "start_time": future,
                "status": "upcoming",
                "external_provider": "test-provider",
                "external_event_id": f"dash-test-{i}",
            }).execute()

        data = build_dashboard(supabase_client)
        assert data.total_events >= 3

    def test_build_dashboard_empty(self, supabase_client, clean_tables):
        from app.observability.dashboard import build_dashboard

        data = build_dashboard(supabase_client)
        assert data.total_events == 0


class TestAlerts:
    def test_evaluate_alerts_fires_on_failures(self):
        from app.observability.alerts import evaluate_all_alerts

        alerts = evaluate_all_alerts(
            recent_statuses=["failure", "failure", "success"],
            area_id="bucharest",
            failure_rate_threshold=0.5,
        )
        triggered_conditions = {a.condition for a in alerts}
        assert "ingest_failure_rate_high" in triggered_conditions

    def test_save_and_list_alerts(self, supabase_client, clean_tables):
        from app.observability.alerts import (
            Alert,
            Severity,
            list_active_alerts,
            save_alert,
        )

        alert = Alert(
            severity=Severity.WARNING,
            condition="test_condition",
            message="Integration test alert",
            current_value=0.9,
            threshold=0.5,
            area_id="bucharest",
        )
        save_alert(alert, supabase_client)

        active = list_active_alerts(supabase_client)
        assert len(active) >= 1
        found = [a for a in active if a.id == alert.id]
        assert len(found) == 1
        assert found[0].condition == "test_condition"
        assert found[0].acknowledged_at is None

    def test_no_active_alerts_when_clean(self, supabase_client, clean_tables):
        from app.observability.alerts import list_active_alerts

        active = list_active_alerts(supabase_client)
        assert active == []
