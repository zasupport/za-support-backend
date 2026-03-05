"""
Notification engine — sends alerts via Mailgun email and Slack webhook.
Subscribes to the event bus for critical/high severity events.
"""
import os
import logging
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models.models import NotificationLog, SystemEvent

logger = logging.getLogger(__name__)

# Config from env
MAILGUN_API_KEY = os.getenv("HC_NOTIFY_MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("HC_NOTIFY_MAILGUN_DOMAIN", "")
MAILGUN_FROM = os.getenv("HC_NOTIFY_MAILGUN_FROM", f"ZA Support <noreply@{MAILGUN_DOMAIN}>")
NOTIFY_EMAIL_TO = os.getenv("HC_NOTIFY_EMAIL_TO", "courtney@zasupport.com")
SLACK_WEBHOOK = os.getenv("HC_NOTIFY_SLACK_WEBHOOK", "")

# Only notify on these severities
NOTIFY_SEVERITIES = {"critical", "high"}


def send_email(to: str, subject: str, body: str, db: Optional[Session] = None, event_id: Optional[int] = None) -> bool:
    """Send email via Mailgun API."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        logger.warning("Mailgun not configured — skipping email.")
        return False

    try:
        resp = httpx.post(
            f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),
            data={"from": MAILGUN_FROM, "to": to, "subject": subject, "text": body},
            timeout=10,
        )
        success = resp.status_code == 200
        if db:
            db.add(NotificationLog(
                channel="email", recipient=to, subject=subject,
                event_id=event_id, status="sent" if success else "failed",
                error=None if success else resp.text,
            ))
            db.flush()
        if not success:
            logger.error(f"Mailgun error {resp.status_code}: {resp.text}")
        return success
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        if db:
            db.add(NotificationLog(
                channel="email", recipient=to, subject=subject,
                event_id=event_id, status="failed", error=str(e),
            ))
            db.flush()
        return False


def send_slack(message: str, db: Optional[Session] = None, event_id: Optional[int] = None) -> bool:
    """Send message to Slack webhook."""
    if not SLACK_WEBHOOK:
        return False

    try:
        resp = httpx.post(SLACK_WEBHOOK, json={"text": message}, timeout=10)
        success = resp.status_code == 200
        if db:
            db.add(NotificationLog(
                channel="slack", subject=message[:200],
                event_id=event_id, status="sent" if success else "failed",
                error=None if success else resp.text,
            ))
            db.flush()
        return success
    except Exception as e:
        logger.error(f"Slack send failed: {e}")
        return False


def on_event(event: SystemEvent, db: Session):
    """Event bus subscriber — auto-notify on critical/high events."""
    if event.severity not in NOTIFY_SEVERITIES:
        return

    subject = f"[ZA Support {event.severity.upper()}] {event.summary}"
    body = (
        f"Event: {event.event_type}\n"
        f"Source: {event.source}\n"
        f"Severity: {event.severity}\n"
        f"Summary: {event.summary}\n"
        f"Device: {event.device_serial or 'N/A'}\n"
        f"Client: {event.client_id or 'N/A'}\n"
        f"Time: {event.created_at}\n"
    )
    if event.detail:
        body += f"\nDetail: {event.detail}\n"

    send_email(NOTIFY_EMAIL_TO, subject, body, db=db, event_id=event.id)

    slack_msg = f"*{event.severity.upper()}* | {event.source} | {event.summary}"
    if event.device_serial:
        slack_msg += f" | Device: {event.device_serial}"
    send_slack(slack_msg, db=db, event_id=event.id)
