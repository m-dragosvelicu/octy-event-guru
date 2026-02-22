from datetime import datetime

from pydantic import BaseModel, Field


class AreaConfig(BaseModel):
    area_id: str
    lat: float
    lng: float
    radius_km: int = 50
    timezone: str = "UTC"
    horizon_days: int = 7
    default_activity_slug: str | None = None
    search_queries: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    area_id: str
    provider: str
    seed_urls: list[str]
    sport_hint: str | None = None
    enabled: bool = True
    allowed_domains: list[str] = Field(default_factory=list)


class RawPage(BaseModel):
    area_id: str
    provider: str
    sport_hint: str | None
    url: str
    html: str


class ExtractedEvent(BaseModel):
    area_id: str
    provider: str
    sport_hint: str | None
    source_url: str

    title: str | None = None
    description: str | None = None
    start_time_text: str | None = None
    end_time_text: str | None = None
    location_name: str | None = None
    location_address: str | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    canonical_id: str | None = None


class NormalizedEvent(BaseModel):
    area_id: str
    provider: str
    sport_hint: str | None
    source_url: str

    title: str
    description: str | None
    start_time: datetime
    end_time: datetime | None
    location_name: str
    location_address: str | None
    location_text: str

    canonical_id: str | None = None
    external_event_id: str | None = None
    external_confidence: float | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    timezone: str | None = None
    start_time_local: str | None = None
    end_time_local: str | None = None


class IngestSummary(BaseModel):
    fetched: int = 0
    parsed: int = 0
    geocoded: int = 0
    accepted: int = 0
    inserted: int = 0
    skipped_duplicates: int = 0
    rejected_low_precision: int = 0
    dropped_no_coords: int = 0
    with_source_coords: int = 0
