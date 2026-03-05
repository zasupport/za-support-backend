from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db

router = APIRouter(prefix="/api/v1/shield", tags=["shield"])


class ShieldEvent(BaseModel):
    serial: str
    hostname: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    event_type: str  # PERSISTENCE, KEXT_LOAD, AUTH_FAIL, POLICY_CHANGE, TEMP_EXECUTABLE, DNS_CHANGE, UNSIGNED_DAEMON
    path: str
    detail: str
    timestamp: Optional[str] = None


@router.post("/events", dependencies=[Depends(verify_agent_token)])
def receive_shield_event(event: ShieldEvent, db: Session = Depends(get_db)):
    ts = None
    if event.timestamp:
        try:
            ts = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        except ValueError:
            ts = None

    db.execute(
        """
        INSERT INTO shield_events
            (serial, hostname, severity, event_type, path, detail, timestamp)
        VALUES
            (:serial, :hostname, :severity, :event_type, :path, :detail,
             COALESCE(:timestamp, NOW()))
        """,
        {
            "serial": event.serial,
            "hostname": event.hostname,
            "severity": event.severity,
            "event_type": event.event_type,
            "path": event.path,
            "detail": event.detail,
            "timestamp": ts,
        },
    )
    db.commit()

    return {"status": "received", "severity": event.severity, "event_type": event.event_type}


@router.get("/events", dependencies=[Depends(verify_agent_token)])
def list_shield_events(
    serial: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    last_hours: int = Query(24),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=last_hours)

    query = "SELECT * FROM shield_events WHERE timestamp >= :cutoff"
    params = {"cutoff": cutoff}

    if serial:
        query += " AND serial = :serial"
        params["serial"] = serial

    if severity:
        query += " AND severity = :severity"
        params["severity"] = severity

    query += " ORDER BY timestamp DESC LIMIT 500"

    result = db.execute(query, params)
    rows = result.fetchall()

    events = []
    for row in rows:
        events.append(dict(row._mapping))

    return {
        "events": events,
        "count": len(events),
        "filter": {"serial": serial, "severity": severity, "last_hours": last_hours},
    }
