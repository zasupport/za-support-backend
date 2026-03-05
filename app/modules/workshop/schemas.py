from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, field_validator


class LineItemIn(BaseModel):
    description: str
    qty: int = 1
    unit_price: Optional[Decimal] = None
    item_type: str = "labour"


class LineItemOut(BaseModel):
    id: int
    description: str
    qty: int
    unit_price: Optional[Decimal]
    line_total: Optional[Decimal]
    item_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class JobCreate(BaseModel):
    client_id: str
    serial: Optional[str] = None
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    scheduled_date: Optional[date] = None
    notes: Optional[str] = None
    line_items: List[LineItemIn] = []

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed = {"low", "normal", "high", "urgent"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v


class JobStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"open", "in_progress", "waiting_parts", "completed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class JobUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    scheduled_date: Optional[date] = None
    assigned_to: Optional[str] = None
    labour_minutes: Optional[int] = None
    notes: Optional[str] = None


class JobHistoryOut(BaseModel):
    id: int
    from_status: Optional[str]
    to_status: str
    note: Optional[str]
    changed_by: str
    changed_at: datetime

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    id: int
    job_ref: str
    client_id: str
    serial: Optional[str]
    title: str
    description: Optional[str]
    status: str
    priority: str
    source: str
    snapshot_id: Optional[int]
    assigned_to: Optional[str]
    scheduled_date: Optional[date]
    completed_at: Optional[datetime]
    labour_minutes: Optional[int]
    total_incl_vat: Optional[Decimal]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    line_items: List[LineItemOut] = []
    history: List[JobHistoryOut] = []

    class Config:
        from_attributes = True


class JobListOut(BaseModel):
    id: int
    job_ref: str
    client_id: str
    serial: Optional[str]
    title: str
    status: str
    priority: str
    source: str
    scheduled_date: Optional[date]
    created_at: datetime

    class Config:
        from_attributes = True
