"""
Notification engine — sends alerts via SMTP email and Slack webhook.
Subscribes to the event bus for critical/high severity events.
"""
import os
import smtplib
import ssl
import subprocess
import tempfile
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models.models import NotificationLog, SystemEvent

logger = logging.getLogger(__name__)

# SMTP config — set HC_NOTIFY_SMTP_* on Render (see render.yaml)
SMTP_HOST       = os.getenv("HC_NOTIFY_SMTP_HOST", "mail.hexonline.co.za")
SMTP_PORT       = int(os.getenv("HC_NOTIFY_SMTP_PORT", "587"))
SMTP_USER       = os.getenv("HC_NOTIFY_SMTP_USER", "Courtney@zasupport.com")
SMTP_PASS       = os.getenv("HC_NOTIFY_SMTP_PASS", "")
EMAIL_FROM      = os.getenv("HC_NOTIFY_EMAIL_FROM", "ZA Support <Courtney@zasupport.com>")
NOTIFY_EMAIL_TO = os.getenv("HC_NOTIFY_EMAIL_TO", "courtney@zasupport.com")
SLACK_WEBHOOK   = os.getenv("HC_NOTIFY_SLACK_WEBHOOK", "")

NOTIFY_SEVERITIES = {"critical", "high"}


def _build_msg(to: str, subject: str, body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = to
    msg.attach(MIMEText(body, "plain"))
    return msg


def _send_ntlm(to: str, msg: MIMEMultipart) -> bool:
    """Send via curl NTLM (Exchange servers reject STARTTLS)."""
    eml = netrc = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".eml", delete=False, prefix="/tmp/za-") as f:
            f.write(msg.as_string())
            eml = f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".netrc", delete=False, prefix="/tmp/za-") as f:
            f.write(f"machine {SMTP_HOST} login {SMTP_USER} password {SMTP_PASS}\n")
            netrc = f.name
        os.chmod(netrc, 0o600)
        r = subprocess.run([
            "curl", "--silent", "--show-error",
            "--url", f"smtp://{SMTP_HOST}:{SMTP_PORT}",
            "--mail-from", SMTP_USER, "--mail-rcpt", to,
            "--netrc-file", netrc, "--ntlm", "--upload-file", eml,
        ], capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    finally:
        for p in (eml, netrc):
            if p:
                try:
                    os.unlink(p)
                except Exception:
                    pass


def _send_starttls(to: str, msg: MIMEMultipart) -> bool:
    """STARTTLS fallback."""
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(SMTP_USER, to, msg.as_string())
    return True


def send_email(to: str, subject: str, body: str, db: Optional[Session] = None, event_id: Optional[int] = None) -> bool:
    """Send email via SMTP (NTLM first, STARTTLS fallback)."""
    if not SMTP_PASS:
        logger.warning("HC_NOTIFY_SMTP_PASS not configured — skipping email.")
        return False

    msg = _build_msg(to, subject, body)
    success = False
    error_msg = None

    try:
        success = _send_ntlm(to, msg)
        if not success:
            success = _send_starttls(to, msg)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Email send failed: {e}")

    if db:
        db.add(NotificationLog(
            channel="email", recipient=to, subject=subject,
            event_id=event_id,
            status="sent" if success else "failed",
            error=error_msg,
        ))
        db.flush()
    return success


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
