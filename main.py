"""
ZA Support Health Check Backend v11.1
Production deployment - Render.com
Includes diagnostic upload endpoint for za_diag_v3.sh
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import get_engine, Base
from app.api import health, devices, network, alerts, dashboard, diagnostics
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Starting ZA Support Backend v11.1...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables verified.")
    yield
    logger.info("Shutting down ZA Support Backend v11.1.")


app = FastAPI(
    title="ZA Support Health Check API",
    version="11.1.0",
    description="Device health monitoring, diagnostic ingestion, and predictive alerting for ZA Support clients.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Route Registration ---
app.include_router(health.router, tags=["Health"])
app.include_router(devices.router, prefix="/api/v1/devices", tags=["Devices"])
app.include_router(network.router, prefix="/api/v1/network", tags=["Network"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(diagnostics.router, prefix="/api/v1/diagnostics", tags=["Diagnostics"])


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "ZA Support Health Check API",
        "version": "11.1.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "devices": "/api/v1/devices",
            "diagnostics": "/api/v1/diagnostics",
            "alerts": "/api/v1/alerts",
            "dashboard": "/api/v1/dashboard",
            "network": "/api/v1/network",
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(settings.PORT), reload=settings.DEBUG)
