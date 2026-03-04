"""
Background scheduler for ISP Outage Monitor.
Uses APScheduler BackgroundScheduler (sync, thread-pool based)
to match existing sync SQLAlchemy session pattern.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import settings
from app.core.database import get_session_factory
from app.services.isp_monitor import run_all_checks, evaluate_agent_heartbeats

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler = None


def _run_checks_job():
    """Job wrapper: creates a DB session, runs all checks, closes session."""
    db = get_session_factory()()
    try:
        run_all_checks(db)
    except Exception as e:
        logger.error(f"ISP check job failed: {e}")
    finally:
        db.close()


def _heartbeat_job():
    """Job wrapper: creates a DB session, evaluates heartbeats, closes session."""
    db = get_session_factory()()
    try:
        evaluate_agent_heartbeats(db)
    except Exception as e:
        logger.error(f"ISP heartbeat job failed: {e}")
    finally:
        db.close()


def start_isp_scheduler():
    """Start the ISP monitor background scheduler."""
    global _scheduler

    if not settings.ISP_MONITOR_ENABLED:
        logger.info("ISP Monitor disabled (ISP_MONITOR_ENABLED=false)")
        return

    if _scheduler is not None:
        logger.warning("ISP scheduler already running")
        return

    _scheduler = BackgroundScheduler()

    _scheduler.add_job(
        _run_checks_job,
        "interval",
        seconds=settings.ISP_MONITOR_STATUS_PAGE_CHECK_INTERVAL,
        id="isp_run_all_checks",
        name="ISP Status Checks (Layers 1-3)",
        max_instances=1,
    )

    _scheduler.add_job(
        _heartbeat_job,
        "interval",
        seconds=settings.ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT,
        id="isp_agent_heartbeats",
        name="ISP Agent Heartbeat Evaluation (Layer 4)",
        max_instances=1,
    )

    _scheduler.start()
    logger.info(
        f"ISP scheduler started: checks every {settings.ISP_MONITOR_STATUS_PAGE_CHECK_INTERVAL}s, "
        f"heartbeats every {settings.ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT}s"
    )


def stop_isp_scheduler():
    """Stop the ISP monitor background scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("ISP scheduler stopped")
