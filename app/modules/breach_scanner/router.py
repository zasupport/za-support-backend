"""
FastAPI Router — Compromised Data Scanner endpoints.

Prefix: /api/v1/breach-scanner
All operations require POPIA consent (enforced at service layer).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .models import (
    AgentScanReport,
    ConsentRecord,
    DashboardStats,
    DeviceScanSummary,
    FindingResponse,
    FindingSeverity,
    ScanRequest,
    ScanScope,
    ScanSessionResponse,
)
from .service import ConsentError, ScannerService

router = APIRouter(tags=["Compromised Data Scanner"])

# ── Singleton service (initialised on first use) ──────────────────────

_service: Optional[ScannerService] = None


async def get_service() -> ScannerService:
    global _service
    if _service is None:
        _service = ScannerService()
        await _service.initialise()
    return _service


# ── Error handler helper ──────────────────────────────────────────────


def _handle_consent_error(exc: ConsentError) -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "error": "consent_required",
            "message": str(exc),
            "action": "POST /api/v1/breach-scanner/consent to record consent",
        },
    )


# ── Health Check ──────────────────────────────────────────────────────


@router.get("/health")
async def health_check(service: ScannerService = Depends(get_service)):
    """Module health check — provider status and config."""
    return await service.initialise()


# ── Consent Management ────────────────────────────────────────────────


@router.post("/consent", status_code=201)
async def grant_consent(
    record: ConsentRecord,
    service: ScannerService = Depends(get_service),
):
    """
    Record POPIA consent for endpoint forensic scanning.
    Required before any scanning operations can be performed.
    """
    return await service.grant_consent(record)


@router.delete("/consent/{client_id}")
async def revoke_consent(
    client_id: uuid.UUID,
    service: ScannerService = Depends(get_service),
):
    """
    Revoke POPIA consent — stops all scanning and schedule for this client.
    Existing findings are retained for compliance record-keeping.
    """
    return await service.revoke_consent(client_id)


@router.get("/consent/{client_id}/status")
async def consent_status(
    client_id: uuid.UUID,
    service: ScannerService = Depends(get_service),
):
    """Check POPIA consent status for a client."""
    return await service.get_consent_status(client_id)


# ── Scan Operations ───────────────────────────────────────────────────


@router.post("/scan", status_code=202)
async def trigger_scan(
    request: ScanRequest,
    service: ScannerService = Depends(get_service),
):
    """
    Request a scan on a specific device.
    The Health Check agent will execute and report back.
    """
    try:
        return await service.trigger_scan(request)
    except ConsentError as exc:
        _handle_consent_error(exc)


@router.post("/submit-report", status_code=201)
async def submit_agent_report(
    report: AgentScanReport,
    service: ScannerService = Depends(get_service),
):
    """
    Receive a scan report from the Health Check agent.
    Triggers corroboration and alert processing.
    """
    try:
        session = await service.submit_agent_report(report)
        return session
    except ConsentError as exc:
        _handle_consent_error(exc)


# ── Findings ──────────────────────────────────────────────────────────


@router.get("/findings/{device_id}", response_model=list[FindingResponse])
async def get_device_findings(
    device_id: uuid.UUID,
    client_id: uuid.UUID = Query(...),
    include_resolved: bool = Query(False),
    severity: Optional[FindingSeverity] = Query(None),
    service: ScannerService = Depends(get_service),
):
    """Get all findings for a device."""
    try:
        return await service.get_device_findings(
            device_id, client_id, include_resolved, severity
        )
    except ConsentError as exc:
        _handle_consent_error(exc)


@router.get("/summary/{device_id}", response_model=DeviceScanSummary)
async def get_device_summary(
    device_id: uuid.UUID,
    client_id: uuid.UUID = Query(...),
    service: ScannerService = Depends(get_service),
):
    """Get comprehensive scan summary with risk score."""
    try:
        return await service.get_device_summary(device_id, client_id)
    except ConsentError as exc:
        _handle_consent_error(exc)


class ResolveRequest(BaseModel):
    resolved_by: str
    is_false_positive: bool = False


@router.post("/resolve-finding/{finding_id}")
async def resolve_finding(
    finding_id: uuid.UUID,
    body: ResolveRequest,
    client_id: uuid.UUID = Query(...),
    service: ScannerService = Depends(get_service),
):
    """Mark a finding as resolved or false positive."""
    try:
        return await service.resolve_finding(
            finding_id, client_id, body.resolved_by, body.is_false_positive
        )
    except ConsentError as exc:
        _handle_consent_error(exc)


# ── Dashboard ─────────────────────────────────────────────────────────


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    service: ScannerService = Depends(get_service),
):
    """Aggregate stats across all scanned devices."""
    return await service.get_dashboard()


# ── Schedule Management ───────────────────────────────────────────────


class ScheduleUpdate(BaseModel):
    scope: Optional[ScanScope] = None
    interval_hours: Optional[int] = None
    enabled: Optional[bool] = None


@router.put("/schedule/{device_id}")
async def update_schedule(
    device_id: uuid.UUID,
    body: ScheduleUpdate,
    client_id: uuid.UUID = Query(...),
    service: ScannerService = Depends(get_service),
):
    """Update or create a scan schedule for a device."""
    try:
        return await service.update_schedule(
            device_id, client_id, body.scope, body.interval_hours, body.enabled
        )
    except ConsentError as exc:
        _handle_consent_error(exc)
