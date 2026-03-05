"""
migrate.py — Idempotent SQL migration runner.
Runs all migrations/0*.sql files in numeric order against DATABASE_URL.
Called automatically by Render buildCommand before service start.
Safe to run multiple times — all SQL uses IF NOT EXISTS.
"""
import os
import re
import sys
import glob
import logging

import sqlalchemy as sa

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def get_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        log.error("DATABASE_URL not set — skipping migrations")
        sys.exit(0)  # Don't block startup if no DB configured (local dev)
    return url.replace("postgres://", "postgresql://", 1)


def run_migrations():
    db_url = get_db_url()
    log.info("=== ZA Support — Running Migrations ===")
    log.info(f"Target: {db_url.split('@')[-1] if '@' in db_url else 'local'}")

    sql_files = sorted(
        glob.glob(os.path.join(os.path.dirname(__file__), "migrations", "0*.sql")),
        key=lambda f: int(re.search(r"(\d+)", os.path.basename(f)).group(1)),
    )

    if not sql_files:
        log.info("No migration files found.")
        return

    engine = sa.create_engine(db_url, pool_pre_ping=True)

    for path in sql_files:
        name = os.path.basename(path)
        try:
            with open(path, "r") as f:
                sql = f.read()
            with engine.begin() as conn:
                # Execute each statement individually for better error isolation
                statements = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
                for stmt in statements:
                    conn.execute(sa.text(stmt))
            log.info(f"  ✓ {name}")
        except Exception as e:
            log.error(f"  ✗ {name}: {e}")
            sys.exit(1)

    # Verify key tables exist
    log.info("\nVerifying tables...")
    expected = [
        "clients", "client_setup", "client_onboarding_tasks", "client_checkins",
        "vault_entries", "shield_events", "client_devices", "diagnostic_snapshots",
    ]
    with engine.connect() as conn:
        result = conn.execute(sa.text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
        ))
        existing = {row[0] for row in result}

    for t in expected:
        status = "✓" if t in existing else "✗ MISSING"
        log.info(f"  {status} {t}")

    log.info(f"\nTotal tables: {len(existing)}")
    log.info("=== Migrations complete ===\n")


if __name__ == "__main__":
    run_migrations()
