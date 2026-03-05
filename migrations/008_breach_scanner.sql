-- =============================================================================
-- Compromised Data Scanner — Initial Migration
-- Module: app/modules/breach_scanner
-- Health Check v11
-- =============================================================================
-- Tables:
--   1. breach_consent        — POPIA consent records per client
--   2. scan_sessions         — Individual scan execution records
--   3. scan_findings         — Detected IOCs / suspicious items
--   4. finding_corroborations — Per-provider corroboration results
--   5. scan_schedules        — Per-device automated scan schedules
--   6. breach_notifications  — POPIA Section 22 notification records
--   7. scanner_alert_events  — Webhook / email alert dispatch log
-- =============================================================================

BEGIN;

-- ── 1. POPIA Consent Records ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS breach_consent (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL,
    granted_by      TEXT NOT NULL,          -- name of person granting consent
    granted_role    TEXT NOT NULL,          -- e.g. 'practice_owner', 'it_admin'
    consent_scope   TEXT NOT NULL DEFAULT 'full_scan',
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    ip_address      INET,
    notes           TEXT,

    CONSTRAINT uq_breach_consent_client UNIQUE (client_id)
);

CREATE INDEX idx_breach_consent_client ON breach_consent (client_id);
CREATE INDEX idx_breach_consent_active ON breach_consent (is_active) WHERE is_active = TRUE;

COMMENT ON TABLE breach_consent IS
    'POPIA consent records — scanning operations require active consent per client.';


-- ── 2. Scan Sessions ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scan_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id           UUID NOT NULL,
    client_id           UUID NOT NULL,
    scope               TEXT NOT NULL DEFAULT 'full',  -- full | quick | targeted
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    duration_seconds    REAL,
    total_items_scanned INTEGER NOT NULL DEFAULT 0,
    findings_count      INTEGER NOT NULL DEFAULT 0,
    critical_count      INTEGER NOT NULL DEFAULT 0,
    high_count          INTEGER NOT NULL DEFAULT 0,
    confirmed_malicious INTEGER NOT NULL DEFAULT 0,
    agent_version       TEXT,
    error_message       TEXT,

    CONSTRAINT fk_scan_sessions_consent
        FOREIGN KEY (client_id) REFERENCES breach_consent (client_id)
        -- no ON DELETE CASCADE: sessions preserved for audit trail
);

CREATE INDEX idx_scan_sessions_device ON scan_sessions (device_id);
CREATE INDEX idx_scan_sessions_client ON scan_sessions (client_id);
CREATE INDEX idx_scan_sessions_started ON scan_sessions (started_at DESC);
CREATE INDEX idx_scan_sessions_status ON scan_sessions (status) WHERE status IN ('pending', 'running');

-- Convert to TimescaleDB hypertable for time-series queries
-- (only if TimescaleDB extension is available)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'scan_sessions', 'started_at',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;

COMMENT ON TABLE scan_sessions IS
    'Individual scan execution records — one row per agent scan submission.';


-- ── 3. Scan Findings ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scan_findings (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              UUID NOT NULL REFERENCES scan_sessions (id) ON DELETE CASCADE,
    device_id               UUID NOT NULL,
    client_id               UUID NOT NULL,

    -- Classification
    scanner                 TEXT NOT NULL,       -- filesystem | email | app | persistence | process | network
    category                TEXT NOT NULL,       -- malware | phishing | rootkit | data_exfiltration | etc.
    severity                TEXT NOT NULL DEFAULT 'medium',  -- critical | high | medium | low | info
    title                   TEXT NOT NULL,
    description             TEXT,

    -- Evidence fields (nullable — depends on scanner type)
    file_path               TEXT,
    file_hash_sha256        TEXT,
    file_hash_md5           TEXT,
    file_size_bytes         BIGINT,
    process_name            TEXT,
    process_pid             INTEGER,
    process_cmdline         TEXT,
    network_ip              INET,
    network_port            INTEGER,
    network_domain          TEXT,
    network_protocol        TEXT,
    email_subject           TEXT,
    email_sender            TEXT,
    app_name                TEXT,
    app_version             TEXT,
    persistence_location    TEXT,

    -- MITRE ATT&CK mapping
    mitre_technique         TEXT,       -- e.g. T1059.001
    mitre_tactic            TEXT,       -- e.g. Execution

    -- Corroboration outcome (written by corroboration engine)
    corroboration_status    TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed_malicious | likely_malicious | suspicious | clean | inconclusive | error
    corroboration_confidence REAL NOT NULL DEFAULT 0.0,
    corroboration_sources   INTEGER NOT NULL DEFAULT 0,
    recommended_action      TEXT,

    -- Resolution
    is_resolved             BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at             TIMESTAMPTZ,
    resolved_by             TEXT,
    is_false_positive       BOOLEAN NOT NULL DEFAULT FALSE,
    resolution_notes        TEXT,

    -- Timestamps
    found_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Raw scanner output (JSON blob for debugging / audit)
    raw_data                JSONB
);

