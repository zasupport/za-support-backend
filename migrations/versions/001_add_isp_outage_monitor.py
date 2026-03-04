"""Add ISP Outage Monitor tables

Revision ID: 001_isp_outage_monitor
Revises: None
Create Date: 2026-03-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "001_isp_outage_monitor"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ISP Providers
    op.create_table(
        "isp_providers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("status_page_url", sa.String(512), nullable=True),
        sa.Column("downdetector_slug", sa.String(128), nullable=True),
        sa.Column("probe_targets", sa.JSON(), nullable=True),
        sa.Column("gateway_ip", sa.String(45), nullable=True),
        sa.Column("underlying_provider", sa.String(128), nullable=True),
        sa.Column("current_status", sa.String(16), server_default="operational"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_isp_providers_slug", "isp_providers", ["slug"])

    # ISP Status Checks (time-series)
    op.create_table(
        "isp_status_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("isp_providers.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="operational"),
        sa.Column("response_time_ms", sa.Float(), nullable=True),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_healthy", sa.Boolean(), server_default=sa.text("true")),
    )
    op.create_index("ix_isp_check_provider_ts", "isp_status_checks", ["provider_id", "timestamp"])
    op.create_index("ix_isp_check_source_ts", "isp_status_checks", ["source", "timestamp"])

    # Agent Connectivity (time-series)
    op.create_table(
        "agent_connectivity",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("machine_id", sa.String(128), sa.ForeignKey("devices.machine_id"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("isp_providers.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("state", sa.String(16), server_default="connected"),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("packet_loss_pct", sa.Float(), nullable=True),
        sa.Column("gateway_reachable", sa.Boolean(), nullable=True),
        sa.Column("dns_reachable", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_agent_conn_machine_ts", "agent_connectivity", ["machine_id", "timestamp"])
    op.create_index("ix_agent_conn_provider_ts", "agent_connectivity", ["provider_id", "timestamp"])

    # ISP Outages
    op.create_table(
        "isp_outages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("isp_providers.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("severity", sa.String(16), server_default="outage"),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("confirmation_sources", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("auto_resolved", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_isp_outages_started", "isp_outages", ["started_at"])

    # TimescaleDB hypertables (graceful fallback)
    _try_create_hypertable("isp_status_checks", "timestamp")
    _try_create_hypertable("agent_connectivity", "timestamp")


def _try_create_hypertable(table: str, time_column: str):
    """Create TimescaleDB hypertable with graceful fallback."""
    try:
        op.execute(f"SELECT create_hypertable('{table}', '{time_column}', migrate_data => true, if_not_exists => true)")
        logger.info(f"Created hypertable: {table}")
        # 90-day retention policy
        op.execute(
            f"SELECT add_retention_policy('{table}', INTERVAL '90 days', if_not_exists => true)"
        )
        logger.info(f"Added 90-day retention to: {table}")
    except Exception as e:
        logger.warning(f"TimescaleDB not available for {table}, using regular table: {e}")


def downgrade() -> None:
    op.drop_table("isp_outages")
    op.drop_table("agent_connectivity")
    op.drop_table("isp_status_checks")
    op.drop_table("isp_providers")
