"""
Health Check v11 — ISP Outage Alert System
Sends alerts via webhook (Slack/Teams), email, and future WhatsApp.
Includes auto-generated call scripts and fault report emails for reception staff.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List

import httpx

from .config import config
from .schemas import OutageAlert, OutageSeverity
from .isp_registry import ISP_SUPPORT_CONTACTS

logger = logging.getLogger("healthcheck.isp_monitor.alerts")


class AlertManager:
    """
    Manages outage notifications with cooldown to prevent alert fatigue.
    Generates auto-formatted fault reports and call scripts.
    """

    def __init__(self):
        # Track last alert time per ISP to enforce cooldown
        self._last_alert: Dict[int, datetime] = {}
        self.http_client: Optional[httpx.AsyncClient] = None

    async def start(self):
        self.http_client = httpx.AsyncClient(timeout=10)

    async def stop(self):
        if self.http_client:
            await self.http_client.aclose()

    # ==========================================================
    # Alert dispatch
    # ==========================================================
    async def send_outage_alert(self, alert: OutageAlert) -> bool:
        """
        Send an outage alert through all configured channels.
        Returns True if at least one channel succeeded.
        """
        # Check cooldown
        if not self._should_alert(alert.outage_id):
            logger.debug(f"Alert cooldown active for outage {alert.outage_id}")
            return False

        self._last_alert[alert.outage_id] = datetime.now(timezone.utc)
        success = False

        # Webhook (Slack / Teams)
        if config.ALERT_WEBHOOK_URL:
            try:
                await self._send_webhook(alert)
                success = True
            except Exception as e:
                logger.error(f"Webhook alert failed: {e}")

        # Email alert (to ZA Support team)
        try:
            await self._send_email_alert(alert)
            success = True
        except Exception as e:
            logger.error(f"Email alert failed: {e}")

        # Future: WhatsApp via Business API
        if config.WHATSAPP_ENABLED and config.WHATSAPP_API_URL:
            try:
                await self._send_whatsapp_alert(alert)
                success = True
            except Exception as e:
                logger.error(f"WhatsApp alert failed: {e}")

        return success

    async def send_restoration_alert(self, alert: OutageAlert) -> bool:
        """Send an ISP restored notification."""
        alert.alert_type = "isp_restored"
        return await self.send_outage_alert(alert)

    def _should_alert(self, outage_id: int) -> bool:
        """Check if enough time has passed since last alert for this outage."""
        last = self._last_alert.get(outage_id)
        if last is None:
            return True
        cooldown = timedelta(minutes=config.ALERT_COOLDOWN_MINS)
        return datetime.now(timezone.utc) - last > cooldown

    # ==========================================================
    # Webhook (Slack / Teams)
    # ==========================================================
    async def _send_webhook(self, alert: OutageAlert):
        """Send formatted alert to Slack/Teams webhook."""
        emoji = {"isp_outage": "🔴", "isp_degraded": "🟡", "isp_restored": "🟢"}.get(
            alert.alert_type, "⚪"
        )

        clients_text = ", ".join(alert.affected_clients) if alert.affected_clients else "None mapped"

        payload = {
            "text": (
                f"{emoji} *ISP {alert.alert_type.replace('isp_', '').upper()}: {alert.isp_name}*\n"
                f"Severity: {alert.severity}\n"
                f"Detected: {alert.started_at.strftime('%Y-%m-%d %H:%M SAST')}\n"
                f"Method: {alert.detection_method}\n"
                f"Affected clients: {clients_text}\n"
                f"{alert.message}"
            )
        }

        await self.http_client.post(config.ALERT_WEBHOOK_URL, json=payload)
        logger.info(f"Webhook alert sent for {alert.isp_name}")

    # ==========================================================
    # Email alert
    # ==========================================================
    async def _send_email_alert(self, alert: OutageAlert):
        """
        Queue an email alert. In production, integrate with your
        existing email system (SendGrid, SES, SMTP, etc.).
        For now, stores the alert payload for the email worker to pick up.
        """
        # This would integrate with your existing Health Check email system
        logger.info(
            f"Email alert queued: {alert.alert_type} for {alert.isp_name} "
            f"affecting {len(alert.affected_clients)} clients"
        )
        # TODO: Push to Redis queue for email worker
        # await redis.rpush("email:alerts", alert.model_dump_json())

    # ==========================================================
    # WhatsApp (future)
    # ==========================================================
    async def _send_whatsapp_alert(self, alert: OutageAlert):
        """Send WhatsApp alert via Business API (future implementation)."""
        logger.info(f"WhatsApp alert would be sent for {alert.isp_name}")

    # ==========================================================
    # Auto-generated reception scripts
    # ==========================================================
    @staticmethod
    def generate_fault_report_email(
        isp_slug: str,
        practice_name: str,
        contact_name: str,
        contact_number: str,
        practice_address: str,
        account_ref: Optional[str],
        outage_start: datetime,
        notes: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate a ready-to-send fault report email for reception staff.
        Returns dict with 'subject' and 'body'.
        """
        isp_info = ISP_SUPPORT_CONTACTS.get(isp_slug, {})
        isp_name = isp_info.get("name", isp_slug.upper())
        isp_email = isp_info.get("email", "[ISP email address]")
        time_str = outage_start.strftime("%H:%M on %d/%m/%Y")

        account_line = f"Account reference: {account_ref}" if account_ref else "Account reference: [please check latest invoice]"

        extra_notes = f"\n\nAdditional information: {notes}" if notes else ""

        subject = f"Urgent: Internet Down at {practice_name}"
        body = (
            f"Dear Sirs\n\n"
            f"I am writing from {practice_name}. Our internet connection has been "
            f"down since approximately {time_str} and we currently have no connection at all.\n\n"
            f"This is affecting our ability to process medical claims, manage patient "
            f"appointments, and access emails. We are a medical practice and this is "
            f"causing significant disruption to patient care.\n\n"
            f"Our details:\n"
            f"- Practice name: {practice_name}\n"
            f"- Contact person: {contact_name}\n"
            f"- Contact number: {contact_number}\n"
            f"- Address: {practice_address}\n"
            f"- {account_line}\n\n"
            f"Our IT support has confirmed that all equipment on our side is powered on "
            f"and the issue is with the internet line itself."
            f"{extra_notes}\n\n"
            f"Please urgently investigate and provide us with:\n"
            f"1. A fault reference number\n"
            f"2. An estimated time for the connection to be restored\n\n"
            f"This is a medical practice. The outage is directly affecting patient services "
            f"and we need this resolved as a matter of urgency.\n\n"
            f"Kind regards\n"
            f"{contact_name}\n"
            f"{practice_name}"
        )

        return {
            "to": isp_email,
            "subject": subject,
            "body": body,
        }

    @staticmethod
    def generate_call_script(
        isp_slug: str,
        practice_name: str,
        contact_name: str,
        account_ref: Optional[str],
        practice_address: str,
        outage_start: datetime,
    ) -> str:
        """
        Generate a plain-language call script for non-technical reception staff.
        Written so it can be read almost word-for-word.
        """
        isp_info = ISP_SUPPORT_CONTACTS.get(isp_slug, {})
        isp_name = isp_info.get("name", isp_slug.upper())
        isp_phone = isp_info.get("phone", "[check ISP phone number]")
        time_str = outage_start.strftime("%H:%M this morning (%d/%m/%Y)")

        account_line = f"Account number: {account_ref}" if account_ref else "Account number: [check on the latest invoice or ask Courtney]"

        script = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CALL SCRIPT — REPORT INTERNET OUTAGE
