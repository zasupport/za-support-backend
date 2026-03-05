"""
ISP Outage Notifier — subscribes to isp.outage_detected events.
Sends Courtney an immediate Slack + email alert when a client's ISP goes down.
Registered in automation_scheduler.py startup.
"""
import logging
from app.core.event_bus import subscribe
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO    = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com/isp"

# Map ISP names to known clients so alerts mention who is affected
ISP_CLIENT_MAP = {
    "stem":    ["Dr Evan Shoul"],
    "x-dsl":   ["Dr Evan Shoul"],
    "ntt":     ["Charles Chemel"],
    "ntt data": ["Charles Chemel"],
}


def _clients_for_isp(isp_name: str) -> list[str]:
    name_lower = (isp_name or "").lower()
    for key, clients in ISP_CLIENT_MAP.items():
        if key in name_lower:
            return clients
    return []


@subscribe("isp.outage_detected")
async def on_isp_outage(payload: dict):
    """
    Fires when ISP monitor confirms an outage.
    1. Alerts Courtney via email + Slack.
    2. Emails affected clients directly so they know it's a known issue.
    """
    isp_name    = payload.get("isp_name", "Unknown ISP")
    status      = payload.get("status", "outage")
    confidence  = payload.get("confidence", 0)
    region      = payload.get("region", "SA")
    detected_at = payload.get("detected_at", "")

    affected_client_names = _clients_for_isp(isp_name)
    client_note = f"Affected clients: {', '.join(affected_client_names)}" if affected_client_names else "No known clients on this ISP"

    # Alert Courtney
    subject = f"ISP Outage Detected — {isp_name} ({status.upper()})"
    body = "\n".join([
        f"ZA Support ISP Monitor has detected an outage.",
        f"",
        f"ISP        : {isp_name}",
        f"Status     : {status.upper()}",
        f"Confidence : {confidence}%",
        f"Region     : {region}",
        f"Detected   : {detected_at}",
        f"",
        client_note,
        f"",
        f"ISP Status Dashboard : {DASHBOARD_URL}",
    ])
    try:
        send_email(NOTIFY_TO, subject, body)
        logger.info(f"ISP outage email sent: {isp_name} ({status})")
    except Exception as e:
        logger.error(f"ISP outage email failed for {isp_name}: {e}")

    try:
        client_tag = f"\nAffected: {', '.join(affected_client_names)}" if affected_client_names else ""
        send_slack(
            f"*ISP Outage* — *{isp_name}* | Status: `{status.upper()}` | Confidence: {confidence}%"
            f"{client_tag}\n<{DASHBOARD_URL}|View ISP Status>"
        )
    except Exception as e:
        logger.error(f"ISP outage Slack alert failed for {isp_name}: {e}")

    # Email affected clients directly
    if affected_client_names:
        try:
            from app.core.database import get_session_factory
            from app.modules.clients.models import Client
            db = get_session_factory()()
            try:
                # Find clients whose ISP matches
                isp_key = isp_name.lower()
                clients = db.execute(
                    __import__('sqlalchemy').text(
                        "SELECT first_name, last_name, email FROM client_setup s "
                        "JOIN clients c ON c.client_id = s.client_id "
                        "WHERE LOWER(s.isp) LIKE :isp AND c.status != 'inactive'"
                    ),
                    {"isp": f"%{isp_key.split()[0]}%"},
                ).fetchall()

                for c in clients:
                    if not c.email:
                        continue
                    client_subject = f"Internet Connectivity Issue — {isp_name}"
                    client_body = "\n".join([
                        f"Hi {c.first_name},",
                        f"",
                        f"Our monitoring system has detected an outage affecting {isp_name}.",
                        f"",
                        f"If you're experiencing internet connectivity issues right now,",
                        f"this is a known problem with your ISP — not your equipment.",
                        f"",
                        f"What to do:",
                        f"  • No action needed on your end",
                        f"  • ISPs typically resolve outages within 1-4 hours",
                        f"  • If it persists beyond 4 hours, contact your ISP directly",
                        f"",
                        f"We'll continue monitoring and will notify you when service is restored.",
                        f"",
                        f"ZA Support | Practice IT. Perfected.",
                        f"admin@zasupport.com | 064 529 5863",
                    ])
                    try:
                        send_email(c.email, client_subject, client_body)
                        logger.info(f"ISP outage client notification sent to {c.email}")
                    except Exception as e:
                        logger.error(f"ISP client email failed for {c.email}: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"ISP client notification lookup failed: {e}")


@subscribe("isp.outage_resolved")
async def on_isp_resolved(payload: dict):
    """Fires when ISP monitor marks outage as resolved."""
    isp_name   = payload.get("isp_name", "Unknown ISP")
    duration   = payload.get("duration_minutes")
    resolved_at = payload.get("resolved_at", "")

    duration_note = f" (down for {duration} min)" if duration else ""

    try:
        slack_msg = f"ISP *{isp_name}* is back online{duration_note}. <{DASHBOARD_URL}|View ISP Status>"
        send_slack(slack_msg)
        logger.info(f"ISP resolved notification sent: {isp_name}")
    except Exception as e:
        logger.error(f"ISP resolved Slack notification failed: {e}")
