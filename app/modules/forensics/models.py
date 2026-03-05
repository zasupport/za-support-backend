"""
Health Check AI — Forensics Module
Database Models (SQLAlchemy) and Pydantic Schemas
"""

from datetime import datetime
from typing import Optional
from enum import Enum
import uuid

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean,
    ForeignKey, JSON, Integer, Float
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

# Import your existing Base from Health Check AI
# from app.database import Base
# For module portability, we define it locally if needed:
try:
    from app.database import Base
except ImportError:
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase):
        pass

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class InvestigationStatus(str, Enum):
    PENDING         = "pending"          # created, awaiting consent
    CONSENT_GRANTED = "consent_granted"  # consent received, ready to run
    RUNNING         = "running"          # analysis in progress
    PAUSED          = "paused"           # manually paused
    COMPLETE        = "complete"         # all tasks done
    FAILED          = "failed"           # critical error
    CANCELLED       = "cancelled"        # cancelled before completion


class AnalysisScope(str, Enum):
    QUICK_TRIAGE = "quick_triage"        # ~5 min: running procs, network, recent files
    STANDARD     = "standard"            # ~30 min: + disk artefacts, logs, timeline
    DEEP         = "deep"                # ~2+ hrs: + memory dump, full disk carving


class EvidenceType(str, Enum):
    MEMORY_DUMP     = "memory_dump"
    DISK_IMAGE      = "disk_image"
    LOG_EXPORT      = "log_export"
    PROCESS_LIST    = "process_list"
    NETWORK_STATE   = "network_state"
    FILE_TIMELINE   = "file_timeline"
    REGISTRY_EXPORT = "registry_export"
    YARA_SCAN       = "yara_scan"
    ARTIFACT_ZIP    = "artifact_zip"
    REPORT          = "report"


class FindingSeverity(str, Enum):
    CRITICAL  = "critical"
    HIGH      = "high"
    MEDIUM    = "medium"
    LOW       = "low"
    INFO      = "info"


class TaskStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETE  = "complete"
    FAILED    = "failed"
    SKIPPED   = "skipped"    # tool not available


# ─── SQLAlchemy Models ────────────────────────────────────────────────────────

class ForensicInvestigation(Base):
    """
    Root record for a forensic investigation.
    Nothing proceeds without POPIA consent recorded here.
    """
    __tablename__ = "forensic_investigations"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id       = Column(String(100), nullable=False, index=True)
    device_id       = Column(String(100), nullable=True, index=True)
    device_name     = Column(String(200), nullable=True)
    device_os       = Column(String(100), nullable=True)

    # Scope and status
    scope           = Column(String(50), nullable=False, default=AnalysisScope.QUICK_TRIAGE)
    status          = Column(String(50), nullable=False, default=InvestigationStatus.PENDING)

    # The reason this investigation was initiated
    reason          = Column(Text, nullable=False)
    initiated_by    = Column(String(100), nullable=False)   # ZA Support user

    # POPIA consent gate — MANDATORY before any analysis runs
    consent_granted      = Column(Boolean, default=False, nullable=False)
    consent_obtained_by  = Column(String(200), nullable=True)   # Name of person who gave consent
    consent_method       = Column(String(100), nullable=True)   # "email", "signed_form", "verbal_recorded"
    consent_reference    = Column(String(200), nullable=True)   # Reference number / email subject
    consent_timestamp    = Column(DateTime, nullable=True)

    # Timestamps
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at      = Column(DateTime, nullable=True)
    completed_at    = Column(DateTime, nullable=True)

    # Output location (server-side path)
    output_directory = Column(String(500), nullable=True)

    # Summary stats (populated on completion)
    total_tasks     = Column(Integer, default=0)
    completed_tasks = Column(Integer, default=0)
    finding_count   = Column(Integer, default=0)
    critical_count  = Column(Integer, default=0)
    high_count      = Column(Integer, default=0)

    # Relationships
    tasks    = relationship("ForensicTask",    back_populates="investigation", cascade="all, delete-orphan")
    evidence = relationship("ForensicEvidence", back_populates="investigation", cascade="all, delete-orphan")
    findings = relationship("ForensicFinding",  back_populates="investigation", cascade="all, delete-orphan")
    report   = relationship("ForensicReport",   back_populates="investigation", uselist=False, cascade="all, delete-orphan")


class ForensicTask(Base):
    """
    Individual analysis task within an investigation.
    One task = one tool run (e.g. Volatility process scan).
    """
    __tablename__ = "forensic_tasks"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("forensic_investigations.id"), nullable=False)

    tool_id          = Column(String(100), nullable=False)   # from tool_registry
    tool_name        = Column(String(200), nullable=False)
    task_type        = Column(String(100), nullable=False)   # e.g. "process_scan", "yara_scan"
    description      = Column(Text, nullable=True)

    status           = Column(String(50), default=TaskStatus.QUEUED, nullable=False)
    started_at       = Column(DateTime, nullable=True)
    completed_at     = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Command executed (for audit trail)
    command          = Column(Text, nullable=True)
    exit_code        = Column(Integer, nullable=True)
    error_output     = Column(Text, nullable=True)

    # Task-specific results (structured)
    results          = Column(JSON, nullable=True)
    result_summary   = Column(Text, nullable=True)    # human-readable one-liner

    investigation = relationship("ForensicInvestigation", back_populates="tasks")


