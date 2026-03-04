"""Add automation layer tables: system_events, scheduled_jobs, patch_status, backup_status, notification_log

Revision ID: 003
Revises: 002_add_agent_router
Create Date: 2026-03-04
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # System Events
    op.create_table(
        'system_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_type', sa.String(64), nullable=False, index=True),
        sa.Column('source', sa.String(64), nullable=False, index=True),
        sa.Column('severity', sa.String(16), server_default='info'),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('device_serial', sa.String(64), nullable=True, index=True),
        sa.Column('client_id', sa.String(128), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), index=True),
    )
    op.create_index('ix_sysevent_type_created', 'system_events', ['event_type', 'created_at'])
    op.create_index('ix_sysevent_source_created', 'system_events', ['source', 'created_at'])

    # Scheduled Jobs
    op.create_table(
        'scheduled_jobs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('job_id', sa.String(64), unique=True, nullable=False, index=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('schedule', sa.String(128), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='true'),
        sa.Column('last_run', sa.DateTime(), nullable=True),
        sa.Column('next_run', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(16), server_default='pending'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('run_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_schedjob_enabled', 'scheduled_jobs', ['enabled'])

    # Patch Status
    op.create_table(
        'patch_status',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('device_serial', sa.String(64), nullable=False, index=True),
        sa.Column('client_id', sa.String(128), nullable=True, index=True),
        sa.Column('current_os', sa.String(32), nullable=True),
        sa.Column('latest_os', sa.String(32), nullable=True),
        sa.Column('pending_updates', sa.JSON(), nullable=True),
        sa.Column('days_behind', sa.Integer(), server_default='0'),
        sa.Column('last_checked', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_patch_serial_checked', 'patch_status', ['device_serial', 'last_checked'])

    # Backup Status
    op.create_table(
        'backup_status',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('device_serial', sa.String(64), nullable=False, index=True),
        sa.Column('client_id', sa.String(128), nullable=True, index=True),
        sa.Column('time_machine_enabled', sa.Boolean(), nullable=True),
        sa.Column('last_tm_backup', sa.DateTime(), nullable=True),
        sa.Column('tm_days_stale', sa.Integer(), server_default='0'),
        sa.Column('third_party_agent', sa.String(64), nullable=True),
        sa.Column('third_party_last_backup', sa.DateTime(), nullable=True),
        sa.Column('no_backup', sa.Boolean(), server_default='false'),
        sa.Column('last_checked', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_backup_serial_checked', 'backup_status', ['device_serial', 'last_checked'])

    # Notification Log
    op.create_table(
        'notification_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('channel', sa.String(16), nullable=False),
        sa.Column('recipient', sa.String(256), nullable=True),
        sa.Column('subject', sa.String(512), nullable=True),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(16), server_default='sent'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), server_default=sa.func.now(), index=True),
    )


def downgrade():
    op.drop_table('notification_log')
    op.drop_table('backup_status')
    op.drop_table('patch_status')
    op.drop_table('scheduled_jobs')
    op.drop_table('system_events')
