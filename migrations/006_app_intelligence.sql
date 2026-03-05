-- App Intelligence: process metrics, app health scoring, productivity analytics
-- Note: device_id and client_id are VARCHAR — no FK constraint (devices/clients tables not yet created)

CREATE TABLE IF NOT EXISTS app_resource_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    app_name VARCHAR(255),
    app_bundle_id VARCHAR(255),
    cpu_avg_percent FLOAT,
    cpu_peak_percent FLOAT,
    memory_avg_mb FLOAT,
    memory_peak_mb FLOAT,
    disk_read_mb FLOAT,
    disk_write_mb FLOAT,
    net_sent_mb FLOAT,
    net_recv_mb FLOAT,
    energy_impact_avg FLOAT,
    foreground_seconds INTEGER,
    is_foreground BOOLEAN,
    thread_count_avg FLOAT,
    responsiveness_score FLOAT,
    slow_interactions INTEGER,
    unresponsive_interactions INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_resource_device ON app_resource_metrics(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_app_resource_client ON app_resource_metrics(client_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_app_resource_app ON app_resource_metrics(device_id, app_bundle_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS app_foreground_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    app_name VARCHAR(255) NOT NULL,
    app_bundle_id VARCHAR(255),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    end_reason VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_foreground_sessions_device ON app_foreground_sessions(device_id, started_at DESC);

CREATE TABLE IF NOT EXISTS app_health_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    app_name VARCHAR(255) NOT NULL,
    app_bundle_id VARCHAR(255),
    health_score FLOAT,
    crash_score FLOAT,
    hang_score FLOAT,
    cpu_score FLOAT,
    memory_score FLOAT,
    energy_score FLOAT,
    background_score FLOAT,
    crash_count INTEGER,
    hang_count INTEGER,
    total_foreground_minutes FLOAT,
    total_background_minutes FLOAT,
    UNIQUE(device_id, date, app_bundle_id)
);

CREATE INDEX IF NOT EXISTS idx_app_health_device ON app_health_scores(device_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_app_health_low ON app_health_scores(health_score) WHERE health_score < 50;

CREATE TABLE IF NOT EXISTS startup_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    boot_timestamp TIMESTAMPTZ,
    login_timestamp TIMESTAMPTZ,
    desktop_ready_timestamp TIMESTAMPTZ,
    system_settled_timestamp TIMESTAMPTZ,
    boot_to_ready_seconds FLOAT,
    login_to_ready_seconds FLOAT,
    login_items JSONB,
    total_login_items INTEGER,
    slowest_login_item VARCHAR(255),
    slowest_login_item_seconds FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_startup_device ON startup_reports(device_id, boot_timestamp DESC);

CREATE TABLE IF NOT EXISTS app_daily_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    total_active_hours FLOAT,
    total_app_switches INTEGER,
    top_foreground_app VARCHAR(255),
    top_foreground_app_minutes FLOAT,
    top_cpu_app VARCHAR(255),
    top_cpu_app_avg FLOAT,
    top_memory_app VARCHAR(255),
    top_memory_app_avg_mb FLOAT,
    top_energy_app VARCHAR(255),
    lowest_health_app VARCHAR(255),
    lowest_health_score FLOAT,
    avg_responsiveness_score FLOAT,
    memory_pressure_minutes FLOAT,
    UNIQUE(device_id, date)
);

CREATE TABLE IF NOT EXISTS app_network_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    app_name VARCHAR(255),
    app_bundle_id VARCHAR(255),
    flag_type VARCHAR(50) NOT NULL,
    bytes_sent BIGINT,
    bytes_received BIGINT,
    connections INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_network_flags_device ON app_network_flags(device_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS productivity_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    week_start DATE NOT NULL,
    productive_app_minutes FLOAT,
    neutral_app_minutes FLOAT,
    unproductive_app_minutes FLOAT,
    total_active_minutes FLOAT,
    productivity_ratio FLOAT,
    context_switch_rate FLOAT,
    avg_session_length_minutes FLOAT,
    peak_productivity_hour INTEGER,
    lowest_productivity_hour INTEGER,
    device_health_impact_minutes FLOAT,
    UNIQUE(device_id, week_start)
);

CREATE TABLE IF NOT EXISTS app_classifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(100) NOT NULL,
    app_bundle_id VARCHAR(255) NOT NULL,
    app_name VARCHAR(255),
    classification VARCHAR(20) NOT NULL,
    classified_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, app_bundle_id)
);

CREATE TABLE IF NOT EXISTS ai_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    recommendation_text TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,
    priority VARCHAR(10) NOT NULL,
    supporting_data JSONB,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    dismissed_at TIMESTAMPTZ,
    actioned_at TIMESTAMPTZ,
    actioned_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_ai_recommendations_device ON ai_recommendations(device_id, generated_at DESC);
