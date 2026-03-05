"""
Health Check AI — ISP Outage Monitor Scheduler
Background task that periodically checks all monitored ISPs,
correlates signals, manages outage lifecycle, and triggers alerts.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from .config import config
from .detection_engine import ISPDetectionEngine, OutageCorrelator
from .alerts import AlertManager
from .schemas import OutageAlert, StatusCheckResult

logger = logging.getLogger("healthcheck.isp_monitor.scheduler")


class ISPMonitorScheduler:
    """
    Main scheduler that orchestrates:
    1. Periodic ISP status checks via detection engine
    2. Signal correlation via OutageCorrelator
    3. Outage event lifecycle (create → update → resolve)
    4. Alert dispatch
    5. Result persistence to database

    Integrates with Health Check AI's existing async infrastructure.
    """

    def __init__(self, db_pool, redis_client):
        """
        Args:
            db_pool: asyncpg connection pool (from Health Check main app)
            redis_client: aioredis client (from Health Check main app)
        """
        self.db = db_pool
        self.redis = redis_client
        self.engine = ISPDetectionEngine()
        self.correlator = OutageCorrelator(
            confirmation_threshold=config.OUTAGE_CONFIRMATION_THRESHOLD
        )
        self.alerts = AlertManager()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Cache of active outages: {isp_id: outage_id}
        self._active_outages: Dict[int, int] = {}

    # ==========================================================
    # Lifecycle
    # ==========================================================
    async def start(self):
        """Start the monitoring loop."""
        await self.engine.start()
        await self.alerts.start()
        await self._load_active_outages()

        self._running = True
        self._task = asyncio.create_task(self._monitoring_loop())
        logger.info("ISP Monitor Scheduler started")

    async def stop(self):
        """Gracefully stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.engine.stop()
        await self.alerts.stop()
        logger.info("ISP Monitor Scheduler stopped")

    # ==========================================================
    # Main monitoring loop
    # ==========================================================
    async def _monitoring_loop(self):
        """
        Core loop: fetch enabled ISPs → run checks → correlate → act.
        Runs every STATUS_PAGE_CHECK_INTERVAL seconds.
        """
        while self._running:
            try:
                # 1. Get all enabled ISPs from database
                isps = await self._get_enabled_isps()

                # 2. Run checks concurrently for all ISPs
                check_tasks = [
                    self._check_single_isp(isp["isp_id"], isp["isp_slug"])
                    for isp in isps
                ]
                await asyncio.gather(*check_tasks, return_exceptions=True)

                # 3. Publish current status to Redis for real-time dashboard
                await self._publish_dashboard_status()

            except Exception as e:
                logger.error(f"Monitoring loop error: {e}", exc_info=True)

            # Wait for next cycle
            await asyncio.sleep(config.STATUS_PAGE_CHECK_INTERVAL)

    async def _check_single_isp(self, isp_id: int, isp_slug: str):
        """Run all checks for one ISP, correlate, and act."""
        try:
            # Run detection methods
            results = await self.engine.check_isp(isp_id, isp_slug)

            # Persist check results
            await self._store_check_results(results)

            # Get agent connectivity data for this ISP's clients
            agents_offline, agents_total = await self._get_agent_status(isp_id)

            # Correlate signals
            severity, reason = self.correlator.evaluate(
                isp_id, results, agents_offline, agents_total
            )

            # Act on correlation result
            if severity is not None:
                await self._handle_outage_detected(isp_id, isp_slug, severity, reason)
            else:
                await self._handle_no_outage(isp_id, isp_slug)

        except Exception as e:
            logger.error(f"Check failed for ISP {isp_slug}: {e}", exc_info=True)

    # ==========================================================
    # Outage lifecycle management
    # ==========================================================
    async def _handle_outage_detected(
        self, isp_id: int, isp_slug: str, severity: str, reason: str
    ):
        """Handle a detected outage — create new event or update existing."""
        if isp_id in self._active_outages:
            # Update existing outage
            outage_id = self._active_outages[isp_id]
            await self._update_outage(outage_id, severity, reason)
            logger.info(f"Outage {outage_id} for {isp_slug} updated: {severity} — {reason}")
        else:
            # Create new outage event
            outage_id = await self._create_outage(isp_id, severity, reason)
            self._active_outages[isp_id] = outage_id
            logger.warning(f"NEW OUTAGE {outage_id} for {isp_slug}: {severity} — {reason}")

            # Send alert
            affected_clients = await self._get_affected_clients(isp_id)
            isp_name = await self._get_isp_name(isp_id)

            alert = OutageAlert(
                alert_type="isp_outage" if severity in ("full", "partial") else "isp_degraded",
                isp_name=isp_name,
                isp_slug=isp_slug,
                severity=severity,
                started_at=datetime.now(timezone.utc),
                detection_method=reason,
                affected_clients=affected_clients,
                message=reason,
                outage_id=outage_id,
            )
            await self.alerts.send_outage_alert(alert)

            # Record client impact
            await self._record_client_impact(outage_id, isp_id)

            # Cache in Redis for real-time access
            await self.redis.set(
                f"isp:outage:active:{isp_id}",
                str(outage_id),
                ex=86400,       # expires in 24h as safety net
            )

    async def _handle_no_outage(self, isp_id: int, isp_slug: str):
        """Handle ISP appearing healthy — resolve active outage if exists."""
        if isp_id in self._active_outages:
            outage_id = self._active_outages.pop(isp_id)
            await self._resolve_outage(outage_id)
            self.correlator.clear_isp(isp_id)

            logger.info(f"OUTAGE RESOLVED {outage_id} for {isp_slug}")

            # Send restoration alert
            affected_clients = await self._get_affected_clients(isp_id)
            isp_name = await self._get_isp_name(isp_id)

            alert = OutageAlert(
                alert_type="isp_restored",
                isp_name=isp_name,
                isp_slug=isp_slug,
                severity="resolved",
                started_at=datetime.now(timezone.utc),
                detection_method="All checks passing",
                affected_clients=affected_clients,
                message=f"{isp_name} connectivity restored",
                outage_id=outage_id,
            )
            await self.alerts.send_restoration_alert(alert)

            # Clear Redis cache
            await self.redis.delete(f"isp:outage:active:{isp_id}")

    # ==========================================================
    # Database operations
    # ==========================================================
    async def _get_enabled_isps(self):
        """Fetch all ISPs that are enabled for monitoring."""
        return await self.db.fetch(
            "SELECT isp_id, isp_slug, isp_name, check_interval "
            "FROM isp_registry WHERE check_enabled = TRUE"
        )

    async def _store_check_results(self, results: list[StatusCheckResult]):
        """Persist check results to TimescaleDB."""
        if not results:
            return
        now = datetime.now(timezone.utc)
        await self.db.executemany(
            """INSERT INTO isp_status_checks
               (check_time, isp_id, check_method, is_up, latency_ms,
                packet_loss_pct, status_code, raw_status, error_message, source)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            [
                (now, r.isp_id, r.check_method.value, r.is_up, r.latency_ms,
                 r.packet_loss_pct, r.status_code, r.raw_status, r.error_message, r.source)
                for r in results
            ],
        )

    async def _get_agent_status(self, isp_id: int) -> tuple[int, int]:
        """
        Count how many Health Check agents on this ISP are offline.
        Returns (offline_count, total_count).
        """
        row = await self.db.fetchrow(
            """SELECT
                 COUNT(*) AS total,
                 COUNT(*) FILTER (
                     WHERE ac.report_time < NOW() - INTERVAL '$1 seconds'
                     OR ac.is_online = FALSE
                 ) AS offline
               FROM client_isp ci
               JOIN LATERAL (
                   SELECT report_time, is_online
                   FROM agent_connectivity
                   WHERE client_id = ci.client_id
                   ORDER BY report_time DESC
                   LIMIT 1
               ) ac ON TRUE
               WHERE ci.isp_id = $2""",
            config.AGENT_HEARTBEAT_TIMEOUT,
            isp_id,
        )
        if row:
            return row["offline"] or 0, row["total"] or 0
        return 0, 0

    async def _create_outage(self, isp_id: int, severity: str, reason: str) -> int:
        """Create a new outage event and return its ID."""
        row = await self.db.fetchrow(
            """INSERT INTO isp_outage_events
               (isp_id, started_at, severity, detection_method, notes, auto_detected)
               VALUES ($1, NOW(), $2, $3, $4, TRUE)
               RETURNING outage_id""",
            isp_id, severity, reason, reason,
        )
        return row["outage_id"]

    async def _update_outage(self, outage_id: int, severity: str, reason: str):
        """Update severity/notes on an active outage."""
        await self.db.execute(
            """UPDATE isp_outage_events
               SET severity = $1, notes = $2
               WHERE outage_id = $3 AND ended_at IS NULL""",
            severity, reason, outage_id,
        )

    async def _resolve_outage(self, outage_id: int):
        """Close an outage event."""
        await self.db.execute(
            "UPDATE isp_outage_events SET ended_at = NOW() WHERE outage_id = $1",
            outage_id,
        )

    async def _get_affected_clients(self, isp_id: int) -> list[str]:
        """Get names of clients using this ISP."""
        rows = await self.db.fetch(
            """SELECT DISTINCT ci.site_name
               FROM client_isp ci
               WHERE ci.isp_id = $1""",
            isp_id,
        )
        return [r["site_name"] for r in rows if r["site_name"]]

    async def _get_isp_name(self, isp_id: int) -> str:
        """Get ISP display name."""
        row = await self.db.fetchrow(
            "SELECT isp_name FROM isp_registry WHERE isp_id = $1", isp_id
        )
        return row["isp_name"] if row else "Unknown ISP"

    async def _record_client_impact(self, outage_id: int, isp_id: int):
        """Record which clients are affected by an outage."""
        await self.db.execute(
            """INSERT INTO outage_client_impact (outage_id, client_id, client_isp_id)
               SELECT $1, ci.client_id, ci.client_isp_id
               FROM client_isp ci WHERE ci.isp_id = $2
               ON CONFLICT (outage_id, client_id) DO NOTHING""",
            outage_id, isp_id,
        )

    async def _load_active_outages(self):
        """Load any active (unresolved) outages on startup."""
        rows = await self.db.fetch(
            "SELECT outage_id, isp_id FROM isp_outage_events WHERE ended_at IS NULL"
        )
        self._active_outages = {r["isp_id"]: r["outage_id"] for r in rows}
        if self._active_outages:
            logger.info(f"Loaded {len(self._active_outages)} active outages from database")

    async def _publish_dashboard_status(self):
        """Push current ISP status summary to Redis for real-time dashboard."""
        try:
            isps = await self._get_enabled_isps()
            for isp in isps:
                isp_id = isp["isp_id"]
                latest = await self.db.fetchrow(
                    """SELECT is_up, latency_ms, packet_loss_pct, check_time
                       FROM isp_status_checks
                       WHERE isp_id = $1
                       ORDER BY check_time DESC LIMIT 1""",
                    isp_id,
                )
                if latest:
                    import json
                    status = {
                        "isp_id": isp_id,
                        "isp_slug": isp["isp_slug"],
                        "isp_name": isp["isp_name"],
                        "is_up": latest["is_up"],
                        "latency_ms": latest["latency_ms"],
                        "packet_loss_pct": latest["packet_loss_pct"],
                        "last_checked": latest["check_time"].isoformat(),
                        "has_active_outage": isp_id in self._active_outages,
                    }
                    await self.redis.set(
                        f"isp:status:{isp_id}",
                        json.dumps(status),
                        ex=600,         # 10 min TTL
                    )
        except Exception as e:
            logger.error(f"Failed to publish dashboard status: {e}")
