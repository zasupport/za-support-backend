from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr
import uuid


class ContactIn(BaseModel):
    client_id: Optional[str] = None
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    segment: str = "individual"  # medical_practice|sme|individual|family
    investec_client: bool = False
    referral_source: Optional[str] = None
    notes: Optional[str] = None


class ContactOut(ContactIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class OpportunityIn(BaseModel):
    contact_id: uuid.UUID
    title: str
    stage: str = "lead"
    value_rand: Optional[float] = None
    segment: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    follow_up_at: Optional[datetime] = None


class OpportunityOut(OpportunityIn):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


class OpportunityStageUpdate(BaseModel):
    stage: str
    notes: Optional[str] = None
    value_rand: Optional[float] = None
    follow_up_at: Optional[datetime] = None


class ActivityIn(BaseModel):
    opportunity_id: uuid.UUID
    activity_type: str
    notes: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: str = "courtney@zasupport.com"


class ActivityOut(ActivityIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class ProductIn(BaseModel):
    name: str
    category: str
    description: Optional[str] = None
    price_from_rand: Optional[float] = None
    warrantable: bool = True
    failure_risk: str = "low"
    applicable_segments: List[str] = []
    diagnostic_triggers: List[str] = []
    roi_framing: Optional[str] = None
    notes: Optional[str] = None


class ProductOut(ProductIn):
    id: uuid.UUID
    active: bool
    created_at: datetime
    class Config:
        from_attributes = True


class RecommendationOut(BaseModel):
    id: uuid.UUID
    client_id: str
    product_id: Optional[uuid.UUID]
    reason: Optional[str]
    rand_value_framing: Optional[str]
    roi_framing: Optional[str]
    outcome: str
    recommended_at: datetime
    presented_at: Optional[datetime]
    outcome_at: Optional[datetime]
    class Config:
        from_attributes = True


class OutcomeUpdate(BaseModel):
    outcome: str  # accepted|declined|deferred
    rand_value: Optional[float] = None


class InvestecScanResult(BaseModel):
    emails_scanned: int
    investec_contacts_found: int
    new_contacts_created: int
    outreach_triggered: int
