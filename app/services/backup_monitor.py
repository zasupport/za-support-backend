"""
Backup monitor — checks Time Machine and third-party backup status from diagnostic data.
Alerts when no backup is configured or backups are stale.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.models import BackupStatus, WorkshopDiagnostic, Device
from app.services.event_bus import publish

logger = logging.getLogger(__name__)

# Third-party backup agents we detect (from diagnostic v3.0 section 27)
BACKUP_AGENTS = [
    "Carbonite", "Backblaze", "CrashPlan", "Code42",
    "Arq", "ChronoSync", "Acronis",
]

STALE_DAYS_WARNING = 7
STALE_DAYS_CRITICAL = 30


def check_all_devices(db: Session):
    """Scan diagnostics and health data for backup status."""
    logger.info("[BackupMonitor] Starting backup scan...")
    devices = db.query(Device).filter(Device.is_active == True).all()
    events_count = 0

    for device in devices:
        serial = device.serial_number or device.machine_id

        # Get latest diagnostic for this device (if any)
        diag = db.query(WorkshopDiagnostic).filter(
            WorkshopDiagnostic.serial_number == serial
        ).order_by(WorkshopDiagnostic.captured_at.desc()).first()

        # Upsert backup status
        bs = db.query(BackupStatus).filter(
            BackupStatus.device_serial == serial
        ).first()

        if not bs:
            bs = BackupStatus(device_serial=serial, client_id=device.client_id)
            db.add(bs)

        bs.last_checked = datetime.now(timezone.utc)
        bs.client_id = device.client_id

        if diag and diag.raw_json:
            raw = diag.raw_json if isinstance(diag.raw_json, dict) else {}
            _update_from_diagnostic(bs, raw)

        # Generate events for missing/stale backups
        if bs.no_backup:
            publish(
                db, event_type="backup.missing", source="backup_monitor",
                summary=f"No backup configured on {device.hostname or serial}",
                severity="critical",
                device_serial=serial, client_id=device.client_id,
                detail={"time_machine": False, "third_party": None},
            )
            events_count += 1
        elif bs.tm_days_stale and bs.tm_days_stale > STALE_DAYS_WARNING:
            severity = "critical" if bs.tm_days_stale > STALE_DAYS_CRITICAL else "high"
            publish(
                db, event_type="backup.stale", source="backup_monitor",
                summary=f"Time Machine {bs.tm_days_stale}d stale on {device.hostname or serial}",
                severity=severity,
                device_serial=serial, client_id=device.client_id,
                detail={"tm_days_stale": bs.tm_days_stale},
            )
            events_count += 1

    db.commit()
    logger.info(f"[BackupMonitor] Scan complete. {len(devices)} devices, {events_count} alerts.")


def _update_from_diagnostic(bs: BackupStatus, raw: dict):
    """Extract backup info from diagnostic JSON."""
    # Section 27 — Time Machine Deep
    tm = raw.get("time_machine", {})
    if isinstance(tm, dict):
        bs.time_machine_enabled = tm.get("enabled", False)
        last_backup_str = tm.get("last_backup")
        if last_backup_str:
            try:
                last_dt = datetime.fromisoformat(last_backup_str.replace("Z", "+00:00"))
                bs.last_tm_backup = last_dt
                bs.tm_days_stale = (datetime.now(timezone.utc) - last_dt.replace(tzinfo=None)).days
            except (ValueError, TypeError):
                pass

        # Third-party detection
        agents = tm.get("third_party_agents", [])
        if agents:
            bs.third_party_agent = agents[0] if isinstance(agents, list) else str(agents)

    # If no TM and no third-party, flag as no backup
    if not bs.time_machine_enabled and not bs.third_party_agent:
        bs.no_backup = True
    else:
        bs.no_backup = False
