# Health Check v11

## Stack
- FastAPI backend, PostgreSQL + TimescaleDB, Redis, asyncpg, httpx
- Deployed on Render
- Agent runs on client macOS devices, reports every 60s

## Key Modules
- ISP Outage Monitor: `/isp_outage_monitor/`, API prefix `/api/v1/isp/`
- Agent connectivity: `agent_connectivity.py`
- 4-layer detection: Status page scraper, Downdetector ZA, HTTP probe, agent connectivity

## Database
- TimescaleDB hypertables for time-series (isp_status_checks, agent_connectivity)
- Retention: 90 days detailed, 2 years aggregated
- 13 pre-seeded SA ISPs

## Environment Variables
- ISP_MONITOR_STATUS_PAGE_CHECK_INTERVAL=300
- ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT=180
- ISP_MONITOR_OUTAGE_CONFIRMATION_THRESHOLD=3
- ISP_MONITOR_OUTAGE_DEGRADED_THRESHOLD=10.0
- ISP_MONITOR_ALERT_COOLDOWN_MINS=30

## Clients
- Dr Evan Shoul → Stem ISP, X-DSL underlying, gateway 192.168.1.252
- Charles Chemel → NTT Data ISP, UniFi Site Manager
