from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
import uuid


class PracticeIn(BaseModel):
    client_id: str
    practice_name: str
    practice_type: str = "gp"  # gp|specialist|allied|dental|veterinary|psychology
    hpcsa_number: Optional[str] = None
    doctor_count: int = 1
    staff_count: int = 0
    software_stack: List[str] = []
    devices_count: int = 0
    compliance_notes: Optional[str] = None
    notes: Optional[str] = None


class PracticeOut(PracticeIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class AssessmentIn(BaseModel):
    practice_id: uuid.UUID
    network_score: Optional[int] = None
    device_score: Optional[int] = None
    software_score: Optional[int] = None
    backup_score: Optional[int] = None
    compliance_score: Optional[int] = None
    popia_compliant: str = "unknown"
    hpcsa_compliant: str = "unknown"
    backup_offsite: str = "unknown"
    encryption_status: str = "unknown"
    recommendations: List[dict] = []
    upsell_flags: List[str] = []


class AssessmentOut(AssessmentIn):
    id: uuid.UUID
    overall_score: Optional[int]
    overall_grade: Optional[str]
    assessment_date: datetime
    created_at: datetime
    class Config:
        from_attributes = True
