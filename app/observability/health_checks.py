"""health_checks.py -- post-run ingest health evaluation.

Produces alert dicts that match the alerts table schema:
    id, severity, condition, message, current_value, threshold
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def check_ingest_health(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate a completed ingest run summary and return a list of alerts.

    Each alert dict contains the keys required by the alerts table:
        id, severity, condition, message, current_value, threshold,
        created_at  (provider and area_id are left for the caller to attach).

    Args:
        summary: The dict returned by run_pipeline_from_pages / run_ingest_job.

    Returns:
        A (possibly empty) list of alert dicts.
    """
    alerts: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    inserted: int = summary.get("inserted", 0)
    parsed: int = summary.get("parsed", 0)
    dropped_no_coords: int = summary.get("dropped_no_coords", 0)

    # Alert 1: no events ingested (critical)
    if inserted == 0:
        alerts.append(
            _make_alert(
                severity="critical",
                condition="no_events_inserted",
                message="Ingest run completed with zero events inserted.",
                current_value=float(inserted),
                threshold=1.0,
                created_at=now,
            )
        )

    # Alert 2: single provider only (warning) -- only if field is present
    if "provider_count" in summary:
        provider_count: int = summary["provider_count"]
        if provider_count == 1:
            alerts.append(
                _make_alert(
                    severity="warning",
                    condition="single_provider",
                    message=(
                        "All accepted events came from a single provider. "
                        "Consider adding more source diversity."
                    ),
                    current_value=float(provider_count),
                    threshold=2.0,
                    created_at=now,
                )
            )

    # Alert 3: excessive coord-drop rate (warning)
    if parsed > 0:
        drop_rate = dropped_no_coords / parsed
        if drop_rate > 0.5:
            alerts.append(
                _make_alert(
                    severity="warning",
                    condition="high_coord_drop_rate",
                    message=(
                        f"More than 50% of parsed events were dropped for missing coordinates "
                        f"({dropped_no_coords}/{parsed}, {drop_rate:.1%})."
                    ),
                    current_value=round(drop_rate, 4),
                    threshold=0.5,
                    created_at=now,
                )
            )

    return alerts


def _make_alert(
    *,
    severity: str,
    condition: str,
    message: str,
    current_value: float,
    threshold: float,
    created_at: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "severity": severity,
        "condition": condition,
        "message": message,
        "current_value": current_value,
        "threshold": threshold,
        "created_at": created_at,
    }
