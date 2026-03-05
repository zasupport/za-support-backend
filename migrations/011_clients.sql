-- Clients Module — Migration 011
-- Client intake form data, setup profiles, onboarding tasks, pre-visit check-ins
-- Run: psql $DATABASE_URL < migrations/011_clients.sql

-- Main client record (created from onboarding form submission)
CREATE TABLE IF NOT EXISTS clients (
    id                              SERIAL PRIMARY KEY,
    client_id                       VARCHAR(100) UNIQUE NOT NULL,
    first_name                      VARCHAR(100) NOT NULL,
    last_name                       VARCHAR(100) NOT NULL,
    email                           VARCHAR(255) UNIQUE NOT NULL,
    phone                           VARCHAR(50) NOT NULL,
    preferred_contact               VARCHAR(50) NOT NULL,
    address                         TEXT,
    referral_source                 VARCHAR(100),
    referred_by                     VARCHAR(200),
    urgency_level                   VARCHAR(50),
    concerns                        TEXT[],
    concerns_detail                 TEXT,
    has_business                    BOOLEAN DEFAULT FALSE,
    business_name                   VARCHAR(200),
    business_type                   VARCHAR(200),
    business_staff_count            VARCHAR(50),
    business_device_count           VARCHAR(50),
    business_health_check_interest  VARCHAR(100),
    popia_consent                   BOOLEAN NOT NULL DEFAULT FALSE,
    marketing_consent               BOOLEAN DEFAULT FALSE,
    status                          VARCHAR(50) DEFAULT 'new',
    created_at                      TIMESTAMPTZ DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clients_email     ON clients(email);
CREATE INDEX IF NOT EXISTS idx_clients_status    ON clients(status);
CREATE INDEX IF NOT EXISTS idx_clients_created   ON clients(created_at DESC);

-- Client environment profile (captured from intake form)
-- Separate from client_devices (which is Scout-registered Mac hardware)
CREATE TABLE IF NOT EXISTS client_setup (
    id                      SERIAL PRIMARY KEY,
    client_id               VARCHAR(100) REFERENCES clients(client_id) ON DELETE CASCADE,
    primary_computer        VARCHAR(50),
    form_factor             VARCHAR(50),
    computer_age            VARCHAR(50),
    computer_model_hint     VARCHAR(200),
    has_external_backup     VARCHAR(20),
    other_devices           TEXT[],
    isp                     VARCHAR(100),
    cloud_services          TEXT[],
    email_clients           TEXT[],
    has_google_account      VARCHAR(20),
    has_apple_id            VARCHAR(20),
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_setup_client ON client_setup(client_id);

-- Onboarding task checklist (auto-populated on client.created)
CREATE TABLE IF NOT EXISTS client_onboarding_tasks (
    id              SERIAL PRIMARY KEY,
    client_id       VARCHAR(100) REFERENCES clients(client_id) ON DELETE CASCADE,
    task            VARCHAR(500) NOT NULL,
    status          VARCHAR(50) DEFAULT 'pending',
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_onboarding_tasks_client ON client_onboarding_tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_tasks_status ON client_onboarding_tasks(status);

-- Pre-visit check-in responses (Form 2)
CREATE TABLE IF NOT EXISTS client_checkins (
    id                      SERIAL PRIMARY KEY,
    client_id               VARCHAR(100) REFERENCES clients(client_id) ON DELETE CASCADE,
    working_well            TEXT,
    changes_since_last      TEXT,
    focus_today             TEXT,
    issues_noted            TEXT,
    backup_drive_connected  VARCHAR(20),
    pre_visit_notes         TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_checkins_client  ON client_checkins(client_id);
CREATE INDEX IF NOT EXISTS idx_checkins_created ON client_checkins(created_at DESC);
