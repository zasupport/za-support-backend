-- Migration 022: Research Module + Documents Module
-- Idempotent — safe to re-run

CREATE TABLE IF NOT EXISTS research_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               TEXT NOT NULL,
    summary             TEXT,
    source              VARCHAR(50),      -- hn|arxiv|producthunt|github|crunchbase
    url                 TEXT,
    category            VARCHAR(50),      -- voice_ai|autonomous_agents|ai_tools|investment|other
    relevance           VARCHAR(20) DEFAULT 'medium',
    investment_usd      NUMERIC(15, 0),
    tags                JSONB DEFAULT '[]',
    published_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    included_in_digest  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_research_category ON research_items(category);
CREATE INDEX IF NOT EXISTS idx_research_relevance ON research_items(relevance);
CREATE INDEX IF NOT EXISTS idx_research_digest ON research_items(included_in_digest);

CREATE TABLE IF NOT EXISTS research_digests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_of     TIMESTAMPTZ NOT NULL,
    summary_md  TEXT,
    item_ids    JSONB DEFAULT '[]',
    sent_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id           VARCHAR(100) NOT NULL,
    filename            VARCHAR(300) NOT NULL,
    document_type       VARCHAR(50),   -- cyberpulse_report|cybershield_report|assessment|guide|invoice|other
    onedrive_id         VARCHAR(200),
    onedrive_url        TEXT,
    onedrive_path       TEXT,
    file_size_bytes     VARCHAR(20),
    mime_type           VARCHAR(100),
    shared_with_client  BOOLEAN NOT NULL DEFAULT FALSE,
    share_link          TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_client_docs_client ON client_documents(client_id);
CREATE INDEX IF NOT EXISTS idx_client_docs_type ON client_documents(document_type);
