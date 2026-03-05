from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone, timedelta

from app.core.agent_auth import verify_agent_token
from app.core.database import get_db
from app.modules.app_intelligence import service
from app.modules.app_intelligence.schemas import (
    AppMetricsReport,
    StartupReport,
    AppClassificationCreate,
)

router = APIRouter(prefix="/api/v1/app-intelligence", tags=["app-intelligence"])


@router.post("/report", dependencies=[Depends(verify_agent_token)])
def post_metrics_report(payload: AppMetricsReport, db: Session = Depends(get_db)):
    return service.store_metrics_report(db, payload.device_id, payload.client_id, payload)


@router.post("/startup-report", dependencies=[Depends(verify_agent_token)])
def post_startup_report(payload: StartupReport, db: Session = Depends(get_db)):
    return service.store_startup_report(db, payload.device_id, payload.client_id, payload)


@router.get("/devices/{device_id}/app-health", dependencies=[Depends(verify_agent_token)])
def get_app_health(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_app_health(db, device_id, period_days)


@router.get("/devices/{device_id}/app-ranking", dependencies=[Depends(verify_agent_token)])
def get_app_ranking(
    device_id: str,
    period_days: int = Query(7),
    sort_by: str = Query("cpu"),
    db: Session = Depends(get_db),
):
    return service.get_app_ranking(db, device_id, period_days, sort_by)


@router.get("/devices/{device_id}/resource-timeline", dependencies=[Depends(verify_agent_token)])
def get_resource_timeline(
    device_id: str,
    app_bundle_id: str = Query(...),
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_resource_timeline(db, device_id, app_bundle_id, period_days)


@router.get("/devices/{device_id}/foreground-breakdown", dependencies=[Depends(verify_agent_token)])
def get_foreground_breakdown(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_foreground_breakdown(db, device_id, period_days)


@router.get("/devices/{device_id}/startup-history", dependencies=[Depends(verify_agent_token)])
def get_startup_history(
    device_id: str,
    period_days: int = Query(30),
    db: Session = Depends(get_db),
):
    return service.get_startup_history(db, device_id, period_days)


@router.get("/devices/{device_id}/productivity", dependencies=[Depends(verify_agent_token)])
def get_productivity(
    device_id: str,
    period_days: int = Query(28),
    db: Session = Depends(get_db),
):
    return service.get_productivity(db, device_id, period_days)


@router.get("/devices/{device_id}/context-switches", dependencies=[Depends(verify_agent_token)])
def get_context_switches(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        text("""
        SELECT
            DATE_TRUNC('hour', timestamp) AS hour,
            SUM(total_app_switches) AS total_switches,
            AVG(total_app_switches) AS avg_switches
        FROM app_daily_summary
        WHERE device_id = :device_id AND date >= :cutoff
        GROUP BY hour
        ORDER BY hour ASC
        """),
        {"device_id": device_id, "cutoff": cutoff.date()},
    )
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/devices/{device_id}/network-flags", dependencies=[Depends(verify_agent_token)])
def get_network_flags(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        text("""
        SELECT * FROM app_network_flags
        WHERE device_id = :device_id AND timestamp >= :cutoff
        ORDER BY timestamp DESC
        LIMIT 200
        """),
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/devices/{device_id}/responsiveness", dependencies=[Depends(verify_agent_token)])
def get_responsiveness(
    device_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        text("""
        SELECT
            app_name,
            app_bundle_id,
            AVG(responsiveness_score) AS avg_responsiveness,
            SUM(slow_interactions) AS total_slow,
            SUM(unresponsive_interactions) AS total_unresponsive,
            COUNT(*) AS sample_count
        FROM app_resource_metrics
        WHERE device_id = :device_id
          AND timestamp >= :cutoff
          AND responsiveness_score IS NOT NULL
        GROUP BY app_name, app_bundle_id
        ORDER BY avg_responsiveness ASC NULLS LAST
        """),
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/devices/{device_id}/recommendations", dependencies=[Depends(verify_agent_token)])
def get_recommendations(
    device_id: str,
    db: Session = Depends(get_db),
):
    return service.get_recommendations(db, device_id)


@router.get("/clients/{client_id}/fleet-health", dependencies=[Depends(verify_agent_token)])
def get_fleet_health(
    client_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    return service.get_fleet_health(db, client_id, period_days)


@router.get("/clients/{client_id}/worst-apps", dependencies=[Depends(verify_agent_token)])
def get_worst_apps(
    client_id: str,
    period_days: int = Query(7),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        text("""
        SELECT
            app_name,
            app_bundle_id,
            AVG(health_score) AS avg_health_score,
            COUNT(DISTINCT device_id) AS affected_devices
        FROM app_health_scores
        WHERE client_id = :client_id AND date >= :cutoff
        GROUP BY app_name, app_bundle_id
        HAVING AVG(health_score) < 70
        ORDER BY avg_health_score ASC NULLS LAST
        LIMIT 20
        """),
        {"client_id": client_id, "cutoff": cutoff.date()},
    )
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/clients/{client_id}/startup-comparison", dependencies=[Depends(verify_agent_token)])
def get_startup_comparison(
    client_id: str,
    period_days: int = Query(30),
    db: Session = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        text("""
        SELECT
            device_id,
            AVG(boot_to_ready_seconds) AS avg_boot_to_ready,
            AVG(login_to_ready_seconds) AS avg_login_to_ready,
            AVG(total_login_items) AS avg_login_items,
            COUNT(*) AS sample_count
        FROM startup_reports
        WHERE client_id = :client_id AND created_at >= :cutoff
        GROUP BY device_id
        ORDER BY avg_boot_to_ready DESC NULLS LAST
        """),
        {"client_id": client_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/report-data/{client_id}", dependencies=[Depends(verify_agent_token)])
def get_report_data(
    client_id: str,
    period_days: int = Query(30),
    db: Session = Depends(get_db),
):
    fleet_health = service.get_fleet_health(db, client_id, period_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

    worst_apps_result = db.execute(
        text("""
        SELECT app_name, app_bundle_id, AVG(health_score) AS avg_health_score,
               COUNT(DISTINCT device_id) AS affected_devices
        FROM app_health_scores
        WHERE client_id = :client_id AND date >= :cutoff
        GROUP BY app_name, app_bundle_id
        ORDER BY avg_health_score ASC NULLS LAST
        LIMIT 10
        """),
        {"client_id": client_id, "cutoff": cutoff.date()},
    )
    worst_apps = [dict(row._mapping) for row in worst_apps_result.fetchall()]

    return {
        "client_id": client_id,
        "period_days": period_days,
        "fleet_health": fleet_health,
        "worst_apps": worst_apps,
    }


@router.post("/config/{device_id}/app-classification", dependencies=[Depends(verify_agent_token)])
def set_app_classification(
    device_id: str,
    payload: AppClassificationCreate,
    db: Session = Depends(get_db),
):
    # device_id path param used for routing context; classification stored per client_id
    db.execute(
        text("""
        INSERT INTO app_classifications (client_id, app_bundle_id, app_name, classification, classified_by)
        VALUES (:client_id, :app_bundle_id, :app_name, :classification, :classified_by)
        ON CONFLICT (client_id, app_bundle_id)
        DO UPDATE SET
            classification = EXCLUDED.classification,
            app_name = EXCLUDED.app_name,
            classified_by = EXCLUDED.classified_by
        """),
        {
            "client_id": device_id,
            "app_bundle_id": payload.app_bundle_id,
            "app_name": payload.app_name,
            "classification": payload.classification,
            "classified_by": payload.classified_by,
        },
    )
    db.commit()
    return {"status": "saved", "app_bundle_id": payload.app_bundle_id, "classification": payload.classification}


@router.delete("/devices/{device_id}/data", dependencies=[Depends(verify_agent_token)])
def delete_device_data(
    device_id: str,
    db: Session = Depends(get_db),
):
    return service.delete_device_data(db, device_id)
