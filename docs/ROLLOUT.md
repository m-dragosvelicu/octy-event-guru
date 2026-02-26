# Production Rollout Checklist

This document is the operational runbook for deploying event-guru to production.
For project overview, API usage, and local development commands see `README.md`.

---

## 1. Prerequisites

Confirm all of the following before starting.

### Infrastructure
- [ ] Supabase project created with the **PostGIS** extension enabled
  (Dashboard > Database > Extensions > postgis)
- [ ] Supabase project URL and service-role key retrieved from
  Dashboard > Project Settings > API
- [ ] A bot/host user account created in Supabase Auth; its UUID noted for
  `EVENT_GURU_HOST_USER_ID`

### API keys
- [ ] `BRAVE_SEARCH_API_KEY` obtained from https://brave.com/search/api/

### Deployment target
- [ ] Docker-capable host (VM, container service, Railway, Fly.io, etc.)
  with port 8000 accessible to GitHub Actions or your trigger mechanism
- [ ] A stable public HTTPS URL for the service (`INGEST_ENDPOINT`)

### Repository secrets (GitHub Actions)
The following secrets must be set under Settings > Secrets and variables > Actions:

| Secret | Description |
|---|---|
| `INGEST_ENDPOINT` | Public base URL of the deployed service, e.g. `https://api.example.com` |
| `INGEST_API_TOKEN` | Shared secret token; must match `INGEST_API_TOKEN` env var in the container |
| `DEFAULT_AREA_ID` | Area slug to ingest, e.g. `bucharest` |
| `ALERT_WEBHOOK_URL` | (Optional) Webhook URL for cron failure notifications. Receives JSON with `workflow`, `run_url`, `timestamp`. If not set, failures are silent beyond GitHub's default email. |

---

## 2. Database Migration

Run `scripts/migrate_production.sql` against your Supabase project exactly once
(it is idempotent so re-running is safe, but not necessary).

### Option A: Supabase SQL editor (recommended for first run)
1. Open Supabase Dashboard > SQL Editor
2. Paste the contents of `scripts/migrate_production.sql`
3. Click Run
4. Verify no errors in the output panel

### Option B: psql
```bash
psql "$DATABASE_URL" -f scripts/migrate_production.sql
```

Where `DATABASE_URL` is the direct connection string from
Dashboard > Database > Connection string (use the `psql` format).

### What the migration creates
- Extensions: `postgis`, `uuid-ossp`
- Tables: `activities`, `events`, `ingest_runs`, `alerts`, `source_scorecards`
- Indexes: GIST on `location_point`, B-tree on `start_time`, `h3_index`
- Unique index: `events_external_unique` (deduplication constraint)
- Trigger: `trg_events_set_location_point` (auto-derives geometry from lat/lng)
- RPC functions: `find_events_nearby`, `count_events_nearby`,
  `find_events_in_bbox`, `count_events_in_bbox`, `find_map_pins`,
  `update_event_location_point`
- Grants: `service_role` gets full access; `anon` gets SELECT
- Seed data: 11 activity slugs

### Migration does NOT include
- `truncate_test_tables()` (test-only, intentionally excluded)
- Test roles (`authenticator` with hardcoded password)
- Any data migration (this is a greenfield schema)

---

## 3. Environment Variable Setup

Copy `.env.example` to `.env` and fill in all values before starting the container.

```bash
cp .env.example .env
```

Required variables:

