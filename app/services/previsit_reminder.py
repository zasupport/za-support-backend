"""
Pre-Visit Reminder — daily job at 07:30.
Finds workshop jobs scheduled for today or tomorrow, emails the client
a reminder with the pre-visit check-in form link and what to prepare.
"""
import logging
from datetime import datetime, timezone, timedelta, date

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO      = "courtney@zasupport.com"
CHECKIN_FORM   = "https://app.zasupport.com/checkin"   # Formbricks form URL or dashboard page
DASHBOARD_URL  = "https://app.zasupport.com"


def run_previsit_reminders():
    """
    Email clients whose workshop job is scheduled for today or tomorrow.
    Also notifies Courtney of the day's schedule.
    """
    db = get_session_factory()()
    try:
        today    = date.today()
        tomorrow = today + timedelta(days=1)

        rows = db.execute(
            text("""
                SELECT
                    j.job_ref, j.title, j.scheduled_date, j.client_id, j.serial, j.notes,
                    c.first_name, c.last_name, c.email, c.phone, c.preferred_contact
                FROM workshop_jobs j
                LEFT JOIN clients c ON c.client_id = j.client_id
                WHERE j.scheduled_date IN (:today, :tomorrow)
                  AND j.status NOT IN ('done', 'cancelled')
                ORDER BY j.scheduled_date, c.last_name
            """),
            {"today": today, "tomorrow": tomorrow},
        ).fetchall()

        if not rows:
            logger.info("[PreVisitReminder] No visits scheduled for today or tomorrow.")
            return

        today_visits    = [r for r in rows if r.scheduled_date == today]
        tomorrow_visits = [r for r in rows if r.scheduled_date == tomorrow]

        # Email each client
        for r in rows:
            if not r.email:
                logger.warning(f"[PreVisitReminder] No email for client {r.client_id} — skipping")
                continue

            when = "today" if r.scheduled_date == today else "tomorrow"
            when_cap = when.capitalize()
            date_str = r.scheduled_date.strftime("%A, %d %B %Y")

            subject = f"ZA Support Visit — {when_cap}, {date_str}"
            body = "\n".join([
                f"Hi {r.first_name},",
                f"",
                f"This is a reminder that Courtney from ZA Support will be visiting {when}:",
                f"",
                f"  Date  : {date_str}",
                f"  Reason: {r.title}",
                f"",
                f"To help us make the most of the visit, please take 2 minutes to complete",
                f"our pre-visit check-in before we arrive:",
                f"",
                f"  {CHECKIN_FORM}",
                f"",
                f"What to prepare:",
                f"  • Have your Mac powered on and logged in",
                f"  • Plug in your backup drive if you have one",
                f"  • Note any issues or things that feel slow/unusual",
                f"  • Have your login passwords accessible (we may need to install/update)",
                f"",
                f"If the time doesn't work, please call or WhatsApp Courtney on 064 529 5863.",
                f"",
                f"ZA Support | Practice IT. Perfected.",
                f"admin@zasupport.com | 064 529 5863 | zasupport.com",
            ])

            try:
                send_email(r.email, subject, body)
                logger.info(f"[PreVisitReminder] Reminder sent to {r.email} for {r.scheduled_date} visit")
            except Exception as e:
                logger.error(f"[PreVisitReminder] Email failed for {r.email}: {e}")

        # Notify Courtney of the schedule
        schedule_lines = ["*Today's Visit Schedule*"]
        if today_visits:
            schedule_lines.append(f"\n*Today ({today.strftime('%d %b')})*")
            for r in today_visits:
                schedule_lines.append(f"  • {r.first_name} {r.last_name} — {r.title} | <{DASHBOARD_URL}/clients/{r.client_id}|Brief>")
        if tomorrow_visits:
            schedule_lines.append(f"\n*Tomorrow ({tomorrow.strftime('%d %b')})*")
            for r in tomorrow_visits:
                schedule_lines.append(f"  • {r.first_name} {r.last_name} — {r.title} | <{DASHBOARD_URL}/clients/{r.client_id}|Brief>")

        try:
            send_slack("\n".join(schedule_lines))
        except Exception as e:
            logger.error(f"[PreVisitReminder] Slack schedule notification failed: {e}")

        # Email Courtney a day-sheet
        courtney_lines = [
            f"Pre-Visit Schedule — {today.strftime('%A, %d %B %Y')}",
            f"",
        ]
        if today_visits:
            courtney_lines.append("TODAY:")
            for r in today_visits:
                courtney_lines.append(f"  {r.first_name} {r.last_name} ({r.client_id})")
                courtney_lines.append(f"  Phone: {r.phone or '—'} | {r.title}")
                courtney_lines.append(f"  Brief: {DASHBOARD_URL}/clients/{r.client_id}/brief")
                courtney_lines.append("")
        if tomorrow_visits:
            courtney_lines.append("TOMORROW:")
            for r in tomorrow_visits:
                courtney_lines.append(f"  {r.first_name} {r.last_name} ({r.client_id})")
                courtney_lines.append(f"  Phone: {r.phone or '—'} | {r.title}")
                courtney_lines.append(f"  Brief: {DASHBOARD_URL}/clients/{r.client_id}/brief")
                courtney_lines.append("")
        courtney_lines.append(f"Morning Brief: {DASHBOARD_URL}/morning")

        try:
            send_email(NOTIFY_TO, f"Visit Schedule — {today.strftime('%d/%m/%Y')}", "\n".join(courtney_lines))
        except Exception as e:
            logger.error(f"[PreVisitReminder] Courtney schedule email failed: {e}")

    except Exception as e:
        logger.error(f"[PreVisitReminder] Job failed: {e}", exc_info=True)
    finally:
        db.close()
