-- Customer Guides module
-- Centralised knowledge base linked to client profiles

CREATE TABLE IF NOT EXISTS guides (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    content_md  TEXT NOT NULL,
    category    TEXT,
    tags        TEXT[] DEFAULT '{}',
    created_by  TEXT DEFAULT 'courtney',
    is_public   BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS guide_client_links (
    id          SERIAL PRIMARY KEY,
    guide_id    INT NOT NULL REFERENCES guides(id) ON DELETE CASCADE,
    client_id   TEXT NOT NULL,
    sent_at     TIMESTAMPTZ DEFAULT NOW(),
    viewed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_guide_client_links_client ON guide_client_links(client_id);

CREATE TABLE IF NOT EXISTS guide_feedback (
    id          SERIAL PRIMARY KEY,
    guide_id    INT NOT NULL REFERENCES guides(id) ON DELETE CASCADE,
    client_id   TEXT NOT NULL,
    helpful     BOOLEAN NOT NULL,
    comment     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_guide_feedback_guide ON guide_feedback(guide_id);
