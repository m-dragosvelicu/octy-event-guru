import html
import re
from datetime import UTC, datetime

import dateparser

from ..domain.models import ExtractedEvent, NormalizedEvent

_SPACE_RE = re.compile(r"\s+")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    compact = _SPACE_RE.sub(" ", html.unescape(value)).strip()
    return compact or None


def _parse_datetime(value: str | None, timezone_name: str) -> datetime | None:
    if not value:
        return None

    dt = dateparser.parse(
        value,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": timezone_name,
            "TO_TIMEZONE": timezone_name,
            "PREFER_DATES_FROM": "future",
        },
    )
    if dt is None:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC)


def _to_local_iso(value: str | None, timezone_name: str) -> str | None:
    if not value:
        return None

    dt = dateparser.parse(
        value,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "TIMEZONE": timezone_name,
            "TO_TIMEZONE": timezone_name,
            "PREFER_DATES_FROM": "future",
        },
    )
    if dt is None:
        return None

    return dt.isoformat()


def normalize_event(event: ExtractedEvent, timezone_name: str = "UTC") -> NormalizedEvent | None:
    title = _clean_text(event.title)
    location_name = _clean_text(event.location_name)
    location_address = _clean_text(event.location_address)
    location_text = _clean_text(
        " - ".join(part for part in [location_name, location_address] if part)
    )

    if not title or not location_text:
        return None

    start_time = _parse_datetime(event.start_time_text, timezone_name)
    if start_time is None:
        return None

    end_time = _parse_datetime(event.end_time_text, timezone_name)
    if end_time is not None and end_time <= start_time:
        end_time = None

    start_time_local = _to_local_iso(event.start_time_text, timezone_name)
    end_time_local = _to_local_iso(event.end_time_text, timezone_name) if end_time else None

    return NormalizedEvent(
        area_id=event.area_id,
        provider=event.provider,
        sport_hint=event.sport_hint,
        source_url=event.source_url,
        title=title,
        description=_clean_text(event.description),
        start_time=start_time,
        end_time=end_time,
        location_name=location_name or location_text,
        location_address=location_address,
        location_text=location_text,
        canonical_id=_clean_text(event.canonical_id),
        timezone=timezone_name if timezone_name != "UTC" else None,
        start_time_local=start_time_local,
        end_time_local=end_time_local,
    )


def normalize_events(events: list[ExtractedEvent], timezone_name: str = "UTC") -> list[NormalizedEvent]:
    normalized: list[NormalizedEvent] = []
    for event in events:
        maybe_event = normalize_event(event, timezone_name=timezone_name)
        if maybe_event is not None:
            normalized.append(maybe_event)
    return normalized
