"""
Workshop bridge — links Health Check monitoring data with Workshop PKG diagnostics.
Provides correlation between continuous monitoring and point-in-time diagnostic snapshots.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import WorkshopDiagnostic, HealthData, Device
from app.services.event_bus import publish

logger = logging.getLogger(__name__)


def on_diagnostic_upload(db: Session, diagnostic_id: int):
    """Called after a new diagnostic is uploaded — correlate with HC monitoring data."""
    diag = db.query(WorkshopDiagnostic).get(diagnostic_id)
    if not diag:
        return

    serial = diag.serial_number
    captured = diag.captured_at or datetime.utcnow()

    # Find matching device in HC
    device = db.query(Device).filter(
        Device.serial_number == serial
    ).first()

    if device:
        # Get 24h of health data before diagnostic
        window_start = captured - timedelta(hours=24)
        health_records = db.query(HealthData).filter(
            HealthData.machine_id == device.machine_id,
            HealthData.timestamp >= window_start,
            HealthData.timestamp <= captured,
        ).all()

        if health_records:
            avg_cpu = sum(h.cpu_percent or 0 for h in health_records) / len(health_records)
            avg_mem = sum(h.memory_percent or 0 for h in health_records) / len(health_records)
            avg_disk = sum(h.disk_percent or 0 for h in health_records) / len(health_records)

            publish(
                db, event_type="workshop.correlated", source="workshop_bridge",
                summary=f"Diagnostic {diagnostic_id} correlated with {len(health_records)} HC records for {serial}",
                severity="info",
                device_serial=serial, client_id=diag.client_id,
                detail={
                    "diagnostic_id": diagnostic_id,
                    "health_records_24h": len(health_records),
                    "avg_cpu_24h": round(avg_cpu, 1),
                    "avg_memory_24h": round(avg_mem, 1),
                    "avg_disk_24h": round(avg_disk, 1),
                },
            )

    # Always emit diagnostic received event
    publish(
        db, event_type="workshop.diagnostic_received", source="workshop_bridge",
        summary=f"Diagnostic uploaded for {diag.hostname or serial} ({diag.mode or 'full'} mode)",
        severity="info",
        device_serial=serial, client_id=diag.client_id,
        detail={
            "diagnostic_id": diagnostic_id,
            "version": diag.diagnostic_version,
            "recommendation_count": diag.recommendation_count or 0,
        },
    )


def get_device_timeline(db: Session, serial: str, days: int = 30) -> dict:
    """Build a combined timeline of HC monitoring + diagnostics for a device."""
    since = datetime.utcnow() - timedelta(days=days)

    diagnostics = db.query(WorkshopDiagnostic).filter(
        WorkshopDiagnostic.serial_number == serial,
        WorkshopDiagnostic.captured_at >= since,
    ).order_by(WorkshopDiagnostic.captured_at.desc()).all()

    device = db.query(Device).filter(Device.serial_number == serial).first()
    health_summary = None
    if device:
        records = db.query(HealthData).filter(
            HealthData.machine_id == device.machine_id,
            HealthData.timestamp >= since,
        ).count()
        health_summary = {"total_records": records, "period_days": days}

    return {
        "serial": serial,
        "diagnostics": len(diagnostics),
        "health_monitoring": health_summary,
        "latest_diagnostic": diagnostics[0].captured_at.isoformat() if diagnostics else None,
    }
