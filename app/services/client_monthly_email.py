"""
Monthly client health summary email — runs on the 1st of each month.

For every active/SLA client:
  - Sends a plain-English device health summary
  - Shows last scan date, risk level, any open workshop jobs
  - Encourages booking if overdue for a scan (>60 days)
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email

logger = logging.getLogger(__name__)

NOTIFY_FROM = "ZA Support <admin@zasupport.com>"
BOOKING_LINK = "https://zasupport.com/book"
DASHBOARD = "https://app.zasupport.com"


def run_monthly_client_emails() -> None:
    """Entry point called by automation scheduler on the 1st of each month."""
    db = get_session_factory()()
    try:
        _send_all(db)
    finally:
        db.close()


def _send_all(db: Session) -> None:
    rows = db.execute(text("""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.email,
            c.status,
            c.has_business,
            c.business_name,
            -- latest scan across all client devices
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
            (SELECT COUNT(*) FROM client_devices d
             WHERE d.client_id = c.client_id AND d.is_active = TRUE) AS device_count,
            (SELECT COUNT(*) FROM workshop_jobs j
             WHERE j.client_id = c.client_id
               AND j.status NOT IN ('done', 'completed', 'cancelled')) AS open_jobs
        FROM clients c
        WHERE c.status IN ('active', 'sla')
          AND c.email IS NOT NULL
          AND c.email != ''
        ORDER BY c.first_name
    """)).fetchall()

    sent = 0
    failed = 0
    month_label = datetime.now(timezone.utc).strftime("%B %Y")

    for row in rows:
        r = dict(row._mapping)
        try:
            _send_one(r, month_label)
            sent += 1
        except Exception as e:
            logger.error(f"Monthly email failed for {r.get('client_id')}: {e}")
            failed += 1

    logger.info(f"[MonthlyEmail] {month_label}: {sent} sent, {failed} failed.")


def _send_one(r: dict, month_label: str) -> None:
    first          = r.get("first_name", "")
    client_id      = r.get("client_id", "")
    email          = r.get("email", "")
    risk_level     = r.get("risk_level") or "Unknown"
    risk_score     = r.get("risk_score")
    days_since     = r.get("days_since_scan")
    device_count   = r.get("device_count", 0) or 0
    open_jobs      = r.get("open_jobs", 0) or 0
    last_scan_date = r.get("last_scan_date")
    has_business   = r.get("has_business", False)
    business_name  = r.get("business_name", "")

    # Human-readable risk
    risk_label = {
        "low":      "Low — your device is healthy",
        "moderate": "Moderate — some items to watch",
        "high":     "High — attention needed soon",
        "critical": "Critical — immediate action required",
    }.get(risk_level.lower(), risk_level)

    scan_line = (
        f"Your last health scan was {days_since} days ago"
        if days_since is not None
        else "We have not yet run a health scan on your device"
    )

    overdue = days_since is not None and days_since > 60
    overdue_note = (
        "\nYour device is overdue for a health scan. "
        "Regular scans help us catch issues early — we recommend booking soon.\n"
        f"Book a visit: {BOOKING_LINK}\n"
        if overdue else ""
    )

    jobs_line = (
        f"You currently have {open_jobs} open workshop job{'s' if open_jobs != 1 else ''} in progress."
        if open_jobs > 0
        else "No open workshop jobs — you're all clear."
    )

    business_line = (
        f"\nAs a business client ({business_name}), your practice IT is covered under your ZA Support plan.\n"
        if has_business and business_name
        else ""
    )

    scan_date_str = (
        last_scan_date.strftime("%d/%m/%Y") if hasattr(last_scan_date, "strftime")
        else str(last_scan_date)[:10] if last_scan_date else "not yet recorded"
    )

    subject = f"Your {month_label} Device Health Summary — ZA Support"

    body = f"""Hi {first},

Here is your monthly device health summary from ZA Support.

DEVICE HEALTH — {month_label.upper()}
{"─" * 40}
Devices monitored : {device_count}
Last scan date    : {scan_date_str}
{scan_line}.
Risk level        : {risk_label}{f" (score: {risk_score}/10)" if risk_score is not None else ""}
Workshop jobs     : {jobs_line}
{overdue_note}{business_line}
YOUR NEXT STEPS
{"─" * 40}
{"• Book a health scan — your device is overdue." if overdue else "• Keep your Mac up to date and backed up daily."}
• If you notice anything unusual, contact us immediately.
• View your full device history: {DASHBOARD}/clients/{client_id}

CONTACT ZA SUPPORT
{"─" * 40}
Phone  : 064 529 5863
Email  : admin@zasupport.com
Web    : zasupport.com

Practice IT. Perfected.
ZA Support | Vizibiliti Intelligent Solutions (Pty) Ltd
1 Hyde Park Lane, Hyde Park, Johannesburg, 2196
"""

    send_email(email, subject, body)
    logger.info(f"Monthly summary sent to {email} ({client_id}) — {risk_level}, {days_since}d since scan")
