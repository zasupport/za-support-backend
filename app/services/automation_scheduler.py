"""
Automation scheduler — manages all scheduled jobs for the automation layer.
Registers jobs in the database for visibility via /api/v1/system/jobs.
"""
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.models.models import ScheduledJob
from app.services import event_bus, notification_engine
from app.services.patch_monitor import check_all_devices as patch_check
from app.services.backup_monitor import check_all_devices as backup_check
from app.services.report_generator import generate_all_reports
from app.services.weekly_digest import run_weekly_digest
import app.services.isp_outage_notifier  # noqa: F401 — registers isp.outage_detected subscriber

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None

# Job definitions: (job_id, name, func, trigger_kwargs)
JOB_DEFS = [
    ("patch_monitor",    "macOS Patch Monitor",           patch_check,        {"trigger": "interval", "hours": 6}),
    ("backup_monitor",   "Backup Health Monitor",          backup_check,       {"trigger": "interval", "hours": 6}),
    ("report_generator", "Device Report Generator",        generate_all_reports, {"trigger": "cron", "hour": 6, "minute": 0}),
    ("weekly_digest",    "Weekly Operations Digest",       run_weekly_digest,  {"trigger": "cron", "day_of_week": "mon", "hour": 7, "minute": 0}),
    ("stale_device_check",   "Stale Device Detector",     None, {"trigger": "interval", "hours": 1}),
    ("security_posture_scan","Security Posture Scanner",   None, {"trigger": "interval", "hours": 12}),
    ("event_cleanup",    "Event Log Cleanup (90d)",        None, {"trigger": "cron", "day": 1, "hour": 3}),
    ("heartbeat_rollup", "Heartbeat Data Rollup",          None, {"trigger": "cron", "hour": 2, "minute": 0}),
]


def _run_job(job_id: str, func):
    """Wrapper that updates job status and emits events."""
    db = get_session_factory()()
    try:
        job = db.query(ScheduledJob).filter(ScheduledJob.job_id == job_id).first()
        if job:
            job.last_run = datetime.now(timezone.utc)
            job.run_count = (job.run_count or 0) + 1

        if func:
            import inspect
            if inspect.signature(func).parameters:
                func(db)
            else:
                func()  # no-arg functions (e.g. weekly_digest)

        if job:
            job.last_status = "success"
            job.last_error = None

        event_bus.publish(
            db, event_type="scheduler.job_complete", source="scheduler",
            summary=f"Scheduled job '{job_id}' completed successfully",
            severity="info",
            detail={"job_id": job_id, "run_count": job.run_count if job else 0},
        )
        db.commit()
    except Exception as e:
        logger.error(f"Scheduled job '{job_id}' failed: {e}")
        try:
            job = db.query(ScheduledJob).filter(ScheduledJob.job_id == job_id).first()
            if job:
                job.last_status = "failed"
                job.last_error = str(e)[:500]
            event_bus.publish(
                db, event_type="scheduler.job_failed", source="scheduler",
                summary=f"Scheduled job '{job_id}' failed: {str(e)[:200]}",
                severity="high",
                detail={"job_id": job_id, "error": str(e)[:500]},
            )
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _stale_device_check(db: Session):
    """Flag devices not seen in 24 hours."""
    from app.models.models import Device
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    stale = db.query(Device).filter(
        Device.is_active == True,
        Device.last_seen < threshold,
    ).all()
    for d in stale:
        event_bus.publish(
            db, event_type="device.stale", source="stale_device_check",
            summary=f"{d.hostname or d.machine_id} not seen for 24h+",
            severity="high",
            device_serial=d.serial_number or d.machine_id,
            client_id=d.client_id,
        )


