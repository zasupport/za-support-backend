"""
CyberShield router — HTTP layer only. All logic in service.py.
Prefix: /api/v1/cybershield
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.cybershield import service
from app.modules.cybershield.schemas import EnrollRequest, EnrollmentOut, ReportOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cybershield", tags=["CyberShield"])


# ── Summary ────────────────────────────────────────────────────────────────────

@router.get("/summary", dependencies=[Depends(verify_agent_token)])
def get_summary(db: Session = Depends(get_db)):
    """Dashboard summary: active enrollments, monthly ARR, reports generated."""
    return service.get_summary(db)


# ── Enrollments ────────────────────────────────────────────────────────────────

@router.get("/enrollments", response_model=dict, dependencies=[Depends(verify_agent_token)])
def list_enrollments(
    active_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_enrollments(db, active_only=active_only, page=page, per_page=per_page)
    return {
        "data": [EnrollmentOut.model_validate(e) for e in result["data"]],
        "meta": result["meta"],
    }


@router.post("/enrollments", response_model=EnrollmentOut, dependencies=[Depends(verify_agent_token)])
def enroll_client(data: EnrollRequest, db: Session = Depends(get_db)):
    try:
        return service.enroll(db, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/enrollments/{client_id}", response_model=EnrollmentOut, dependencies=[Depends(verify_agent_token)])
def get_enrollment(client_id: str, db: Session = Depends(get_db)):
    row = service.get_enrollment(db, client_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return row


@router.patch("/enrollments/{client_id}/activate", response_model=EnrollmentOut, dependencies=[Depends(verify_agent_token)])
def activate(client_id: str, db: Session = Depends(get_db)):
    row = service.set_active(db, client_id, active=True)
    if not row:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return row


@router.patch("/enrollments/{client_id}/deactivate", response_model=EnrollmentOut, dependencies=[Depends(verify_agent_token)])
def deactivate(client_id: str, db: Session = Depends(get_db)):
    row = service.set_active(db, client_id, active=False)
    if not row:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return row


# ── Reports ────────────────────────────────────────────────────────────────────

@router.get("/reports", response_model=dict, dependencies=[Depends(verify_agent_token)])
def list_reports(
    client_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_reports(db, client_id=client_id, page=page, per_page=per_page)
    return {
        "data": [ReportOut.model_validate(r) for r in result["data"]],
        "meta": result["meta"],
    }
