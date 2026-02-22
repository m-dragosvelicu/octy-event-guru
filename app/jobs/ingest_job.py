from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import get_settings, load_area_configs
from ..domain.models import AreaConfig, IngestSummary, NormalizedEvent
from ..extract.html_fallback import parse_html_events
from ..extract.jsonld import parse_jsonld_events
from ..extract.normalize import normalize_events
from ..geocode.mapbox_client import MapboxClient
from ..geocode.scoring import passes_precision_gate, score_geocode
from ..sink.dedupe import attach_external_event_ids, dedupe_in_batch
from ..sink.supabase_writer import SupabaseWriter
from ..sources.adapters import get_selectors
from ..sources.base import SourceFetcher, load_source_registry
from ..sources.connectors.ticketmaster import fetch_ticketmaster_events

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

    writer = SupabaseWriter(settings)
    mapbox = MapboxClient(
        settings.mapbox_access_token,
        permanent=settings.mapbox_permanent,
        timeout_seconds=settings.requests_timeout_seconds,
    )

    all_normalized: list[NormalizedEvent] = []

    # --- API connector path: Ticketmaster ---
    if area and "ticketmaster" in area.providers:
        if not settings.ticketmaster_api_key:
            logger.error("TICKETMASTER_API_KEY required but not set")
        else:
            tm_events = fetch_ticketmaster_events(
                api_key=settings.ticketmaster_api_key,
                area=area,
                timeout_seconds=settings.requests_timeout_seconds,
            )
            summary.fetched += len(tm_events)
            summary.parsed += len(tm_events)

            for ev in tm_events:
                if ev.location_lat is not None and ev.location_lng is not None:
                    summary.with_source_coords += 1

            all_normalized.extend(tm_events)

    # --- HTML scraping path (existing registry-based sources) ---
    all_sources = load_source_registry()
    sources = [s for s in all_sources if s.enabled and s.area_id == target_area_id]

    if sources:
        fetcher = SourceFetcher(
            timeout_seconds=settings.requests_timeout_seconds,
            user_agent=settings.requests_user_agent,
        )
        extracted_events = []
        for source in sources:
            pages = fetcher.fetch_source(source, max_pages=max_events)
            summary.fetched += len(pages)

            selectors = get_selectors(source.provider)
            for page in pages:
                jsonld_events = parse_jsonld_events(page)
                if jsonld_events:
                    parsed_events = jsonld_events
                else:
                    parsed_events = parse_html_events(page, selectors)

                summary.parsed += len(parsed_events)
                extracted_events.extend(parsed_events)

        tz_name = area.timezone if area else "UTC"
        html_normalized = normalize_events(extracted_events, timezone_name=tz_name)
        all_normalized.extend(html_normalized)

    # --- Geocode events that lack coordinates ---
    accepted_events: list[NormalizedEvent] = []
    for event in all_normalized:
        if event.location_lat is not None and event.location_lng is not None:
            accepted_events.append(event)
            continue

        geocode_result = mapbox.geocode(
            event.location_text,
            country=settings.mapbox_country_bias,
            bbox=settings.mapbox_bbox_bias,
        )
        if geocode_result is None:
            summary.rejected_low_precision += 1
            logger.info(
                "Dropping event: geocode returned no result",
                extra={"title": event.title, "location_text": event.location_text},
            )
            summary.dropped_no_coords += 1
            continue

        summary.geocoded += 1
        score = score_geocode(event.location_text, geocode_result)
        if not passes_precision_gate(score, threshold=settings.geocode_min_score):
            summary.rejected_low_precision += 1
            logger.info(
                "Dropping event: geocode score too low",
                extra={"title": event.title, "score": score},
            )
            summary.dropped_no_coords += 1
            continue

        event.location_lat = geocode_result.get("lat")
        event.location_lng = geocode_result.get("lng")
        event.external_confidence = score
        accepted_events.append(event)

    # Drop events that still have no usable coordinates
    coords_events = []
    for event in accepted_events:
        if event.location_lat is None or event.location_lng is None:
            summary.dropped_no_coords += 1
            logger.info("Dropping event: no usable coordinates", extra={"title": event.title})
            continue
        coords_events.append(event)

    summary.accepted = len(coords_events)

    # --- Dedupe ---
    attach_external_event_ids(coords_events)
    unique_events, batch_duplicates = dedupe_in_batch(coords_events)
    summary.skipped_duplicates += batch_duplicates

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
