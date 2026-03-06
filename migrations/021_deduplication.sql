-- Migration 021: Deduplication Module
-- Idempotent — safe to re-run

CREATE TABLE IF NOT EXISTS dedup_scans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       VARCHAR(100) NOT NULL,
    scan_date       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_files     INTEGER NOT NULL DEFAULT 0,
    duplicate_sets  INTEGER NOT NULL DEFAULT 0,
    recoverable_gb  NUMERIC(10, 3) NOT NULL DEFAULT 0,
    photo_gb        NUMERIC(10, 3) NOT NULL DEFAULT 0,
    document_gb     NUMERIC(10, 3) NOT NULL DEFAULT 0,
    other_gb        NUMERIC(10, 3) NOT NULL DEFAULT 0,
    top_culprits    JSONB DEFAULT '[]',  -- [{path, size_gb, count}]
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending|complete|reviewed|actioned
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dedup_scans_client ON dedup_scans(client_id);
CREATE INDEX IF NOT EXISTS idx_dedup_scans_date ON dedup_scans(scan_date DESC);

CREATE TABLE IF NOT EXISTS dedup_items (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id      UUID NOT NULL REFERENCES dedup_scans(id) ON DELETE CASCADE,
    file_hash    VARCHAR(64) NOT NULL,
    file_paths   JSONB DEFAULT '[]',    -- all paths sharing this hash
    file_size_mb NUMERIC(10, 3),
    file_type    VARCHAR(50),           -- photo|document|video|archive|other
    keep_path    TEXT,                  -- recommended path to keep
    action       VARCHAR(20) NOT NULL DEFAULT 'review',  -- keep|delete|review
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dedup_items_scan ON dedup_items(scan_id);
CREATE INDEX IF NOT EXISTS idx_dedup_items_action ON dedup_items(action);
CREATE INDEX IF NOT EXISTS idx_dedup_items_hash ON dedup_items(file_hash);
