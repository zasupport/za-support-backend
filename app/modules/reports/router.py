"""
Reports router — HTTP layer only.
Prefix: /api/v1/reports
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.reports.generator import generate_cyberpulse_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


def _get_latest_snapshot(db: Session, client_id: str, snapshot_id: int = None) -> dict | None:
    """Fetch snapshot payload for the given client (or specific snapshot_id)."""
    if snapshot_id:
        row = db.execute(
            text("SELECT * FROM diagnostic_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        ).fetchone()
        return dict(row._mapping) if row else None

    # Latest snapshot for any device belonging to this client
    row = db.execute(
        text("""
        SELECT s.*
        FROM   diagnostic_snapshots s
        JOIN   client_devices d ON d.serial = s.serial
        WHERE  d.client_id = :client_id
        ORDER  BY s.scan_date DESC
        LIMIT  1
        """),
        {"client_id": client_id},
    ).fetchone()
    return dict(row._mapping) if row else None


def _get_device(db: Session, serial: str) -> dict | None:
    row = db.execute(
        text("SELECT * FROM client_devices WHERE serial = :serial"),
        {"serial": serial},
    ).fetchone()
    return dict(row._mapping) if row else None


def _get_client(db: Session, client_id: str) -> dict | None:
    row = db.execute(
        text("SELECT * FROM clients WHERE client_id = :client_id"),
        {"client_id": client_id},
    ).fetchone()
    return dict(row._mapping) if row else None


@router.get("/cyberpulse/{client_id}", dependencies=[Depends(verify_agent_token)])
def generate_report(
    client_id: str,
    snapshot_id: int = Query(None, description="Specific snapshot ID; defaults to latest"),
    db: Session = Depends(get_db),
):
    """
    Generate CyberPulse Assessment PDF for a client.
    Returns the PDF as an inline/download binary stream.
    """
    snap = _get_latest_snapshot(db, client_id, snapshot_id)
    if not snap:
        raise HTTPException(
            status_code=404,
            detail=f"No diagnostic snapshot found for client '{client_id}'",
        )

    device = _get_device(db, snap["serial"])
    client = _get_client(db, client_id)

    client_name = "Unknown Client"
    if client:
        first = client.get("first_name", "")
        last  = client.get("last_name", "")
        client_name = f"{first} {last}".strip() or client_id

    hostname    = (device or {}).get("hostname") or snap["serial"]
    serial      = snap["serial"]
    payload     = snap.get("raw_json") or {}
    scan_date   = None
    if snap.get("scan_date"):
        try:
            scan_date = datetime.fromisoformat(str(snap["scan_date"])).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass

    reason = (
        f"Routine Health Check Scout diagnostic assessment. "
        f"Scout v{(payload.get('version') or '3.5')} diagnostic run on {scan_date or 'this device'}."
    )

    try:
        pdf_bytes = generate_cyberpulse_pdf(
            client_name=client_name,
            client_id=client_id,
            hostname=hostname,
            serial=serial,
            payload=payload,
            scan_date=scan_date,
            reason=reason,
        )
    except Exception as e:
        logger.error(f"PDF generation failed for {client_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    # Log the generated report
    try:
        filename = f"CyberPulse Assessment {client_name} {datetime.now().strftime('%d %m %Y')}.pdf"
        db.execute(
            text("""
            INSERT INTO generated_reports (client_id, serial, snapshot_id, report_type, filename)
            VALUES (:client_id, :serial, :snapshot_id, 'cyberpulse', :filename)
            """),
            {"client_id": client_id, "serial": serial,
             "snapshot_id": snap.get("id"), "filename": filename},
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to log generated report: {e}")

    safe_name = client_name.replace(" ", "_")
    date_str  = datetime.now().strftime("%d_%m_%Y")
    dl_name   = f"CyberPulse_Assessment_{safe_name}_{date_str}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{dl_name}"'},
    )


@router.get("/history/{client_id}", dependencies=[Depends(verify_agent_token)])
def report_history(client_id: str, db: Session = Depends(get_db)):
    """List previously generated reports for a client."""
    rows = db.execute(
        text("SELECT * FROM generated_reports WHERE client_id = :cid ORDER BY generated_at DESC LIMIT 20"),
        {"cid": client_id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]
