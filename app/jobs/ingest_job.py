from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import get_settings, load_area_configs
from ..domain.models import IngestSummary, RawPage
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

    _write_run_report(
        report_path=settings.ingest_run_report_path,
        report={
            "run_at": datetime.now(timezone.utc).isoformat(),
            "area_id": target_area_id,
            "dry_run": dry_run,
            "max_events": max_events,
            **result,
        },
    )

    logger.info("Ingest job completed", extra={"area_id": target_area_id, "event": "ingest_complete"})
    return result


def _write_run_report(report_path: str, report: dict) -> None:
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

    existing_reports.append(report)
    path.write_text(json.dumps(existing_reports, indent=2), encoding="utf-8")
