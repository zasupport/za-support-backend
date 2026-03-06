"""
Workshop router — HTTP layer only. All logic in service.py.
Prefix: /api/v1/workshop
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.workshop import service
from app.modules.workshop.schemas import (
    JobCreate, JobUpdate, JobStatusUpdate, LineItemIn,
    JobOut, JobListOut, LineItemOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/workshop", tags=["Workshop"])


@router.get("/revenue", dependencies=[Depends(verify_agent_token)])
def revenue_summary(db: Session = Depends(get_db)):
    """Revenue analytics — totals from completed jobs and open pipeline value."""
    return service.get_revenue_summary(db)


@router.get("/jobs", response_model=dict, dependencies=[Depends(verify_agent_token)])
def list_jobs(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List job cards. Filter by client_id and/or status."""
    result = service.list_jobs(db, client_id=client_id, status=status, page=page, per_page=per_page)
    return {
        "data": [JobListOut.model_validate(j) for j in result["data"]],
        "meta": result["meta"],
    }


@router.post("/jobs", response_model=JobOut, dependencies=[Depends(verify_agent_token)])
def create_job(data: JobCreate, db: Session = Depends(get_db)):
    """Create a job card manually."""
    return service.create_job(db, data, source="manual")


@router.get("/jobs/{job_ref}", response_model=JobOut, dependencies=[Depends(verify_agent_token)])
def get_job(job_ref: str, db: Session = Depends(get_db)):
    job = service.get_job(db, job_ref)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/jobs/{job_ref}/status", response_model=JobOut, dependencies=[Depends(verify_agent_token)])
def update_status(job_ref: str, update: JobStatusUpdate, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Cycle job status: open → in_progress → waiting_parts → done."""
    from app.core.event_bus import emit_event
    job = service.get_job(db, job_ref)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    prev_status = job.status
    updated = service.update_job_status(db, job, update)
    done_statuses = {"done", "completed"}
    if update.status in done_statuses and prev_status not in done_statuses:
        background.add_task(emit_event, "workshop.job_completed", {
            "job_ref":   updated.job_ref,
            "client_id": updated.client_id,
            "serial":    updated.serial,
            "title":     updated.title,
            "notes":     updated.notes,
        })
    return updated


@router.patch("/jobs/{job_ref}", response_model=JobOut, dependencies=[Depends(verify_agent_token)])
def update_job(job_ref: str, data: JobUpdate, db: Session = Depends(get_db)):
    """Update job fields (title, notes, scheduled date, labour minutes, etc.)."""
    job = service.get_job(db, job_ref)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return service.update_job(db, job, data)


@router.post("/jobs/{job_ref}/line-items", response_model=LineItemOut, dependencies=[Depends(verify_agent_token)])
def add_line_item(job_ref: str, item: LineItemIn, db: Session = Depends(get_db)):
    """Add a line item (labour, part, or service) to an existing job."""
    job = service.get_job(db, job_ref)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return service.add_line_item(db, job, item)


@router.delete("/jobs/{job_ref}/line-items/{item_id}", status_code=204, dependencies=[Depends(verify_agent_token)])
def delete_line_item(job_ref: str, item_id: int, db: Session = Depends(get_db)):
    """Remove a line item from a job."""
    job = service.get_job(db, job_ref)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not service.delete_line_item(db, job, item_id):
        raise HTTPException(status_code=404, detail="Line item not found")
