# ZA Support Health Check v11 — Claude Instructions
# Read this FIRST before writing any code in this project.

## Project
FastAPI + PostgreSQL + TimescaleDB + Redis
Deployed on Render (Frankfurt) | Repo: zasupport/za-support-backend
Live API: https://api.zasupport.com

## Architecture — CRITICAL RULES

### Module Pattern (MANDATORY for all features)
Every feature lives in `app/modules/{module_name}/`. NEVER add feature code to main.py.

```
app/modules/{name}/
  __init__.py
  router.py        ← HTTP ONLY. No logic. No DB.
  service.py       ← ALL business logic. asyncpg. Typed.
  models.py        ← SQLAlchemy models + Pydantic schemas
  migration_{nnn}_{name}.sql  ← Raw SQL. Idempotent. IF NOT EXISTS.
  README.md        ← Purpose, endpoints, env vars, activation
```

### Core Infrastructure (DO NOT MODIFY)
```
app/core/
  config.py        ← Settings (env vars via pydantic-settings)
  database.py      ← asyncpg pool + SQLAlchemy engine
  agent_auth.py    ← verify_agent_token() — dual-token support
  auth.py          ← General auth utilities
  encryption.py    ← Fernet encryption (used by vault module)
  event_bus.py     ← Inter-module event bus (emit_event, subscribe)
main.py            ← ONLY: app init + include_router calls
```

### Database
- asyncpg for all queries (NOT SQLAlchemy ORM for queries)
- Tables: `{module}_{entity}` naming
- TimescaleDB hypertables: `create_hypertable(..., chunk_time_interval => '7 days', if_not_exists => TRUE)`
- All tables: UUID PK, created_at TIMESTAMPTZ DEFAULT NOW()
- Migrations: raw SQL files, idempotent, IF NOT EXISTS everywhere

### Inter-Module Communication
- NEVER import from another module
- Use: `await emit_event("module.action", payload)` via app/core/event_bus.py
- Events follow: `{module}.{past_tense_action}` (e.g., diagnostics.upload_received)

### API Standards
- Prefix: /api/v1/{module}/
- Auth: `dependencies=[Depends(verify_agent_token)]` on protected endpoints
- Pagination on all list endpoints: page, per_page, return meta

## Active Modules
| Module | Prefix | Status |
|--------|--------|--------|
| vault | /api/v1/vault/ | Active |
| shield_agent | /api/v1/shield/ | Active |
| app_intelligence | /api/v1/app-intelligence/ | Active |
| interaction_analytics | /api/v1/interaction-analytics/ | Active |
| breach_scanner | /api/v1/breach/ | Active |

## Missing Modules (Need to Build)
- forensics — 14 files, 30+ tools, POPIA consent gate
- networking_integrations — 6 external providers, weighted correlation

## Adding a New Module
1. Create app/modules/{name}/ with all 5 files
2. Write migration SQL (idempotent)
3. ONE line in main.py: `app.include_router({name}_router)`
4. Add env vars to .env.example
5. Write README.md

## Deployment
- Push to main → Render auto-deploys in ~60s
- Render service: za-health-check-main
- Render DB: za-db (PostgreSQL)
- Custom domain: api.zasupport.com → za-health-check-v11.onrender.com

## Env Vars (Render)
```
DATABASE_URL
REDIS_URL
AGENT_AUTH_TOKEN
AGENT_AUTH_TOKEN_OLD
VAULT_ENCRYPTION_KEY
```
