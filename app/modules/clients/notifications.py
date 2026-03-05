"""
Client event subscribers — fires on client.created and diagnostics.upload_received.
Imported by __init__.py so subscriptions register at startup.
"""
import logging
from app.core.event_bus import subscribe
from app.core.database import get_session_factory
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


@subscribe("diagnostics.upload_received")
async def on_diagnostic_received(payload: dict):
    """
    1. Auto-progress client status new → active when Scout diagnostic arrives.
    2. Notify Courtney immediately if risk_level is CRITICAL or HIGH.
    """
    from app.modules.clients.models import Client
    client_id  = payload.get("client_id")
    serial     = payload.get("serial", "unknown")
    risk_level = payload.get("risk_level", "")
    snapshot_id = payload.get("snapshot_id")

    if not client_id:
        return

    try:
        db = get_session_factory()()
        try:
            client = db.query(Client).filter(Client.client_id == client_id).first()
            if client and client.status == "new":
                client.status = "active"
                db.commit()
                logger.info(f"Client {client_id}: new → active (Scout diagnostic received)")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Status auto-progression failed for {client_id}: {e}")

    # Alert Courtney on CRITICAL or HIGH risk findings
    if risk_level and risk_level.upper() in ("CRITICAL", "HIGH"):
        recommendations = payload.get("recommendations", [])
        rec_count = len(recommendations)
        report_url = f"https://app.zasupport.com/api/reports/{client_id}"
        if snapshot_id:
            report_url += f"?snapshot_id={snapshot_id}"
        client_url = f"{DASHBOARD_URL}/{client_id}"

        subject = f"{'🚨 CRITICAL' if risk_level.upper() == 'CRITICAL' else '⚠️ HIGH'} Risk Diagnostic — {client_id}"
        body_lines = [
            f"Scout diagnostic uploaded for client: {client_id}",
            f"Device: {serial}",
            f"Risk Level: {risk_level.upper()}",
            f"Recommendations: {rec_count}",
            f"",
        ]
        if recommendations:
            body_lines.append("Top findings:")
            for r in recommendations[:5]:
                sev = r.get("severity", "")
                title = r.get("title", r.get("recommendation", str(r)))
                body_lines.append(f"  [{sev}] {title}")
            body_lines.append("")

        body_lines += [
            f"Client dashboard : {client_url}",
            f"Download report  : {report_url}",
        ]
        body = "\n".join(body_lines)

        try:
            send_email(NOTIFY_TO, subject, body)
            logger.info(f"High-risk diagnostic alert sent for {client_id} ({risk_level})")
        except Exception as e:
            logger.error(f"High-risk diagnostic email failed for {client_id}: {e}")

        try:
            level_tag = "*🚨 CRITICAL*" if risk_level.upper() == "CRITICAL" else "*⚠️ HIGH*"
            slack_lines = [
                f"{level_tag} Diagnostic — `{client_id}` | Device: `{serial}`",
                f"Risk: *{risk_level.upper()}* | {rec_count} recommendation(s)",
                f"<{client_url}|View Client> | <{report_url}|Download Report>",
            ]
            send_slack("\n".join(slack_lines))
        except Exception as e:
            logger.error(f"High-risk diagnostic Slack alert failed for {client_id}: {e}")
