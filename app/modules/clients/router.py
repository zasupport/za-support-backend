import hashlib
import hmac
import json
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.agent_auth import verify_agent_token
from app.core.config import settings
from app.core.database import get_db
from app.core.event_bus import emit_event
from app.modules.clients import service
from app.modules.clients.schemas import (
    ClientIntakePayload,
    ClientCheckinPayload,
    TaskStatusUpdate,
    ClientOut,
    ClientDetailOut,
    ClientTaskOut,
    CheckinOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/clients", tags=["Clients"])


def _verify_formbricks_signature(request: Request, body: bytes) -> bool:
    """Verify Formbricks webhook HMAC-SHA256 signature."""
    secret = getattr(settings, "FORMBRICKS_WEBHOOK_SECRET", None)
    if not secret:
        # No secret configured — allow through (set secret in production)
        logger.warning("FORMBRICKS_WEBHOOK_SECRET not set — skipping signature verification")
        return True
    sig = request.headers.get("x-formbricks-signature-256", "")
    expected = "sha256=" + hmac.new(key=secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# ── Public Webhook Endpoints (Formbricks) ─────────────────────────────────────

@router.post("/intake/webhook", status_code=200)
async def formbricks_intake_webhook(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Formbricks webhook for Form 1 (New Client Intake).
    Set this URL in Formbricks: POST https://api.zasupport.com/api/v1/clients/intake/webhook
    """
    body = await request.body()
    if not _verify_formbricks_signature(request, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    raw = json.loads(body)

    # Only process on final submission
    event = raw.get("event", "")
    if event not in ("responseCreated", "responseFinished", "responseUpdated"):
        return {"status": "ignored", "event": event}

    payload = service.map_formbricks_intake(raw)
    if not payload:
        raise HTTPException(status_code=422, detail="Could not map Formbricks payload — check field IDs in service.py")

    client = service.create_client(db, payload)
    background.add_task(emit_event, "client.created", {
        "client_id": client.client_id,
        "email": client.email,
        "has_business": client.has_business,
        "urgency_level": client.urgency_level,
    })
    return {"status": "ok", "client_id": client.client_id}


@router.post("/checkin/webhook", status_code=200)
async def formbricks_checkin_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Formbricks webhook for Form 2 (Pre-Visit Check-In).
    Set this URL in Formbricks: POST https://api.zasupport.com/api/v1/clients/checkin/webhook
    """
    body = await request.body()
    if not _verify_formbricks_signature(request, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    raw = json.loads(body)

    event = raw.get("event", "")
    if event not in ("responseCreated", "responseFinished", "responseUpdated"):
        return {"status": "ignored", "event": event}

    payload = service.map_formbricks_checkin(raw)
    if not payload:
        raise HTTPException(status_code=422, detail="Could not map Formbricks check-in payload")

    checkin = service.create_checkin(db, payload)
    return {"status": "ok", "checkin_id": checkin.id}


# ── Direct API Endpoints (internal / testing / dashboard) ────────────────────

@router.post("/intake", response_model=ClientOut, dependencies=[Depends(verify_agent_token)])
def intake(payload: ClientIntakePayload, background: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Direct intake submission (bypasses Formbricks — use for testing or internal onboarding).
    Authenticated with agent token.
    """
    client = service.create_client(db, payload)
    background.add_task(emit_event, "client.created", {
        "client_id": client.client_id,
        "email": client.email,
        "has_business": client.has_business,
        "urgency_level": client.urgency_level,
    })
    return client


@router.post("/checkin", response_model=CheckinOut, dependencies=[Depends(verify_agent_token)])
def checkin(payload: ClientCheckinPayload, db: Session = Depends(get_db)):
    """Direct check-in submission (authenticated)."""
    if not service.get_client(db, payload.client_id):
        raise HTTPException(status_code=404, detail=f"Client not found: {payload.client_id}")
    return service.create_checkin(db, payload)


# ── Client CRUD ───────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(verify_agent_token)])
def list_clients(
    status:   Optional[str] = Query(None, description="Filter by status: new, active, sla, inactive"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db:       Session = Depends(get_db),
):
    result = service.list_clients(db, status=status, page=page, per_page=per_page)
    return {
        "data": [ClientOut.model_validate(c) for c in result["data"]],
        "meta": result["meta"],
    }


@router.get("/{client_id}", response_model=ClientDetailOut, dependencies=[Depends(verify_agent_token)])
def get_client(client_id: str, db: Session = Depends(get_db)):
    client = service.get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    return client


# ── Onboarding Tasks ──────────────────────────────────────────────────────────

@router.get("/{client_id}/tasks", response_model=List[ClientTaskOut], dependencies=[Depends(verify_agent_token)])
def get_tasks(client_id: str, db: Session = Depends(get_db)):
    if not service.get_client(db, client_id):
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    return service.get_tasks(db, client_id)


@router.patch("/{client_id}/tasks/{task_id}", response_model=ClientTaskOut, dependencies=[Depends(verify_agent_token)])
def update_task(client_id: str, task_id: int, update: TaskStatusUpdate, db: Session = Depends(get_db)):
    task = service.update_task(db, task_id, update)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


# ── Check-In History ──────────────────────────────────────────────────────────

@router.get("/{client_id}/checkins", response_model=List[CheckinOut], dependencies=[Depends(verify_agent_token)])
def get_checkins(client_id: str, db: Session = Depends(get_db)):
    if not service.get_client(db, client_id):
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    return service.get_checkins(db, client_id)


# ── Morning Operations View ───────────────────────────────────────────────────

@router.get("/morning/overview", dependencies=[Depends(verify_agent_token)])
def morning_overview(db: Session = Depends(get_db)):
    """
    Daily operations view: all active/new clients with their current health snapshot.
    Returns per-client: name, status, last scan date, risk level, days since scan,
    open task count, open workshop job count.
    """
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.status,
            c.urgency_level,
            c.has_business,
            -- latest diagnostic snapshot across all client devices
            (SELECT s.scan_date
             FROM diagnostic_snapshots s
             JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id
             ORDER BY s.scan_date DESC LIMIT 1) AS last_scan_date,
            (SELECT s.risk_level
             FROM diagnostic_snapshots s
             JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id
             ORDER BY s.scan_date DESC LIMIT 1) AS risk_level,
            (SELECT s.risk_score
             FROM diagnostic_snapshots s
             JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id
             ORDER BY s.scan_date DESC LIMIT 1) AS risk_score,
            (SELECT EXTRACT(DAY FROM NOW() - s.scan_date)::int
             FROM diagnostic_snapshots s
             JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id
             ORDER BY s.scan_date DESC LIMIT 1) AS days_since_scan,
            (SELECT COUNT(*) FROM client_onboarding_tasks t
             WHERE t.client_id = c.client_id AND t.status != 'completed') AS open_tasks,
            (SELECT COUNT(*) FROM workshop_jobs j
             WHERE j.client_id = c.client_id AND j.status NOT IN ('done', 'cancelled')) AS open_jobs,
            (SELECT COUNT(*) FROM client_devices d WHERE d.client_id = c.client_id AND d.is_active = TRUE) AS device_count
        FROM clients c
        WHERE c.status IN ('new', 'active', 'sla')
        ORDER BY
            CASE c.urgency_level WHEN 'Urgent' THEN 0 ELSE 1 END,
            c.status,
            c.first_name
    """)).fetchall()

    return [dict(r._mapping) for r in rows]


# ── Site Visit Brief ──────────────────────────────────────────────────────────

@router.get("/{client_id}/brief", dependencies=[Depends(verify_agent_token)])
def get_site_visit_brief(client_id: str, db: Session = Depends(get_db)):
    """
    Pre-visit context brief: client info, devices + latest snapshot,
    open tasks, latest check-in, open workshop jobs.
    """
    brief = service.get_site_visit_brief(db, client_id)
    if not brief:
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")

    client = brief["client"]

    def _snap(s):
        if not s:
            return None
        return {k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in s.items()}

    def _dev(d):
        out = {k: (str(v) if hasattr(v, 'isoformat') else v) for k, v in d.items() if k != "latest_snapshot"}
        out["latest_snapshot"] = _snap(d.get("latest_snapshot"))
        return out

    return {
        "client": ClientDetailOut.model_validate(client),
        "devices": [_dev(d) for d in brief["devices"]],
        "open_tasks": [ClientTaskOut.model_validate(t) for t in brief["open_tasks"]],
        "completed_task_count": brief["completed_task_count"],
        "latest_checkin": CheckinOut.model_validate(brief["latest_checkin"]) if brief["latest_checkin"] else None,
        "open_workshop_jobs": brief["open_workshop_jobs"],
    }
