"""
Backup monitor — checks Time Machine and CCC backup status from Scout v3 diagnostic data.
Reads diagnostic_snapshots (environment section, flat fields from environment_mod.sh).
Alerts when no backup is configured or backups are stale.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.models import BackupStatus
from app.services.event_bus import publish

logger = logging.getLogger(__name__)

STALE_DAYS_WARNING  = 7
STALE_DAYS_CRITICAL = 30


def check_all_devices(db: Session):
    """Scan latest diagnostic snapshots for backup status (one per serial)."""
    logger.info("[BackupMonitor] Starting backup scan...")

    # One latest snapshot per serial
    rows = db.execute(
        text("""
        SELECT DISTINCT ON (serial)
            serial, client_id, raw_json,
            raw_json::json->'system'->>'hostname' AS hostname
        FROM diagnostic_snapshots
        ORDER BY serial, scan_date DESC
        """)
    ).fetchall()

    events_count = 0

    for row in rows:
        serial    = row.serial
        client_id = row.client_id
        hostname  = row.hostname or serial

        try:
            raw = json.loads(row.raw_json) if isinstance(row.raw_json, str) else (row.raw_json or {})
        except Exception:
            raw = {}

        env = raw.get("environment", {})

        # ── Parse flat fields written by environment_mod.sh ──────────────
        tm_status  = (env.get("time_machine_status") or "").upper()
        days_raw   = env.get("time_machine_days_ago")
        try:
            tm_days = int(days_raw) if days_raw not in (None, "UNKNOWN", "") else None
        except (ValueError, TypeError):
            tm_days = None

        tm_enabled   = tm_status not in ("DISABLED", "")
        ccc_installed = (env.get("ccc_installed") or "NO").upper() == "YES"

        # ── Upsert backup status record ───────────────────────────────────
        bs = db.query(BackupStatus).filter(BackupStatus.device_serial == serial).first()
        if not bs:
            bs = BackupStatus(device_serial=serial, client_id=client_id)
            db.add(bs)

        bs.last_checked       = datetime.now(timezone.utc)
        bs.client_id          = client_id
        bs.time_machine_enabled = tm_enabled
        if tm_days is not None:
            bs.tm_days_stale  = tm_days
        if ccc_installed:
            bs.third_party_agent = "CCC"
        bs.no_backup = not tm_enabled and not ccc_installed

        # ── Generate alerts ───────────────────────────────────────────────
        if bs.no_backup:
            publish(
                db, event_type="backup.missing", source="backup_monitor",
                summary=f"No backup configured on {hostname}",
                severity="critical",
                device_serial=serial, client_id=client_id,
                detail={"time_machine": False, "ccc": False},
            )
            events_count += 1
        elif tm_days is not None and tm_days > STALE_DAYS_WARNING:
            severity = "critical" if tm_days > STALE_DAYS_CRITICAL else "high"
            publish(
                db, event_type="backup.stale", source="backup_monitor",
                summary=f"Time Machine {tm_days}d stale on {hostname}",
                severity=severity,
                device_serial=serial, client_id=client_id,
                detail={"tm_days_stale": tm_days},
            )
            events_count += 1

    db.commit()
    logger.info(f"[BackupMonitor] Scan complete. {len(rows)} devices, {events_count} alerts.")
