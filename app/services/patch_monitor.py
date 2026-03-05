"""
Patch monitor — checks device OS versions against latest known macOS releases.
Generates events when devices are behind on patches.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import (
    AgentHeartbeatRecord, PatchStatus, Device
)
from app.services.event_bus import publish

logger = logging.getLogger(__name__)

# Known latest macOS versions (updated manually or via Apple feed)
LATEST_MACOS = {
    "15": "15.3.2",   # Sequoia
    "14": "14.7.4",   # Sonoma
    "13": "13.7.4",   # Ventura
    "12": "12.7.6",   # Monterey
}


def _parse_major(version: str) -> Optional[str]:
    """Extract major version number."""
    if not version:
        return None
    parts = version.split(".")
    return parts[0] if parts else None


def check_all_devices(db: Session):
    """Scan all active devices for patch status."""
    logger.info("[PatchMonitor] Starting patch scan...")
    devices = db.query(Device).filter(Device.is_active == True).all()
    events_count = 0

    for device in devices:
        if not device.os_version:
            continue

        major = _parse_major(device.os_version)
        latest = LATEST_MACOS.get(major)
        if not latest:
            continue

        is_current = device.os_version == latest
        days_behind = 0 if is_current else _estimate_days_behind(device.os_version, latest)

        # Upsert patch status
        ps = db.query(PatchStatus).filter(
            PatchStatus.device_serial == (device.serial_number or device.machine_id)
        ).first()

        if not ps:
            ps = PatchStatus(
                device_serial=device.serial_number or device.machine_id,
                client_id=device.client_id,
            )
            db.add(ps)

        ps.current_os = device.os_version
        ps.latest_os = latest
        ps.days_behind = days_behind
        ps.last_checked = datetime.now(timezone.utc)

        if not is_current and days_behind > 14:
            severity = "critical" if days_behind > 60 else "high"
            publish(
                db, event_type="patch.outdated", source="patch_monitor",
                summary=f"{device.hostname or device.machine_id} running {device.os_version} (latest: {latest})",
                severity=severity,
                device_serial=device.serial_number or device.machine_id,
                client_id=device.client_id,
                detail={"current": device.os_version, "latest": latest, "days_behind": days_behind},
            )
            events_count += 1

    db.commit()
    logger.info(f"[PatchMonitor] Scan complete. {len(devices)} devices, {events_count} alerts.")


def _estimate_days_behind(current: str, latest: str) -> int:
    """Rough estimate of days behind based on version difference."""
    try:
        c_parts = [int(x) for x in current.split(".")]
        l_parts = [int(x) for x in latest.split(".")]
        # Each minor version ~30 days, each patch ~14 days
        major_diff = (l_parts[0] - c_parts[0]) * 180
        minor_diff = (l_parts[1] if len(l_parts) > 1 else 0) - (c_parts[1] if len(c_parts) > 1 else 0)
        patch_diff = (l_parts[2] if len(l_parts) > 2 else 0) - (c_parts[2] if len(c_parts) > 2 else 0)
        return max(0, major_diff + minor_diff * 30 + patch_diff * 14)
    except (ValueError, IndexError):
        return 30  # Default estimate
