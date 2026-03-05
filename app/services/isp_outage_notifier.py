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
    Expected payload keys: isp_name, status, confidence, region, detected_at
    """
    isp_name    = payload.get("isp_name", "Unknown ISP")
    status      = payload.get("status", "outage")
    confidence  = payload.get("confidence", 0)
    region      = payload.get("region", "SA")
    detected_at = payload.get("detected_at", "")

    affected_clients = _clients_for_isp(isp_name)
    client_note = f"Affected clients: {', '.join(affected_clients)}" if affected_clients else "No known clients on this ISP"

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
        client_tag = f"\nAffected: {', '.join(affected_clients)}" if affected_clients else ""
        slack_msg = (
            f"*ISP Outage* — *{isp_name}* | Status: `{status.upper()}` | Confidence: {confidence}%"
            f"{client_tag}\n"
            f"<{DASHBOARD_URL}|View ISP Status>"
        )
        send_slack(slack_msg)
    except Exception as e:
        logger.error(f"ISP outage Slack alert failed for {isp_name}: {e}")


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
