-- 015_client_notes.sql
-- Sticky notes for internal use on client profiles (visible only in dashboard)

CREATE TABLE IF NOT EXISTS client_notes (
    id          SERIAL PRIMARY KEY,
    client_id   VARCHAR(100) NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    author      VARCHAR(100) DEFAULT 'courtney@zasupport.com',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_notes_client_id ON client_notes(client_id);
CREATE INDEX IF NOT EXISTS idx_client_notes_created_at ON client_notes(created_at DESC);
