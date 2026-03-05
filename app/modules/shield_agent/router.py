from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from app.core.agent_auth import verify_agent_token

router = APIRouter(prefix="/api/v1/shield", tags=["shield"])


class ShieldEvent(BaseModel):
    serial: str
    hostname: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    event_type: str  # PERSISTENCE, KEXT_LOAD, AUTH_FAIL, POLICY_CHANGE, TEMP_EXECUTABLE, DNS_CHANGE, UNSIGNED_DAEMON
    path: str
    detail: str
    timestamp: Optional[str] = None


@router.post("/events")
async def receive_shield_event(event: ShieldEvent, token: str = Depends(verify_agent_token)):
    # TODO: store in shield_events table (005_shield_events.sql)
    if event.severity == "CRITICAL":
        # TODO: webhook alert to Slack/Teams
        pass

    return {"status": "received", "severity": event.severity, "event_type": event.event_type}


@router.get("/events")
async def list_shield_events(
    serial: Optional[str] = None,
    severity: Optional[str] = None,
    last_hours: int = 24,
    token: str = Depends(verify_agent_token),
):
    # TODO: query shield_events table
    return {"events": [], "filter": {"serial": serial, "severity": severity, "last_hours": last_hours}}
