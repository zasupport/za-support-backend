-- Migration 020: Medical Practice Module
-- Idempotent — safe to re-run

CREATE TABLE IF NOT EXISTS medical_practices (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id        VARCHAR(100) NOT NULL UNIQUE,
    practice_name    VARCHAR(200) NOT NULL,
    practice_type    VARCHAR(50) NOT NULL DEFAULT 'gp',  -- gp|specialist|allied|dental|veterinary|psychology
    hpcsa_number     VARCHAR(50),
    doctor_count     INTEGER NOT NULL DEFAULT 1,
    staff_count      INTEGER NOT NULL DEFAULT 0,
    software_stack   JSONB DEFAULT '[]',   -- ["GoodX", "HealthBridge", "Dragon Dictate"]
    devices_count    INTEGER NOT NULL DEFAULT 0,
    compliance_notes TEXT,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_medical_practices_client ON medical_practices(client_id);
CREATE INDEX IF NOT EXISTS idx_medical_practices_type ON medical_practices(practice_type);

CREATE TABLE IF NOT EXISTS medical_assessments (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id       UUID NOT NULL REFERENCES medical_practices(id) ON DELETE CASCADE,
    assessment_date   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Scores 0-100
    network_score     INTEGER,
    device_score      INTEGER,
    software_score    INTEGER,
    backup_score      INTEGER,
    compliance_score  INTEGER,
    overall_score     INTEGER,
    overall_grade     CHAR(1),   -- A B C D F

    -- Compliance flags
    popia_compliant   VARCHAR(20) NOT NULL DEFAULT 'unknown',   -- met|not_met|partial|unknown
    hpcsa_compliant   VARCHAR(20) NOT NULL DEFAULT 'unknown',
    backup_offsite    VARCHAR(20) NOT NULL DEFAULT 'unknown',
    encryption_status VARCHAR(20) NOT NULL DEFAULT 'unknown',

    recommendations   JSONB DEFAULT '[]',   -- [{priority, category, action, rand_impact}]
    upsell_flags      JSONB DEFAULT '[]',   -- product names triggered by this assessment
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_medical_assessments_practice ON medical_assessments(practice_id);
CREATE INDEX IF NOT EXISTS idx_medical_assessments_date ON medical_assessments(assessment_date DESC);
