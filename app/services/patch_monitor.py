"""
Patch monitor — checks device OS versions against latest known macOS releases.
Generates events when devices are behind on patches.
"""
import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import (
    AgentHeartbeatRecord, PatchStatus, Device
)
from app.services.event_bus import publish

logger = logging.getLogger(__name__)

# Fallback versions — auto-updated each run from Apple GDMF API
_LATEST_MACOS_FALLBACK = {
    "15": "15.3.2",   # Sequoia
    "14": "14.7.4",   # Sonoma
    "13": "13.7.4",   # Ventura
    "12": "12.7.6",   # Monterey
}

_GDMF_URL = "https://gdmf.apple.com/v2/pmv"


def _fetch_apple_versions() -> dict:
    """Fetch latest macOS versions from Apple's GDMF API.
    Returns dict of {major: full_version} or fallback on any error.
    """
    try:
        req = urllib.request.Request(
            _GDMF_URL,
            headers={"User-Agent": "ZASupport-PatchMonitor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        versions: dict[str, str] = {}
        for entry in data.get("PublicAssetSets", {}).get("macOS", []):
            product = entry.get("ProductVersion", "")
            if not product:
                continue
            major = product.split(".")[0]
            existing = versions.get(major, "0")
            # Keep highest version per major
            if _ver_gt(product, existing):
                versions[major] = product

        if versions:
            logger.info(f"[PatchMonitor] GDMF fetch: {versions}")
            return versions
    except Exception as e:
        logger.warning(f"[PatchMonitor] GDMF fetch failed, using fallback: {e}")
    return _LATEST_MACOS_FALLBACK.copy()


def _ver_gt(a: str, b: str) -> bool:
    """Return True if version a > version b."""
    try:
        return [int(x) for x in a.split(".")] > [int(x) for x in b.split(".")]
    except ValueError:
        return False


def _parse_major(version: str) -> Optional[str]:
    """Extract major version number."""
    if not version:
        return None
    parts = version.split(".")
    return parts[0] if parts else None


def check_all_devices(db: Session):
    """Scan all active devices for patch status."""
    logger.info("[PatchMonitor] Starting patch scan...")
    LATEST_MACOS = _fetch_apple_versions()
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
