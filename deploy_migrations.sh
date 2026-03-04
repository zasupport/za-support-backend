#!/bin/bash
# deploy_migrations.sh — Run automation layer migration against Render database
# Usage: DATABASE_URL=<render_url> bash deploy_migrations.sh
# Or set DATABASE_URL in environment before running.

set -e

echo "=== ZA Support Health Check — Automation Layer Migration ==="
echo "Date: $(date)"
echo ""

if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: DATABASE_URL not set."
    echo "Usage: DATABASE_URL=postgresql://user:pass@host:5432/db bash deploy_migrations.sh"
    exit 1
fi

# Fix Render's postgres:// to postgresql://
export DATABASE_URL=$(echo "$DATABASE_URL" | sed 's|^postgres://|postgresql://|')

echo "Target: ${DATABASE_URL%%@*}@***"
echo ""

echo "[1/3] Creating automation layer tables..."
python3 -c "
import sqlalchemy as sa
engine = sa.create_engine('$DATABASE_URL')
with engine.connect() as conn:
    # system_events
    conn.execute(sa.text('''
        CREATE TABLE IF NOT EXISTS system_events (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(64) NOT NULL,
            source VARCHAR(64) NOT NULL,
            severity VARCHAR(16) DEFAULT 'info',
            summary TEXT NOT NULL,
            detail JSONB,
            device_serial VARCHAR(64),
            client_id VARCHAR(128),
            created_at TIMESTAMP DEFAULT NOW()
        )
    '''))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_type ON system_events(event_type)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_source ON system_events(source)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_created ON system_events(created_at)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_serial ON system_events(device_serial)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_client ON system_events(client_id)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_type_created ON system_events(event_type, created_at)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_sysevent_source_created ON system_events(source, created_at)'))
    print('  ✓ system_events')

    # scheduled_jobs
    conn.execute(sa.text('''
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            id SERIAL PRIMARY KEY,
            job_id VARCHAR(64) UNIQUE NOT NULL,
            name VARCHAR(128) NOT NULL,
            schedule VARCHAR(128) NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            last_run TIMESTAMP,
            next_run TIMESTAMP,
            last_status VARCHAR(16) DEFAULT 'pending',
            last_error TEXT,
            run_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    '''))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_schedjob_id ON scheduled_jobs(job_id)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_schedjob_enabled ON scheduled_jobs(enabled)'))
    print('  ✓ scheduled_jobs')

    # patch_status
    conn.execute(sa.text('''
        CREATE TABLE IF NOT EXISTS patch_status (
            id SERIAL PRIMARY KEY,
            device_serial VARCHAR(64) NOT NULL,
            client_id VARCHAR(128),
            current_os VARCHAR(32),
            latest_os VARCHAR(32),
            pending_updates JSONB,
            days_behind INTEGER DEFAULT 0,
            last_checked TIMESTAMP DEFAULT NOW(),
            notified_at TIMESTAMP
        )
    '''))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_patch_serial ON patch_status(device_serial)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_patch_serial_checked ON patch_status(device_serial, last_checked)'))
    print('  ✓ patch_status')

    # backup_status
    conn.execute(sa.text('''
        CREATE TABLE IF NOT EXISTS backup_status (
            id SERIAL PRIMARY KEY,
            device_serial VARCHAR(64) NOT NULL,
            client_id VARCHAR(128),
            time_machine_enabled BOOLEAN,
            last_tm_backup TIMESTAMP,
            tm_days_stale INTEGER DEFAULT 0,
            third_party_agent VARCHAR(64),
            third_party_last_backup TIMESTAMP,
            no_backup BOOLEAN DEFAULT FALSE,
            last_checked TIMESTAMP DEFAULT NOW(),
            notified_at TIMESTAMP
        )
    '''))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_backup_serial ON backup_status(device_serial)'))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_backup_serial_checked ON backup_status(device_serial, last_checked)'))
    print('  ✓ backup_status')

    # notification_log
    conn.execute(sa.text('''
        CREATE TABLE IF NOT EXISTS notification_log (
            id SERIAL PRIMARY KEY,
            channel VARCHAR(16) NOT NULL,
            recipient VARCHAR(256),
            subject VARCHAR(512),
            event_id INTEGER,
            status VARCHAR(16) DEFAULT 'sent',
            error TEXT,
            sent_at TIMESTAMP DEFAULT NOW()
        )
    '''))
    conn.execute(sa.text('CREATE INDEX IF NOT EXISTS ix_notiflog_sent ON notification_log(sent_at)'))
    print('  ✓ notification_log')

    conn.commit()

print('')
print('[2/3] Verifying tables...')
with engine.connect() as conn:
    result = conn.execute(sa.text(\"\"\"
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    \"\"\"))
    tables = [row[0] for row in result]
    automation_tables = ['system_events', 'scheduled_jobs', 'patch_status', 'backup_status', 'notification_log']
    for t in automation_tables:
        status = '✓' if t in tables else '✗ MISSING'
        print(f'  {status} {t}')

print('')
print('[3/3] Migration complete!')
print(f'Total tables in database: {len(tables)}')
for t in tables:
    print(f'  - {t}')
"

echo ""
echo "=== Migration complete ==="
