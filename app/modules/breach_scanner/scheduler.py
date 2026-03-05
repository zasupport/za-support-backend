"""
Scan Scheduler — manages per-device scan schedules and triggers
scans at the appropriate intervals.

Works with the Health Check agent: the scheduler doesn't run scans
directly. It signals agents when their devices are due for a scan.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import ScannerConfig
from .models import ScanScope

logger = logging.getLogger(__name__)


class ScanSchedule:
    """Represents a scan schedule for a single device."""

    def __init__(
        self,
        device_id: uuid.UUID,
        client_id: uuid.UUID,
        scope: ScanScope = ScanScope.FULL,
        interval_hours: int = 24,
        enabled: bool = True,
    ) -> None:
        self.device_id = device_id
        self.client_id = client_id
        self.scope = scope
        self.interval_hours = interval_hours
        self.enabled = enabled
        self.last_scan_at: Optional[datetime] = None
        self.next_scan_at: Optional[datetime] = None
        self.consecutive_failures: int = 0

    @property
    def is_due(self) -> bool:
        if not self.enabled:
            return False
        if not self.next_scan_at:
            return True
        return datetime.now(timezone.utc) >= self.next_scan_at

    def mark_completed(self, completed_at: Optional[datetime] = None) -> None:
        self.last_scan_at = completed_at or datetime.now(timezone.utc)
        self.next_scan_at = self.last_scan_at + timedelta(hours=self.interval_hours)
        self.consecutive_failures = 0

    def mark_failed(self) -> None:
        self.consecutive_failures += 1
        # Back off: double interval after each failure, cap at 7 days
        backoff = min(self.interval_hours * (2 ** self.consecutive_failures), 168)
        self.next_scan_at = datetime.now(timezone.utc) + timedelta(hours=backoff)


class ScanScheduler:
    """Manages scan schedules across all monitored devices."""

    def __init__(self) -> None:
        self._schedules: dict[uuid.UUID, ScanSchedule] = {}  # device_id -> schedule
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_device(
        self,
        device_id: uuid.UUID,
        client_id: uuid.UUID,
        scope: ScanScope = ScanScope.FULL,
        interval_hours: Optional[int] = None,
    ) -> ScanSchedule:
        """Register a device for scheduled scanning."""
        schedule = ScanSchedule(
            device_id=device_id,
            client_id=client_id,
            scope=scope,
            interval_hours=interval_hours or ScannerConfig.DEFAULT_SCAN_INTERVAL_HOURS,
        )
        self._schedules[device_id] = schedule
        logger.info(
            "Device %s scheduled for %s scans every %d hours",
            device_id,
            scope.value,
            schedule.interval_hours,
        )
        return schedule

    def remove_device(self, device_id: uuid.UUID) -> None:
        self._schedules.pop(device_id, None)

    def update_schedule(
        self,
        device_id: uuid.UUID,
        scope: Optional[ScanScope] = None,
        interval_hours: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[ScanSchedule]:
        schedule = self._schedules.get(device_id)
        if not schedule:
            return None
        if scope is not None:
            schedule.scope = scope
        if interval_hours is not None:
            schedule.interval_hours = interval_hours
        if enabled is not None:
            schedule.enabled = enabled
        return schedule

    def get_due_devices(self) -> list[ScanSchedule]:
        """Return all devices due for a scan."""
        return [s for s in self._schedules.values() if s.is_due]

    def get_schedule(self, device_id: uuid.UUID) -> Optional[ScanSchedule]:
        return self._schedules.get(device_id)

    def get_all_schedules(self) -> list[ScanSchedule]:
        return list(self._schedules.values())

    async def start(self, check_callback=None) -> None:
        """
        Start the scheduler loop. Checks every 5 minutes for due devices.

        check_callback: async function(device_id, client_id, scope)
            called when a device is due for scanning.
        """
        self._running = True
        logger.info("Scan scheduler started with %d devices", len(self._schedules))

        while self._running:
            try:
                due = self.get_due_devices()
                if due:
                    logger.info("%d device(s) due for scanning", len(due))
                    for schedule in due:
                        if check_callback:
                            try:
                                await check_callback(
                                    schedule.device_id,
                                    schedule.client_id,
                                    schedule.scope,
                                )
                                schedule.mark_completed()
                            except Exception as exc:
                                logger.error(
                                    "Scan trigger failed for %s: %s",
                                    schedule.device_id,
                                    exc,
                                )
                                schedule.mark_failed()
            except Exception as exc:
                logger.exception("Scheduler loop error: %s", exc)

            await asyncio.sleep(300)  # Check every 5 minutes

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def load_from_db(self, db) -> int:
        """Load schedules from database."""
        rows = await db.fetch(
            """
            SELECT device_id, client_id, scope, interval_hours, enabled,
                   last_scan_at, next_scan_at
            FROM breach_scanner.scan_schedules
            WHERE enabled = true
            """
        )
        for row in rows:
            schedule = ScanSchedule(
                device_id=row["device_id"],
                client_id=row["client_id"],
                scope=ScanScope(row["scope"]),
                interval_hours=row["interval_hours"],
                enabled=row["enabled"],
            )
            schedule.last_scan_at = row["last_scan_at"]
            schedule.next_scan_at = row["next_scan_at"]
            self._schedules[schedule.device_id] = schedule

        logger.info("Loaded %d scan schedules from database", len(rows))
        return len(rows)

    async def save_to_db(self, db) -> None:
        """Persist all schedules to database."""
        for schedule in self._schedules.values():
            await db.execute(
                """
                INSERT INTO breach_scanner.scan_schedules
                    (device_id, client_id, scope, interval_hours, enabled,
                     last_scan_at, next_scan_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (device_id) DO UPDATE SET
                    scope = $3, interval_hours = $4, enabled = $5,
                    last_scan_at = $6, next_scan_at = $7,
                    updated_at = NOW()
                """,
                schedule.device_id,
                schedule.client_id,
                schedule.scope.value,
                schedule.interval_hours,
                schedule.enabled,
                schedule.last_scan_at,
                schedule.next_scan_at,
            )
