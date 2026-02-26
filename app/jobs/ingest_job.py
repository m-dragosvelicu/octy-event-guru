from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import get_settings, load_area_configs
from ..domain.models import IngestSummary, RawPage
from ..domain.run_diff import compute_run_diff
from ..observability.health_checks import check_ingest_health
from ..sources.base import SourceFetcher
from ..sources.connectors.brave_search import search_event_urls

logger = logging.getLogger(__name__)


def run_ingest_job(
    *,
    area_id: str | None = None,
    dry_run: bool = False,
    max_events: int | None = None,
) -> dict:
    """Full ingest: Brave Search -> fetch HTML -> extract -> dedupe -> insert.

    Pipeline invariants:
    - No Mapbox geocoding: events without source coordinates are dropped.
    - Coords and provenance gates are enforced at insert time.
    - Deduplication: in-batch fingerprint + DB external_event_id lookup.
    """
    settings = get_settings()
    target_area_id = area_id or settings.default_area_id

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)

    summary = IngestSummary()

    area_configs = load_area_configs()
    area = next((a for a in area_configs if a.area_id == target_area_id), None)
    if area is None:
        logger.error("No area config found", extra={"area_id": target_area_id})
        return summary.model_dump()

    # --- Step 1: Search the web for event pages ---
    urls = search_event_urls(
        api_key=settings.brave_search_api_key,
        queries=area.search_queries,
        timeout_seconds=settings.requests_timeout_seconds,
    )
    if not urls:
        logger.warning("No URLs found from search", extra={"area_id": target_area_id})
        return summary.model_dump()

    # --- Step 2: Crawl each URL ---
    fetcher = SourceFetcher(
        timeout_seconds=settings.requests_timeout_seconds,
        user_agent=settings.requests_user_agent,
    )

    pages: list[RawPage] = []
    for url in urls:
        try:
            page = fetcher.fetch_url(url, area_id=area.area_id)
        except Exception:
            logger.info("Failed to fetch URL", extra={"url": url})
            continue
        if page is not None:
            pages.append(page)

    # --- Steps 3-9: Extract -> Normalize -> Dedupe -> Insert ---
    from .ingest_pipeline import run_pipeline_from_pages

    result = run_pipeline_from_pages(
        pages, area, settings, dry_run=dry_run, max_events=max_events,
    )

    finished_at = datetime.now(timezone.utc)
    run_status = "success" if result.get("inserted", 0) > 0 else "empty"

    current_report: dict = {
        "run_id": run_id,
        "run_at": started_at.isoformat(),
        "area_id": target_area_id,
        "dry_run": dry_run,
        "max_events": max_events,
        **result,
    }

    prev_run = _write_run_report(
        report_path=settings.ingest_run_report_path,
        report=current_report,
    )

    if prev_run is not None:
        diff = compute_run_diff(
            r1_candidates=prev_run.get("candidate_ids") or [],
            r1_inserted=prev_run.get("inserted_ids") or [],
            r2_candidates=result.get("candidate_ids") or [],
            r2_inserted=result.get("inserted_ids") or [],
        )
        diff_dict = diff.model_dump()
        leak_count = len(diff.duplicate_leaks_in_run2)
        new_disc_count = len(diff.new_discovery_in_run2)
        log_extra = {
            "leak_count": leak_count,
            "new_discovery_count": new_disc_count,
            "area_id": target_area_id,
            "event": "run_diff",
        }
        if leak_count > 0:
            logger.warning("Run diff: duplicate leaks detected", extra=log_extra)
        else:
            logger.info("Run diff computed", extra=log_extra)
        _patch_last_run_report(
            report_path=settings.ingest_run_report_path,
            extra={"run_diff": diff_dict},
        )
        current_report["run_diff"] = diff_dict

    # --- Post-run: persist run metadata to DB and evaluate health alerts ---
    if settings.supabase_url and settings.supabase_service_role_key:
        from ..sink.supabase_writer import SupabaseWriter

        writer = SupabaseWriter(settings)

        writer.persist_ingest_run(
            run_id=run_id,
            area_id=target_area_id,
            started_at=started_at,
            finished_at=finished_at,
            status=run_status,
            summary=result,
        )

        alerts = check_ingest_health(result)
        if alerts:
            for alert in alerts:
                alert["area_id"] = target_area_id
            logger.warning(
                "Health check alerts detected",
                extra={"run_id": run_id, "alert_count": len(alerts)},
            )
            for alert in alerts:
                logger.warning(
                    "Alert [%s] %s: %s",
                    alert["severity"],
                    alert["condition"],
                    alert["message"],
                )
            writer.insert_alerts(alerts)
        else:
            logger.info("Health checks passed", extra={"run_id": run_id})

        _write_source_scorecards(writer, target_area_id, result, alerts)
    else:
        # No DB configured -- still evaluate and log alerts locally
        alerts = check_ingest_health(result)
        if alerts:
            for alert in alerts:
                logger.warning(
                    "Alert [%s] %s: %s",
                    alert["severity"],
                    alert["condition"],
                    alert["message"],
                )

    logger.info("Ingest job completed", extra={"area_id": target_area_id, "event": "ingest_complete"})
    return result


def _write_run_report(report_path: str, report: dict) -> dict | None:
    """Append report to the JSON run log. Returns the previous run entry, or None if first run."""
    path = Path(report_path)

    existing_reports: list[dict]
    if path.exists():
        try:
            existing_reports = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing_reports, list):
                existing_reports = []
        except json.JSONDecodeError:
            existing_reports = []
    else:
        existing_reports = []

    prev_run = existing_reports[-1] if existing_reports else None
    existing_reports.append(report)
    path.write_text(json.dumps(existing_reports, indent=2), encoding="utf-8")
    return prev_run


def _write_source_scorecards(
    writer,
    area_id: str,
    result: dict,
    alerts: list[dict],
) -> None:
    """Derive per-provider health status and upsert source_scorecards rows."""
    domain_stats: dict[str, int] = result.get("domain_stats", {})
    if not domain_stats:
        return

    alert_severities = [a["severity"] for a in alerts]
    has_critical = "critical" in alert_severities
    has_warning = "warning" in alert_severities

    total_accepted = result.get("accepted", 0)

    for provider, count in domain_stats.items():
        share_pct = round(count / total_accepted * 100, 2) if total_accepted > 0 else 0.0

        if has_critical:
            health = "critical"
        elif has_warning:
            health = "warning"
        else:
            health = "healthy"

        metrics = {
            "fetched": result.get("fetched", 0),
            "parsed": result.get("parsed", 0),
            "accepted": total_accepted,
            "inserted": result.get("inserted", 0),
            "dropped_no_coords": result.get("dropped_no_coords", 0),
            "provider_event_count": count,
            "provider_share_pct": share_pct,
        }

        writer.upsert_source_scorecard(
            provider=provider,
            area_id=area_id,
            health_status=health,
            metrics=metrics,
        )


def _patch_last_run_report(report_path: str, extra: dict) -> None:
    """Merge extra fields into the last entry of the JSON run log."""
    path = Path(report_path)
    if not path.exists():
        return
    try:
        reports = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(reports, list) or not reports:
            return
    except json.JSONDecodeError:
        return
    reports[-1].update(extra)
    path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
