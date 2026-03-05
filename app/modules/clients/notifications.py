"""
Client event subscribers — fires on client.created via event bus.
Imported by __init__.py so subscriptions register at startup.
"""
import logging
from app.core.event_bus import subscribe
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO = "courtney@zasupport.com"
NOTIFY_CC = "admin@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com/clients"


@subscribe("client.created")
async def on_client_created(payload: dict):
    """
    Fires when a new client submits the Formbricks intake form.
    Notifies Courtney + admin via email and Slack.
    """
    client_id    = payload.get("client_id", "unknown")
    email        = payload.get("email", "")
    has_business = payload.get("has_business", False)
    urgency      = payload.get("urgency_level", "")

    urgent_flag   = urgency and urgency.lower().startswith("urgent")
    business_flag = has_business

    prefix = "🚨 URGENT — " if urgent_flag else ""
    subject = f"{prefix}New Client: {client_id}"

    body_lines = [
        f"A new client has submitted the ZA Support onboarding form.",
        f"",
        f"Client ID : {client_id}",
        f"Email     : {email}",
        f"Urgency   : {urgency or 'Not specified'}",
        f"Business  : {'YES — offer SME Health Check' if business_flag else 'No'}",
        f"",
        f"Dashboard : {DASHBOARD_URL}/{client_id}",
        f"",
    ]

    if urgent_flag:
        body_lines.insert(0, "⚠️  CLIENT MARKED THIS AS URGENT — action today.\n")

    if business_flag:
        body_lines.append("ACTION: Book SME Health Check conversation for their business.\n")

    body_lines += [
        "Onboarding checklist has been auto-created in the dashboard.",
        "Next step: schedule Health Check Scout diagnostic visit.",
    ]

    body = "\n".join(body_lines)

    try:
        send_email(NOTIFY_TO, subject, body)
        logger.info(f"client.created notification sent for {client_id}")
    except Exception as e:
        logger.error(f"client.created email failed for {client_id}: {e}")

    try:
        urgency_tag = " 🚨 *URGENT*" if urgent_flag else ""
        biz_tag = " | 💼 Has business" if business_flag else ""
        slack_msg = (
            f"*New Client Onboarded*{urgency_tag}{biz_tag}\n"
            f"Client: `{client_id}` | Email: {email}\n"
            f"<{DASHBOARD_URL}/{client_id}|Open in Dashboard>"
        )
        send_slack(slack_msg)
    except Exception as e:
        logger.error(f"client.created Slack notification failed: {e}")
