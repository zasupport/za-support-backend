"""
Workshop event subscribers.
Listens for diagnostics.upload_received → auto-creates job card if high/critical findings.
"""
import logging
from app.core.event_bus import subscribe
from app.core.database import get_session_factory

logger = logging.getLogger(__name__)


@subscribe("diagnostics.upload_received")
async def on_diagnostic_received(payload: dict):
    """
    When Scout diagnostic arrives, check for CRITICAL/HIGH severity recommendations.
    Auto-create a Workshop job card if any are found.
    """
    client_id   = payload.get("client_id")
    serial      = payload.get("serial")
    snapshot_id = payload.get("snapshot_id")
    recs        = payload.get("recommendations", [])

    if not client_id or not serial:
        return

    # Only proceed if there are recommendations to evaluate
    if not recs:
        return

    try:
        from app.modules.workshop.service import auto_create_from_diagnostic
        db = get_session_factory()()
        try:
            job = auto_create_from_diagnostic(
                db=db,
                client_id=client_id,
                serial=serial,
                snapshot_id=snapshot_id,
                recommendations=recs,
            )
            if job:
                logger.info(f"Workshop: auto-created job {job.job_ref} for {client_id} / {serial}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Workshop auto-job creation failed for {client_id}: {e}")
