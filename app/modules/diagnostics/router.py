"""
Diagnostic Storage Router — retrieval API for stored diagnostic data.
Prefix: /api/v1/diagnostics
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostic_storage"])


# ── Device Registry ───────────────────────────────────────────────────


@router.get("/devices", dependencies=[Depends(verify_agent_token)])
def list_devices(
    client_id: Optional[str] = Query(None),
    search:    Optional[str] = Query(None, description="Search by serial, hostname, or client_id"),
    is_active: bool = Query(True),
    per_page:  int  = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all registered devices with optional search."""
    conditions = ["is_active = :active"]
    params: dict = {"active": is_active}
    if client_id:
        conditions.append("client_id = :client_id")
        params["client_id"] = client_id
    if search:
        conditions.append("(serial ILIKE :s OR hostname ILIKE :s OR client_id ILIKE :s)")
        params["s"] = f"%{search}%"
    where = " AND ".join(conditions)
    rows = db.execute(
        text(f"SELECT * FROM client_devices WHERE {where} ORDER BY last_seen DESC LIMIT :n"),
        {**params, "n": per_page},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/devices/{serial}", dependencies=[Depends(verify_agent_token)])
def get_device(serial: str, db: Session = Depends(get_db)):
    """Device detail with latest snapshot summary."""
    device = db.execute(
        text("SELECT * FROM client_devices WHERE serial = :serial"),
        {"serial": serial},
    ).fetchone()
    if not device:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Device not found")

    latest = db.execute(
        text("""
        SELECT id, scan_date, risk_score, risk_level, recommendation_count, version
        FROM diagnostic_snapshots
        WHERE serial = :serial
        ORDER BY scan_date DESC LIMIT 1
        """),
        {"serial": serial},
    ).fetchone()

    return {
        **dict(device._mapping),
        "latest_snapshot": dict(latest._mapping) if latest else None,
    }


# ── Snapshots ─────────────────────────────────────────────────────────


@router.get("/devices/{serial}/history", dependencies=[Depends(verify_agent_token)])
def get_device_history(
    serial: str,
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(50),
    db: Session = Depends(get_db),
):
    """All diagnostic snapshots for a device (excludes raw_json for size)."""
    q = """
        SELECT id, scan_date, risk_score, risk_level, recommendation_count,
               version, mode, reason, runtime_seconds
        FROM diagnostic_snapshots
        WHERE serial = :serial
    """
    params: dict = {"serial": serial}
    if from_date:
        q += " AND scan_date >= :from_date"
        params["from_date"] = from_date
    if to_date:
        q += " AND scan_date <= :to_date"
        params["to_date"] = to_date
    q += " ORDER BY scan_date DESC LIMIT :limit"
    params["limit"] = limit
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/snapshots/{snapshot_id}", dependencies=[Depends(verify_agent_token)])
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    """Full snapshot detail including raw_json."""
    row = db.execute(
        text("SELECT * FROM diagnostic_snapshots WHERE id = :id"),
        {"id": snapshot_id},
    ).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return dict(row._mapping)


# ── Time-Series Metrics ───────────────────────────────────────────────


@router.get("/devices/{serial}/metrics", dependencies=[Depends(verify_agent_token)])
def get_device_metrics(
    serial: str,
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    metric: Optional[str] = Query(None, description="Filter to single metric column"),
    db: Session = Depends(get_db),
):
    """Time-series metrics for a device."""
    # Whitelist columns to prevent injection
    allowed = {
        "battery_health_pct", "battery_cycle_count", "disk_used_pct", "disk_free_gb",
        "ram_pressure_pct", "swap_used_mb", "process_count",
        "filevault_on", "firewall_on", "sip_enabled",
        "risk_score", "threat_count", "malware_findings",
    }
    cols = metric if metric in allowed else "*"

    q = f"SELECT time, serial, {cols} FROM device_metrics WHERE serial = :serial"
    params: dict = {"serial": serial}
    if from_date:
        q += " AND time >= :from_date"
        params["from_date"] = from_date
    if to_date:
        q += " AND time <= :to_date"
        params["to_date"] = to_date
    q += " ORDER BY time DESC LIMIT 1000"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.get("/devices/{serial}/trends", dependencies=[Depends(verify_agent_token)])
def get_device_trends(serial: str, db: Session = Depends(get_db)):
    """Computed trends: battery degradation, disk fill rate, risk score direction."""
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_7 = datetime.now(timezone.utc) - timedelta(days=7)

    rows_30 = db.execute(
        text("""
        SELECT
            MIN(battery_health_pct)  AS battery_min,
            MAX(battery_health_pct)  AS battery_max,
            MIN(disk_used_pct)       AS disk_min,
            MAX(disk_used_pct)       AS disk_max,
            MIN(risk_score)          AS risk_min,
            MAX(risk_score)          AS risk_max,
            COUNT(*)                 AS samples
        FROM device_metrics
        WHERE serial = :serial AND time >= :cutoff
        """),
        {"serial": serial, "cutoff": cutoff_30},
    ).fetchone()

    rows_7 = db.execute(
        text("""
        SELECT
            AVG(risk_score)     AS avg_risk,
            AVG(disk_used_pct)  AS avg_disk,
            AVG(battery_health_pct) AS avg_battery
        FROM device_metrics
        WHERE serial = :serial AND time >= :cutoff
        """),
        {"serial": serial, "cutoff": cutoff_7},
    ).fetchone()

    return {
        "serial": serial,
        "last_30_days": dict(rows_30._mapping) if rows_30 else {},
        "last_7_days":  dict(rows_7._mapping) if rows_7 else {},
    }


# ── Alerts ────────────────────────────────────────────────────────────


@router.get("/devices/trend-alerts", dependencies=[Depends(verify_agent_token)])
def get_trend_alerts(
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Proactive trend alerts: devices on a deteriorating trajectory.
    Flags: battery declining >10% / disk growing >15% / risk increasing >20pts in 30 days.
    Only devices with >=3 metric samples in the last 30 days are evaluated.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Get first and last reading in 30-day window for each device
    q = """
        SELECT
            serial,
            FIRST_VALUE(battery_health_pct) OVER w AS battery_start,
            LAST_VALUE(battery_health_pct)  OVER w AS battery_end,
            FIRST_VALUE(disk_used_pct)      OVER w AS disk_start,
            LAST_VALUE(disk_used_pct)       OVER w AS disk_end,
            FIRST_VALUE(risk_score)         OVER w AS risk_start,
            LAST_VALUE(risk_score)          OVER w AS risk_end,
            COUNT(*) OVER (PARTITION BY serial) AS sample_count
        FROM device_metrics
        WHERE time >= :cutoff
        WINDOW w AS (
            PARTITION BY serial ORDER BY time
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        )
    """
    params: dict = {"cutoff": cutoff}

    rows = db.execute(text(q), params).fetchall()

    # Deduplicate (window fn repeats per-row), apply thresholds
    seen: set = set()
    alerts = []
    for r in rows:
        serial = r.serial
        if serial in seen:
            continue
        seen.add(serial)

        if (r.sample_count or 0) < 3:
            continue

        alert_types = []
        battery_drop = None
        disk_rise = None
        risk_rise = None

        if r.battery_start is not None and r.battery_end is not None:
            battery_drop = float(r.battery_start) - float(r.battery_end)
            if battery_drop > 10:
                alert_types.append("battery_declining")

        if r.disk_start is not None and r.disk_end is not None:
            disk_rise = float(r.disk_end) - float(r.disk_start)
            if disk_rise > 15:
                alert_types.append("disk_filling")

        if r.risk_start is not None and r.risk_end is not None:
            risk_rise = float(r.risk_end) - float(r.risk_start)
            if risk_rise > 20:
                alert_types.append("risk_escalating")

        if not alert_types:
            continue

        # Look up device metadata
        dev = db.execute(
            text("SELECT hostname, model, client_id FROM client_devices WHERE serial = :s"),
            {"s": serial},
        ).fetchone()

        if client_id and (not dev or dev.client_id != client_id):
            continue

        alerts.append({
            "serial": serial,
            "client_id": dev.client_id if dev else None,
            "hostname": dev.hostname if dev else None,
            "model": dev.model if dev else None,
            "alert_types": alert_types,
            "battery_drop_pct": round(battery_drop, 1) if battery_drop is not None else None,
            "disk_rise_pct": round(disk_rise, 1) if disk_rise is not None else None,
            "risk_rise_pts": round(risk_rise, 1) if risk_rise is not None else None,
            "samples": r.sample_count,
        })

    # Most severe first
    priority = {"risk_escalating": 0, "battery_declining": 1, "disk_filling": 2}
    alerts.sort(key=lambda a: min(priority.get(t, 9) for t in a["alert_types"]))
    return alerts


@router.get("/alerts", dependencies=[Depends(verify_agent_token)])
def get_at_risk_devices(
    threshold: int = Query(40),
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Devices with latest risk_score above threshold."""
    q = """
        SELECT DISTINCT ON (s.serial)
            s.serial, s.client_id, s.scan_date, s.risk_score, s.risk_level,
            d.hostname, d.model
        FROM diagnostic_snapshots s
        LEFT JOIN client_devices d ON d.serial = s.serial
        WHERE s.risk_score >= :threshold
    """
    params: dict = {"threshold": threshold}
    if client_id:
        q += " AND s.client_id = :client_id"
        params["client_id"] = client_id
    q += " ORDER BY s.serial, s.scan_date DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]
