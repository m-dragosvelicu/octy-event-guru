from __future__ import annotations

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

    def insert_events(self, events: list[NormalizedEvent], *, dry_run: bool = False) -> int:
        inserted = 0

        for event in events:
            if event.start_time <= datetime.now(timezone.utc):
                continue

            activity_id = self._resolve_activity_id(event.sport_hint)
            if activity_id is None:
                logger.info("Skipping event because sport hint could not be mapped")
                continue

            if event.location_lat is None or event.location_lng is None:
                continue

            payload = {
                "title": event.title,
                "description": event.description,
                "activity_id": activity_id,
                "location_name": event.location_name,
                "location_lat": event.location_lat,
                "location_lng": event.location_lng,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "max_participants": 20,
                "presigned_count": 0,
                "skill_level": "beginner",
                "status": "upcoming",
                "host_id": self.settings.event_guru_host_user_id,
                "external_provider": event.provider,
                "external_event_id": event.external_event_id,
                "external_source_url": event.source_url,
                "external_confidence": event.external_confidence,
            }

            if dry_run:
                inserted += 1
                continue

            try:
                self.client.table("events").insert(payload).execute()
                inserted += 1
            except Exception:
                logger.warning("Supabase insert failed for event", exc_info=True)

        return inserted

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