| Variable | Required | Notes |
|---|---|---|
| `BRAVE_SEARCH_API_KEY` | Yes | Web search connector |
| `SUPABASE_URL` | Yes | e.g. `https://xyzxyz.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Full DB access; keep secret |
| `EVENT_GURU_HOST_USER_ID` | Yes | UUID of bot user in Supabase Auth |
| `INGEST_API_TOKEN` | Yes | Bearer token for POST /v1/ingest/run |
| `DEFAULT_AREA_ID` | Yes | e.g. `bucharest` |
| `MAPBOX_ACCESS_TOKEN` | No | Unused -- geocoding fallback is disabled; events without source coords are dropped |
| `MAPBOX_PERMANENT` | No | Unused |
| `MAPBOX_COUNTRY_BIAS` | No | Unused |
| `MAPBOX_BBOX_BIAS` | No | Unused |
| `INGEST_RUN_REPORT_PATH` | Optional | Defaults to `ingest_runs.json` |

Build and start the container:

```bash
docker build -t event-guru:latest .
docker run --env-file .env -p 8000:8000 event-guru:latest
```

Confirm the service is up:

```bash
curl http://localhost:8000/health
```

Expected response: `{"status":"ok"}` (or equivalent 200).

---

## 4. First-Run Verification

Run the validation script to confirm end-to-end pipeline health before activating
the cron.

```bash
# Requires SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, BRAVE_SEARCH_API_KEY in env
python scripts/validate_live.py --area-id bucharest
```

The script performs:
1. Two consecutive ingest runs against the live Supabase DB
2. A run-diff check to confirm deduplication is working
3. A `find_events_nearby` RPC query
4. Coverage checks: coords, provider, and event_id must all be 100%

Expected terminal output ends with one of:
- `VERDICT: PASS (stable)` - dedupe is clean, no new events on run 2
- `VERDICT: PASS (with new discovery)` - run 2 found genuinely new events

If you see `VERDICT: FAIL`, address the listed blockers before proceeding.

Dry-run option (no DB writes, useful for smoke-testing credentials):

```bash
python scripts/validate_live.py --area-id bucharest --dry-run
```

---

## 5. Cron Job Activation

The cron workflow is defined in `.github/workflows/ingest-cron.yml` and triggers
`POST /v1/ingest/run` hourly via `curl`.

Steps:
1. Confirm the three GitHub Actions secrets from section 1 are set
2. Navigate to Actions > Ingest Cron > Run workflow to trigger a manual test run
3. Inspect the run log and confirm the curl exits 0 (HTTP 200 from the service)
4. The scheduled cron (`0 * * * *`) will fire automatically from that point on

Note: the workflow sends a webhook notification on failure if `ALERT_WEBHOOK_URL`
is configured. If not set, failures are silent beyond GitHub's default email.

---

## 6. Monitoring and Alerting

There is no dedicated monitoring stack at this time. The following is what exists
and what is missing.

### What exists
- `GET /health` endpoint returns HTTP 200 when the service process is up
- `ingest_runs` table records every run with `status`, `summary`, `errors`,
  and `source_breakdown` columns - query this for post-hoc diagnosis
- `alerts` table is schema-ready for application-level alerts but no alert
  dispatch mechanism is wired up yet
- `source_scorecards` table is populated per provider+area on each ingest run
  with health status and metrics (upserted via unique index)

### Minimum viable monitoring (manual setup required)
- **Uptime check**: configure an external ping (UptimeRobot free tier, Better
  Uptime, or equivalent) against `GET /health` with a 2-minute interval
- **Cron failure notification**: configured via `ALERT_WEBHOOK_URL` secret in
  the ingest-cron workflow (fires on failure, gracefully skips if unset)
- **DB query for stale runs** (run manually or via cron):
  ```sql
  SELECT run_id, area_id, started_at, status, summary
  FROM ingest_runs
  ORDER BY started_at DESC
  LIMIT 10;
  ```

### Known gaps
- No Prometheus/Grafana metrics exported
- `alerts` table is not consumed by any dispatch logic beyond DB storage

---

## 7. Rollback Procedure

### Application rollback
The service is stateless. Roll back by redeploying the previous Docker image tag:

```bash
docker run --env-file .env -p 8000:8000 event-guru:<previous-tag>
```

If using a container platform (Railway, Fly.io, etc.), use its deployment history
UI or CLI to revert to the last stable release.

### Database rollback
There is no automated schema rollback. The migration is additive only (all
`CREATE IF NOT EXISTS`), so rolling back the application image does not require
a schema rollback in normal cases.

If a schema change must be reverted manually:
1. Disable the cron first (disable the GitHub Actions schedule or revoke
   `INGEST_API_TOKEN`)
2. Run the corrective SQL in the Supabase SQL editor
3. Redeploy the application
4. Re-run `python scripts/validate_live.py` to confirm recovery

### Disabling ingestion immediately
Set `INGEST_API_TOKEN` to an invalid value in the container env and redeploy.
All subsequent POST /v1/ingest/run calls will return 401 without touching the DB.

Alternatively, disable the GitHub Actions schedule:
- Go to Actions > Ingest Cron > ... (top-right) > Disable workflow