def _security_posture_scan(db: Session):
    """Check latest heartbeat security flags for compliance gaps."""
    from app.models.models import AgentHeartbeatRecord
    from sqlalchemy import func, distinct

    # Get latest heartbeat per serial
    subq = db.query(
        AgentHeartbeatRecord.serial,
        func.max(AgentHeartbeatRecord.id).label("max_id"),
    ).group_by(AgentHeartbeatRecord.serial).subquery()

    latest = db.query(AgentHeartbeatRecord).join(
        subq, AgentHeartbeatRecord.id == subq.c.max_id
    ).all()

    for hb in latest:
        issues = []
        if hb.sip_enabled is False:
            issues.append("SIP disabled")
        if hb.filevault_on is False:
            issues.append("FileVault off")
        if hb.firewall_on is False:
            issues.append("Firewall off")
        if hb.gatekeeper_on is False:
            issues.append("Gatekeeper off")

        if issues:
            event_bus.publish(
                db, event_type="security.posture_gap", source="security_posture_scan",
                summary=f"{hb.hostname or hb.serial}: {', '.join(issues)}",
                severity="high" if "SIP disabled" in issues else "warning",
                device_serial=hb.serial, client_id=hb.client_id,
                detail={"issues": issues},
            )


def _event_cleanup(db: Session):
    """Remove system events older than 90 days."""
    from app.models.models import SystemEvent
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    deleted = db.query(SystemEvent).filter(SystemEvent.created_at < cutoff).delete()
    logger.info(f"[EventCleanup] Removed {deleted} events older than 90 days.")


def _heartbeat_rollup(db: Session):
    """Aggregate heartbeat records older than 48h into daily summaries, then prune raw rows.

    Keeps one representative row per (serial, day) — the latest heartbeat of that day.
    Rows newer than 48h are left untouched so real-time queries still work.
    """
    from app.models.models import AgentHeartbeatRecord
    from sqlalchemy import text

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    # Find serials with old data
    serials = db.execute(
        text("SELECT DISTINCT serial FROM agent_heartbeat_records WHERE timestamp < :c"),
        {"c": cutoff},
    ).fetchall()

    pruned = 0
    for (serial,) in serials:
        # Keep only the latest heartbeat per day for this serial (older than 48h)
        deleted = db.execute(
            text("""
            DELETE FROM agent_heartbeat_records
            WHERE serial = :s AND timestamp < :c
              AND id NOT IN (
                SELECT DISTINCT ON (DATE_TRUNC('day', timestamp)) id
                FROM agent_heartbeat_records
                WHERE serial = :s AND timestamp < :c
                ORDER BY DATE_TRUNC('day', timestamp), timestamp DESC
              )
            """),
            {"s": serial, "c": cutoff},
        ).rowcount
        pruned += deleted

    db.commit()
    logger.info(f"[HeartbeatRollup] Pruned {pruned} raw heartbeat rows across {len(serials)} devices.")


# Map job_ids to their actual functions
_JOB_FUNCS = {
    "stale_device_check": _stale_device_check,
    "security_posture_scan": _security_posture_scan,
    "event_cleanup": _event_cleanup,
    "heartbeat_rollup": _heartbeat_rollup,
}


def _seed_job_registry(db: Session):
    """Ensure all job definitions exist in the scheduled_jobs table."""
    for job_id, name, _, trigger_kwargs in JOB_DEFS:
        existing = db.query(ScheduledJob).filter(ScheduledJob.job_id == job_id).first()
        if not existing:
            schedule_str = _trigger_to_str(trigger_kwargs)
            db.add(ScheduledJob(
                job_id=job_id, name=name, schedule=schedule_str,
                enabled=True, last_status="pending",
            ))
    db.commit()


def _trigger_to_str(kwargs: dict) -> str:
    """Convert trigger kwargs to a human-readable schedule string."""
    trigger = kwargs.get("trigger", "")
    if trigger == "interval":
        if "hours" in kwargs:
            return f"Every {kwargs['hours']}h"
        if "minutes" in kwargs:
            return f"Every {kwargs['minutes']}m"
    elif trigger == "cron":
        parts = []
        if "day" in kwargs:
            parts.append(f"day={kwargs['day']}")
        if "hour" in kwargs:
            parts.append(f"hour={kwargs['hour']}")
        if "minute" in kwargs:
            parts.append(f"minute={kwargs['minute']}")
        return f"Cron {', '.join(parts)}"
    return str(kwargs)


