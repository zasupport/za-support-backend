-- ============================================================
-- Health Check AI — ISP Outage Monitor
-- Database Migration: TimescaleDB + PostgreSQL
-- Run against your existing Health Check database
-- ============================================================

-- -------------------------------------------------------
-- 1. ISP Registry — known SA internet service providers
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS isp_registry (
    isp_id          SERIAL PRIMARY KEY,
    isp_name        VARCHAR(100) NOT NULL UNIQUE,       -- e.g. "Stem", "Afrihost"
    isp_slug        VARCHAR(50) NOT NULL UNIQUE,         -- e.g. "stem", "afrihost"
    status_page_url VARCHAR(500),                        -- official status page if exists
    support_phone   VARCHAR(50),                         -- support line
    support_email   VARCHAR(200),                        -- support email
    region          VARCHAR(50) DEFAULT 'ZA',            -- country code
    check_enabled   BOOLEAN DEFAULT TRUE,                -- actively monitored
    check_interval  INTEGER DEFAULT 300,                 -- seconds between checks (default 5 min)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------------------------------------
-- 2. Client-ISP Mapping — which client uses which ISP
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS client_isp (
    client_isp_id   SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(client_id),
    isp_id          INTEGER NOT NULL REFERENCES isp_registry(isp_id),
    account_ref     VARCHAR(100),                        -- client's ISP account number
    circuit_id      VARCHAR(100),                        -- line/circuit reference
    connection_type VARCHAR(50),                         -- fibre, dsl, lte, wireless
    ip_address      INET,                                -- WAN IP if known
    gateway_ip      INET,                                -- gateway for local ping checks
    site_name       VARCHAR(200),                        -- e.g. "Dr Evan Shoul Practice"
    is_primary      BOOLEAN DEFAULT TRUE,                -- primary vs backup link
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, isp_id, circuit_id)
);

-- -------------------------------------------------------
-- 3. ISP Status Checks — time-series of check results
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS isp_status_checks (
    check_time      TIMESTAMPTZ NOT NULL,
    isp_id          INTEGER NOT NULL REFERENCES isp_registry(isp_id),
    check_method    VARCHAR(30) NOT NULL,                -- 'status_page', 'downdetector', 'ping', 'agent', 'http'
    is_up           BOOLEAN,                             -- TRUE=online, FALSE=down, NULL=unknown
    latency_ms      FLOAT,                               -- response time if applicable
    packet_loss_pct FLOAT,                               -- packet loss if applicable
    status_code     INTEGER,                             -- HTTP status code if applicable
    raw_status      VARCHAR(500),                        -- raw text scraped from status page
    error_message   TEXT,                                -- error details if check failed
    source          VARCHAR(100)                         -- which scraper/agent produced this
);

