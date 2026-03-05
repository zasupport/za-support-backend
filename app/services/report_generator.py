"""
Report generator — produces device health summary reports.
Generates JSON reports (PDF rendering deferred to frontend/reportlab layer).
"""
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Device, HealthData, Alert, WorkshopDiagnostic, PatchStatus, BackupStatus
from app.services.event_bus import publish

logger = logging.getLogger(__name__)

REPORT_OUTPUT_DIR = os.getenv("HC_REPORT_OUTPUT_DIR", "/var/hc_reports")


def generate_device_report(db: Session, serial: str, days: int = 30) -> dict:
    """Generate a health summary report for a single device."""
    device = db.query(Device).filter(Device.serial_number == serial).first()
    if not device:
        return {"error": f"Device {serial} not found"}

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Health data aggregation
    health_agg = db.query(
        func.avg(HealthData.cpu_percent).label("avg_cpu"),
        func.avg(HealthData.memory_percent).label("avg_mem"),
        func.avg(HealthData.disk_percent).label("avg_disk"),
        func.max(HealthData.cpu_percent).label("max_cpu"),
        func.max(HealthData.memory_percent).label("max_mem"),
        func.count(HealthData.id).label("total_records"),
    ).filter(
        HealthData.machine_id == device.machine_id,
        HealthData.timestamp >= since,
    ).first()

    # Alert counts
    alert_counts = db.query(
        Alert.severity, func.count(Alert.id)
    ).filter(
        Alert.machine_id == device.machine_id,
        Alert.timestamp >= since,
    ).group_by(Alert.severity).all()

    # Patch status
    patch = db.query(PatchStatus).filter(
        PatchStatus.device_serial == serial
    ).first()

    # Backup status
    backup = db.query(BackupStatus).filter(
        BackupStatus.device_serial == serial
    ).first()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_days": days,
        "device": {
            "serial": serial,
            "hostname": device.hostname,
            "model": device.model_identifier,
            "os_version": device.os_version,
            "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        },
        "health": {
            "avg_cpu": round(health_agg.avg_cpu, 1) if health_agg.avg_cpu else None,
            "avg_memory": round(health_agg.avg_mem, 1) if health_agg.avg_mem else None,
            "avg_disk": round(health_agg.avg_disk, 1) if health_agg.avg_disk else None,
            "max_cpu": round(health_agg.max_cpu, 1) if health_agg.max_cpu else None,
            "max_memory": round(health_agg.max_mem, 1) if health_agg.max_mem else None,
            "total_records": health_agg.total_records or 0,
        },
        "alerts": {row[0]: row[1] for row in alert_counts},
        "patch_status": {
            "current_os": patch.current_os if patch else None,
            "latest_os": patch.latest_os if patch else None,
            "days_behind": patch.days_behind if patch else 0,
        },
        "backup_status": {
            "time_machine": backup.time_machine_enabled if backup else None,
            "last_backup": backup.last_tm_backup.isoformat() if backup and backup.last_tm_backup else None,
            "no_backup": backup.no_backup if backup else None,
        },
    }

    return report


def generate_all_reports(db: Session):
    """Generate reports for all active devices — scheduled job."""
    logger.info("[ReportGen] Starting report generation...")
    devices = db.query(Device).filter(Device.is_active == True).all()

    for device in devices:
        serial = device.serial_number or device.machine_id
        try:
            report = generate_device_report(db, serial)
            # Save to disk if output dir exists
            if os.path.isdir(REPORT_OUTPUT_DIR):
                filename = f"hc_report_{serial}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json"
                filepath = os.path.join(REPORT_OUTPUT_DIR, filename)
                with open(filepath, "w") as f:
                    json.dump(report, f, indent=2)

            publish(
                db, event_type="report.generated", source="report_generator",
                summary=f"Health report generated for {device.hostname or serial}",
                severity="info",
                device_serial=serial, client_id=device.client_id,
            )
        except Exception as e:
            logger.error(f"Report generation failed for {serial}: {e}")

    db.commit()
    logger.info(f"[ReportGen] Generated reports for {len(devices)} devices.")
