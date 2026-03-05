"""
Health Check v11 — ISP Outage Monitor API Router
FastAPI endpoints for ISP monitoring, outage management,
real-time dashboard, and agent connectivity reporting.

Mount in your main Health Check app:
    from isp_outage_monitor.router import router as isp_router
    app.include_router(isp_router, prefix="/api/v1/isp", tags=["ISP Monitor"])
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse

from .schemas import (
    ISPCreate, ISPResponse,
    ClientISPCreate, ClientISPResponse,
    AgentConnectivityReport,
    OutageEventCreate, OutageEventUpdate, OutageEventResponse,
    StatusCheckResponse,
    ISPDashboardResponse, ISPCurrentStatus,
)
from .alerts import AlertManager

logger = logging.getLogger("healthcheck.isp_monitor.router")
router = APIRouter()


# ==========================================================
# Dependency: get DB pool and Redis from app state
# ==========================================================
async def get_db(request=None):
    """Get database pool from app state. Override in tests."""
    # This connects to your existing Health Check DB pool
    # In production: return request.app.state.db_pool
    raise NotImplementedError("Wire up to your Health Check app.state.db_pool")


async def get_redis(request=None):
    """Get Redis client from app state."""
    # In production: return request.app.state.redis
    raise NotImplementedError("Wire up to your Health Check app.state.redis")


# ==========================================================
# ISP Registry CRUD
# ==========================================================
@router.get("/isps", response_model=List[ISPResponse])
async def list_isps(
    enabled_only: bool = Query(True, description="Only show actively monitored ISPs"),
):
    """List all registered ISPs."""
    db = await get_db()
    query = "SELECT * FROM isp_registry"
    if enabled_only:
        query += " WHERE check_enabled = TRUE"
    query += " ORDER BY isp_name"
    rows = await db.fetch(query)
    return [ISPResponse(**dict(r)) for r in rows]


@router.post("/isps", response_model=ISPResponse, status_code=201)
async def create_isp(isp: ISPCreate):
    """Register a new ISP for monitoring."""
    db = await get_db()
    row = await db.fetchrow(
        """INSERT INTO isp_registry (isp_name, isp_slug, status_page_url,
           support_phone, support_email, check_enabled, check_interval)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING *""",
        isp.isp_name, isp.isp_slug, isp.status_page_url,
        isp.support_phone, isp.support_email, isp.check_enabled, isp.check_interval,
    )
    return ISPResponse(**dict(row))


@router.patch("/isps/{isp_id}")
async def update_isp(isp_id: int, updates: dict):
    """Update ISP settings (enable/disable, change interval, etc.)."""
    db = await get_db()
    allowed = {"check_enabled", "check_interval", "status_page_url",
               "support_phone", "support_email"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        raise HTTPException(400, "No valid fields to update")

    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(filtered))
    values = list(filtered.values())
    await db.execute(
        f"UPDATE isp_registry SET {sets}, updated_at = NOW() WHERE isp_id = $1",
        isp_id, *values,
    )
    return {"status": "updated"}


# ==========================================================
# Client-ISP Mapping
# ==========================================================
@router.get("/clients/{client_id}/isp", response_model=List[ClientISPResponse])
async def get_client_isps(client_id: int):
    """Get ISPs mapped to a client."""
    db = await get_db()
    rows = await db.fetch(
        "SELECT * FROM client_isp WHERE client_id = $1", client_id
    )
    return [ClientISPResponse(**dict(r)) for r in rows]


@router.post("/clients/isp", response_model=ClientISPResponse, status_code=201)
async def map_client_isp(mapping: ClientISPCreate):
    """Map a client to their ISP with circuit details."""
    db = await get_db()
    row = await db.fetchrow(
        """INSERT INTO client_isp
           (client_id, isp_id, account_ref, circuit_id, connection_type,
            ip_address, gateway_ip, site_name, is_primary)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           RETURNING *""",
        mapping.client_id, mapping.isp_id, mapping.account_ref,
        mapping.circuit_id, mapping.connection_type,
        mapping.ip_address, mapping.gateway_ip,
        mapping.site_name, mapping.is_primary,
    )
    return ClientISPResponse(**dict(row))


# ==========================================================
# Real-time Dashboard
# ==========================================================
@router.get("/dashboard", response_model=ISPDashboardResponse)
async def get_dashboard():
    """
    Real-time ISP status dashboard.
    Pulls from Redis cache for speed, falls back to DB.
    """
    db = await get_db()
    redis = await get_redis()

    isps = await db.fetch(
        "SELECT * FROM isp_registry WHERE check_enabled = TRUE ORDER BY isp_name"
    )

    statuses = []
    up = degraded = down = unknown = 0

    for isp in isps:
        isp_id = isp["isp_id"]

        # Try Redis cache first
        cached = await redis.get(f"isp:status:{isp_id}")
        if cached:
            data = json.loads(cached)
            is_up = data.get("is_up")
            has_outage = data.get("has_active_outage", False)
        else:
            # Fallback to DB
            latest = await db.fetchrow(
                """SELECT is_up, latency_ms, packet_loss_pct, check_time
                   FROM isp_status_checks WHERE isp_id = $1
                   ORDER BY check_time DESC LIMIT 1""",
                isp_id,
            )
            is_up = latest["is_up"] if latest else None
            has_outage = bool(await db.fetchval(
                "SELECT 1 FROM isp_outage_events WHERE isp_id = $1 AND ended_at IS NULL",
                isp_id,
            ))

        # Determine status label
        if has_outage:
            status_label = "Down"
            down += 1
        elif is_up is True:
            status_label = "Online"
            up += 1
        elif is_up is False:
            status_label = "Down"
            down += 1
        else:
            status_label = "Unknown"
            unknown += 1

        # Count affected clients
        client_count = await db.fetchval(
            "SELECT COUNT(*) FROM client_isp WHERE isp_id = $1", isp_id
        ) or 0

        # Get active outage details if any
        active_outage = None
        if has_outage:
            outage_row = await db.fetchrow(
                """SELECT o.*, r.isp_name FROM isp_outage_events o
                   JOIN isp_registry r ON o.isp_id = r.isp_id
                   WHERE o.isp_id = $1 AND o.ended_at IS NULL
                   ORDER BY o.started_at DESC LIMIT 1""",
                isp_id,
            )
            if outage_row:
                active_outage = OutageEventResponse(**dict(outage_row))

        statuses.append(ISPCurrentStatus(
            isp_id=isp_id,
            isp_name=isp["isp_name"],
            isp_slug=isp["isp_slug"],
            is_up=is_up,
            last_checked=datetime.now(timezone.utc),
            latency_ms=data.get("latency_ms") if cached else None,
            packet_loss_pct=data.get("packet_loss_pct") if cached else None,
            active_outage=active_outage,
            affected_client_count=client_count,
            status_label=status_label,
        ))

    active_outages = await db.fetchval(
        "SELECT COUNT(*) FROM isp_outage_events WHERE ended_at IS NULL"
    ) or 0

    return ISPDashboardResponse(
        timestamp=datetime.now(timezone.utc),
        total_isps_monitored=len(isps),
        isps_up=up,
        isps_degraded=degraded,
        isps_down=down,
        isps_unknown=unknown,
        active_outages=active_outages,
        statuses=statuses,
    )


# ==========================================================
# Outage Events
# ==========================================================
@router.get("/outages", response_model=List[OutageEventResponse])
async def list_outages(
    active_only: bool = Query(False),
    isp_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
):
    """List outage events with optional filters."""
    db = await get_db()
    conditions = []
    params = []
    idx = 1

    if active_only:
        conditions.append("o.ended_at IS NULL")
    if isp_id:
        conditions.append(f"o.isp_id = ${idx}")
        params.append(isp_id)
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = await db.fetch(
        f"""SELECT o.*, r.isp_name FROM isp_outage_events o
            JOIN isp_registry r ON o.isp_id = r.isp_id
            {where}
            ORDER BY o.started_at DESC
            LIMIT ${idx}""",
        *params, limit,
    )
    return [OutageEventResponse(**dict(r)) for r in rows]


@router.post("/outages", response_model=OutageEventResponse, status_code=201)
async def create_manual_outage(outage: OutageEventCreate):
    """Manually create an outage event (e.g. reported by client)."""
    db = await get_db()
    row = await db.fetchrow(
        """INSERT INTO isp_outage_events
           (isp_id, started_at, severity, detection_method, notes, auto_detected)
           VALUES ($1, NOW(), $2, $3, $4, $5)
           RETURNING *, (SELECT isp_name FROM isp_registry WHERE isp_id = $1) AS isp_name""",
        outage.isp_id, outage.severity, outage.detection_method or "manual",
        outage.notes, outage.auto_detected,
    )
    return OutageEventResponse(**dict(row))


@router.patch("/outages/{outage_id}", response_model=OutageEventResponse)
async def update_outage(outage_id: int, update: OutageEventUpdate):
    """
    Update an outage event (add ISP reference number, ETA, resolve, etc.).
    Use this after Kedibone gets the reference number from the ISP.
    """
    db = await get_db()
    sets = []
    params = [outage_id]
    idx = 2

    for field in ["ended_at", "severity", "isp_ref_number", "isp_eta", "notes"]:
        value = getattr(update, field, None)
        if value is not None:
            sets.append(f"{field} = ${idx}")
            params.append(value)
            idx += 1

    if not sets:
        raise HTTPException(400, "No fields to update")

    row = await db.fetchrow(
        f"""UPDATE isp_outage_events SET {', '.join(sets)}
            WHERE outage_id = $1
            RETURNING *, (SELECT isp_name FROM isp_registry WHERE isp_id = isp_outage_events.isp_id) AS isp_name""",
        *params,
    )
    if not row:
        raise HTTPException(404, "Outage not found")
    return OutageEventResponse(**dict(row))


# ==========================================================
# Agent Connectivity Reports
# ==========================================================
@router.post("/agent-report", status_code=202)
async def receive_agent_report(report: AgentConnectivityReport):
    """
    Receive connectivity report from a Health Check agent.
    Called by the agent every 60 seconds.
    """
    db = await get_db()
    await db.execute(
        """INSERT INTO agent_connectivity
           (report_time, device_id, client_id, is_online, wan_ip,
            gateway_ip, gateway_ping_ms, dns_resolves, latency_ms, packet_loss_pct)
           VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        report.device_id, report.client_id, report.is_online,
        report.wan_ip, report.gateway_ip, report.gateway_ping_ms,
        report.dns_resolves, report.latency_ms, report.packet_loss_pct,
    )
    return {"status": "accepted"}


