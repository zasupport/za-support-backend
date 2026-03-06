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

from app.modules.cybershield.models import CyberShieldEnrollment, CyberShieldReport, CyberShieldBilling
from app.modules.cybershield.schemas import EnrollRequest, BillingCreate, BillingStatusUpdate

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


# ── Billing ────────────────────────────────────────────────────────────────────

def list_billing(
    db: Session,
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    q = db.query(CyberShieldBilling)
    if client_id:
        q = q.filter(CyberShieldBilling.client_id == client_id)
    if status:
        q = q.filter(CyberShieldBilling.status == status)
    total = q.count()
    rows = q.order_by(CyberShieldBilling.created_at.desc()) \
             .offset((page - 1) * per_page).limit(per_page).all()
    return {"data": rows, "meta": {"page": page, "per_page": per_page, "total": total}}


def create_billing_record(db: Session, data: BillingCreate) -> CyberShieldBilling:
    existing = db.query(CyberShieldBilling).filter(
        CyberShieldBilling.client_id == data.client_id,
        CyberShieldBilling.month_label == data.month_label,
    ).first()
    if existing:
        raise ValueError(f"Billing record already exists for {data.client_id} / {data.month_label}")
    row = CyberShieldBilling(
        client_id=data.client_id,
        month_label=data.month_label,
        amount=data.amount,
        due_date=data.due_date,
        invoice_ref=data.invoice_ref,
        notes=data.notes,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(f"CyberShield billing: created record for {data.client_id} ({data.month_label})")
    return row


def update_billing_status(db: Session, billing_id: int, update: BillingStatusUpdate) -> Optional[CyberShieldBilling]:
    row = db.query(CyberShieldBilling).filter(CyberShieldBilling.id == billing_id).first()
    if not row:
        return None
    row.status = update.status
    if update.invoice_ref:
        row.invoice_ref = update.invoice_ref
    if update.notes:
        row.notes = update.notes
    if update.status == "paid":
        row.paid_at = datetime.now(timezone.utc)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def generate_monthly_billing(db: Session) -> int:
    """
    Called by scheduler on 1st of month. Creates billing records for all active
    enrollments for the current billing month. Idempotent — skips if record exists.
    """
    import calendar
    now = datetime.now(timezone.utc)
    month_label = f"{calendar.month_name[now.month]} {now.year}"

    active = db.query(CyberShieldEnrollment).filter(
        CyberShieldEnrollment.active == True
    ).all()

    # Due date = 20th of current month
    from datetime import date
    due = date(now.year, now.month, min(20, calendar.monthrange(now.year, now.month)[1]))

    created = 0
    for enrollment in active:
        existing = db.query(CyberShieldBilling).filter(
            CyberShieldBilling.client_id == enrollment.client_id,
            CyberShieldBilling.month_label == month_label,
        ).first()
        if existing:
            continue
        row = CyberShieldBilling(
            client_id=enrollment.client_id,
            month_label=month_label,
            amount=enrollment.monthly_fee,
            due_date=due,
            status="pending",
        )
        db.add(row)
        created += 1

    db.commit()
    logger.info(f"CyberShield billing: created {created} records for {month_label}")
    return created


def get_billing_summary(db: Session) -> dict:
    """Totals: outstanding, paid this month, overdue count."""
    from sqlalchemy import text
    import calendar
    now = datetime.now(timezone.utc)
    month_label = f"{calendar.month_name[now.month]} {now.year}"
    row = db.execute(text("""
        SELECT
            COALESCE(SUM(amount) FILTER (WHERE status IN ('pending','sent')), 0) AS outstanding,
            COALESCE(SUM(amount) FILTER (WHERE status = 'paid'), 0)              AS total_paid_all_time,
            COALESCE(SUM(amount) FILTER (WHERE status = 'paid'
                AND month_label = :ml), 0)                                       AS paid_this_month,
            COUNT(*) FILTER (WHERE status = 'overdue')                           AS overdue_count
        FROM cybershield_billing
    """), {"ml": month_label}).fetchone()
    return {
        "outstanding":       float(row.outstanding),
        "total_paid_all_time": float(row.total_paid_all_time),
        "paid_this_month":   float(row.paid_this_month),
        "overdue_count":     int(row.overdue_count),
    }


def email_invoice(db: Session, billing_id: int) -> bool:
    """
    Generate invoice PDF and email it to the client.
    Returns True if sent, False on error.
    """
    from decimal import Decimal
    from app.modules.cybershield.invoice_generator import generate_cybershield_invoice
    from app.services.notification_engine import send_email

    row = db.query(CyberShieldBilling).filter(CyberShieldBilling.id == billing_id).first()
    if not row:
        return False

    enrollment = get_enrollment(db, row.client_id)
    if not enrollment:
        return False

    from sqlalchemy import text
    try:
        client_row = db.execute(
            text("SELECT first_name, last_name, email FROM clients WHERE client_id = :cid"),
            {"cid": row.client_id},
        ).fetchone()
    except Exception:
        client_row = None

    client_name  = f"{client_row.first_name} {client_row.last_name}".strip() if client_row else row.client_id
    client_email = client_row.email if client_row else None

    if not client_email:
        logger.warning(f"CyberShield billing: no email for {row.client_id} — invoice not sent")
        return False

    invoice_ref = row.invoice_ref or f"CS-{row.client_id.upper()[:6]}-{row.month_label.replace(' ', '-').upper()}"

    try:
        pdf_bytes = generate_cybershield_invoice(
            client_name=client_name,
            practice_name=enrollment.practice_name or client_name,
            client_email=client_email,
            month_label=row.month_label,
            amount_excl=Decimal(str(row.amount)),
            invoice_ref=invoice_ref,
            due_date=row.due_date,
            isp_name=enrollment.isp_name,
        )
    except Exception as exc:
        logger.error(f"CyberShield invoice PDF failed for {row.client_id}: {exc}")
        return False

    subject = f"CyberShield Invoice — {row.month_label} ({invoice_ref})"
    body = "\n".join([
        f"Dear {client_name},",
        "",
        f"Please find attached your CyberShield invoice for {row.month_label}.",
        f"Invoice reference: {invoice_ref}",
        f"Amount due (incl. VAT): R {float(row.amount) * 1.15:,.2f}",
        f"Due date: {row.due_date.strftime('%d/%m/%Y') if row.due_date else 'On receipt'}",
        "",
        "Please use your invoice reference when making payment.",
        "",
        "ZA Support | Practice IT. Perfected.",
        "admin@zasupport.com | 064 529 5863 | zasupport.com",
    ])

    try:
        send_email(client_email, subject, body, attachments=[(pdf_bytes, "application/pdf", f"CyberShield_Invoice_{row.month_label.replace(' ','_')}.pdf")])
        logger.info(f"CyberShield invoice emailed to {client_email} ({invoice_ref})")

        # Mark as sent
        row.status = "sent"
        row.invoice_ref = invoice_ref
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as exc:
        logger.error(f"CyberShield invoice email failed for {row.client_id}: {exc}")
        return False


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
