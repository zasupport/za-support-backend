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
    NoteIn,
    NoteOut,
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


# ── ISP Map ───────────────────────────────────────────────────────────────────

@router.get("/isp-map", dependencies=[Depends(verify_agent_token)])
def client_isp_map(db: Session = Depends(get_db)):
    """Per-client ISP name for impact mapping on the ISP status page."""
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT c.client_id, c.first_name, c.last_name, cs.isp
        FROM clients c
        LEFT JOIN client_setup cs ON cs.client_id = c.client_id
        WHERE c.status IN ('new', 'active', 'sla')
        ORDER BY c.first_name
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Direct Client Create (dashboard quick-add, bypasses Formbricks) ───────────

@router.post("", response_model=ClientDetailOut, dependencies=[Depends(verify_agent_token)])
def create_client_direct(payload: ClientIntakePayload, background: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Create a client directly from the dashboard (no Formbricks webhook required).
    Emits client.created event for welcome email + Slack notification.
    """
    from app.core.event_bus import emit_event
    client = service.create_client(db, payload)
    background.add_task(emit_event, "client.created", {
        "client_id": client.client_id,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "status": client.status,
    })
    return client


# ── Client CRUD ───────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(verify_agent_token)])
def list_clients(
    status:   Optional[str] = Query(None),
    search:   Optional[str] = Query(None, description="Search by name, email, or client_id"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db:       Session = Depends(get_db),
):
    result = service.list_clients(db, status=status, search=search, page=page, per_page=per_page)
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


# ── Client Health Score ───────────────────────────────────────────────────────

@router.get("/{client_id}/health", dependencies=[Depends(verify_agent_token)])
def client_health(client_id: str, db: Session = Depends(get_db)):
    """
    Compute a 0-100 health score for a client based on:
    - Latest diagnostic risk score (40 pts)
    - Backup status (20 pts)
    - Onboarding completion (20 pts)
    - Days since last scan (20 pts)
    """
    from sqlalchemy import text
    client = service.get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")

    snap = db.execute(text("""
        SELECT s.risk_score, s.risk_level, s.scan_date, s.raw_json
        FROM diagnostic_snapshots s
        JOIN client_devices d ON d.serial = s.serial
        WHERE d.client_id = :cid
        ORDER BY s.scan_date DESC LIMIT 1
    """), {"cid": client_id}).fetchone()

    tasks = service.get_tasks(db, client_id)
    total_tasks     = len(tasks)
    completed_tasks = sum(1 for t in tasks if t.status == "completed")

    # Score components
    risk_pts    = 0
    backup_pts  = 0
    task_pts    = 0
    scan_pts    = 0
    days_since  = None
    risk_level  = None

    if snap:
        risk_score = snap.risk_score or 0
        risk_level = snap.risk_level
        # risk_score 0-10, invert: score 10 = 0 pts, score 0 = 40 pts
        risk_pts = max(0, int(40 - (risk_score * 4)))

        # Days since scan
        if snap.scan_date:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            scan_dt = snap.scan_date
            if scan_dt.tzinfo is None:
                scan_dt = scan_dt.replace(tzinfo=timezone.utc)
            days_since = (now - scan_dt).days
            scan_pts = 20 if days_since <= 30 else (10 if days_since <= 60 else 0)

        # Backup check from environment data (flat fields from environment_mod.sh)
        import json
        raw = json.loads(snap.raw_json) if isinstance(snap.raw_json, str) else (snap.raw_json or {})
        env = raw.get("environment", {})
        tm_status = (env.get("time_machine_status") or "").upper()
        tm_days_raw = env.get("time_machine_days_ago")
        try:
            tm_days = int(tm_days_raw) if tm_days_raw not in (None, "UNKNOWN", "") else None
        except (ValueError, TypeError):
            tm_days = None
        tm_ok = tm_status not in ("DISABLED", "UNKNOWN", "")
        tm_recent = tm_ok and (tm_days is None or tm_days <= 7)
        ccc_installed = (env.get("ccc_installed") or "NO").upper() == "YES"
        ccc_ok = ccc_installed
        backup_pts = 20 if (tm_recent or ccc_ok) else (10 if tm_ok else 0)
    else:
        risk_pts = 0  # No data — unknown risk, score 0

    if total_tasks > 0:
        task_pts = int(20 * (completed_tasks / total_tasks))
    else:
        task_pts = 20  # No tasks = nothing pending

    total = risk_pts + backup_pts + task_pts + scan_pts
    grade = "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 50 else "D" if total >= 30 else "F"

    return {
        "client_id":       client_id,
        "health_score":    total,
        "grade":           grade,
        "risk_level":      risk_level,
        "days_since_scan": days_since,
        "components": {
            "risk":     risk_pts,
            "backup":   backup_pts,
            "tasks":    task_pts,
            "freshness": scan_pts,
        },
        "tasks_completed": completed_tasks,
        "tasks_total":     total_tasks,
    }


# ── Client Status Update ──────────────────────────────────────────────────────

@router.patch("/{client_id}/status", dependencies=[Depends(verify_agent_token)])
def update_client_status(
    client_id: str, body: dict, background: BackgroundTasks, db: Session = Depends(get_db)
):
    """Update client status: new | active | sla | inactive."""
    allowed = {"new", "active", "sla", "inactive"}
    new_status = (body.get("status") or "").lower().strip()
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(allowed)}")
    client = service.get_client(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    old_status = client.status
    client.status = new_status
    db.commit()
    db.refresh(client)
    logger.info(f"Client {client_id} status updated: {old_status} → {new_status}")
    if old_status != new_status:
        background.add_task(emit_event, "client.status_changed", {
            "client_id": client_id,
            "email": client.email,
            "first_name": client.first_name,
            "old_status": old_status,
            "new_status": new_status,
        })
    return {"client_id": client_id, "status": new_status}


# ── Client Notes ──────────────────────────────────────────────────────────────

@router.post("/{client_id}/notes", response_model=NoteOut, dependencies=[Depends(verify_agent_token)])
def add_note(client_id: str, payload: NoteIn, db: Session = Depends(get_db)):
    """Add a sticky note to a client profile."""
    if not service.get_client(db, client_id):
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    return service.add_note(db, client_id, payload)


@router.get("/{client_id}/notes", response_model=List[NoteOut], dependencies=[Depends(verify_agent_token)])
def get_notes(client_id: str, db: Session = Depends(get_db)):
    """Get all notes for a client (newest first)."""
    if not service.get_client(db, client_id):
        raise HTTPException(status_code=404, detail=f"Client not found: {client_id}")
    return service.get_notes(db, client_id)


@router.delete("/{client_id}/notes/{note_id}", dependencies=[Depends(verify_agent_token)])
def delete_note(client_id: str, note_id: int, db: Session = Depends(get_db)):
    """Delete a note."""
    deleted = service.delete_note(db, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Note not found: {note_id}")
    return {"deleted": note_id}


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
