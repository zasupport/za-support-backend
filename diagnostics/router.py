"""
ZA Support Diagnostics Endpoint
================================
Serves the macOS diagnostic export script via HTTP.
Client usage: curl -s https://api.zasupport.com/diagnostics/run | bash

Eliminates the Terminal paste buffer issue entirely.
Version: 3.0
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, JSONResponse

logger = logging.getLogger("diagnostics")

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

SCRIPTS_DIR = Path(__file__).parent / "scripts"
DEFAULT_SCRIPT = "diagnostic_export.sh"


def _get_script_content(version: str | None = None) -> str | None:
    """Read script content from file. Returns None if not found."""
    if version:
        filename = f"diagnostic_export_v{version}.sh"
    else:
        filename = DEFAULT_SCRIPT
    script_path = SCRIPTS_DIR / filename
    if not script_path.exists():
        return None
    return script_path.read_text(encoding="utf-8")


def _log_request(request: Request, version: str | None, served: bool):
    """Log diagnostic script request for usage tracking."""
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    user_agent = request.headers.get("user-agent", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()
    if served:
        logger.info(f"DIAGNOSTIC_SERVED | ip={client_ip} | ua={user_agent} | version={version or 'latest'} | {timestamp}")
    else:
        logger.warning(f"DIAGNOSTIC_NOT_FOUND | ip={client_ip} | ua={user_agent} | version={version or 'latest'} | {timestamp}")


@router.get("/run", response_class=PlainTextResponse)
async def serve_diagnostic_script(
    request: Request,
    v: str | None = Query(None, description="Script version (e.g. '2.1'). Omit for latest."),
):
    """
    Serve the macOS diagnostic export script as plain text.
    Usage: curl -s https://api.zasupport.com/diagnostics/run | bash
    """
    content = _get_script_content(version=v)

    if content is None:
        _log_request(request, v, served=False)
        error_script = (
            '#!/bin/bash\n'
            'echo ""\n'
            'echo "============================================"\n'
            'echo "  ⚠️  SCRIPT NOT AVAILABLE"\n'
            'echo "============================================"\n'
            'echo ""\n'
            f'echo "  Requested version: {v or "latest"}"\n'
            'echo "  The diagnostic script could not be loaded."\n'
            'echo "  Please contact ZA Support: admin@zasupport.com"\n'
            'echo "  Phone: 064 529 5863"\n'
            'echo ""\n'
            'echo "============================================"\n'
            'exit 1\n'
        )
        return PlainTextResponse(content=error_script, status_code=200)

    _log_request(request, v, served=True)
    return PlainTextResponse(content=content)


@router.get("/versions")
async def list_versions():
    """List all available diagnostic script versions."""
    versions = []

    if not SCRIPTS_DIR.exists():
        return JSONResponse(content={"versions": [], "latest": None})

    for f in sorted(SCRIPTS_DIR.glob("diagnostic_export*.sh")):
        name = f.stem
        if name == "diagnostic_export":
            versions.append({"version": "latest", "filename": f.name, "size_bytes": f.stat().st_size})
        elif name.startswith("diagnostic_export_v"):
            ver = name.replace("diagnostic_export_v", "")
            versions.append({"version": ver, "filename": f.name, "size_bytes": f.stat().st_size})

    latest = next((v for v in versions if v["version"] == "latest"), None)

    return JSONResponse(content={
        "versions": versions,
        "latest": latest,
        "usage": "curl -s https://api.zasupport.com/diagnostics/run | bash",
        "usage_versioned": "curl -s https://api.zasupport.com/diagnostics/run?v=2.1 | bash",
    })


@router.get("/health")
async def diagnostics_health():
    """Health check for diagnostics endpoint."""
    script_path = SCRIPTS_DIR / DEFAULT_SCRIPT
    script_exists = script_path.exists()
    script_size = script_path.stat().st_size if script_exists else 0

    return JSONResponse(content={
        "status": "ok" if script_exists else "warning",
        "script_available": script_exists,
        "script_size_bytes": script_size,
        "scripts_dir": str(SCRIPTS_DIR),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
