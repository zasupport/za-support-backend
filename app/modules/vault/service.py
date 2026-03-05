from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone, timedelta

from app.modules.vault.models import VaultEntry, VaultAuditLog
from app.modules.vault.encryption import encrypt_value, decrypt_value


def create_entry(db: Session, data: dict, performer: str, ip: str) -> VaultEntry:
    enc_fields = {}
    for field in ("username", "password", "notes", "license_key"):
        val = data.get(field)
        enc_fields[field] = encrypt_value(val) if val else None

    entry = VaultEntry(
        client_id=data["client_id"],
        category=data["category"],
        service_name=data["service_name"],
        username=enc_fields["username"],
        password=enc_fields["password"],
        url=data.get("url"),
        notes=enc_fields["notes"],
        license_key=enc_fields["license_key"],
        expiry_date=data.get("expiry_date"),
        rotation_reminder_days=data.get("rotation_reminder_days", 90),
        created_by=data.get("created_by", "courtney"),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    _audit(db, entry.id, "created", performer, ip, f"Created {data['service_name']}")
    return entry


def list_entries(db: Session, client_id: str) -> List[VaultEntry]:
    return (
        db.query(VaultEntry)
        .filter(VaultEntry.client_id == client_id, VaultEntry.is_active == True)
        .order_by(VaultEntry.category, VaultEntry.service_name)
        .all()
    )


def get_entry(db: Session, entry_id: int, performer: str, ip: str) -> Optional[VaultEntry]:
    entry = (
        db.query(VaultEntry)
        .filter(VaultEntry.id == entry_id, VaultEntry.is_active == True)
        .first()
    )
    if not entry:
        return None
    # Decrypt sensitive fields in-place for response
    for field in ("username", "password", "notes", "license_key"):
        val = getattr(entry, field)
        if val:
            setattr(entry, field, decrypt_value(val))
    _audit(db, entry_id, "viewed", performer, ip, "Credentials accessed")
    return entry


def update_entry(db: Session, entry_id: int, data: dict, performer: str, ip: str) -> Optional[VaultEntry]:
    entry = (
        db.query(VaultEntry)
        .filter(VaultEntry.id == entry_id, VaultEntry.is_active == True)
        .first()
    )
    if not entry:
        return None
    for field in ("username", "password", "notes", "license_key"):
        if field in data and data[field] is not None:
            data[field] = encrypt_value(data[field])
    for key, value in data.items():
        setattr(entry, key, value)
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    _audit(db, entry_id, "updated", performer, ip, f"Updated fields: {', '.join(data.keys())}")
    return entry


def delete_entry(db: Session, entry_id: int, performer: str, ip: str) -> bool:
    entry = (
        db.query(VaultEntry)
        .filter(VaultEntry.id == entry_id)
        .first()
    )
    if not entry:
        return False
    entry.is_active = False
    entry.updated_at = datetime.utcnow()
    db.commit()
    _audit(db, entry_id, "deleted", performer, ip, "Soft deleted")
    return True


def rotate_entry(db: Session, entry_id: int, performer: str, ip: str) -> Optional[VaultEntry]:
    entry = (
        db.query(VaultEntry)
        .filter(VaultEntry.id == entry_id, VaultEntry.is_active == True)
        .first()
    )
    if not entry:
        return None
    entry.last_rotated = datetime.utcnow()
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry)
    _audit(db, entry_id, "rotated", performer, ip, "Password rotation recorded")
    return entry


def get_expiring(db: Session, days: int) -> List[VaultEntry]:
    cutoff = datetime.now(timezone.utc) + timedelta(days=days)
    return (
        db.query(VaultEntry)
        .filter(
            VaultEntry.is_active == True,
            VaultEntry.expiry_date != None,
            VaultEntry.expiry_date <= cutoff,
        )
        .order_by(VaultEntry.expiry_date)
        .all()
    )


def get_audit_log(db: Session, entry_id: int) -> List[VaultAuditLog]:
    return (
        db.query(VaultAuditLog)
        .filter(VaultAuditLog.entry_id == entry_id)
        .order_by(VaultAuditLog.performed_at.desc())
        .all()
    )


def _audit(db: Session, entry_id: int, action: str, performer: str, ip: str, details: str):
    log = VaultAuditLog(
        entry_id=entry_id,
        action=action,
        performed_by=performer,
        ip_address=ip,
        details=details,
    )
    db.add(log)
    db.commit()
