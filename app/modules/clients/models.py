from sqlalchemy import Column, Integer, String, Boolean, Text, ARRAY, TIMESTAMP
from sqlalchemy.sql import func
from app.core.database import Base


class Client(Base):
    __tablename__ = "clients"

    id                              = Column(Integer, primary_key=True)
    client_id                       = Column(String(100), unique=True, nullable=False)
    first_name                      = Column(String(100), nullable=False)
    last_name                       = Column(String(100), nullable=False)
    email                           = Column(String(255), unique=True, nullable=False)
    phone                           = Column(String(50), nullable=False)
    preferred_contact               = Column(String(50), nullable=False)
    address                         = Column(Text)
    referral_source                 = Column(String(100))
    referred_by                     = Column(String(200))
    urgency_level                   = Column(String(50))
    concerns                        = Column(ARRAY(String))
    concerns_detail                 = Column(Text)
    has_business                    = Column(Boolean, default=False)
    business_name                   = Column(String(200))
    business_type                   = Column(String(200))
    business_staff_count            = Column(String(50))
    business_device_count           = Column(String(50))
    business_health_check_interest  = Column(String(100))
    popia_consent                   = Column(Boolean, nullable=False, default=False)
    marketing_consent               = Column(Boolean, default=False)
    status                          = Column(String(50), default="new")
    created_at                      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at                      = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class ClientSetup(Base):
    __tablename__ = "client_setup"

    id                  = Column(Integer, primary_key=True)
    client_id           = Column(String(100), nullable=False)
    primary_computer    = Column(String(50))
    form_factor         = Column(String(50))
    computer_age        = Column(String(50))
    computer_model_hint = Column(String(200))
    has_external_backup = Column(String(20))
    other_devices       = Column(ARRAY(String))
    isp                 = Column(String(100))
    cloud_services      = Column(ARRAY(String))
    email_clients       = Column(ARRAY(String))
    has_google_account  = Column(String(20))
    has_apple_id        = Column(String(20))
    created_at          = Column(TIMESTAMP(timezone=True), server_default=func.now())


class ClientOnboardingTask(Base):
    __tablename__ = "client_onboarding_tasks"

    id           = Column(Integer, primary_key=True)
    client_id    = Column(String(100), nullable=False)
    task         = Column(String(500), nullable=False)
    status       = Column(String(50), default="pending")
    notes        = Column(Text)
    created_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())
    completed_at = Column(TIMESTAMP(timezone=True))


class ClientCheckin(Base):
    __tablename__ = "client_checkins"

    id                     = Column(Integer, primary_key=True)
    client_id              = Column(String(100), nullable=False)
    working_well           = Column(Text)
    changes_since_last     = Column(Text)
    focus_today            = Column(Text)
    issues_noted           = Column(Text)
    backup_drive_connected = Column(String(20))
    pre_visit_notes        = Column(Text)
    created_at             = Column(TIMESTAMP(timezone=True), server_default=func.now())
