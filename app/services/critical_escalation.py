"""
Critical Escalation — daily job at 09:00.
Re-alerts Courtney if any CRITICAL-priority workshop job is still 'open'
48+ hours after creation with no status change.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO     = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com"
ESCALATE_HOURS = 48


def run_critical_escalation():
    """Find CRITICAL open workshop jobs older than 48h and re-alert."""
    db = get_session_factory()()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=ESCALATE_HOURS)

        rows = db.execute(
            text("""
                SELECT
                    j.job_ref, j.title, j.client_id, j.serial, j.created_at, j.status, j.priority,
                    EXTRACT(HOUR FROM NOW() - j.created_at)::int AS hours_open,
                    c.first_name, c.last_name, c.email, c.phone
                FROM workshop_jobs j
                LEFT JOIN clients c ON c.client_id = j.client_id
                WHERE j.priority = 'urgent'
                  AND j.status = 'open'
                  AND j.created_at < :cutoff
                ORDER BY j.created_at ASC
            """),
            {"cutoff": cutoff},
        ).fetchall()

        if not rows:
            logger.info("[CriticalEscalation] No unactioned critical jobs found.")
            return

        logger.warning(f"[CriticalEscalation] {len(rows)} unactioned CRITICAL job(s) — escalating.")

        lines = [
            f"ESCALATION — Unactioned Critical Workshop Jobs",
            f"These jobs have been open for {ESCALATE_HOURS}+ hours with no status change:",
            f"",
        ]
        slack_lines = [f"*ESCALATION: {len(rows)} Unactioned Critical Job(s)*"]

        for r in rows:
            created = r.created_at.strftime("%d/%m/%Y %H:%M") if r.created_at else "unknown"
            lines += [
                f"Job      : {r.job_ref} — {r.title}",
                f"Client   : {r.first_name} {r.last_name} ({r.client_id})",
                f"Phone    : {r.phone or '—'}",
                f"Open for : {r.hours_open}h",
                f"Created  : {created}",
                f"Dashboard: {DASHBOARD_URL}/workshop",
                f"",
            ]
            slack_lines.append(
                f"\n• `{r.job_ref}` — {r.title} | *{r.first_name} {r.last_name}* | {r.hours_open}h open"
            )

        slack_lines.append(f"\n<{DASHBOARD_URL}/workshop|Open Workshop Board>")

        try:
            send_email(NOTIFY_TO, f"ESCALATION: {len(rows)} Critical Job(s) Unactioned ({ESCALATE_HOURS}h+)", "\n".join(lines))
            logger.info(f"[CriticalEscalation] Escalation email sent: {len(rows)} jobs")
        except Exception as e:
            logger.error(f"[CriticalEscalation] Email failed: {e}")

        try:
            send_slack("\n".join(slack_lines))
        except Exception as e:
            logger.error(f"[CriticalEscalation] Slack failed: {e}")

    except Exception as e:
        logger.error(f"[CriticalEscalation] Job failed: {e}", exc_info=True)
    finally:
        db.close()
