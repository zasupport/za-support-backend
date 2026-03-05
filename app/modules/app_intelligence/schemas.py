from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime


class ProcessMetricsEntry(BaseModel):
    app_name: Optional[str] = None
    app_bundle_id: Optional[str] = None
    timestamp: datetime
    cpu_avg_percent: Optional[float] = None
    cpu_peak_percent: Optional[float] = None
    memory_avg_mb: Optional[float] = None
    memory_peak_mb: Optional[float] = None
    disk_read_mb: Optional[float] = None
    disk_write_mb: Optional[float] = None
    net_sent_mb: Optional[float] = None
    net_recv_mb: Optional[float] = None
    energy_impact_avg: Optional[float] = None
    foreground_seconds: Optional[int] = None
    is_foreground: Optional[bool] = None
    thread_count_avg: Optional[float] = None
    responsiveness_score: Optional[float] = None
    slow_interactions: Optional[int] = None
    unresponsive_interactions: Optional[int] = None


class AppMetricsReport(BaseModel):
    device_id: str
    client_id: str
    metrics: List[ProcessMetricsEntry]


class StartupReport(BaseModel):
    device_id: str
    client_id: str
    boot_timestamp: Optional[datetime] = None
    login_timestamp: Optional[datetime] = None
    desktop_ready_timestamp: Optional[datetime] = None
    system_settled_timestamp: Optional[datetime] = None
    boot_to_ready_seconds: Optional[float] = None
    login_to_ready_seconds: Optional[float] = None
    login_items: Optional[List[Any]] = None
    total_login_items: Optional[int] = None
    slowest_login_item: Optional[str] = None
    slowest_login_item_seconds: Optional[float] = None


class AppHealthScoreResponse(BaseModel):
    device_id: str
    date: str
    app_name: str
    app_bundle_id: Optional[str]
    health_score: Optional[float]
    crash_score: Optional[float]
    hang_score: Optional[float]
    cpu_score: Optional[float]
    memory_score: Optional[float]
    energy_score: Optional[float]
    background_score: Optional[float]
    crash_count: Optional[int]
    hang_count: Optional[int]
    total_foreground_minutes: Optional[float]
    total_background_minutes: Optional[float]

    class Config:
        from_attributes = True


class AppRankingEntry(BaseModel):
    app_name: Optional[str]
    app_bundle_id: Optional[str]
    avg_cpu: Optional[float]
    avg_memory_mb: Optional[float]
    avg_energy: Optional[float]
    total_foreground_minutes: Optional[float]
    avg_health_score: Optional[float]
    sample_count: int


class ResourceTimelinePoint(BaseModel):
    timestamp: datetime
    cpu_avg_percent: Optional[float]
    memory_avg_mb: Optional[float]
    energy_impact_avg: Optional[float]
    disk_read_mb: Optional[float]
    disk_write_mb: Optional[float]


class ForegroundBreakdownEntry(BaseModel):
    app_name: Optional[str]
    app_bundle_id: Optional[str]
    total_foreground_minutes: float
    session_count: int


class ProductivitySummary(BaseModel):
    device_id: str
    week_start: str
    productive_app_minutes: Optional[float]
    neutral_app_minutes: Optional[float]
    unproductive_app_minutes: Optional[float]
    total_active_minutes: Optional[float]
    productivity_ratio: Optional[float]
    context_switch_rate: Optional[float]
    avg_session_length_minutes: Optional[float]
    peak_productivity_hour: Optional[int]
    lowest_productivity_hour: Optional[int]
    device_health_impact_minutes: Optional[float]


class AppClassificationCreate(BaseModel):
    app_bundle_id: str
    app_name: Optional[str] = None
    classification: str  # productive, neutral, unproductive
    classified_by: Optional[str] = "courtney"
