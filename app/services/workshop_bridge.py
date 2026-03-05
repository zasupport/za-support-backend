"""
Workshop bridge — links Health Check monitoring data with Workshop PKG diagnostics.
Provides correlation between continuous monitoring and point-in-time diagnostic snapshots.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import DiagnosticReport, HealthData, Device
from app.services.event_bus import publish

logger = logging.getLogger(__name__)


def on_diagnostic_upload(db: Session, report_id: int):
    """Called after a new DiagnosticReport is saved — correlate with HC monitoring data."""
    report = db.query(DiagnosticReport).get(report_id)
    if not report:
        return

    serial = report.serial
    captured = report.uploaded_at or datetime.now(timezone.utc)
    payload = report.payload if isinstance(report.payload, dict) else {}

    rec_count = len(payload.get("recommendations", [])) if payload else 0
    risk_level = payload.get("risk_level", "unknown") if payload else "unknown"

    # Find matching device in HC for health data correlation
    device = db.query(Device).filter(Device.serial_number == serial).first()

    if device:
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
                summary=f"Diagnostic {report_id} correlated with {len(health_records)} HC records for {serial}",
                severity="info",
                device_serial=serial, client_id=report.client_id,
                detail={
                    "report_id": report_id,
                    "health_records_24h": len(health_records),
                    "avg_cpu_24h": round(avg_cpu, 1),
                    "avg_memory_24h": round(avg_mem, 1),
                    "avg_disk_24h": round(avg_disk, 1),
                },
            )

    publish(
        db, event_type="workshop.diagnostic_received", source="workshop_bridge",
        summary=f"Diagnostic uploaded for {report.hostname or serial} (risk: {risk_level})",
        severity="info",
        device_serial=serial, client_id=report.client_id,
        detail={
            "report_id": report_id,
            "risk_level": risk_level,
            "recommendation_count": rec_count,
        },
    )


def get_device_timeline(db: Session, serial: str, days: int = 30) -> dict:
    """Build a combined timeline of HC monitoring + diagnostics for a device."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

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
