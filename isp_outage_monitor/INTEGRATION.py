"""
Health Check v11 — ISP Outage Monitor Integration
==================================================
Updated: Includes Networking Integrations setup

Add this to your existing Health Check v11 FastAPI main.py
to wire up the ISP monitoring module with all providers.
"""

# ============================================================
# STEP 1: Add to requirements.txt / pyproject.toml
# ============================================================
# httpx>=0.27.0
# beautifulsoup4>=4.12.0
# pydantic-settings>=2.0.0
# (asyncpg, aioredis, fastapi already in Health Check)


# ============================================================
# STEP 2: Add to your main.py (FastAPI app)
# ============================================================
"""
# --- In your imports section ---
from isp_outage_monitor.router import router as isp_router
from isp_outage_monitor.router_networking import router as networking_router
from isp_outage_monitor.router_networking import set_networking_manager
from isp_outage_monitor.scheduler import ISPMonitorScheduler

# --- Mount both routers ---
app.include_router(
    isp_router,
    prefix="/api/v1/isp",
    tags=["ISP Monitor"],
)
app.include_router(
    networking_router,
    prefix="/api/v1/isp",
    tags=["Networking Integrations"],
)

# --- Initialise scheduler in startup event ---
@app.on_event("startup")
async def startup():
    # ... your existing startup code ...

    # ISP Outage Monitor (includes Networking Integrations)
    app.state.isp_scheduler = ISPMonitorScheduler(
        db_pool=app.state.db_pool,
        redis_client=app.state.redis,
    )
    await app.state.isp_scheduler.start()

    # Share the networking manager with the router
    if app.state.isp_scheduler.engine.networking:
        set_networking_manager(app.state.isp_scheduler.engine.networking)

@app.on_event("shutdown")
async def shutdown():
    # ... your existing shutdown code ...
    await app.state.isp_scheduler.stop()


# --- Fix the dependency injection in router.py ---
from fastapi import Request

async def get_db(request: Request):
    return request.app.state.db_pool

async def get_redis(request: Request):
    return request.app.state.redis
"""


# ============================================================
# STEP 3: Run database migration
# ============================================================
"""
psql -U healthcheck -d healthcheck -f isp_outage_monitor/migrations/001_isp_outage_tables.sql
"""


# ============================================================
# STEP 4: Add ISP monitoring to Health Check agent
# ============================================================
"""
In your Health Check agent's main loop (the code running on each client device):

from isp_outage_monitor.agent_connectivity import connectivity_check_loop

asyncio.create_task(connectivity_check_loop(
    api_url="https://healthcheck.zasupport.com",
    device_id=DEVICE_ID,
    client_id=CLIENT_ID,
    interval=60,
))
"""


# ============================================================
# STEP 5: Map Dr Shoul's practice to their ISP
# ============================================================
"""
POST /api/v1/isp/clients/isp
{
    "client_id": <dr_shoul_client_id>,
    "isp_id": <stem_isp_id>,
    "account_ref": "<Stem account number>",
    "connection_type": "fibre",
    "gateway_ip": "192.168.1.252",
    "site_name": "Dr Evan Shoul Practice",
    "is_primary": true
}
"""


# ============================================================
# STEP 6: Configure environment variables
# ============================================================
"""
Add to your .env file:

# ==============================================
# ISP Monitor — Core Settings
# ==============================================
ISP_MONITOR_STATUS_PAGE_CHECK_INTERVAL=300
ISP_MONITOR_DOWNDETECTOR_CHECK_INTERVAL=300
ISP_MONITOR_PING_CHECK_INTERVAL=60
ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT=180
ISP_MONITOR_OUTAGE_CONFIRMATION_THRESHOLD=3
ISP_MONITOR_OUTAGE_DEGRADED_THRESHOLD=10.0
ISP_MONITOR_ALERT_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
ISP_MONITOR_ALERT_COOLDOWN_MINS=30

# ==============================================
# Networking Integrations — Provider Settings
# ==============================================

# Master switch (disable all providers at once)
ISP_MONITOR_NETWORKING_INTEGRATIONS_ENABLED=true

# --- Cloudflare Radar ---
# Get free API token: https://dash.cloudflare.com/profile/api-tokens
# Create token with "Cloudflare Radar: Read" permission
ISP_MONITOR_CLOUDFLARE_RADAR_ENABLED=true
ISP_MONITOR_CLOUDFLARE_RADAR_TOKEN=your_cloudflare_api_token_here
ISP_MONITOR_CLOUDFLARE_RADAR_CHECK_INTERVAL=600

# --- IODA / CAIDA ---
# Free, no auth required — just enable
ISP_MONITOR_IODA_ENABLED=true
ISP_MONITOR_IODA_CHECK_INTERVAL=600
ISP_MONITOR_IODA_COUNTRY_CHECK_ENABLED=true

# --- RIPE Atlas ---
# Get free API key: https://atlas.ripe.net/keys/
# Free tier: 500,000 credits/day (ping = 10 credits per probe)
ISP_MONITOR_RIPE_ATLAS_ENABLED=true
ISP_MONITOR_RIPE_ATLAS_API_KEY=your_ripe_atlas_api_key_here
ISP_MONITOR_RIPE_ATLAS_CHECK_INTERVAL=900
ISP_MONITOR_RIPE_ATLAS_MAX_PROBES_PER_CHECK=5

# --- Statuspage.io API ---
# Free, no auth — reads public ISP status pages
ISP_MONITOR_STATUSPAGE_API_ENABLED=true
ISP_MONITOR_STATUSPAGE_CHECK_INTERVAL=300

# --- BGP / Looking Glass ---
# Free, uses RIPE RIS (Routing Information Service)
ISP_MONITOR_BGP_LOOKING_GLASS_ENABLED=true
ISP_MONITOR_BGP_CHECK_INTERVAL=900

# --- ISP Webhooks ---
# Receive push-based status from ISPs
ISP_MONITOR_WEBHOOK_ENABLED=true
"""


