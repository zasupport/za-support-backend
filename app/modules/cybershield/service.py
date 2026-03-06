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
    """Called by scheduler on 1st of month — generates PDFs for all active CyberShield practices."""
    import calendar, os
    from sqlalchemy import text
    from app.modules.cybershield.report_generator import generate_cybershield_pdf

    now = datetime.now(timezone.utc)
    if now.month == 1:
        month_label = f"December {now.year - 1}"
    else:
        month_label = f"{calendar.month_name[now.month - 1]} {now.year}"

    active = db.query(CyberShieldEnrollment).filter(
        CyberShieldEnrollment.active == True
    ).all()

    os.makedirs("/tmp/cybershield_reports", exist_ok=True)
    count = 0

    for enrollment in active:
        try:
            # Look up client name from clients table
            row = db.execute(
                text("SELECT first_name, last_name FROM clients WHERE client_id = :cid"),
                {"cid": enrollment.client_id},
            ).fetchone()
            client_name = f"{row.first_name} {row.last_name}".strip() if row else enrollment.client_id

            # Pull real event counts for this client's devices in the report month
            prev_month_end = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            if now.month == 1:
                prev_month_start = datetime(now.year - 1, 12, 1, tzinfo=timezone.utc)
            else:
                prev_month_start = datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)

            shield_count_row = db.execute(
                text(
                    "SELECT COUNT(*) FROM shield_events se "
                    "JOIN client_devices cd ON cd.serial = se.serial "
                    "WHERE cd.client_id = :cid "
                    "AND se.created_at >= :start AND se.created_at < :end"
                ),
                {"cid": enrollment.client_id, "start": prev_month_start, "end": prev_month_end},
            ).scalar()

            isp_count_row = db.execute(
                text(
                    "SELECT COUNT(DISTINCT io.id) FROM isp_outages io "
                    "JOIN isp_providers ip ON ip.id = io.provider_id "
                    "JOIN client_devices cd ON LOWER(cd.isp_name) LIKE '%' || LOWER(COALESCE(ip.name,'')) || '%' "
                    "WHERE cd.client_id = :cid "
                    "AND io.started_at >= :start AND io.started_at < :end"
                ),
                {"cid": enrollment.client_id, "start": prev_month_start, "end": prev_month_end},
            ).scalar()

            pdf_bytes = generate_cybershield_pdf(
                client_name=client_name,
                practice_name=enrollment.practice_name or client_name,
                isp_name=enrollment.isp_name,
                month_label=month_label,
                shield_event_count=int(shield_count_row or 0),
                isp_outage_count=int(isp_count_row or 0),
            )

            safe = enrollment.client_id.replace("/", "_")
            filename = f"CyberShield {enrollment.practice_name or client_name} {month_label}.pdf"
            file_path = f"/tmp/cybershield_reports/{safe}_{month_label.replace(' ', '_')}.pdf"

            with open(file_path, "wb") as f:
                f.write(pdf_bytes)

            record_report(db, enrollment.client_id, filename, month_label, file_path)
            count += 1
            logger.info(f"CyberShield PDF generated for {enrollment.client_id} ({month_label})")
        except Exception as exc:
            logger.error(f"CyberShield report failed for {enrollment.client_id}: {exc}")

    logger.info(f"CyberShield: generated {count}/{len(active)} monthly reports for {month_label}")
    return count


def sync_sla_enrollments(db: Session) -> dict:
    """Auto-enroll all SLA-tier clients who aren't already enrolled."""
    from sqlalchemy import text

    rows = db.execute(
        text("SELECT client_id, first_name, last_name FROM clients WHERE status = 'sla'")
    ).fetchall()

    enrolled_count = 0
    skipped_count = 0

    for row in rows:
        if get_enrollment(db, row.client_id):
            skipped_count += 1
            continue
        try:
            req = EnrollRequest(
                client_id=row.client_id,
                practice_name=f"{row.first_name} {row.last_name}".strip(),
            )
            enroll(db, req)
            enrolled_count += 1
            logger.info(f"CyberShield: auto-enrolled SLA client {row.client_id}")
        except Exception as exc:
            logger.warning(f"CyberShield sync: could not enroll {row.client_id}: {exc}")

    return {"enrolled": enrolled_count, "already_enrolled": skipped_count, "total_sla": len(rows)}


def get_report_pdf(db: Session, report_id: int) -> tuple[bytes | None, str]:
    """Return (pdf_bytes, filename) for a stored report, or (None, '') if not found."""
    row = db.query(CyberShieldReport).filter(CyberShieldReport.id == report_id).first()
    if not row or not row.file_path:
        return None, ""
    try:
        with open(row.file_path, "rb") as f:
            return f.read(), row.filename
    except FileNotFoundError:
        return None, row.filename
