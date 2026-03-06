"""
System API — event bus, scheduled jobs, and automation status.
GET /api/v1/system/events  — system event log
GET /api/v1/system/jobs    — scheduled job registry
GET /api/v1/system/status  — automation layer health
"""
import os
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from app.core.database import get_db
from app.core.agent_auth import verify_agent_token
from app.models.models import SystemEvent, ScheduledJob, NotificationLog

router = APIRouter()


@router.get("/agent-token", dependencies=[Depends(verify_agent_token)])
def get_agent_token():
    """Return the primary agent auth token — used by the dashboard installer page."""
    token = os.environ.get("AGENT_AUTH_TOKEN", "")
    return {"token": token if token else None}


@router.get("/events")
def list_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    severity: Optional[str] = None,
    since_hours: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """List system events with optional filtering."""
    q = db.query(SystemEvent)
    if event_type:
        q = q.filter(SystemEvent.event_type == event_type)
    if source:
        q = q.filter(SystemEvent.source == source)
    if severity:
        q = q.filter(SystemEvent.severity == severity)
    if since_hours:
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        q = q.filter(SystemEvent.created_at >= since)

    total = q.count()
    events = q.order_by(SystemEvent.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "source": e.source,
                "severity": e.severity,
                "summary": e.summary,
                "detail": e.detail,
                "device_serial": e.device_serial,
                "client_id": e.client_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db)):
    """List all scheduled automation jobs."""
    jobs = db.query(ScheduledJob).order_by(ScheduledJob.id).all()
    return {
        "total": len(jobs),
        "jobs": [
            {
                "id": j.id,
                "job_id": j.job_id,
                "name": j.name,
                "schedule": j.schedule,
                "enabled": j.enabled,
                "last_run": j.last_run.isoformat() if j.last_run else None,
                "next_run": j.next_run.isoformat() if j.next_run else None,
                "last_status": j.last_status,
                "last_error": j.last_error,
                "run_count": j.run_count,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
    }


@router.get("/activity")
def activity_feed(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    """
    Combined real-time activity feed: recent clients, diagnostics, workshop jobs.
    Powers the dashboard home activity panel.
    """
    from sqlalchemy import text

    # Recent clients
    clients = db.execute(
        text("SELECT client_id, first_name, last_name, status, created_at FROM clients ORDER BY created_at DESC LIMIT :n"),
        {"n": limit // 3 or 5},
    ).fetchall()

    # Recent diagnostic snapshots
    snaps = db.execute(
        text("""
            SELECT s.id, s.serial, s.client_id, s.scan_date, s.risk_level, s.risk_score,
                   d.hostname
            FROM diagnostic_snapshots s
            LEFT JOIN client_devices d ON d.serial = s.serial
            ORDER BY s.scan_date DESC LIMIT :n
        """),
        {"n": limit // 3 or 5},
    ).fetchall()

    # Recent workshop jobs
    jobs = db.execute(
        text("""
            SELECT j.job_ref, j.title, j.client_id, j.status, j.priority, j.source,
                   j.created_at, c.first_name, c.last_name
            FROM workshop_jobs j
            LEFT JOIN clients c ON c.client_id = j.client_id
            ORDER BY j.created_at DESC LIMIT :n
        """),
        {"n": limit // 3 or 5},
    ).fetchall()

    events = []

    for r in clients:
        events.append({
            "type": "client_created",
            "icon": "user",
            "label": f"New client: {r.first_name} {r.last_name}",
            "sub": r.status,
            "href": f"/clients/{r.client_id}",
            "ts": r.created_at.isoformat() if r.created_at else None,
        })

    for r in snaps:
        level = r.risk_level or "—"
        events.append({
            "type": "diagnostic",
            "icon": "scan",
            "label": f"Diagnostic: {r.hostname or r.serial}",
            "sub": f"Risk: {level} ({r.risk_score or '—'})",
            "severity": level.lower(),
            "href": f"/devices/{r.serial}",
            "ts": r.scan_date.isoformat() if r.scan_date else None,
        })

    for r in jobs:
        events.append({
            "type": "workshop_job",
            "icon": "wrench",
            "label": f"Job: {r.title[:60]}",
            "sub": f"{r.first_name or ''} {r.last_name or ''} · {r.status} · {r.priority}",
            "href": f"/workshop",
            "ts": r.created_at.isoformat() if r.created_at else None,
        })

    # Sort combined feed by timestamp desc
    events.sort(key=lambda e: e.get("ts") or "", reverse=True)

    return {"events": events[:limit]}


@router.get("/status")
def automation_status(db: Session = Depends(get_db)):
    """Overall automation layer health."""
    total_events = db.query(func.count(SystemEvent.id)).scalar() or 0
    total_jobs = db.query(func.count(ScheduledJob.id)).scalar() or 0
    failed_jobs = db.query(func.count(ScheduledJob.id)).filter(
        ScheduledJob.last_status == "failed"
    ).scalar() or 0
    notifications_sent = db.query(func.count(NotificationLog.id)).scalar() or 0

    # Events in last 24h by severity
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    severity_counts = db.query(
        SystemEvent.severity, func.count(SystemEvent.id)
    ).filter(
        SystemEvent.created_at >= since_24h
    ).group_by(SystemEvent.severity).all()

    return {
        "status": "operational",
        "version": "11.2.0",
        "automation_layer": True,
        "total_events": total_events,
        "total_jobs": total_jobs,
        "failed_jobs": failed_jobs,
        "notifications_sent": notifications_sent,
        "events_24h": {row[0]: row[1] for row in severity_counts},
    }
