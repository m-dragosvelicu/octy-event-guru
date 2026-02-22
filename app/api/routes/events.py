from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ...core.config import get_settings, load_area_configs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/events", tags=["events"])


class NearbyEvent(BaseModel):
    id: str
    title: str
    description: str | None = None
    start_time: str
    end_time: str | None = None
    timezone: str | None = None
    start_time_local: str | None = None
    end_time_local: str | None = None
    location_name: str | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    external_provider: str | None = None
    external_event_id: str | None = None
    external_source_url: str | None = None
    external_confidence: float | None = None
    activity_id: str | None = None
    status: str | None = None
    distance_km: float | None = None


class NearbyResponse(BaseModel):
    events: list[NearbyEvent]
    count: int
    area_id: str | None = None


@router.get("/nearby", response_model=NearbyResponse)
def get_nearby_events(
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    area_id: str | None = Query(default=None),
    radius_km: float = Query(default=30, ge=1, le=200),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> NearbyResponse:
    settings = get_settings()
    resolved_area_id = area_id

    if lat is None or lng is None:
        target_area_id = area_id or settings.default_area_id
        areas = load_area_configs()
        area = next((a for a in areas if a.area_id == target_area_id), None)
        if area is None:
            return NearbyResponse(events=[], count=0, area_id=target_area_id)
        lat = area.lat
        lng = area.lng
        radius_km = area.radius_km
        days = area.horizon_days
        resolved_area_id = area.area_id

    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    radius_meters = radius_km * 1000

    try:
        response = client.rpc(
            "find_events_nearby",
            {
                "p_lat": lat,
                "p_lng": lng,
                "p_radius_meters": radius_meters,
                "p_start_date": now.isoformat(),
                "p_end_date": end.isoformat(),
                "p_limit": limit,
                "p_offset": offset,
            },
        ).execute()
    except Exception:
        logger.warning("find_events_nearby RPC failed", exc_info=True)
        return NearbyResponse(events=[], count=0, area_id=resolved_area_id)

    rows = response.data or []
    events = []
    for row in rows:
        events.append(
            NearbyEvent(
                id=row["id"],
                title=row["title"],
                description=row.get("description"),
                start_time=row["start_time"],
                end_time=row.get("end_time"),
                timezone=row.get("timezone"),
                start_time_local=row.get("start_time_local"),
                end_time_local=row.get("end_time_local"),
                location_name=row.get("location_name"),
                location_lat=row.get("location_lat"),
                location_lng=row.get("location_lng"),
                external_provider=row.get("external_provider"),
                external_event_id=row.get("external_event_id"),
                external_source_url=row.get("external_source_url"),
                external_confidence=row.get("external_confidence"),
                activity_id=row.get("activity_id"),
                status=row.get("status"),
                distance_km=row.get("distance_km"),
            )
        )

    return NearbyResponse(events=events, count=len(events), area_id=resolved_area_id)
