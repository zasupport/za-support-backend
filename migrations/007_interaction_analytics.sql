-- Interaction Analytics: keystroke dynamics, mouse behavior, frustration scoring
-- POPIA compliant — no content captured, behavioral timing only
-- device_id and client_id are VARCHAR — no FK constraint

CREATE TABLE IF NOT EXISTS interaction_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    foreground_app VARCHAR(255),
    foreground_app_bundle_id VARCHAR(255),
    app_duration_seconds INTEGER,
    app_switch_count INTEGER,
    typing_speed_wpm FLOAT,
    backspace_ratio FLOAT,
    avg_dwell_time_ms FLOAT,
    avg_flight_time_ms FLOAT,
    typing_cadence_variance FLOAT,
    burst_count INTEGER,
    pause_count INTEGER,
    pause_avg_duration_ms FLOAT,
    modifier_ratio FLOAT,
    active_typing_minutes FLOAT,
    total_clicks INTEGER,
    rage_click_count INTEGER,
    dead_click_count INTEGER,
    double_click_accuracy FLOAT,
    click_to_action_latency_avg_ms FLOAT,
    cursor_distance_px FLOAT,
    cursor_speed_avg FLOAT,
    direction_changes INTEGER,
    scroll_distance_px FLOAT,
    scroll_reversals INTEGER,
    hover_events INTEGER,
    hesitation_events INTEGER,
    abandoned_actions INTEGER,
    avg_hesitation_ms FLOAT,
    frustration_score FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interaction_metrics_device ON interaction_metrics(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_interaction_metrics_client ON interaction_metrics(client_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_interaction_metrics_frustration ON interaction_metrics(device_id, frustration_score) WHERE frustration_score > 60;

CREATE TABLE IF NOT EXISTS interaction_daily_summary (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    foreground_app VARCHAR(255),
    total_active_minutes FLOAT,
    avg_typing_speed_wpm FLOAT,
    avg_backspace_ratio FLOAT,
    total_rage_clicks INTEGER,
    total_dead_clicks INTEGER,
    total_hesitation_events INTEGER,
    total_abandoned_actions INTEGER,
    avg_frustration_score FLOAT,
    peak_frustration_score FLOAT,
    peak_frustration_time TIMESTAMPTZ,
    peak_frustration_app VARCHAR(255),
    typing_cadence_trend VARCHAR(20),
    UNIQUE(device_id, date, foreground_app)
);

CREATE INDEX IF NOT EXISTS idx_interaction_daily_device ON interaction_daily_summary(device_id, date DESC);

CREATE TABLE IF NOT EXISTS interaction_baselines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    baseline_mean FLOAT,
    baseline_stddev FLOAT,
    sample_count INTEGER,
    last_updated TIMESTAMPTZ,
    UNIQUE(device_id, metric_name)
);

CREATE TABLE IF NOT EXISTS frustration_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(100) NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    foreground_app VARCHAR(255),
    frustration_score FLOAT NOT NULL,
    primary_signals JSONB,
    duration_seconds INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_frustration_events_device ON frustration_events(device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_frustration_events_score ON frustration_events(frustration_score DESC);
