"""
Forensics Module Router — Health Check AI
==========================================
API endpoints for forensic investigation management.

This module is OPTIONAL and must be explicitly loaded.
It is NOT included in the default Health Check AI router.

To activate, add to main.py:
    from app.modules.forensics.router import router as forensics_router
    app.include_router(forensics_router, prefix="/api/v1/forensics", tags=["Forensics"])

POPIA NOTICE: All endpoints that initiate or access forensic data require
recorded consent. Consent gate is enforced at the service layer.
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import FileResponse
from typing import Optional, List
from datetime import datetime
import os
import logging

from .models import (
    CreateInvestigationRequest,
    ConsentGrantRequest,
    InvestigationSummary,
    TaskSummary,
    FindingSchema,
    ToolStatusSchema,
    AnalysisScope,
    InvestigationStatus,
)
from sqlalchemy.orm import Session
from app.core.database import get_db
from .service import ForensicsService
from .tool_registry import ForensicToolRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


def get_service(db: Session = Depends(get_db)) -> ForensicsService:
    return ForensicsService(db_session=db)


def get_registry() -> ForensicToolRegistry:
    return ForensicToolRegistry()


# ---------------------------------------------------------------------------
# Tool Registry Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/tools",
    response_model=List[ToolStatusSchema],
    summary="List all forensic tools and their installation status",
    description=(
        "Returns the full catalogue of supported forensic tools with "
        "availability status on the current system. Use this to verify "
        "which tools are installed before starting an investigation."
    ),
)
async def list_tools(registry: ForensicToolRegistry = Depends(get_registry)):
    """Return tool catalogue with availability flags."""
    return registry.get_all_tools()


@router.get(
    "/tools/available",
    response_model=List[ToolStatusSchema],
    summary="List only installed forensic tools",
)
async def list_available_tools(registry: ForensicToolRegistry = Depends(get_registry)):
    """Return only tools that are currently installed and executable."""
    return registry.get_available_tools()


@router.get(
    "/tools/summary",
    summary="Tool availability summary",
    description="Returns a count of installed vs total tools per category.",
)
async def tool_summary(registry: ForensicToolRegistry = Depends(get_registry)):
    return registry.get_summary()


# ---------------------------------------------------------------------------
# Investigation Lifecycle Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/investigations",
    response_model=InvestigationSummary,
    status_code=201,
    summary="Create a new forensic investigation",
    description=(
        "Creates a new investigation record in PENDING state. "
        "Consent must be granted via the /consent endpoint before "
        "analysis can begin. "
        "POPIA: No data collection or analysis occurs at this stage."
    ),
)
async def create_investigation(
    request: CreateInvestigationRequest,
    service: ForensicsService = Depends(get_service),
):
    """Initialise a new forensic investigation."""
    try:
        investigation = await service.create_investigation(request)
        return investigation
    except Exception as e:
        logger.error(f"Failed to create investigation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/investigations/{investigation_id}/consent",
    response_model=InvestigationSummary,
    summary="Record POPIA consent for an investigation",
    description=(
        "Records the consent obtained from the data subject (device owner / "
        "authorised representative) before forensic analysis may proceed. "
        "Required fields: obtained_by (staff name), method (verbal/written/email), "
        "reference (consent form number or email reference). "
        "POPIA: This record is permanent and cannot be deleted."
    ),
)
async def grant_consent(
    investigation_id: str,
    request: ConsentGrantRequest,
    service: ForensicsService = Depends(get_service),
):
    """Record consent and advance investigation to CONSENT_GRANTED state."""
    try:
        investigation = await service.grant_consent(investigation_id, request)
        return investigation
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to record consent for {investigation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/investigations/{investigation_id}/start",
    response_model=InvestigationSummary,
    summary="Start forensic analysis",
    description=(
        "Begins the forensic analysis. Will fail if consent has not been "
        "recorded. Analysis runs in the background — poll the investigation "
        "status endpoint to track progress. "
        "Evidence is collected in volatile-first order: RAM → processes → "
        "network → disk."
    ),
)
async def start_investigation(
    investigation_id: str,
    service: ForensicsService = Depends(get_service),
):
    """Start forensic analysis (consent required)."""
    try:
        investigation = await service.start_investigation(investigation_id)

        # Emit event if critical/high findings found so workshop job can be auto-created
        critical = investigation.get("findings_critical", 0) or 0
        high     = investigation.get("findings_high",     0) or 0
        if critical > 0 or high > 0:
            import asyncio
            from app.core.event_bus import emit_event
            asyncio.create_task(emit_event("forensics.critical_findings", {
                "investigation_id":  investigation_id,
                "client_id":         investigation.get("client_id"),
                "device_id":         investigation.get("device_id"),
                "serial":            investigation.get("serial"),
                "findings_critical": critical,
                "findings_high":     high,
                "findings_total":    investigation.get("findings_total", critical + high),
                "scope":             investigation.get("scope", "unknown"),
            }))

        return investigation
    except PermissionError as e:
        raise HTTPException(
            status_code=403,
            detail=str(e) + " — Record consent first via /consent endpoint.",
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to start investigation {investigation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Investigation Status & Results
# ---------------------------------------------------------------------------

@router.get(
    "/investigations",
    response_model=List[InvestigationSummary],
    summary="List all investigations",
)
async def list_investigations(
    status: Optional[InvestigationStatus] = Query(
        None, description="Filter by status"
    ),
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    device_id: Optional[str] = Query(None, description="Filter by device ID"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: ForensicsService = Depends(get_service),
):
    """Return investigation list with optional filters."""
    return await service.list_investigations(
        status=status,
        client_id=client_id,
        device_id=device_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationSummary,
    summary="Get investigation details",
)
async def get_investigation(
    investigation_id: str,
    service: ForensicsService = Depends(get_service),
):
    """Return full investigation record including consent, tasks, and findings."""
    investigation = await service.get_investigation(investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation


@router.get(
    "/investigations/{investigation_id}/findings",
    response_model=List[FindingSchema],
    summary="Get findings for an investigation",
    description=(
        "Returns all indicators detected during analysis. "
        "Findings are indicators requiring human review — "
        "they are NOT confirmed incidents or policy violations."
    ),
)
async def get_findings(
    investigation_id: str,
    severity: Optional[str] = Query(
        None, description="Filter by severity: critical, high, medium, low, info"
    ),
    reviewed: Optional[bool] = Query(None, description="Filter by review status"),
    service: ForensicsService = Depends(get_service),
):
    """Return findings with optional severity and review-status filters."""
    return await service.get_findings(
        investigation_id, severity=severity, reviewed=reviewed
    )


@router.get(
    "/investigations/{investigation_id}/tasks",
    response_model=List[TaskSummary],
    summary="Get task execution details for an investigation",
)
async def get_tasks(
    investigation_id: str,
    service: ForensicsService = Depends(get_service),
):
    """Return individual tool task results for an investigation."""
    return await service.get_tasks(investigation_id)


# ---------------------------------------------------------------------------
# Report Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/investigations/{investigation_id}/report",
    summary="Generate investigation report",
    description=(
        "Generates PDF and JSON reports from completed investigation. "
        "Investigation must be in COMPLETE status. "
        "Reports include: consent record, chain of custody manifest, "
        "findings summary, executive summary (plain language), "
        "detailed indicator list, tool results, and POPIA disclaimer."
    ),
)
async def generate_report(
    investigation_id: str,
    service: ForensicsService = Depends(get_service),
):
    """Generate PDF and JSON reports for a completed investigation."""
    try:
        report_paths = await service.generate_report(investigation_id)
        return {
            "status": "generated",
            "pdf": report_paths.get("pdf"),
            "json": report_paths.get("json"),
            "text": report_paths.get("text"),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate report for {investigation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/investigations/{investigation_id}/report/pdf",
    summary="Download investigation PDF report",
    response_class=FileResponse,
)
async def download_pdf_report(
    investigation_id: str,
    service: ForensicsService = Depends(get_service),
):
    """Stream the PDF report for download."""
    report = await service.get_report(investigation_id)
    if not report or not report.get("pdf"):
        raise HTTPException(
            status_code=404,
            detail="PDF report not found. Generate it first via POST /report",
        )
    pdf_path = report["pdf"]
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk")
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"Forensic_Investigation_{investigation_id}.pdf",
    )


@router.get(
    "/investigations/{investigation_id}/report/json",
    summary="Download investigation JSON report (machine-readable)",
)
async def download_json_report(
    investigation_id: str,
    service: ForensicsService = Depends(get_service),
):
    """Return the JSON report as an API response."""
    import json

    report = await service.get_report(investigation_id)
    if not report or not report.get("json"):
        raise HTTPException(status_code=404, detail="JSON report not found")
    json_path = report["json"]
    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail="Report file not found on disk")
    with open(json_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Finding Review Endpoints (mark findings as reviewed / false positive)
# ---------------------------------------------------------------------------

@router.patch(
    "/investigations/{investigation_id}/findings/{finding_id}/review",
    summary="Mark a finding as reviewed",
    description=(
        "Records that a human analyst has reviewed this indicator. "
        "Use is_false_positive=true to dismiss indicators that do not "
        "represent genuine threats in context. "
        "Reviewer name is recorded for chain of custody."
    ),
)
async def review_finding(
    investigation_id: str,
    finding_id: str,
    reviewed_by: str = Query(..., description="Name of reviewing analyst"),
    is_false_positive: bool = Query(False),
    notes: Optional[str] = Query(None),
    service: ForensicsService = Depends(get_service),
):
    """Mark a finding as reviewed with analyst name."""
    try:
        return await service.review_finding(
            investigation_id=investigation_id,
            finding_id=finding_id,
            reviewed_by=reviewed_by,
            is_false_positive=is_false_positive,
            notes=notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Investigation Cancellation
# ---------------------------------------------------------------------------

@router.post(
    "/investigations/{investigation_id}/cancel",
    summary="Cancel a running or pending investigation",
)
async def cancel_investigation(
    investigation_id: str,
    reason: str = Query(..., description="Reason for cancellation"),
    service: ForensicsService = Depends(get_service),
):
    """Cancel an investigation. Completed investigations cannot be cancelled."""
    try:
        return await service.cancel_investigation(investigation_id, reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
