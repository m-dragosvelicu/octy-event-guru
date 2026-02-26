"""Reusable pipeline extracted from ingest_job for deterministic testing.

run_pipeline_from_pages() accepts pre-fetched RawPage objects,
skipping the Brave Search + HTTP fetch steps so tests can supply
snapshot HTML and get fully deterministic results.

Pipeline invariants:
- Events without source coordinates are dropped (no Mapbox geocoding).
- Events without provider/external_event_id/source_url are dropped at insert.
- Deduplication runs in two layers: in-batch fingerprint, then DB lookup.
"""
from __future__ import annotations

import logging
from collections import Counter

from ..core.config import Settings
from ..domain.models import AreaConfig, IngestSummary, NormalizedEvent, RawPage
from ..extract.html_fallback import parse_html_events
from ..extract.jsonld import parse_jsonld_events
from ..extract.normalize import normalize_events
from ..sink.dedupe import attach_external_event_ids, dedupe_in_batch
from ..sources.adapters import get_selectors

logger = logging.getLogger(__name__)


def run_pipeline_from_pages(
    pages: list[RawPage],
    area: AreaConfig,
    settings: Settings,
    *,
    dry_run: bool = False,
    max_events: int | None = None,
) -> dict:
    """Run the extraction-to-insert pipeline on pre-fetched pages.

    Returns the IngestSummary as a dict (same shape as run_ingest_job).
    """
    summary = IngestSummary()
    summary.fetched = len(pages)

    # --- Step 3: Extract events from pages ---
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

    # --- Step 4: Normalize ---
    normalized = normalize_events(extracted_events, timezone_name=area.timezone)

    # --- Step 5: Drop events without source coordinates ---
    coords_events: list[NormalizedEvent] = []
    for ev in normalized:
        if ev.location_lat is not None and ev.location_lng is not None:
            summary.with_source_coords += 1
            coords_events.append(ev)
        else:
            summary.dropped_no_coords += 1

    # --- Step 6: Track date_only and domain stats ---
    domain_counter: Counter[str] = Counter()
    for ev in coords_events:
        if ev.date_only:
            summary.date_only_count += 1
        domain_counter[ev.provider] += 1

    summary.domain_stats = dict(domain_counter.most_common())

    # --- Step 7: Per-domain cap ---
    if area.per_domain_cap is not None and area.per_domain_cap > 0:
        capped: list[NormalizedEvent] = []
        cap_counter: Counter[str] = Counter()
        for ev in coords_events:
            if cap_counter[ev.provider] < area.per_domain_cap:
                capped.append(ev)
                cap_counter[ev.provider] += 1
        coords_events = capped

    summary.accepted = len(coords_events)

    # --- Step 7b: Provider diversity metrics ---
    accepted_provider_counter: Counter[str] = Counter(ev.provider for ev in coords_events)
    summary.provider_count = len(accepted_provider_counter)
    if summary.accepted > 0:
        top_count = accepted_provider_counter.most_common(1)[0][1]
        summary.top_provider_pct = round(top_count / summary.accepted * 100, 2)
    else:
        summary.top_provider_pct = 0.0

    if summary.top_provider_pct > area.provider_diversity_warn_pct:
        top_provider = accepted_provider_counter.most_common(1)[0][0]
        logger.warning(
            "Provider diversity warning for area %s: %s supplied %.1f%% of accepted events"
            " (threshold %d%%). Consider broadening sources.",
            area.area_id,
            top_provider,
            summary.top_provider_pct,
            area.provider_diversity_warn_pct,
        )

    # --- Step 8: Dedupe ---
    attach_external_event_ids(coords_events)
    summary.candidate_ids = [
        ev.external_event_id for ev in coords_events if ev.external_event_id
    ]
    unique_events, batch_duplicates = dedupe_in_batch(coords_events)
    summary.skipped_duplicates += batch_duplicates

    # --- Step 9: DB dedupe + insert ---
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

        inserted_count, inserted_ids = writer.insert_events(db_unique_events, dry_run=dry_run)
        summary.inserted = inserted_count
        summary.inserted_ids = inserted_ids
    else:
        if max_events is not None:
            unique_events = unique_events[:max_events]
        summary.inserted = len(unique_events) if dry_run else 0
        summary.inserted_ids = [
            ev.external_event_id for ev in unique_events if ev.external_event_id
        ] if dry_run else []

    return summary.model_dump()
