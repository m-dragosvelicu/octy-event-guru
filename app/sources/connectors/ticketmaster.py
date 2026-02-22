from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

from ...domain.models import AreaConfig, NormalizedEvent

logger = logging.getLogger(__name__)

DISCOVERY_URL = "https://app.ticketmaster.com/discovery/v2/events.json"

SEGMENT_TO_SLUG: dict[str, str] = {
    "music": "music",
    "sports": "sports",
    "arts & theatre": "theatre",
    "arts": "theatre",
    "theatre": "theatre",
    "film": "events",
    "miscellaneous": "events",
    "undefined": "events",
}

PAGE_SIZE = 200
MAX_PAGES = 5


def fetch_ticketmaster_events(
    *,
    api_key: str,
    area: AreaConfig,
    timeout_seconds: int = 15,
) -> list[NormalizedEvent]:
    if not api_key:
        logger.error("TICKETMASTER_API_KEY is empty, skipping Ticketmaster fetch")
        return []

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=area.horizon_days)

    start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    all_events: list[NormalizedEvent] = []
    page = 0

    while page < MAX_PAGES:
        params = {
            "apikey": api_key,
            "latlong": f"{area.lat},{area.lng}",
            "radius": str(area.radius_km),
            "unit": "km",
            "startDateTime": start_str,
            "endDateTime": end_str,
            "size": str(PAGE_SIZE),
            "page": str(page),
            "sort": "date,asc",
        }

        try:
            resp = requests.get(DISCOVERY_URL, params=params, timeout=timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("Ticketmaster API request failed", exc_info=True)
            break

        data = resp.json()
        embedded = data.get("_embedded")
        if not embedded:
            break

        raw_events = embedded.get("events", [])
        if not raw_events:
            break

        for raw in raw_events:
            event = _parse_event(raw, area)
            if event is not None:
                all_events.append(event)

        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 0)
        page += 1
        if page >= total_pages:
            break

    logger.info(
        "Ticketmaster fetch complete",
        extra={"area_id": area.area_id, "event_count": len(all_events)},
    )
    return all_events


def _parse_event(raw: dict, area: AreaConfig) -> NormalizedEvent | None:
    event_id = raw.get("id")
    name = raw.get("name")
    if not name or not event_id:
        return None

    url = raw.get("url") or ""
    description = raw.get("description") or raw.get("info") or raw.get("pleaseNote") or ""

    dates = raw.get("dates", {})
    start_obj = dates.get("start", {})
    tz_name = dates.get("timezone") or area.timezone

    utc_dt_str = start_obj.get("dateTime")
    local_date = start_obj.get("localDate")
    local_time = start_obj.get("localTime")

    start_time_utc = _parse_utc_datetime(utc_dt_str)
    if start_time_utc is None and local_date:
        start_time_utc = _fallback_parse_local(local_date, local_time, tz_name)
    if start_time_utc is None:
        return None

    start_time_local = _build_local_string(local_date, local_time, tz_name)

    end_dates = dates.get("end", {})
    end_utc_str = end_dates.get("dateTime")
    end_time_utc = _parse_utc_datetime(end_utc_str)
    end_time_local = None
    if end_dates.get("localDate"):
        end_time_local = _build_local_string(
            end_dates.get("localDate"),
            end_dates.get("localTime"),
            tz_name,
        )

    venue = _extract_venue(raw)
    location_name = venue.get("name") or ""
    location_address = venue.get("address") or ""
    location_text = " - ".join(p for p in [location_name, location_address] if p) or location_name
    lat = venue.get("lat")
    lng = venue.get("lng")

    if not location_text:
        return None

    sport_hint = _classify_event(raw, area)

    return NormalizedEvent(
        area_id=area.area_id,
        provider="ticketmaster",
        sport_hint=sport_hint,
        source_url=url,
        title=name,
        description=description[:2000] if description else None,
        start_time=start_time_utc,
        end_time=end_time_utc,
        location_name=location_name or location_text,
        location_address=location_address or None,
        location_text=location_text,
        canonical_id=event_id,
        external_event_id=event_id,
        location_lat=lat,
        location_lng=lng,
        timezone=tz_name,
        start_time_local=start_time_local,
        end_time_local=end_time_local,
    )


def _parse_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _fallback_parse_local(local_date: str, local_time: str | None, tz_name: str) -> datetime | None:
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(tz_name)
        time_part = local_time or "00:00:00"
        dt_str = f"{local_date}T{time_part}"
        naive = datetime.fromisoformat(dt_str)
        return naive.replace(tzinfo=tz).astimezone(timezone.utc)
    except Exception:
        return None


def _build_local_string(local_date: str | None, local_time: str | None, tz_name: str) -> str | None:
    if not local_date:
        return None
    time_part = local_time or "00:00:00"
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(tz_name)
        naive = datetime.fromisoformat(f"{local_date}T{time_part}")
        aware = naive.replace(tzinfo=tz)
        return aware.isoformat()
    except Exception:
        return f"{local_date}T{time_part}"


def _extract_venue(raw: dict) -> dict:
    venues = (raw.get("_embedded") or {}).get("venues") or []
    if not venues:
        return {}
    v = venues[0]
    name = v.get("name") or ""

    addr_parts = []
    addr_obj = v.get("address") or {}
    if addr_obj.get("line1"):
        addr_parts.append(addr_obj["line1"])
    city = (v.get("city") or {}).get("name")
    if city:
        addr_parts.append(city)
    country = (v.get("country") or {}).get("name")
    if country:
        addr_parts.append(country)
    address = ", ".join(addr_parts)

    loc = v.get("location") or {}
    lat = _safe_float(loc.get("latitude"))
    lng = _safe_float(loc.get("longitude"))

    return {"name": name, "address": address, "lat": lat, "lng": lng}


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _classify_event(raw: dict, area: AreaConfig) -> str:
    classifications = raw.get("classifications") or []
    for cls in classifications:
        segment = cls.get("segment") or {}
        segment_name = (segment.get("name") or "").lower().strip()
        if segment_name in SEGMENT_TO_SLUG:
            return SEGMENT_TO_SLUG[segment_name]

        genre = cls.get("genre") or {}
        genre_name = (genre.get("name") or "").lower().strip()
        if genre_name in SEGMENT_TO_SLUG:
            return SEGMENT_TO_SLUG[genre_name]

    return area.default_activity_slug or "events"
