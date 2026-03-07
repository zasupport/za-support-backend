"""
Network telemetry submission and retrieval.
Includes UniFi Network Integration for client-site controllers.
  - Generic telemetry: /submit, /history (legacy, kept for compatibility)
  - UniFi-specific: /unifi/* (snapshots, live status, devices, config, cloud poll trigger)
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta, timezone
from typing import List

from app.core.database import get_db
from app.core.auth import verify_api_key
from app.modules.vault.encryption import encrypt_value, decrypt_value
from app.models.models import NetworkData, UniFiSnapshot, UniFiDeviceState, UniFiControllerConfig
from app.models.schemas import (
    NetworkSubmission,
    UniFiSnapshotSubmit, UniFiSnapshotOut, UniFiLiveStatus,
    UniFiDeviceOut, UniFiControllerConfigCreate,
)
from app.services.unifi_poller import store_snapshot, run_unifi_cloud_poll, UniFiCloudClient

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Legacy generic network telemetry (kept for compatibility)
# ─────────────────────────────────────────────────────────────

@router.post("/submit")
async def submit_network(
    payload: NetworkSubmission,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Submit generic network controller telemetry."""
    record = NetworkData(
        controller_id=payload.controller_id,
        total_clients=payload.total_clients,
        total_devices=payload.total_devices,
        wan_status=payload.wan_status,
        wan_latency_ms=payload.wan_latency_ms,
        raw_data=payload.raw_data,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "id": record.id}


@router.get("/history")
async def network_history(
    controller_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Get generic network telemetry history for a controller."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    records = (
        db.query(NetworkData)
        .filter(NetworkData.controller_id == controller_id, NetworkData.timestamp >= since)
        .order_by(desc(NetworkData.timestamp))
        .limit(500)
        .all()
    )
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "clients": r.total_clients,
            "devices": r.total_devices,
            "wan_status": r.wan_status,
            "wan_latency_ms": r.wan_latency_ms,
        }
        for r in records
    ]


# ─────────────────────────────────────────────────────────────
# UniFi Network Integration
# ─────────────────────────────────────────────────────────────

@router.post("/unifi/snapshot", summary="Ingest UniFi snapshot from local or cloud poller")
async def submit_unifi_snapshot(
    payload: UniFiSnapshotSubmit,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Accept a UniFi snapshot from the local poller script (runs on client LAN)
    or from the cloud poller service. Stores snapshot + upserts device states.
    """
    config = db.query(UniFiControllerConfig).filter_by(client_id=payload.client_id).first()
    if not config:
        # Auto-create a minimal config record so data is accepted
        config = UniFiControllerConfig(
            client_id=payload.client_id,
            controller_host=payload.controller_id,
            site_name=payload.site_name or "default",
        )
        db.add(config)
        db.flush()

    store_snapshot(db, config, payload.model_dump())
    return {"status": "ok", "client_id": payload.client_id}


@router.get("/unifi/live/{client_id}", response_model=UniFiLiveStatus, summary="Live UniFi status for a client site")
async def unifi_live_status(
    client_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Returns the most recent UniFi snapshot for the client — WAN status, throughput,
    connected client count, device health. Marks as stale if > 15 minutes old.
    """
    snapshot = (
        db.query(UniFiSnapshot)
        .filter_by(client_id=client_id)
        .order_by(desc(UniFiSnapshot.polled_at))
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"No UniFi data for client '{client_id}'")

    devices = (
        db.query(UniFiDeviceState)
        .filter_by(client_id=client_id)
        .all()
    )

    stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)
    polled_at = snapshot.polled_at
    if polled_at.tzinfo is None:
        polled_at = polled_at.replace(tzinfo=timezone.utc)

    uptime_hours = None
    if snapshot.uptime_seconds:
        uptime_hours = round(snapshot.uptime_seconds / 3600, 1)

    return UniFiLiveStatus(
        client_id         = client_id,
        controller_id     = snapshot.controller_id,
        as_of             = polled_at,
        wan_status        = snapshot.wan_status or "unknown",
        wan_ip            = snapshot.wan_ip,
        wan_rx_mbps       = snapshot.wan_rx_mbps,
        wan_tx_mbps       = snapshot.wan_tx_mbps,
        wan_latency_ms    = snapshot.wan_latency_ms,
        connected_clients = snapshot.connected_clients,
        wireless_clients  = snapshot.wireless_clients,
        wired_clients     = snapshot.wired_clients,
        devices_total     = snapshot.devices_total,
        devices_online    = snapshot.devices_online,
        site_name         = snapshot.site_name,
        uptime_hours      = uptime_hours,
        source            = snapshot.source or "unknown",
        stale             = polled_at < stale_threshold,
        devices           = [
            UniFiDeviceOut(
                mac              = d.mac,
                name             = d.name,
                model            = d.model,
                type             = d.type,
                ip               = d.ip,
                status           = d.status,
                uptime_seconds   = d.uptime_seconds,
                firmware_version = d.firmware_version,
                last_seen        = d.last_seen,
            )
            for d in devices
        ],
    )


