-- ZA Vault: encrypted credential storage for managed client accounts

CREATE TABLE IF NOT EXISTS vault_entries (
    id                      SERIAL PRIMARY KEY,
    client_id               VARCHAR(100) NOT NULL,
    category                VARCHAR(50) NOT NULL,
    service_name            VARCHAR(200) NOT NULL,
    username                TEXT,
    password                TEXT,
    url                     VARCHAR(500),
    notes                   TEXT,
    license_key             TEXT,
    expiry_date             TIMESTAMPTZ,
    last_rotated            TIMESTAMPTZ,
    rotation_reminder_days  INTEGER DEFAULT 90,
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    created_by              VARCHAR(100) DEFAULT 'courtney',
    is_active               BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_vault_entries_client_id ON vault_entries(client_id);
CREATE INDEX IF NOT EXISTS idx_vault_entries_category  ON vault_entries(category);
CREATE INDEX IF NOT EXISTS idx_vault_entries_expiry    ON vault_entries(expiry_date) WHERE is_active = true;

CREATE TABLE IF NOT EXISTS vault_audit_log (
    id            SERIAL PRIMARY KEY,
    entry_id      INTEGER NOT NULL REFERENCES vault_entries(id),
    action        VARCHAR(50) NOT NULL,
    performed_by  VARCHAR(100) NOT NULL,
    performed_at  TIMESTAMPTZ DEFAULT NOW(),
    ip_address    VARCHAR(45),
    details       TEXT
);

CREATE INDEX IF NOT EXISTS idx_vault_audit_entry_id ON vault_audit_log(entry_id);
