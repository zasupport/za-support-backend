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
- [x] CC4: ZA Shield Agent — agent/za_shield_agent.sh + app/modules/shield_agent/ (real-time macOS security monitor, shield_events table, POST/GET /api/v1/shield/events)
- [x] App Intelligence module — app/modules/app_intelligence/ (process metrics, app health scoring, startup analysis, productivity scoring, fleet health, POPIA deletion — 16 endpoints at /api/v1/app-intelligence)
- [x] Interaction Analytics module — app/modules/interaction_analytics/ (keystroke dynamics, frustration scoring, POPIA compliant, baselines, anomaly detection — 11 endpoints at /api/v1/interaction-analytics)

---

## WHAT IS PENDING (in priority order)

### NEXT: Frontend Dashboard
- V11 frontend (device list, diagnostics viewer, ISP status, alerts, app intelligence views)

### AFTER: Monthly Report Generation Engine
- Auto-generate PDF reports from App Intelligence + Interaction Analytics data
- Use reportlab (Platypus), A4, match CyberShield template structure

### AFTER: CyberShield Integration
- Network security assessment service, R 1,499/month
- Integrate with existing shield_events and shield agent

### FUTURE

- Per-client .pkg builder (embeds token + client ID)
- Workshop/PTG trigger automation from diagnostic findings

---

## GIT

Repo: https://github.com/zasupport/za-support-backend
Branch: main
Latest: chore: update CLAUDE.md — all CC modules complete

Commit message format: "feat/fix/chore: description"
Deploy: auto on push to main → Render rebuilds in ~60s

---

## CLIENTS

- Dr Evan Shoul → Stem ISP, X-DSL underlying, gateway 192.168.1.252
- Charles Chemel → NTT Data ISP, UniFi Site Manager
- Dr Anton Meyberg → Practice: "Dr's Pieterse, Hunt, Meyberg, Laher & Associates"
- Gillian Pearson → client_id: gillian-pearson
