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

from sqlalchemy import text

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


def _check_device(db: Session, serial: str, client_id: str, hostname: str, os_version: str, LATEST_MACOS: dict) -> bool:
    """Check one device against latest macOS versions. Returns True if alert was emitted."""
    major = _parse_major(os_version)
    latest = LATEST_MACOS.get(major)
    if not latest:
        return False

    is_current = os_version == latest
    days_behind = 0 if is_current else _estimate_days_behind(os_version, latest)

    ps = db.query(PatchStatus).filter(PatchStatus.device_serial == serial).first()
    if not ps:
        ps = PatchStatus(device_serial=serial, client_id=client_id)
        db.add(ps)

    ps.current_os = os_version
    ps.latest_os = latest
    ps.days_behind = days_behind
    ps.last_checked = datetime.now(timezone.utc)

    if not is_current and days_behind > 14:
        severity = "critical" if days_behind > 60 else "high"
        publish(
            db, event_type="patch.outdated", source="patch_monitor",
            summary=f"{hostname} running {os_version} (latest: {latest})",
            severity=severity,
            device_serial=serial,
            client_id=client_id,
            detail={"current": os_version, "latest": latest, "days_behind": days_behind},
        )
        return True
    return False


def check_all_devices(db: Session):
    """Scan all active devices for patch status — Shield Agent devices + Scout v3 devices."""
    logger.info("[PatchMonitor] Starting patch scan...")
    LATEST_MACOS = _fetch_apple_versions()
    events_count = 0
    seen_serials: set = set()

    # ── 1. Shield Agent devices (legacy Device model) ─────────────────────────
    devices = db.query(Device).filter(Device.is_active == True).all()
    for device in devices:
        if not device.os_version:
            continue
        serial = device.serial_number or device.machine_id
        seen_serials.add(serial)
        if _check_device(db, serial, device.client_id or "", device.hostname or serial, device.os_version, LATEST_MACOS):
            events_count += 1

    # ── 2. Scout v3 devices (client_devices table) ────────────────────────────
    # These are devices that run Scout but may not have the Shield Agent installed.
    scout_rows = db.execute(
        text("""
        SELECT serial, client_id, hostname, macos_version
        FROM client_devices
        WHERE is_active = TRUE
          AND macos_version IS NOT NULL
          AND macos_version != ''
        ORDER BY serial
        """)
    ).fetchall()

    for row in scout_rows:
        if row.serial in seen_serials:
            continue  # Already processed via Shield Agent scan
        seen_serials.add(row.serial)
        if _check_device(db, row.serial, row.client_id or "", row.hostname or row.serial, row.macos_version, LATEST_MACOS):
            events_count += 1

    db.commit()
    logger.info(f"[PatchMonitor] Scan complete. {len(seen_serials)} devices, {events_count} alerts.")


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
