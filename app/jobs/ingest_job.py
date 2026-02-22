from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import get_settings, load_area_configs
from ..domain.models import IngestSummary, NormalizedEvent, RawPage
from ..extract.html_fallback import parse_html_events
from ..extract.jsonld import parse_jsonld_events
from ..extract.normalize import normalize_events
from ..sink.dedupe import attach_external_event_ids, dedupe_in_batch
from ..sources.base import SourceFetcher
from ..sources.connectors.brave_search import search_event_urls

logger = logging.getLogger(__name__)


def run_ingest_job(
    *,
    area_id: str | None = None,
    dry_run: bool = False,
    max_events: int | None = None,
) -> dict[str, int]:
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

    summary.fetched = len(pages)
    logger.info("Crawl phase complete", extra={"pages_fetched": len(pages), "urls_tried": len(urls)})

    # --- Step 3: Extract events from pages (JSON-LD first, HTML fallback) ---
    from ..sources.adapters import get_selectors

    extracted_events = []
    for page in pages:
        jsonld_events = parse_jsonld_events(page)
        if jsonld_events:
            parsed = jsonld_events
        else:
            selectors = get_selectors(page.provider)
            parsed = parse_html_events(page, selectors)

        summary.parsed += len(parsed)
        extracted_events.extend(parsed)

    logger.info("Extract phase complete", extra={"events_extracted": len(extracted_events)})

    # --- Step 4: Normalize ---
    normalized = normalize_events(extracted_events, timezone_name=area.timezone)

    for ev in normalized:
        if ev.location_lat is not None and ev.location_lng is not None:
            summary.with_source_coords += 1

    # Accept all events (with or without coords for now)
    summary.accepted = len(normalized)

    # --- Step 5: Dedupe ---
    attach_external_event_ids(normalized)
    unique_events, batch_duplicates = dedupe_in_batch(normalized)
    summary.skipped_duplicates += batch_duplicates

    # --- Step 6: DB dedupe + insert (only if Supabase is configured) ---
    if settings.supabase_url and settings.supabase_service_role_key:
        from ..sink.supabase_writer import SupabaseWriter

        writer = SupabaseWriter(settings)

        db_unique_events: list[NormalizedEvent] = []
        grouped_ids: dict[str, list[str]] = {}
        for event in unique_events:
            if not event.external_event_id:
                continue
            grouped_ids.setdefault(event.provider, []).append(event.external_event_id)

        existing_ids_by_provider: dict[str, set[str]] = {}
        if not dry_run:
            for provider, external_ids in grouped_ids.items():
                existing_ids_by_provider[provider] = writer.get_existing_external_event_ids(provider, external_ids)

        for event in unique_events:
            event_id = event.external_event_id
            if not event_id:
                continue
            existing = existing_ids_by_provider.get(event.provider, set())
            if event_id in existing:
                summary.skipped_duplicates += 1
                continue
            db_unique_events.append(event)

        if max_events is not None:
            db_unique_events = db_unique_events[:max_events]

        summary.inserted = writer.insert_events(db_unique_events, dry_run=dry_run)
    else:
        logger.info("Supabase not configured, skipping DB write")
        if max_events is not None:
            unique_events = unique_events[:max_events]
        summary.inserted = len(unique_events) if dry_run else 0

    _write_run_report(
        report_path=settings.ingest_run_report_path,
        report={
            "run_at": datetime.now(timezone.utc).isoformat(),
            "area_id": target_area_id,
            "dry_run": dry_run,
            "max_events": max_events,
            **summary.model_dump(),
        },
    )

    logger.info("Ingest job completed", extra={"area_id": target_area_id, "event": "ingest_complete"})
    return summary.model_dump()


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
