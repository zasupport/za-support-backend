-- Migration 016: CyberShield — network security service tables
-- Idempotent (safe to re-run)

CREATE TABLE IF NOT EXISTS cybershield_subscriptions (
    id                  SERIAL PRIMARY KEY,
    client_id           VARCHAR NOT NULL UNIQUE,
    status              VARCHAR NOT NULL DEFAULT 'pending',   -- pending/active/inactive
    network_type        VARCHAR DEFAULT 'unifi',
    gateway_ip          VARCHAR,
    unifi_site_id       VARCHAR,
    monthly_price       NUMERIC(10,2) DEFAULT 1499.00,
    start_date          DATE,
    next_billing_date   DATE,
    agreement_signed_at TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cybershield_sub_client ON cybershield_subscriptions(client_id);
CREATE INDEX IF NOT EXISTS idx_cybershield_sub_status ON cybershield_subscriptions(status);

CREATE TABLE IF NOT EXISTS cybershield_events (
    id              SERIAL PRIMARY KEY,
    client_id       VARCHAR NOT NULL,
    event_type      VARCHAR NOT NULL,   -- threat_detected/intrusion_attempt/data_exfiltration/anomaly/breach_prevention
    severity        VARCHAR NOT NULL DEFAULT 'low',  -- low/moderate/high/critical
    source_ip       VARCHAR,
    destination_ip  VARCHAR,
    description     TEXT NOT NULL,
    raw_data        TEXT,
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cybershield_events_client ON cybershield_events(client_id);
CREATE INDEX IF NOT EXISTS idx_cybershield_events_severity ON cybershield_events(severity);
CREATE INDEX IF NOT EXISTS idx_cybershield_events_resolved ON cybershield_events(resolved);
CREATE INDEX IF NOT EXISTS idx_cybershield_events_created ON cybershield_events(created_at DESC);

CREATE TABLE IF NOT EXISTS cybershield_monthly_reports (
    id               SERIAL PRIMARY KEY,
    client_id        VARCHAR NOT NULL,
    month            VARCHAR NOT NULL,  -- YYYY-MM
    report_url       TEXT,
    pdf_path         TEXT,
    events_total     INTEGER DEFAULT 0,
    threats_blocked  INTEGER DEFAULT 0,
    compliance_score INTEGER DEFAULT 100,
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(client_id, month)
);

CREATE INDEX IF NOT EXISTS idx_cybershield_reports_client ON cybershield_monthly_reports(client_id);
