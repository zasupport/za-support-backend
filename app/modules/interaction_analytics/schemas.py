from pydantic import BaseModel
from typing import Optional, List, Any, Dict, Union
from datetime import datetime


class InteractionDataPoint(BaseModel):
    timestamp: datetime
    foreground_app: Optional[str] = None
    foreground_app_bundle_id: Optional[str] = None
    app_duration_seconds: Optional[int] = None
    app_switch_count: Optional[int] = None
    typing_speed_wpm: Optional[float] = None
    backspace_ratio: Optional[float] = None
    avg_dwell_time_ms: Optional[float] = None
    avg_flight_time_ms: Optional[float] = None
    typing_cadence_variance: Optional[float] = None
    burst_count: Optional[int] = None
    pause_count: Optional[int] = None
    pause_avg_duration_ms: Optional[float] = None
    modifier_ratio: Optional[float] = None
    active_typing_minutes: Optional[float] = None
    total_clicks: Optional[int] = None
    rage_click_count: Optional[int] = None
    dead_click_count: Optional[int] = None
    double_click_accuracy: Optional[float] = None
    click_to_action_latency_avg_ms: Optional[float] = None
    cursor_distance_px: Optional[float] = None
    cursor_speed_avg: Optional[float] = None
    direction_changes: Optional[int] = None
    scroll_distance_px: Optional[float] = None
    scroll_reversals: Optional[int] = None
    hover_events: Optional[int] = None
    hesitation_events: Optional[int] = None
    abandoned_actions: Optional[int] = None
    avg_hesitation_ms: Optional[float] = None
    frustration_score: Optional[float] = None


class InteractionReport(BaseModel):
    device_id: str
    client_id: str
    data: Union[List[InteractionDataPoint], InteractionDataPoint]


class InteractionSummaryResponse(BaseModel):
    device_id: str
    period_days: int
    avg_typing_speed_wpm: Optional[float]
    avg_backspace_ratio: Optional[float]
    avg_frustration_score: Optional[float]
    peak_frustration_score: Optional[float]
    total_rage_clicks: Optional[int]
    total_dead_clicks: Optional[int]
    total_hesitation_events: Optional[int]
    total_abandoned_actions: Optional[int]
    total_active_minutes: Optional[float]
    sample_count: int


class FrustrationTimelinePoint(BaseModel):
    timestamp: datetime
    frustration_score: Optional[float]
    foreground_app: Optional[str]


class AppBreakdownEntry(BaseModel):
    foreground_app: Optional[str]
    foreground_app_bundle_id: Optional[str]
    avg_frustration_score: Optional[float]
    avg_typing_speed_wpm: Optional[float]
    total_rage_clicks: Optional[int]
    total_dead_clicks: Optional[int]
    total_active_minutes: Optional[float]
    sample_count: int


class TypingTrendPoint(BaseModel):
    date: str
    avg_typing_speed_wpm: Optional[float]
    avg_backspace_ratio: Optional[float]
    avg_cadence_variance: Optional[float]


class AnomalyEntry(BaseModel):
    timestamp: datetime
    metric_name: str
    observed_value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    foreground_app: Optional[str]


class FleetSummaryEntry(BaseModel):
    device_id: str
    avg_frustration_score: Optional[float]
    peak_frustration_score: Optional[float]
    total_rage_clicks: Optional[int]
    avg_typing_speed_wpm: Optional[float]
    sample_count: int
