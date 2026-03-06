"""
Risk Trend Alerter — subscribes to diagnostics.upload_received.
Compares the new snapshot's risk score against the previous one.
If risk has worsened significantly, alerts Courtney immediately.

Thresholds:
  - Risk level escalated (LOW → HIGH, MODERATE → CRITICAL, etc.)
  - Score jumped by 3+ points (on a 1–10 scale)
"""
import logging
from app.core.event_bus import subscribe
from app.core.database import get_session_factory
from app.services.notification_engine import send_email, send_slack

logger = logging.getLogger(__name__)

NOTIFY_TO     = "courtney@zasupport.com"
DASHBOARD_URL = "https://app.zasupport.com"

_LEVEL_ORDER = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "CRITICAL": 4}
_SCORE_JUMP_THRESHOLD = 3


@subscribe("diagnostics.upload_received")
async def on_diagnostic_received(payload: dict):
    """
    Compare new snapshot risk against previous snapshot.
    Alert if risk level escalated or score jumped by 3+.
    """
    serial      = payload.get("serial")
    client_id   = payload.get("client_id")
    snapshot_id = payload.get("snapshot_id")

    if not serial or not client_id or not snapshot_id:
        return

    try:
        from sqlalchemy import text
        db = get_session_factory()()
        try:
            rows = db.execute(
                text("""
                SELECT id, risk_level, risk_score, scan_date
                FROM diagnostic_snapshots
                WHERE serial = :serial
                ORDER BY scan_date DESC
                LIMIT 2
                """),
                {"serial": serial},
            ).fetchall()

            if len(rows) < 2:
                return

            new_snap  = rows[0]
            prev_snap = rows[1]

            new_level_str  = (new_snap.risk_level  or "").upper()
            prev_level_str = (prev_snap.risk_level or "").upper()
            new_score  = int(new_snap.risk_score  or 0)
            prev_score = int(prev_snap.risk_score or 0)

            new_order  = _LEVEL_ORDER.get(new_level_str,  0)
            prev_order = _LEVEL_ORDER.get(prev_level_str, 0)

            level_escalated = new_order > prev_order
            score_jumped    = (new_score - prev_score) >= _SCORE_JUMP_THRESHOLD

            if not (level_escalated or score_jumped):
                return

            hostname_row = db.execute(
                text("SELECT hostname FROM client_devices WHERE serial = :s LIMIT 1"),
                {"s": serial},
            ).fetchone()
            hostname = hostname_row.hostname if hostname_row else serial

            reason_parts = []
            if level_escalated:
                reason_parts.append(f"risk level: {prev_level_str} → {new_level_str}")
            if score_jumped:
                reason_parts.append(f"score: {prev_score} → {new_score} (+{new_score - prev_score})")
            reason = " | ".join(reason_parts)

            subject = f"Risk Trend Alert — {hostname} ({new_level_str})"
            body = "\n".join([
                f"Risk has worsened on a client device.",
                f"",
                f"Device    : {hostname} ({serial})",
                f"Client    : {client_id}",
                f"Previous  : {prev_level_str} (score {prev_score})",
                f"Now       : {new_level_str} (score {new_score})",
                f"Change    : {reason}",
                f"",
                f"Client dashboard : {DASHBOARD_URL}/clients/{client_id}",
                f"Device detail    : {DASHBOARD_URL}/devices/{serial}",
            ])

            try:
                send_email(NOTIFY_TO, subject, body)
                logger.info(f"[RiskTrend] Alert sent for {serial} ({reason})")
            except Exception as e:
                logger.error(f"[RiskTrend] Email failed for {serial}: {e}")

            try:
                level_emoji = ":rotating_light:" if new_level_str == "CRITICAL" else ":warning:"
                send_slack(
                    f"{level_emoji} *Risk Trend Alert* — *{hostname}* (`{client_id}`)\n"
                    f"{prev_level_str} (score {prev_score}) → *{new_level_str}* (score {new_score})\n"
                    f"<{DASHBOARD_URL}/devices/{serial}|View Device>"
                )
            except Exception as e:
                logger.error(f"[RiskTrend] Slack failed for {serial}: {e}")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"[RiskTrend] Failed for {serial}: {e}", exc_info=True)
