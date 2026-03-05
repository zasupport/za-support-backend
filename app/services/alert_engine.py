"""
Alert engine — evaluates health data against thresholds, generates alerts.
"""
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List
import logging

from app.models.models import Alert, AlertSeverity
from app.core.config import settings

logger = logging.getLogger(__name__)


def evaluate_health_data(machine_id: str, data: dict, db: Session) -> List[Alert]:
    """Evaluate health submission against configured thresholds."""
    alerts = []

    # --- CPU ---
    cpu = data.get("cpu_percent", 0)
    if cpu >= settings.CPU_CRITICAL:
        alerts.append(_make_alert(machine_id, AlertSeverity.CRITICAL, "cpu",
                                   f"CPU at {cpu}% — sustained high usage."))
    elif cpu >= settings.CPU_WARNING:
        alerts.append(_make_alert(machine_id, AlertSeverity.WARNING, "cpu",
                                   f"CPU at {cpu}% — elevated usage."))

    # --- Memory ---
    mem = data.get("memory_percent", 0)
    if mem >= settings.MEMORY_CRITICAL:
        alerts.append(_make_alert(machine_id, AlertSeverity.CRITICAL, "memory",
                                   f"Memory at {mem}% — critical pressure."))
    elif mem >= settings.MEMORY_WARNING:
        alerts.append(_make_alert(machine_id, AlertSeverity.WARNING, "memory",
                                   f"Memory at {mem}% — elevated usage."))

    # --- Disk ---
    disk = data.get("disk_percent", 0)
    if disk >= settings.DISK_CRITICAL:
        alerts.append(_make_alert(machine_id, AlertSeverity.CRITICAL, "disk",
                                   f"Disk at {disk}% — critically full."))
    elif disk >= settings.DISK_WARNING:
        alerts.append(_make_alert(machine_id, AlertSeverity.WARNING, "disk",
                                   f"Disk at {disk}% — running low."))

    # --- Battery ---
    bat = data.get("battery_percent")
    if bat is not None and bat <= settings.BATTERY_CRITICAL:
        alerts.append(_make_alert(machine_id, AlertSeverity.CRITICAL, "battery",
                                   f"Battery at {bat}% — critically low."))

    # --- Threat Score ---
    threat = data.get("threat_score", 0)
    if threat >= settings.THREAT_CRITICAL:
        alerts.append(_make_alert(machine_id, AlertSeverity.CRITICAL, "security",
                                   f"Threat score {threat}/10 — security review required."))

    # Persist alerts
    for alert in alerts:
        db.add(alert)

    if alerts:
        db.flush()
        logger.info(f"[{machine_id}] Generated {len(alerts)} alert(s).")

    return alerts


def _make_alert(machine_id: str, severity: AlertSeverity, category: str, message: str) -> Alert:
    return Alert(
        machine_id=machine_id,
        severity=severity.value,
        category=category,
        message=message,
        timestamp=datetime.utcnow(),
    )
