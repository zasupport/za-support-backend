"""
SQLAlchemy ORM models for Health Check v11.
Includes diagnostic upload table for za_diag_v3.sh integration.
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, JSON, Text, Boolean,
    ForeignKey, Index, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from datetime import datetime
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
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    registered_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    metadata_ = Column("metadata", JSON, nullable=True)

    health_records = relationship("HealthData", back_populates="device", lazy="dynamic")
    alerts = relationship("Alert", back_populates="device", lazy="dynamic")


# ---------- Health Telemetry ----------

class HealthData(Base):
    __tablename__ = "health_data"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String(128), ForeignKey("devices.machine_id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
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
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
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
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
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
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_diag_serial_captured", "serial_number", "captured_at"),
        Index("ix_diag_client_captured", "client_id", "captured_at"),
    )
