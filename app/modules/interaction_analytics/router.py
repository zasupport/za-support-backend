from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List, Union
from datetime import datetime, timezone, timedelta

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.interaction_analytics import service
from app.modules.interaction_analytics.schemas import InteractionReport

router = APIRouter(prefix="/api/v1/interaction-analytics", tags=["interaction-analytics"])


@router.post("/consent", dependencies=[Depends(verify_agent_token)])
def grant_consent(
    client_id: str,
    device_id: str,
    consent_text: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Grant POPIA consent for interaction analytics data collection."""
    return service.grant_consent(db, client_id, device_id, consent_text)


@router.delete("/consent/{client_id}", dependencies=[Depends(verify_agent_token)])
def revoke_consent(client_id: str, db: Session = Depends(get_db)):
    """Revoke POPIA consent and erase all interaction data for the client."""
    return service.revoke_consent(db, client_id)


@router.get("/consent/{client_id}", dependencies=[Depends(verify_agent_token)])
def get_consent_status(client_id: str, db: Session = Depends(get_db)):
    """Return POPIA consent status for a client."""
    return service.get_consent_status(db, client_id)


@router.post("/report", dependencies=[Depends(verify_agent_token)])
def post_report(payload: InteractionReport, db: Session = Depends(get_db)):
    try:
        return service.store_report(db, payload.device_id, payload.client_id, payload)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/devices/{device_id}/summary", dependencies=[Depends(verify_agent_token)])
def get_summary(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_summary(db, device_id, period_days)


@router.get("/devices/{device_id}/frustration-timeline", dependencies=[Depends(verify_agent_token)])
def get_frustration_timeline(
    device_id: str,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    if start and end:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    else:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=period_days)

    return service.get_frustration_timeline(db, device_id, start_dt, end_dt)


@router.get("/devices/{device_id}/app-breakdown", dependencies=[Depends(verify_agent_token)])
def get_app_breakdown(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_app_breakdown(db, device_id, period_days)


@router.get("/devices/{device_id}/typing-trend", dependencies=[Depends(verify_agent_token)])
def get_typing_trend(
    device_id: str,
    period_days: int = Query(14),
    db: Session = Depends(get_db),
):
    return service.get_typing_trend(db, device_id, period_days)


@router.get("/devices/{device_id}/anomalies", dependencies=[Depends(verify_agent_token)])
def get_anomalies(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_anomalies(db, device_id, period_days)


@router.get("/clients/{client_id}/fleet-summary", dependencies=[Depends(verify_agent_token)])
def get_fleet_summary(
    client_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_fleet_summary(db, client_id, period_days)


@router.get("/clients/{client_id}/frustration-hotspots", dependencies=[Depends(verify_agent_token)])
def get_frustration_hotspots(
    client_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_frustration_hotspots(db, client_id, period_days)


@router.post("/baselines/{device_id}/recalculate", dependencies=[Depends(verify_agent_token)])
def recalculate_baselines(
    device_id: str,
    db: Session = Depends(get_db),
):
    return service.recalculate_baselines(db, device_id)


@router.get("/report-data/{client_id}", dependencies=[Depends(verify_agent_token)])
def get_report_data(
    client_id: str,
    period: str = Query("month"),
    date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return service.get_report_data(db, client_id, period, date)


@router.delete("/devices/{device_id}/data", dependencies=[Depends(verify_agent_token)])
def delete_device_data(
    device_id: str,
    db: Session = Depends(get_db),
):
    return service.delete_device_data(db, device_id)
