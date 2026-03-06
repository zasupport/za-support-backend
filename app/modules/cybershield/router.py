"""
CyberShield router — HTTP layer only. All logic in service.py.
Prefix: /api/v1/cybershield
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.cybershield import service
from app.modules.cybershield.models import CyberShieldBilling
from app.modules.cybershield.schemas import (
    EnrollRequest, EnrollmentOut, ReportOut,
    BillingCreate, BillingStatusUpdate, BillingOut,
)
from app.modules.cybershield.report_generator import generate_cybershield_pdf

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


@router.post("/enrollments/sync", dependencies=[Depends(verify_agent_token)])
def sync_enrollments(db: Session = Depends(get_db)):
    """Auto-enroll all SLA-tier clients not already enrolled in CyberShield."""
    return service.sync_sla_enrollments(db)


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


@router.get("/reports/{client_id}/generate", dependencies=[Depends(verify_agent_token)])
def generate_report(
    client_id: str,
    month: Optional[str] = Query(None, description="Month label e.g. 'February 2026' (defaults to current month)"),
    db: Session = Depends(get_db),
):
    """Generate a CyberShield PDF report for an enrolled practice and return it inline."""
    enrollment = service.get_enrollment(db, client_id)
    if not enrollment:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' is not enrolled in CyberShield")

    # Resolve month label
    now = datetime.now()
    month_label = month or now.strftime("%B %Y")

    # Count shield events this month
    try:
        shield_count = db.execute(
            text("""
            SELECT COUNT(*) FROM shield_events
            WHERE timestamp >= date_trunc('month', NOW())
              AND serial IN (
                SELECT serial FROM client_devices WHERE client_id = :cid
              )
            """),
            {"cid": client_id},
        ).scalar() or 0
    except Exception:
        shield_count = 0

    # Count ISP outages this month
    try:
        isp_count = db.execute(
            text("""
            SELECT COUNT(*) FROM isp_outages
            WHERE detected_at >= date_trunc('month', NOW())
            """),
        ).scalar() or 0
    except Exception:
        isp_count = 0

    # Resolve client name
    try:
        client_row = db.execute(
            text("SELECT first_name, last_name FROM clients WHERE client_id = :cid"),
            {"cid": client_id},
        ).fetchone()
        client_name = f"{client_row.first_name} {client_row.last_name}".strip() if client_row else client_id
    except Exception:
        client_name = client_id

    try:
        pdf_bytes = generate_cybershield_pdf(
            client_name=client_name,
            practice_name=enrollment.practice_name or client_name,
            isp_name=enrollment.isp_name,
            month_label=month_label,
            shield_event_count=int(shield_count),
            isp_outage_count=int(isp_count),
        )
    except Exception as e:
        logger.error(f"CyberShield PDF generation failed for {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    # Log the report
    safe_name = (enrollment.practice_name or client_name).replace(" ", "_")
    date_str = now.strftime("%d %m %Y")
    filename = f"CyberShield {enrollment.practice_name or client_name} {date_str}.pdf"
    try:
        service.record_report(db, client_id=client_id, filename=filename, month_label=month_label)
    except Exception as e:
        logger.warning(f"Failed to log CyberShield report: {e}")

    dl_name = f"CyberShield_{safe_name}_{date_str.replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{dl_name}"'},
    )


# ── Billing ────────────────────────────────────────────────────────────────────

@router.get("/billing/summary", dependencies=[Depends(verify_agent_token)])
def billing_summary(db: Session = Depends(get_db)):
    """Outstanding, paid this month, overdue count."""
    return service.get_billing_summary(db)


@router.get("/billing", response_model=dict, dependencies=[Depends(verify_agent_token)])
def list_billing(
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    result = service.list_billing(db, client_id=client_id, status=status, page=page, per_page=per_page)
    return {
        "data": [BillingOut.model_validate(r) for r in result["data"]],
        "meta": result["meta"],
    }


@router.post("/billing", response_model=BillingOut, dependencies=[Depends(verify_agent_token)])
def create_billing(data: BillingCreate, db: Session = Depends(get_db)):
    try:
        return service.create_billing_record(db, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/billing/{billing_id}/status", response_model=BillingOut, dependencies=[Depends(verify_agent_token)])
def update_billing_status(billing_id: int, update: BillingStatusUpdate, db: Session = Depends(get_db)):
    row = service.update_billing_status(db, billing_id, update)
    if not row:
        raise HTTPException(status_code=404, detail="Billing record not found")
    return row


@router.post("/billing/{billing_id}/email-invoice", dependencies=[Depends(verify_agent_token)])
def email_invoice(billing_id: int, db: Session = Depends(get_db)):
    """Generate and email the invoice PDF to the client. Marks billing record as sent."""
    ok = service.email_invoice(db, billing_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not send invoice — check client email and enrollment")
    return {"sent": True}


@router.post("/billing/generate", dependencies=[Depends(verify_agent_token)])
def generate_billing(db: Session = Depends(get_db)):
    """Manually trigger billing record generation for the current month (idempotent)."""
    count = service.generate_monthly_billing(db)
    return {"created": count}


@router.get("/billing/{billing_id}/invoice", dependencies=[Depends(verify_agent_token)])
def download_invoice(billing_id: int, db: Session = Depends(get_db)):
    """Generate and download a PDF invoice for a billing record."""
    from app.modules.cybershield.invoice_generator import generate_cybershield_invoice
    from decimal import Decimal

    billing = db.query(CyberShieldBilling).filter(
        CyberShieldBilling.id == billing_id
    ).first()
    if not billing:
        raise HTTPException(status_code=404, detail="Billing record not found")

    enrollment = service.get_enrollment(db, billing.client_id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    # Resolve client name and email
    try:
        client_row = db.execute(
            text("SELECT first_name, last_name, email FROM clients WHERE client_id = :cid"),
            {"cid": billing.client_id},
        ).fetchone()
        client_name = f"{client_row.first_name} {client_row.last_name}".strip() if client_row else billing.client_id
        client_email = client_row.email if client_row else None
    except Exception:
        client_name = billing.client_id
        client_email = None

    # Auto-generate invoice ref if not set
    invoice_ref = billing.invoice_ref or f"CS-{billing.client_id.upper()[:6]}-{billing.month_label.replace(' ', '-').upper()}"

    try:
        pdf_bytes = generate_cybershield_invoice(
            client_name=client_name,
            practice_name=enrollment.practice_name or client_name,
            client_email=client_email,
            month_label=billing.month_label,
            amount_excl=Decimal(str(billing.amount)),
            invoice_ref=invoice_ref,
            due_date=billing.due_date,
            isp_name=enrollment.isp_name,
        )
    except Exception as e:
        logger.error(f"Invoice generation failed for billing {billing_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Invoice generation failed: {e}")

    safe = (enrollment.practice_name or client_name).replace(" ", "_")
    filename = f"CyberShield_Invoice_{safe}_{billing.month_label.replace(' ', '_')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
