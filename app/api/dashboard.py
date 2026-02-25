"""
Dashboard aggregation — provides a single-call overview for client dashboards.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta
from typing import Optional

from app.core.database import get_db
from app.core.auth import verify_api_key
from app.models.models import Device, HealthData, Alert
from app.models.schemas import DashboardOverview, DeviceHealthSummary
from app.core.config import settings

router = APIRouter()


@router.get("/overview", response_model=DashboardOverview)
async def dashboard_overview(
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Single-call dashboard overview: device statuses, alert counts, health summaries."""
    q = db.query(Device).filter(Device.is_active == True)
    if client_id:
        q = q.filter(Device.client_id == client_id)
    devices = q.all()

    stale_threshold = datetime.utcnow() - timedelta(minutes=15)

    device_summaries = []
    for d in devices:
        latest = (
            db.query(HealthData)
            .filter(HealthData.machine_id == d.machine_id)
            .order_by(desc(HealthData.timestamp))
            .first()
        )
        open_alerts = (
            db.query(func.count(Alert.id))
            .filter(Alert.machine_id == d.machine_id, Alert.resolved == False)
            .scalar()
        )

        status = "offline"
        if d.last_seen and d.last_seen >= stale_threshold:
            status = "healthy"
            if latest:
                if latest.cpu_percent and latest.cpu_percent >= settings.CPU_CRITICAL:
                    status = "critical"
                elif latest.disk_percent and latest.disk_percent >= settings.DISK_CRITICAL:
                    status = "critical"
                elif latest.threat_score and latest.threat_score >= settings.THREAT_CRITICAL:
                    status = "critical"
                elif (latest.cpu_percent and latest.cpu_percent >= settings.CPU_WARNING) or \
                     (latest.disk_percent and latest.disk_percent >= settings.DISK_WARNING):
                    status = "warning"

        device_summaries.append(DeviceHealthSummary(
            machine_id=d.machine_id,
            hostname=d.hostname,
            model=d.model_identifier,
            serial=d.serial_number,
            status=status,
            cpu=latest.cpu_percent if latest else None,
            memory=latest.memory_percent if latest else None,
            disk=latest.disk_percent if latest else None,
            battery=latest.battery_percent if latest else None,
            threat=latest.threat_score if latest else 0,
            last_seen=d.last_seen,
            open_alerts=open_alerts or 0,
        ))

    critical_count = (
        db.query(func.count(Alert.id))
        .filter(Alert.resolved == False, Alert.severity == "critical")
        .scalar() or 0
    )
    warning_count = (
        db.query(func.count(Alert.id))
        .filter(Alert.resolved == False, Alert.severity == "warning")
        .scalar() or 0
    )

    return DashboardOverview(
        total_devices=len(devices),
        active_devices=sum(1 for d in device_summaries if d.status != "offline"),
        critical_alerts=critical_count,
        warning_alerts=warning_count,
        devices=device_summaries,
    )
