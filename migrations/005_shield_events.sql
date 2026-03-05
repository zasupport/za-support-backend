-- ZA Shield Agent: real-time macOS security event storage

CREATE TABLE IF NOT EXISTS shield_events (
    id                  SERIAL PRIMARY KEY,
    serial              VARCHAR(100) NOT NULL,
    hostname            VARCHAR(200),
    severity            VARCHAR(20) NOT NULL,
    event_type          VARCHAR(100) NOT NULL,
    path                TEXT,
    detail              TEXT,
    timestamp           TIMESTAMPTZ DEFAULT NOW(),
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    acknowledged        BOOLEAN DEFAULT FALSE,
    acknowledged_by     VARCHAR(100),
    acknowledged_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_shield_serial    ON shield_events(serial);
CREATE INDEX IF NOT EXISTS idx_shield_severity  ON shield_events(severity);
CREATE INDEX IF NOT EXISTS idx_shield_timestamp ON shield_events(timestamp DESC);
