"""
Diagnostic Storage Service
Handles device auto-registration, snapshot storage, and metric extraction.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


def upsert_device(db: Session, serial: str, client_id: str, payload: dict) -> int:
    """Create or update client_devices record. Returns device id."""
    hw = payload.get("hardware", payload.get("system", {}))
    storage = payload.get("storage", {})

    model = hw.get("model_name") or hw.get("model") or None
    chip = hw.get("chip") or hw.get("processor_name") or None
    cpu = hw.get("processor") or chip or None
    ram_raw = hw.get("memory") or hw.get("ram") or ""
    try:
        ram_gb = int(str(ram_raw).split()[0]) if ram_raw else None
    except (ValueError, IndexError):
        ram_gb = None

    storage_raw = storage.get("boot_disk_total_gb") or storage.get("total_gb") or None
    try:
        storage_gb = int(float(storage_raw)) if storage_raw else None
    except (ValueError, TypeError):
        storage_gb = None

    macos = (
        payload.get("os", {}).get("version")
        or payload.get("macos_version")
        or hw.get("macos_version")
        or None
    )
    hostname = payload.get("hostname") or payload.get("device_name") or None

    result = db.execute(
        text("""
        INSERT INTO client_devices
            (serial, client_id, hostname, model, chip_type, cpu, ram_gb, storage_gb, macos_version, first_seen, last_seen)
        VALUES
            (:serial, :client_id, :hostname, :model, :chip, :cpu, :ram_gb, :storage_gb, :macos, NOW(), NOW())
        ON CONFLICT (serial) DO UPDATE SET
            client_id     = EXCLUDED.client_id,
            hostname      = COALESCE(EXCLUDED.hostname, client_devices.hostname),
            model         = COALESCE(EXCLUDED.model, client_devices.model),
            chip_type     = COALESCE(EXCLUDED.chip_type, client_devices.chip_type),
            cpu           = COALESCE(EXCLUDED.cpu, client_devices.cpu),
            ram_gb        = COALESCE(EXCLUDED.ram_gb, client_devices.ram_gb),
            storage_gb    = COALESCE(EXCLUDED.storage_gb, client_devices.storage_gb),
            macos_version = COALESCE(EXCLUDED.macos_version, client_devices.macos_version),
            last_seen     = NOW(),
            is_active     = TRUE
        RETURNING id
        """),
        {
            "serial": serial, "client_id": client_id, "hostname": hostname,
            "model": model, "chip": chip, "cpu": cpu, "ram_gb": ram_gb,
            "storage_gb": storage_gb, "macos": macos,
        },
    )
    device_id = result.fetchone()[0]
    db.commit()
    logger.info(f"Device upserted: serial={serial} client={client_id} id={device_id}")
    return device_id


def compute_risk_score(payload: dict) -> tuple[int, str]:
    """
    Derive risk_score (0–100) and risk_level from V3's recommendations array.
    V3 generates recommendations as the authoritative intelligence source.
    V11 converts them to a numeric score for time-series tracking.

    Weights: CRITICAL=30, HIGH=15, MEDIUM=5 (capped at 100)
    """
    recs = payload.get("recommendations", [])
    if not recs:
        return 0, "LOW"

    weights = {"CRITICAL": 30, "HIGH": 15, "MEDIUM": 5}
    score = 0
    for rec in recs:
        severity = str(rec.get("severity", "")).upper()
        score += weights.get(severity, 0)

    score = min(score, 100)

    if score >= 60:
        level = "CRITICAL"
    elif score >= 30:
        level = "HIGH"
    elif score >= 10:
        level = "MEDIUM"
    else:
        level = "LOW"

    return score, level


def extract_metrics(payload: dict) -> dict:
    """Extract time-series fields from diagnostic JSON."""
    battery = payload.get("battery", {})
    storage = payload.get("storage", {})
    security = payload.get("security", {})
    threats = payload.get("threat_intel", {})
    malware = payload.get("malware_scan", {})
    disk_io = payload.get("disk_io_qos", payload.get("disk_io", {}))

    def _pct(v) -> Optional[float]:
        try:
            return float(str(v).replace("%", "").strip())
        except (TypeError, ValueError):
            return None

    def _int(v) -> Optional[int]:
        try:
            return int(float(str(v).strip()))
        except (TypeError, ValueError):
            return None

    def _bool_field(d: dict, *keys) -> Optional[bool]:
        for k in keys:
            v = d.get(k)
            if v is None:
                continue
            if isinstance(v, bool):
                return v
            s = str(v).lower()
            if s in ("true", "1", "on", "enabled", "yes"):
                return True
            if s in ("false", "0", "off", "disabled", "no"):
                return False
        return None

    swap_raw = disk_io.get("swap_used") or payload.get("swap_used") or None
    try:
        swap_mb = float(str(swap_raw).split()[0]) if swap_raw else None
    except (ValueError, TypeError):
        swap_mb = None

    return {
        "battery_health_pct":  _pct(battery.get("health_pct") or battery.get("health")),
        "battery_cycle_count": _int(battery.get("cycle_count") or battery.get("cycles")),
        "disk_used_pct":       _pct(storage.get("boot_disk_used_pct") or storage.get("used_pct")),
        "disk_free_gb":        _pct(storage.get("boot_disk_free_gb") or storage.get("free_gb")),
        "ram_pressure_pct":    _pct(payload.get("memory", {}).get("pressure_pct")),
        "swap_used_mb":        swap_mb,
        "process_count":       _int(payload.get("total_processes") or payload.get("process_count")),
        "filevault_on":        _bool_field(security, "filevault_on", "filevault"),
        "firewall_on":         _bool_field(security, "firewall_on", "firewall_enabled", "firewall"),
        "sip_enabled":         _bool_field(security, "sip_enabled", "sip"),
        "risk_score":          compute_risk_score(payload)[0],
        "threat_count":        _int(threats.get("total_threats") or threats.get("count")),
        "malware_findings":    _int(malware.get("findings") or malware.get("count")),
    }


def store_snapshot(
    db: Session,
    device_id: int,
    serial: str,
    client_id: str,
    raw_json: dict,
    raw_txt: Optional[str] = None,
) -> int:
    """Insert diagnostic snapshot and extract metrics row. Returns snapshot id."""
    meta = raw_json.get("meta", raw_json.get("metadata", {}))

    # Derive risk_score from V3's recommendations (authoritative intelligence source)
    risk_score, risk_level = compute_risk_score(raw_json)

    result = db.execute(
        text("""
        INSERT INTO diagnostic_snapshots
            (device_id, serial, client_id, scan_date, version, mode, reason,
             runtime_seconds, risk_score, risk_level, recommendation_count, raw_json, raw_txt)
        VALUES
            (:device_id, :serial, :client_id, NOW(), :version, :mode, :reason,
             :runtime, :risk_score, :risk_level, :rec_count, :raw_json, :raw_txt)
        RETURNING id
        """),
        {
            "device_id":  device_id,
            "serial":     serial,
            "client_id":  client_id,
            "version":    meta.get("version") or raw_json.get("version"),
            "mode":       meta.get("mode") or raw_json.get("mode"),
            "reason":     meta.get("reason") or raw_json.get("reason"),
            "runtime":    meta.get("runtime_seconds") or raw_json.get("runtime_seconds"),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "rec_count":  raw_json.get("recommendation_count"),
            "raw_json":   __import__("json").dumps(raw_json),
            "raw_txt":    raw_txt,
        },
    )
    snapshot_id = result.fetchone()[0]

    # Write time-series row
    metrics = extract_metrics(raw_json)
    metrics["serial"] = serial
    db.execute(
        text("""
        INSERT INTO device_metrics
            (time, serial, battery_health_pct, battery_cycle_count, disk_used_pct,
             disk_free_gb, ram_pressure_pct, swap_used_mb, process_count,
             filevault_on, firewall_on, sip_enabled, risk_score, threat_count, malware_findings)
        VALUES
            (NOW(), :serial, :battery_health_pct, :battery_cycle_count, :disk_used_pct,
             :disk_free_gb, :ram_pressure_pct, :swap_used_mb, :process_count,
             :filevault_on, :firewall_on, :sip_enabled, :risk_score, :threat_count, :malware_findings)
        """),
        metrics,
    )
    db.commit()
    logger.info(f"Snapshot stored: id={snapshot_id} serial={serial}")
    return snapshot_id
