"""
Morning operations email — sent daily at 07:00 SAST to Courtney.
Summarises every active client: health, last scan, open tasks, open jobs.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO = "courtney@zasupport.com"
DASHBOARD = "https://app.zasupport.com"


def run_morning_email():
    db = get_session_factory()()
    try:
        _send(db)
    except Exception as e:
        logger.error(f"Morning email failed: {e}", exc_info=True)
    finally:
        db.close()


def _send(db):
    rows = db.execute(text("""
        SELECT
            c.client_id,
            c.first_name,
            c.last_name,
            c.status,
            c.urgency_level,
            (SELECT s.risk_level
             FROM diagnostic_snapshots s JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id ORDER BY s.scan_date DESC LIMIT 1) AS risk_level,
            (SELECT s.risk_score
             FROM diagnostic_snapshots s JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id ORDER BY s.scan_date DESC LIMIT 1) AS risk_score,
            (SELECT EXTRACT(DAY FROM NOW() - s.scan_date)::int
             FROM diagnostic_snapshots s JOIN client_devices d ON d.serial = s.serial
             WHERE d.client_id = c.client_id ORDER BY s.scan_date DESC LIMIT 1) AS days_since_scan,
            (SELECT COUNT(*) FROM client_onboarding_tasks t
             WHERE t.client_id = c.client_id AND t.status != 'completed') AS open_tasks,
            (SELECT COUNT(*) FROM workshop_jobs j
             WHERE j.client_id = c.client_id AND j.status NOT IN ('done', 'cancelled', 'completed')) AS open_jobs
        FROM clients c
        WHERE c.status IN ('new', 'active', 'sla')
        ORDER BY
            CASE c.urgency_level WHEN 'Urgent' THEN 0 ELSE 1 END,
            c.status,
            c.first_name
    """)).fetchall()

    now_str = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    urgent_clients = [r for r in rows if (r.urgency_level or "").lower().startswith("urgent")]
    high_risk = [r for r in rows if (r.risk_level or "").upper() in ("CRITICAL", "HIGH")]
    overdue = [r for r in rows if (r.days_since_scan or 999) > 30]

    lines = [
        f"ZA Support — Morning Operations Brief",
        f"{now_str}",
        f"{'=' * 60}",
        f"",
        f"{len(rows)} active client{'s' if len(rows) != 1 else ''}",
    ]

    if urgent_clients:
        lines.append(f"⚠ URGENT: {', '.join(f'{r.first_name} {r.last_name}' for r in urgent_clients)}")
    if high_risk:
        lines.append(f"⚠ HIGH RISK: {', '.join(f'{r.first_name} {r.last_name} ({r.risk_level})' for r in high_risk)}")
    if overdue:
        lines.append(f"⚠ SCAN OVERDUE (>30 days): {', '.join(f'{r.first_name} {r.last_name}' for r in overdue)}")

    lines += ["", f"{'CLIENT':<25} {'STATUS':<8} {'RISK':<10} {'LAST SCAN':<10} {'TASKS':>5} {'JOBS':>5}", "-" * 70]

    for r in rows:
        name = f"{r.first_name} {r.last_name}"[:24]
        status = (r.status or "")[:7]
        risk = (r.risk_level or "No scan")[:9]
        scan = f"{r.days_since_scan}d ago" if r.days_since_scan is not None else "Never"
        tasks = str(r.open_tasks or 0)
        jobs = str(r.open_jobs or 0)
        lines.append(f"{name:<25} {status:<8} {risk:<10} {scan:<10} {tasks:>5} {jobs:>5}")

    lines += [
        "",
        f"Morning Brief: {DASHBOARD}/morning",
        f"Workshop:      {DASHBOARD}/workshop",
        f"",
        "— ZA Support Health Check AI",
    ]

    body = "\n".join(lines)
    action_flag = urgent_clients or high_risk

    subject = (
        f"{'⚠ ACTION REQUIRED — ' if action_flag else ''}"
        f"ZA Support Morning Brief — {now_str}"
    )

    try:
        send_email(NOTIFY_TO, subject, body)
        logger.info("Morning brief email sent")
    except Exception as e:
        logger.error(f"Morning brief email failed: {e}")

    try:
        slack_parts = [f"*Morning Brief — {now_str}*", f"{len(rows)} active clients"]
        if urgent_clients:
            slack_parts.append(f":rotating_light: URGENT: {', '.join(f'{r.first_name} {r.last_name}' for r in urgent_clients)}")
        if high_risk:
            slack_parts.append(f":warning: High risk: {', '.join(f'{r.first_name} {r.last_name}' for r in high_risk)}")
        slack_parts.append(f"<{DASHBOARD}/morning|Open Morning Brief>")
        send_slack("\n".join(slack_parts))
    except Exception as e:
        logger.warning(f"Morning brief Slack failed: {e}")
