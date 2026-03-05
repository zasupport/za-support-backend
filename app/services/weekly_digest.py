"""
Weekly digest — sent every Monday at 07:00 SAST to Courtney.
Summarises: new clients, open workshop jobs, high-risk devices, ISP outage count.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

DIGEST_TO = "courtney@zasupport.com"
DASHBOARD = "https://app.zasupport.com"


def run_weekly_digest():
    db: Session = get_session_factory()()
    try:
        _send(db)
    except Exception as e:
        logger.error(f"Weekly digest failed: {e}", exc_info=True)
    finally:
        db.close()


def _send(db: Session):
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # ── New clients this week ────────────────────────────────────────────
    new_clients = db.execute(
        text("SELECT first_name, last_name, client_id, created_at FROM clients WHERE created_at >= :since ORDER BY created_at DESC"),
        {"since": week_ago},
    ).fetchall()

    # ── Open workshop jobs ───────────────────────────────────────────────
    open_jobs = db.execute(
        text("SELECT job_ref, client_id, title, priority, status FROM workshop_jobs WHERE status NOT IN ('completed','cancelled') ORDER BY priority DESC, created_at DESC"),
    ).fetchall()

    urgent_jobs = [j for j in open_jobs if j.priority == "urgent"]

    # ── High-risk devices (latest snapshot risk ≥ 7) ────────────────────
    high_risk = db.execute(
        text("""
        SELECT DISTINCT ON (d.serial)
            d.serial, d.client_id, d.hostname, s.risk_score, s.risk_level, s.scan_date
        FROM   client_devices d
        JOIN   diagnostic_snapshots s ON s.serial = d.serial
        WHERE  s.risk_score >= 7
        ORDER  BY d.serial, s.scan_date DESC
        """),
    ).fetchall()

    # ── ISP outages this week ────────────────────────────────────────────
    isp_outages = db.execute(
        text("SELECT COUNT(*) AS cnt FROM isp_outages WHERE started_at >= :since"),
        {"since": week_ago},
    ).fetchone()
    outage_count = isp_outages.cnt if isp_outages else 0

    # ── New diagnostic scans ─────────────────────────────────────────────
    new_scans = db.execute(
        text("SELECT COUNT(*) AS cnt FROM diagnostic_snapshots WHERE scan_date >= :since"),
        {"since": week_ago},
    ).fetchone()
    scan_count = new_scans.cnt if new_scans else 0

    # ── Build email body ─────────────────────────────────────────────────
    now_str = datetime.now().strftime("%A %d %B %Y")
    lines = [
        f"ZA Support — Weekly Operations Digest",
        f"Week of {now_str}",
        "=" * 60,
        "",
    ]

    # New clients
    lines.append(f"NEW CLIENTS THIS WEEK: {len(new_clients)}")
    if new_clients:
        for c in new_clients:
            joined = c.created_at.strftime("%d/%m/%Y") if c.created_at else "—"
            lines.append(f"  • {c.first_name} {c.last_name} ({c.client_id}) — joined {joined}")
            lines.append(f"    {DASHBOARD}/clients/{c.client_id}")
    lines.append("")

    # Workshop jobs
    lines.append(f"OPEN WORKSHOP JOBS: {len(open_jobs)}"
                 + (f"  ⚠ {len(urgent_jobs)} URGENT" if urgent_jobs else ""))
    for j in open_jobs[:10]:
        lines.append(f"  [{j.priority.upper():8}] {j.job_ref} — {j.client_id} — {j.title[:60]}")
    if len(open_jobs) > 10:
        lines.append(f"  ... and {len(open_jobs) - 10} more")
    lines.append(f"  View all: {DASHBOARD}/workshop")
    lines.append("")

    # High-risk devices
    lines.append(f"HIGH-RISK DEVICES (score ≥ 7): {len(high_risk)}")
    for d in high_risk[:8]:
        scan_str = d.scan_date.strftime("%d/%m/%Y") if d.scan_date else "—"
        lines.append(f"  • {d.hostname or d.serial} ({d.client_id}) — "
                     f"Risk {d.risk_score} {d.risk_level} — last scan {scan_str}")
        lines.append(f"    {DASHBOARD}/devices/{d.serial}")
    lines.append("")

    # ISP + scans
    lines.append(f"DIAGNOSTIC SCANS THIS WEEK:  {scan_count}")
    lines.append(f"ISP OUTAGES THIS WEEK:       {outage_count}")
    lines.append("")
    lines.append(f"Dashboard: {DASHBOARD}")
    lines.append("")
    lines.append("— ZA Support Health Check AI")

    body = "\n".join(lines)
    subject = (
        f"{'⚠ ACTION REQUIRED — ' if urgent_jobs or high_risk else ''}"
        f"ZA Support Weekly Digest — {now_str}"
    )

    try:
        send_email(DIGEST_TO, subject, body)
        logger.info("Weekly digest sent")
    except Exception as e:
        logger.error(f"Weekly digest email failed: {e}")

    # Slack summary
    try:
        slack_lines = [
            f"*Weekly Digest — {now_str}*",
            f"New clients: *{len(new_clients)}* | Open jobs: *{len(open_jobs)}*"
            + (f" | :warning: *{len(urgent_jobs)} urgent*" if urgent_jobs else ""),
            f"High-risk devices: *{len(high_risk)}* | Scans: *{scan_count}* | ISP outages: *{outage_count}*",
            f"<{DASHBOARD}|Open Dashboard>",
        ]
        send_slack("\n".join(slack_lines))
    except Exception as e:
        logger.warning(f"Weekly digest Slack failed: {e}")
