"""
Device registration and health telemetry submission.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta
from typing import Optional, List

from app.core.database import get_db
from app.core.auth import verify_api_key
from app.core.encryption import encrypt_payload
from app.models.models import Device, HealthData
from app.models.schemas import (
    DeviceRegister, DeviceResponse, HealthSubmission, HealthResponse
)
from app.services.alert_engine import evaluate_health_data

router = APIRouter()


# ---------- Device Registration ----------

@router.post("/register", response_model=DeviceResponse)
async def register_device(
    payload: DeviceRegister,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Register a new device or update an existing one (upsert by machine_id)."""
    device = db.query(Device).filter(Device.machine_id == payload.machine_id).first()

    if device:
        # Update existing
        for field in ["hostname", "device_type", "model_identifier", "serial_number",
                      "os_version", "agent_version", "client_id"]:
            val = getattr(payload, field, None)
            if val is not None:
                setattr(device, field, val)
        device.last_seen = datetime.utcnow()
        device.is_active = True
    else:
        device = Device(
            machine_id=payload.machine_id,
            hostname=payload.hostname,
            device_type=payload.device_type,
            model_identifier=payload.model_identifier,
            serial_number=payload.serial_number,
            os_version=payload.os_version,
            agent_version=payload.agent_version,
            client_id=payload.client_id,
            metadata_=payload.metadata,
        )
        db.add(device)

    db.commit()
    db.refresh(device)
    return device


# ---------- Health Submission ----------

@router.post("/health")
async def submit_health(
    payload: HealthSubmission,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Submit health telemetry. Auto-registers device if unknown."""
    # Auto-register device if not exists
    device = db.query(Device).filter(Device.machine_id == payload.machine_id).first()
    if not device:
        device = Device(
            machine_id=payload.machine_id,
            device_type="other",
        )
        db.add(device)
        db.flush()

    device.last_seen = datetime.utcnow()

    # Encrypt raw data
    encrypted = None
    if payload.raw_data:
        try:
            encrypted = encrypt_payload(payload.raw_data)
        except Exception:
            encrypted = None

    record = HealthData(
        machine_id=payload.machine_id,
        cpu_percent=payload.cpu_percent,
        memory_percent=payload.memory_percent,
        disk_percent=payload.disk_percent,
        battery_percent=payload.battery_percent,
        battery_cycle_count=payload.battery_cycle_count,
        battery_health=payload.battery_health,
        threat_score=payload.threat_score,
        uptime_hours=payload.uptime_hours,
        network_up_mbps=payload.network_up_mbps,
        network_down_mbps=payload.network_down_mbps,
        encrypted_raw=encrypted,
        raw_data=payload.raw_data,
        timestamp=datetime.utcnow(),
    )
    db.add(record)

    # Evaluate alerts
    alerts = evaluate_health_data(payload.machine_id, payload.model_dump(), db)

    db.commit()
    db.refresh(record)

    return {
        "status": "success",
        "id": record.id,
        "alerts_generated": len(alerts),
    }


# ---------- Device Listing ----------

@router.get("/", response_model=List[DeviceResponse])
async def list_devices(
    client_id: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """List all registered devices."""
    q = db.query(Device)
    if client_id:
        q = q.filter(Device.client_id == client_id)
    if active_only:
        q = q.filter(Device.is_active == True)
    return q.order_by(desc(Device.last_seen)).all()


# ---------- Device History ----------

@router.get("/{machine_id}/history")
async def device_history(
    machine_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Get health telemetry history for a device."""
    since = datetime.utcnow() - timedelta(hours=hours)
    records = (
        db.query(HealthData)
        .filter(HealthData.machine_id == machine_id, HealthData.timestamp >= since)
        .order_by(desc(HealthData.timestamp))
        .limit(500)
        .all()
    )
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "cpu": r.cpu_percent,
            "memory": r.memory_percent,
            "disk": r.disk_percent,
            "battery": r.battery_percent,
            "threat": r.threat_score,
            "uptime_hours": r.uptime_hours,
        }
        for r in records
    ]
