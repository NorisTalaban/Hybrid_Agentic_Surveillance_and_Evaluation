-- ============================================================
-- CRISIS MONITOR — SUPABASE SCHEMA v2.3
-- Run this in Supabase SQL Editor to create all tables
--
-- Includes:
--   - schema.sql v2.1 (original)
--   - cm_agent_runs (ex agent_runs_migration.sql)
--   - cm_supervisor_log (new)
--   - FIX: classified_events.crisis_id FK added
--   - FIX: composite index connections(from_country, to_country)
--   - FIX: crises.source CHECK updated with 'manual'
--   - FIX: key_timeline.event_date -> TIMESTAMPTZ
--   - FIX: cm_collection_log.cost_estimate -> NUMERIC(10,6)
-- FIX: crisis_events.source CHECK updated with 'matcher'
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────
-- DOMAIN 1: RAW DATA
-- ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS raw_articles (
    id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    gnews_id      TEXT        UNIQUE,
    title         TEXT,
    description   TEXT,
    content       TEXT,
    url           TEXT,
    image_url     TEXT,
    source_name   TEXT,
    source_url    TEXT,
    published_at  TIMESTAMPTZ,
    collected_at  TIMESTAMPTZ DEFAULT NOW(),
    query_used    TEXT,
    status        TEXT        DEFAULT 'new'
                              CHECK (status IN ('new','classified','filtered','validation_failed'))
);

CREATE TABLE IF NOT EXISTS cm_collection_log (
    id              SERIAL        PRIMARY KEY,
    run_type        TEXT          CHECK (run_type IN ('bootstrap','enricher','scanner','verify')),
    collected_at    TIMESTAMPTZ   DEFAULT NOW(),
    articles_count  INT           DEFAULT 0,
    api_calls_used  INT           DEFAULT 0,
    cost_estimate   NUMERIC(10,6) DEFAULT 0.0   -- FIX: was FLOAT, standardized to NUMERIC
);

