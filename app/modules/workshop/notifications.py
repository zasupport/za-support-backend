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
    When Scout diagnostic arrives:
    1. Auto-create job card for CRITICAL/HIGH recommendations.
    2. Auto-create backup failure job if Time Machine or CCC is broken.
    """
    client_id   = payload.get("client_id")
    serial      = payload.get("serial")
    snapshot_id = payload.get("snapshot_id")
    recs        = payload.get("recommendations", [])

    if not client_id or not serial:
        return

    try:
        from app.modules.workshop.service import auto_create_from_diagnostic, create_job
        from app.modules.workshop.schemas import JobCreate
        db = get_session_factory()()
        try:
            # 1. Standard CRITICAL/HIGH job card
            if recs:
                job = auto_create_from_diagnostic(
                    db=db,
                    client_id=client_id,
                    serial=serial,
                    snapshot_id=snapshot_id,
                    recommendations=recs,
                )
                if job:
                    logger.info(f"Workshop: auto-created job {job.job_ref} for {client_id} / {serial}")

            # 2. Backup failure detection from environment section
            from sqlalchemy import text
            snap_row = db.execute(
                text("SELECT raw_json FROM diagnostic_snapshots WHERE id = :id"),
                {"id": snapshot_id},
            ).fetchone() if snapshot_id else None

            if snap_row:
                import json
                raw = json.loads(snap_row.raw_json) if isinstance(snap_row.raw_json, str) else (snap_row.raw_json or {})
                env = raw.get("environment", {})

                backup_issues = []

                # Time Machine check (flat fields from environment_mod.sh)
                tm_status = (env.get("time_machine_status") or "").upper()
                days_since_raw = env.get("time_machine_days_ago")
                try:
                    days_since = int(days_since_raw) if days_since_raw not in (None, "UNKNOWN", "") else None
                except (ValueError, TypeError):
                    days_since = None

                if tm_status in ("DISABLED", ""):
                    backup_issues.append("Time Machine: disabled")
                elif days_since is not None and days_since > 7:
                    backup_issues.append(f"Time Machine: {days_since} days since last backup")

                # CCC check (flat fields from environment_mod.sh)
                ccc_installed = (env.get("ccc_installed") or "NO").upper() == "YES"
                ccc_status = (env.get("ccc_backup_status") or "").strip()
                if ccc_installed and ccc_status not in ("0", ""):
                    backup_issues.append(f"CCC: last run status {ccc_status}")
                elif not ccc_installed and tm_status in ("DISABLED", ""):
                    backup_issues.append("CCC: not installed")

                if backup_issues:
                    existing = db.execute(
                        text("""
                            SELECT id FROM workshop_jobs
                            WHERE client_id = :cid AND serial = :serial
                              AND title ILIKE '%backup%'
                              AND status NOT IN ('done', 'cancelled')
                              AND created_at > NOW() - INTERVAL '14 days'
                        """),
                        {"cid": client_id, "serial": serial},
                    ).fetchone()

                    if not existing:
                        issue_str = "; ".join(backup_issues)
                        backup_job = create_job(
                            db=db,
                            data=JobCreate(
                                client_id=client_id,
                                serial=serial,
                                title=f"Backup failure — {serial}",
                                description=f"Scout detected backup issues: {issue_str}",
                                priority="high",
                                line_items=[],
                            ),
                            source="auto",
                            snapshot_id=snapshot_id,
                        )
                        db.commit()
                        logger.info(f"Workshop: backup failure job {backup_job.job_ref} created for {client_id} — {issue_str}")

                # 3. Remote access tool detection (flat string from environment_mod.sh)
                remote_str = env.get("remote_access_tools") or ""
                # Value is space-separated tool names, e.g. "AnyDesk TeamViewer ScreenSharing(macOS)"
                if isinstance(remote_str, list):
                    remote_tools = [t.strip() for t in remote_str if t.strip()]
                else:
                    remote_tools = [t.strip() for t in remote_str.replace("|", " ").split() if t.strip() and t.strip().upper() != "NONE"]

                unknown_tools = []
                approved = {"teamviewer", "parallels", "screens", "apple remote desktop", "screensharing(macos)"}
                for tool in remote_tools:
                    if tool.lower() not in approved:
                        unknown_tools.append(tool)

                if unknown_tools:
                    existing_ra = db.execute(
                        text("""
                            SELECT id FROM workshop_jobs
                            WHERE client_id = :cid AND serial = :serial
                              AND title ILIKE '%remote access%'
                              AND status NOT IN ('done', 'cancelled')
                              AND created_at > NOW() - INTERVAL '14 days'
                        """),
                        {"cid": client_id, "serial": serial},
                    ).fetchone()

                    if not existing_ra:
                        tools_str = ", ".join(unknown_tools)
                        ra_job = create_job(
                            db=db,
                            data=JobCreate(
                                client_id=client_id,
                                serial=serial,
                                title=f"Suspicious remote access tool — {serial}",
                                description=(
                                    f"Scout detected unrecognised remote access software: {tools_str}. "
                                    f"Verify with client whether these are authorised."
                                ),
                                priority="urgent",
                                line_items=[],
                            ),
                            source="auto",
                            snapshot_id=snapshot_id,
                        )
                        db.commit()
                        logger.warning(
                            f"Workshop: CRITICAL remote access job {ra_job.job_ref} created "
                            f"for {client_id} — tools: {tools_str}"
                        )

        finally:
            db.close()
    except Exception as e:
        logger.error(f"Workshop auto-job creation failed for {client_id}: {e}")
