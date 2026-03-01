# CLAUDE.md — ZA Support Backend

## Project Overview

**ZA Support Health Check Backend v11.1** — A FastAPI-based device health monitoring and diagnostics API for managing macOS client devices. Ingests telemetry (CPU, memory, disk, battery, security), generates threshold-based alerts, and stores deep diagnostic snapshots from the `za_diag_v3.sh` client script.

- **Language**: Python 3
- **Framework**: FastAPI (async, Pydantic v2 validation)
- **Database**: PostgreSQL via SQLAlchemy 2.0
- **Deployment**: Render.com (Gunicorn + Uvicorn workers)

## Repository Structure

```
za-support-backend/
├── main.py                          # FastAPI app entry point, router registration, CORS, lifespan
├── requirements.txt                 # Python dependencies (pip)
├── .env.example                     # Environment variable template
├── render.yaml                      # Render.com deployment config
├── Procfile                         # Heroku-style process definition
├── test_api.sh                      # Bash integration test suite (13 tests)
├── app/
│   ├── __init__.py
│   ├── core/                        # Infrastructure layer
│   │   ├── config.py                # Settings class (env vars, thresholds, retention)
│   │   ├── database.py              # SQLAlchemy engine, session factory (lazy init)
│   │   ├── auth.py                  # API key verification (X-API-Key header)
│   │   └── encryption.py            # Fernet symmetric encryption for sensitive payloads
│   ├── models/                      # Data layer
│   │   ├── models.py                # SQLAlchemy ORM models (Device, HealthData, NetworkData, Alert, WorkshopDiagnostic)
│   │   └── schemas.py               # Pydantic v2 request/response schemas
│   ├── api/                         # Route handlers (controllers)
│   │   ├── health.py                # GET /health — liveness/readiness probe
│   │   ├── devices.py               # /api/v1/devices — registration, telemetry, listing, history
│   │   ├── network.py               # /api/v1/network — network controller telemetry
│   │   ├── alerts.py                # /api/v1/alerts — alert management, resolution
│   │   ├── dashboard.py             # /api/v1/dashboard — aggregated overview
│   │   └── diagnostics.py           # /api/v1/diagnostics — za_diag_v3.sh upload/retrieval/comparison
│   └── services/                    # Business logic
│       └── alert_engine.py          # Threshold evaluation, alert generation
```

## API Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/` | No | Root info |
| GET | `/health` | No | Health check probe |
| POST | `/api/v1/devices/register` | Yes | Register/update device (upsert) |
| POST | `/api/v1/devices/health` | Yes | Submit health telemetry |
| GET | `/api/v1/devices/` | Yes | List devices (filterable) |
| GET | `/api/v1/devices/{machine_id}/history` | Yes | Health history (1-720 hours) |
| POST | `/api/v1/network/submit` | Yes | Submit network telemetry |
| GET | `/api/v1/network/history` | Yes | Network history |
| GET | `/api/v1/alerts/` | Yes | List alerts (filterable) |
| POST | `/api/v1/alerts/{alert_id}/resolve` | Yes | Resolve single alert |
| POST | `/api/v1/alerts/resolve-all` | Yes | Resolve all alerts for device |
| GET | `/api/v1/dashboard/overview` | Yes | Dashboard summary |
| POST | `/api/v1/diagnostics/upload` | **No** | Diagnostic upload (client script) |
| GET | `/api/v1/diagnostics/` | Yes | List diagnostics |
| GET | `/api/v1/diagnostics/device/{serial_number}` | Yes | Device diagnostics |
| GET | `/api/v1/diagnostics/{diagnostic_id}` | Yes | Single diagnostic |
| GET | `/api/v1/diagnostics/compare/{id1}/{id2}` | Yes | Compare two snapshots |

Authentication is via `X-API-Key` header. The diagnostics upload endpoint is intentionally unauthenticated (client scripts may not have credentials).

## Database Models

- **Device** — device registry (machine_id, hostname, serial, os_version, agent_version, metadata JSON)
- **HealthData** — time-series telemetry (cpu, memory, disk, battery, threat_score), indexed by (machine_id, timestamp)
- **NetworkData** — network controller telemetry, indexed by (controller_id, timestamp)
- **Alert** — generated alerts with severity enum (CRITICAL, HIGH, WARNING, INFO), resolution tracking
- **WorkshopDiagnostic** — full diagnostic snapshots (~215 data points across 53 sections from za_diag_v3.sh)