CREATE INDEX idx_scan_findings_session ON scan_findings (session_id);
CREATE INDEX idx_scan_findings_device ON scan_findings (device_id);
CREATE INDEX idx_scan_findings_client ON scan_findings (client_id);
CREATE INDEX idx_scan_findings_severity ON scan_findings (severity) WHERE severity IN ('critical', 'high');
CREATE INDEX idx_scan_findings_corroboration ON scan_findings (corroboration_status);
CREATE INDEX idx_scan_findings_unresolved ON scan_findings (device_id, severity)
    WHERE is_resolved = FALSE;
CREATE INDEX idx_scan_findings_hash ON scan_findings (file_hash_sha256)
    WHERE file_hash_sha256 IS NOT NULL;
CREATE INDEX idx_scan_findings_found ON scan_findings (found_at DESC);

-- TimescaleDB hypertable (if available)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'scan_findings', 'found_at',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;

COMMENT ON TABLE scan_findings IS
    'Detected IOCs and suspicious items — each row is one finding from a scanner.';


-- ── 4. Finding Corroborations ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS finding_corroborations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id      UUID NOT NULL REFERENCES scan_findings (id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,       -- virustotal | abuseipdb | yara | hashdb | mitre
    status          TEXT NOT NULL,       -- confirmed_malicious | likely_malicious | suspicious | clean | inconclusive | error
    confidence      REAL NOT NULL DEFAULT 0.0,
    detail          TEXT,                -- human-readable summary
    raw_response    JSONB,               -- full provider response for audit
    queried_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    response_time_ms INTEGER
);

CREATE INDEX idx_finding_corroborations_finding ON finding_corroborations (finding_id);
CREATE INDEX idx_finding_corroborations_provider ON finding_corroborations (provider);

COMMENT ON TABLE finding_corroborations IS
    'Per-provider corroboration results for each finding.';


-- ── 5. Scan Schedules ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scan_schedules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id           UUID NOT NULL UNIQUE,
    client_id           UUID NOT NULL,
    scope               TEXT NOT NULL DEFAULT 'full',
    interval_hours      INTEGER NOT NULL DEFAULT 24,
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    last_scan_at        TIMESTAMPTZ,
    next_scan_at        TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_scan_schedules_client ON scan_schedules (client_id);
CREATE INDEX idx_scan_schedules_next ON scan_schedules (next_scan_at)
    WHERE enabled = TRUE;

COMMENT ON TABLE scan_schedules IS
    'Per-device automated scan schedules with exponential backoff on failure.';


-- ── 6. POPIA Section 22 Breach Notifications ────────────────────────────────

CREATE TABLE IF NOT EXISTS breach_notifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           UUID NOT NULL,
    device_id           UUID NOT NULL,
    finding_ids         UUID[] NOT NULL,           -- array of related finding IDs
    notification_type   TEXT NOT NULL DEFAULT 'popia_section_22',
    severity            TEXT NOT NULL,
    data_types_at_risk  TEXT[] NOT NULL DEFAULT '{}',
    summary             TEXT NOT NULL,
    recommended_actions TEXT[] NOT NULL DEFAULT '{}',
    regulatory_refs     TEXT[] NOT NULL DEFAULT '{}',

    -- Delivery tracking
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at             TIMESTAMPTZ,
    sent_to             TEXT[],                    -- email addresses
    delivery_status     TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed
    failure_reason      TEXT,

    -- Compliance tracking
    information_regulator_notified BOOLEAN NOT NULL DEFAULT FALSE,
    data_subjects_notified         BOOLEAN NOT NULL DEFAULT FALSE,
    notification_deadline          TIMESTAMPTZ     -- 72h from discovery
);

