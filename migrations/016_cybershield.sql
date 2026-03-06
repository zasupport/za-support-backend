-- 016_cybershield.sql
-- CyberShield — monthly network security service enrollment + report tracking

CREATE TABLE IF NOT EXISTS cybershield_enrollments (
    id           SERIAL PRIMARY KEY,
    client_id    VARCHAR(100) NOT NULL UNIQUE,
    practice_name TEXT,
    isp_name     TEXT,
    enrolled_at  TIMESTAMPTZ DEFAULT NOW(),
    active       BOOLEAN DEFAULT TRUE,
    monthly_fee  NUMERIC(10, 2) DEFAULT 1499.00,
    notes        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cybershield_reports (
    id           SERIAL PRIMARY KEY,
    client_id    VARCHAR(100) NOT NULL,
    filename     TEXT NOT NULL,
    month_label  VARCHAR(20),
    file_path    TEXT,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_enrollments_client  ON cybershield_enrollments(client_id);
CREATE INDEX IF NOT EXISTS idx_cs_enrollments_active  ON cybershield_enrollments(active);
CREATE INDEX IF NOT EXISTS idx_cs_reports_client      ON cybershield_reports(client_id);
CREATE INDEX IF NOT EXISTS idx_cs_reports_generated   ON cybershield_reports(generated_at DESC);
