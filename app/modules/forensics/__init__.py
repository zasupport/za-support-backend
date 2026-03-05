"""
Health Check v11 — Forensics Module
=====================================
Optional forensic analysis module. Not loaded by default.

ACTIVATION
----------
Add to your main FastAPI app:

    from app.modules.forensics import forensics_router, FORENSICS_AVAILABLE
    
    if FORENSICS_AVAILABLE:
        app.include_router(
            forensics_router,
            prefix="/api/v1/forensics",
            tags=["Forensics"]
        )

Or unconditionally:

    from app.modules.forensics import forensics_router
    app.include_router(forensics_router, prefix="/api/v1/forensics", tags=["Forensics"])

POPIA NOTICE
------------
This module processes personal information as defined under POPIA (No. 4 of 2013).
- Written consent from the data subject is required before any analysis.
- All data access is logged in forensic_audit_log.
- Findings are indicators requiring human review — not confirmed incidents.
- Reports contain confidential information and must be handled accordingly.

SCOPE
-----
This module performs SOFTWARE-ONLY forensic analysis:
- Live system state (processes, network connections, open files)
- Disk artifacts (file metadata, deleted file indicators, carved files)
- Memory analysis (process lists, network sockets, injected code indicators)
- Log analysis (auth events, scheduled tasks, persistence mechanisms)
- Malware indicators (YARA pattern matching, suspicious strings)
- Network captures (traffic analysis, DNS queries, C2 indicators)

Hardware forensics (chip-level, firmware, physical write-blocking) is
coordinated separately at the time of hardware investigation.
"""

import logging

logger = logging.getLogger(__name__)

# Lazy import — only fail if someone actually tries to use the router
try:
    from .router import router as forensics_router
    from .service import ForensicsService
    from .tool_registry import ForensicToolRegistry
    from .models import (
        CreateInvestigationRequest,
        ConsentGrantRequest,
        InvestigationSummary,
        AnalysisScope,
        InvestigationStatus,
        FindingSeverity,
    )
    FORENSICS_AVAILABLE = True
    logger.info("Forensics module loaded successfully")
except ImportError as e:
    FORENSICS_AVAILABLE = False
    logger.warning(f"Forensics module dependencies not available: {e}")
    forensics_router = None
    ForensicsService = None
    ForensicToolRegistry = None

__all__ = [
    "forensics_router",
    "ForensicsService",
    "ForensicToolRegistry",
    "FORENSICS_AVAILABLE",
    "CreateInvestigationRequest",
    "ConsentGrantRequest",
    "InvestigationSummary",
    "AnalysisScope",
    "InvestigationStatus",
    "FindingSeverity",
]
