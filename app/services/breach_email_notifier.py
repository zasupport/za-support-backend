"""
Breach scanner email notifier — fires when the breach scanner confirms
critical or high-severity malicious findings on a client device.

Subscribes to: breach.critical_found
Emitted by:    app/modules/breach_scanner/router.py (submit_agent_report)
"""
import logging

from app.core.event_bus import subscribe
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO  = "courtney@zasupport.com"
DASHBOARD  = "https://app.zasupport.com"


@subscribe("breach.critical_found")
async def on_breach_critical(payload: dict):
    """
    Alert Courtney immediately when the breach scanner confirms
    CRITICAL or HIGH findings on a client device.
    """
    client_id          = payload.get("client_id", "unknown")
    device_id          = payload.get("device_id", "unknown")
    critical_findings  = payload.get("critical_findings", 0)
    high_findings      = payload.get("high_findings", 0)
    confirmed_malicious = payload.get("confirmed_malicious", 0)
    scan_id            = payload.get("scan_id", "")
    scanners_run       = payload.get("scanners_run", [])

    severity_label = "🔴 CRITICAL" if critical_findings > 0 else "🟠 HIGH"
    subject = f"{severity_label} Breach Scanner Alert — {client_id}"

    body_lines = [
        f"The Breach Scanner has detected confirmed or likely malicious findings.",
        f"",
        f"Client/Device : {client_id} / {device_id}",
        f"Scan ID       : {scan_id}",
        f"",
        f"Findings:",
        f"  Critical      : {critical_findings}",
        f"  High          : {high_findings}",
        f"  Confirmed mal : {confirmed_malicious}",
        f"",
    ]

    if scanners_run:
        body_lines.append(f"Scanners run: {', '.join(scanners_run)}")
        body_lines.append("")

    body_lines += [
        f"IMMEDIATE ACTIONS:",
        f"  1. Review findings in dashboard breach scanner section",
        f"  2. If confirmed: isolate device from network immediately",
        f"  3. Do NOT wipe — preserve evidence for forensic review",
        f"  4. Assess personal data exposure for POPIA Section 22 obligations",
        f"",
        f"Dashboard: {DASHBOARD}/breach-scanner",
    ]

    if client_id and client_id != "unknown":
        body_lines.append(f"Client:    {DASHBOARD}/clients/{client_id}")

    body = "\n".join(body_lines)

    try:
        send_email(NOTIFY_TO, subject, body)
        logger.warning(f"Breach alert email sent for {client_id} — {critical_findings} critical, {high_findings} high")
    except Exception as e:
        logger.error(f"Breach alert email failed: {e}")

    try:
        slack_lines = [
            f"*{severity_label} Breach Scanner Alert*",
            f"Client: `{client_id}` | Device: `{device_id}`",
            f"Critical: *{critical_findings}* | High: *{high_findings}* | Confirmed malicious: *{confirmed_malicious}*",
            f"<{DASHBOARD}/breach-scanner|Open Breach Scanner>",
        ]
        send_slack("\n".join(slack_lines))
    except Exception as e:
        logger.error(f"Breach alert Slack failed: {e}")
