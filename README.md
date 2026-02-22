# event-guru

FastAPI service that ingests external event listings and writes normalized events to Supabase.

## Stack

- FastAPI app with `/health` and `/v1/ingest/*` routes
- Source crawling with `requests` + `tenacity`
- Event extraction via JSON-LD (`extruct`) with HTML fallback (`BeautifulSoup`)
- Date normalization with `dateparser`
- Geocoding via Mapbox forward geocoding API
- Deduplication using `(external_provider, external_event_id)`
- Supabase writes using service-role key

## Project layout

```text
app/
  main.py
  api/routes/{health.py, ingest.py}
  core/{config.py, logging.py}
  domain/models.py
  sources/{registry.yaml, base.py, adapters/*}
  extract/{jsonld.py, html_fallback.py, normalize.py}
  geocode/{mapbox_client.py, scoring.py}
  sink/{supabase_writer.py, dedupe.py}
  jobs/ingest_job.py
tests/
```

## Environment

Copy `.env.example` to `.env` and set:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `EVENT_GURU_HOST_USER_ID`
- `MAPBOX_ACCESS_TOKEN`
- `MAPBOX_PERMANENT=true`
- `INGEST_API_TOKEN`
- `DEFAULT_AREA_ID`

## Supabase dedupe extension

```sql
alter table public.events
  add column if not exists external_provider text,
  add column if not exists external_event_id text,
  add column if not exists external_source_url text,
  add column if not exists external_confidence numeric;

create unique index if not exists events_external_unique
on public.events (external_provider, external_event_id)
where external_provider is not null and external_event_id is not null;
```

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

### Example run

```bash
curl -X POST http://127.0.0.1:8000/v1/ingest/run \
  -H "Authorization: Bearer $INGEST_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"area_id":"default-city","dry_run":true,"max_events":50}'
```

## Scheduling

Use GitHub Actions cron (hourly) to call `POST /v1/ingest/run` with `INGEST_API_TOKEN`.

## Notes

- Keep `MAPBOX_PERMANENT=true` when storing coordinates.
- Create a bot host account in Supabase Auth and set its UUID as `EVENT_GURU_HOST_USER_ID`.
- Run summaries are appended to `ingest_runs.json`.