CREATE INDEX idx_breach_notifications_client ON breach_notifications (client_id);
CREATE INDEX idx_breach_notifications_status ON breach_notifications (delivery_status)
    WHERE delivery_status = 'pending';
CREATE INDEX idx_breach_notifications_generated ON breach_notifications (generated_at DESC);

COMMENT ON TABLE breach_notifications IS
    'POPIA Section 22 breach notification records — tracks generation, delivery, and compliance.';


-- ── 7. Alert Events ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS scanner_alert_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       UUID NOT NULL,
    client_id       UUID NOT NULL,
    finding_id      UUID REFERENCES scan_findings (id) ON DELETE SET NULL,
    alert_type      TEXT NOT NULL,       -- critical_finding | high_finding | scan_failed | schedule_stale
    channel         TEXT NOT NULL,       -- webhook | email
    destination     TEXT NOT NULL,       -- webhook URL or email address
    payload         JSONB,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivery_status TEXT NOT NULL DEFAULT 'sent',  -- sent | failed
    failure_reason  TEXT,
    cooldown_key    TEXT                 -- for deduplication within cooldown window
);

CREATE INDEX idx_scanner_alerts_device ON scanner_alert_events (device_id);
CREATE INDEX idx_scanner_alerts_sent ON scanner_alert_events (sent_at DESC);
CREATE INDEX idx_scanner_alerts_cooldown ON scanner_alert_events (cooldown_key, sent_at DESC)
    WHERE cooldown_key IS NOT NULL;

COMMENT ON TABLE scanner_alert_events IS
    'Webhook and email alert dispatch log for audit and cooldown tracking.';


-- ── Data Retention Policy (TimescaleDB) ──────────────────────────────────────

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        -- 90-day detailed retention for scan sessions
        PERFORM add_retention_policy('scan_sessions', INTERVAL '90 days',
            if_not_exists => TRUE);
        -- 90-day detailed retention for findings
        PERFORM add_retention_policy('scan_findings', INTERVAL '90 days',
            if_not_exists => TRUE);
    END IF;
END $$;


-- ── Summary Views ────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW breach_scanner_device_summary AS
SELECT
    f.device_id,
    f.client_id,
    COUNT(*)                                                    AS total_findings,
    COUNT(*) FILTER (WHERE f.severity = 'critical')             AS critical_count,
    COUNT(*) FILTER (WHERE f.severity = 'high')                 AS high_count,
    COUNT(*) FILTER (WHERE f.severity = 'medium')               AS medium_count,
    COUNT(*) FILTER (WHERE f.corroboration_status = 'confirmed_malicious') AS confirmed_malicious,
    COUNT(*) FILTER (WHERE f.is_resolved = FALSE)               AS unresolved,
    MAX(f.found_at)                                             AS last_finding_at,
    MAX(s.started_at)                                           AS last_scan_at
FROM scan_findings f
JOIN scan_sessions s ON s.id = f.session_id
WHERE f.is_resolved = FALSE
GROUP BY f.device_id, f.client_id;

COMMENT ON VIEW breach_scanner_device_summary IS
    'Aggregate finding counts per device for dashboard queries.';


CREATE OR REPLACE VIEW breach_scanner_client_dashboard AS
SELECT
    c.client_id,
    c.granted_by,
    c.granted_at,
    COALESCE(ds.total_devices, 0)       AS devices_monitored,
    COALESCE(ds.total_findings, 0)      AS total_findings,
    COALESCE(ds.critical_total, 0)      AS critical_findings,
    COALESCE(ds.confirmed_total, 0)     AS confirmed_malicious,
    COALESCE(ds.unresolved_total, 0)    AS unresolved_findings,
    ds.last_scan_at
FROM breach_consent c
LEFT JOIN LATERAL (
    SELECT
        COUNT(DISTINCT device_id)           AS total_devices,
        SUM(total_findings)                 AS total_findings,
        SUM(critical_count)                 AS critical_total,
        SUM(confirmed_malicious)            AS confirmed_total,
        SUM(unresolved)                     AS unresolved_total,
        MAX(last_scan_at)                   AS last_scan_at
    FROM breach_scanner_device_summary ds2
    WHERE ds2.client_id = c.client_id
) ds ON TRUE
WHERE c.is_active = TRUE;

COMMENT ON VIEW breach_scanner_client_dashboard IS
    'Client-level dashboard aggregate for the breach scanner module.';


COMMIT;