# ==========================================================
# Status History (for charts)
# ==========================================================
@router.get("/isps/{isp_id}/history", response_model=List[StatusCheckResponse])
async def get_isp_history(
    isp_id: int,
    hours: int = Query(24, le=720, description="Hours of history"),
    method: Optional[str] = Query(None),
):
    """Get status check history for an ISP (for charting)."""
    db = await get_db()
    conditions = [f"s.isp_id = $1", f"s.check_time > NOW() - INTERVAL '{hours} hours'"]
    params = [isp_id]

    if method:
        conditions.append(f"s.check_method = $2")
        params.append(method)

    where = " AND ".join(conditions)
    rows = await db.fetch(
        f"""SELECT s.*, r.isp_name FROM isp_status_checks s
            JOIN isp_registry r ON s.isp_id = r.isp_id
            WHERE {where}
            ORDER BY s.check_time DESC
            LIMIT 500""",
        *params,
    )
    return [StatusCheckResponse(**dict(r)) for r in rows]


# ==========================================================
# Reception tools: auto-generated scripts
# ==========================================================
@router.get("/outages/{outage_id}/call-script", response_class=PlainTextResponse)
async def get_call_script(outage_id: int):
    """
    Generate a reception-friendly call script for an active outage.
    Kedibone can print this and read it word-for-word.
    """
    db = await get_db()
    outage = await db.fetchrow(
        """SELECT o.*, r.isp_slug, r.isp_name,
                  ci.account_ref, ci.site_name,
                  c.client_name, c.contact_phone, c.address
           FROM isp_outage_events o
           JOIN isp_registry r ON o.isp_id = r.isp_id
           LEFT JOIN client_isp ci ON ci.isp_id = o.isp_id
           LEFT JOIN clients c ON ci.client_id = c.client_id
           WHERE o.outage_id = $1
           LIMIT 1""",
        outage_id,
    )
    if not outage:
        raise HTTPException(404, "Outage not found")

    script = AlertManager.generate_call_script(
        isp_slug=outage["isp_slug"],
        practice_name=outage["site_name"] or outage["client_name"] or "The Practice",
        contact_name="Kedibone",
        account_ref=outage["account_ref"],
        practice_address=outage["address"] or "[practice address]",
        outage_start=outage["started_at"],
    )
    return script


