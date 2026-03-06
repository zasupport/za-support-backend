"""
Health Check AI v11.2
Production deployment - Render.com
Intelligence processing engine — receives Scout data, applies risk scoring,
monitors ISPs, runs security modules, and serves the Health Check AI dashboard.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import get_engine, Base
from app.api import health, devices, network, alerts, dashboard, diagnostics, isp, agent, system
from diagnostics.router import router as diagnostics_router
from app.modules.vault.router import router as vault_router
from app.modules.shield_agent.router import router as shield_router
from app.modules.app_intelligence.router import router as app_intelligence_router
from app.modules.interaction_analytics.router import router as interaction_analytics_router
from app.modules.breach_scanner.router import router as breach_scanner_router
from app.modules.forensics import forensics_router
from app.modules.diagnostics.router import router as diagnostic_storage_router
from app.modules.clients.router import router as clients_router
from app.modules.workshop.router import router as workshop_router
from app.modules.workshop import notifications as _workshop_notifications  # registers subscribers
from app.services import risk_trend_alerter as _risk_trend_alerter  # registers diagnostics.upload_received subscriber
from app.modules.reports.router import router as reports_router
from app.modules.cybershield.router import router as cybershield_router
from app.modules.customer_guides.router import router as guides_router
from app.api.agent_delivery import router as agent_delivery_router
from app.services.isp_scheduler import start_isp_scheduler, stop_isp_scheduler
from app.services.automation_scheduler import start_automation_scheduler, stop_automation_scheduler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Starting Health Check AI v11.2...")
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables verified.")
    start_isp_scheduler()
    start_automation_scheduler()
    logger.info("All schedulers started.")
    yield
    stop_automation_scheduler()
    stop_isp_scheduler()
    logger.info("Shutting down ZA Support Backend v11.2.")


app = FastAPI(
    title="Health Check AI API",
    version="11.2.0",
    description="Intelligence processing engine for ZA Support — ingests Scout data, applies risk scoring, monitors ISPs, runs security modules, and serves the Health Check AI dashboard.",
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
app.include_router(diagnostic_storage_router)  # must be before diagnostics.router — avoids /{id} catching /devices
app.include_router(diagnostics.router, prefix="/api/v1/diagnostics", tags=["Diagnostics"])
app.include_router(isp.router, prefix="/api/v1/isp", tags=["ISP Monitor"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])
app.include_router(system.router, prefix="/api/v1/system", tags=["System"])
app.include_router(diagnostics_router)
app.include_router(vault_router)
app.include_router(shield_router)
app.include_router(app_intelligence_router)
app.include_router(interaction_analytics_router)
app.include_router(breach_scanner_router, prefix="/api/v1/breach-scanner")
if forensics_router:
    app.include_router(forensics_router, prefix="/api/v1/forensics", tags=["Forensics"])
app.include_router(clients_router)
app.include_router(workshop_router)
app.include_router(reports_router)
app.include_router(cybershield_router)
app.include_router(guides_router)
app.include_router(agent_delivery_router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "Health Check AI API",
        "version": "11.2.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "devices": "/api/v1/devices",
            "diagnostics": "/api/v1/diagnostics",
            "alerts": "/api/v1/alerts",
            "dashboard": "/api/v1/dashboard",
            "network": "/api/v1/network",
            "isp": "/api/v1/isp",
            "agent": "/api/v1/agent",
            "system_events": "/api/v1/system/events",
            "system_jobs": "/api/v1/system/jobs",
            "system_status": "/api/v1/system/status",
            "shield": "/api/v1/shield",
            "app_intelligence": "/api/v1/app-intelligence",
            "interaction_analytics": "/api/v1/interaction-analytics",
            "breach_scanner": "/api/v1/breach-scanner",
            "forensics": "/api/v1/forensics",
            "diagnostic_storage": "/api/v1/diagnostics/devices",
            "clients": "/api/v1/clients",
            "workshop": "/api/v1/workshop",
            "reports":  "/api/v1/reports",
            "cybershield": "/api/v1/cybershield",
            "guides":      "/api/v1/guides",
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(settings.PORT), reload=settings.DEBUG)
