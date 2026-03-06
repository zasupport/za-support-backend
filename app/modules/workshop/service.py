"""
Workshop service layer — all business logic.
Creates job cards manually or auto-generates them from high-risk diagnostic findings.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import Session

from app.modules.workshop.models import WorkshopJob, WorkshopLineItem, WorkshopJobHistory
from app.modules.workshop.schemas import JobCreate, JobStatusUpdate, JobUpdate, LineItemIn

logger = logging.getLogger(__name__)

# Severity thresholds that trigger auto job card creation
_AUTO_CREATE_SEVERITIES = {"CRITICAL", "HIGH"}

# Priority mapping from recommendation severity
_SEVERITY_TO_PRIORITY = {
    "CRITICAL": "urgent",
    "HIGH":     "high",
    "MODERATE": "normal",
    "LOW":      "low",
}


def _next_job_ref(db: Session) -> str:
    """Generate sequential job ref: WS-YYYY-NNNN."""
    year = datetime.now().year
    count = db.query(WorkshopJob).filter(
        WorkshopJob.job_ref.like(f"WS-{year}-%")
    ).count()
    return f"WS-{year}-{count + 1:04d}"


def create_job(db: Session, data: JobCreate, source: str = "manual", snapshot_id: Optional[int] = None) -> WorkshopJob:
    job_ref = _next_job_ref(db)
    job = WorkshopJob(
        job_ref=job_ref,
        client_id=data.client_id,
        serial=data.serial,
        title=data.title,
        description=data.description,
        priority=data.priority,
        source=source,
        snapshot_id=snapshot_id,
        scheduled_date=data.scheduled_date,
        notes=data.notes,
    )
    db.add(job)
    db.flush()  # get job.id

    for item in data.line_items:
        line = WorkshopLineItem(
            job_id=job.id,
            description=item.description,
            qty=item.qty,
            unit_price=item.unit_price,
            line_total=(item.unit_price * item.qty) if item.unit_price else None,
            item_type=item.item_type,
        )
        db.add(line)

    db.add(WorkshopJobHistory(
        job_id=job.id,
        from_status=None,
        to_status="open",
        note=f"Job created via {source}",
        changed_by="system" if source == "auto_diagnostic" else "courtney",
    ))

    db.commit()
    db.refresh(job)
    logger.info(f"Workshop job created: {job_ref} for client {data.client_id}")
    return job


def auto_create_from_diagnostic(
    db: Session,
    client_id: str,
    serial: str,
    snapshot_id: Optional[int],
    recommendations: list,
) -> Optional[WorkshopJob]:
    """
    Called by the diagnostics event subscriber.
    If there are CRITICAL or HIGH severity recommendations, create a job card.
    Deduplicates — will not create a second job for the same snapshot.
    """
    if snapshot_id:
        existing = db.query(WorkshopJob).filter(
            WorkshopJob.snapshot_id == snapshot_id
        ).first()
        if existing:
            logger.info(f"Workshop: job already exists for snapshot {snapshot_id} — skipping")
            return None

    critical_recs = [r for r in recommendations if r.get("severity", "") in _AUTO_CREATE_SEVERITIES]
    if not critical_recs:
        return None

    highest = "CRITICAL" if any(r["severity"] == "CRITICAL" for r in critical_recs) else "HIGH"
    priority = _SEVERITY_TO_PRIORITY[highest]

    title = f"Site visit required — {len(critical_recs)} {highest.lower()} finding{'s' if len(critical_recs) > 1 else ''} ({serial})"
    desc_lines = [f"Auto-generated from Health Check Scout diagnostic.\nSerial: {serial}\n\nFindings requiring attention:"]
    for r in critical_recs:
        desc_lines.append(f"  [{r['severity']}] {r.get('title', '')} — {r.get('evidence', '')}")

    data = JobCreate(
        client_id=client_id,
        serial=serial,
        title=title,
        description="\n".join(desc_lines),
        priority=priority,
        line_items=[
            LineItemIn(
                description=r.get("title", "Finding"),
                qty=1,
                item_type="service",
                unit_price=None,
            )
            for r in critical_recs
        ],
    )

    return create_job(db, data, source="auto_diagnostic", snapshot_id=snapshot_id)


def list_jobs(
    db: Session,
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    q = db.query(WorkshopJob)
    if client_id:
        q = q.filter(WorkshopJob.client_id == client_id)
    if status:
        q = q.filter(WorkshopJob.status == status)
    total = q.count()
    jobs = q.order_by(WorkshopJob.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": jobs, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_job(db: Session, job_ref: str) -> Optional[WorkshopJob]:
    return db.query(WorkshopJob).filter(WorkshopJob.job_ref == job_ref).first()


def update_job_status(db: Session, job: WorkshopJob, update: JobStatusUpdate, changed_by: str = "courtney") -> WorkshopJob:
    old_status = job.status
    job.status = update.status
    if update.status == "completed":
        job.completed_at = datetime.now(timezone.utc)
    job.updated_at = datetime.now(timezone.utc)
    db.add(WorkshopJobHistory(
        job_id=job.id,
        from_status=old_status,
        to_status=update.status,
        note=update.note,
        changed_by=changed_by,
    ))
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: WorkshopJob, data: JobUpdate) -> WorkshopJob:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(job, field, value)
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def add_line_item(db: Session, job: WorkshopJob, item: LineItemIn) -> WorkshopLineItem:
    line = WorkshopLineItem(
        job_id=job.id,
        description=item.description,
        qty=item.qty,
        unit_price=item.unit_price,
        line_total=(item.unit_price * item.qty) if item.unit_price else None,
        item_type=item.item_type,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line


def delete_line_item(db: Session, job: WorkshopJob, item_id: int) -> bool:
    line = db.query(WorkshopLineItem).filter(
        WorkshopLineItem.id == item_id,
        WorkshopLineItem.job_id == job.id,
    ).first()
    if not line:
        return False
    db.delete(line)
    db.commit()
    return True
