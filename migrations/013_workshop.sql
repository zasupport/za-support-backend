-- ============================================================
-- Migration 013: Workshop / PTG (Parts & Time Tracking) Jobs
-- Auto-creates job cards from high-risk diagnostic findings.
-- Idempotent — safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS workshop_jobs (
    id              SERIAL PRIMARY KEY,
    job_ref         TEXT NOT NULL UNIQUE,          -- WS-2026-0001
    client_id       TEXT NOT NULL,
    serial          TEXT,                          -- device serial if device-specific
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'open',  -- open | in_progress | waiting_parts | completed | cancelled
    priority        TEXT NOT NULL DEFAULT 'normal',-- low | normal | high | urgent
    source          TEXT NOT NULL DEFAULT 'manual',-- manual | auto_diagnostic
    snapshot_id     INTEGER,                       -- link to diagnostic_snapshots row
    assigned_to     TEXT DEFAULT 'courtney@zasupport.com',
    scheduled_date  DATE,
    completed_at    TIMESTAMPTZ,
    labour_minutes  INTEGER,
    total_incl_vat  NUMERIC(10,2),
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workshop_line_items (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES workshop_jobs(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    qty         INTEGER NOT NULL DEFAULT 1,
    unit_price  NUMERIC(10,2),
    line_total  NUMERIC(10,2),
    item_type   TEXT DEFAULT 'labour',             -- labour | part | software | service
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workshop_job_history (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES workshop_jobs(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    note        TEXT,
    changed_by  TEXT DEFAULT 'system',
    changed_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workshop_jobs_client_id  ON workshop_jobs(client_id);
CREATE INDEX IF NOT EXISTS idx_workshop_jobs_status     ON workshop_jobs(status);
CREATE INDEX IF NOT EXISTS idx_workshop_jobs_created_at ON workshop_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workshop_line_items_job  ON workshop_line_items(job_id);
