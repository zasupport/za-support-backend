"""
Report generator — daily scheduled job at 06:00.
Generates CyberPulse PDF for all active/SLA clients with fresh Scout data.
Stores the result in generated_reports for quick retrieval from the dashboard.
Does NOT email — email delivery is handled by:
  - report_delivery.py (on CRITICAL/HIGH diagnostic upload)
  - sla_report_scheduler.py (monthly, 1st of each month)
"""
import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.event_bus import publish

logger = logging.getLogger(__name__)

FRESH_THRESHOLD_DAYS = 7     # Only generate for clients with recent Scout data
REGEN_COOLDOWN_HOURS = 20    # Skip if a report was generated within last 20h


def generate_all_reports(db: Session):
    """
    Generate CyberPulse PDFs for all active/SLA clients with recent Scout data.
    Skips clients with no fresh snapshot or a report generated today.
    """
    from app.modules.reports.generator import generate_cyberpulse_pdf

    logger.info("[ReportGen] Starting daily CyberPulse report generation...")

    cutoff_fresh   = datetime.now(timezone.utc) - timedelta(days=FRESH_THRESHOLD_DAYS)
    cutoff_regen   = datetime.now(timezone.utc) - timedelta(hours=REGEN_COOLDOWN_HOURS)

    # All active/SLA clients with at least one fresh snapshot
    rows = db.execute(
        text("""
        SELECT DISTINCT ON (c.client_id)
            c.client_id,
            c.first_name,
            c.last_name,
            c.email,
            c.status,
            s.id         AS snapshot_id,
            s.serial,
            s.scan_date,
            s.raw_json,
            d.hostname
        FROM clients c
        JOIN client_devices d ON d.client_id = c.client_id AND d.is_active = TRUE
        JOIN diagnostic_snapshots s ON s.serial = d.serial
        WHERE c.status IN ('active', 'sla')
          AND s.scan_date >= :cutoff_fresh
        ORDER BY c.client_id, s.scan_date DESC
        """),
        {"cutoff_fresh": cutoff_fresh},
    ).fetchall()

    if not rows:
        logger.info("[ReportGen] No clients with fresh diagnostic data — nothing to generate.")
        return

    generated = 0
    skipped   = 0
    failed    = 0

    for row in rows:
        client_id   = row.client_id
        client_name = f"{row.first_name} {row.last_name}".strip()

        # Skip if a report was already generated recently
        recent = db.execute(
            text("""
            SELECT id FROM generated_reports
            WHERE client_id = :cid
              AND generated_at >= :cutoff_regen
            LIMIT 1
            """),
            {"cid": client_id, "cutoff_regen": cutoff_regen},
        ).fetchone()

        if recent:
            skipped += 1
            continue

        raw_payload = {}
        try:
            raw_payload = json.loads(row.raw_json) if isinstance(row.raw_json, str) else (row.raw_json or {})
        except Exception:
            pass

        try:
            pdf_bytes = generate_cyberpulse_pdf(
                client_name=client_name,
                client_id=client_id,
                hostname=row.hostname or row.serial,
                serial=row.serial,
                payload=raw_payload,
                scan_date=row.scan_date,
                reason="Automated daily CyberPulse Assessment.",
            )
        except Exception as e:
            logger.error(f"[ReportGen] PDF generation failed for {client_id}: {e}")
            failed += 1
            continue

        # Store report log
        try:
            date_str = datetime.now(timezone.utc).strftime("%d %m %Y")
            filename = f"ZA Support CyberPulse {client_name} {date_str}.pdf"
            db.execute(
                text("""
                INSERT INTO generated_reports (client_id, serial, snapshot_id, report_type, filename)
                VALUES (:client_id, :serial, :snapshot_id, 'cyberpulse', :filename)
                """),
                {
                    "client_id":   client_id,
                    "serial":      row.serial,
                    "snapshot_id": row.snapshot_id,
                    "filename":    filename,
                },
            )
            db.commit()
        except Exception as e:
            logger.warning(f"[ReportGen] Failed to log report for {client_id}: {e}")
            db.rollback()

        publish(
            db, event_type="report.generated", source="report_generator",
            summary=f"CyberPulse PDF generated for {client_name}",
            severity="info",
            client_id=client_id, device_serial=row.serial,
        )

        generated += 1
        logger.info(f"[ReportGen] Generated: {client_name} ({client_id})")

    db.commit()
    logger.info(
        f"[ReportGen] Done. Generated: {generated}, Skipped (recent): {skipped}, Failed: {failed}."
    )
