"""
Notification Service — generates POPIA Section 22 breach notifications
when confirmed compromise involves personal data, and dispatches alerts
via webhook / email.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .config import ScannerConfig
from .models import (
    CorroborationStatus,
    FindingCategory,
    FindingResponse,
    FindingSeverity,
    ScanSessionResponse,
)

logger = logging.getLogger(__name__)

# Categories that may involve personal data exposure
PERSONAL_DATA_CATEGORIES = {
    FindingCategory.DATA_EXFILTRATION,
    FindingCategory.PHISHING,
    FindingCategory.MALWARE,
    FindingCategory.SUSPICIOUS_EMAIL,
    FindingCategory.REMOTE_ACCESS,
    FindingCategory.ROOTKIT,
}


class NotificationService:
    """Alert dispatch and POPIA notification generation."""

    def __init__(self) -> None:
        self._webhook_url = ScannerConfig.ALERT_WEBHOOK_URL
        self._last_alert: dict[str, datetime] = {}  # device_id -> last alert time

    async def process_scan_results(
        self,
        session: ScanSessionResponse,
        findings: list[FindingResponse],
        client_name: str = "Client",
        device_hostname: str = "Unknown Device",
    ) -> None:
        """
        Evaluate scan results and dispatch alerts if warranted.
        Also generates POPIA notification if personal data is at risk.
        """
        # Filter to actionable findings
        critical_findings = [
            f for f in findings
            if f.severity in (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
            and f.corroboration_status in (
                CorroborationStatus.CONFIRMED_MALICIOUS,
                CorroborationStatus.LIKELY_MALICIOUS,
            )
            and not f.is_false_positive
        ]

        if not critical_findings:
            return

        # Check cooldown
        device_key = str(session.device_id)
        if self._is_in_cooldown(device_key):
            logger.info("Alert cooldown active for device %s — skipping", device_key)
            return

        # Dispatch webhook alert
        if self._webhook_url:
            await self._send_webhook_alert(
                session, critical_findings, client_name, device_hostname
            )

        # Check if POPIA notification is needed
        popia_findings = [
            f for f in critical_findings if f.category in PERSONAL_DATA_CATEGORIES
        ]
        if popia_findings:
            notification = self.generate_popia_notification(
                client_name, device_hostname, popia_findings
            )
            logger.warning(
                "POPIA Section 22 notification triggered for %s: %d findings",
                client_name,
                len(popia_findings),
            )
            # Store notification (caller handles persistence)

        self._last_alert[device_key] = datetime.now(timezone.utc)

    async def _send_webhook_alert(
        self,
        session: ScanSessionResponse,
        findings: list[FindingResponse],
        client_name: str,
        hostname: str,
    ) -> None:
        """Send alert to Slack/Teams webhook."""
        severity_emoji = {
            FindingSeverity.CRITICAL: "🔴",
            FindingSeverity.HIGH: "🟠",
            FindingSeverity.MEDIUM: "🟡",
            FindingSeverity.LOW: "🟢",
        }

        finding_lines = []
        for f in findings[:10]:
            emoji = severity_emoji.get(f.severity, "⚪")
            finding_lines.append(
                f"{emoji} *{f.severity.value.upper()}*: {f.title} "
                f"({f.corroboration_status.value})"
            )

        text = (
            f"🚨 *Compromised Data Scanner Alert*\n\n"
            f"*Client:* {client_name}\n"
            f"*Device:* {hostname}\n"
            f"*Scan ID:* {session.id}\n"
            f"*Critical/High Findings:* {len(findings)}\n"
            f"*Confirmed Malicious:* {session.confirmed_malicious}\n\n"
            f"*Top Findings:*\n" + "\n".join(finding_lines)
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self._webhook_url,
                    json={"text": text},
                )
                if resp.status_code not in (200, 204):
                    logger.error("Webhook alert failed: %d", resp.status_code)
                else:
                    logger.info("Webhook alert sent for device %s", session.device_id)
        except Exception as exc:
            logger.error("Webhook dispatch error: %s", exc)

    def generate_popia_notification(
        self,
        client_name: str,
        device_hostname: str,
        findings: list[FindingResponse],
    ) -> dict:
        """
        Generate POPIA Section 22 breach notification content.

        Section 22 of POPIA requires notification to the Information
        Regulator and affected data subjects when there are reasonable
        grounds to believe personal information has been accessed or
        acquired by an unauthorised person.
        """
        now = datetime.now(timezone.utc)

        # Categorise the types of data potentially compromised
        data_types = set()
        for f in findings:
            if f.category == FindingCategory.DATA_EXFILTRATION:
                data_types.add("Documents and files (may include patient records)")
            elif f.category == FindingCategory.PHISHING:
                data_types.add("Email credentials and communications")
            elif f.category == FindingCategory.REMOTE_ACCESS:
                data_types.add("Remote system access (all data accessible)")
            elif f.category == FindingCategory.MALWARE:
                data_types.add("System-wide access (all stored data at risk)")
            elif f.category == FindingCategory.ROOTKIT:
                data_types.add("Complete system compromise (all data at risk)")

        finding_summaries = []
        for f in findings[:10]:
            finding_summaries.append({
                "severity": f.severity.value,
                "category": f.category.value,
                "title": f.title,
                "description": f.description,
                "corroboration": f.corroboration_status.value,
                "confidence": f.corroboration_confidence,
            })

        return {
            "notification_type": "POPIA Section 22 Breach Notification",
            "generated_at": now.isoformat(),
            "client_name": client_name,
            "device": device_hostname,
            "status": "REQUIRES_REVIEW",
            "summary": (
                f"The Compromised Data Scanner has identified {len(findings)} "
                f"confirmed or likely malicious finding(s) on {device_hostname} "
                f"that may indicate unauthorised access to personal information."
            ),
            "data_types_at_risk": list(data_types),
            "findings": finding_summaries,
            "recommended_actions": [
                "Isolate the affected device from the network immediately",
                "Preserve all evidence — do not wipe or reinstall",
                "Engage ZA Support incident response team",
                "Assess whether personal information was actually accessed",
                "If personal data was accessed, notify the Information Regulator within 72 hours",
                "Notify affected data subjects as soon as reasonably possible",
                "Document all response actions taken",
            ],
            "regulatory_references": [
                "POPIA Section 22: Notification of Security Compromises",
                "Information Regulator contact: inforeg.org.za",
                "HPCSA: Ethical obligation to protect patient confidentiality",
            ],
            "disclaimer": (
                "This notification is system-generated based on automated threat "
                "detection. A qualified assessment should be conducted before "
                "formal notification to the Information Regulator. ZA Support "
                "can assist with incident response and regulatory compliance."
            ),
        }

    def _is_in_cooldown(self, device_key: str) -> bool:
        last = self._last_alert.get(device_key)
        if not last:
            return False
        from datetime import timedelta

        elapsed = datetime.now(timezone.utc) - last
        return elapsed < timedelta(minutes=ScannerConfig.ALERT_COOLDOWN_MINUTES)
