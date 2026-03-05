"""
Post-Visit Follow-Up — fires when a workshop job is marked 'done'.
Emails the client a thank-you + visit summary with report download link.
Registered by automation_scheduler import.
"""
import logging
from app.core.event_bus import subscribe
from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://app.zasupport.com"
NOTIFY_TO     = "courtney@zasupport.com"


@subscribe("workshop.job_completed")
async def on_job_completed(payload: dict):
    """Email client a visit summary when their workshop job is marked done."""
    client_id = payload.get("client_id")
    job_ref   = payload.get("job_ref", "")
    title     = payload.get("title", "Visit")
    notes     = payload.get("notes") or ""

    if not client_id:
        return

    try:
        from app.modules.clients.models import Client
        db = get_session_factory()()
        try:
            client = db.query(Client).filter(Client.client_id == client_id).first()
            if not client or not client.email:
                logger.warning(f"[PostVisit] No client/email for {client_id}")
                return

            report_url  = f"{DASHBOARD_URL}/api/reports/{client_id}"
            client_name = f"{client.first_name} {client.last_name}"

            subject = f"ZA Support — Visit Complete: {title}"
            body_lines = [
                f"Hi {client.first_name},",
                f"",
                f"Thank you for having us — your visit is complete.",
                f"",
                f"Job Reference : {job_ref}",
                f"Summary       : {title}",
            ]
            if notes:
                body_lines += [f"", f"Notes from today's visit:", f"{notes}"]

            body_lines += [
                f"",
                f"Your CyberPulse Assessment report (updated after today's work) is",
                f"available to download at any time:",
                f"  {report_url}",
                f"",
                f"If anything feels off in the coming days, reply to this email",
                f"or call Courtney on 064 529 5863 — we're always here.",
                f"",
                f"ZA Support | Practice IT. Perfected.",
                f"admin@zasupport.com | 064 529 5863 | zasupport.com",
            ]

            send_email(client.email, subject, "\n".join(body_lines))
            logger.info(f"[PostVisit] Follow-up sent to {client.email} ({client_id}) for {job_ref}")

            send_slack(
                f"Visit complete: *{job_ref}* — *{client_name}* | Follow-up email sent to {client.email}"
            )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[PostVisit] Failed for {client_id} / {job_ref}: {e}", exc_info=True)
