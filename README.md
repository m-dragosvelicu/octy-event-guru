# event-guru

FastAPI service that ingests external event listings and writes normalized events to Supabase.

## Stack

- FastAPI app with `/health`, `/v1/ingest/*`, and `/v1/events/*` routes
- **Ticketmaster Discovery API** connector for real event data
- Source crawling with `requests` + `tenacity`
- Event extraction via JSON-LD (`extruct`) with HTML fallback (`BeautifulSoup`)
- Date normalization with `dateparser`
- Geocoding via Mapbox forward geocoding API (fallback for events without source coords)
- Deduplication using `(external_provider, external_event_id)`
- Supabase writes using service-role key
- PostGIS spatial queries via RPC functions

## Project layout

```text
app/
  main.py
  api/routes/{health.py, ingest.py, events.py}
  core/{config.py, logging.py}
  domain/models.py
  sources/{registry.yaml, areas.yaml, base.py, adapters/*, connectors/ticketmaster.py}
  extract/{jsonld.py, html_fallback.py, normalize.py}
  geocode/{mapbox_client.py, scoring.py}
  sink/{supabase_writer.py, dedupe.py}
  jobs/ingest_job.py
scripts/
  validate_live.py
  init_test_db.sql
```

## Environment

Copy `.env.example` to `.env` and set:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `EVENT_GURU_HOST_USER_ID`
- `MAPBOX_ACCESS_TOKEN`
- `MAPBOX_PERMANENT=true`
- `INGEST_API_TOKEN`
- `DEFAULT_AREA_ID=bucharest`
- `TICKETMASTER_API_KEY` (get from https://developer.ticketmaster.com/)
- `MAPBOX_COUNTRY_BIAS=ro`

## Supabase schema additions

Run these on your Supabase DB if not already present:

```sql
-- Provenance columns
alter table public.events
  add column if not exists external_provider text,
  add column if not exists external_event_id text,
  add column if not exists external_source_url text,
  add column if not exists external_confidence numeric;

-- Timezone columns
alter table public.events
  add column if not exists timezone text,
  add column if not exists start_time_local text,
  add column if not exists end_time_local text;

-- Dedupe index
create unique index if not exists events_external_unique
on public.events (external_provider, external_event_id)
where external_provider is not null and external_event_id is not null;

-- Activity seeds for Ticketmaster event types
insert into activities (slug, name) values
    ('music', 'Music'),
    ('sports', 'Sports'),
    ('theatre', 'Theatre'),
    ('comedy', 'Comedy'),
    ('festival', 'Festival'),
    ('events', 'Events')
on conflict (slug) do nothing;
```

Update the `find_events_nearby` RPC to return provenance fields (see `scripts/init_test_db.sql` for the full definition).

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
  providers:
    - ticketmaster
```

## Scheduling

Use GitHub Actions cron (hourly) to call `POST /v1/ingest/run` with `INGEST_API_TOKEN`.

## Notes

- Keep `MAPBOX_PERMANENT=true` when storing coordinates.
- Create a bot host account in Supabase Auth and set its UUID as `EVENT_GURU_HOST_USER_ID`.
- Run summaries are appended to `ingest_runs.json`.
- Ticketmaster events come with venue coordinates; Mapbox geocoding is only used as fallback.
- All events store UTC time for filtering + timezone/local time for display.
