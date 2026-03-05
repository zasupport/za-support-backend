"""
Scan Orchestrator — coordinates all 6 device-side scanners,
aggregates findings, and triggers corroboration via the engine.

On the backend, this processes AgentScanReports submitted by the
Health Check agent. On-device, the agent runs scanners directly
and submits the raw report.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .config import ScannerConfig
from .corroboration_engine import CorroborationEngine
from .models import (
    AgentScanReport,
    CorroborationStatus,
    FindingResponse,
    FindingSeverity,
    RawFinding,
    ScanScope,
    ScanSessionResponse,
    ScanStatus,
)

logger = logging.getLogger(__name__)


class ScanOrchestrator:
    """
    Server-side orchestrator that processes agent scan reports.

    Flow:
    1. Agent runs scanners on device → produces RawFindings
    2. Agent submits AgentScanReport to backend
    3. Orchestrator receives report
    4. Each finding → corroboration engine → verdict
    5. Severity adjusted based on corroboration
    6. Findings stored in database
    7. Critical findings → alert pipeline
    """

    def __init__(self, corroboration_engine: CorroborationEngine) -> None:
        self._engine = corroboration_engine
        self._active_scans: dict[uuid.UUID, ScanSessionResponse] = {}

    async def process_agent_report(
        self,
        report: AgentScanReport,
        db=None,
    ) -> ScanSessionResponse:
        """
        Process a complete scan report from a Health Check agent.
        Corroborates each finding and returns the session summary.
        """
        scan_id = uuid.uuid4()
        started = datetime.now(timezone.utc)

        session = ScanSessionResponse(
            id=scan_id,
            client_id=report.client_id,
            device_id=report.device_id,
            scope=report.scan_scope,
            status=ScanStatus.CORROBORATING,
            os_platform=report.os_platform,
            started_at=report.scan_started_at,
            completed_at=None,
            duration_seconds=None,
            total_items_scanned=report.total_items_scanned,
            findings_count=len(report.findings),
            scanners_run=report.scanners_run,
        )

        self._active_scans[scan_id] = session
        logger.info(
            "Processing agent report: device=%s, findings=%d, scanners=%s",
            report.device_id,
            len(report.findings),
            report.scanners_run,
        )

        try:
            # Corroborate all findings
            corroborated_findings = await self._corroborate_findings(
                report.findings, scan_id
            )

            # Count severities
            critical = sum(
                1 for f in corroborated_findings if f.severity == FindingSeverity.CRITICAL
            )
            high = sum(
                1 for f in corroborated_findings if f.severity == FindingSeverity.HIGH
            )
            confirmed = sum(
                1
                for f in corroborated_findings
                if f.corroboration_status == CorroborationStatus.CONFIRMED_MALICIOUS
            )

            # Update session
            completed = datetime.now(timezone.utc)
            session.status = ScanStatus.COMPLETED
            session.completed_at = completed
            session.duration_seconds = int((completed - started).total_seconds())
            session.findings_count = len(corroborated_findings)
            session.critical_findings = critical
            session.high_findings = high
            session.confirmed_malicious = confirmed

            # Store in database if available
            if db:
                await self._store_session(db, session, corroborated_findings)

            logger.info(
                "Scan complete: device=%s, findings=%d, critical=%d, confirmed_malicious=%d",
                report.device_id,
                len(corroborated_findings),
                critical,
                confirmed,
            )

            return session

        except Exception as exc:
            session.status = ScanStatus.FAILED
            session.error_message = str(exc)
            logger.exception("Scan processing failed: %s", exc)
            return session
        finally:
            self._active_scans.pop(scan_id, None)

    async def _corroborate_findings(
        self, findings: list[RawFinding], scan_id: uuid.UUID
    ) -> list[FindingResponse]:
        """Corroborate each finding through the engine."""
        results: list[FindingResponse] = []

        # Process in batches to respect rate limits
        batch_size = 10
        for i in range(0, len(findings), batch_size):
            batch = findings[i : i + batch_size]
            batch_tasks = [
                self._corroborate_single(finding, scan_id) for finding in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error("Finding corroboration failed: %s", result)
                    continue
                if result is not None:
                    results.append(result)

        # Sort by severity (critical first)
        severity_order = {
            FindingSeverity.CRITICAL: 0,
            FindingSeverity.HIGH: 1,
            FindingSeverity.MEDIUM: 2,
            FindingSeverity.LOW: 3,
            FindingSeverity.INFO: 4,
        }
        results.sort(key=lambda f: severity_order.get(f.severity, 5))

        # Cap findings
        if len(results) > ScannerConfig.MAX_FINDINGS_PER_SCAN:
            logger.warning(
                "Findings capped at %d (had %d)",
                ScannerConfig.MAX_FINDINGS_PER_SCAN,
                len(results),
            )
            results = results[: ScannerConfig.MAX_FINDINGS_PER_SCAN]

        return results

    async def _corroborate_single(
        self, finding: RawFinding, scan_id: uuid.UUID
    ) -> Optional[FindingResponse]:
        """Corroborate a single finding and produce a FindingResponse."""
        try:
            status, confidence, details = await self._engine.corroborate_finding(finding)

            # Adjust severity based on corroboration
            adjusted_severity = self._engine.adjust_severity(
                finding.severity, status, confidence, details
            )

            return FindingResponse(
                id=uuid.uuid4(),
                scan_id=scan_id,
                category=finding.category,
                severity=adjusted_severity,
                title=finding.title,
                description=finding.description,
                file_path=finding.file_path,
                file_hash_sha256=finding.file_hash_sha256,
                process_name=finding.process_name,
                network_ip=finding.network_ip,
                network_domain=finding.network_domain,
                email_subject=finding.email_subject,
                attachment_name=finding.attachment_name,
                app_name=finding.app_name,
                extension_id=finding.extension_id,
                mitre_technique=finding.mitre_technique,
                mitre_tactic=finding.mitre_tactic,
                corroboration_status=status,
                corroboration_confidence=confidence,
                corroboration_details=details,
                recommended_action=finding.recommended_action,
                found_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.error("Failed to corroborate finding '%s': %s", finding.title, exc)
            return None

    async def _store_session(self, db, session, findings):
        """Store scan session and findings in database."""
        # Insert scan session
        await db.execute(
            """
            INSERT INTO breach_scanner.scan_sessions
                (id, client_id, device_id, scope, status, os_platform,
                 started_at, completed_at, duration_seconds,
                 total_items_scanned, findings_count, critical_findings,
                 high_findings, confirmed_malicious, scanners_run, error_message)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            """,
            session.id,
            session.client_id,
            session.device_id,
            session.scope.value,
            session.status.value,
            session.os_platform.value,
            session.started_at,
            session.completed_at,
            session.duration_seconds,
            session.total_items_scanned,
            session.findings_count,
            session.critical_findings,
            session.high_findings,
            session.confirmed_malicious,
            session.scanners_run,
            session.error_message,
        )

        # Insert findings
        for finding in findings:
            await db.execute(
                """
                INSERT INTO breach_scanner.scan_findings
                    (id, scan_id, category, severity, title, description,
                     file_path, file_hash_sha256, process_name,
                     network_ip, network_domain, email_subject,
                     attachment_name, app_name, extension_id,
                     mitre_technique, mitre_tactic,
                     corroboration_status, corroboration_confidence,
                     corroboration_details, recommended_action, found_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
                """,
                finding.id,
                finding.scan_id,
                finding.category.value,
                finding.severity.value,
                finding.title,
                finding.description,
                finding.file_path,
                finding.file_hash_sha256,
                finding.process_name,
                finding.network_ip,
                finding.network_domain,
                finding.email_subject,
                finding.attachment_name,
                finding.app_name,
                finding.extension_id,
                finding.mitre_technique,
                finding.mitre_tactic,
                finding.corroboration_status.value,
                finding.corroboration_confidence,
                [r.model_dump() for r in finding.corroboration_details],
                finding.recommended_action,
                finding.found_at,
            )

    def get_active_scans(self) -> list[ScanSessionResponse]:
        return list(self._active_scans.values())
