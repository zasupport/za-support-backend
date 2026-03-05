"""
ISP Outage Monitor API — 15 endpoints under /api/v1/isp/
All endpoints require API key authentication.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.auth import verify_api_key
from app.core.database import get_db
from app.models.models import (
    ISPProvider, ISPStatusCheck, ISPOutage, AgentConnectivity, ISPStatus,
)
from app.models.schemas import (
    ISPProviderCreate, ISPProviderUpdate, ISPProviderResponse,
    StatusCheckSubmission, StatusCheckResponse,
    AgentHeartbeat, AgentConnectivityResponse,
    ISPOutageCreate, ISPOutageResponse,
    ISPProviderStatus, ISPDashboard,
)
from app.services.isp_seed import seed_isp_providers

router = APIRouter()


# ── Provider CRUD ─────────────────────────────────────────────

@router.get("/providers", response_model=List[ISPProviderResponse])
def list_providers(
    active_only: bool = True,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    query = db.query(ISPProvider)
    if active_only:
        query = query.filter(ISPProvider.is_active == True)
    return query.order_by(ISPProvider.name).all()


@router.get("/providers/{provider_id}", response_model=ISPProviderResponse)
def get_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    provider = db.query(ISPProvider).filter(ISPProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.post("/providers", response_model=ISPProviderResponse, status_code=201)
def create_provider(
    data: ISPProviderCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    existing = db.query(ISPProvider).filter(ISPProvider.slug == data.slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Provider with slug '{data.slug}' already exists")
    provider = ISPProvider(**data.model_dump())
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


@router.put("/providers/{provider_id}", response_model=ISPProviderResponse)
def update_provider(
    provider_id: int,
    data: ISPProviderUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    provider = db.query(ISPProvider).filter(ISPProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(provider, key, value)
    db.commit()
    db.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    provider = db.query(ISPProvider).filter(ISPProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider.is_active = False
    db.commit()
    return {"status": "success", "detail": f"Provider '{provider.name}' deactivated"}


# ── Status Checks ────────────────────────────────────────────

@router.post("/checks", response_model=StatusCheckResponse, status_code=201)
def submit_check(
    data: StatusCheckSubmission,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    provider = db.query(ISPProvider).filter(ISPProvider.id == data.provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    check = ISPStatusCheck(**data.model_dump())
    db.add(check)
    db.commit()
    db.refresh(check)
    return check


@router.get("/checks/{provider_id}", response_model=List[StatusCheckResponse])
def get_check_history(
    provider_id: int,
    hours: int = Query(24, ge=1, le=720),
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (
        db.query(ISPStatusCheck)
        .filter(
            ISPStatusCheck.provider_id == provider_id,
            ISPStatusCheck.timestamp >= cutoff,
        )
    )
    if source:
        query = query.filter(ISPStatusCheck.source == source)
    return query.order_by(ISPStatusCheck.timestamp.desc()).limit(500).all()


# ── Outages ──────────────────────────────────────────────────

@router.get("/outages", response_model=List[ISPOutageResponse])
def list_outages(
    provider_id: Optional[int] = None,
    active_only: bool = False,
    hours: int = Query(168, ge=1, le=8760),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = db.query(ISPOutage).filter(ISPOutage.started_at >= cutoff)
    if provider_id:
        query = query.filter(ISPOutage.provider_id == provider_id)
    if active_only:
        query = query.filter(ISPOutage.ended_at == None)
    return query.order_by(ISPOutage.started_at.desc()).all()


@router.get("/outages/current", response_model=List[ISPOutageResponse])
def current_outages(
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    return (
        db.query(ISPOutage)
        .filter(ISPOutage.ended_at == None)
        .order_by(ISPOutage.started_at.desc())
        .all()
    )


@router.post("/outages", response_model=ISPOutageResponse, status_code=201)
def create_outage(
    data: ISPOutageCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    provider = db.query(ISPProvider).filter(ISPProvider.id == data.provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    outage = ISPOutage(
        provider_id=data.provider_id,
        severity=data.severity,
        description=data.description,
        confirmed=True,
        confirmation_sources=["manual"],
    )
    db.add(outage)
    provider.current_status = data.severity
    db.commit()
    db.refresh(outage)
    return outage


@router.post("/outages/{outage_id}/resolve")
def resolve_outage(
    outage_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    outage = db.query(ISPOutage).filter(ISPOutage.id == outage_id).first()
    if not outage:
        raise HTTPException(status_code=404, detail="Outage not found")
    if outage.ended_at:
        raise HTTPException(status_code=409, detail="Outage already resolved")
    outage.ended_at = datetime.now(timezone.utc)
    outage.auto_resolved = False
    # Reset provider status
    provider = db.query(ISPProvider).filter(ISPProvider.id == outage.provider_id).first()
    if provider:
        provider.current_status = ISPStatus.OPERATIONAL.value
    db.commit()
    return {"status": "success", "detail": "Outage resolved"}


# ── Agent Heartbeat ──────────────────────────────────────────

@router.post("/heartbeat", status_code=201)
def submit_heartbeat(
    data: AgentHeartbeat,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    provider = db.query(ISPProvider).filter(ISPProvider.id == data.provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    record = AgentConnectivity(**data.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"status": "success", "id": record.id}


@router.get("/connectivity/{machine_id}", response_model=List[AgentConnectivityResponse])
def get_connectivity_history(
    machine_id: str,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return (
        db.query(AgentConnectivity)
        .filter(
            AgentConnectivity.machine_id == machine_id,
            AgentConnectivity.timestamp >= cutoff,
        )
        .order_by(AgentConnectivity.timestamp.desc())
        .limit(500)
        .all()
    )


# ── Status (simple list — used by dashboard frontend) ────────

@router.get("/status")
def isp_status(
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """Flat ISP status list — one entry per active provider."""
    providers = db.query(ISPProvider).filter(ISPProvider.is_active == True).order_by(ISPProvider.name).all()
    result = []
    for p in providers:
        recent = (
            db.query(ISPStatusCheck)
            .filter(ISPStatusCheck.provider_id == p.id)
            .order_by(ISPStatusCheck.timestamp.desc())
            .first()
        )
        result.append({
            "isp_name": p.name,
            "slug": p.slug,
            "status": p.current_status,
            "last_checked": recent.timestamp.isoformat() if recent else None,
            "latency_ms": getattr(recent, "latency_ms", None) if recent else None,
        })
    return result


# ── Dashboard ────────────────────────────────────────────────

@router.get("/dashboard", response_model=ISPDashboard)
def isp_dashboard(
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    providers = db.query(ISPProvider).filter(ISPProvider.is_active == True).all()
    active_outages = (
        db.query(ISPOutage)
        .filter(ISPOutage.ended_at == None)
        .order_by(ISPOutage.started_at.desc())
        .all()
    )

    # Build per-provider status
    provider_statuses = []
    operational = degraded = outage = unknown = 0

    for p in providers:
        recent_checks = (
            db.query(ISPStatusCheck)
            .filter(ISPStatusCheck.provider_id == p.id)
            .order_by(ISPStatusCheck.timestamp.desc())
            .limit(10)
            .all()
        )

        provider_outage = (
            db.query(ISPOutage)
            .filter(ISPOutage.provider_id == p.id, ISPOutage.ended_at == None)
            .first()
        )

        ps = ISPProviderStatus(
            provider=ISPProviderResponse.model_validate(p),
            recent_checks=[StatusCheckResponse.model_validate(c) for c in recent_checks],
            active_outage=ISPOutageResponse.model_validate(provider_outage) if provider_outage else None,
        )
        provider_statuses.append(ps)

        status = p.current_status
        if status == ISPStatus.OPERATIONAL.value:
            operational += 1
        elif status == ISPStatus.DEGRADED.value:
            degraded += 1
        elif status == ISPStatus.OUTAGE.value:
            outage += 1
        else:
            unknown += 1

    return ISPDashboard(
        total_providers=len(providers),
        operational_count=operational,
        degraded_count=degraded,
        outage_count=outage,
        unknown_count=unknown,
        active_outages=[ISPOutageResponse.model_validate(o) for o in active_outages],
        providers=provider_statuses,
    )


# ── Seed ─────────────────────────────────────────────────────

@router.post("/seed")
def seed_providers(
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    count = seed_isp_providers(db)
    return {"status": "success", "providers_seeded": count}
