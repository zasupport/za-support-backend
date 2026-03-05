-- ============================================================
-- Forensics Module — Initial Database Migration
-- Health Check v11
-- Migration: forensics_001_initial
-- ============================================================
-- Run this migration ONLY when activating the forensics module.
-- It is NOT part of the core Health Check v11 schema.
--
-- Prerequisites: Health Check v11 core schema must exist.
-- TimescaleDB is NOT required for this module.
-- ============================================================

BEGIN;

-- --------------------------------------------------------
-- ENUM TYPES
-- --------------------------------------------------------

CREATE TYPE investigation_status AS ENUM (
    'pending',
    'consent_granted',
    'running',
    'complete',
    'failed',
    'cancelled'
);

CREATE TYPE analysis_scope AS ENUM (
    'quick_triage',   -- ~5-10 min: osquery, strings, YARA, short pcap
    'standard',       -- ~30-60 min: adds disk analysis, bulk extractor
    'deep'            -- 2+ hrs: adds memory analysis, file carving
);

CREATE TYPE evidence_type AS ENUM (
    'memory_dump',
    'disk_image',
    'live_capture',
    'pcap',
    'log_file',
    'artifact',
    'screenshot',
    'other'
);

CREATE TYPE finding_severity AS ENUM (
    'critical',
    'high',
    'medium',
    'low',
    'info'
);

CREATE TYPE task_status AS ENUM (
    'pending',
    'running',
    'complete',
    'failed',
    'skipped'
);

-- --------------------------------------------------------
-- FORENSIC INVESTIGATIONS
-- Root record for each investigation.
-- One investigation per device/incident.
-- --------------------------------------------------------

CREATE TABLE forensic_investigations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Client/device linkage (references Health Check v11 core tables)
    client_id           VARCHAR(255),
    device_id           VARCHAR(255),
    device_hostname     VARCHAR(255),
    device_os           VARCHAR(100),
    
    -- Investigation metadata
    scope               analysis_scope NOT NULL DEFAULT 'quick_triage',
    status              investigation_status NOT NULL DEFAULT 'pending',
    initiated_by        VARCHAR(255) NOT NULL,   -- staff member who created investigation
    reason              TEXT NOT NULL,            -- documented reason for investigation
    notes               TEXT,
    
    -- POPIA consent record (immutable once set)
    consent_granted     BOOLEAN NOT NULL DEFAULT FALSE,
    consent_timestamp   TIMESTAMPTZ,
    consent_obtained_by VARCHAR(255),             -- staff member who obtained consent
    consent_method      VARCHAR(100),             -- verbal, written, email, form
    consent_reference   VARCHAR(255),             -- form number, email ref, etc.
    
    -- Execution tracking
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    duration_seconds    INTEGER,
    output_directory    TEXT,                     -- filesystem path to evidence directory
    
    -- Findings summary (denormalised for quick dashboard queries)
    findings_critical   INTEGER NOT NULL DEFAULT 0,
    findings_high       INTEGER NOT NULL DEFAULT 0,
    findings_medium     INTEGER NOT NULL DEFAULT 0,
    findings_low        INTEGER NOT NULL DEFAULT 0,
    findings_info       INTEGER NOT NULL DEFAULT 0,
    
    -- Cancellation
    cancelled_at        TIMESTAMPTZ,
    cancellation_reason TEXT,
    
    -- Error tracking
    error_message       TEXT,
    
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forensic_investigations_client  ON forensic_investigations(client_id);
CREATE INDEX idx_forensic_investigations_device  ON forensic_investigations(device_id);
CREATE INDEX idx_forensic_investigations_status  ON forensic_investigations(status);
CREATE INDEX idx_forensic_investigations_created ON forensic_investigations(created_at DESC);

COMMENT ON TABLE forensic_investigations IS
    'Root record for each forensic investigation. '
    'POPIA: consent fields are immutable once set. '
    'No analysis may begin without consent_granted = TRUE.';

COMMENT ON COLUMN forensic_investigations.consent_granted IS
    'POPIA GATE: Must be TRUE before any data collection or analysis begins. '
    'Set via grant_consent() service method only — never set directly.';

-- --------------------------------------------------------
-- FORENSIC TASKS
-- Individual tool executions within an investigation.
-- --------------------------------------------------------

CREATE TABLE forensic_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID NOT NULL REFERENCES forensic_investigations(id) ON DELETE CASCADE,
    
    tool_id         VARCHAR(100) NOT NULL,       -- matches tool_registry key
    tool_name       VARCHAR(255) NOT NULL,
    category        VARCHAR(100),
    status          task_status NOT NULL DEFAULT 'pending',
    
    -- Execution details
    command         TEXT,                        -- full command string executed
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    duration_seconds INTEGER,
    exit_code       INTEGER,
    
    -- Results
    results         JSONB,                       -- structured output from tool
    artifacts       JSONB,                       -- list of files produced {path, sha256, size}
    summary         TEXT,                        -- human-readable one-line summary
    error_message   TEXT,
    
    -- Skipped reason (when tool not installed)
    skip_reason     TEXT,
    install_command TEXT,                        -- how to install missing tool
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forensic_tasks_investigation ON forensic_tasks(investigation_id);
CREATE INDEX idx_forensic_tasks_tool         ON forensic_tasks(tool_id);
CREATE INDEX idx_forensic_tasks_status       ON forensic_tasks(status);

-- --------------------------------------------------------
-- FORENSIC EVIDENCE
-- Chain of custody record for collected artifacts.
-- --------------------------------------------------------

