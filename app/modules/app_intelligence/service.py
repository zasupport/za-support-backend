from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import json

from app.modules.app_intelligence.schemas import (
    AppMetricsReport,
    StartupReport,
)


def store_metrics_report(db: Session, device_id: str, client_id: str, report: AppMetricsReport) -> dict:
    """Bulk insert process metrics entries into app_resource_metrics."""
    inserted = 0
    for entry in report.metrics:
        db.execute(
            """
            INSERT INTO app_resource_metrics (
                device_id, client_id, timestamp,
                app_name, app_bundle_id,
                cpu_avg_percent, cpu_peak_percent,
                memory_avg_mb, memory_peak_mb,
                disk_read_mb, disk_write_mb,
                net_sent_mb, net_recv_mb,
                energy_impact_avg,
                foreground_seconds, is_foreground,
                thread_count_avg,
                responsiveness_score, slow_interactions, unresponsive_interactions
            ) VALUES (
                :device_id, :client_id, :timestamp,
                :app_name, :app_bundle_id,
                :cpu_avg_percent, :cpu_peak_percent,
                :memory_avg_mb, :memory_peak_mb,
                :disk_read_mb, :disk_write_mb,
                :net_sent_mb, :net_recv_mb,
                :energy_impact_avg,
                :foreground_seconds, :is_foreground,
                :thread_count_avg,
                :responsiveness_score, :slow_interactions, :unresponsive_interactions
            )
            """,
            {
                "device_id": device_id,
                "client_id": client_id,
                "timestamp": entry.timestamp,
                "app_name": entry.app_name,
                "app_bundle_id": entry.app_bundle_id,
                "cpu_avg_percent": entry.cpu_avg_percent,
                "cpu_peak_percent": entry.cpu_peak_percent,
                "memory_avg_mb": entry.memory_avg_mb,
                "memory_peak_mb": entry.memory_peak_mb,
                "disk_read_mb": entry.disk_read_mb,
                "disk_write_mb": entry.disk_write_mb,
                "net_sent_mb": entry.net_sent_mb,
                "net_recv_mb": entry.net_recv_mb,
                "energy_impact_avg": entry.energy_impact_avg,
                "foreground_seconds": entry.foreground_seconds,
                "is_foreground": entry.is_foreground,
                "thread_count_avg": entry.thread_count_avg,
                "responsiveness_score": entry.responsiveness_score,
                "slow_interactions": entry.slow_interactions,
                "unresponsive_interactions": entry.unresponsive_interactions,
            },
        )
        inserted += 1
    db.commit()
    generate_recommendations(db, device_id, client_id)
    return {"inserted": inserted}


def store_startup_report(db: Session, device_id: str, client_id: str, data: StartupReport) -> dict:
    """Insert a startup report into startup_reports."""
    login_items_json = None
    if data.login_items is not None:
        login_items_json = json.dumps(data.login_items)

    result = db.execute(
        """
        INSERT INTO startup_reports (
            device_id, client_id,
            boot_timestamp, login_timestamp,
            desktop_ready_timestamp, system_settled_timestamp,
            boot_to_ready_seconds, login_to_ready_seconds,
            login_items, total_login_items,
            slowest_login_item, slowest_login_item_seconds
        ) VALUES (
            :device_id, :client_id,
            :boot_timestamp, :login_timestamp,
            :desktop_ready_timestamp, :system_settled_timestamp,
            :boot_to_ready_seconds, :login_to_ready_seconds,
            :login_items::jsonb, :total_login_items,
            :slowest_login_item, :slowest_login_item_seconds
        ) RETURNING id
        """,
        {
            "device_id": device_id,
            "client_id": client_id,
            "boot_timestamp": data.boot_timestamp,
            "login_timestamp": data.login_timestamp,
            "desktop_ready_timestamp": data.desktop_ready_timestamp,
            "system_settled_timestamp": data.system_settled_timestamp,
            "boot_to_ready_seconds": data.boot_to_ready_seconds,
            "login_to_ready_seconds": data.login_to_ready_seconds,
            "login_items": login_items_json,
            "total_login_items": data.total_login_items,
            "slowest_login_item": data.slowest_login_item,
            "slowest_login_item_seconds": data.slowest_login_item_seconds,
        },
    )
    db.commit()
    row = result.fetchone()
    return {"id": str(row[0]) if row else None, "status": "stored"}


