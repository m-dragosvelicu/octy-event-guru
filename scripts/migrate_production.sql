-- migrate_production.sql
-- Version: 1.0.0
-- Date: 2026-02-25
--
-- Production migration for event-guru on Supabase (PostGIS-enabled project).
-- Safe to run against an existing Supabase instance: all statements are idempotent.
-- Does NOT contain test-only artifacts (no truncate helpers, no test roles,
-- no hardcoded test credentials).
--
-- Run via Supabase SQL editor or psql:
--   psql "$DATABASE_URL" -f scripts/migrate_production.sql
-- ===================================================================


-- ===================================================================
-- Extensions
-- ===================================================================
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ===================================================================
-- Tables
-- ===================================================================

CREATE TABLE IF NOT EXISTS activities (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title                   TEXT NOT NULL,
    description             TEXT,
    activity_id             UUID REFERENCES activities(id),
    location_name           TEXT,
    location_lat            DOUBLE PRECISION,
    location_lng            DOUBLE PRECISION,
    location_point          GEOMETRY(Point, 4326),
    start_time              TIMESTAMPTZ NOT NULL,
    end_time                TIMESTAMPTZ,
    max_participants        INTEGER DEFAULT 20,
    presigned_count         INTEGER DEFAULT 0,
    skill_level             TEXT DEFAULT 'beginner',
    status                  TEXT DEFAULT 'upcoming',
    host_id                 UUID,
    external_provider       TEXT,
    external_event_id       TEXT,
    external_source_url     TEXT,
    external_confidence     NUMERIC,
    timezone                TEXT,
    start_time_local        TEXT,
    end_time_local          TEXT,
    date_only               BOOLEAN DEFAULT FALSE,
    h3_index                VARCHAR(15),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id              TEXT PRIMARY KEY,
    area_id             TEXT NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    duration_seconds    DOUBLE PRECISION,
    status              TEXT NOT NULL DEFAULT 'running',
    summary             JSONB NOT NULL DEFAULT '{}'::jsonb,
    errors              JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_breakdown    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS alerts (
    id                  TEXT PRIMARY KEY,
    severity            TEXT NOT NULL,
    condition           TEXT NOT NULL,
    message             TEXT NOT NULL,
    current_value       DOUBLE PRECISION,
    threshold           DOUBLE PRECISION,
    provider            TEXT,
    area_id             TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS source_scorecards (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider            TEXT NOT NULL,
    area_id             TEXT,
    health_status       TEXT NOT NULL DEFAULT 'healthy',
    last_checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb
);


-- ===================================================================
-- Unique constraints
-- ===================================================================

-- source_scorecards: one row per provider+area for upsert
CREATE UNIQUE INDEX IF NOT EXISTS source_scorecards_provider_area
    ON source_scorecards (provider, area_id);

-- events: deduplication constraint
CREATE UNIQUE INDEX IF NOT EXISTS events_external_unique
    ON events (external_provider, external_event_id)
    WHERE external_provider IS NOT NULL
      AND external_event_id IS NOT NULL;


-- ===================================================================
-- Indexes
-- ===================================================================
CREATE INDEX IF NOT EXISTS idx_events_location_point
    ON events USING GIST(location_point);

CREATE INDEX IF NOT EXISTS idx_events_start_time
    ON events(start_time);

CREATE INDEX IF NOT EXISTS idx_events_start_time_point
    ON events(start_time)
    WHERE location_point IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_h3_index
    ON events(h3_index);


-- ===================================================================
-- Trigger: auto-populate location_point from lat/lng
-- ===================================================================
CREATE OR REPLACE FUNCTION trg_events_set_location_point()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.location_lat IS NOT NULL AND NEW.location_lng IS NOT NULL THEN
        NEW.location_point := ST_SetSRID(
            ST_MakePoint(NEW.location_lng, NEW.location_lat), 4326
        );
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_events_set_location_point ON events;
CREATE TRIGGER trg_events_set_location_point
    BEFORE INSERT OR UPDATE ON events
    FOR EACH ROW
    EXECUTE FUNCTION trg_events_set_location_point();


-- ===================================================================
-- RPC Functions
-- ===================================================================

-- find_events_nearby: proximity search with time window
CREATE OR REPLACE FUNCTION find_events_nearby(
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION,
    p_radius_meters DOUBLE PRECISION,
    p_start_date TEXT,
    p_end_date TEXT,
    p_limit INTEGER DEFAULT 20,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE(
    id UUID,
    title TEXT,
    description TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    timezone TEXT,
    start_time_local TEXT,
    end_time_local TEXT,
    location_name TEXT,
    location_lat DOUBLE PRECISION,
    location_lng DOUBLE PRECISION,
    external_provider TEXT,
    external_event_id TEXT,
    external_source_url TEXT,
    external_confidence NUMERIC,
    activity_id UUID,
    status TEXT,
    date_only BOOLEAN,
    distance_km DOUBLE PRECISION
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.timezone,
        e.start_time_local,
        e.end_time_local,
        e.location_name,
        e.location_lat,
        e.location_lng,
        e.external_provider,
        e.external_event_id,
        e.external_source_url,
        e.external_confidence,
        e.activity_id,
        e.status,
        e.date_only,
        ST_Distance(
            e.location_point::geography,
            ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::geography
        ) / 1000.0 AS distance_km
    FROM events e
    WHERE e.location_point IS NOT NULL
        AND ST_DWithin(
            e.location_point::geography,
            ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::geography,
            p_radius_meters
        )
        AND e.start_time >= p_start_date::timestamptz
        AND e.start_time <= p_end_date::timestamptz
    ORDER BY distance_km ASC, e.start_time ASC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;

-- count_events_nearby: count for pagination
CREATE OR REPLACE FUNCTION count_events_nearby(
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION,
    p_radius_meters DOUBLE PRECISION,
    p_start_date TEXT,
    p_end_date TEXT
)
RETURNS TABLE(count BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT COUNT(*)::BIGINT
    FROM events e
    WHERE e.location_point IS NOT NULL
        AND ST_DWithin(
            e.location_point::geography,
            ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::geography,
            p_radius_meters
        )
        AND e.start_time >= p_start_date::timestamptz
        AND e.start_time <= p_end_date::timestamptz;
END;
$$;

-- find_events_in_bbox: bounding box search
CREATE OR REPLACE FUNCTION find_events_in_bbox(
    p_min_lng DOUBLE PRECISION,
    p_min_lat DOUBLE PRECISION,
    p_max_lng DOUBLE PRECISION,
    p_max_lat DOUBLE PRECISION,
    p_start_date TEXT,
    p_end_date TEXT,
    p_limit INTEGER DEFAULT 20,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE(
    id UUID,
    title TEXT,
    description TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    location_name TEXT,
    location_lat DOUBLE PRECISION,
    location_lng DOUBLE PRECISION,
    external_source_url TEXT,
    activity_id UUID,
    status TEXT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id,
        e.title,
        e.description,
        e.start_time,
        e.end_time,
        e.location_name,
        e.location_lat,
        e.location_lng,
        e.external_source_url,
        e.activity_id,
        e.status
    FROM events e
    WHERE e.location_point IS NOT NULL
        AND ST_Within(
            e.location_point,
            ST_MakeEnvelope(p_min_lng, p_min_lat, p_max_lng, p_max_lat, 4326)
        )
        AND e.start_time >= p_start_date::timestamptz
        AND e.start_time <= p_end_date::timestamptz
    ORDER BY e.start_time ASC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;

-- count_events_in_bbox: count for pagination
CREATE OR REPLACE FUNCTION count_events_in_bbox(
    p_min_lng DOUBLE PRECISION,
    p_min_lat DOUBLE PRECISION,
    p_max_lng DOUBLE PRECISION,
    p_max_lat DOUBLE PRECISION,
    p_start_date TEXT,
    p_end_date TEXT
)
RETURNS TABLE(count BIGINT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT COUNT(*)::BIGINT
    FROM events e
    WHERE e.location_point IS NOT NULL
        AND ST_Within(
            e.location_point,
            ST_MakeEnvelope(p_min_lng, p_min_lat, p_max_lng, p_max_lat, 4326)
        )
        AND e.start_time >= p_start_date::timestamptz
        AND e.start_time <= p_end_date::timestamptz;
END;
$$;

-- find_map_pins: lightweight markers for map rendering
CREATE OR REPLACE FUNCTION find_map_pins(
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION,
    p_radius_meters DOUBLE PRECISION,
    p_start_date TEXT,
    p_end_date TEXT,
    p_limit INTEGER DEFAULT 200
)
RETURNS TABLE(
    id UUID,
    location_lat DOUBLE PRECISION,
    location_lng DOUBLE PRECISION,
    title TEXT,
    start_time TIMESTAMPTZ
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id,
        e.location_lat,
        e.location_lng,
        e.title,
        e.start_time
    FROM events e
    WHERE e.location_point IS NOT NULL
        AND ST_DWithin(
            e.location_point::geography,
            ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)::geography,
            p_radius_meters
        )
        AND e.start_time >= p_start_date::timestamptz
        AND e.start_time <= p_end_date::timestamptz
    ORDER BY e.start_time ASC
    LIMIT p_limit;
END;
$$;

-- update_event_location_point: manual point update
CREATE OR REPLACE FUNCTION update_event_location_point(
    p_event_id UUID,
    p_lat DOUBLE PRECISION,
    p_lng DOUBLE PRECISION
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE events
    SET location_point = ST_SetSRID(ST_MakePoint(p_lng, p_lat), 4326)
    WHERE id = p_event_id;
END;
$$;


-- ===================================================================
-- Grants
-- NOTE: In Supabase, the anon and service_role roles already exist.
-- These grants are safe to re-run.
-- ===================================================================
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon;


-- ===================================================================
-- Seed data: activity slugs
-- ON CONFLICT means this is safe to re-run against a populated DB.
-- ===================================================================
INSERT INTO activities (slug, name) VALUES
    ('running',  'Running'),
    ('cycling',  'Cycling'),
    ('yoga',     'Yoga'),
    ('hiking',   'Hiking'),
    ('swimming', 'Swimming'),
    ('music',    'Music'),
    ('sports',   'Sports'),
    ('theatre',  'Theatre'),
    ('comedy',   'Comedy'),
    ('festival', 'Festival'),
    ('events',   'Events')
ON CONFLICT (slug) DO NOTHING;
