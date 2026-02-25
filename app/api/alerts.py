"""
Alert management — list, resolve, bulk operations.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime
from typing import Optional, List

from app.core.database import get_db
from app.core.auth import verify_api_key
from app.models.models import Alert
from app.models.schemas import AlertResponse

router = APIRouter()


@router.get("/", response_model=List[AlertResponse])
async def list_alerts(
    machine_id: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    unresolved_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """List alerts with optional filters."""
    q = db.query(Alert)
    if machine_id:
        q = q.filter(Alert.machine_id == machine_id)
    if severity:
        q = q.filter(Alert.severity == severity)
    if unresolved_only:
        q = q.filter(Alert.resolved == False)
    return q.order_by(desc(Alert.timestamp)).limit(limit).all()


@router.post("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Mark an alert as resolved."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert.resolved = True
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return {"status": "resolved", "id": alert_id}


@router.post("/resolve-all")
async def resolve_all(
    machine_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Resolve all open alerts for a device."""
    count = (
        db.query(Alert)
        .filter(Alert.machine_id == machine_id, Alert.resolved == False)
        .update({"resolved": True, "resolved_at": datetime.utcnow()})
    )
    db.commit()
    return {"status": "resolved", "count": count}