@router.get("/outages/{outage_id}/fault-email")
async def get_fault_email(outage_id: int):
    """
    Generate a ready-to-send fault report email for an active outage.
    Returns JSON with to, subject, and body fields.
    """
    db = await get_db()
    outage = await db.fetchrow(
        """SELECT o.*, r.isp_slug, r.isp_name,
                  ci.account_ref, ci.site_name,
                  c.client_name, c.contact_phone, c.address
           FROM isp_outage_events o
           JOIN isp_registry r ON o.isp_id = r.isp_id
           LEFT JOIN client_isp ci ON ci.isp_id = o.isp_id
           LEFT JOIN clients c ON ci.client_id = c.client_id
           WHERE o.outage_id = $1
           LIMIT 1""",
        outage_id,
    )
    if not outage:
        raise HTTPException(404, "Outage not found")

    email = AlertManager.generate_fault_report_email(
        isp_slug=outage["isp_slug"],
        practice_name=outage["site_name"] or outage["client_name"] or "The Practice",
        contact_name="Kedibone",
        contact_number=outage["contact_phone"] or "[practice phone number]",
        practice_address=outage["address"] or "[practice address]",
        account_ref=outage["account_ref"],
        outage_start=outage["started_at"],
    )
    return email


# ==========================================================
# Hourly aggregated stats (for reports)
# ==========================================================
@router.get("/isps/{isp_id}/stats")
async def get_isp_stats(
    isp_id: int,
    hours: int = Query(24, le=720),
):
    """Get hourly aggregated stats for an ISP (uptime %, avg latency)."""
    db = await get_db()
    rows = await db.fetch(
        """SELECT bucket, total_checks, up_checks, down_checks,
                  avg_latency_ms, avg_packet_loss_pct,
                  ROUND(up_checks::numeric / NULLIF(total_checks, 0) * 100, 2) AS uptime_pct
           FROM isp_hourly_stats
           WHERE isp_id = $1
             AND bucket > NOW() - INTERVAL '%s hours'
           ORDER BY bucket DESC""" % hours,
        isp_id,
    )
    return [dict(r) for r in rows]
