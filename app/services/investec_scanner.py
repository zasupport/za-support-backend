"""
Investec Client Scanner — daily scheduled job.
Scans courtney@zasupport.com + mary@zasupport.com via Microsoft Graph API
for payment emails referencing Investec bank.
Flags matching contacts in CRM as investec_client=True and triggers outreach.
"""
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.services.event_bus import emit_event

logger = logging.getLogger(__name__)

INVESTEC_PATTERNS = [
    r"investec",
    r"@investec\.co\.za",
    r"private bank",
    r"investec bank",
]

SCAN_MAILBOXES = [
    "courtney@zasupport.com",
    "mary@zasupport.com",
]


def _get_graph_token(settings) -> Optional[str]:
    """Get Microsoft Graph API access token via client credentials."""
    import httpx

    tenant_id = getattr(settings, "MS_TENANT_ID", None)
    client_id = getattr(settings, "MS_CLIENT_ID", None)
    client_secret = getattr(settings, "MS_CLIENT_SECRET", None)

    if not all([tenant_id, client_id, client_secret]):
        logger.warning("Investec scanner: Microsoft Graph credentials not configured — skipping")
        return None

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    try:
        resp = httpx.post(url, data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }, timeout=15)
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception as e:
        logger.error(f"Investec scanner: Graph token error: {e}")
        return None


def _fetch_recent_emails(token: str, mailbox: str, since_hours: int = 25) -> List[dict]:
    """Fetch emails from the past 25 hours for a mailbox."""
    import httpx

    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages"
    params = {
        "$filter": f"receivedDateTime ge {since}",
        "$select": "subject,bodyPreview,from,receivedDateTime",
        "$top": 100,
    }
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json().get("value", [])
    except Exception as e:
        logger.error(f"Investec scanner: email fetch error for {mailbox}: {e}")
        return []


def _is_investec_email(email: dict) -> bool:
    """Check if email contains Investec indicators."""
    text = " ".join([
        email.get("subject", ""),
        email.get("bodyPreview", ""),
        email.get("from", {}).get("emailAddress", {}).get("address", ""),
        email.get("from", {}).get("emailAddress", {}).get("name", ""),
    ]).lower()

    return any(re.search(p, text, re.IGNORECASE) for p in INVESTEC_PATTERNS)


def _extract_sender(email: dict) -> dict:
    """Extract sender name and email from Graph message."""
    addr = email.get("from", {}).get("emailAddress", {})
    name = addr.get("name", "")
    address = addr.get("address", "")

    parts = name.strip().split(" ", 1)
    first = parts[0] if parts else "Unknown"
    last = parts[1] if len(parts) > 1 else ""

    return {"first_name": first, "last_name": last, "email": address, "name": name}


def run_investec_scanner(db: Optional[Session] = None):
    """
    Main job function — called daily by automation scheduler.
    Scans both ZA Support mailboxes, flags Investec contacts, triggers outreach.
    """
    from app.core.config import settings
    from app.modules.sales_crm.models import CRMContact

    close_db = False
    if db is None:
        db = get_session_factory()()
        close_db = True

    stats = {
        "emails_scanned": 0,
        "investec_found": 0,
        "contacts_created": 0,
        "contacts_flagged": 0,
        "outreach_triggered": 0,
    }

    try:
        token = _get_graph_token(settings)
        if not token:
            logger.info("Investec scanner: no Graph token — skipping (configure MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET)")
            return stats

        for mailbox in SCAN_MAILBOXES:
            emails = _fetch_recent_emails(token, mailbox)
            stats["emails_scanned"] += len(emails)

            for email in emails:
                if not _is_investec_email(email):
                    continue

                stats["investec_found"] += 1
                sender = _extract_sender(email)

                if not sender["email"]:
                    continue

                # Find or create CRM contact
                contact = db.query(CRMContact).filter(
                    CRMContact.email == sender["email"]
                ).first()

                if not contact:
                    contact = CRMContact(
                        first_name=sender["first_name"],
                        last_name=sender["last_name"],
                        email=sender["email"],
                        segment="individual",
                        investec_client=True,
                        referral_source="investec_email_scan",
                        notes=f"Auto-detected via Investec email scan. Subject: {email.get('subject', '')[:100]}",
                    )
                    db.add(contact)
                    db.flush()
                    stats["contacts_created"] += 1
                    logger.info(f"Investec scanner: new contact created — {sender['email']}")
                elif not contact.investec_client:
                    contact.investec_client = True
                    contact.updated_at = datetime.now(timezone.utc)
                    stats["contacts_flagged"] += 1
                    logger.info(f"Investec scanner: flagged existing contact — {sender['email']}")

                # Trigger outreach opportunity if none exists
                from app.modules.sales_crm.models import CRMOpportunity
                existing_opp = db.query(CRMOpportunity).filter(
                    CRMOpportunity.contact_id == contact.id,
                    CRMOpportunity.stage.notin_(["closed_won", "closed_lost"]),
                ).first()

                if not existing_opp:
                    opp = CRMOpportunity(
                        contact_id=contact.id,
                        title=f"Complementary IT Assessment — {sender['name']}",
                        stage="lead",
                        investec_flag=True,
                        segment="individual",
                        referral_source="investec_email_scan",
                        notes="Auto-generated from Investec email scan. Follow up within 24 hours with complementary IT assessment offer.",
                    )
                    db.add(opp)
                    stats["outreach_triggered"] += 1

        db.commit()

        if stats["investec_found"] > 0:
            logger.info(
                f"Investec scanner complete: scanned={stats['emails_scanned']}, "
                f"found={stats['investec_found']}, created={stats['contacts_created']}, "
                f"outreach={stats['outreach_triggered']}"
            )

    except Exception as e:
        logger.error(f"Investec scanner failed: {e}")
        db.rollback()
    finally:
        if close_db:
            db.close()

    return stats
