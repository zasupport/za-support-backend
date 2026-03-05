"""
Health Check AI — Networking Integrations Router Extension
============================================================
Additional FastAPI endpoints for Networking Integration providers.
Mount alongside the existing ISP monitor router.

Add to your main router.py imports and endpoints, or mount separately:

    from isp_outage_monitor.router_networking import router as networking_router
    app.include_router(networking_router, prefix="/api/v1/isp", tags=["Networking Integrations"])
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, BackgroundTasks

from .schemas import (
    ISPWebhookPayload,
    ProviderHealthResponse,
    StatusCheckResult,
)
from .networking_integrations import (
    NetworkingIntegrationManager,
    ISPWebhookHandler,
)

logger = logging.getLogger("healthcheck.isp_monitor.router_networking")
router = APIRouter()

# Shared instances — initialised by the scheduler/app startup
_networking_manager: Optional[NetworkingIntegrationManager] = None
_webhook_handler = ISPWebhookHandler()


def set_networking_manager(manager: NetworkingIntegrationManager):
    """Called during app startup to inject the shared manager."""
    global _networking_manager
    _networking_manager = manager


# ==========================================================
# ISP Webhook Receiver
# ==========================================================
@router.post("/webhooks/{isp_slug}", status_code=202)
async def receive_isp_webhook(
    isp_slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_webhook_signature: Optional[str] = Header(None),
):
    """
    Receive inbound status webhook from an ISP.

    ISPs that support push-based status updates send POST requests
    here when their status changes. Supports:
    - Statuspage.io webhook format
    - Generic JSON format
    - PagerDuty-style events

    The webhook is processed asynchronously to return 202 immediately.
    """
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload")

    # Verify signature if configured
    if x_webhook_signature:
        if not _webhook_handler.verify_signature(isp_slug, body, x_webhook_signature):
            raise HTTPException(401, "Invalid webhook signature")

    # Look up ISP ID from slug
    db = request.app.state.db_pool
    row = await db.fetchrow(
        "SELECT isp_id FROM isp_registry WHERE isp_slug = $1", isp_slug
    )
    if not row:
        raise HTTPException(404, f"ISP '{isp_slug}' not found in registry")

    isp_id = row["isp_id"]

    # Process in background
    background_tasks.add_task(_process_webhook, isp_id, isp_slug, payload, db)

    return {"status": "accepted", "isp_slug": isp_slug}


async def _process_webhook(isp_id: int, isp_slug: str, payload: dict, db):
    """Background task to process and store webhook result."""
    # Try Statuspage format first
    if "meta" in payload and "incident" in payload:
        result = _webhook_handler.process_statuspage_webhook(isp_id, isp_slug, payload)
    else:
        result = _webhook_handler.process_generic_webhook(isp_id, isp_slug, payload)

    if result:
        # Store the check result
        now = datetime.now(timezone.utc)
        await db.execute(
            """INSERT INTO isp_status_checks
               (check_time, isp_id, check_method, is_up, latency_ms,
                packet_loss_pct, status_code, raw_status, error_message, source)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            now, result.isp_id, result.check_method.value, result.is_up,
            result.latency_ms, result.packet_loss_pct, result.status_code,
            result.raw_status, result.error_message, result.source,
        )
        logger.info(f"Webhook processed for {isp_slug}: is_up={result.is_up}")


# ==========================================================
# Webhook Secret Management
# ==========================================================
@router.post("/webhooks/{isp_slug}/secret")
async def register_webhook_secret(isp_slug: str, request: Request):
    """
    Register a webhook signing secret for an ISP.
    Used to verify inbound webhook signatures.
    """
    body = await request.json()
    secret = body.get("secret")
    if not secret:
        raise HTTPException(400, "Missing 'secret' field")

    _webhook_handler.register_secret(isp_slug, secret)
    return {"status": "registered", "isp_slug": isp_slug}