-- ─────────────────────────────────────────────────
-- DOMAIN 2: PROCESSED DATA
-- ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS classified_events (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id      UUID        REFERENCES raw_articles(id),
    crisis_id       UUID        REFERENCES crises(id) ON DELETE SET NULL,  -- FIX: FK added
    title_clean     TEXT,
    summary         TEXT,
    severity        INT         CHECK (severity BETWEEN 1 AND 10),
    severity_reason TEXT,
    event_type      TEXT        CHECK (event_type IN ('conflict','disaster','economic','political','health')),
    sub_type        TEXT,
    countries_inv   JSONB,      -- [{name, code, role}]
    event_location  JSONB,      -- {name, type, country_code}
    primary_country TEXT,
    keywords        TEXT[],
    media_attention TEXT        CHECK (media_attention IN ('high','medium','low')),
    real_impact     TEXT        CHECK (real_impact IN ('high','medium','low')),
    published_at    TIMESTAMPTZ,
    classified_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crises (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT        NOT NULL,
    type            TEXT        CHECK (type IN ('conflict','disaster','economic','political','health')),
    status          TEXT        DEFAULT 'active'
                                CHECK (status IN ('active','escalating','de_escalating','stable','resolved')),
    severity        INT         CHECK (severity BETWEEN 1 AND 10),
    severity_peak   INT         CHECK (severity_peak BETWEEN 1 AND 10),
    countries       TEXT[],
    primary_country TEXT,
    lat             FLOAT,
    lng             FLOAT,
    event_count     INT         DEFAULT 0,
    source          TEXT        CHECK (source IN ('scanner','enricher','manual')),  -- FIX: added 'manual'
    first_event_at  TIMESTAMPTZ,
    last_event_at   TIMESTAMPTZ,
    last_updated    TIMESTAMPTZ DEFAULT NOW(),
    last_verified   TIMESTAMPTZ,
    media_gap       BOOLEAN     DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    summary         TEXT
);

CREATE TABLE IF NOT EXISTS crisis_events (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    crisis_id       UUID        REFERENCES crises(id) ON DELETE CASCADE,
    event_id        UUID        REFERENCES classified_events(id),  -- NULL for synthetic
    event_date      TIMESTAMPTZ,
    severity_at     INT         CHECK (severity_at BETWEEN 1 AND 10),
    status_at       TEXT,
    is_escalation   BOOLEAN     DEFAULT FALSE,
    source          TEXT        CHECK (source IN ('news','scanner','verifier','matcher')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS connections (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    crisis_id       UUID        REFERENCES crises(id) ON DELETE CASCADE,
    from_country    TEXT        NOT NULL,
    to_country      TEXT        NOT NULL,
    relation_type   TEXT        CHECK (relation_type IN (
                                    'military_attack','sanction','trade_cut','aid',
                                    'alliance','disruption','refugee_flow','diplomatic_break'
                                )),
    strength        INT         CHECK (strength BETWEEN 1 AND 10),
    direction       TEXT        CHECK (direction IN ('unidirectional','bidirectional')),
    description     TEXT,
    active          BOOLEAN     DEFAULT TRUE,
    first_seen      TIMESTAMPTZ DEFAULT NOW(),
    last_seen       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS analyses (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    crisis_id       UUID        REFERENCES crises(id) ON DELETE CASCADE,
    analysis_text   TEXT,
    evolutions      JSONB,      -- [{scenario, probability, description}]
    precedents      JSONB,      -- [{event, year, similarity}]
    key_actors      TEXT[],
    watch_list      TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS key_timeline (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    crisis_id       UUID        REFERENCES crises(id) ON DELETE CASCADE,
    event_date      TIMESTAMPTZ,                -- FIX: was DATE, standardized to TIMESTAMPTZ
    title           TEXT,
    significance    TEXT,
    severity_impact TEXT,                       -- e.g. "→ 9"
    source          TEXT        CHECK (source IN ('analyst','scanner','manual')),
    order_index     INT         DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────
-- DOMAIN 3: SYSTEM
-- ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS country_coords (
    code    TEXT PRIMARY KEY,   -- ISO 3166-1 alpha-2
    name    TEXT,
    lat     FLOAT,
    lng     FLOAT,
    region  TEXT
);

CREATE TABLE IF NOT EXISTS verification_log (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    crisis_id       UUID        REFERENCES crises(id),
    status_before   TEXT,
    status_after    TEXT,
    severity_before INT,
    severity_after  INT,
    result          TEXT        CHECK (result IN (
                                    'still_active','resolved','escalated',
                                    'de_escalated','insufficient_data'
                                )),
    evidence        TEXT,
    sources         TEXT[],
    media_gap       BOOLEAN     DEFAULT FALSE,
    verified_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS validation_errors (
    id          SERIAL      PRIMARY KEY,
    validator   TEXT        CHECK (validator IN ('validator_a','validator_b','validator_c')),
    entity_type TEXT,
    entity_id   UUID,
    check_name  TEXT,
    expected    TEXT,
    actual      TEXT,
    severity    TEXT        CHECK (severity IN ('hard_fail','soft_fail')),
    resolved    BOOLEAN     DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────
-- DOMAIN 4: PIPELINE MONITORING
-- ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cm_agent_runs (
    id            UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    agent         TEXT          NOT NULL,
                                -- 'collector'|'classifier'|'matcher'|'connector'
                                -- |'analyst'|'verifier'|'supervisor'
    run_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    status        TEXT          NOT NULL CHECK (status IN ('success','error','skipped')),
    duration_ms   INT,
    input_count   INT           DEFAULT 0,
    output_count  INT           DEFAULT 0,
    cost_usd      NUMERIC(10,6) DEFAULT 0,
    input_tokens  INT           DEFAULT 0,
    output_tokens INT           DEFAULT 0,
    error_msg     TEXT,
    meta          JSONB         DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cm_supervisor_log (
    id                    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    run_at                TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    overall_health        TEXT          CHECK (overall_health IN ('stable','degrading','critical','unknown')),
    summary               TEXT,
    pipeline_stats        JSONB         DEFAULT '{}',   -- per-agent scores, metrics, verdicts
    match_issues          JSONB         DEFAULT '[]',
    resolution_candidates JSONB         DEFAULT '[]',
    country_issues        JSONB         DEFAULT '[]',
    anomalies             JSONB         DEFAULT '[]'
);

-- ─────────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────────

-- Crises
CREATE INDEX IF NOT EXISTS idx_crises_status        ON crises(status);
CREATE INDEX IF NOT EXISTS idx_crises_severity      ON crises(severity DESC);
CREATE INDEX IF NOT EXISTS idx_crises_last_verified ON crises(last_verified);

-- Crisis events
CREATE INDEX IF NOT EXISTS idx_crisis_events_crisis ON crisis_events(crisis_id);
CREATE INDEX IF NOT EXISTS idx_crisis_events_date   ON crisis_events(event_date DESC);

-- Connections
CREATE INDEX IF NOT EXISTS idx_connections_crisis   ON connections(crisis_id);
CREATE INDEX IF NOT EXISTS idx_connections_active   ON connections(active);
CREATE INDEX IF NOT EXISTS idx_connections_countries ON connections(from_country, to_country);  -- FIX: added

-- Classified events
CREATE INDEX IF NOT EXISTS idx_classified_crisis    ON classified_events(crisis_id);
CREATE INDEX IF NOT EXISTS idx_classified_article   ON classified_events(article_id);

-- Raw articles
CREATE INDEX IF NOT EXISTS idx_raw_status           ON raw_articles(status);

-- Key timeline
CREATE INDEX IF NOT EXISTS idx_key_timeline_crisis  ON key_timeline(crisis_id, order_index);

-- Validation
CREATE INDEX IF NOT EXISTS idx_validation_resolved  ON validation_errors(resolved);

-- Pipeline monitoring
CREATE INDEX IF NOT EXISTS idx_cm_agent_runs_agent  ON cm_agent_runs(agent, run_at DESC);
CREATE INDEX IF NOT EXISTS idx_cm_agent_runs_run_at ON cm_agent_runs(run_at DESC);
CREATE INDEX IF NOT EXISTS idx_cm_supervisor_run_at ON cm_supervisor_log(run_at DESC);

-- ─────────────────────────────────────────────────
-- REALTIME (enable for frontend subscriptions)
-- ─────────────────────────────────────────────────

-- Run these in Supabase Dashboard → Database → Replication:
-- ALTER PUBLICATION supabase_realtime ADD TABLE crises;
-- ALTER PUBLICATION supabase_realtime ADD TABLE connections;
-- ALTER PUBLICATION supabase_realtime ADD TABLE crisis_events;

-- ─────────────────────────────────────────────────
-- ROW LEVEL SECURITY
-- ─────────────────────────────────────────────────

-- Public read-only (frontend)
ALTER TABLE crises          ENABLE ROW LEVEL SECURITY;
ALTER TABLE crisis_events   ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections     ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses        ENABLE ROW LEVEL SECURITY;
ALTER TABLE key_timeline    ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_coords  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public read" ON crises         FOR SELECT USING (true);
CREATE POLICY "Public read" ON crisis_events  FOR SELECT USING (true);
CREATE POLICY "Public read" ON connections    FOR SELECT USING (true);
CREATE POLICY "Public read" ON analyses       FOR SELECT USING (true);
CREATE POLICY "Public read" ON key_timeline   FOR SELECT USING (true);
CREATE POLICY "Public read" ON country_coords FOR SELECT USING (true);

-- Pipeline monitoring: backend only (no public read)
-- cm_agent_runs, cm_supervisor_log, cm_collection_log, validation_errors
-- no public policy — accessible only via service_role key
