-- Health Check AI — Interaction Analytics Consent
-- POPIA consent records for interaction/keystroke analytics collection.
-- A client_id must have an active consent record before data is accepted.

CREATE TABLE IF NOT EXISTS interaction_consent (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id   VARCHAR(100) NOT NULL UNIQUE,
    device_id   VARCHAR(100),
    consented   BOOLEAN NOT NULL DEFAULT FALSE,
    consented_at TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    consent_text TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interaction_consent_client ON interaction_consent(client_id);
