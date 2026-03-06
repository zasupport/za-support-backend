from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class EnrollRequest(BaseModel):
    client_id: str
    practice_name: Optional[str] = None
    isp_name: Optional[str] = None
    notes: Optional[str] = None
    monthly_fee: Optional[float] = 1499.00


class EnrollmentOut(BaseModel):
    id: int
    client_id: str
    practice_name: Optional[str]
    isp_name: Optional[str]
    enrolled_at: Optional[datetime]
    active: bool
    monthly_fee: Optional[float]
    notes: Optional[str]

    model_config = {"from_attributes": True}


class ReportOut(BaseModel):
    id: int
    client_id: str
    filename: str
    month_label: Optional[str]
    generated_at: Optional[datetime]

    model_config = {"from_attributes": True}
