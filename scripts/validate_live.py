#!/usr/bin/env python3
"""Live validation: two ingest runs with diff-based dedupe classification.

Verdicts:
  FAIL  - duplicate_leaks_in_run2 is non-empty (dedupe bug)
  FAIL  - coords_coverage < 100% or provenance_coverage < 100%
  FAIL  - run1 inserted 0 events
  PASS (with new discovery) - run2 inserted events, all are new_discovery
  PASS (stable)             - run2 inserted 0
"""
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
    from app.domain.run_diff import compute_run_diff
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

    # --- Compute run diff ---
    diff = compute_run_diff(
        r1_candidates=r1.get("candidate_ids", []),
        r1_inserted=r1.get("inserted_ids", []),
        r2_candidates=r2.get("candidate_ids", []),
        r2_inserted=r2.get("inserted_ids", []),
    )

    print(f"\n=== RUN DIFF REPORT ===")
    print(f"{'run1_candidates':<30} {diff.run1_candidate_count}")
    print(f"{'run1_inserted':<30} {diff.run1_inserted_count}")
    print(f"{'run2_candidates':<30} {diff.run2_candidate_count}")
    print(f"{'run2_inserted':<30} {diff.run2_inserted_count}")
    print(f"{'shared_candidates':<30} {len(diff.shared_candidates)}")
    print(f"{'new_candidates_in_run2':<30} {len(diff.new_candidates_in_run2)}")
    print(f"{'duplicate_leaks_in_run2':<30} {len(diff.duplicate_leaks_in_run2)}")
    print(f"{'new_discovery_in_run2':<30} {len(diff.new_discovery_in_run2)}")

    if diff.duplicate_leaks_in_run2:
        print(f"\n  Leaked IDs: {diff.duplicate_leaks_in_run2[:10]}")
    if diff.new_discovery_in_run2:
        print(f"\n  New discovery IDs: {diff.new_discovery_in_run2[:10]}")

    # --- Nearby query for coverage checks ---
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
            "date_only": row.get("date_only"),
            "location_name": row.get("location_name"),
            "location_lat": row.get("location_lat"),
            "location_lng": row.get("location_lng"),
            "external_provider": row.get("external_provider"),
            "external_event_id": row.get("external_event_id"),
            "external_source_url": row.get("external_source_url"),
            "distance_km": row.get("distance_km"),
        }, indent=2, ensure_ascii=False))

    # --- Metrics ---
    i1 = r1.get("inserted", 0)
    coords_cov = 100.0 if total > 0 and with_coords == total else (with_coords / max(total, 1) * 100)
    prov_cov = 100.0 if total > 0 and with_provider == total else (with_provider / max(total, 1) * 100)

    print(f"\n=== METRICS TABLE ===")
    print(f"{'fetched':<30} {r1.get('fetched', 0)}")
    print(f"{'parsed':<30} {r1.get('parsed', 0)}")
    print(f"{'with_source_coords':<30} {r1.get('with_source_coords', 0)}")
    print(f"{'dropped_no_coords':<30} {r1.get('dropped_no_coords', 0)}")
    print(f"{'accepted':<30} {r1.get('accepted', 0)}")
    print(f"{'inserted_run1':<30} {i1}")
    print(f"{'inserted_run2':<30} {diff.run2_inserted_count}")
    print(f"{'duplicate_leaks':<30} {len(diff.duplicate_leaks_in_run2)}")
    print(f"{'new_discovery':<30} {len(diff.new_discovery_in_run2)}")
    print(f"{'date_only_count':<30} {r1.get('date_only_count', 0)}")
    print(f"{'coords_coverage':<30} {coords_cov:.1f}%")
    print(f"{'provenance_coverage':<30} {prov_cov:.1f}%")
    print(f"{'domain_stats':<30} {json.dumps(r1.get('domain_stats', {}))}")

    # --- Verdict ---
    failures: list[str] = []
    if i1 == 0:
        failures.append("run1 inserted 0 events")
    if coords_cov < 100:
        failures.append(f"coords_coverage={coords_cov:.1f}% (need 100%)")
    if prov_cov < 100:
        failures.append(f"provenance_coverage={prov_cov:.1f}% (need 100%)")
    if diff.duplicate_leaks_in_run2:
        failures.append(
            f"duplicate_leaks={len(diff.duplicate_leaks_in_run2)} "
            f"(dedupe bug: {diff.duplicate_leaks_in_run2[:5]})"
        )

    if failures:
        print(f"\n=== VERDICT: FAIL ===")
        for f in failures:
            print(f"  BLOCKER: {f}")
        return 1

    if diff.run2_inserted_count > 0:
        print(f"\n=== VERDICT: PASS (with new discovery) ===")
        print(f"  run2 inserted {diff.run2_inserted_count} events, "
              f"all {len(diff.new_discovery_in_run2)} are new discoveries")
    else:
        print(f"\n=== VERDICT: PASS (stable) ===")

    return 0


if __name__ == "__main__":
    sys.exit(main())
