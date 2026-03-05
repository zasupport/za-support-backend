from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.core.database import Base

class VaultEntry(Base):
    __tablename__ = "vault_entries"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(100), nullable=False, index=True)
    category = Column(String(50), nullable=False)  # microsoft365, icloud, isp, router, wifi, application, other
    service_name = Column(String(200), nullable=False)  # "Microsoft 365 Business Premium", "Stem ISP Account"
    username = Column(Text, nullable=True)  # encrypted
    password = Column(Text, nullable=True)  # encrypted
    url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)  # encrypted
    license_key = Column(Text, nullable=True)  # encrypted
    expiry_date = Column(DateTime, nullable=True)
    last_rotated = Column(DateTime, nullable=True)
    rotation_reminder_days = Column(Integer, default=90)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by = Column(String(100), default="courtney")
    is_active = Column(Boolean, default=True)

class VaultAuditLog(Base):
    __tablename__ = "vault_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("vault_entries.id"), nullable=False)
    action = Column(String(50), nullable=False)  # created, viewed, updated, deleted, rotated
    performed_by = Column(String(100), nullable=False)
    performed_at = Column(DateTime, server_default=func.now())
    ip_address = Column(String(45), nullable=True)
    details = Column(Text, nullable=True)