# ==========================================================
# Country Health Check (South Africa)
# ==========================================================
@router.get("/country-health", response_model=ProviderHealthResponse)
async def get_country_health():
    """
    Get overall South Africa internet health from Cloudflare + IODA.
    Detects nationwide events: undersea cable cuts, Eskom load shedding
    impact on cell towers, WACS/SAT-3 cable issues, etc.
    """
    if not _networking_manager:
        raise HTTPException(503, "Networking integrations not initialised")

    results = await _networking_manager.check_country_health()

    # Parse results
    cloudflare_status = None
    ioda_status = None
    active_alerts = 0

    cf_data = results.get("cloudflare_za")
    if cf_data:
        anomalies = cf_data.get("anomalies", [])
        active_alerts += len(anomalies)
        cloudflare_status = "anomaly_detected" if anomalies else "normal"

    ioda_result = results.get("ioda_za")
    if ioda_result and isinstance(ioda_result, StatusCheckResult):
        if ioda_result.is_up is False:
            ioda_status = "disruption_detected"
            active_alerts += 1
        else:
            ioda_status = "normal"

    return ProviderHealthResponse(
        timestamp=datetime.now(timezone.utc),
        cloudflare_status=cloudflare_status,
        ioda_status=ioda_status,
        active_country_alerts=active_alerts,
        details=results,
    )


# ==========================================================
# Provider Status (which providers are active/configured)
# ==========================================================
@router.get("/providers")
async def get_provider_status():
    """
    List which networking integration providers are active and configured.
    Useful for the dashboard to show which data sources are feeding in.
    """
    from .config import config
    from .networking_integrations import (
        CLOUDFLARE_ASN_MAP,
        IODA_ENTITY_MAP,
        STATUSPAGE_API_MAP,
    )

    return {
        "networking_integrations_enabled": config.NETWORKING_INTEGRATIONS_ENABLED,
        "providers": {
            "cloudflare_radar": {
                "enabled": config.CLOUDFLARE_RADAR_ENABLED,
                "configured": bool(config.CLOUDFLARE_RADAR_TOKEN),
                "isps_covered": len([k for k, v in CLOUDFLARE_ASN_MAP.items() if v]),
                "check_interval_seconds": config.CLOUDFLARE_RADAR_CHECK_INTERVAL,
            },
            "ioda": {
                "enabled": config.IODA_ENABLED,
                "configured": True,     # no auth required
                "isps_covered": len(IODA_ENTITY_MAP),
                "country_check": config.IODA_COUNTRY_CHECK_ENABLED,
                "check_interval_seconds": config.IODA_CHECK_INTERVAL,
            },
            "ripe_atlas": {
                "enabled": config.RIPE_ATLAS_ENABLED,
                "configured": bool(config.RIPE_ATLAS_API_KEY),
                "check_interval_seconds": config.RIPE_ATLAS_CHECK_INTERVAL,
            },
            "statuspage_api": {
                "enabled": config.STATUSPAGE_API_ENABLED,
                "configured": True,     # no auth required
                "isps_covered": len(STATUSPAGE_API_MAP),
                "check_interval_seconds": config.STATUSPAGE_CHECK_INTERVAL,
            },
            "bgp_looking_glass": {
                "enabled": config.BGP_LOOKING_GLASS_ENABLED,
                "configured": True,     # uses free RIPE RIS
                "check_interval_seconds": config.BGP_CHECK_INTERVAL,
            },
            "webhooks": {
                "enabled": config.WEBHOOK_ENABLED,
                "endpoint": "/api/v1/isp/webhooks/{isp_slug}",
            },
        },
    }


# ==========================================================
# ISP Statuspage Components (detailed component status)
# ==========================================================
@router.get("/isps/{isp_slug}/components")
async def get_isp_components(isp_slug: str):
    """
    Get individual component statuses for ISPs that use Statuspage.io.
    Shows status of Fibre, DSL, Email, DNS, etc. separately.
    """
    if not _networking_manager or not _networking_manager.statuspage:
        raise HTTPException(503, "Statuspage provider not available")

    components = await _networking_manager.statuspage.get_components(isp_slug)
    if not components:
        raise HTTPException(404, f"No Statuspage components found for {isp_slug}")

    return {
        "isp_slug": isp_slug,
        "components": [
            {
                "name": c.get("name"),
                "status": c.get("status"),
                "description": c.get("description"),
                "updated_at": c.get("updated_at"),
            }
            for c in components
        ],
    }


