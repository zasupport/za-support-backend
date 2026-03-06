from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
import uuid


class ContactIn(BaseModel):
    client_id: Optional[str] = None
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    segment: str = "individual"  # medical_practice|sme|individual|family
    investec_client: bool = False
    referral_source: Optional[str] = None
    referred_by: Optional[str] = None
    notes: Optional[str] = None


class ContactOut(ContactIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class OpportunityIn(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    client_id: Optional[str] = None
    title: str
    stage: str = "lead"  # lead|qualified|proposed|closed_won|closed_lost
    value_rand: Optional[float] = None
    product: Optional[str] = None
    urgency: Optional[str] = None
    investec_flag: bool = False
    segment: Optional[str] = None
    referral_source: Optional[str] = None
    notes: Optional[str] = None


class OpportunityOut(OpportunityIn):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    class Config:
        from_attributes = True


class OpportunityStageUpdate(BaseModel):
    stage: str
    notes: Optional[str] = None
    value_rand: Optional[float] = None


class ActivityIn(BaseModel):
    opportunity_id: Optional[uuid.UUID] = None
    contact_id: Optional[uuid.UUID] = None
    activity_type: str  # call|visit|email|demo|report_delivery|follow_up
    subject: Optional[str] = None
    notes: Optional[str] = None
    outcome: Optional[str] = None
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
    price_rand: Optional[float] = None
    diagnostic_triggers: List[str] = []
    applicable_segments: List[str] = []
    warranty_risk: str = "low"  # low|medium|high
    active: bool = True


class ProductOut(ProductIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class RecommendationIn(BaseModel):
    client_id: str
    product_id: uuid.UUID
    product_name: Optional[str] = None
    trigger_field: Optional[str] = None
    trigger_value: Optional[str] = None
    roi_description: Optional[str] = None
    rand_value: Optional[float] = None


class RecommendationOut(RecommendationIn):
    id: uuid.UUID
    status: str
    created_at: datetime
    class Config:
        from_attributes = True


class RecommendationStatusUpdate(BaseModel):
    status: str  # pending|accepted|declined|deferred


class OutcomeIn(BaseModel):
    opportunity_id: Optional[uuid.UUID] = None
    recommendation_id: Optional[uuid.UUID] = None
    client_id: str
    segment: Optional[str] = None
    product: Optional[str] = None
    outcome: str  # accepted|declined|deferred|closed_won|closed_lost
    loss_reason: Optional[str] = None
    revenue_rand: Optional[float] = None
    notes: Optional[str] = None


class OutcomeOut(OutcomeIn):
    id: uuid.UUID
    created_at: datetime
    class Config:
        from_attributes = True


class InvestecScanResult(BaseModel):
    emails_scanned: int
    investec_contacts_found: int
    new_contacts_created: int
    outreach_triggered: int
