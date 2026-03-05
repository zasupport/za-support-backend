"""
Pydantic models for the Compromised Data Scanner Module.
Covers: findings, scan sessions, threat intel corroboration, reports.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class FindingSeverity(str, Enum):
    CRITICAL = "critical"    # Confirmed malware, active C2, data exfiltration
    HIGH = "high"            # Strong IOC match, unsigned persistent binary
    MEDIUM = "medium"        # Suspicious but unconfirmed, known-vulnerable app
    LOW = "low"              # Informational, minor anomaly
    INFO = "info"            # Context — not a threat but worth noting


class FindingCategory(str, Enum):
    MALWARE = "malware"                    # Confirmed malicious software
    SUSPICIOUS_FILE = "suspicious_file"    # File with IOC characteristics
    SUSPICIOUS_EMAIL = "suspicious_email"  # Dodgy attachment or phishing
    COMPROMISED_APP = "compromised_app"    # Known-vulnerable or malicious app
    PERSISTENCE = "persistence"            # Startup/launch agent/cron anomaly
    BROWSER_EXTENSION = "browser_extension"
    SUSPICIOUS_PROCESS = "suspicious_process"
    NETWORK_ANOMALY = "network_anomaly"    # C2 connection, exfil pattern
    DATA_EXFILTRATION = "data_exfiltration"
    CRYPTO_MINER = "crypto_miner"
    REMOTE_ACCESS = "remote_access"        # Unauthorized RAT/RDP/VNC
    MACRO_PAYLOAD = "macro_payload"        # Office macro with payload
    PHISHING = "phishing"                  # Phishing indicator
    ROOTKIT = "rootkit"
    ADWARE = "adware"
    PUP = "pup"                            # Potentially unwanted program


class CorroborationStatus(str, Enum):
    CONFIRMED_MALICIOUS = "confirmed_malicious"
    LIKELY_MALICIOUS = "likely_malicious"
    SUSPICIOUS = "suspicious"
    LIKELY_BENIGN = "likely_benign"
    CONFIRMED_BENIGN = "confirmed_benign"
    UNKNOWN = "unknown"
    PENDING = "pending"


class ScanScope(str, Enum):
    FULL = "full"              # Everything — filesystem, apps, email, network, processes
    FILESYSTEM = "filesystem"  # Files and folders only
    EMAIL = "email"            # Email stores and attachments only
    APPS = "apps"              # Installed apps, plugins, extensions
    PERSISTENCE = "persistence"  # Startup items, launch agents, cron
    NETWORK = "network"        # Active connections, DNS, processes
    QUICK = "quick"            # High-priority checks only (known malware paths, persistence, processes)


class ScanStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CORROBORATING = "corroborating"  # Findings found, checking threat intel
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConsentStatus(str, Enum):
    GRANTED = "granted"
    REVOKED = "revoked"
    PENDING = "pending"


class ThreatIntelSource(str, Enum):
    VIRUSTOTAL = "virustotal"
    ABUSE_IPDB = "abuse_ipdb"
    YARA = "yara"
    HASH_DB = "hash_db"
    MITRE_ATTACK = "mitre_attack"
    HAVE_I_BEEN_PWNED = "have_i_been_pwned"
    MANUAL = "manual"


class OSPlatform(str, Enum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"


# ---------------------------------------------------------------------------
# Core finding model — every scanner produces these
# ---------------------------------------------------------------------------

class RawFinding(BaseModel):
    """A single finding produced by any scanner before corroboration."""
    category: FindingCategory
    severity: FindingSeverity
    title: str = Field(..., max_length=300)
    description: str
    file_path: Optional[str] = None           # Full path to suspect file/folder
    file_hash_sha256: Optional[str] = None
    file_hash_md5: Optional[str] = None
    file_size_bytes: Optional[int] = None
    file_created: Optional[datetime] = None
    file_modified: Optional[datetime] = None
    process_name: Optional[str] = None
    process_pid: Optional[int] = None
    network_ip: Optional[str] = None
    network_port: Optional[int] = None
    network_domain: Optional[str] = None
    email_subject: Optional[str] = None
    email_sender: Optional[str] = None
    email_date: Optional[datetime] = None
    attachment_name: Optional[str] = None
    app_name: Optional[str] = None
    app_version: Optional[str] = None
    extension_id: Optional[str] = None
    mitre_technique: Optional[str] = None      # e.g. T1059.001
    mitre_tactic: Optional[str] = None         # e.g. Execution
    scanner_name: str                          # Which scanner found this
    raw_evidence: Optional[dict[str, Any]] = None  # Scanner-specific evidence
    recommended_action: Optional[str] = None


# ---------------------------------------------------------------------------
# Corroboration result — threat intel verdict on a finding
# ---------------------------------------------------------------------------

class CorroborationResult(BaseModel):
    """Result of cross-referencing a finding against threat intelligence."""
    source: ThreatIntelSource
    status: CorroborationStatus
    confidence: float = Field(..., ge=0, le=1.0, description="0.0 = no confidence, 1.0 = certain")
    detail: str
    detection_names: list[str] = Field(default_factory=list)  # AV detection names from VT
    detection_ratio: Optional[str] = None      # e.g. "47/72" from VirusTotal
    abuse_score: Optional[int] = None          # AbuseIPDB confidence score
    yara_rules_matched: list[str] = Field(default_factory=list)
    mitre_techniques: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)
    raw_response: Optional[dict] = None


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    """Request to initiate a scan on a device."""
    client_id: uuid.UUID
    device_id: uuid.UUID
    scope: ScanScope = ScanScope.FULL
    os_platform: OSPlatform = OSPlatform.MACOS
    custom_paths: list[str] = Field(default_factory=list, description="Additional paths to scan")
    skip_corroboration: bool = False  # For offline/air-gapped scans
    priority: bool = False            # Jump the queue


class ConsentRecord(BaseModel):
    """POPIA consent for endpoint scanning."""
    client_id: uuid.UUID
    granted_by: str = Field(..., max_length=200)
    granted_by_role: str = Field(..., max_length=100)
    consent_scope: str = Field(default="endpoint_forensic_scan")
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class FindingResponse(BaseModel):
    """A finding after corroboration, as stored in the database."""
    id: uuid.UUID
    scan_id: uuid.UUID
    category: FindingCategory
    severity: FindingSeverity
    title: str
    description: str
    file_path: Optional[str]
    file_hash_sha256: Optional[str]
    process_name: Optional[str]
    network_ip: Optional[str]
    network_domain: Optional[str]
    email_subject: Optional[str]
    attachment_name: Optional[str]
    app_name: Optional[str]
    extension_id: Optional[str]
    mitre_technique: Optional[str]
    mitre_tactic: Optional[str]
    corroboration_status: CorroborationStatus
    corroboration_confidence: float
    corroboration_details: list[CorroborationResult] = Field(default_factory=list)
    recommended_action: Optional[str]
    found_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    is_false_positive: bool = False


class ScanSessionResponse(BaseModel):
    """Summary of a scan session."""
    id: uuid.UUID
    client_id: uuid.UUID
    device_id: uuid.UUID
    scope: ScanScope
    status: ScanStatus
    os_platform: OSPlatform
    started_at: datetime
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    total_items_scanned: int = 0
    findings_count: int = 0
    critical_findings: int = 0
    high_findings: int = 0
    confirmed_malicious: int = 0
    scanners_run: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class DeviceScanSummary(BaseModel):
    """Comprehensive scan summary for a device."""
    device_id: uuid.UUID
    client_id: uuid.UUID
    hostname: Optional[str]
    os_platform: OSPlatform
    last_scan: Optional[ScanSessionResponse]
    total_scans: int
    total_findings: int
    active_threats: int       # Confirmed malicious, not yet resolved
    risk_score: float = Field(ge=0, le=100)
    findings_by_category: dict[str, int] = Field(default_factory=dict)
    findings_by_severity: dict[str, int] = Field(default_factory=dict)
    top_findings: list[FindingResponse] = Field(default_factory=list)


class DashboardStats(BaseModel):
    """Aggregate stats across all scanned devices."""
    total_devices_scanned: int
    total_scans_run: int
    total_findings: int
    active_threats: int
    confirmed_malicious_total: int
    devices_at_critical_risk: int
    most_common_categories: dict[str, int]
    most_common_mitre_techniques: dict[str, int]
    last_scan_at: Optional[datetime]
    provider_health: dict[str, bool]


# ---------------------------------------------------------------------------
# Agent report model — sent from device agent to backend
# ---------------------------------------------------------------------------

class AgentScanReport(BaseModel):
    """
    Complete scan report submitted by the Health Check agent running
    on the client device. Contains all raw findings before corroboration.
    """
    device_id: uuid.UUID
    client_id: uuid.UUID
    agent_version: str
    os_platform: OSPlatform
    hostname: str
    os_version: str
    scan_scope: ScanScope
    scan_started_at: datetime
    scan_completed_at: datetime
    total_items_scanned: int
    findings: list[RawFinding]
    scanners_run: list[str]
    errors: list[str] = Field(default_factory=list)
