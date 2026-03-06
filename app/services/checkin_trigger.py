"""
Six-Month Check-In Trigger — daily scheduled job.
Sends re-engagement emails to clients at T-30 and T-14 days before their
6-month check-in due date. Escalates to Courtney if T=0 and not booked.

Check-in due date = last_visit_date + 6 months.
'Last visit' = most recent completed workshop job for that client.
"""
import logging
from datetime import datetime, timezone, timedelta, date

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO     = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com"

CHECKIN_MONTHS   = 6          # Months between check-ins
REMIND_AT_DAYS   = [30, 14]   # Send reminders at T-30 and T-14
ESCALATE_AT_DAYS = 0          # Escalate to Courtney at T=0 if not booked


def run_checkin_trigger():
    """
    Daily: compute each active/SLA client's next check-in date.
    Send reminders and escalations at the correct intervals.
    """
    db = get_session_factory()()
    try:
        today = date.today()

        # Find active/SLA clients with at least one completed workshop job
        rows = db.execute(
            text("""
            SELECT
                c.client_id,
                c.first_name,
                c.last_name,
                c.email,
                c.status,
                MAX(wj.completed_at)::date AS last_visit_date
            FROM clients c
            JOIN workshop_jobs wj ON wj.client_id = c.client_id
            WHERE c.status IN ('active', 'sla')
              AND wj.status IN ('completed', 'done')
              AND wj.completed_at IS NOT NULL
            GROUP BY c.client_id, c.first_name, c.last_name, c.email, c.status
            """)
        ).fetchall()

        if not rows:
            logger.info("[CheckinTrigger] No clients with completed visits.")
            return

        reminded = 0
        escalated = 0

        for r in rows:
            if not r.last_visit_date:
                continue

            last_visit  = r.last_visit_date
            # 6-month due date: add 6 months to last visit
            try:
                next_month = last_visit.month + CHECKIN_MONTHS
                next_year  = last_visit.year + (next_month - 1) // 12
                next_month = ((next_month - 1) % 12) + 1
                checkin_due = last_visit.replace(year=next_year, month=next_month)
            except (ValueError, OverflowError):
                continue

            days_until = (checkin_due - today).days
            client_id  = r.client_id
            first_name = r.first_name or "there"
            email      = r.email
            name       = f"{r.first_name} {r.last_name}".strip()

            if days_until in REMIND_AT_DAYS:
                if not email:
                    continue
                subject = f"Your {CHECKIN_MONTHS}-Month Health Check is Coming Up — {name}"
                body = "\n".join([
                    f"Hi {first_name},",
                    f"",
                    f"It's been nearly 6 months since your last ZA Support visit — time for your",
                    f"complementary Health Check Scout diagnostic and review.",
                    f"",
                    f"What's included:",
                    f"  • Full 120-point Mac health and security diagnostic",
                    f"  • Updated CyberPulse Assessment report",
                    f"  • 30-minute walk-through of findings and recommendations",
                    f"  • No charge — this is part of your ongoing ZA Support service",
                    f"",
                    f"Your check-in is due in approximately {days_until} days ({checkin_due.strftime('%d/%m/%Y')}).",
                    f"",
                    f"To book, simply reply to this email or call Courtney on 064 529 5863.",
                    f"",
                    f"ZA Support | Practice IT. Perfected.",
                    f"admin@zasupport.com | 064 529 5863 | zasupport.com",
                ])
                try:
                    send_email(email, subject, body)
                    logger.info(f"[CheckinTrigger] T-{days_until} reminder sent to {email} ({client_id})")
                    reminded += 1
                except Exception as e:
                    logger.error(f"[CheckinTrigger] Reminder email failed for {client_id}: {e}")

            elif days_until <= ESCALATE_AT_DAYS:
                # Due or overdue — escalate to Courtney
                overdue_days = abs(days_until)
                subject = f"Check-In Overdue — {name} ({overdue_days}d overdue)"
                body = "\n".join([
                    f"ACTION REQUIRED: 6-month check-in is overdue.",
                    f"",
                    f"Client    : {name} ({client_id})",
                    f"Status    : {r.status}",
                    f"Last visit: {last_visit.strftime('%d/%m/%Y')}",
                    f"Due date  : {checkin_due.strftime('%d/%m/%Y')}",
                    f"Overdue   : {overdue_days} day(s)",
                    f"",
                    f"Contact {first_name} to book the 6-month health check.",
                    f"Dashboard: {DASHBOARD_URL}/clients/{client_id}",
                ])
                try:
                    send_email(NOTIFY_TO, subject, body)
                    send_slack(
                        f":calendar: *Check-In Overdue* — *{name}* (`{client_id}`)\n"
                        f"Last visit: {last_visit.strftime('%d/%m/%Y')} | Due: {checkin_due.strftime('%d/%m/%Y')} | "
                        f"Overdue {overdue_days}d\n"
                        f"<{DASHBOARD_URL}/clients/{client_id}|Open Client>"
                    )
                    logger.info(f"[CheckinTrigger] Escalated overdue check-in for {client_id}")
                    escalated += 1
                except Exception as e:
                    logger.error(f"[CheckinTrigger] Escalation failed for {client_id}: {e}")

        logger.info(f"[CheckinTrigger] Done. Reminders: {reminded}, Escalated: {escalated}.")

    except Exception as e:
        logger.error(f"[CheckinTrigger] Job failed: {e}", exc_info=True)
    finally:
        db.close()
