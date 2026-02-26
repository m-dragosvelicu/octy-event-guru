import hashlib
import re
import unicodedata

from ..domain.models import NormalizedEvent

_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]")
_MULTI_SPACE_RE = re.compile(r"\s+")


def _canonicalize(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text.strip().lower())
    stripped = _NON_ALNUM_RE.sub("", lowered)
    return _MULTI_SPACE_RE.sub(" ", stripped).strip()


def build_external_event_id(event: NormalizedEvent) -> str:
    if event.canonical_id:
        cleaned = re.sub(r"\s+", "-", event.canonical_id.strip().lower())
        cleaned = re.sub(r"[^a-z0-9._:/-]", "", cleaned)
        return cleaned[:160]

    # Use content-based fingerprint (title + date + venue) so that the same
    # event discovered via different URLs gets the same external_event_id.
    return _build_fingerprint(event)


def _build_fingerprint(event: NormalizedEvent) -> str:
    parts = [
        _canonicalize(event.title),
        event.start_time.date().isoformat(),
        _canonicalize(event.location_name),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def attach_external_event_ids(events: list[NormalizedEvent]) -> list[NormalizedEvent]:
    for event in events:
        event.external_event_id = build_external_event_id(event)
    return events


def dedupe_in_batch(events: list[NormalizedEvent]) -> tuple[list[NormalizedEvent], int]:
    unique_events: list[NormalizedEvent] = []
    seen_primary: set[tuple[str, str]] = set()
    seen_fingerprints: set[str] = set()
    duplicates = 0

    for event in events:
        if not event.external_event_id:
            event.external_event_id = build_external_event_id(event)

        primary_key = (event.provider, event.external_event_id)
        if primary_key in seen_primary:
            duplicates += 1
            continue

        fingerprint = _build_fingerprint(event)
        if fingerprint in seen_fingerprints:
            duplicates += 1
            continue

        seen_primary.add(primary_key)
        seen_fingerprints.add(fingerprint)
        unique_events.append(event)

    return unique_events, duplicates
