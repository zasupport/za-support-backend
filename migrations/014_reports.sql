-- ============================================================
-- Migration 014: Generated Reports Log
-- Tracks CyberPulse and CyberShield reports generated from
-- diagnostic data. Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS generated_reports (
    id           SERIAL PRIMARY KEY,
    client_id    TEXT NOT NULL,
    serial       TEXT,
    snapshot_id  INTEGER,
    report_type  TEXT NOT NULL DEFAULT 'cyberpulse', -- cyberpulse | cybershield
    filename     TEXT NOT NULL,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    generated_by TEXT DEFAULT 'system',
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_reports_client_id   ON generated_reports(client_id);
CREATE INDEX IF NOT EXISTS idx_reports_generated_at ON generated_reports(generated_at DESC);
