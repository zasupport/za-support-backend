"""
Health Check AI — ISP Outage Monitor Schemas
Pydantic models for API requests, responses, and internal data passing.

Updated: Networking Integrations — added check methods for Cloudflare Radar,
IODA, RIPE Atlas, Statuspage API, Webhooks, and BGP Looking Glass.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# -------------------------------------------------------
# Enums
# -------------------------------------------------------
class CheckMethod(str, Enum):
    # Original detection methods
    STATUS_PAGE = "status_page"
    DOWNDETECTOR = "downdetector"
    PING = "ping"
    HTTP = "http"
    AGENT = "agent"

    # === Networking Integrations ===
    CLOUDFLARE_RADAR = "cloudflare_radar"       # Cloudflare Radar traffic anomalies
    IODA = "ioda"                                # CAIDA/Georgia Tech outage detection
    RIPE_ATLAS = "ripe_atlas"                    # RIPE Atlas probe measurements
    STATUSPAGE_API = "statuspage_api"            # Statuspage.io structured JSON API
    WEBHOOK = "webhook"                          # Inbound ISP webhook push
    BGP_LOOKING_GLASS = "bgp_looking_glass"      # BGP route health via RIPE RIS


class OutageSeverity(str, Enum):
    DEGRADED = "degraded"       # packet loss, high latency
    PARTIAL = "partial"         # some services affected
    FULL = "full"               # complete outage
    UNKNOWN = "unknown"


class ConnectionType(str, Enum):
    FIBRE = "fibre"
    DSL = "dsl"
    LTE = "lte"
    WIRELESS = "wireless"
    SATELLITE = "satellite"


# -------------------------------------------------------
# ISP Registry
# -------------------------------------------------------
class ISPBase(BaseModel):
    isp_name: str
    isp_slug: str
    status_page_url: Optional[str] = None
    support_phone: Optional[str] = None
    support_email: Optional[str] = None
    check_enabled: bool = True
    check_interval: int = 300


class ISPCreate(ISPBase):
    pass


class ISPResponse(ISPBase):
    isp_id: int
    region: str = "ZA"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# -------------------------------------------------------
# Client-ISP Mapping
# -------------------------------------------------------
class ClientISPCreate(BaseModel):
    client_id: int
    isp_id: int
    account_ref: Optional[str] = None
    circuit_id: Optional[str] = None
    connection_type: Optional[ConnectionType] = None
    ip_address: Optional[str] = None
    gateway_ip: Optional[str] = None
    site_name: Optional[str] = None
    is_primary: bool = True


class ClientISPResponse(ClientISPCreate):
    client_isp_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# -------------------------------------------------------
# Status Check Results
# -------------------------------------------------------
class StatusCheckResult(BaseModel):
    """Internal model for a single check result."""
    isp_id: int
    check_method: CheckMethod
    is_up: Optional[bool] = None
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None
    status_code: Optional[int] = None
    raw_status: Optional[str] = None
    error_message: Optional[str] = None
    source: str = "healthcheck-v11"


class StatusCheckResponse(BaseModel):
    check_time: datetime
    isp_id: int
    isp_name: str
    check_method: str
    is_up: Optional[bool]
    latency_ms: Optional[float]
    packet_loss_pct: Optional[float]
    raw_status: Optional[str]


# -------------------------------------------------------
# Outage Events
# -------------------------------------------------------
class OutageEventCreate(BaseModel):
    isp_id: int
    severity: OutageSeverity = OutageSeverity.UNKNOWN
    detection_method: Optional[str] = None
    affected_region: Optional[str] = None
    notes: Optional[str] = None
    auto_detected: bool = True


class OutageEventUpdate(BaseModel):
    ended_at: Optional[datetime] = None
    severity: Optional[OutageSeverity] = None
    isp_ref_number: Optional[str] = None
    isp_eta: Optional[datetime] = None
    notes: Optional[str] = None


class OutageEventResponse(BaseModel):
    outage_id: int
    isp_id: int
    isp_name: str
    started_at: datetime
    ended_at: Optional[datetime]
    duration_mins: Optional[int]
    severity: str
    detection_method: Optional[str]
    affected_region: Optional[str]
    isp_ref_number: Optional[str]
    isp_eta: Optional[datetime]
    notes: Optional[str]
    auto_detected: bool
    affected_clients: List[str] = []

    class Config:
        from_attributes = True


# -------------------------------------------------------
# Agent Connectivity Report (from Health Check agents)
# -------------------------------------------------------
class AgentConnectivityReport(BaseModel):
    """Sent by Health Check agent on each device."""
    device_id: int
    client_id: int
    is_online: bool
    wan_ip: Optional[str] = None
    gateway_ip: Optional[str] = None
    gateway_ping_ms: Optional[float] = None
    dns_resolves: Optional[bool] = None
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None


# -------------------------------------------------------
# Dashboard / Summary
# -------------------------------------------------------
class ISPCurrentStatus(BaseModel):
    """Real-time ISP status for dashboard."""
    isp_id: int
    isp_name: str
    isp_slug: str
    is_up: Optional[bool]
    last_checked: Optional[datetime]
    latency_ms: Optional[float]
    packet_loss_pct: Optional[float]
    active_outage: Optional[OutageEventResponse] = None
    affected_client_count: int = 0
    status_label: str = "Unknown"               # "Online", "Degraded", "Down", "Unknown"
    check_methods_reporting: List[str] = []


class ISPDashboardResponse(BaseModel):
    """Full dashboard payload."""
    timestamp: datetime
    total_isps_monitored: int
    isps_up: int
    isps_degraded: int
    isps_down: int
    isps_unknown: int
    active_outages: int
    statuses: List[ISPCurrentStatus]


# -------------------------------------------------------
# Alert Payloads
# -------------------------------------------------------
class OutageAlert(BaseModel):
    """Payload sent to alert channels."""
    alert_type: str = "isp_outage"              # "isp_outage", "isp_degraded", "isp_restored"
    isp_name: str
    isp_slug: str
    severity: str
    started_at: datetime
    detection_method: str
    affected_clients: List[str]
    message: str
    outage_id: int


# -------------------------------------------------------
# Networking Integration — Webhook Inbound
# -------------------------------------------------------
class ISPWebhookPayload(BaseModel):
    """Generic inbound webhook payload from ISPs."""
    status: Optional[str] = None                # "up", "down", "degraded", "maintenance"
    message: Optional[str] = None
    severity: Optional[str] = None              # "critical", "major", "minor", "none"
    affected_services: Optional[List[str]] = None
    incident_id: Optional[str] = None
    started_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class ProviderHealthResponse(BaseModel):
    """Response from country-level health check endpoint."""
    timestamp: datetime
    country: str = "ZA"
    cloudflare_status: Optional[str] = None
    ioda_status: Optional[str] = None
    active_country_alerts: int = 0
    details: Optional[dict] = None
