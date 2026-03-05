"""
SLA Report Scheduler — runs on the 1st of each month at 06:00.
Finds all clients with status='sla', generates their CyberPulse PDF from
the latest diagnostic snapshot, and emails it to them automatically.
"""
import json
import logging
from datetime import datetime

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email_with_attachment, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO    = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com"


def run_sla_monthly_reports():
    """
    Monthly CyberPulse delivery to all SLA clients.
    Skips clients with no diagnostic snapshot on record.
    """
    from app.modules.reports.generator import generate_cyberpulse_pdf

    db = get_session_factory()()
    delivered = []
    failed    = []

    try:
        # All SLA clients
        sla_clients = db.execute(
            text("SELECT * FROM clients WHERE status = 'sla' ORDER BY last_name"),
        ).fetchall()

        if not sla_clients:
            logger.info("[SLAReports] No SLA clients found.")
            return

        month_str = datetime.now().strftime("%B %Y")
        logger.info(f"[SLAReports] Generating monthly reports for {len(sla_clients)} SLA clients — {month_str}")

        for c in sla_clients:
            client_id   = c.client_id
            client_name = f"{c.first_name} {c.last_name}".strip()
            client_email = c.email

            if not client_email:
                logger.warning(f"[SLAReports] No email for {client_id} — skipping")
                failed.append(f"{client_name} (no email)")
                continue

            # Latest snapshot for this client
            snap = db.execute(
                text("""
                    SELECT s.*, d.hostname
                    FROM diagnostic_snapshots s
                    JOIN client_devices d ON d.serial = s.serial
                    WHERE d.client_id = :cid
                    ORDER BY s.scan_date DESC LIMIT 1
                """),
                {"cid": client_id},
            ).fetchone()

            if not snap:
                logger.warning(f"[SLAReports] No snapshot for {client_id} — skipping")
                failed.append(f"{client_name} (no diagnostic data)")
                continue

            raw_payload = json.loads(snap.raw_json) if isinstance(snap.raw_json, str) else (snap.raw_json or {})
            scan_date_str = snap.scan_date.strftime("%d/%m/%Y %H:%M") if snap.scan_date else None

            try:
                pdf_bytes = generate_cyberpulse_pdf(
                    client_name=client_name,
                    client_id=client_id,
                    hostname=snap.hostname or snap.serial,
                    serial=snap.serial,
                    payload=raw_payload,
                    scan_date=snap.scan_date,
                    reason=f"Monthly SLA CyberPulse Assessment — {month_str}",
                )
            except Exception as e:
                logger.error(f"[SLAReports] PDF generation failed for {client_id}: {e}")
                failed.append(f"{client_name} (PDF error)")
                continue

            date_for_file = datetime.now().strftime("%d %m %Y")
            filename = f"ZA Support CyberPulse {client_name} {date_for_file}.pdf"

            subject = f"Your Monthly ZA Support CyberPulse Report — {month_str}"
            body = "\n".join([
                f"Hi {c.first_name},",
                f"",
                f"Please find your monthly CyberPulse Assessment attached.",
                f"",
                f"This report is part of your ZA Support SLA service and covers",
                f"the current health, security posture, and backup status of your Mac.",
                f"",
                f"Latest scan: {scan_date_str or 'on file'}",
                f"",
                f"Courtney reviews your system data regularly. If anything in this",
                f"report requires attention, we'll be in touch — otherwise, all is well.",
                f"",
                f"Questions? Reply to this email or call 064 529 5863.",
                f"",
                f"ZA Support | Practice IT. Perfected.",
                f"admin@zasupport.com | zasupport.com",
            ])

            success = send_email_with_attachment(
                to=client_email,
                subject=subject,
                body=body,
                attachment=pdf_bytes,
                filename=filename,
            )

            if success:
                delivered.append(client_name)
                logger.info(f"[SLAReports] Delivered to {client_email} ({client_id})")
            else:
                failed.append(f"{client_name} (send failed)")

        # Notify Courtney of batch results
        summary_lines = [
            f"*Monthly SLA Reports — {month_str}*",
            f"Delivered: {len(delivered)} | Failed: {len(failed)}",
        ]
        if delivered:
            summary_lines.append("Sent to: " + ", ".join(delivered))
        if failed:
            summary_lines.append("Failed: " + ", ".join(failed))
        summary_lines.append(f"<{DASHBOARD_URL}/clients|View Clients>")

        try:
            send_slack("\n".join(summary_lines))
        except Exception as e:
            logger.error(f"[SLAReports] Slack summary failed: {e}")

    except Exception as e:
        logger.error(f"[SLAReports] Batch job failed: {e}", exc_info=True)
    finally:
        db.close()
