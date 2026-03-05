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
  api/              ← FastAPI route handlers (health, devices, network, alerts,
                       dashboard, diagnostics, isp, agent, system)
  core/
    config.py       ← Settings (AGENT_AUTH_TOKEN, AGENT_AUTH_TOKEN_OLD, DATABASE_URL)
    agent_auth.py   ← verify_agent_token() — dual-token rotation support
    database.py     ← asyncpg pool setup
  models/           ← SQLAlchemy models
  modules/
    vault/          ← CC3: encrypted credential storage
    shield_agent/   ← CC4: real-time macOS security monitor
    app_intelligence/      ← CC5: process metrics, app health, productivity scoring
    interaction_analytics/ ← CC6: keystroke dynamics, frustration scoring (POPIA)
    breach_scanner/        ← compromised data detection, 5 threat intel providers
    forensics/             ← software forensics, 30+ tools, POPIA consent gate
    diagnostics/           ← device registry, snapshots, time-series metrics
  services/         ← isp_monitor, automation_scheduler, event_bus, alert_engine, etc.
diagnostics/
  router.py         ← /diagnostics/run, /diagnostics/health (curl delivery)
  scripts/
    diagnostic_export.sh  ← 120-section standalone curl-deliverable script
isp_outage_monitor/       ← full module: 6 providers, weighted correlator, 13 SA ISPs
agent/
  za_shield_agent.sh      ← macOS LaunchDaemon client for shield monitoring
migrations/
  004_vault.sql
  005_shield_events.sql
  006_app_intelligence.sql
  007_interaction_analytics.sql
  008_breach_scanner.sql
  009_forensics.sql
  010_diagnostic_storage.sql   ← ⚠ NOT YET RUN ON RENDER
main.py             ← App entry point, all routers registered
```

---

## KEY ENDPOINTS

| Endpoint | Purpose |
|----------|---------|
| GET /diagnostics/run | Serves 120-section bash script (curl \| bash delivery) |
| POST /api/v1/agent/diagnostics | Receives V3 JSON push → stores snapshot + metrics |
| POST /api/v1/agent/heartbeat | Agent heartbeat |
| GET /api/v1/isp/status | ISP outage status |
| GET /api/v1/diagnostics/devices | Device registry |
| GET /api/v1/diagnostics/devices/{serial}/trends | Battery/disk/risk trends |
| GET /api/v1/diagnostics/alerts | Devices with risk_score > threshold |
| POST /api/v1/shield/events | Receive Shield Agent security events |
| POST /api/v1/vault | Encrypted credential storage |
| POST /api/v1/app-intelligence/report | App metrics ingest |
| POST /api/v1/interaction-analytics/report | Interaction metrics ingest |
| POST /api/v1/breach-scanner/submit-report | Agent scan report ingest |
| POST /api/v1/forensics/investigations | Create forensic investigation |

---

## AGENT AUTH

- Primary token: `AGENT_AUTH_TOKEN` env var on Render
- Fallback token: `AGENT_AUTH_TOKEN_OLD` env var (for rotation, empty = disabled)
- Header: `Authorization: Bearer <token>`
- Dual-token support in: app/core/agent_auth.py

---

## DATABASE — MIGRATIONS STATUS

| File | Tables | Status |
|------|--------|--------|
| 001–003 (alembic) | core tables | ✓ applied |
| 004_vault.sql | vault_entries, vault_audit_log | ✓ applied |
| 005_shield_events.sql | shield_events | ✓ applied |
| 006_app_intelligence.sql | app_resource_metrics, app_daily_summary, etc. | ✓ applied |
| 007_interaction_analytics.sql | interaction_metrics, interaction_baselines, etc. | ✓ applied |
| 008_breach_scanner.sql | breach_consent, scan_sessions, scan_findings, etc. | ⚠ NOT RUN |
| 009_forensics.sql | forensic_investigations, forensic_findings, forensic_audit_log | ⚠ NOT RUN |
| 010_diagnostic_storage.sql | client_devices, diagnostic_snapshots, device_metrics | ⚠ NOT RUN |

Run pending migrations:
```bash
psql $DATABASE_URL < migrations/008_breach_scanner.sql
psql $DATABASE_URL < migrations/009_forensics.sql
psql $DATABASE_URL < migrations/010_diagnostic_storage.sql
```

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

# Breach Scanner (set on Render)
VIRUSTOTAL_API_KEY=     # configured
ABUSEIPDB_API_KEY=      # configured
HIBP_API_KEY=           # configured

# ISP Networking Integrations (optional)
CLOUDFLARE_RADAR_TOKEN=
RIPE_ATLAS_API_KEY=
NETWORKING_INTEGRATIONS_ENABLED=false
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
- [x] Automation layer — event bus, scheduler, monitors, notifications
- [x] CC3: ZA Vault — app/modules/vault/ (Fernet encryption, CRUD, audit log)
- [x] CC4: ZA Shield Agent — agent/za_shield_agent.sh + app/modules/shield_agent/
- [x] CC5: App Intelligence — app/modules/app_intelligence/ (16 endpoints)
- [x] CC6: Interaction Analytics — app/modules/interaction_analytics/ (11 endpoints, POPIA)
- [x] Breach Scanner — app/modules/breach_scanner/ (6 scanners, 5 threat intel providers, POPIA)
- [x] Forensics — app/modules/forensics/ (30+ tools, POPIA consent gate, chain of custody)
- [x] ISP Networking Integrations — isp_outage_monitor/ (Cloudflare Radar, IODA, RIPE Atlas, BGP, webhooks)
- [x] Diagnostic Storage — app/modules/diagnostics/ (device registry, snapshots, time-series metrics)

---

## WHAT IS PENDING (in priority order)

### 1. Run pending DB migrations on Render (BLOCKING for new modules)
```bash
psql $DATABASE_URL < migrations/008_breach_scanner.sql
psql $DATABASE_URL < migrations/009_forensics.sql
psql $DATABASE_URL < migrations/010_diagnostic_storage.sql
```

### 2. Set API keys on Render
- VIRUSTOTAL_API_KEY
- ABUSEIPDB_API_KEY
- CLOUDFLARE_RADAR_TOKEN (optional)
- RIPE_ATLAS_API_KEY (optional)

### 3. Frontend Dashboard
- Device list, diagnostics viewer, ISP status, alerts, app intelligence views

### 4. Monthly Report Generation Engine
- Auto-generate PDF reports from stored diagnostic + module data
- reportlab (Platypus), A4, CyberShield/CyberPulse template structure

### 5. Per-client .pkg builder
- Embeds AGENT_AUTH_TOKEN + client_id at build time

### 6. Workshop/PTG trigger automation
- Diagnostic findings → auto-create Workshop job cards

---

## GIT

Repo: https://github.com/zasupport/za-support-backend
Branch: main
Latest: 8dc7121 feat: diagnostic storage — device registry, snapshots, time-series metrics

Commit message format: "feat/fix/chore: description"
Deploy: auto on push to main → Render rebuilds in ~60s

---

## CLIENTS

- Dr Evan Shoul → Stem ISP, X-DSL underlying, gateway 192.168.1.252
- Charles Chemel → NTT Data ISP, UniFi Site Manager
- Dr Anton Meyberg → Practice: "Dr's Pieterse, Hunt, Meyberg, Laher & Associates"
- Gillian Pearson → client_id: gillian-pearson
