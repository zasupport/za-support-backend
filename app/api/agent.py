"""
Agent Router — receives telemetry and diagnostics from Mac agents.

Endpoints:
    POST /heartbeat        — 60-second telemetry (bearer auth)
    POST /diagnostics      — full diagnostic JSON upload (bearer auth)
    GET  /devices          — list online devices (bearer auth)
    GET  /devices/{serial} — single device status (bearer auth)
    GET  /health           — no auth, uptime check
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
from datetime import datetime, timedelta
from typing import List
import logging

from app.core.database import get_db
from app.core.agent_auth import verify_agent_token
from app.models.models import AgentHeartbeatRecord, DiagnosticReport
from app.models.schemas import (
    AgentHeartbeatSubmit, AgentHeartbeatResponse,
    AgentDiagnosticSubmit, AgentDiagnosticResponse,
    AgentDeviceStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter()

ONLINE_THRESHOLD_SECONDS = 120  # device considered online if heartbeat within 2 min


# ---------- Health (no auth) ----------

@router.get("/health")
async def agent_health(db: Session = Depends(get_db)):
    """No-auth health check for agent subsystem."""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "subsystem": "agent_router",
        "database": "connected" if db_ok else "disconnected",
    }


# ---------- Heartbeat ----------

@router.post("/heartbeat", status_code=201)
async def receive_heartbeat(
    payload: AgentHeartbeatSubmit,
    db: Session = Depends(get_db),
    _: str = Depends(verify_agent_token),
):
    """Receive 60-second telemetry from a Mac agent."""
    logger.info(f"Heartbeat: serial={payload.serial} client={payload.client_id}")

    record = AgentHeartbeatRecord(
        serial=payload.serial,
        hostname=payload.hostname,
        client_id=payload.client_id,
        timestamp=datetime.utcnow(),
        cpu_load=payload.cpu_load,
        memory_pressure=payload.memory_pressure,
        disk_used_pct=payload.disk_used_pct,
        battery=payload.battery,
        sip_enabled=payload.security.sip_enabled,
        filevault_on=payload.security.filevault_on,
        firewall_on=payload.security.firewall_on,
        gatekeeper_on=payload.security.gatekeeper_on,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {"status": "ok", "id": record.id, "serial": record.serial}


# ---------- Diagnostics Upload ----------

@router.post("/diagnostics", status_code=201)
async def upload_diagnostic(
    payload: AgentDiagnosticSubmit,
    db: Session = Depends(get_db),
    _: str = Depends(verify_agent_token),
):
    """Receive full diagnostic JSON from za_diag_v3.sh via agent."""
    logger.info(f"Diagnostic upload: serial={payload.serial} client={payload.client_id}")

    report = DiagnosticReport(
        serial=payload.serial,
        hostname=payload.hostname,
        client_id=payload.client_id,
        uploaded_at=datetime.utcnow(),
        payload=payload.payload,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # Store structured snapshot + extract time-series metrics
    try:
        from app.modules.diagnostics.service import upsert_device, store_snapshot
        device_id = upsert_device(db, payload.serial, payload.client_id, payload.payload)
        snapshot_id = store_snapshot(db, device_id, payload.serial, payload.client_id, payload.payload)
        logger.info(f"Diagnostic snapshot stored: snapshot_id={snapshot_id}")
    except Exception as e:
        logger.warning(f"Diagnostic storage service error (non-fatal): {e}")

    return {"status": "ok", "id": report.id, "serial": report.serial}


# ---------- List Online Devices ----------

@router.get("/devices", response_model=List[AgentDeviceStatus])
async def list_agent_devices(
    client_id: str = Query(None),
    db: Session = Depends(get_db),
    _: str = Depends(verify_agent_token),
):
    """List devices with their latest heartbeat status."""
    cutoff = datetime.utcnow() - timedelta(seconds=ONLINE_THRESHOLD_SECONDS)

    # Subquery: latest heartbeat per serial
    from sqlalchemy import func
    latest_sub = (
        db.query(
            AgentHeartbeatRecord.serial,
            func.max(AgentHeartbeatRecord.id).label("max_id"),
        )
        .group_by(AgentHeartbeatRecord.serial)
    )
    if client_id:
        latest_sub = latest_sub.filter(AgentHeartbeatRecord.client_id == client_id)
    latest_sub = latest_sub.subquery()

    records = (
        db.query(AgentHeartbeatRecord)
        .join(latest_sub, AgentHeartbeatRecord.id == latest_sub.c.max_id)
        .order_by(desc(AgentHeartbeatRecord.timestamp))
        .all()
    )

    return [
        AgentDeviceStatus(
            serial=r.serial,
            hostname=r.hostname,
            client_id=r.client_id,
            last_seen=r.timestamp,
            cpu_load=r.cpu_load,
            memory_pressure=r.memory_pressure,
            disk_used_pct=r.disk_used_pct,
            battery=r.battery,
            online=r.timestamp >= cutoff if r.timestamp else False,
        )
        for r in records
    ]


# ---------- Single Device Status ----------

@router.get("/devices/{serial}", response_model=AgentDeviceStatus)
async def get_agent_device(
    serial: str,
    db: Session = Depends(get_db),
    _: str = Depends(verify_agent_token),
):
    """Get latest status for a single device by serial number."""
    record = (
        db.query(AgentHeartbeatRecord)
        .filter(AgentHeartbeatRecord.serial == serial)
        .order_by(desc(AgentHeartbeatRecord.timestamp))
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"No heartbeat found for serial {serial}")

    cutoff = datetime.utcnow() - timedelta(seconds=ONLINE_THRESHOLD_SECONDS)
    return AgentDeviceStatus(
        serial=record.serial,
        hostname=record.hostname,
        client_id=record.client_id,
        last_seen=record.timestamp,
        cpu_load=record.cpu_load,
        memory_pressure=record.memory_pressure,
        disk_used_pct=record.disk_used_pct,
        battery=record.battery,
        online=record.timestamp >= cutoff if record.timestamp else False,
    )
