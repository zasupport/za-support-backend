# ZA Support — Health Check v11
# Project: za-support-backend
# Repo: https://github.com/zasupport/za-support-backend
# Working directory: /Users/courtneybentley/Developer/za-support-backend/
# Live API: https://api.zasupport.com (Render — Frankfurt region)

---

## PROJECT PURPOSE

This is the V11 FastAPI backend. It receives diagnostic data from client Macs,
stores it in TimescaleDB, powers the dashboard, and serves the diagnostic script
via curl delivery. This is a SEPARATE project from V3 (za-support-diagnostics).

---

## STACK

- FastAPI + Uvicorn
- PostgreSQL + TimescaleDB (time-series hypertables)
- Redis (caching, pub/sub)
- asyncpg (async DB driver)
- httpx (async HTTP client)
- Deployed: Render (Frankfurt region, auto-deploy on push to main)
- Custom domain: api.zasupport.com (CNAME → za-health-check-v11.onrender.com)

---

## REPO STRUCTURE

```
app/
  api/              ← FastAPI route handlers
  core/
    config.py       ← Settings (AGENT_AUTH_TOKEN, AGENT_AUTH_TOKEN_OLD, DATABASE_URL)
    agent_auth.py   ← verify_agent_token() — dual-token rotation support
    database.py     ← asyncpg pool setup
  models/           ← SQLAlchemy models
  services/         ← Business logic
diagnostics/
  __init__.py
  router.py         ← /diagnostics/run, /diagnostics/versions, /diagnostics/health
  scripts/
    diagnostic_export.sh  ← 120-section standalone curl-deliverable script (3190 lines)
isp_outage_monitor/       ← 4-layer ISP detection, 13 SA ISPs, APScheduler
main.py                   ← App entry point, includes all routers
```

---

## KEY ENDPOINTS

| Endpoint | Purpose |
|----------|---------|
| GET /diagnostics/run | Serves 120-section bash script (curl \| bash delivery) |
| GET /diagnostics/health | Script availability check |
| POST /api/v1/agent/diagnostics | Receives V3 JSON push (DiagnosticSubmission) |
| POST /api/v1/agent/heartbeat | Agent heartbeat |
| GET /api/v1/isp/status | ISP outage status |

---

## AGENT AUTH

- Primary token: `AGENT_AUTH_TOKEN` env var on Render
- Fallback token: `AGENT_AUTH_TOKEN_OLD` env var (for rotation, empty = disabled)
- Header: `Authorization: Bearer <token>`
- Dual-token support in: app/core/agent_auth.py

DiagnosticSubmission schema:
```json
{ "serial": "...", "hostname": "...", "client_id": "...", "payload": {} }
```

---

## DATABASE

- TimescaleDB hypertables: isp_status_checks, agent_connectivity
- Retention: 90 days detailed, 2 years aggregated
- 13 pre-seeded SA ISPs

---

## ENVIRONMENT VARIABLES (Render)

```
DATABASE_URL                    PostgreSQL connection string
REDIS_URL                       Redis connection string
AGENT_AUTH_TOKEN                Primary agent auth bearer token
AGENT_AUTH_TOKEN_OLD            Rotation fallback (empty = disabled)
ISP_MONITOR_STATUS_PAGE_CHECK_INTERVAL=300
ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT=180
ISP_MONITOR_OUTAGE_CONFIRMATION_THRESHOLD=3
ISP_MONITOR_OUTAGE_DEGRADED_THRESHOLD=10.0
ISP_MONITOR_ALERT_COOLDOWN_MINS=30
```

---

## WHAT IS DONE

- [x] FastAPI core + ISP outage monitor (4-layer detection, 13 SA ISPs)
- [x] Agent heartbeat + connectivity tracking
- [x] Diagnostics endpoint (/diagnostics/run serves curl-deliverable bash script)
- [x] 120-section standalone diagnostic_export.sh (3190 lines, no deps)
- [x] Custom domain api.zasupport.com with TLS
- [x] Dual-token agent auth rotation (AGENT_AUTH_TOKEN_OLD)
- [x] DiagnosticSubmission endpoint — receives V3 JSON push
- [x] CC3: ZA Vault module — app/modules/vault/ (Fernet encryption, CRUD, audit log, commit 232e1ae)

---

## WHAT IS PENDING (in priority order)

### NEXT: CC4 — ZA Shield Agent Module
Location: app/modules/shield_agent/ (server-side)
           agent/za_shield_agent.sh (client-side LaunchDaemon)

Server-side: receives real-time security events from client Macs.
Client-side: macOS log stream monitor. Watches for:
  - LaunchDaemon/LaunchAgent creation
  - Kernel extension loads
  - Auth failures (5+ in 60s = alert)
  - SIP/Gatekeeper policy changes
  - Suspicious process spawns from /tmp

Endpoint: POST /api/v1/shield/events
Schema: { serial, hostname, event_type, severity, details, timestamp }
Events stored in shield_events TimescaleDB hypertable.
Commit: "feat: ZA Shield Agent — real-time macOS security monitor"

### AFTER: App Intelligence Module
Location: app/modules/app_intelligence/
Source: /Users/courtneybentley/Downloads/files-10/Health Check v11 Module App Intelligence INSTRUCTIONS.md

Agent samples running processes every 60s. Aggregates to 5-min windows.
Tracks: CPU, memory, disk I/O, energy impact, foreground app, crash/hang rates.
Generates: app health scores, startup impact analysis, productivity scoring.
TimescaleDB hypertable: app_metrics.
Endpoint: POST /api/v1/intelligence/app-metrics

### AFTER: Interaction Analytics Module
Location: app/modules/interaction_analytics/
Source: /Users/courtneybentley/Downloads/files-10/Health Check v11 Module Interaction Analytics INSTRUCTIONS.md

POPIA compliant — NO keystrokes/characters captured. Behavioral timing only.
Tracks: typing speed WPM, dwell/flight times, mouse patterns, frustration scoring.
Generates: frustration score, productivity score, UX friction alerts.
TimescaleDB hypertable: interaction_metrics.
Endpoint: POST /api/v1/intelligence/interaction-metrics

### FUTURE

- V11 frontend dashboard (device list, diagnostics viewer, ISP status, alerts)
- Monthly report generation engine
- Per-client .pkg builder (embeds token + client ID)
- CyberShield integration
- Workshop/PTG trigger automation from diagnostic findings

---

## GIT

Repo: https://github.com/zasupport/za-support-backend
Branch: main
Latest: cf6a6ca (fix: remove dangling run_threat_intel call)

Commit message format: "feat/fix/chore: description"
Deploy: auto on push to main → Render rebuilds in ~60s

---

## CLIENTS

- Dr Evan Shoul → Stem ISP, X-DSL underlying, gateway 192.168.1.252
- Charles Chemel → NTT Data ISP, UniFi Site Manager
- Dr Anton Meyberg → Practice: "Dr's Pieterse, Hunt, Meyberg, Laher & Associates"
- Gillian Pearson → client_id: gillian-pearson
