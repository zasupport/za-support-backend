"""
CyberShield service layer — all business logic.
Manages practice enrollments and monthly PDF report records.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.modules.cybershield.models import CyberShieldEnrollment, CyberShieldReport
from app.modules.cybershield.schemas import EnrollRequest

logger = logging.getLogger(__name__)


# ── Enrollments ────────────────────────────────────────────────────────────────

def list_enrollments(
    db: Session,
    active_only: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    q = db.query(CyberShieldEnrollment)
    if active_only:
        q = q.filter(CyberShieldEnrollment.active == True)
    total = q.count()
    rows = q.order_by(CyberShieldEnrollment.enrolled_at.desc()) \
             .offset((page - 1) * per_page).limit(per_page).all()
    return {"data": rows, "meta": {"page": page, "per_page": per_page, "total": total}}


def get_enrollment(db: Session, client_id: str) -> Optional[CyberShieldEnrollment]:
    return db.query(CyberShieldEnrollment) \
             .filter(CyberShieldEnrollment.client_id == client_id).first()


def enroll(db: Session, data: EnrollRequest) -> CyberShieldEnrollment:
    existing = get_enrollment(db, data.client_id)
    if existing:
        raise ValueError(f"Client {data.client_id} is already enrolled in CyberShield")

    row = CyberShieldEnrollment(
        client_id=data.client_id,
        practice_name=data.practice_name,
        isp_name=data.isp_name,
        monthly_fee=Decimal(str(data.monthly_fee)) if data.monthly_fee else Decimal("1499.00"),
        notes=data.notes,
        active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(f"CyberShield: enrolled {data.client_id}")
    return row


def set_active(db: Session, client_id: str, active: bool) -> Optional[CyberShieldEnrollment]:
    row = get_enrollment(db, client_id)
    if not row:
        return None
    row.active = active
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


# ── Reports ────────────────────────────────────────────────────────────────────

def list_reports(
    db: Session,
    client_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    q = db.query(CyberShieldReport)
    if client_id:
        q = q.filter(CyberShieldReport.client_id == client_id)
    total = q.count()
    rows = q.order_by(CyberShieldReport.generated_at.desc()) \
             .offset((page - 1) * per_page).limit(per_page).all()
    return {"data": rows, "meta": {"page": page, "per_page": per_page, "total": total}}


def record_report(
    db: Session,
    client_id: str,
    filename: str,
    month_label: Optional[str] = None,
    file_path: Optional[str] = None,
) -> CyberShieldReport:
    row = CyberShieldReport(
        client_id=client_id,
        filename=filename,
        month_label=month_label,
        file_path=file_path,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(f"CyberShield: report recorded for {client_id} ({month_label})")
    return row


# ── Summary ────────────────────────────────────────────────────────────────────

def get_summary(db: Session) -> dict:
    active_count = db.query(CyberShieldEnrollment).filter(
        CyberShieldEnrollment.active == True
    ).count()

    total_count = db.query(CyberShieldEnrollment).count()

    monthly_arr_row = db.query(func.sum(CyberShieldEnrollment.monthly_fee)).filter(
        CyberShieldEnrollment.active == True
    ).scalar()
    monthly_arr = float(monthly_arr_row) if monthly_arr_row else 0.0

    reports_total = db.query(CyberShieldReport).count()

    return {
        "active_subscriptions": active_count,
        "total_subscriptions": total_count,
        "monthly_arr": monthly_arr,
        "reports_generated": reports_total,
    }


# ── Scheduler function ─────────────────────────────────────────────────────────

def generate_all_monthly_reports(db: Session) -> int:
    """Placeholder called by scheduler on 1st of month.
    Logs which clients need reports; actual PDF generation is a separate process."""
    now = datetime.now(timezone.utc)
    if now.month == 1:
        month_label = f"December {now.year - 1}"
    else:
        import calendar
        month_label = f"{calendar.month_name[now.month - 1]} {now.year}"

    active = db.query(CyberShieldEnrollment).filter(
        CyberShieldEnrollment.active == True
    ).all()

    logger.info(f"CyberShield: {len(active)} practices due for {month_label} report")
    for e in active:
        logger.info(f"  → {e.client_id} ({e.practice_name or 'unknown practice'})")

    return len(active)
