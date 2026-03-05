"""
Report Delivery — auto-delivers CyberPulse PDF to the client's email
when a CRITICAL or HIGH diagnostic arrives.

Subscribes to diagnostics.upload_received.
Registered by automation_scheduler import.
"""
import logging
from datetime import datetime

from app.core.event_bus import subscribe
from app.core.database import get_session_factory
from app.services.notification_engine import send_email_with_attachment, send_slack

logger = logging.getLogger(__name__)

COURTNEY_EMAIL = "courtney@zasupport.com"
DASHBOARD_URL  = "https://app.zasupport.com"


@subscribe("diagnostics.upload_received")
async def auto_deliver_report(payload: dict):
    """
    On CRITICAL or HIGH risk: generate CyberPulse PDF and email it directly
    to the client. Also notify Courtney that the report was sent.
    """
    risk_level  = (payload.get("risk_level") or "").upper()
    client_id   = payload.get("client_id")
    serial      = payload.get("serial", "unknown")
    snapshot_id = payload.get("snapshot_id")

    if not client_id or risk_level not in ("CRITICAL", "HIGH"):
        return

    try:
        from app.modules.clients.models import Client
        from app.modules.reports.generator import generate_cyberpulse_pdf

        db = get_session_factory()()
        try:
            client = db.query(Client).filter(Client.client_id == client_id).first()
            if not client or not client.email:
                logger.warning(f"report_delivery: no client or email for {client_id}")
                return

            client_name = f"{client.first_name} {client.last_name}"

            # Get the latest snapshot raw data for the serial
            from sqlalchemy import text
            snap_row = db.execute(
                text("""
                    SELECT raw_json, scan_date, reason, version
                    FROM diagnostic_snapshots
                    WHERE serial = :serial
                    ORDER BY scan_date DESC LIMIT 1
                """),
                {"serial": serial},
            ).fetchone()

            if not snap_row:
                logger.warning(f"report_delivery: no snapshot found for serial {serial}")
                return

            import json
            raw_payload = json.loads(snap_row.raw_json) if isinstance(snap_row.raw_json, str) else (snap_row.raw_json or {})

            # Generate PDF
            pdf_bytes = generate_cyberpulse_pdf(
                client_name=client_name,
                client_id=client_id,
                hostname=raw_payload.get("system", {}).get("hostname", serial),
                serial=serial,
                payload=raw_payload,
                scan_date=snap_row.scan_date,
                reason=snap_row.reason or "Routine diagnostic",
            )

            scan_date_str = snap_row.scan_date.strftime("%d %m %Y") if snap_row.scan_date else datetime.today().strftime("%d %m %Y")
            filename = f"ZA Support CyberPulse {client_name} {scan_date_str}.pdf"

            # Email to client
            subject = f"Your ZA Support CyberPulse Assessment — {client_name}"
            body = "\n".join([
                f"Dear {client.first_name},",
                f"",
                f"Please find your CyberPulse Assessment attached.",
                f"",
                f"This report summarises the health and security status of your Mac,",
                f"including findings and recommended actions.",
                f"",
                f"Courtney will be in touch to walk through the results with you.",
                f"",
                f"ZA Support | Practice IT. Perfected.",
                f"admin@zasupport.com | 064 529 5863",
                f"zasupport.com",
            ])

            delivered = send_email_with_attachment(
                to=client.email,
                subject=subject,
                body=body,
                attachment=pdf_bytes,
                filename=filename,
            )

            if delivered:
                logger.info(f"CyberPulse report auto-delivered to {client.email} ({client_id})")
                # Notify Courtney
                send_slack(
                    f"CyberPulse report auto-delivered to *{client_name}* ({client.email}) | "
                    f"Risk: *{risk_level}* | <{DASHBOARD_URL}/clients/{client_id}|View Client>"
                )
            else:
                logger.error(f"report_delivery: failed to deliver to {client.email}")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"report_delivery failed for {client_id}: {e}", exc_info=True)
