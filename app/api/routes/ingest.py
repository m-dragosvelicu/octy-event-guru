import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from ...core.config import get_settings
from ...jobs.ingest_job import run_ingest_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


class IngestRunRequest(BaseModel):
    area_id: str | None = None
    dry_run: bool = False
    max_events: int | None = Field(default=None, ge=1)


class IngestSummaryResponse(BaseModel):
    fetched: int
    parsed: int
    geocoded: int
    accepted: int
    inserted: int
    skipped_duplicates: int
    rejected_low_precision: int
    dropped_no_coords: int = 0
    with_source_coords: int = 0


class IngestHealthResponse(BaseModel):
    status: str


class IngestRunResponse(BaseModel):
    area_id: str
    dry_run: bool
    max_events: int | None
    summary: IngestSummaryResponse


def _extract_bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split(" ", maxsplit=1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _verify_ingest_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> None:
    settings = get_settings()
    provided_token = x_api_token or _extract_bearer_token(authorization)

    if not provided_token:
        raise HTTPException(status_code=401, detail="Missing ingest API token")

    if not secrets.compare_digest(provided_token, settings.ingest_api_token):
        raise HTTPException(status_code=401, detail="Invalid ingest API token")


@router.get("/health", response_model=IngestHealthResponse)
def ingest_health() -> IngestHealthResponse:
    return IngestHealthResponse(status="ok")


@router.post("/run", response_model=IngestRunResponse)
def run_ingest(
    payload: IngestRunRequest,
    _: Any = Depends(_verify_ingest_token),
) -> IngestRunResponse:
    summary = run_ingest_job(
        area_id=payload.area_id,
        dry_run=payload.dry_run,
        max_events=payload.max_events,
    )
    selected_area = payload.area_id or get_settings().default_area_id
    return IngestRunResponse(
        area_id=selected_area,
        dry_run=payload.dry_run,
        max_events=payload.max_events,
        summary=IngestSummaryResponse(**summary),
    )


@router.post("/preview", response_model=IngestRunResponse)
def preview_ingest(
    payload: IngestRunRequest,
    _: Any = Depends(_verify_ingest_token),
) -> IngestRunResponse:
    preview_payload = payload.model_copy(update={"dry_run": True})
    summary = run_ingest_job(
        area_id=preview_payload.area_id,
        dry_run=True,
        max_events=preview_payload.max_events,
    )
    selected_area = preview_payload.area_id or get_settings().default_area_id
    return IngestRunResponse(
        area_id=selected_area,
        dry_run=True,
        max_events=preview_payload.max_events,
        summary=IngestSummaryResponse(**summary),
    )