# ============================================================
# STEP 7: Register ISP webhook endpoints (optional)
# ============================================================
"""
For ISPs that support push-based status updates, register a
webhook secret for signature verification:

POST /api/v1/isp/webhooks/afrihost/secret
{
    "secret": "your_shared_secret_with_afrihost"
}

Then give the ISP your webhook URL:
https://healthcheck.zasupport.com/api/v1/isp/webhooks/afrihost

They'll POST status updates whenever their status changes.
"""


# ============================================================
# API ENDPOINT REFERENCE (Updated with Networking Integrations)
# ============================================================
"""
ISP Registry:
  GET    /api/v1/isp/isps                              List monitored ISPs
  POST   /api/v1/isp/isps                              Add new ISP
  PATCH  /api/v1/isp/isps/{isp_id}                     Update ISP settings

Client Mapping:
  GET    /api/v1/isp/clients/{client_id}/isp            Get client's ISP(s)
  POST   /api/v1/isp/clients/isp                        Map client to ISP

Dashboard:
  GET    /api/v1/isp/dashboard                          Real-time ISP status dashboard

Outages:
  GET    /api/v1/isp/outages                            List outage events
  GET    /api/v1/isp/outages?active_only=true           Active outages only
  POST   /api/v1/isp/outages                            Manual outage report
  PATCH  /api/v1/isp/outages/{id}                       Update (add ref#, resolve)

Reception Tools:
  GET    /api/v1/isp/outages/{id}/call-script           Auto-generated call script
  GET    /api/v1/isp/outages/{id}/fault-email           Auto-generated fault email

History & Stats:
  GET    /api/v1/isp/isps/{isp_id}/history              Check history (for charts)
  GET    /api/v1/isp/isps/{isp_id}/stats                Hourly aggregated stats

Agent Reporting:
  POST   /api/v1/isp/agent-report                       Device connectivity report

=== Networking Integrations (NEW) ===

Provider Status:
  GET    /api/v1/isp/providers                          Which providers are active

Country Health:
  GET    /api/v1/isp/country-health                     South Africa internet health

ISP Webhooks:
  POST   /api/v1/isp/webhooks/{isp_slug}               Receive ISP status webhook
  POST   /api/v1/isp/webhooks/{isp_slug}/secret         Register webhook secret

Statuspage Components:
  GET    /api/v1/isp/isps/{isp_slug}/components         ISP service component status
  GET    /api/v1/isp/isps/{isp_slug}/maintenance         Upcoming maintenance windows

RIPE Atlas:
  POST   /api/v1/isp/isps/{isp_slug}/measure            Trigger on-demand measurement

BGP:
  GET    /api/v1/isp/isps/{isp_slug}/bgp                BGP route visibility

IODA:
  GET    /api/v1/isp/isps/{isp_slug}/ioda-history        IODA time-series signals
"""


# ============================================================
# PROVIDER SETUP CHECKLIST
# ============================================================
"""
┌─────────────────────┬──────────┬───────────────────────────────────┐
│ Provider            │ Auth     │ Setup Required                    │
├─────────────────────┼──────────┼───────────────────────────────────┤
│ Cloudflare Radar    │ API Token│ Create token at Cloudflare dash   │
│ IODA / CAIDA        │ None     │ Just enable — free, no auth       │
│ RIPE Atlas          │ API Key  │ Register at atlas.ripe.net/keys   │
│ Statuspage.io API   │ None     │ Just enable — reads public pages  │
│ BGP / RIPE RIS      │ None     │ Just enable — free, no auth       │
│ ISP Webhooks        │ Secret   │ Register per-ISP shared secret    │
└─────────────────────┴──────────┴───────────────────────────────────┘

Minimum viable: Enable IODA + Statuspage + BGP (all free, no auth).
Add Cloudflare Radar + RIPE Atlas when API keys are available.
ISP Webhooks added per ISP as relationships are established.
"""
