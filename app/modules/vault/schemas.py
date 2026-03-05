from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class VaultEntryCreate(BaseModel):
    client_id: str
    category: str
    service_name: str
    username: Optional[str] = None
    password: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    license_key: Optional[str] = None
    expiry_date: Optional[datetime] = None
    rotation_reminder_days: int = 90
    created_by: str = "courtney"

class VaultEntryUpdate(BaseModel):
    service_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    license_key: Optional[str] = None
    expiry_date: Optional[datetime] = None
    rotation_reminder_days: Optional[int] = None

class VaultEntryMeta(BaseModel):
    id: int
    client_id: str
    category: str
    service_name: str
    url: Optional[str]
    expiry_date: Optional[datetime]
    last_rotated: Optional[datetime]
    rotation_reminder_days: int
    created_at: datetime
    updated_at: datetime
    created_by: str
    is_active: bool

    class Config:
        from_attributes = True

class VaultEntryFull(VaultEntryMeta):
    username: Optional[str]
    password: Optional[str]
    notes: Optional[str]
    license_key: Optional[str]

class VaultAuditLogEntry(BaseModel):
    id: int
    entry_id: int
    action: str
    performed_by: str
    performed_at: datetime
    ip_address: Optional[str]
    details: Optional[str]

    class Config:
        from_attributes = True