Tables are auto-created at startup via `Base.metadata.create_all()`. No Alembic migrations are in use.

## Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with DATABASE_URL, API_KEY, ENCRYPTION_KEY

# Run development server
uvicorn main:app --reload --port 8080

# Run integration tests (requires running server)
bash test_api.sh http://localhost:8080 <your-api-key>
```

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `API_KEY` | API authentication key |
| `ENCRYPTION_KEY` | Fernet key for encrypting sensitive telemetry |
| `PORT` | Server port (default: 8080) |
| `DEBUG` | Debug mode (default: false) |
| `ALLOWED_ORIGINS` | CORS origins, comma-separated |

### Alert Threshold Variables

`CPU_WARNING` (75), `CPU_CRITICAL` (90), `MEMORY_WARNING` (80), `MEMORY_CRITICAL` (90), `DISK_WARNING` (80), `DISK_CRITICAL` (90), `BATTERY_CRITICAL` (20), `THREAT_CRITICAL` (7)

## Testing

There is no Python test framework (no pytest/unittest). Testing is done via `test_api.sh`, a bash script that exercises 13 API endpoints using curl. It requires a running server instance.

```bash
bash test_api.sh [BASE_URL] [API_KEY]
# Defaults: http://localhost:8080 test-key
```

There are no linters, formatters, or pre-commit hooks configured.

## Key Patterns and Conventions

### Code Style
- **Functions**: `snake_case` (e.g., `verify_api_key`, `evaluate_health_data`)
- **Classes**: `PascalCase` (e.g., `DeviceRegister`, `HealthData`)
- **Constants**: `UPPER_CASE` (e.g., `CPU_CRITICAL`)
- **Private functions**: leading underscore (e.g., `_make_alert`, `_safe_float`)
- Type hints used consistently on function signatures
- Minimal but present docstrings and inline comments

### Architecture Patterns
- **Dependency injection**: FastAPI `Depends()` for database sessions (`get_db`) and auth (`verify_api_key`)
- **Lazy initialization**: Database engine/session created on first use, not at import time
- **Explicit transactions**: `db.add()` → `db.flush()` → `db.commit()` → `db.refresh()`
- **Query building**: Chainable SQLAlchemy ORM queries with `.filter()`, `.order_by()`, `.all()`
- **Validation**: Pydantic v2 schemas with `from_attributes = True` for ORM serialization
- **Safe type coercion**: `_safe_float()`, `_safe_int()` helpers in diagnostics for handling mixed-type script output ("N/A", "null", empty strings)
- **Graceful degradation**: Encryption failures are silently caught (data stored unencrypted)

### Settings
- Plain Python class (`Settings`) with `os.getenv()` — not Pydantic BaseSettings
- Singleton pattern: `settings = Settings()` at module level
- PostgreSQL URL compatibility: `postgres://` auto-converted to `postgresql://`

### Database Column Naming
- Uses `metadata_` as Python attribute mapped to `"metadata"` DB column (avoids keyword conflict)
- Composite indexes on (machine_id, timestamp) and (controller_id, timestamp) for time-series queries

## Deployment

Deployed on **Render.com** (free tier) via `render.yaml`:
- Build: `pip install -r requirements.txt`
- Start: `gunicorn main:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120`
- Database: Managed PostgreSQL (Frankfurt region)
- Secrets: `API_KEY` and `ENCRYPTION_KEY` auto-generated at deploy time

No CI/CD pipelines, Docker, or containerization configured.

## Important Notes for AI Assistants

1. **This is a Python/FastAPI project** — not Node.js/TypeScript
2. **No automated test suite** — changes should be manually verified or tested via `test_api.sh`
3. **No migrations** — schema changes require careful handling since tables are created via `create_all()`; adding columns to existing production tables needs manual SQL or Alembic migration setup
4. **Diagnostics endpoint is unauthenticated** — by design, for client script access. Do not add auth without considering client-side impact
5. **Encryption is optional** — if `ENCRYPTION_KEY` is not set, encryption silently fails and raw data is stored unencrypted
6. **Single settings instance** — `from app.core.config import settings` used everywhere
7. **Database sessions** — always obtained via `Depends(get_db)` in route handlers; never create sessions manually in API code
8. **Alert severity enum** — `CRITICAL`, `HIGH`, `WARNING`, `INFO` (defined as `str, enum.Enum`)
9. **Swagger docs** — auto-generated at `/docs` endpoint
