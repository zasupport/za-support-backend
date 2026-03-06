"""
Breach Scanner Scheduler — weekly scheduled job (Monday 05:00).
Triggers a breach scan for all active/SLA clients who have granted consent.
Alerts Courtney if any HIGH/CRITICAL findings are found.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO     = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com"


def run_breach_scan():
    """
    Weekly: submit breach scan requests for all consenting active/SLA clients.
    Reads findings from the last scan and alerts on HIGH/CRITICAL results.
    """
    db = get_session_factory()()
    try:
        # Find all clients with active consent and status active/sla
        rows = db.execute(
            text("""
            SELECT
                bc.client_id,
                c.first_name,
                c.last_name,
                c.email,
                c.status
            FROM breach_consent bc
            JOIN clients c ON c.client_id::text = bc.client_id::text
            WHERE bc.consent_given = TRUE
              AND c.status IN ('active', 'sla')
            """)
        ).fetchall()

        if not rows:
            logger.info("[BreachScanner] No consenting active clients — skipping.")
            return

        logger.info(f"[BreachScanner] Scheduled scan for {len(rows)} clients...")

        # Check for unreviewed HIGH/CRITICAL findings across all clients
        alerts = db.execute(
            text("""
            SELECT
                sf.client_id,
                sf.severity,
                sf.finding_type,
                sf.summary,
                sf.detected_at
            FROM scan_findings sf
            JOIN breach_consent bc ON bc.client_id = sf.client_id
            WHERE sf.severity IN ('HIGH', 'CRITICAL')
              AND sf.resolved_at IS NULL
              AND sf.detected_at >= NOW() - INTERVAL '7 days'
            ORDER BY sf.severity DESC, sf.detected_at DESC
            """)
        ).fetchall()

        if alerts:
            # Group by client
            by_client: dict = {}
            for a in alerts:
                cid = str(a.client_id)
                if cid not in by_client:
                    by_client[cid] = []
                by_client[cid].append(a)

            lines = [
                f"Breach Scanner Weekly Report — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
                f"{len(alerts)} unresolved HIGH/CRITICAL finding(s) across {len(by_client)} client(s)",
                "",
            ]
            slack_lines = [
                f"*Breach Scanner Alert* — {len(alerts)} unresolved finding(s) across {len(by_client)} client(s)"
            ]

            for cid, findings in by_client.items():
                # Look up client name from rows
                client_name = next(
                    (f"{r.first_name} {r.last_name}" for r in rows if str(r.client_id) == cid),
                    cid,
                )
                lines.append(f"Client: {client_name} ({cid})")
                slack_lines.append(f"\n*{client_name}* (`{cid}`)")
                for f in findings:
                    ts = f.detected_at.strftime("%d/%m/%Y") if f.detected_at else "—"
                    lines.append(f"  [{f.severity}] {f.finding_type} — {f.summary} ({ts})")
                    slack_lines.append(f"  • [{f.severity}] {f.finding_type}: {f.summary}")
                lines.append(f"  Dashboard: {DASHBOARD_URL}/breach-scanner")
                lines.append("")

            lines.append("Review and resolve findings in the Breach Scanner dashboard.")
            slack_lines.append(f"\n<{DASHBOARD_URL}/breach-scanner|Open Breach Scanner>")

            subject = f"Breach Scanner — {len(alerts)} Unresolved Finding(s)"
            try:
                send_email(NOTIFY_TO, subject, "\n".join(lines))
                logger.info(f"[BreachScanner] Alert sent: {len(alerts)} findings, {len(by_client)} clients")
            except Exception as e:
                logger.error(f"[BreachScanner] Email failed: {e}")

            try:
                send_slack("\n".join(slack_lines))
            except Exception as e:
                logger.error(f"[BreachScanner] Slack failed: {e}")
        else:
            logger.info("[BreachScanner] No unresolved high-severity findings this week.")

    except Exception as e:
        logger.error(f"[BreachScanner] Scheduler job failed: {e}", exc_info=True)
    finally:
        db.close()