For: {contact_name} at {practice_name}
Call: {isp_name} on {isp_phone}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WHEN THEY ANSWER, SAY:

"Hi, my name is {contact_name}. I am calling from
{practice_name}. I need to report that our internet
is completely down."

WHEN THEY ASK FOR ACCOUNT DETAILS:

- Account name: {practice_name}
- {account_line}
- Address: {practice_address}

WHEN THEY ASK WHAT THE PROBLEM IS, SAY:

"Our internet went down at about {time_str}. We have
no connection at all. We cannot get online from any
device in the practice. Our IT support has checked
all the equipment on our side and confirmed the
problem is with the internet line, not our equipment."

IF THEY ASK YOU TO RESTART EQUIPMENT, SAY:

"Our IT support has already checked everything on our
side and confirmed the issue is not with our devices.
Please can you check the line from your side."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEFORE YOU HANG UP, MAKE SURE YOU GET:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. FAULT REFERENCE NUMBER — write this down
2. ESTIMATED TIME for when it will be fixed
3. NAME of the person you spoke to

IF THEY CANNOT GIVE YOU A TIME, SAY:

"This is a medical practice and we cannot process
patient claims or manage appointments without
internet. Please can this be treated as urgent."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AFTER THE CALL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Write down:
- Reference number: ___________________
- ETA to fix: ___________________
- Person spoken to: ___________________
- Time of call: ___________________

Send the fault email (already prepared) and add
the reference number to the email as a reply.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        return script.strip()
