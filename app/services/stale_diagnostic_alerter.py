"""
Stale Diagnostic Alerter — daily scheduled job.
Finds clients whose devices haven't run Scout in 30+ days and notifies Courtney.
Registered in automation_scheduler.py.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO     = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com"
STALE_DAYS    = 30


def run_stale_diagnostic_check():
    """
    Daily: find active clients with devices that haven't had a Scout run in STALE_DAYS.
    Groups findings by client and sends a single consolidated alert.
    """
    db = get_session_factory()()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)

        rows = db.execute(
            text("""
                SELECT
                    d.client_id,
                    d.serial,
                    d.hostname,
                    d.last_seen,
                    EXTRACT(DAY FROM NOW() - d.last_seen)::int AS days_ago,
                    c.first_name,
                    c.last_name,
                    c.email,
                    c.status AS client_status
                FROM client_devices d
                LEFT JOIN clients c ON c.client_id = d.client_id
                WHERE d.is_active = TRUE
                  AND d.last_seen < :cutoff
                ORDER BY d.last_seen ASC
            """),
            {"cutoff": cutoff},
        ).fetchall()

        if not rows:
            logger.info("[StaleAlertер] No stale devices found.")
            return

        # Group by client
        by_client: dict = {}
        for r in rows:
            cid = r.client_id or "unknown"
            if cid not in by_client:
                by_client[cid] = {
                    "name": f"{r.first_name or ''} {r.last_name or ''}".strip() or cid,
                    "email": r.email or "",
                    "status": r.client_status or "",
                    "devices": [],
                }
            by_client[cid]["devices"].append({
                "serial":   r.serial,
                "hostname": r.hostname or r.serial,
                "days_ago": r.days_ago or 0,
                "last_seen": r.last_seen,
            })

        # Build report
        lines = [
            f"Stale Diagnostic Report — {datetime.now().strftime('%d/%m/%Y')}",
            f"Devices that haven't run Scout in {STALE_DAYS}+ days:",
            f"",
        ]
        slack_lines = [f"*Stale Diagnostics ({len(rows)} device(s) across {len(by_client)} client(s))*"]

        for cid, data in by_client.items():
            lines.append(f"Client: {data['name']} ({cid}) — {data['status']}")
            slack_lines.append(f"\n*{data['name']}* (`{cid}`)")
            for dev in data["devices"]:
                last_str = dev["last_seen"].strftime("%d/%m/%Y") if dev["last_seen"] else "Never"
                lines.append(f"  • {dev['hostname']} ({dev['serial']}) — last seen {last_str} ({dev['days_ago']} days ago)")
                slack_lines.append(f"  • {dev['hostname']} — {dev['days_ago']} days since last scan")
            lines.append(f"  Dashboard: {DASHBOARD_URL}/clients/{cid}")
            lines.append("")

        lines.append("Action: Schedule Scout diagnostic run for each client above.")
        slack_lines.append(f"\n<{DASHBOARD_URL}/clients|Open Clients Dashboard>")

        body = "\n".join(lines)
        subject = f"Action Required: {len(rows)} Device(s) Overdue for Diagnostic"

        try:
            send_email(NOTIFY_TO, subject, body)
            logger.info(f"[StaleAlerter] Sent stale diagnostic report: {len(rows)} devices, {len(by_client)} clients")
        except Exception as e:
            logger.error(f"[StaleAlerter] Email failed: {e}")

        try:
            send_slack("\n".join(slack_lines))
        except Exception as e:
            logger.error(f"[StaleAlerter] Slack failed: {e}")

    except Exception as e:
        logger.error(f"[StaleAlerter] Job failed: {e}", exc_info=True)
    finally:
        db.close()
