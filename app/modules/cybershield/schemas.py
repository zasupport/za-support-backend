from datetime import date, datetime
from decimal import Decimal
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


class BillingCreate(BaseModel):
    client_id: str
    month_label: str
    amount: Optional[Decimal] = Decimal("1499.00")
    due_date: Optional[date] = None
    invoice_ref: Optional[str] = None
    notes: Optional[str] = None


class BillingStatusUpdate(BaseModel):
    status: str  # pending|sent|paid|overdue
    invoice_ref: Optional[str] = None
    notes: Optional[str] = None


class BillingOut(BaseModel):
    id: int
    client_id: str
    month_label: str
    amount: Optional[Decimal]
    status: str
    invoice_ref: Optional[str]
    due_date: Optional[date]
    paid_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}