class ForensicEvidence(Base):
    """
    Evidence artefact collected during an investigation.
    Every item has an intake hash and a verification hash.
    """
    __tablename__ = "forensic_evidence"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("forensic_investigations.id"), nullable=False)
    task_id          = Column(UUID(as_uuid=True), ForeignKey("forensic_tasks.id"), nullable=True)

    evidence_type    = Column(String(100), nullable=False)
    filename         = Column(String(500), nullable=False)
    file_path        = Column(String(1000), nullable=True)
    file_size_bytes  = Column(Integer, nullable=True)

    # Chain of custody hashes
    sha256_intake    = Column(String(64), nullable=True)     # hash at time of collection
    sha256_verified  = Column(String(64), nullable=True)     # re-verification hash
    hash_verified    = Column(Boolean, default=False)
    hash_verified_at = Column(DateTime, nullable=True)

    collected_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    description      = Column(Text, nullable=True)

    investigation = relationship("ForensicInvestigation", back_populates="evidence")


class ForensicFinding(Base):
    """
    A single indicator or finding from the analysis.
    Findings are indicators — they require human review before conclusions are drawn.
    """
    __tablename__ = "forensic_findings"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("forensic_investigations.id"), nullable=False)
    task_id          = Column(UUID(as_uuid=True), ForeignKey("forensic_tasks.id"), nullable=True)

    severity         = Column(String(20), nullable=False, default=FindingSeverity.INFO)
    category         = Column(String(100), nullable=False)   # e.g. "malware_indicator", "data_exfiltration"
    title            = Column(String(500), nullable=False)
    detail           = Column(Text, nullable=True)

    # Source context
    source_tool      = Column(String(100), nullable=True)
    source_artifact  = Column(String(500), nullable=True)    # file/path where found
    raw_indicator    = Column(Text, nullable=True)           # the raw match/value

    # Classification
    is_false_positive    = Column(Boolean, nullable=True)    # null = unreviewed
    reviewed_by          = Column(String(100), nullable=True)
    reviewed_at          = Column(DateTime, nullable=True)
    review_notes         = Column(Text, nullable=True)

    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)

    investigation = relationship("ForensicInvestigation", back_populates="findings")


class ForensicReport(Base):
    """
    Generated report for a completed investigation.
    """
    __tablename__ = "forensic_reports"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("forensic_investigations.id"), nullable=False)

    generated_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    generated_by     = Column(String(100), nullable=False)

    report_path      = Column(String(1000), nullable=True)   # path to PDF file
    json_path        = Column(String(1000), nullable=True)   # path to JSON summary
    sha256           = Column(String(64), nullable=True)     # hash of the report PDF

    executive_summary = Column(Text, nullable=True)
    finding_count     = Column(Integer, default=0)
    critical_count    = Column(Integer, default=0)
    high_count        = Column(Integer, default=0)

    investigation = relationship("ForensicInvestigation", back_populates="report")


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class ConsentGrantRequest(BaseModel):
    consent_obtained_by: str    = Field(..., description="Full name of person granting consent")
    consent_method:      str    = Field(..., description="email | signed_form | verbal_recorded")
    consent_reference:   str    = Field(..., description="Email subject line, form reference, or recording ID")


class CreateInvestigationRequest(BaseModel):
    client_id:    str  = Field(..., description="Health Check AI client ID")
    device_id:    Optional[str] = Field(None, description="Specific device to analyse (optional)")
    device_name:  Optional[str] = None
    device_os:    Optional[str] = None
    scope:        AnalysisScope = AnalysisScope.QUICK_TRIAGE
    reason:       str  = Field(..., description="Business reason for the investigation")
    initiated_by: str  = Field(..., description="ZA Support user initiating the investigation")


class InvestigationSummary(BaseModel):
    id:              str
    client_id:       str
    device_name:     Optional[str]
    scope:           str
    status:          str
    reason:          str
    consent_granted: bool
    created_at:      datetime
    started_at:      Optional[datetime]
    completed_at:    Optional[datetime]
    finding_count:   int
    critical_count:  int
    high_count:      int

    class Config:
        from_attributes = True


class TaskSummary(BaseModel):
    id:              str
    tool_id:         str
    tool_name:       str
    task_type:       str
    status:          str
    duration_seconds: Optional[float]
    result_summary:  Optional[str]

    class Config:
        from_attributes = True


class FindingSchema(BaseModel):
    id:             str
    severity:       str
    category:       str
    title:          str
    detail:         Optional[str]
    source_tool:    Optional[str]
    source_artifact: Optional[str]
    raw_indicator:  Optional[str]
    is_false_positive: Optional[bool]
    created_at:     datetime

    class Config:
        from_attributes = True


class ToolStatusSchema(BaseModel):
    id:           str
    name:         str
    description:  str
    category:     str
    is_available: bool
    version:      Optional[str]
    install_cmd:  str
