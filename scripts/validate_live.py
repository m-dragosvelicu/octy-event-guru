from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate live Event Guru ingestion: fetch, ingest, and query real events."
    )
    parser.add_argument("--area-id", default="bucharest")
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Run ingest in dry-run mode (no DB writes)")
    parser.add_argument("--query-only", action="store_true", help="Skip ingestion, only query nearby events")
    return parser.parse_args()


def run_ingest(area_id: str, dry_run: bool, max_events: int | None) -> dict:
    from app.jobs.ingest_job import run_ingest_job

    return run_ingest_job(area_id=area_id, dry_run=dry_run, max_events=max_events)


def query_nearby(area_id: str) -> dict:
    from app.core.config import get_settings, load_area_configs

    settings = get_settings()
    areas = load_area_configs()
    area = next((a for a in areas if a.area_id == area_id), None)
    if area is None:
        return {"error": f"No area config found for '{area_id}'"}

    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=area.horizon_days)

    response = client.rpc(
        "find_events_nearby",
        {
            "p_lat": area.lat,
            "p_lng": area.lng,
            "p_radius_meters": area.radius_km * 1000,
            "p_start_date": now.isoformat(),
            "p_end_date": end.isoformat(),
            "p_limit": 50,
            "p_offset": 0,
        },
    ).execute()

    rows = response.data or []

    with_coords = sum(1 for r in rows if r.get("location_lat") is not None)
    with_provider = sum(1 for r in rows if r.get("external_provider"))
    with_source_url = sum(1 for r in rows if r.get("external_source_url"))
    with_event_id = sum(1 for r in rows if r.get("external_event_id"))
    with_timezone = sum(1 for r in rows if r.get("timezone"))

    return {
        "total_events": len(rows),
        "with_coordinates": with_coords,
        "with_coordinates_pct": round(with_coords / len(rows) * 100, 1) if rows else 0,
        "with_provider": with_provider,
        "with_source_url": with_source_url,
        "with_event_id": with_event_id,
        "with_timezone": with_timezone,
        "sample_events": [
            {
                "id": r["id"],
                "title": r["title"],
                "start_time": r["start_time"],
                "timezone": r.get("timezone"),
                "start_time_local": r.get("start_time_local"),
                "location_name": r.get("location_name"),
                "location_lat": r.get("location_lat"),
                "location_lng": r.get("location_lng"),
                "external_provider": r.get("external_provider"),
                "external_event_id": r.get("external_event_id"),
                "external_source_url": r.get("external_source_url"),
                "external_confidence": r.get("external_confidence"),
                "distance_km": r.get("distance_km"),
            }
            for r in rows[:5]
        ],
    }


def main() -> int:
    args = _parse_args()
    output: dict = {"area_id": args.area_id, "timestamp": datetime.now(timezone.utc).isoformat()}

    if not args.query_only:
        print(f"--- Running ingest for area '{args.area_id}' (dry_run={args.dry_run}) ---")
        try:
            summary = run_ingest(args.area_id, args.dry_run, args.max_events)
            output["ingest_summary"] = summary
            print(f"Ingest complete: {json.dumps(summary, indent=2)}")
        except Exception as exc:
            output["ingest_error"] = str(exc)
            print(f"Ingest failed: {exc}")

        if not args.dry_run:
            print(f"\n--- Re-running ingest to verify dedupe ---")
            try:
                summary2 = run_ingest(args.area_id, False, args.max_events)
                output["dedupe_rerun"] = summary2
                new_inserts = summary2.get("inserted", 0)
                print(f"Dedupe re-run: inserted={new_inserts} (should be 0 or near-zero)")
            except Exception as exc:
                output["dedupe_rerun_error"] = str(exc)
                print(f"Dedupe re-run failed: {exc}")

    if not args.dry_run:
        print(f"\n--- Querying nearby events ---")
        try:
            query_result = query_nearby(args.area_id)
            output["nearby_query"] = query_result
            print(f"Nearby query: {json.dumps(query_result, indent=2)}")
        except Exception as exc:
            output["nearby_query_error"] = str(exc)
            print(f"Nearby query failed: {exc}")

    print(f"\n=== Full output ===")
    print(json.dumps(output, indent=2, default=str))

    total = output.get("nearby_query", {}).get("total_events", 0)
    with_coords_pct = output.get("nearby_query", {}).get("with_coordinates_pct", 0)
    with_provider = output.get("nearby_query", {}).get("with_provider", 0)

    if total > 0:
        print(f"\n--- Validation Summary ---")
        print(f"Events returned: {total}")
        print(f"With coordinates: {with_coords_pct}%")
        print(f"With provider: {with_provider}/{total}")
        if with_coords_pct >= 90 and with_provider == total:
            print("PASS: All provenance and coordinate requirements met")
            return 0
        else:
            print("WARN: Some requirements not fully met")
            return 1
    elif args.dry_run:
        inserted = output.get("ingest_summary", {}).get("inserted", 0)
        if inserted > 0:
            print(f"\nDry-run would insert {inserted} events")
            return 0
        else:
            print(f"\nDry-run found 0 events to insert")
            return 1
    else:
        print("FAIL: No events found")
        return 1


if __name__ == "__main__":
    sys.exit(main())
