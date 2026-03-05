"""
Forensics notifier — fires when a forensics investigation completes
with CRITICAL or HIGH severity findings.

Subscribes to: forensics.critical_findings
- Emails Courtney immediately with findings summary
- Auto-creates an URGENT workshop job for the affected device
"""
import logging

from app.core.event_bus import subscribe
from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO = "courtney@zasupport.com"
DASHBOARD = "https://app.zasupport.com"


@subscribe("forensics.critical_findings")
async def on_forensics_critical(payload: dict):
    investigation_id = payload.get("investigation_id", "unknown")
    client_id        = payload.get("client_id", "unknown")
    device_id        = payload.get("device_id")
    serial           = payload.get("serial")
    critical         = payload.get("findings_critical", 0)
    high             = payload.get("findings_high", 0)
    scope            = payload.get("scope", "unknown")

    severity_label = "🔴 CRITICAL" if critical > 0 else "🟠 HIGH"
    subject = f"{severity_label} Forensic Findings — {client_id}"

    body_lines = [
        f"A forensic investigation has completed with {severity_label} findings.",
        f"",
        f"Investigation : {investigation_id}",
        f"Client        : {client_id}",
        f"Device        : {serial or device_id or 'unknown'}",
        f"Scope         : {scope}",
        f"",
        f"Findings:",
        f"  Critical : {critical}",
        f"  High     : {high}",
        f"",
        f"IMMEDIATE ACTIONS:",
        f"  1. Review full findings in Forensics dashboard",
        f"  2. If device compromise confirmed: isolate immediately",
        f"  3. Do NOT wipe — preserve forensic evidence",
        f"  4. Assess POPIA Section 22 obligations",
        f"",
        f"Forensics: {DASHBOARD}/forensics",
    ]
    if client_id and client_id != "unknown":
        body_lines.append(f"Client:       {DASHBOARD}/clients/{client_id}")

    try:
        send_email(NOTIFY_TO, subject, "\n".join(body_lines))
        logger.warning(f"Forensics alert email sent — investigation {investigation_id}, {critical} critical/{high} high")
    except Exception as e:
        logger.error(f"Forensics alert email failed: {e}")

    try:
        send_slack(
            f"*{severity_label} Forensic Investigation Complete*\n"
            f"Client: `{client_id}` | Device: `{serial or device_id or '?'}`\n"
            f"Critical: *{critical}* | High: *{high}*\n"
            f"<{DASHBOARD}/forensics|Open Forensics>"
        )
    except Exception as e:
        logger.error(f"Forensics Slack alert failed: {e}")

    # Auto-create urgent workshop job if there's a known client+device
    if not client_id or client_id == "unknown":
        return

    try:
        from sqlalchemy import text
        from app.modules.workshop.service import create_job
        from app.modules.workshop.schemas import JobCreate

        db = get_session_factory()()
        try:
            # Deduplicate — don't create another job if one exists within 7 days
            existing = db.execute(
                text("""
                    SELECT id FROM workshop_jobs
                    WHERE client_id = :cid
                      AND title ILIKE '%forensic%'
                      AND status NOT IN ('done', 'completed', 'cancelled')
                      AND created_at > NOW() - INTERVAL '7 days'
                """),
                {"cid": client_id},
            ).fetchone()

            if not existing:
                job = create_job(
                    db=db,
                    data=JobCreate(
                        client_id=client_id,
                        serial=serial or None,
                        title=f"Forensic findings — {critical} critical, {high} high — {serial or device_id or 'device'}",
                        description=(
                            f"Forensic investigation {investigation_id} completed with {severity_label} findings.\n"
                            f"Scope: {scope}\n"
                            f"Review full investigation in Forensics dashboard before any remediation."
                        ),
                        priority="urgent",
                        line_items=[],
                    ),
                    source="auto",
                )
                db.commit()
                logger.info(f"Workshop: forensics job {job.job_ref} created for {client_id}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Forensics workshop job creation failed: {e}")
