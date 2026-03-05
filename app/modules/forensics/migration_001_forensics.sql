-- ============================================================================
-- Forensics Module — Migration 001
-- Chain of custody, evidence collection, POPIA compliant
-- ============================================================================
-- device serial is VARCHAR — no FK constraint (devices table may not exist)
-- Run against the production PostgreSQL/TimescaleDB instance on Render.

CREATE TABLE IF NOT EXISTS forensics_cases (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    serial      VARCHAR(100) NOT NULL,
    client_id   VARCHAR(100) NOT NULL,
    hostname    VARCHAR(255),
    investigator VARCHAR(255) NOT NULL,
    severity    VARCHAR(20)  NOT NULL DEFAULT 'medium',
    description TEXT         NOT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'open',
    popia_consent BOOLEAN    NOT NULL DEFAULT FALSE,
    case_hash   VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forensics_cases_serial   ON forensics_cases(serial);
CREATE INDEX IF NOT EXISTS idx_forensics_cases_client   ON forensics_cases(client_id);
CREATE INDEX IF NOT EXISTS idx_forensics_cases_status   ON forensics_cases(status);

-- ────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS forensics_evidence (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID         NOT NULL,
    evidence_type   VARCHAR(50)  NOT NULL,
    filename        VARCHAR(500) NOT NULL,
    size_bytes      BIGINT,
    sha256_hash     VARCHAR(64)  NOT NULL,
    collection_tool VARCHAR(100),
    notes           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forensics_evidence_case ON forensics_evidence(case_id);

-- ────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS forensics_custody_log (
    id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id   UUID         NOT NULL,
    action    VARCHAR(100) NOT NULL,
    actor     VARCHAR(255) NOT NULL,
    details   TEXT,
    timestamp TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forensics_custody_case ON forensics_custody_log(case_id, timestamp DESC);