# ==========================================================
# Scheduled Maintenance (from Statuspage ISPs)
# ==========================================================
@router.get("/isps/{isp_slug}/maintenance")
async def get_isp_maintenance(isp_slug: str):
    """
    Get upcoming scheduled maintenance windows for an ISP.
    Useful for: not alerting during planned maintenance,
    and proactively warning clients.
    """
    if not _networking_manager or not _networking_manager.statuspage:
        raise HTTPException(503, "Statuspage provider not available")

    maintenances = await _networking_manager.statuspage.get_scheduled_maintenances(isp_slug)

    return {
        "isp_slug": isp_slug,
        "upcoming_maintenance": [
            {
                "name": m.get("name"),
                "status": m.get("status"),
                "scheduled_for": m.get("scheduled_for"),
                "scheduled_until": m.get("scheduled_until"),
                "impact": m.get("impact"),
                "components": [
                    c.get("name") for c in m.get("components", [])
                ],
            }
            for m in maintenances
        ],
    }


# ==========================================================
# RIPE Atlas — Trigger on-demand measurement
# ==========================================================
@router.post("/isps/{isp_slug}/measure")
async def trigger_ripe_measurement(isp_slug: str, request: Request):
    """
    Trigger an on-demand RIPE Atlas measurement from SA probes
    to an ISP target. Useful for manual investigation.

    Body: { "target_ip": "196.x.x.x" }
    """
    if not _networking_manager or not _networking_manager.ripe_atlas:
        raise HTTPException(503, "RIPE Atlas provider not available")

    body = await request.json()
    target_ip = body.get("target_ip")
    if not target_ip:
        raise HTTPException(400, "Missing 'target_ip' field")

    msm_id = await _networking_manager.ripe_atlas.create_one_off_measurement(
        isp_slug=isp_slug,
        target_ip=target_ip,
        description=f"ZA Support manual check: {isp_slug}",
    )

    if msm_id:
        return {
            "status": "measurement_created",
            "measurement_id": msm_id,
            "results_url": f"https://atlas.ripe.net/measurements/{msm_id}/",
        }
    else:
        raise HTTPException(500, "Failed to create RIPE Atlas measurement")


# ==========================================================
# BGP Prefix Overview
# ==========================================================
@router.get("/isps/{isp_slug}/bgp")
async def get_isp_bgp_status(isp_slug: str):
    """
    Get BGP route visibility and announced prefixes for an ISP.
    Shows whether the ISP's routes are visible globally.
    """
    if not _networking_manager or not _networking_manager.bgp:
        raise HTTPException(503, "BGP provider not available")

    overview = await _networking_manager.bgp.get_prefix_overview(isp_slug)
    if not overview:
        raise HTTPException(404, f"No BGP data available for {isp_slug}")

    return {
        "isp_slug": isp_slug,
        "bgp_overview": overview,
    }


# ==========================================================
# IODA Time-Series (for charting)
# ==========================================================
@router.get("/isps/{isp_slug}/ioda-history")
async def get_isp_ioda_history(isp_slug: str, hours: int = 24):
    """
    Get IODA time-series data for an ISP — BGP, active probing,
    and darknet signals over time. Useful for dashboard charts.
    """
    if not _networking_manager or not _networking_manager.ioda:
        raise HTTPException(503, "IODA provider not available")

    timeseries = await _networking_manager.ioda.get_isp_timeseries(isp_slug, hours)
    if not timeseries:
        raise HTTPException(404, f"No IODA history for {isp_slug}")

    return {
        "isp_slug": isp_slug,
        "hours": hours,
        "timeseries": timeseries,
    }
