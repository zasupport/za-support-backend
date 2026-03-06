from sqlalchemy import Column, String, Boolean, Text, Numeric, ARRAY, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base


class CRMContact(Base):
    __tablename__ = "crm_contacts"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    client_id       = Column(String(100))
    first_name      = Column(String(100), nullable=False)
    last_name       = Column(String(100), nullable=False)
    email           = Column(String(255))
    phone           = Column(String(50))
    company         = Column(String(200))
    segment         = Column(String(50))
    investec_client = Column(Boolean, default=False)
    referral_source = Column(String(100))
    referred_by     = Column(String(200))
    notes           = Column(Text)
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at      = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class CRMOpportunity(Base):
    __tablename__ = "crm_opportunities"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    contact_id      = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id", ondelete="CASCADE"))
    client_id       = Column(String(100))
    title           = Column(String(200), nullable=False)
    stage           = Column(String(50), default="lead")
    value_rand      = Column(Numeric(12, 2))
    product         = Column(String(100))
    urgency         = Column(String(50))
    investec_flag   = Column(Boolean, default=False)
    segment         = Column(String(50))
    referral_source = Column(String(100))
    notes           = Column(Text)
    closed_at       = Column(TIMESTAMP(timezone=True))
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at      = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class CRMActivity(Base):
    __tablename__ = "crm_activities"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    opportunity_id  = Column(UUID(as_uuid=True), ForeignKey("crm_opportunities.id", ondelete="CASCADE"))
    contact_id      = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id", ondelete="SET NULL"))
    activity_type   = Column(String(50), nullable=False)
    subject         = Column(String(200))
    notes           = Column(Text)
    outcome         = Column(String(100))
    scheduled_at    = Column(TIMESTAMP(timezone=True))
    completed_at    = Column(TIMESTAMP(timezone=True))
    created_by      = Column(String(100), default="system")
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())


class UpsellProduct(Base):
    __tablename__ = "upsell_products"

    id                  = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name                = Column(String(200), nullable=False)
    category            = Column(String(100))
    price_rand          = Column(Numeric(12, 2))
    description         = Column(Text)
    diagnostic_triggers = Column(ARRAY(String))
    applicable_segments = Column(ARRAY(String))
    warranty_risk       = Column(String(50), default="low")
    active              = Column(Boolean, default=True)
    created_at          = Column(TIMESTAMP(timezone=True), server_default=func.now())


class UpsellRecommendation(Base):
    __tablename__ = "upsell_recommendations"

    id              = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    client_id       = Column(String(100), nullable=False)
    product_id      = Column(UUID(as_uuid=True), ForeignKey("upsell_products.id", ondelete="SET NULL"))
    product_name    = Column(String(200))
    trigger_field   = Column(String(200))
    trigger_value   = Column(Text)
    roi_description = Column(Text)
    rand_value      = Column(Numeric(12, 2))
    status          = Column(String(50), default="pending")
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at      = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class SalesOutcome(Base):
    __tablename__ = "sales_outcomes"

    id                = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    opportunity_id    = Column(UUID(as_uuid=True), ForeignKey("crm_opportunities.id", ondelete="SET NULL"))
    recommendation_id = Column(UUID(as_uuid=True), ForeignKey("upsell_recommendations.id", ondelete="SET NULL"))
    client_id         = Column(String(100))
    segment           = Column(String(50))
    product           = Column(String(100))
    outcome           = Column(String(50))
    loss_reason       = Column(String(200))
    revenue_rand      = Column(Numeric(12, 2))
    notes             = Column(Text)
    created_at        = Column(TIMESTAMP(timezone=True), server_default=func.now())
