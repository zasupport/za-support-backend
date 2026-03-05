from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timezone, timedelta, date
import json

from app.modules.interaction_analytics.schemas import InteractionReport, InteractionDataPoint


def _insert_single(db: Session, device_id: str, client_id: str, entry: InteractionDataPoint):
    db.execute(
        """
        INSERT INTO interaction_metrics (
            device_id, client_id, timestamp,
            foreground_app, foreground_app_bundle_id,
            app_duration_seconds, app_switch_count,
            typing_speed_wpm, backspace_ratio,
            avg_dwell_time_ms, avg_flight_time_ms,
            typing_cadence_variance, burst_count, pause_count, pause_avg_duration_ms,
            modifier_ratio, active_typing_minutes,
            total_clicks, rage_click_count, dead_click_count,
            double_click_accuracy, click_to_action_latency_avg_ms,
            cursor_distance_px, cursor_speed_avg, direction_changes,
            scroll_distance_px, scroll_reversals,
            hover_events, hesitation_events, abandoned_actions, avg_hesitation_ms,
            frustration_score
        ) VALUES (
            :device_id, :client_id, :timestamp,
            :foreground_app, :foreground_app_bundle_id,
            :app_duration_seconds, :app_switch_count,
            :typing_speed_wpm, :backspace_ratio,
            :avg_dwell_time_ms, :avg_flight_time_ms,
            :typing_cadence_variance, :burst_count, :pause_count, :pause_avg_duration_ms,
            :modifier_ratio, :active_typing_minutes,
            :total_clicks, :rage_click_count, :dead_click_count,
            :double_click_accuracy, :click_to_action_latency_avg_ms,
            :cursor_distance_px, :cursor_speed_avg, :direction_changes,
            :scroll_distance_px, :scroll_reversals,
            :hover_events, :hesitation_events, :abandoned_actions, :avg_hesitation_ms,
            :frustration_score
        )
        """,
        {
            "device_id": device_id,
            "client_id": client_id,
            "timestamp": entry.timestamp,
            "foreground_app": entry.foreground_app,
            "foreground_app_bundle_id": entry.foreground_app_bundle_id,
            "app_duration_seconds": entry.app_duration_seconds,
            "app_switch_count": entry.app_switch_count,
            "typing_speed_wpm": entry.typing_speed_wpm,
            "backspace_ratio": entry.backspace_ratio,
            "avg_dwell_time_ms": entry.avg_dwell_time_ms,
            "avg_flight_time_ms": entry.avg_flight_time_ms,
            "typing_cadence_variance": entry.typing_cadence_variance,
            "burst_count": entry.burst_count,
            "pause_count": entry.pause_count,
            "pause_avg_duration_ms": entry.pause_avg_duration_ms,
            "modifier_ratio": entry.modifier_ratio,
            "active_typing_minutes": entry.active_typing_minutes,
            "total_clicks": entry.total_clicks,
            "rage_click_count": entry.rage_click_count,
            "dead_click_count": entry.dead_click_count,
            "double_click_accuracy": entry.double_click_accuracy,
            "click_to_action_latency_avg_ms": entry.click_to_action_latency_avg_ms,
            "cursor_distance_px": entry.cursor_distance_px,
            "cursor_speed_avg": entry.cursor_speed_avg,
            "direction_changes": entry.direction_changes,
            "scroll_distance_px": entry.scroll_distance_px,
            "scroll_reversals": entry.scroll_reversals,
            "hover_events": entry.hover_events,
            "hesitation_events": entry.hesitation_events,
            "abandoned_actions": entry.abandoned_actions,
            "avg_hesitation_ms": entry.avg_hesitation_ms,
            "frustration_score": entry.frustration_score,
        },
    )


def store_report(db: Session, device_id: str, client_id: str, data: InteractionReport) -> dict:
    """Insert interaction metrics — accepts single or array."""
    entries = data.data if isinstance(data.data, list) else [data.data]
    for entry in entries:
        _insert_single(db, device_id, client_id, entry)
    db.commit()
    return {"inserted": len(entries), "status": "stored"}