CREATE TABLE forensic_evidence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID NOT NULL REFERENCES forensic_investigations(id) ON DELETE CASCADE,
    task_id         UUID REFERENCES forensic_tasks(id) ON DELETE SET NULL,
    
    evidence_type   evidence_type NOT NULL,
    filename        VARCHAR(500) NOT NULL,
    file_path       TEXT NOT NULL,              -- absolute path on server
    file_size_bytes BIGINT,
    
    -- Chain of custody hashing
    sha256_intake   VARCHAR(64),                -- hash at collection
    sha256_verified VARCHAR(64),                -- hash at verification (must match)
    hash_verified   BOOLEAN DEFAULT FALSE,
    hash_verified_at TIMESTAMPTZ,
    hash_verified_by VARCHAR(255),
    
    -- Metadata
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_by    VARCHAR(255),               -- staff or tool name
    description     TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forensic_evidence_investigation ON forensic_evidence(investigation_id);

COMMENT ON TABLE forensic_evidence IS
    'Chain of custody record. sha256_intake and sha256_verified must match. '
    'Any mismatch invalidates the evidence for legal purposes.';

-- --------------------------------------------------------
-- FORENSIC FINDINGS
-- Individual indicators detected during analysis.
-- --------------------------------------------------------

CREATE TABLE forensic_findings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID NOT NULL REFERENCES forensic_investigations(id) ON DELETE CASCADE,
    task_id         UUID REFERENCES forensic_tasks(id) ON DELETE SET NULL,
    
    severity        finding_severity NOT NULL,
    category        VARCHAR(100) NOT NULL,       -- malware, network, persistence, etc.
    title           VARCHAR(500) NOT NULL,
    detail          TEXT NOT NULL,               -- full indicator detail
    raw_evidence    TEXT,                        -- raw output line that triggered finding
    
    -- Source
    tool_id         VARCHAR(100),
    source_file     TEXT,
    source_line     INTEGER,
    source_offset   BIGINT,
    
    -- Review
    is_false_positive BOOLEAN DEFAULT FALSE,
    reviewed_by     VARCHAR(255),
    reviewed_at     TIMESTAMPTZ,
    review_notes    TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forensic_findings_investigation ON forensic_findings(investigation_id);
CREATE INDEX idx_forensic_findings_severity      ON forensic_findings(severity);
CREATE INDEX idx_forensic_findings_category      ON forensic_findings(category);
CREATE INDEX idx_forensic_findings_reviewed      ON forensic_findings(reviewed_by) WHERE reviewed_by IS NOT NULL;

COMMENT ON TABLE forensic_findings IS
    'Indicators detected during analysis. '
    'IMPORTANT: A finding is an INDICATOR requiring human review — '
    'it is NOT a confirmed incident or policy violation. '
    'All findings must be reviewed by a qualified professional.';

-- --------------------------------------------------------
-- FORENSIC REPORTS
-- Generated report metadata.
-- --------------------------------------------------------

CREATE TABLE forensic_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id UUID NOT NULL REFERENCES forensic_investigations(id) ON DELETE CASCADE,
    
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    generated_by    VARCHAR(255),
    
    -- File paths
    pdf_path        TEXT,
    json_path       TEXT,
    text_path       TEXT,
    
    -- Integrity
    pdf_sha256      VARCHAR(64),
    json_sha256     VARCHAR(64),
    
    -- Report metadata
    total_findings  INTEGER NOT NULL DEFAULT 0,
    executive_summary TEXT,
    
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forensic_reports_investigation ON forensic_reports(investigation_id);

-- --------------------------------------------------------
-- AUDIT LOG
-- Immutable log of all forensics module actions.
-- POPIA requires audit trail for all personal data access.
-- --------------------------------------------------------

CREATE TABLE forensic_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    investigation_id UUID REFERENCES forensic_investigations(id) ON DELETE SET NULL,
    
    action          VARCHAR(100) NOT NULL,       -- consent_granted, analysis_started, finding_reviewed, report_generated, etc.
    performed_by    VARCHAR(255) NOT NULL,
    performed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    detail          JSONB,                       -- action-specific metadata
    ip_address      VARCHAR(45),
    
    -- This table is append-only — no updates or deletes
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forensic_audit_investigation ON forensic_audit_log(investigation_id);
CREATE INDEX idx_forensic_audit_performed_at  ON forensic_audit_log(performed_at DESC);
CREATE INDEX idx_forensic_audit_action        ON forensic_audit_log(action);

COMMENT ON TABLE forensic_audit_log IS
    'Immutable audit trail. POPIA: Every access to personal data in this module '
    'must be logged here. Do NOT add UPDATE or DELETE grants on this table. '
    'Append-only — INSERT only.';

-- --------------------------------------------------------
-- UPDATED_AT TRIGGER
-- --------------------------------------------------------

CREATE OR REPLACE FUNCTION update_forensics_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_investigations_updated_at
    BEFORE UPDATE ON forensic_investigations
    FOR EACH ROW EXECUTE FUNCTION update_forensics_updated_at();

CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON forensic_tasks
    FOR EACH ROW EXECUTE FUNCTION update_forensics_updated_at();

-- --------------------------------------------------------
-- MIGRATION TRACKING
-- --------------------------------------------------------

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration   VARCHAR(255) PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (migration) VALUES ('forensics_001_initial')
    ON CONFLICT DO NOTHING;

COMMIT;

-- ============================================================
-- POST-MIGRATION NOTES
-- ============================================================
-- 1. No row-level security has been applied here — integrate
--    with your existing Health Check v11 RLS policies.
-- 2. forensic_audit_log should have INSERT-only grants for
--    the application role. Never grant UPDATE or DELETE.
-- 3. Consider pg_partman for forensic_audit_log if you expect
--    high volume (large deployments).
-- 4. All JSONB columns support GIN indexing if query patterns
--    require it — add as needed.
-- ============================================================
