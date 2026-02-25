"""
Service health endpoint — used by Render, uptime monitors, and load balancers.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import get_db

router = APIRouter()


@router.get("/health")
async def service_health(db: Session = Depends(get_db)):
    """Liveness + readiness probe."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": "ZA Support Health Check API",
        "version": "11.1.0",
        "database": db_status,
    }