def get_summary(db: Session, device_id: str, period_days: int = 7) -> dict:
    """Aggregated summary for a device."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            AVG(typing_speed_wpm) AS avg_typing_speed_wpm,
            AVG(backspace_ratio) AS avg_backspace_ratio,
            AVG(frustration_score) AS avg_frustration_score,
            MAX(frustration_score) AS peak_frustration_score,
            SUM(rage_click_count) AS total_rage_clicks,
            SUM(dead_click_count) AS total_dead_clicks,
            SUM(hesitation_events) AS total_hesitation_events,
            SUM(abandoned_actions) AS total_abandoned_actions,
            SUM(active_typing_minutes) AS total_active_minutes,
            COUNT(*) AS sample_count
        FROM interaction_metrics
        WHERE device_id = :device_id AND timestamp >= :cutoff
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    row = result.fetchone()
    d = dict(row._mapping) if row else {}
    d["device_id"] = device_id
    d["period_days"] = period_days
    return d


def get_frustration_timeline(
    db: Session, device_id: str, start: datetime, end: datetime
) -> List[dict]:
    """Frustration score over time within a date range."""
    result = db.execute(
        """
        SELECT timestamp, frustration_score, foreground_app
        FROM interaction_metrics
        WHERE device_id = :device_id
          AND timestamp >= :start
          AND timestamp <= :end
          AND frustration_score IS NOT NULL
        ORDER BY timestamp ASC
        """,
        {"device_id": device_id, "start": start, "end": end},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_app_breakdown(db: Session, device_id: str, period_days: int = 7) -> List[dict]:
    """Per-app interaction metrics."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            foreground_app,
            foreground_app_bundle_id,
            AVG(frustration_score) AS avg_frustration_score,
            AVG(typing_speed_wpm) AS avg_typing_speed_wpm,
            SUM(rage_click_count) AS total_rage_clicks,
            SUM(dead_click_count) AS total_dead_clicks,
            SUM(active_typing_minutes) AS total_active_minutes,
            COUNT(*) AS sample_count
        FROM interaction_metrics
        WHERE device_id = :device_id AND timestamp >= :cutoff
        GROUP BY foreground_app, foreground_app_bundle_id
        ORDER BY avg_frustration_score DESC NULLS LAST
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_typing_trend(db: Session, device_id: str, period_days: int = 14) -> List[dict]:
    """Daily typing speed trend."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            DATE_TRUNC('day', timestamp)::date AS date,
            AVG(typing_speed_wpm) AS avg_typing_speed_wpm,
            AVG(backspace_ratio) AS avg_backspace_ratio,
            AVG(typing_cadence_variance) AS avg_cadence_variance
        FROM interaction_metrics
        WHERE device_id = :device_id AND timestamp >= :cutoff
        GROUP BY date
        ORDER BY date ASC
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_anomalies(db: Session, device_id: str, period_days: int = 7) -> List[dict]:
    """Deviations from baseline (z-score > 2)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

    # Fetch baselines for this device
    baselines_result = db.execute(
        "SELECT metric_name, baseline_mean, baseline_stddev FROM interaction_baselines WHERE device_id = :device_id",
        {"device_id": device_id},
    )
    baselines = {row.metric_name: row for row in baselines_result.fetchall()}

    if not baselines:
        return []

    anomalies = []
    metrics_result = db.execute(
        """
        SELECT timestamp, foreground_app,
               typing_speed_wpm, backspace_ratio, frustration_score,
               rage_click_count, avg_dwell_time_ms
        FROM interaction_metrics
        WHERE device_id = :device_id AND timestamp >= :cutoff
        ORDER BY timestamp DESC
        LIMIT 500
        """,
        {"device_id": device_id, "cutoff": cutoff},
    )
    for row in metrics_result.fetchall():
        row_dict = dict(row._mapping)
        for metric in ("typing_speed_wpm", "backspace_ratio", "frustration_score"):
            val = row_dict.get(metric)
            if val is None:
                continue
            baseline = baselines.get(metric)
            if not baseline or not baseline.baseline_stddev:
                continue
            z = abs(val - baseline.baseline_mean) / baseline.baseline_stddev
            if z > 2.0:
                anomalies.append({
                    "timestamp": row_dict["timestamp"],
                    "metric_name": metric,
                    "observed_value": val,
                    "baseline_mean": baseline.baseline_mean,
                    "baseline_stddev": baseline.baseline_stddev,
                    "z_score": round(z, 2),
                    "foreground_app": row_dict.get("foreground_app"),
                })

    anomalies.sort(key=lambda x: x["z_score"], reverse=True)
    return anomalies[:50]


