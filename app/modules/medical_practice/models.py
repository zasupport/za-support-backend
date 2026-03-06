from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, JSON, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.core.database import Base


class MedicalPractice(Base):
    __tablename__ = "medical_practices"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id       = Column(String, nullable=False, unique=True, index=True)
    practice_name   = Column(String, nullable=False)
    practice_type   = Column(String, default="gp")           # gp|specialist|allied|dental|veterinary|psychology
    hpcsa_number    = Column(String)
    doctor_count    = Column(Integer, default=1)
    staff_count     = Column(Integer, default=0)
    software_stack  = Column(JSON, default=list)             # ["GoodX", "HealthBridge", "Dragon Dictate"]
    devices_count   = Column(Integer, default=0)
    compliance_notes = Column(Text)
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    assessments = relationship("MedicalAssessment", back_populates="practice", cascade="all, delete-orphan")


class MedicalAssessment(Base):
    __tablename__ = "medical_assessments"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id       = Column(UUID(as_uuid=True), nullable=False)
    assessment_date   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Scored 0-100
    network_score     = Column(Integer)
    device_score      = Column(Integer)
    software_score    = Column(Integer)
    backup_score      = Column(Integer)
    compliance_score  = Column(Integer)
    overall_score     = Column(Integer)
    overall_grade     = Column(String(1))                    # A B C D F

    # Compliance flags
    popia_compliant   = Column(String, default="unknown")    # met|not_met|partial|unknown
    hpcsa_compliant   = Column(String, default="unknown")
    backup_offsite    = Column(String, default="unknown")
    encryption_status = Column(String, default="unknown")

    recommendations   = Column(JSON, default=list)           # [{priority, category, action, rand_impact}]
    upsell_flags      = Column(JSON, default=list)           # product names triggered by this assessment
    created_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    practice = relationship("MedicalPractice", back_populates="assessments", foreign_keys=[practice_id],
                            primaryjoin="MedicalAssessment.practice_id == MedicalPractice.id")
