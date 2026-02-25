"""
Diagnostic upload and retrieval — receives za_diag_v3.sh JSON output.

This is the endpoint the script POSTs to when run with:
    sudo ./za_diag_v3.sh --push --client CLIENT_ID

The script generates a comprehensive JSON payload with 215 data points
across 53 sections. This endpoint ingests the full payload, extracts
indexed summary fields for fast queries, and stores the complete JSON
for deep analysis.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
from typing import Optional, List
import logging

from app.core.database import get_db
from app.core.auth import verify_api_key
from app.models.models import WorkshopDiagnostic
from app.models.schemas import (
    DiagnosticUpload, DiagnosticResponse, DiagnosticSummary
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _safe_float(val) -> Optional[float]:
    """Convert string/int/float to float, return None for N/A or null."""
    if val is None or val == "null" or val == "N/A" or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    """Convert string/int to int, return None for N/A or null."""
    if val is None or val == "null" or val == "N/A" or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# ---------- Upload ----------

@router.post("/upload", status_code=201)
async def upload_diagnostic(
    payload: DiagnosticUpload,
    db: Session = Depends(get_db),
):
    """
    Receive diagnostic JSON from za_diag_v3.sh --push.
    
    No API key required — the script runs on client machines that
    may not have credentials. The serial number + timestamp provide
    sufficient identification. Rate limiting should be handled at
    the infrastructure level (Render/Cloudflare).
    """
    logger.info(
        f"Diagnostic upload: serial={payload.serial} "
        f"client={payload.client_id} mode={payload.mode} "
        f"v={payload.version} recs={payload.recommendation_count}"
    )

    # Parse battery fields (strings in JSON, stored as numbers)
    batt_health = _safe_float(payload.battery.health_pct)
    batt_cycles = _safe_int(payload.battery.cycles)
    batt_design = _safe_int(payload.battery.design_capacity_mah)
    batt_max = _safe_int(payload.battery.max_capacity_mah)

    record = WorkshopDiagnostic(
        # Identity
        serial_number=payload.serial or payload.hardware.serial,
        hostname=payload.hostname,
        client_id=payload.client_id if payload.client_id else None,
        diagnostic_version=payload.version,
        mode=payload.mode,

        # Hardware
        chip_type=payload.hardware.chip_type,
        model_name=payload.hardware.model,
        model_identifier=payload.hardware.model_id,
        ram_gb=payload.hardware.ram_gb,
        ram_upgradeable=payload.hardware.ram_upgradeable,
        cpu_name=payload.hardware.cpu,
        cores_physical=payload.hardware.cores_physical,
        cores_logical=payload.hardware.cores_logical,

        # macOS
        macos_version=payload.macos.version,
        macos_build=payload.macos.build,
        uptime_seconds=payload.macos.uptime_seconds,

        # Security
        sip_enabled=bool(payload.security.sip_enabled),
        filevault_on=bool(payload.security.filevault_on),
        firewall_on=bool(payload.security.firewall_on),
        gatekeeper_on=bool(payload.security.gatekeeper_on),
        xprotect_version=payload.security.xprotect_version,
        password_manager=payload.security.password_manager,
        av_edr=payload.security.av_edr,

        # Battery
        battery_health_pct=batt_health,
        battery_cycles=batt_cycles,
        battery_design_capacity=batt_design,
        battery_max_capacity=batt_max,
        battery_condition=payload.battery.condition,

        # Storage
        disk_used_pct=payload.storage.boot_disk_used_pct,
        disk_free_gb=payload.storage.boot_disk_free_gb,

        # OCLP
        oclp_detected=payload.oclp.detected,
        oclp_version=payload.oclp.version,
        oclp_root_patched=payload.oclp.root_patched,
        third_party_kexts=payload.oclp.third_party_kexts,

        # Diagnostics
        kernel_panics=payload.diagnostics.kernel_panics,
        total_processes=payload.diagnostics.total_processes,

        # Recommendations
        recommendations=[r.model_dump() for r in payload.recommendations],
        recommendation_count=payload.recommendation_count,

        # Full payload
        raw_json=payload.model_dump(),
        runtime_seconds=payload.runtime_seconds,

        # Timestamps
        captured_at=datetime.utcnow(),
        uploaded_at=datetime.utcnow(),
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(f"Diagnostic stored: id={record.id} serial={record.serial_number}")

    return {
        "status": "success",
        "id": record.id,
        "serial": record.serial_number,
        "recommendations": record.recommendation_count,
        "message": f"Diagnostic v{payload.version} ({payload.mode} mode) stored successfully.",
    }


# ---------- List diagnostics for a device ----------

@router.get("/device/{serial_number}", response_model=List[DiagnosticSummary])
async def list_device_diagnostics(
    serial_number: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """List all diagnostics for a device by serial number."""
    records = (
        db.query(WorkshopDiagnostic)
        .filter(WorkshopDiagnostic.serial_number == serial_number)
        .order_by(desc(WorkshopDiagnostic.captured_at))
        .limit(limit)
        .all()
    )
    if not records:
        raise HTTPException(status_code=404, detail=f"No diagnostics found for {serial_number}")
    return records


# ---------- Get single diagnostic ----------

@router.get("/{diagnostic_id}", response_model=DiagnosticResponse)
async def get_diagnostic(
    diagnostic_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Get a single diagnostic by ID with full details."""
    record = db.query(WorkshopDiagnostic).filter(WorkshopDiagnostic.id == diagnostic_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Diagnostic not found")
    return record


# ---------- List all diagnostics ----------

@router.get("/", response_model=List[DiagnosticSummary])
async def list_all_diagnostics(
    client_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """List all diagnostics, optionally filtered by client_id."""
    q = db.query(WorkshopDiagnostic)
    if client_id:
        q = q.filter(WorkshopDiagnostic.client_id == client_id)
    return q.order_by(desc(WorkshopDiagnostic.captured_at)).limit(limit).all()


# ---------- Compare two diagnostics ----------

@router.get("/compare/{id1}/{id2}")
async def compare_diagnostics(
    id1: int,
    id2: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Compare two diagnostic snapshots for the same or different devices."""
    d1 = db.query(WorkshopDiagnostic).filter(WorkshopDiagnostic.id == id1).first()
    d2 = db.query(WorkshopDiagnostic).filter(WorkshopDiagnostic.id == id2).first()

    if not d1 or not d2:
        raise HTTPException(status_code=404, detail="One or both diagnostics not found")

    def _delta(a, b, label):
        if a is None or b is None:
            return {"field": label, "before": a, "after": b, "delta": None}
        try:
            return {"field": label, "before": a, "after": b, "delta": round(b - a, 2)}
        except TypeError:
            return {"field": label, "before": a, "after": b, "delta": None}

    return {
        "diagnostic_1": {"id": d1.id, "serial": d1.serial_number, "captured_at": d1.captured_at.isoformat() if d1.captured_at else None},
        "diagnostic_2": {"id": d2.id, "serial": d2.serial_number, "captured_at": d2.captured_at.isoformat() if d2.captured_at else None},
        "same_device": d1.serial_number == d2.serial_number,
        "deltas": [
            _delta(d1.battery_health_pct, d2.battery_health_pct, "battery_health_pct"),
            _delta(d1.battery_cycles, d2.battery_cycles, "battery_cycles"),
            _delta(d1.disk_used_pct, d2.disk_used_pct, "disk_used_pct"),
            _delta(d1.disk_free_gb, d2.disk_free_gb, "disk_free_gb"),
            _delta(d1.kernel_panics, d2.kernel_panics, "kernel_panics"),
            _delta(d1.total_processes, d2.total_processes, "total_processes"),
            _delta(d1.recommendation_count, d2.recommendation_count, "recommendation_count"),
        ],
        "security_changes": {
            "sip": {"before": d1.sip_enabled, "after": d2.sip_enabled},
            "filevault": {"before": d1.filevault_on, "after": d2.filevault_on},
            "firewall": {"before": d1.firewall_on, "after": d2.firewall_on},
            "gatekeeper": {"before": d1.gatekeeper_on, "after": d2.gatekeeper_on},
        },
    }