def get_fleet_summary(db: Session, client_id: str, period_days: int = 7) -> List[dict]:
    """All devices aggregated for a client."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            device_id,
            AVG(frustration_score) AS avg_frustration_score,
            MAX(frustration_score) AS peak_frustration_score,
            SUM(rage_click_count) AS total_rage_clicks,
            AVG(typing_speed_wpm) AS avg_typing_speed_wpm,
            COUNT(*) AS sample_count
        FROM interaction_metrics
        WHERE client_id = :client_id AND timestamp >= :cutoff
        GROUP BY device_id
        ORDER BY avg_frustration_score DESC NULLS LAST
        """,
        {"client_id": client_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def get_frustration_hotspots(db: Session, client_id: str, period_days: int = 7) -> List[dict]:
    """Top frustration-causing apps across fleet."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    result = db.execute(
        """
        SELECT
            foreground_app,
            foreground_app_bundle_id,
            AVG(frustration_score) AS avg_frustration_score,
            MAX(frustration_score) AS peak_frustration_score,
            COUNT(DISTINCT device_id) AS affected_devices,
            SUM(rage_click_count) AS total_rage_clicks,
            COUNT(*) AS sample_count
        FROM interaction_metrics
        WHERE client_id = :client_id
          AND timestamp >= :cutoff
          AND frustration_score IS NOT NULL
        GROUP BY foreground_app, foreground_app_bundle_id
        HAVING AVG(frustration_score) > 40
        ORDER BY avg_frustration_score DESC NULLS LAST
        LIMIT 20
        """,
        {"client_id": client_id, "cutoff": cutoff},
    )
    return [dict(row._mapping) for row in result.fetchall()]


def recalculate_baselines(db: Session, device_id: str) -> dict:
    """Recalculate baselines from last 30 days of data."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    metrics_to_baseline = [
        "typing_speed_wpm",
        "backspace_ratio",
        "frustration_score",
        "rage_click_count",
        "avg_dwell_time_ms",
        "avg_flight_time_ms",
        "typing_cadence_variance",
        "cursor_speed_avg",
    ]

    updated = []
    for metric in metrics_to_baseline:
        result = db.execute(
            f"""
            SELECT
                AVG({metric}) AS mean,
                STDDEV({metric}) AS stddev,
                COUNT(*) AS sample_count
            FROM interaction_metrics
            WHERE device_id = :device_id
              AND timestamp >= :cutoff
              AND {metric} IS NOT NULL
            """,
            {"device_id": device_id, "cutoff": cutoff},
        )
        row = result.fetchone()
        if not row or row.sample_count is None or row.sample_count < 10:
            continue

        db.execute(
            """
            INSERT INTO interaction_baselines (device_id, metric_name, baseline_mean, baseline_stddev, sample_count, last_updated)
            VALUES (:device_id, :metric_name, :mean, :stddev, :sample_count, NOW())
            ON CONFLICT (device_id, metric_name)
            DO UPDATE SET
                baseline_mean = EXCLUDED.baseline_mean,
                baseline_stddev = EXCLUDED.baseline_stddev,
                sample_count = EXCLUDED.sample_count,
                last_updated = NOW()
            """,
            {
                "device_id": device_id,
                "metric_name": metric,
                "mean": row.mean,
                "stddev": row.stddev,
                "sample_count": row.sample_count,
            },
        )
        updated.append(metric)

    db.commit()
    return {"device_id": device_id, "updated_metrics": updated, "status": "recalculated"}


def get_report_data(db: Session, client_id: str, period: str = "month", report_date: Optional[str] = None) -> dict:
    """Monthly report data for a client."""
    period_days = 30 if period == "month" else 7
    fleet = get_fleet_summary(db, client_id, period_days)
    hotspots = get_frustration_hotspots(db, client_id, period_days)
    return {
        "client_id": client_id,
        "period": period,
        "fleet_summary": fleet,
        "frustration_hotspots": hotspots,
    }


def delete_device_data(db: Session, device_id: str) -> dict:
    """POPIA right to deletion."""
    tables = [
        "interaction_metrics",
        "interaction_daily_summary",
        "interaction_baselines",
        "frustration_events",
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


from typing import Optional
