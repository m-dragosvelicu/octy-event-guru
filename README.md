# event-guru

FastAPI service that ingests external event listings and writes normalized events to Supabase.

## Stack

- FastAPI app with `/health`, `/v1/ingest/*`, and `/v1/events/*` routes
- **Brave Search** web crawler for event discovery
- Source crawling with `requests` + `tenacity`
- Event extraction via JSON-LD (`extruct`) with HTML fallback (`BeautifulSoup`)
- Date normalization with `dateparser`, `date_only` contract for time-less events
- Content-based fingerprint deduplication + DB-level `(external_provider, external_event_id)` uniqueness
- Supabase writes using service-role key
- PostGIS spatial queries via RPC functions
- Run-diff analysis for dedupe leak detection
- Health check alerts (zero-insert, single-provider, high-coord-drop)

## Project layout

```text
app/
  main.py
  api/routes/{health.py, ingest.py, events.py}
  core/{config.py, logging.py}
  domain/{models.py, run_diff.py}
  sources/{registry.yaml, areas.yaml, base.py, adapters/*, connectors/brave_search.py}
  extract/{jsonld.py, html_fallback.py, normalize.py}
  geocode/{mapbox_client.py, scoring.py}
  sink/{supabase_writer.py, dedupe.py}
  jobs/{ingest_job.py, ingest_pipeline.py}
  observability/{health_checks.py}
scripts/
  validate_live.py
  init_test_db.sql
  migrate_production.sql
docs/
  ROLLOUT.md
```

## Environment

Copy `.env.example` to `.env` and set:

- `BRAVE_SEARCH_API_KEY` (get from https://brave.com/search/api/)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `EVENT_GURU_HOST_USER_ID`
- `INGEST_API_TOKEN`
- `DEFAULT_AREA_ID=bucharest`

## Database setup

For production deployment, run `scripts/migrate_production.sql` against your Supabase instance.
See `docs/ROLLOUT.md` for the full deployment checklist.

For local integration testing, the schema is applied automatically via `docker-compose.test.yml`
using `scripts/init_test_db.sql`.

## Install and run

```bash
uv sync
uv run uvicorn app.main:app --reload --reload-dir app
```

## API

- `GET /health`
- `GET /v1/ingest/health`
- `POST /v1/ingest/run` (requires `Authorization: Bearer <INGEST_API_TOKEN>`)
- `POST /v1/ingest/preview` (token-protected, forced dry-run)
- `GET /v1/events/nearby` (public, accepts `lat`, `lng`, `radius_km`, `days`, `area_id`)

## Live ingestion for Bucharest

### 1. Run ingestion

```bash
# Dry-run first (no DB writes)
curl -X POST http://127.0.0.1:8000/v1/ingest/run \
  -H "Authorization: Bearer $INGEST_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"area_id":"bucharest","dry_run":true}'

# Real run
curl -X POST http://127.0.0.1:8000/v1/ingest/run \
  -H "Authorization: Bearer $INGEST_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"area_id":"bucharest"}'
```

### 2. Query nearby events

```bash
# Using area defaults (Bucharest center, 30km, 7 days)
curl "http://127.0.0.1:8000/v1/events/nearby?area_id=bucharest"

# Custom coordinates
curl "http://127.0.0.1:8000/v1/events/nearby?lat=44.4268&lng=26.1025&radius_km=30&days=7"
```

### 3. Validation script

```bash
# Full validation: ingest + dedupe re-run + nearby query
python scripts/validate_live.py --area-id bucharest

# Dry-run only (no DB writes)
python scripts/validate_live.py --area-id bucharest --dry-run

# Query only (skip ingestion)
python scripts/validate_live.py --area-id bucharest --query-only
```

## Testing

```bash
# Unit tests (no external deps)
make test-unit

# Integration tests (requires docker stack)
make stack-up
make test-integration
make stack-down

# All tests
make test-all

# Live freshness test (manual, pre-release)
BRAVE_SEARCH_API_KEY=... pytest tests/integration/test_live_freshness.py -q
```

## Area configuration

Areas are defined in `app/sources/areas.yaml`:

```yaml
- area_id: bucharest
  lat: 44.4268
  lng: 26.1025
  radius_km: 30
  timezone: Europe/Bucharest
  horizon_days: 7
  default_activity_slug: events
  per_domain_cap: 50
  provider_diversity_warn_pct: 80
```

## Scheduling

Use GitHub Actions cron (hourly) to call `POST /v1/ingest/run` with `INGEST_API_TOKEN`.

## Notes

- Events without source coordinates are dropped (no geocoding fallback).
- Create a bot host account in Supabase Auth and set its UUID as `EVENT_GURU_HOST_USER_ID`.
- Run summaries are persisted to `ingest_runs` DB table and local `ingest_runs.json`.
- All events store UTC time for filtering + timezone/local time for display.
- Events with only a date (no time) are flagged `date_only=true` in the API response.
