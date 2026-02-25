"""
Network telemetry submission and retrieval.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.auth import verify_api_key
from app.models.models import NetworkData
from app.models.schemas import NetworkSubmission

router = APIRouter()


@router.post("/submit")
async def submit_network(
    payload: NetworkSubmission,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Submit network controller telemetry."""
    record = NetworkData(
        controller_id=payload.controller_id,
        total_clients=payload.total_clients,
        total_devices=payload.total_devices,
        wan_status=payload.wan_status,
        wan_latency_ms=payload.wan_latency_ms,
        raw_data=payload.raw_data,
        timestamp=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "id": record.id}


@router.get("/history")
async def network_history(
    controller_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Get network telemetry history for a controller."""
    since = datetime.utcnow() - timedelta(hours=hours)
    records = (
        db.query(NetworkData)
        .filter(NetworkData.controller_id == controller_id, NetworkData.timestamp >= since)
        .order_by(desc(NetworkData.timestamp))
        .limit(500)
        .all()
    )
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "clients": r.total_clients,
            "devices": r.total_devices,
            "wan_status": r.wan_status,
            "wan_latency_ms": r.wan_latency_ms,
        }
        for r in records
    ]
