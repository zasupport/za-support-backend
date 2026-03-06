from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, Text, Numeric, DateTime, Date
from app.core.database import Base


class CyberShieldEnrollment(Base):
    __tablename__ = "cybershield_enrollments"

    id            = Column(Integer, primary_key=True)
    client_id     = Column(String(100), unique=True, nullable=False, index=True)
    practice_name = Column(Text)
    isp_name      = Column(Text)
    enrolled_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    active        = Column(Boolean, default=True)
    monthly_fee   = Column(Numeric(10, 2), default=1499.00)
    notes         = Column(Text)
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


class CyberShieldReport(Base):
    __tablename__ = "cybershield_reports"

    id           = Column(Integer, primary_key=True)
    client_id    = Column(String(100), nullable=False, index=True)
    filename     = Column(Text, nullable=False)
    month_label  = Column(String(20))
    file_path    = Column(Text)
    generated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CyberShieldBilling(Base):
    __tablename__ = "cybershield_billing"

    id          = Column(Integer, primary_key=True)
    client_id   = Column(String(100), nullable=False, index=True)
    month_label = Column(String(20), nullable=False)
    amount      = Column(Numeric(10, 2), nullable=False, default=1499.00)
    status      = Column(String(20), nullable=False, default="pending")  # pending|sent|paid|overdue
    invoice_ref = Column(String(50))
    due_date    = Column(Date)
    paid_at     = Column(DateTime(timezone=True))
    notes       = Column(Text)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))
