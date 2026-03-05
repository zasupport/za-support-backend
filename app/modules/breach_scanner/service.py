"""
Service Layer — business logic for the Compromised Data Scanner.
POPIA consent gate enforced: no scanning or data access without
recorded consent from the client.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import ScannerConfig
from .corroboration_engine import CorroborationEngine
from .models import (
    AgentScanReport,
    ConsentRecord,
    ConsentStatus,
    CorroborationStatus,
    DashboardStats,
    DeviceScanSummary,
    FindingResponse,
    FindingSeverity,
    ScanRequest,
    ScanScope,
    ScanSessionResponse,
)
from .notification import NotificationService
from .risk_scorer import RiskScorer
from .scan_orchestrator import ScanOrchestrator
from .scheduler import ScanScheduler

logger = logging.getLogger(__name__)


class ConsentError(Exception):
    """Raised when an operation is attempted without POPIA consent."""


class ScannerService:
    """
    Central service layer — all external callers go through here.
    POPIA consent check is the first operation in every method.
    """

    def __init__(self, db=None) -> None:
        self._db = db
        self._engine = CorroborationEngine()
        self._orchestrator = ScanOrchestrator(self._engine)
        self._scheduler = ScanScheduler()
        self._notifications = NotificationService()
        self._scorer = RiskScorer()

        # In-memory consent store (backed by DB when available)
        self._consent: dict[uuid.UUID, ConsentRecord] = {}

    async def initialise(self) -> dict:
        """Start all subsystems and return health status."""
        await self._engine.initialise()
        config_warnings = ScannerConfig.validate()

        if self._db:
            await self._scheduler.load_from_db(self._db)

        health = await self._engine.provider_health()
        return {
            "status": "ready",
            "providers": health,
            "config_warnings": config_warnings,
            "schedules_loaded": len(self._scheduler.get_all_schedules()),
        }

    # ── Consent Management ────────────────────────────────────────────

    async def grant_consent(self, record: ConsentRecord) -> dict:
        """Record POPIA consent for endpoint scanning."""
        self._consent[record.client_id] = record

        if self._db:
            await self._db.execute(
                """
                INSERT INTO breach_scanner.breach_consent
                    (client_id, granted_by, granted_by_role, consent_scope, notes, status)
                VALUES ($1, $2, $3, $4, $5, 'granted')
                ON CONFLICT (client_id) DO UPDATE SET
                    granted_by = $2, granted_by_role = $3,
                    consent_scope = $4, notes = $5,
                    status = 'granted', granted_at = NOW()
                """,
                record.client_id,
                record.granted_by,
                record.granted_by_role,
                record.consent_scope,
                record.notes,
            )

        logger.info(
            "POPIA consent granted: client=%s by=%s (%s)",
            record.client_id,
            record.granted_by,
            record.granted_by_role,
        )
        return {"status": "granted", "client_id": str(record.client_id)}

    async def revoke_consent(self, client_id: uuid.UUID) -> dict:
        """Revoke POPIA consent — stops all scanning for this client."""
        self._consent.pop(client_id, None)

        if self._db:
            await self._db.execute(
                """
                UPDATE breach_scanner.breach_consent
                SET status = 'revoked', revoked_at = NOW()
                WHERE client_id = $1
                """,
                client_id,
            )

        # Remove all schedules for this client
        schedules = [
            s for s in self._scheduler.get_all_schedules()
            if s.client_id == client_id
        ]
        for s in schedules:
            self._scheduler.remove_device(s.device_id)

        logger.info("POPIA consent revoked: client=%s", client_id)
        return {"status": "revoked", "client_id": str(client_id)}

    async def get_consent_status(self, client_id: uuid.UUID) -> dict:
        """Check consent status for a client."""
        if client_id in self._consent:
            record = self._consent[client_id]
            return {
                "status": "granted",
                "granted_by": record.granted_by,
                "granted_by_role": record.granted_by_role,
                "scope": record.consent_scope,
            }

        if self._db:
            row = await self._db.fetchrow(
                """
                SELECT status, granted_by, granted_by_role, consent_scope
                FROM breach_scanner.breach_consent
                WHERE client_id = $1
                """,
                client_id,
            )
            if row and row["status"] == "granted":
                return {
                    "status": "granted",
                    "granted_by": row["granted_by"],
                    "granted_by_role": row["granted_by_role"],
                    "scope": row["consent_scope"],
                }

        return {"status": "not_granted"}

    def _require_consent(self, client_id: uuid.UUID) -> None:
        """Gate — raises ConsentError if no active consent."""
        if client_id not in self._consent:
            raise ConsentError(
                f"No POPIA consent on record for client {client_id}. "
                "Endpoint scanning requires explicit consent under POPIA Section 11. "
                "Use POST /consent to record consent before scanning."
            )

    # ── Scan Operations ───────────────────────────────────────────────

    async def submit_agent_report(
        self, report: AgentScanReport
    ) -> ScanSessionResponse:
        """Process a scan report submitted by the Health Check agent."""
        self._require_consent(report.client_id)

        session = await self._orchestrator.process_agent_report(report, self._db)

        # Process notifications
        await self._notifications.process_scan_results(
            session=session,
            findings=[],  # Findings stored in orchestrator
            client_name=str(report.client_id),
            device_hostname=report.hostname,
        )

        return session

    async def trigger_scan(self, request: ScanRequest) -> dict:
        """
        Signal a device to initiate a scan.
        Returns a scan request acknowledgment — the actual scan
        happens on the device and results come back via submit_agent_report.
        """
        self._require_consent(request.client_id)

        # Register or update schedule
        self._scheduler.add_device(
            device_id=request.device_id,
            client_id=request.client_id,
            scope=request.scope,
        )

        return {
            "status": "scan_requested",
            "device_id": str(request.device_id),
            "scope": request.scope.value,
            "message": (
                "Scan request queued. The Health Check agent on this device "
                "will execute the scan and submit results."
            ),
        }

    # ── Finding Queries ───────────────────────────────────────────────

    async def get_device_findings(
        self,
        device_id: uuid.UUID,
        client_id: uuid.UUID,
        include_resolved: bool = False,
        severity_filter: Optional[FindingSeverity] = None,
    ) -> list[FindingResponse]:
        """Get findings for a device."""
        self._require_consent(client_id)

        if not self._db:
            return []

        query = """
            SELECT * FROM breach_scanner.scan_findings f
            JOIN breach_scanner.scan_sessions s ON f.scan_id = s.id
            WHERE s.device_id = $1 AND s.client_id = $2
        """
        params = [device_id, client_id]

        if not include_resolved:
            query += " AND f.resolved_at IS NULL"

        if severity_filter:
            query += f" AND f.severity = ${len(params) + 1}"
            params.append(severity_filter.value)

        query += " ORDER BY f.found_at DESC LIMIT 200"

        rows = await self._db.fetch(query, *params)
        return [self._row_to_finding(row) for row in rows]

    async def get_device_summary(
        self,
        device_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> DeviceScanSummary:
        """Get comprehensive scan summary for a device."""
        self._require_consent(client_id)

        findings = await self.get_device_findings(device_id, client_id)
        all_findings = await self.get_device_findings(
            device_id, client_id, include_resolved=True
        )

        active_threats = sum(
            1 for f in findings
            if f.corroboration_status == CorroborationStatus.CONFIRMED_MALICIOUS
        )

        # Category breakdown
        by_category = {}
        by_severity = {}
        for f in findings:
            by_category[f.category.value] = by_category.get(f.category.value, 0) + 1
            by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1

        risk = self._scorer.calculate_device_risk(findings)

        return DeviceScanSummary(
            device_id=device_id,
            client_id=client_id,
            hostname=None,
            os_platform=findings[0].corroboration_details[0].source.value if findings else "macos",
            last_scan=None,
            total_scans=0,
            total_findings=len(all_findings),
            active_threats=active_threats,
            risk_score=risk,
            findings_by_category=by_category,
            findings_by_severity=by_severity,
            top_findings=findings[:10],
        )

    async def resolve_finding(
        self,
        finding_id: uuid.UUID,
        client_id: uuid.UUID,
        resolved_by: str,
        is_false_positive: bool = False,
    ) -> dict:
        """Mark a finding as resolved."""
        self._require_consent(client_id)

        if self._db:
            await self._db.execute(
                """
                UPDATE breach_scanner.scan_findings
                SET resolved_at = NOW(), resolved_by = $2,
                    is_false_positive = $3
                WHERE id = $1
                """,
                finding_id,
                resolved_by,
                is_false_positive,
            )

        action = "false_positive" if is_false_positive else "resolved"
        logger.info("Finding %s marked as %s by %s", finding_id, action, resolved_by)
        return {"status": action, "finding_id": str(finding_id)}

    # ── Dashboard ─────────────────────────────────────────────────────

    async def get_dashboard(self) -> DashboardStats:
        """Aggregate stats across all devices."""
        provider_health = await self._engine.provider_health()

        if not self._db:
            return DashboardStats(
                total_devices_scanned=0,
                total_scans_run=0,
                total_findings=0,
                active_threats=0,
                confirmed_malicious_total=0,
                devices_at_critical_risk=0,
                most_common_categories={},
                most_common_mitre_techniques={},
                last_scan_at=None,
                provider_health=provider_health,
            )

        stats = await self._db.fetchrow(
            """
            SELECT
                COUNT(DISTINCT device_id) as devices,
                COUNT(*) as scans,
                MAX(completed_at) as last_scan
            FROM breach_scanner.scan_sessions
            WHERE status = 'completed'
            """
        )

        finding_stats = await self._db.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE corroboration_status = 'confirmed_malicious' AND resolved_at IS NULL) as active_threats,
                COUNT(*) FILTER (WHERE corroboration_status = 'confirmed_malicious') as confirmed_total
            FROM breach_scanner.scan_findings
            """
        )

        category_rows = await self._db.fetch(
            """
            SELECT category, COUNT(*) as cnt
            FROM breach_scanner.scan_findings
            WHERE resolved_at IS NULL
            GROUP BY category ORDER BY cnt DESC LIMIT 10
            """
        )

        technique_rows = await self._db.fetch(
            """
            SELECT mitre_technique, COUNT(*) as cnt
            FROM breach_scanner.scan_findings
            WHERE mitre_technique IS NOT NULL AND resolved_at IS NULL
            GROUP BY mitre_technique ORDER BY cnt DESC LIMIT 10
            """
        )

        return DashboardStats(
            total_devices_scanned=stats["devices"] or 0,
            total_scans_run=stats["scans"] or 0,
            total_findings=finding_stats["total"] or 0,
            active_threats=finding_stats["active_threats"] or 0,
            confirmed_malicious_total=finding_stats["confirmed_total"] or 0,
            devices_at_critical_risk=0,  # Calculated from risk scores
            most_common_categories={r["category"]: r["cnt"] for r in category_rows},
            most_common_mitre_techniques={r["mitre_technique"]: r["cnt"] for r in technique_rows},
            last_scan_at=stats["last_scan"],
            provider_health=provider_health,
        )

    # ── Schedule Management ───────────────────────────────────────────

    async def update_schedule(
        self,
        device_id: uuid.UUID,
        client_id: uuid.UUID,
        scope: Optional[ScanScope] = None,
        interval_hours: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> dict:
        """Update scan schedule for a device."""
        self._require_consent(client_id)

        schedule = self._scheduler.update_schedule(
            device_id, scope, interval_hours, enabled
        )
        if not schedule:
            # Create new schedule
            schedule = self._scheduler.add_device(
                device_id, client_id, scope or ScanScope.FULL, interval_hours
            )

        if self._db:
            await self._scheduler.save_to_db(self._db)

        return {
            "device_id": str(device_id),
            "scope": schedule.scope.value,
            "interval_hours": schedule.interval_hours,
            "enabled": schedule.enabled,
            "next_scan_at": schedule.next_scan_at.isoformat() if schedule.next_scan_at else None,
        }

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_finding(row) -> FindingResponse:
        """Convert a database row to a FindingResponse."""
        from .models import FindingCategory

        return FindingResponse(
            id=row["id"],
            scan_id=row["scan_id"],
            category=FindingCategory(row["category"]),
            severity=FindingSeverity(row["severity"]),
            title=row["title"],
            description=row["description"],
            file_path=row.get("file_path"),
            file_hash_sha256=row.get("file_hash_sha256"),
            process_name=row.get("process_name"),
            network_ip=row.get("network_ip"),
            network_domain=row.get("network_domain"),
            email_subject=row.get("email_subject"),
            attachment_name=row.get("attachment_name"),
            app_name=row.get("app_name"),
            extension_id=row.get("extension_id"),
            mitre_technique=row.get("mitre_technique"),
            mitre_tactic=row.get("mitre_tactic"),
            corroboration_status=CorroborationStatus(row["corroboration_status"]),
            corroboration_confidence=row["corroboration_confidence"],
            recommended_action=row.get("recommended_action"),
            found_at=row["found_at"],
            resolved_at=row.get("resolved_at"),
            resolved_by=row.get("resolved_by"),
            is_false_positive=row.get("is_false_positive", False),
        )
