from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from supabase import Client, create_client

from ..core.config import Settings
from ..domain.models import NormalizedEvent

logger = logging.getLogger(__name__)


class SupabaseWriter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
        self._activity_cache: dict[str, str] = {}

    def get_existing_external_event_ids(self, provider: str, external_ids: list[str]) -> set[str]:
        if not external_ids:
            return set()

        existing: set[str] = set()

        chunk_size = 100
        for start in range(0, len(external_ids), chunk_size):
            chunk = external_ids[start : start + chunk_size]
            response = (
                self.client.table("events")
                .select("external_event_id")
                .eq("external_provider", provider)
                .in_("external_event_id", chunk)
                .execute()
            )
            rows = response.data or []
            for row in rows:
                event_id = row.get("external_event_id")
                if isinstance(event_id, str):
                    existing.add(event_id)

        return existing

    def insert_events(self, events: list[NormalizedEvent], *, dry_run: bool = False) -> tuple[int, list[str]]:
        inserted = 0
        inserted_ids: list[str] = []

        for event in events:
            if event.start_time <= datetime.now(timezone.utc):
                continue

            if event.location_lat is None or event.location_lng is None:
                logger.info(
                    "Skipping event: no coordinates",
                    extra={"title": event.title, "provider": event.provider},
                )
                continue

            if not event.provider or not event.external_event_id or not event.source_url:
                logger.info(
                    "Skipping event: missing provenance",
                    extra={"title": event.title},
                )
                continue

            activity_id = self._resolve_activity_id(event.sport_hint)

            payload = {
                "title": event.title,
                "description": event.description,
                "location_name": event.location_name,
                "location_lat": event.location_lat,
                "location_lng": event.location_lng,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "max_participants": 20,
                "presigned_count": 0,
                "skill_level": "beginner",
                "status": "upcoming",
                "host_id": self.settings.event_guru_host_user_id or None,
                "external_provider": event.provider,
                "external_event_id": event.external_event_id,
                "external_source_url": event.source_url,
                "external_confidence": event.external_confidence,
                "timezone": event.timezone,
                "start_time_local": event.start_time_local,
                "end_time_local": event.end_time_local,
                "date_only": event.date_only,
            }

            if activity_id is not None:
                payload["activity_id"] = activity_id

            if dry_run:
                inserted += 1
                inserted_ids.append(event.external_event_id)
                continue

            try:
                self.client.table("events").insert(payload).execute()
                inserted += 1
                inserted_ids.append(event.external_event_id)
            except Exception:
                logger.warning(
                    "Supabase insert failed for event",
                    extra={"title": event.title, "provider": event.provider},
                    exc_info=True,
                )

        return inserted, inserted_ids

    def persist_ingest_run(
        self,
        run_id: str,
        area_id: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        summary: dict,
    ) -> None:
        """Upsert a row into the ingest_runs table."""
        duration = (finished_at - started_at).total_seconds()

        # Extract source_breakdown from domain_stats if present
        source_breakdown = summary.get("domain_stats", {})

        # Build a clean top-level summary without large lists
        summary_payload = {
            k: v
            for k, v in summary.items()
            if k not in ("candidate_ids", "inserted_ids", "domain_stats")
        }

        payload = {
            "run_id": run_id,
            "area_id": area_id,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": duration,
            "status": status,
            "summary": json.dumps(summary_payload),
            "errors": json.dumps([]),
            "source_breakdown": json.dumps(source_breakdown),
        }

        try:
            self.client.table("ingest_runs").upsert(payload).execute()
            logger.info("Persisted ingest run", extra={"run_id": run_id, "status": status})
        except Exception:
            logger.warning("Failed to persist ingest run to DB", extra={"run_id": run_id}, exc_info=True)

    def insert_alerts(self, alerts: list[dict]) -> None:
        """Insert alert rows into the alerts table. Ignores individual failures."""
        for alert in alerts:
            try:
                self.client.table("alerts").insert(alert).execute()
            except Exception:
                logger.warning(
                    "Failed to insert alert",
                    extra={"condition": alert.get("condition")},
                    exc_info=True,
                )

    def upsert_source_scorecard(
        self,
        provider: str,
        area_id: str,
        health_status: str,
        metrics: dict,
    ) -> None:
        """Upsert a row in source_scorecards for the given provider+area.

        Uses the unique index on (provider, area_id) to avoid unbounded duplicates.
        """
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "provider": provider,
            "area_id": area_id,
            "health_status": health_status,
            "last_checked_at": now,
            "metrics": json.dumps(metrics),
        }
        try:
            (
                self.client.table("source_scorecards")
                .upsert(payload, on_conflict="provider,area_id")
                .execute()
            )
            logger.info(
                "Upserted source scorecard",
                extra={"provider": provider, "area_id": area_id, "health_status": health_status},
            )
        except Exception:
            logger.warning(
                "Failed to upsert source scorecard",
                extra={"provider": provider, "area_id": area_id},
                exc_info=True,
            )

    def _resolve_activity_id(self, sport_hint: str | None) -> str | None:
        if not sport_hint:
            return None

        key = sport_hint.strip().lower()
        if key in self._activity_cache:
            return self._activity_cache[key]

        response = (
            self.client.table("activities")
            .select("id,slug,name")
            .eq("slug", key)
            .limit(1)
            .execute()
        )

        rows = response.data or []
        if rows:
            activity_id = rows[0].get("id")
            if isinstance(activity_id, str):
                self._activity_cache[key] = activity_id
                return activity_id

        return None
