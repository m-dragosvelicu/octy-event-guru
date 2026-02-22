#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from app.core.config import get_settings, load_area_configs
    from app.jobs.ingest_job import run_ingest_job

    settings = get_settings()
    area = load_area_configs()[0]
    area_id = area.area_id

    print(f"=== INGEST RUN 1 (area={area_id}) ===")
    r1 = run_ingest_job(area_id=area_id, dry_run=False)
    print(json.dumps(r1, indent=2))

    print(f"\n=== INGEST RUN 2 (dedupe test) ===")
    r2 = run_ingest_job(area_id=area_id, dry_run=False)
    print(json.dumps(r2, indent=2))

    print(f"\n=== NEARBY QUERY ===")
    from supabase import create_client
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=area.horizon_days)

    resp = client.rpc("find_events_nearby", {
        "p_lat": area.lat,
        "p_lng": area.lng,
        "p_radius_meters": area.radius_km * 1000,
        "p_start_date": now.isoformat(),
        "p_end_date": end.isoformat(),
        "p_limit": 50,
        "p_offset": 0,
    }).execute()

    rows = resp.data or []
    total = len(rows)
    with_coords = sum(1 for r in rows if r.get("location_lat") is not None)
    with_provider = sum(1 for r in rows if r.get("external_provider"))
    with_eid = sum(1 for r in rows if r.get("external_event_id"))
    with_url = sum(1 for r in rows if r.get("external_source_url"))

    print(f"Total events: {total}")
    print(f"With coords: {with_coords}/{total}")
    print(f"With provider: {with_provider}/{total}")
    print(f"With event_id: {with_eid}/{total}")
    print(f"With source_url: {with_url}/{total}")

    print(f"\n--- Sample rows (up to 5) ---")
    for row in rows[:5]:
        print(json.dumps({
            "title": row["title"],
            "start_time": row["start_time"],
            "timezone": row.get("timezone"),
            "start_time_local": row.get("start_time_local"),
            "location_name": row.get("location_name"),
            "location_lat": row.get("location_lat"),
            "location_lng": row.get("location_lng"),
            "external_provider": row.get("external_provider"),
            "external_event_id": row.get("external_event_id"),
            "external_source_url": row.get("external_source_url"),
            "distance_km": row.get("distance_km"),
        }, indent=2, ensure_ascii=False))

    # --- METRICS TABLE ---
    i1 = r1.get("inserted", 0)
    i2 = r2.get("inserted", 0)
    coords_cov = 100.0 if total > 0 and with_coords == total else (with_coords / max(total, 1) * 100)
    prov_cov = 100.0 if total > 0 and with_provider == total else (with_provider / max(total, 1) * 100)
    dedupe_ratio = (i2 / i1 * 100) if i1 > 0 else 0.0

    print(f"\n=== METRICS TABLE ===")
    print(f"{'fetched':<25} {r1.get('fetched', 0)}")
    print(f"{'parsed':<25} {r1.get('parsed', 0)}")
    print(f"{'with_source_coords':<25} {r1.get('with_source_coords', 0)}")
    print(f"{'dropped_no_coords':<25} {r1.get('dropped_no_coords', 0)}")
    print(f"{'accepted':<25} {r1.get('accepted', 0)}")
    print(f"{'inserted_run1':<25} {i1}")
    print(f"{'inserted_run2':<25} {i2}")
    print(f"{'dedupe_ratio':<25} {dedupe_ratio:.1f}%")
    print(f"{'skipped_dupes_run2':<25} {r2.get('skipped_duplicates', 0)}")
    print(f"{'date_only_count':<25} {r1.get('date_only_count', 0)}")
    print(f"{'coords_coverage':<25} {coords_cov:.1f}%")
    print(f"{'provenance_coverage':<25} {prov_cov:.1f}%")
    print(f"{'domain_stats':<25} {json.dumps(r1.get('domain_stats', {}))}")

    # --- VERDICT ---
    failures = []
    if i1 == 0:
        failures.append("run1 inserted 0 events")
    if coords_cov < 100:
        failures.append(f"coords_coverage={coords_cov:.1f}% (need 100%)")
    if prov_cov < 100:
        failures.append(f"provenance_coverage={prov_cov:.1f}% (need 100%)")
    if i1 > 0 and dedupe_ratio > 10:
        failures.append(f"dedupe_ratio={dedupe_ratio:.1f}% (need <= 10%)")

    print(f"\n=== VERDICT: {'PASS' if not failures else 'FAIL'} ===")
    if failures:
        for f in failures:
            print(f"  BLOCKER: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
