-- Migration 023: UniFi Network Integration
-- Extends the network module with UniFi-specific time-series and device state tables
-- Supports: UniFi Express 7, UniFi Cloud (api.ui.com), local controller API

-- ---------------------------------------------------------------------------
-- UniFi snapshots — time-series, one row per poll (every 5 min)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unifi_snapshots (
    id               UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id        VARCHAR(100) NOT NULL,
    controller_id    VARCHAR(128) NOT NULL,
    polled_at        TIMESTAMPTZ  DEFAULT NOW() NOT NULL,
    source           VARCHAR(20)  DEFAULT 'local',   -- 'cloud' | 'local'
    wan_status       VARCHAR(20),                    -- 'online' | 'offline' | 'unknown'
    wan_ip           VARCHAR(45),
    wan_rx_bytes     BIGINT,
    wan_tx_bytes     BIGINT,
    wan_rx_mbps      FLOAT,
    wan_tx_mbps      FLOAT,
    wan_latency_ms   FLOAT,
    connected_clients  INT,
    wireless_clients   INT,
    wired_clients      INT,
    devices_total      INT,
    devices_online     INT,
    site_name          VARCHAR(200),
    uptime_seconds     BIGINT,
    raw_json           JSONB
);

CREATE INDEX IF NOT EXISTS ix_unifi_snapshots_client_ts
    ON unifi_snapshots (client_id, polled_at DESC);

CREATE INDEX IF NOT EXISTS ix_unifi_snapshots_controller_ts
    ON unifi_snapshots (controller_id, polled_at DESC);

-- TimescaleDB hypertable (7-day chunks, drops gracefully if not available)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'
    ) THEN
        PERFORM create_hypertable(
            'unifi_snapshots', 'polled_at',
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        );
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- UniFi device state — latest state per physical device (upsert target)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unifi_device_state (
    id               UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id        VARCHAR(100) NOT NULL,
    controller_id    VARCHAR(128) NOT NULL,
    mac              VARCHAR(20)  NOT NULL,
    name             VARCHAR(200),
    model            VARCHAR(100),
    type             VARCHAR(50),     -- 'ugw' | 'usw' | 'uap' | 'udm'
    ip               VARCHAR(45),
    status           VARCHAR(20),     -- 'online' | 'offline' | 'adopting'
    uptime_seconds   BIGINT,
    firmware_version VARCHAR(50),
    last_seen        TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (client_id, mac)
);

CREATE INDEX IF NOT EXISTS ix_unifi_device_client
    ON unifi_device_state (client_id);

-- ---------------------------------------------------------------------------
-- UniFi config registry — stores per-client controller credentials (encrypted)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS unifi_controller_config (
    id                UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    client_id         VARCHAR(100) NOT NULL UNIQUE,
    controller_host   VARCHAR(255) NOT NULL,   -- e.g. 192.168.1.252 or hostname
    controller_port   INT          DEFAULT 443,
    username          TEXT,                    -- encrypted via app encryption key
    password_enc      TEXT,                    -- encrypted
    cloud_api_key_enc TEXT,                    -- UI.com API key, encrypted
    site_name         VARCHAR(100) DEFAULT 'default',
    poll_interval_sec INT          DEFAULT 300,
    enabled           BOOLEAN      DEFAULT TRUE,
    notes             TEXT,
    created_at        TIMESTAMPTZ  DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  DEFAULT NOW()
);
