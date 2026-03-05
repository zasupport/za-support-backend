"""Add agent_heartbeats and diagnostic_reports tables

Revision ID: 002_agent_router
Revises: 001_isp_outage_monitor
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "002_agent_router"
down_revision: Union[str, None] = "001_isp_outage_monitor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- agent_heartbeats ---
    op.create_table(
        "agent_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("serial", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(256), nullable=True),
        sa.Column("client_id", sa.String(128), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("cpu_load", sa.Float(), nullable=True),
        sa.Column("memory_pressure", sa.Float(), nullable=True),
        sa.Column("disk_used_pct", sa.Float(), nullable=True),
        sa.Column("battery", sa.Float(), nullable=True),
        sa.Column("sip_enabled", sa.Boolean(), nullable=True),
        sa.Column("filevault_on", sa.Boolean(), nullable=True),
        sa.Column("firewall_on", sa.Boolean(), nullable=True),
        sa.Column("gatekeeper_on", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_agent_hb_serial", "agent_heartbeats", ["serial"])
    op.create_index("ix_agent_hb_client_id", "agent_heartbeats", ["client_id"])
    op.create_index("ix_agent_hb_timestamp", "agent_heartbeats", ["timestamp"])
    op.create_index("ix_agent_hb_serial_ts", "agent_heartbeats", ["serial", "timestamp"])
    op.create_index("ix_agent_hb_client_ts", "agent_heartbeats", ["client_id", "timestamp"])

    # TimescaleDB hypertable — 1-day chunks, 90-day retention
    _try_create_heartbeat_hypertable()

    # --- diagnostic_reports ---
    op.create_table(
        "diagnostic_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("serial", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(256), nullable=True),
        sa.Column("client_id", sa.String(128), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_diag_report_serial", "diagnostic_reports", ["serial"])
    op.create_index("ix_diag_report_client_id", "diagnostic_reports", ["client_id"])
    op.create_index("ix_diag_report_uploaded_at", "diagnostic_reports", ["uploaded_at"])
    op.create_index("ix_diag_report_serial_ts", "diagnostic_reports", ["serial", "uploaded_at"])

    # GIN index on JSONB payload for deep queries
    _try_create_gin_index()


def _try_create_heartbeat_hypertable():
    """Create TimescaleDB hypertable with 1-day chunks, 90-day retention, 15-min aggregate."""
    try:
        op.execute(
            "SELECT create_hypertable('agent_heartbeats', 'timestamp', "
            "chunk_time_interval => INTERVAL '1 day', "
            "migrate_data => true, if_not_exists => true)"
        )
        logger.info("Created hypertable: agent_heartbeats (1-day chunks)")

        # 90-day retention policy
        op.execute(
            "SELECT add_retention_policy('agent_heartbeats', "
            "INTERVAL '90 days', if_not_exists => true)"
        )
        logger.info("Added 90-day retention to: agent_heartbeats")

        # 15-minute continuous aggregate
        op.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS agent_heartbeats_15m
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket('15 minutes', timestamp) AS bucket,
                serial,
                client_id,
                AVG(cpu_load) AS avg_cpu_load,
                AVG(memory_pressure) AS avg_memory_pressure,
                AVG(disk_used_pct) AS avg_disk_used_pct,
                AVG(battery) AS avg_battery,
                COUNT(*) AS heartbeat_count
            FROM agent_heartbeats
            GROUP BY bucket, serial, client_id
            WITH NO DATA
        """)
        logger.info("Created continuous aggregate: agent_heartbeats_15m")

        # Auto-refresh the aggregate
        op.execute("""
            SELECT add_continuous_aggregate_policy('agent_heartbeats_15m',
                start_offset => INTERVAL '1 hour',
                end_offset => INTERVAL '15 minutes',
                schedule_interval => INTERVAL '15 minutes',
                if_not_exists => true
            )
        """)
        logger.info("Added continuous aggregate policy for agent_heartbeats_15m")

    except Exception as e:
        logger.warning(f"TimescaleDB not available for agent_heartbeats: {e}")


def _try_create_gin_index():
    """Create GIN index on diagnostic_reports.payload for JSONB queries."""
    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_diag_report_payload_gin "
            "ON diagnostic_reports USING GIN (payload)"
        )
        logger.info("Created GIN index on diagnostic_reports.payload")
    except Exception as e:
        logger.warning(f"GIN index creation failed (may need JSONB cast): {e}")


def downgrade() -> None:
    # Drop continuous aggregate first
    try:
        op.execute("DROP MATERIALIZED VIEW IF EXISTS agent_heartbeats_15m CASCADE")
    except Exception:
        pass

    op.drop_table("diagnostic_reports")
    op.drop_table("agent_heartbeats")