@router.get("/unifi/history/{client_id}", response_model=List[UniFiSnapshotOut], summary="UniFi snapshot history")
async def unifi_history(
    client_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Returns time-series snapshots for a client site (default last 24h)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    snapshots = (
        db.query(UniFiSnapshot)
        .filter(UniFiSnapshot.client_id == client_id, UniFiSnapshot.polled_at >= since)
        .order_by(desc(UniFiSnapshot.polled_at))
        .limit(1000)
        .all()
    )
    return snapshots


@router.get("/unifi/devices/{client_id}", response_model=List[UniFiDeviceOut], summary="UniFi device states")
async def unifi_devices(
    client_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Returns latest device state (gateway, switches, APs) for a client site."""
    devices = db.query(UniFiDeviceState).filter_by(client_id=client_id).all()
    if not devices:
        raise HTTPException(status_code=404, detail=f"No device data for client '{client_id}'")
    return devices


@router.post("/unifi/config", summary="Register or update UniFi controller config for a client")
async def upsert_unifi_config(
    payload: UniFiControllerConfigCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Register a UniFi controller for a client. Credentials are encrypted before storage.
    Provide cloud_api_key for cloud polling (recommended) or username/password for
    local polling (used by the on-site poller script).
    """
    existing = db.query(UniFiControllerConfig).filter_by(client_id=payload.client_id).first()

    password_enc   = encrypt_value(payload.password)   if payload.password      else None
    cloud_key_enc  = encrypt_value(payload.cloud_api_key) if payload.cloud_api_key else None

    if existing:
        existing.controller_host   = payload.controller_host
        existing.controller_port   = payload.controller_port
        existing.username          = payload.username or existing.username
        existing.password_enc      = password_enc      or existing.password_enc
        existing.cloud_api_key_enc = cloud_key_enc     or existing.cloud_api_key_enc
        existing.site_name         = payload.site_name
        existing.poll_interval_sec = payload.poll_interval_sec
        existing.notes             = payload.notes or existing.notes
        existing.updated_at        = datetime.now(timezone.utc)
        db.commit()
        return {"status": "updated", "client_id": payload.client_id}

    config = UniFiControllerConfig(
        client_id         = payload.client_id,
        controller_host   = payload.controller_host,
        controller_port   = payload.controller_port,
        username          = payload.username,
        password_enc      = password_enc,
        cloud_api_key_enc = cloud_key_enc,
        site_name         = payload.site_name,
        poll_interval_sec = payload.poll_interval_sec,
        notes             = payload.notes,
    )
    db.add(config)
    db.commit()
    return {"status": "created", "client_id": payload.client_id}


@router.post("/unifi/poll/{client_id}", summary="Trigger immediate cloud poll for a client")
async def trigger_unifi_poll(
    client_id: str,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Manually trigger a cloud API poll for the specified client.
    Useful for on-demand refresh from the dashboard.
    """
    config = db.query(UniFiControllerConfig).filter_by(client_id=client_id, enabled=True).first()
    if not config:
        raise HTTPException(status_code=404, detail=f"No enabled UniFi config for '{client_id}'")
    if not config.cloud_api_key_enc:
        raise HTTPException(status_code=422, detail="No cloud API key configured — use local poller for this site")

    try:
        api_key = decrypt_value(config.cloud_api_key_enc)
        client_obj = UniFiCloudClient(api_key=api_key)
        payload = client_obj.build_snapshot_payload(
            controller_id=client_id,
            client_id=client_id,
            site_name=config.site_name,
        )
        store_snapshot(db, config, payload)
        return {"status": "ok", "wan_status": payload.get("wan_status"), "devices_online": payload.get("devices_online")}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"UniFi API error: {e}")
