-- Diagnostic Storage — Step 3
-- Device registry, full diagnostic snapshots, time-series metrics

CREATE TABLE IF NOT EXISTS client_devices (
    id          SERIAL PRIMARY KEY,
    serial      VARCHAR(100) UNIQUE NOT NULL,
    client_id   VARCHAR(100) NOT NULL,
    hostname    VARCHAR(200),
    model       VARCHAR(200),
    chip_type   VARCHAR(50),
    cpu         VARCHAR(200),
    ram_gb      INTEGER,
    storage_gb  INTEGER,
    macos_version VARCHAR(50),
    first_seen  TIMESTAMPTZ DEFAULT NOW(),
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    is_active   BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_devices_client  ON client_devices(client_id);
CREATE INDEX IF NOT EXISTS idx_devices_serial  ON client_devices(serial);

CREATE TABLE IF NOT EXISTS diagnostic_snapshots (
    id                      SERIAL PRIMARY KEY,
    device_id               INTEGER REFERENCES client_devices(id),
    serial                  VARCHAR(100) NOT NULL,
    client_id               VARCHAR(100),
    scan_date               TIMESTAMPTZ DEFAULT NOW(),
    version                 VARCHAR(20),
    mode                    VARCHAR(20),
    reason                  TEXT,
    runtime_seconds         INTEGER,
    risk_score              INTEGER,
    risk_level              VARCHAR(20),
    recommendation_count    INTEGER,
    raw_json                JSONB NOT NULL,
    raw_txt                 TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_serial ON diagnostic_snapshots(serial);
CREATE INDEX IF NOT EXISTS idx_snapshots_date   ON diagnostic_snapshots(scan_date DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_client ON diagnostic_snapshots(client_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_risk   ON diagnostic_snapshots(risk_score DESC);

CREATE TABLE IF NOT EXISTS device_metrics (
    time                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    serial              VARCHAR(100) NOT NULL,
    battery_health_pct  REAL,
    battery_cycle_count INTEGER,
    disk_used_pct       REAL,
    disk_free_gb        REAL,
    ram_pressure_pct    REAL,
    swap_used_mb        REAL,
    process_count       INTEGER,
    filevault_on        BOOLEAN,
    firewall_on         BOOLEAN,
    sip_enabled         BOOLEAN,
    risk_score          INTEGER,
    threat_count        INTEGER,
    malware_findings    INTEGER
);

-- TimescaleDB not available on Render basic plan — device_metrics is a standard table

CREATE INDEX IF NOT EXISTS idx_metrics_serial ON device_metrics(serial, time DESC);
