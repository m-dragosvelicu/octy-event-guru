import hashlib
import re

from ..domain.models import NormalizedEvent


def build_external_event_id(event: NormalizedEvent) -> str:
    if event.canonical_id:
        cleaned = re.sub(r"\s+", "-", event.canonical_id.strip().lower())
        cleaned = re.sub(r"[^a-z0-9._:/-]", "", cleaned)
        return cleaned[:160]

    hash_source = "|".join(
        [
            event.source_url.strip().lower(),
            event.title.strip().lower(),
            event.start_time.isoformat(),
        ]
    )
    return hashlib.sha256(hash_source.encode("utf-8")).hexdigest()


def attach_external_event_ids(events: list[NormalizedEvent]) -> list[NormalizedEvent]:
    for event in events:
        event.external_event_id = build_external_event_id(event)
    return events


def dedupe_in_batch(events: list[NormalizedEvent]) -> tuple[list[NormalizedEvent], int]:
    unique_events: list[NormalizedEvent] = []
    seen: set[tuple[str, str]] = set()
    duplicates = 0

    for event in events:
        if not event.external_event_id:
            event.external_event_id = build_external_event_id(event)

        dedupe_key = (event.provider, event.external_event_id)
        if dedupe_key in seen:
            duplicates += 1
            continue

        seen.add(dedupe_key)
        unique_events.append(event)

    return unique_events, duplicates