def get_app_health(db: Session, device_id: str, period_days: int = 7) -> List[dict]:
    """Query app_health_scores for a device over the given period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT * FROM app_health_scores
        WHERE device_id = :device_id AND date >= :cutoff
        ORDER BY date DESC, health_score ASC
        """,
        {"device_id": device_id, "cutoff": cutoff.date()},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_app_ranking(db: Session, device_id: str, period_days: int = 7, sort_by: str = "cpu") -> List[dict]:
    """Ranked app list by resource usage."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    order_col = "avg_cpu"
    if sort_by == "memory":
        order_col = "avg_memory_mb"
    elif sort_by == "energy":
        order_col = "avg_energy"
    elif sort_by == "foreground":
        order_col = "total_foreground_minutes"

    result = db.execute(
        f"""
        SELECT
            app_name,
            app_bundle_id,
            AVG(cpu_avg_percent) AS avg_cpu,
            AVG(memory_avg_mb) AS avg_memory_mb,
            AVG(energy_impact_avg) AS avg_energy,
            SUM(foreground_seconds) / 60.0 AS total_foreground_minutes,
            COUNT(*) AS sample_count
        FROM app_resource_metrics
        WHERE device_id = :device_id AND timestamp >= :cutoff
        GROUP BY app_name, app_bundle_id
        ORDER BY {order_col} DESC NULLS LAST
        LIMIT 50
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_resource_timeline(
    db: Session, device_id: str, app_bundle_id: str, period_days: int = 7
) -> List[dict]:
    """Time series of resource usage for a specific app."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            timestamp,
            cpu_avg_percent,
            memory_avg_mb,
            energy_impact_avg,
            disk_read_mb,
            disk_write_mb
        FROM app_resource_metrics
        WHERE device_id = :device_id
          AND app_bundle_id = :app_bundle_id
          AND timestamp >= :cutoff
        ORDER BY timestamp ASC
        """,
        {"device_id": device_id, "app_bundle_id": app_bundle_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_foreground_breakdown(db: Session, device_id: str, period_days: int = 7) -> List[dict]:
    """Time per app in foreground."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            app_name,
            app_bundle_id,
            SUM(foreground_seconds) / 60.0 AS total_foreground_minutes,
            COUNT(*) AS session_count
        FROM app_resource_metrics
        WHERE device_id = :device_id
          AND timestamp >= :cutoff
          AND is_foreground = TRUE
        GROUP BY app_name, app_bundle_id
        ORDER BY total_foreground_minutes DESC NULLS LAST
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_startup_history(db: Session, device_id: str, period_days: int = 30) -> List[dict]:
    """Boot time trend."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            id, boot_timestamp, login_timestamp,
            desktop_ready_timestamp, system_settled_timestamp,
            boot_to_ready_seconds, login_to_ready_seconds,
            total_login_items, slowest_login_item, slowest_login_item_seconds,
            created_at
        FROM startup_reports
        WHERE device_id = :device_id AND created_at >= :cutoff
        ORDER BY boot_timestamp DESC
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_productivity(db: Session, device_id: str, period_days: int = 28) -> List[dict]:
    """Weekly productivity scores."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT * FROM productivity_scores
        WHERE device_id = :device_id AND week_start >= :cutoff
        ORDER BY week_start DESC
        """,
        {"device_id": device_id, "cutoff": cutoff.date()},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def generate_recommendations(db: Session, device_id: str, client_id: str) -> int:
    """Analyse recent metrics and populate ai_recommendations for this device.

    Rules:
      CPU avg > 50%  → HIGH   "high CPU usage"
      CPU avg > 30%  → MEDIUM "elevated CPU usage"
      Memory avg > 500 MB → HIGH  "high memory usage"
      Memory avg > 300 MB → MEDIUM "elevated memory usage"
      Energy avg > 5  → HIGH  "high energy impact — draining battery"
      Responsiveness < 70 with unresponsive > 5 → HIGH "app frequently unresponsive"
      Boot > 120s → HIGH  "slow startup"
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Remove stale undismissed recs so we regenerate fresh each time
    db.execute(
        "DELETE FROM ai_recommendations WHERE device_id = :d AND dismissed_at IS NULL",
        {"d": device_id},
    )

    recs = []

    # --- App-level rules ---
    app_rows = db.execute(
        """
        SELECT
            app_name,
            app_bundle_id,
            AVG(cpu_avg_percent)        AS avg_cpu,
            AVG(memory_avg_mb)          AS avg_mem,
            AVG(energy_impact_avg)      AS avg_energy,
            AVG(responsiveness_score)   AS avg_resp,
            SUM(unresponsive_interactions) AS total_unresponsive
        FROM app_resource_metrics
        WHERE device_id = :d AND timestamp >= :c
        GROUP BY app_name, app_bundle_id
        """,
        {"d": device_id, "c": cutoff},
    ).fetchall()

    for row in app_rows:
        r = dict(row._mapping)
        name = r["app_name"] or r["app_bundle_id"] or "Unknown app"
        cpu  = float(r["avg_cpu"]    or 0)
        mem  = float(r["avg_mem"]    or 0)
        ener = float(r["avg_energy"] or 0)
        resp = float(r["avg_resp"]   or 100)
        unr  = int(r["total_unresponsive"] or 0)

        if cpu > 50:
            recs.append(("HIGH", "performance",
                f"{name} is consuming high CPU (avg {cpu:.0f}%) — consider restarting or updating it.",
                {"app": name, "avg_cpu": round(cpu, 1)}))
        elif cpu > 30:
            recs.append(("MEDIUM", "performance",
                f"{name} has elevated CPU usage (avg {cpu:.0f}%) over the past 7 days.",
                {"app": name, "avg_cpu": round(cpu, 1)}))

        if mem > 500:
            recs.append(("HIGH", "memory",
                f"{name} is using high memory (avg {mem:.0f} MB) — a restart may improve performance.",
                {"app": name, "avg_memory_mb": round(mem, 0)}))
        elif mem > 300:
            recs.append(("MEDIUM", "memory",
                f"{name} has elevated memory usage (avg {mem:.0f} MB).",
                {"app": name, "avg_memory_mb": round(mem, 0)}))

        if ener > 5:
            recs.append(("HIGH", "battery",
                f"{name} has a high energy impact (avg {ener:.1f}) and is reducing battery life.",
                {"app": name, "avg_energy_impact": round(ener, 1)}))

        if resp < 70 and unr > 5:
            recs.append(("HIGH", "responsiveness",
                f"{name} is frequently unresponsive ({unr} unresponsive interactions) — update or reinstall recommended.",
                {"app": name, "avg_responsiveness": round(resp, 0), "unresponsive_interactions": unr}))

    # --- Startup rules ---
    startup_row = db.execute(
        """
        SELECT AVG(boot_to_ready_seconds) AS avg_boot, AVG(total_login_items) AS avg_items
        FROM startup_reports
        WHERE device_id = :d AND created_at >= :c
        """,
        {"d": device_id, "c": cutoff},
    ).fetchone()

    if startup_row:
        avg_boot  = float(startup_row[0] or 0)
        avg_items = float(startup_row[1] or 0)
        if avg_boot > 120:
            recs.append(("HIGH", "startup",
                f"Slow startup detected (avg {avg_boot:.0f}s) — {avg_items:.0f} login items may be contributing.",
                {"avg_boot_seconds": round(avg_boot, 0), "avg_login_items": round(avg_items, 0)}))
        elif avg_boot > 60:
            recs.append(("MEDIUM", "startup",
                f"Startup is taking longer than expected (avg {avg_boot:.0f}s).",
                {"avg_boot_seconds": round(avg_boot, 0)}))

    import json as _json
    for priority, category, text, data in recs:
        db.execute(
            """
            INSERT INTO ai_recommendations
                (device_id, client_id, recommendation_text, category, priority, supporting_data)
            VALUES (:d, :c, :t, :cat, :pri, :dat::jsonb)
            """,
            {"d": device_id, "c": client_id, "t": text,
             "cat": category, "pri": priority, "dat": _json.dumps(data)},
        )

    db.commit()
    return len(recs)


def get_recommendations(db: Session, device_id: str) -> List[dict]:
    """Fetch AI recommendations for a device."""
    result = db.execute(
        """
        SELECT * FROM ai_recommendations
        WHERE device_id = :device_id
          AND dismissed_at IS NULL
        ORDER BY
            CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
            generated_at DESC
        LIMIT 20
        """,
        {"device_id": device_id},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_fleet_health(db: Session, client_id: str, period_days: int = 7) -> List[dict]:
    """All devices aggregated for a client."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            device_id,
            AVG(health_score) AS avg_health_score,
            MIN(health_score) AS min_health_score,
            COUNT(DISTINCT app_bundle_id) AS app_count
        FROM app_health_scores
        WHERE client_id = :client_id AND date >= :cutoff
        GROUP BY device_id
        ORDER BY avg_health_score ASC NULLS LAST
        """,
        {"client_id": client_id, "cutoff": cutoff.date()},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def delete_device_data(db: Session, device_id: str) -> dict:
    """POPIA right to deletion — remove all data for a device."""
    tables = [
        "app_resource_metrics",
        "app_foreground_sessions",
        "app_health_scores",
        "startup_reports",
        "app_daily_summary",
        "app_network_flags",
        "productivity_scores",
        "ai_recommendations",
    ]
    deleted = {}
    for table in tables:
        result = db.execute(
            f"DELETE FROM {table} WHERE device_id = :device_id",
            {"device_id": device_id},
        )
        deleted[table] = result.rowcount
    db.commit()
    return {"device_id": device_id, "deleted": deleted, "status": "erased"}