-- Convert to hypertable for time-series optimisation
SELECT create_hypertable(
    'isp_status_checks', 'check_time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

-- -------------------------------------------------------
-- 4. ISP Outage Events — confirmed outage windows
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS isp_outage_events (
    outage_id       SERIAL PRIMARY KEY,
    isp_id          INTEGER NOT NULL REFERENCES isp_registry(isp_id),
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ,                         -- NULL = still ongoing
    duration_mins   INTEGER GENERATED ALWAYS AS (
                        CASE WHEN ended_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (ended_at - started_at)) / 60
                        ELSE NULL END
                    ) STORED,
    severity        VARCHAR(20) DEFAULT 'unknown',       -- 'degraded', 'partial', 'full'
    detection_method VARCHAR(50),                         -- what triggered detection
    affected_region VARCHAR(100),                         -- geographic area if known
    isp_ref_number  VARCHAR(100),                         -- ISP fault reference
    isp_eta         TIMESTAMPTZ,                          -- ISP estimated resolution
    notes           TEXT,
    auto_detected   BOOLEAN DEFAULT TRUE,                 -- system detected vs manual
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- -------------------------------------------------------
-- 5. Outage-Client Impact — which clients affected
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS outage_client_impact (
    impact_id       SERIAL PRIMARY KEY,
    outage_id       INTEGER NOT NULL REFERENCES isp_outage_events(outage_id),
    client_id       INTEGER NOT NULL REFERENCES clients(client_id),
    client_isp_id   INTEGER REFERENCES client_isp(client_isp_id),
    agent_confirmed BOOLEAN DEFAULT FALSE,               -- Health Check agent confirmed offline
    agent_last_seen TIMESTAMPTZ,                          -- last agent heartbeat
    notified_at     TIMESTAMPTZ,                          -- when client was notified
    notification_ch VARCHAR(30),                          -- 'email', 'whatsapp', 'sms'
    UNIQUE(outage_id, client_id)
);

-- -------------------------------------------------------
-- 6. Agent Connectivity Reports — from Health Check agents
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_connectivity (
    report_time     TIMESTAMPTZ NOT NULL,
    device_id       INTEGER NOT NULL,
    client_id       INTEGER NOT NULL,
    is_online       BOOLEAN NOT NULL,
    wan_ip          INET,
    gateway_ip      INET,
    gateway_ping_ms FLOAT,
    dns_resolves    BOOLEAN,
    latency_ms      FLOAT,
    packet_loss_pct FLOAT
);

SELECT create_hypertable(
    'agent_connectivity', 'report_time',
    if_not_exists => TRUE,
    chunk_time_interval => INTERVAL '1 day'
);

-- -------------------------------------------------------
-- Indexes for performance
-- -------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_isp_checks_isp_time
    ON isp_status_checks (isp_id, check_time DESC);
CREATE INDEX IF NOT EXISTS idx_isp_checks_method
    ON isp_status_checks (check_method, check_time DESC);
CREATE INDEX IF NOT EXISTS idx_outage_events_isp
    ON isp_outage_events (isp_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_outage_events_active
    ON isp_outage_events (isp_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_client_isp_client
    ON client_isp (client_id);
CREATE INDEX IF NOT EXISTS idx_agent_conn_client
    ON agent_connectivity (client_id, report_time DESC);
CREATE INDEX IF NOT EXISTS idx_agent_conn_device
    ON agent_connectivity (device_id, report_time DESC);

-- -------------------------------------------------------
-- Continuous aggregates for dashboards
-- -------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS isp_hourly_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', check_time) AS bucket,
    isp_id,
    check_method,
    COUNT(*)                          AS total_checks,
    COUNT(*) FILTER (WHERE is_up)     AS up_checks,
    COUNT(*) FILTER (WHERE NOT is_up) AS down_checks,
    ROUND(AVG(latency_ms)::numeric, 2)       AS avg_latency_ms,
    ROUND(AVG(packet_loss_pct)::numeric, 2)  AS avg_packet_loss_pct
FROM isp_status_checks
GROUP BY bucket, isp_id, check_method
WITH NO DATA;

-- Refresh policy: update every 15 minutes
SELECT add_continuous_aggregate_policy('isp_hourly_stats',
    start_offset    => INTERVAL '2 hours',
    end_offset      => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists   => TRUE
);

-- Retention: detailed checks for 90 days, aggregates for 2 years
SELECT add_retention_policy('isp_status_checks',
    drop_after => INTERVAL '90 days',
    if_not_exists => TRUE
);
SELECT add_retention_policy('agent_connectivity',
    drop_after => INTERVAL '90 days',
    if_not_exists => TRUE
);

-- -------------------------------------------------------
-- Seed SA ISP registry
-- -------------------------------------------------------
INSERT INTO isp_registry (isp_name, isp_slug, status_page_url, support_phone, support_email, check_interval)
VALUES
    ('Stem',            'stem',       'https://www.stem.co.za',                  NULL, NULL, 300),
    ('X-DSL Networking','x-dsl',      'https://www.x-dsl.co.za',                NULL, NULL, 300),
    ('Afrihost',        'afrihost',   'https://status.afrihost.com',             '011 612 7200', 'support@afrihost.com', 300),
    ('Rain',            'rain',       'https://www.rain.co.za',                  '087 820 7246', NULL, 300),
    ('Vumatel',         'vumatel',    'https://www.vumatel.co.za',               '086 100 8862', NULL, 300),
    ('Openserve',       'openserve',  'https://www.openserve.co.za',             '080 021 0021', NULL, 300),
    ('RSAWEB',          'rsaweb',     'https://status.rsaweb.co.za',             '087 470 0000', 'support@rsaweb.co.za', 300),
    ('Cool Ideas',      'coolideas',  'https://www.coolideas.co.za',             '010 590 0060', NULL, 300),
    ('Webafrica',       'webafrica',  'https://www.webafrica.co.za',             '086 000 9322', NULL, 300),
    ('Herotel',         'herotel',    'https://www.herotel.com',                 '086 001 4376', NULL, 300),
    ('Vodacom',         'vodacom',    'https://www.vodacom.co.za',               '082 111',      NULL, 600),
    ('MTN',             'mtn',        'https://www.mtn.co.za',                   '083 123',      NULL, 600),
    ('Telkom',          'telkom',     'https://www.telkom.co.za',                '10210',        NULL, 300)
ON CONFLICT (isp_slug) DO NOTHING;
