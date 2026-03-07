"""
SQLAlchemy ORM models for Health Check AI.
Includes diagnostic upload table for za_diag_v3.sh integration.
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, Text, Boolean,
    ForeignKey, Index, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from app.core.database import Base


# ---------- Enums ----------

class AlertSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    WARNING = "warning"
    INFO = "info"


class DeviceType(str, enum.Enum):
    MAC_DESKTOP = "mac_desktop"
    MAC_LAPTOP = "mac_laptop"
    IPHONE = "iphone"
    IPAD = "ipad"
    OTHER = "other"


# ---------- Device Registry ----------

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String(128), unique=True, nullable=False, index=True)
    client_id = Column(String(128), nullable=True, index=True)
    hostname = Column(String(256), nullable=True)
    device_type = Column(String(32), default=DeviceType.OTHER.value)
    model_identifier = Column(String(128), nullable=True)
    serial_number = Column(String(64), nullable=True, index=True)
    os_version = Column(String(64), nullable=True)
    agent_version = Column(String(32), nullable=True)
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSON, nullable=True)

    health_records = relationship("HealthData", back_populates="device", lazy="dynamic")
    alerts = relationship("Alert", back_populates="device", lazy="dynamic")


# ---------- Health Telemetry ----------

class HealthData(Base):
    __tablename__ = "health_data"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String(128), ForeignKey("devices.machine_id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    cpu_percent = Column(Float)
    memory_percent = Column(Float)
    disk_percent = Column(Float)
    battery_percent = Column(Float, nullable=True)
    battery_cycle_count = Column(Integer, nullable=True)
    battery_health = Column(String(32), nullable=True)
    threat_score = Column(Integer, default=0)
    uptime_hours = Column(Float, nullable=True)
    network_up_mbps = Column(Float, nullable=True)
    network_down_mbps = Column(Float, nullable=True)
    encrypted_raw = Column(Text, nullable=True)
    raw_data = Column(JSON, nullable=True)

    device = relationship("Device", back_populates="health_records")

    __table_args__ = (
        Index("ix_health_machine_ts", "machine_id", "timestamp"),
    )


# ---------- Network Telemetry ----------

class NetworkData(Base):
    __tablename__ = "network_data"

    id = Column(Integer, primary_key=True, index=True)
    controller_id = Column(String(128), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    total_clients = Column(Integer)
    total_devices = Column(Integer)
    wan_status = Column(String(16), nullable=True)
    wan_latency_ms = Column(Float, nullable=True)
    raw_data = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_network_controller_ts", "controller_id", "timestamp"),
    )


# ---------- Alerts ----------

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String(128), ForeignKey("devices.machine_id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    severity = Column(String(16), default=AlertSeverity.INFO.value)
    category = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", JSON, nullable=True)

    device = relationship("Device", back_populates="alerts")

    __table_args__ = (
        Index("ix_alert_machine_sev", "machine_id", "severity"),
    )


# ══════════════════════════════════════════════════════════════
# NEW: Workshop Diagnostics — receives za_diag_v3.sh JSON output
# ══════════════════════════════════════════════════════════════

class WorkshopDiagnostic(Base):
    """
    Stores deep diagnostic snapshots from za_diag_v3.sh.
    One row per diagnostic run per device.
    The raw_json column stores the complete JSON payload.
    Indexed summary columns enable fast queries without JSONB parsing.
    """
    __tablename__ = "workshop_diagnostics"

    id = Column(Integer, primary_key=True, index=True)

    # Identity
    serial_number = Column(String(64), nullable=False, index=True)
    hostname = Column(String(256), nullable=True)
    client_id = Column(String(128), nullable=True, index=True)
    diagnostic_version = Column(String(16), nullable=True)  # "3.0"
    mode = Column(String(16), nullable=True)  # "full" or "quick"

    # Hardware summary (indexed for fast queries)
    chip_type = Column(String(32), nullable=True)  # APPLE_SILICON or INTEL
    model_name = Column(String(128), nullable=True)
    model_identifier = Column(String(64), nullable=True)
    ram_gb = Column(Integer, nullable=True)
    ram_upgradeable = Column(String(128), nullable=True)
    cpu_name = Column(String(128), nullable=True)
    cores_physical = Column(Integer, nullable=True)
    cores_logical = Column(Integer, nullable=True)

    # macOS
    macos_version = Column(String(32), nullable=True)
    macos_build = Column(String(32), nullable=True)
    uptime_seconds = Column(Integer, nullable=True)

    # Security (indexed — critical for compliance reporting)
    sip_enabled = Column(Boolean, nullable=True)
    filevault_on = Column(Boolean, nullable=True)
    firewall_on = Column(Boolean, nullable=True)
    gatekeeper_on = Column(Boolean, nullable=True)
    xprotect_version = Column(String(32), nullable=True)
    password_manager = Column(String(64), nullable=True)
    av_edr = Column(String(128), nullable=True)

    # Battery (indexed — drives replacement recommendations)
    battery_health_pct = Column(Float, nullable=True)
    battery_cycles = Column(Integer, nullable=True)
    battery_design_capacity = Column(Integer, nullable=True)
    battery_max_capacity = Column(Integer, nullable=True)
    battery_condition = Column(String(32), nullable=True)

    # Storage (indexed — drives cleanup/upgrade recommendations)
    disk_used_pct = Column(Integer, nullable=True)
    disk_free_gb = Column(Integer, nullable=True)

    # OCLP
    oclp_detected = Column(Boolean, default=False)
    oclp_version = Column(String(32), nullable=True)
    oclp_root_patched = Column(Boolean, default=False)
    third_party_kexts = Column(Integer, default=0)

    # Diagnostics summary
    kernel_panics = Column(Integer, default=0)
    total_processes = Column(Integer, nullable=True)

    # Intelligence engine output
    recommendations = Column(JSON, nullable=True)  # Array of recommendation objects
    recommendation_count = Column(Integer, default=0)

    # Full payload
    raw_json = Column(JSON, nullable=True)  # Complete za_diag_v3.sh JSON
    runtime_seconds = Column(Integer, nullable=True)

    # Timestamps
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_diag_serial_captured", "serial_number", "captured_at"),
        Index("ix_diag_client_captured", "client_id", "captured_at"),
    )


# ══════════════════════════════════════════════════════════════
# ISP Outage Monitor — 4-layer detection for SA ISPs
# ══════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════
# Agent Router — heartbeat telemetry + diagnostic report storage
# ══════════════════════════════════════════════════════════════

class AgentHeartbeatRecord(Base):
    """
    60-second telemetry from Mac agents.
    TimescaleDB hypertable with 1-day chunks, 90-day retention.
    """
    __tablename__ = "agent_heartbeats"

    id = Column(Integer, primary_key=True, index=True)
    serial = Column(String(64), nullable=False, index=True)
    hostname = Column(String(256), nullable=True)
    client_id = Column(String(128), nullable=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Telemetry
    cpu_load = Column(Float, nullable=True)
    memory_pressure = Column(Float, nullable=True)
    disk_used_pct = Column(Float, nullable=True)
    battery = Column(Float, nullable=True)

    # Security posture
    sip_enabled = Column(Boolean, nullable=True)
    filevault_on = Column(Boolean, nullable=True)
    firewall_on = Column(Boolean, nullable=True)
    gatekeeper_on = Column(Boolean, nullable=True)

    __table_args__ = (
        Index("ix_agent_hb_serial_ts", "serial", "timestamp"),
        Index("ix_agent_hb_client_ts", "client_id", "timestamp"),
    )


class DiagnosticReport(Base):
    """
    Full diagnostic JSON uploads from za_diag_v3.sh via agent.
    JSONB payload with GIN index for deep querying.
    """
    __tablename__ = "diagnostic_reports"

    id = Column(Integer, primary_key=True, index=True)
    serial = Column(String(64), nullable=False, index=True)
    hostname = Column(String(256), nullable=True)
    client_id = Column(String(128), nullable=True, index=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    payload = Column(JSON, nullable=False)  # Full za_diag_v3.sh JSON

    __table_args__ = (
        Index("ix_diag_report_serial_ts", "serial", "uploaded_at"),
    )


class ISPStatus(str, enum.Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    OUTAGE = "outage"
    UNKNOWN = "unknown"


class CheckSource(str, enum.Enum):
    STATUS_PAGE = "status_page"
    DOWNDETECTOR = "downdetector"
    HTTP_PROBE = "http_probe"
    AGENT_CONNECTIVITY = "agent_connectivity"


class ConnectivityState(str, enum.Enum):
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class ISPProvider(Base):
    """Pre-seeded South African ISP providers."""
    __tablename__ = "isp_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    status_page_url = Column(String(512), nullable=True)
    downdetector_slug = Column(String(128), nullable=True)
    probe_targets = Column(JSON, nullable=True)  # List of URLs to probe
    gateway_ip = Column(String(45), nullable=True)
    underlying_provider = Column(String(128), nullable=True)
    current_status = Column(String(16), default=ISPStatus.OPERATIONAL.value)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    status_checks = relationship("ISPStatusCheck", back_populates="provider", lazy="dynamic")
    connectivity_records = relationship("AgentConnectivity", back_populates="provider", lazy="dynamic")
    outages = relationship("ISPOutage", back_populates="provider", lazy="dynamic")


class ISPStatusCheck(Base):
    """Time-series check results from all detection layers."""
    __tablename__ = "isp_status_checks"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("isp_providers.id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    source = Column(String(32), nullable=False)  # CheckSource value
    status = Column(String(16), default=ISPStatus.OPERATIONAL.value)
    response_time_ms = Column(Float, nullable=True)
    http_status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    is_healthy = Column(Boolean, default=True)

    provider = relationship("ISPProvider", back_populates="status_checks")

    __table_args__ = (
        Index("ix_isp_check_provider_ts", "provider_id", "timestamp"),
        Index("ix_isp_check_source_ts", "source", "timestamp"),
    )


class AgentConnectivity(Base):
    """Agent heartbeat tracking for ISP connectivity."""
    __tablename__ = "agent_connectivity"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String(128), ForeignKey("devices.machine_id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("isp_providers.id"), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    state = Column(String(16), default=ConnectivityState.CONNECTED.value)
    latency_ms = Column(Float, nullable=True)
    packet_loss_pct = Column(Float, nullable=True)
    gateway_reachable = Column(Boolean, nullable=True)
    dns_reachable = Column(Boolean, nullable=True)

    provider = relationship("ISPProvider", back_populates="connectivity_records")

    __table_args__ = (
        Index("ix_agent_conn_machine_ts", "machine_id", "timestamp"),
        Index("ix_agent_conn_provider_ts", "provider_id", "timestamp"),
    )


class ISPOutage(Base):
    """Confirmed outage events."""
    __tablename__ = "isp_outages"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("isp_providers.id"), nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    ended_at = Column(DateTime, nullable=True)
    severity = Column(String(16), default=ISPStatus.OUTAGE.value)
    confirmed = Column(Boolean, default=False)
    confirmation_sources = Column(JSON, nullable=True)  # List of source names
    description = Column(Text, nullable=True)
    auto_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    provider = relationship("ISPProvider", back_populates="outages")


# ══════════════════════════════════════════════════════════════
# Automation Layer — Event Bus, Scheduler, Monitors
# ══════════════════════════════════════════════════════════════

class SystemEvent(Base):
    """Central event bus — every automation action produces an event."""
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    source = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), default="info")
    summary = Column(Text, nullable=False)
    detail = Column(JSON, nullable=True)
    device_serial = Column(String(64), nullable=True, index=True)
    client_id = Column(String(128), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index("ix_sysevent_type_created", "event_type", "created_at"),
        Index("ix_sysevent_source_created", "source", "created_at"),
    )


class ScheduledJob(Base):
    """Registry of scheduled automation jobs."""
    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    schedule = Column(String(128), nullable=False)
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    last_status = Column(String(16), default="pending")
    last_error = Column(Text, nullable=True)
    run_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_schedjob_enabled", "enabled"),
    )


class PatchStatus(Base):
    """macOS patch/update status per device."""
    __tablename__ = "patch_status"

    id = Column(Integer, primary_key=True, index=True)
    device_serial = Column(String(64), nullable=False, index=True)
    client_id = Column(String(128), nullable=True, index=True)
    current_os = Column(String(32), nullable=True)
    latest_os = Column(String(32), nullable=True)
    pending_updates = Column(JSON, nullable=True)
    days_behind = Column(Integer, default=0)
    last_checked = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notified_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_patch_serial_checked", "device_serial", "last_checked"),
    )


class BackupStatus(Base):
    """Backup health per device — Time Machine + third-party agents."""
    __tablename__ = "backup_status"

    id = Column(Integer, primary_key=True, index=True)
    device_serial = Column(String(64), nullable=False, index=True)
    client_id = Column(String(128), nullable=True, index=True)
    time_machine_enabled = Column(Boolean, nullable=True)
    last_tm_backup = Column(DateTime, nullable=True)
    tm_days_stale = Column(Integer, default=0)
    third_party_agent = Column(String(64), nullable=True)
    third_party_last_backup = Column(DateTime, nullable=True)
    no_backup = Column(Boolean, default=False)
    last_checked = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notified_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_backup_serial_checked", "device_serial", "last_checked"),
    )


class NotificationLog(Base):
    """Audit trail of all notifications sent."""
    __tablename__ = "notification_log"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String(16), nullable=False)  # email, slack
    recipient = Column(String(256), nullable=True)
    subject = Column(String(512), nullable=True)
    event_id = Column(Integer, nullable=True)
    status = Column(String(16), default="sent")
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


# ══════════════════════════════════════════════════════════════
# UniFi Network Integration — under Network module
# Supports: UniFi Express 7, UniFi Cloud (api.ui.com)
# Clients: Dr Evan Shoul (gateway 192.168.1.252), Charles Chemel
# ══════════════════════════════════════════════════════════════

class UniFiSnapshot(Base):
    """
    Time-series WAN + client + device snapshot per poll cycle (default 5 min).
    Populated by the cloud poller (api.ui.com) or local poller script.
    """
    __tablename__ = "unifi_snapshots"

    id               = Column(String(36), primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    client_id        = Column(String(100), nullable=False, index=True)
    controller_id    = Column(String(128), nullable=False, index=True)
    polled_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    source           = Column(String(20), default="local")      # 'cloud' | 'local'
    wan_status       = Column(String(20))                       # 'online' | 'offline' | 'unknown'
    wan_ip           = Column(String(45))
    wan_rx_bytes     = Column(Integer)
    wan_tx_bytes     = Column(Integer)
    wan_rx_mbps      = Column(Float)
    wan_tx_mbps      = Column(Float)
    wan_latency_ms   = Column(Float)
    connected_clients  = Column(Integer)
    wireless_clients   = Column(Integer)
    wired_clients      = Column(Integer)
    devices_total      = Column(Integer)
    devices_online     = Column(Integer)
    site_name          = Column(String(200))
    uptime_seconds     = Column(Integer)
    raw_json           = Column(JSON)

    __table_args__ = (
        Index("ix_unifi_snapshots_client_ts",     "client_id",     "polled_at"),
        Index("ix_unifi_snapshots_controller_ts", "controller_id", "polled_at"),
    )


class UniFiDeviceState(Base):
    """
    Latest known state per physical UniFi device (gateway, switch, AP).
    Upserted on every poll — one row per MAC address per client.
    """
    __tablename__ = "unifi_device_state"

    id               = Column(String(36), primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    client_id        = Column(String(100), nullable=False, index=True)
    controller_id    = Column(String(128), nullable=False)
    mac              = Column(String(20), nullable=False)
    name             = Column(String(200))
    model            = Column(String(100))
    type             = Column(String(50))     # 'ugw' | 'usw' | 'uap' | 'udm'
    ip               = Column(String(45))
    status           = Column(String(20))     # 'online' | 'offline' | 'adopting'
    uptime_seconds   = Column(Integer)
    firmware_version = Column(String(50))
    last_seen        = Column(DateTime)
    updated_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_unifi_device_client", "client_id"),
        __import__("sqlalchemy").UniqueConstraint("client_id", "mac", name="uq_unifi_device_client_mac"),
    )


class UniFiControllerConfig(Base):
    """
    Per-client UniFi controller credentials and polling configuration.
    Passwords stored encrypted via app encryption key.
    """
    __tablename__ = "unifi_controller_config"

    id                = Column(String(36), primary_key=True, default=lambda: str(__import__("uuid").uuid4()))
    client_id         = Column(String(100), nullable=False, unique=True)
    controller_host   = Column(String(255), nullable=False)   # e.g. 192.168.1.252
    controller_port   = Column(Integer, default=443)
    username          = Column(Text)
    password_enc      = Column(Text)                          # Fernet encrypted
    cloud_api_key_enc = Column(Text)                          # UI.com API key, encrypted
    site_name         = Column(String(100), default="default")
    poll_interval_sec = Column(Integer, default=300)
    enabled           = Column(Boolean, default=True)
    notes             = Column(Text)
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