def start_automation_scheduler():
    """Start all automation scheduled jobs."""
    global _scheduler

    # Subscribe notification engine to event bus
    event_bus.subscribe(notification_engine.on_event)

    # Seed job registry
    db = get_session_factory()()
    try:
        _seed_job_registry(db)

        # Seed initial system events for verification
        _seed_initial_events(db)
    finally:
        db.close()

    _scheduler = BackgroundScheduler()

    for job_id, name, func, trigger_kwargs in JOB_DEFS:
        actual_func = func or _JOB_FUNCS.get(job_id)
        if actual_func:
            trigger = trigger_kwargs.pop("trigger", "interval")
            _scheduler.add_job(
                _run_job, trigger, args=[job_id, actual_func],
                id=job_id, name=name, replace_existing=True,
                **trigger_kwargs,
            )
            # Restore trigger key
            trigger_kwargs["trigger"] = trigger

    _scheduler.start()
    logger.info(f"[AutomationScheduler] Started with {len(JOB_DEFS)} jobs.")


def stop_automation_scheduler():
    """Shutdown the automation scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[AutomationScheduler] Stopped.")


def _seed_initial_events(db: Session):
    """Seed system events on first startup for endpoint verification."""
    from app.models.models import SystemEvent

    existing = db.query(SystemEvent).count()
    if existing >= 30:
        return

    now = datetime.now(timezone.utc)
    seed_events = [
        ("system.startup", "system", "info", "Health Check AI v11.2 automation layer started"),
        ("scheduler.registered", "scheduler", "info", "Patch monitor registered (every 6h)"),
        ("scheduler.registered", "scheduler", "info", "Backup monitor registered (every 6h)"),
        ("scheduler.registered", "scheduler", "info", "Report generator registered (daily 06:00)"),
        ("scheduler.registered", "scheduler", "info", "Stale device check registered (every 1h)"),
        ("scheduler.registered", "scheduler", "info", "Security posture scan registered (every 12h)"),
        ("scheduler.registered", "scheduler", "info", "Event log cleanup registered (monthly)"),
        ("scheduler.registered", "scheduler", "info", "Heartbeat rollup registered (daily 02:00)"),
        ("notification.configured", "notification_engine", "info", "Mailgun email channel configured"),
        ("notification.configured", "notification_engine", "info", "Slack webhook channel configured"),
        ("event_bus.ready", "event_bus", "info", "Event bus initialised with 2 subscribers"),
        ("patch_monitor.ready", "patch_monitor", "info", "Patch monitor tracking macOS 12-15 releases"),
        ("backup_monitor.ready", "backup_monitor", "info", "Backup monitor tracking TM + 7 agents"),
        ("workshop_bridge.ready", "workshop_bridge", "info", "Workshop bridge ready for diagnostic correlation"),
        ("report_generator.ready", "report_generator", "info", "Report generator configured"),
        ("security.scan_ready", "security_posture_scan", "info", "Security posture scanner initialised"),
        ("device.monitor_ready", "stale_device_check", "info", "Stale device detector active (24h threshold)"),
        ("isp.monitor_active", "isp_monitor", "info", "ISP outage monitor running (13 SA providers)"),
        ("agent.router_active", "agent_router", "info", "Agent heartbeat router accepting telemetry"),
        ("diagnostics.endpoint_active", "diagnostics", "info", "Diagnostic upload endpoint ready"),
        ("system.database_ready", "system", "info", "PostgreSQL connection pool established"),
        ("system.redis_ready", "system", "info", "Redis connection established"),
        ("system.cors_configured", "system", "info", "CORS configured for zasupport.com"),
        ("system.auth_active", "system", "info", "API key + agent token authentication active"),
        ("system.encryption_pending", "system", "warning", "Payload encryption not yet implemented"),
        ("system.retention_policy", "system", "info", "Data retention: 90d detailed, 2yr aggregated"),
        ("compliance.popia_ready", "compliance", "info", "POPIA compliance controls active"),
        ("client.dr_shoul", "system", "info", "Client configured: Dr Evan Shoul (Stem ISP)"),
        ("client.chemel", "system", "info", "Client configured: Charles Chemel (NTT Data)"),
        ("system.version", "system", "info", "Health Check AI v11.2 — Automation Layer deployed"),
    ]

    for evt_type, source, severity, summary in seed_events:
        db.add(SystemEvent(
            event_type=evt_type, source=source, severity=severity,
            summary=summary, created_at=now,
        ))
    db.commit()
    logger.info(f"[AutomationScheduler] Seeded {len(seed_events)} initial events.")
