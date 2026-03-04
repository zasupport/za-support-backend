"""
ISP Outage Monitor — 4-layer detection engine.

Layer 1: Status page scraping (Statuspage.io format + keyword scanning)
Layer 2: Downdetector ZA report parsing
Layer 3: HTTP probes (HEAD requests to probe_targets)
Layer 4: Agent connectivity evaluation (devices.last_seen)
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import (
    ISPProvider, ISPStatusCheck, ISPOutage, AgentConnectivity,
    ISPStatus, CheckSource, Device, Alert, AlertSeverity,
)

logger = logging.getLogger(__name__)

# Redis client (lazy-loaded, optional)
_redis_client = None


def _get_redis():
    """Lazy-load Redis client. Returns None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as redis_lib
        _redis_client = redis_lib.Redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_timeout=5
        )
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis unavailable, cooldowns disabled: {e}")
        _redis_client = None
        return None


def run_all_checks(db: Session):
    """Orchestrator: runs layers 1-3 for each active provider."""
    providers = db.query(ISPProvider).filter(ISPProvider.is_active == True).all()
    logger.info(f"Running ISP checks for {len(providers)} providers")

    for provider in providers:
        try:
            scrape_status_page(provider, db)
        except Exception as e:
            logger.error(f"Status page check failed for {provider.slug}: {e}")

        try:
            check_downdetector(provider, db)
        except Exception as e:
            logger.error(f"Downdetector check failed for {provider.slug}: {e}")

        try:
            run_http_probes(provider, db)
        except Exception as e:
            logger.error(f"HTTP probe failed for {provider.slug}: {e}")

        # Evaluate and update provider status after all checks
        try:
            evaluate_provider_status(provider.id, db)
        except Exception as e:
            logger.error(f"Status evaluation failed for {provider.slug}: {e}")


def scrape_status_page(provider: ISPProvider, db: Session):
    """
    Layer 1: Scrape ISP status page.
    Handles Statuspage.io format and keyword scanning.
    Scraper errors produce status=unknown, is_healthy=True (not counted as failure).
    """
    if not provider.status_page_url:
        return

    status = ISPStatus.UNKNOWN.value
    is_healthy = True
    response_time_ms = None
    http_status_code = None
    error_message = None

    try:
        start = time.monotonic()
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(provider.status_page_url)
        response_time_ms = round((time.monotonic() - start) * 1000, 1)
        http_status_code = resp.status_code

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            page_text = soup.get_text().lower()

            # Statuspage.io format detection
            status_component = soup.find("span", class_="component-status")
            if status_component:
                comp_text = status_component.get_text().lower()
                if "operational" in comp_text:
                    status = ISPStatus.OPERATIONAL.value
                    is_healthy = True
                elif "degraded" in comp_text or "partial" in comp_text:
                    status = ISPStatus.DEGRADED.value
                    is_healthy = True
                elif "outage" in comp_text or "major" in comp_text:
                    status = ISPStatus.OUTAGE.value
                    is_healthy = False
                else:
                    status = ISPStatus.UNKNOWN.value
                    is_healthy = True
            else:
                # Keyword scanning fallback
                if "major outage" in page_text or "service disruption" in page_text:
                    status = ISPStatus.OUTAGE.value
                    is_healthy = False
                elif "degraded" in page_text or "partial outage" in page_text:
                    status = ISPStatus.DEGRADED.value
                    is_healthy = True
                elif "operational" in page_text or "all systems" in page_text:
                    status = ISPStatus.OPERATIONAL.value
                    is_healthy = True
                else:
                    status = ISPStatus.OPERATIONAL.value
                    is_healthy = True
        else:
            error_message = f"HTTP {resp.status_code}"
    except Exception as e:
        error_message = str(e)[:500]
        logger.warning(f"Status page scrape error for {provider.slug}: {e}")

    check = ISPStatusCheck(
        provider_id=provider.id,
        source=CheckSource.STATUS_PAGE.value,
        status=status,
        response_time_ms=response_time_ms,
        http_status_code=http_status_code,
        error_message=error_message,
        is_healthy=is_healthy,
    )
    db.add(check)
    db.commit()


def check_downdetector(provider: ISPProvider, db: Session):
    """
    Layer 2: Check Downdetector ZA for report counts.
    <50 = operational, 50-200 = degraded, >200 = outage.
    Redis rate limit (60s TTL) to avoid hammering.
    """
    if not provider.downdetector_slug:
        return

    # Redis rate limit
    r = _get_redis()
    if r:
        rate_key = f"isp:dd:{provider.slug}"
        if r.get(rate_key):
            logger.debug(f"Downdetector rate-limited for {provider.slug}")
            return
        r.setex(rate_key, 60, "1")

    url = f"https://downdetector.co.za/status/{provider.downdetector_slug}/"
    status = ISPStatus.UNKNOWN.value
    is_healthy = True
    response_time_ms = None
    http_status_code = None
    error_message = None

    try:
        start = time.monotonic()
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ZASupport/11.1)"
            })
        response_time_ms = round((time.monotonic() - start) * 1000, 1)
        http_status_code = resp.status_code

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            # Try to find report count
            report_text = soup.find("span", class_="text-2xl")
            if report_text:
                try:
                    report_count = int(report_text.get_text().strip().replace(",", ""))
                    if report_count < 50:
                        status = ISPStatus.OPERATIONAL.value
                        is_healthy = True
                    elif report_count <= 200:
                        status = ISPStatus.DEGRADED.value
                        is_healthy = True
                    else:
                        status = ISPStatus.OUTAGE.value
                        is_healthy = False
                except ValueError:
                    status = ISPStatus.UNKNOWN.value
                    is_healthy = True
            else:
                # Fallback: keyword scan
                page_text = soup.get_text().lower()
                if "no problems" in page_text or "no issues" in page_text:
                    status = ISPStatus.OPERATIONAL.value
                    is_healthy = True
                elif "possible problems" in page_text:
                    status = ISPStatus.DEGRADED.value
                    is_healthy = True
                else:
                    status = ISPStatus.UNKNOWN.value
                    is_healthy = True
        else:
            error_message = f"HTTP {resp.status_code}"
    except Exception as e:
        error_message = str(e)[:500]
        logger.warning(f"Downdetector check error for {provider.slug}: {e}")

    check = ISPStatusCheck(
        provider_id=provider.id,
        source=CheckSource.DOWNDETECTOR.value,
        status=status,
        response_time_ms=response_time_ms,
        http_status_code=http_status_code,
        error_message=error_message,
        is_healthy=is_healthy,
    )
    db.add(check)
    db.commit()


def run_http_probes(provider: ISPProvider, db: Session):
    """
    Layer 3: HEAD request to each probe_targets URL.
    10s timeout. >5s = degraded, timeout = outage.
    """
    if not provider.probe_targets:
        return

    for target_url in provider.probe_targets:
        status = ISPStatus.OPERATIONAL.value
        is_healthy = True
        response_time_ms = None
        http_status_code = None
        error_message = None

        try:
            start = time.monotonic()
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                resp = client.head(target_url)
            elapsed_ms = round((time.monotonic() - start) * 1000, 1)
            response_time_ms = elapsed_ms
            http_status_code = resp.status_code

            if resp.status_code >= 500:
                status = ISPStatus.OUTAGE.value
                is_healthy = False
            elif elapsed_ms > 5000:
                status = ISPStatus.DEGRADED.value
                is_healthy = True
            else:
                status = ISPStatus.OPERATIONAL.value
                is_healthy = True
        except httpx.TimeoutException:
            status = ISPStatus.OUTAGE.value
            is_healthy = False
            error_message = "Timeout (10s)"
        except Exception as e:
            status = ISPStatus.OUTAGE.value
            is_healthy = False
            error_message = str(e)[:500]

        check = ISPStatusCheck(
            provider_id=provider.id,
            source=CheckSource.HTTP_PROBE.value,
            status=status,
            response_time_ms=response_time_ms,
            http_status_code=http_status_code,
            error_message=error_message,
            is_healthy=is_healthy,
        )
        db.add(check)

    db.commit()


def evaluate_agent_heartbeats(db: Session):
    """
    Layer 4: Check devices.last_seen vs heartbeat timeout.
    Requires 2+ agents on same ISP offline before flagging ISP-level issue.
    """
    timeout = settings.ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT
    cutoff = datetime.utcnow() - timedelta(seconds=timeout)

    # Get all providers with agent connectivity records
    providers = db.query(ISPProvider).filter(ISPProvider.is_active == True).all()

    for provider in providers:
        # Find distinct machines linked to this provider via recent heartbeats
        recent_heartbeats = (
            db.query(AgentConnectivity)
            .filter(
                AgentConnectivity.provider_id == provider.id,
                AgentConnectivity.timestamp >= datetime.utcnow() - timedelta(hours=1),
            )
            .all()
        )

        if not recent_heartbeats:
            continue

        # Group by machine_id, check if device is stale
        machine_ids = set(h.machine_id for h in recent_heartbeats)
        offline_count = 0

        for machine_id in machine_ids:
            device = db.query(Device).filter(Device.machine_id == machine_id).first()
            if device and device.last_seen and device.last_seen < cutoff:
                offline_count += 1

        total_agents = len(machine_ids)
        if total_agents >= 2 and offline_count >= 2:
            # ISP-level issue: 2+ agents offline
            status = ISPStatus.OUTAGE.value
            is_healthy = False
        elif offline_count == 1 and total_agents > 1:
            # Single agent offline — device issue, not ISP
            status = ISPStatus.OPERATIONAL.value
            is_healthy = True
        elif offline_count >= 1 and total_agents == 1:
            # Only one agent — can't confirm ISP issue
            status = ISPStatus.UNKNOWN.value
            is_healthy = True
        else:
            status = ISPStatus.OPERATIONAL.value
            is_healthy = True

        check = ISPStatusCheck(
            provider_id=provider.id,
            source=CheckSource.AGENT_CONNECTIVITY.value,
            status=status,
            is_healthy=is_healthy,
            error_message=f"{offline_count}/{total_agents} agents offline" if offline_count > 0 else None,
        )
        db.add(check)

    db.commit()

    # Evaluate status for all providers after heartbeat checks
    for provider in providers:
        try:
            evaluate_provider_status(provider.id, db)
        except Exception as e:
            logger.error(f"Status evaluation failed for {provider.slug}: {e}")


def evaluate_provider_status(provider_id: int, db: Session):
    """
    Confirmation logic: N consecutive unhealthy checks from any source
    combination confirms outage.
    Multi-source corroboration: 2+ sources agreeing = full outage,
    single source = degraded.
    """
    threshold = settings.ISP_MONITOR_OUTAGE_CONFIRMATION_THRESHOLD
    provider = db.query(ISPProvider).filter(ISPProvider.id == provider_id).first()
    if not provider:
        return

    # Get the last N checks per source
    recent_checks = (
        db.query(ISPStatusCheck)
        .filter(ISPStatusCheck.provider_id == provider_id)
        .order_by(ISPStatusCheck.timestamp.desc())
        .limit(threshold * 4)  # 4 sources max
        .all()
    )

    if not recent_checks:
        return

    # Group by source, check consecutive unhealthy
    source_unhealthy = {}
    source_status = {}
    checks_by_source = {}
    for check in recent_checks:
        if check.source not in checks_by_source:
            checks_by_source[check.source] = []
        checks_by_source[check.source].append(check)

    for source, checks in checks_by_source.items():
        # Count consecutive unhealthy from most recent
        consecutive = 0
        latest_status = ISPStatus.OPERATIONAL.value
        for c in checks[:threshold]:
            if not c.is_healthy:
                consecutive += 1
                latest_status = c.status
            else:
                break
        source_unhealthy[source] = consecutive >= threshold
        source_status[source] = latest_status

    # Count how many sources report unhealthy
    unhealthy_sources = [s for s, is_unhealthy in source_unhealthy.items() if is_unhealthy]
    healthy_sources = [s for s, is_unhealthy in source_unhealthy.items() if not is_unhealthy]

    if len(unhealthy_sources) >= 2:
        # Multi-source corroboration = confirmed outage
        new_status = ISPStatus.OUTAGE.value
        confirmed = True
    elif len(unhealthy_sources) == 1:
        # Single source = degraded
        new_status = ISPStatus.DEGRADED.value
        confirmed = False
    else:
        # All healthy — check for auto-resolution
        new_status = ISPStatus.OPERATIONAL.value
        confirmed = False

    # Check if status actually changed
    old_status = provider.current_status

    # Flap prevention: require N consecutive healthy checks for auto-resolution
    if old_status in (ISPStatus.OUTAGE.value, ISPStatus.DEGRADED.value) and new_status == ISPStatus.OPERATIONAL.value:
        # Verify all sources have N consecutive healthy
        all_healthy = True
        for source, checks in checks_by_source.items():
            healthy_count = 0
            for c in checks[:threshold]:
                if c.is_healthy:
                    healthy_count += 1
                else:
                    break
            if healthy_count < threshold:
                all_healthy = False
                break
        if not all_healthy:
            return  # Don't resolve yet

    # Update provider status
    provider.current_status = new_status
    db.commit()

    # Manage outage lifecycle
    manage_outage_lifecycle(provider_id, new_status, confirmed, unhealthy_sources, db)


def manage_outage_lifecycle(
    provider_id: int,
    status: str,
    confirmed: bool,
    sources: list,
    db: Session,
):
    """
    Creates/escalates/resolves outage records.
    Creates Alert records on confirmation.
    Redis cooldown key prevents duplicate alerts.
    """
    provider = db.query(ISPProvider).filter(ISPProvider.id == provider_id).first()
    if not provider:
        return

    # Find active (unresolved) outage
    active_outage = (
        db.query(ISPOutage)
        .filter(
            ISPOutage.provider_id == provider_id,
            ISPOutage.ended_at == None,
        )
        .first()
    )

    if status in (ISPStatus.OUTAGE.value, ISPStatus.DEGRADED.value):
        if active_outage:
            # Escalate if needed
            if status == ISPStatus.OUTAGE.value and active_outage.severity != ISPStatus.OUTAGE.value:
                active_outage.severity = ISPStatus.OUTAGE.value
            if confirmed and not active_outage.confirmed:
                active_outage.confirmed = True
            active_outage.confirmation_sources = sources
            db.commit()
        else:
            # Create new outage
            outage = ISPOutage(
                provider_id=provider_id,
                severity=status,
                confirmed=confirmed,
                confirmation_sources=sources,
                description=f"Auto-detected {status} for {provider.name}",
            )
            db.add(outage)
            db.commit()

            # Create alert (with cooldown)
            if confirmed:
                _create_outage_alert(provider, status, db)
    elif status == ISPStatus.OPERATIONAL.value and active_outage:
        # Auto-resolve
        active_outage.ended_at = datetime.utcnow()
        active_outage.auto_resolved = True
        db.commit()
        logger.info(f"Auto-resolved outage for {provider.name}")


def _create_outage_alert(provider: ISPProvider, severity: str, db: Session):
    """Create an alert record for a confirmed ISP outage, respecting cooldown."""
    r = _get_redis()
    cooldown_key = f"isp:alert_cooldown:{provider.slug}"

    if r:
        if r.get(cooldown_key):
            logger.debug(f"Alert cooldown active for {provider.slug}")
            return
        r.setex(cooldown_key, settings.ISP_MONITOR_ALERT_COOLDOWN_MINS * 60, "1")

    alert = Alert(
        machine_id=f"isp-{provider.slug}",
        severity=AlertSeverity.CRITICAL.value if severity == ISPStatus.OUTAGE.value else AlertSeverity.WARNING.value,
        category="isp_outage",
        message=f"ISP {severity}: {provider.name} is experiencing {severity}",
    )
    db.add(alert)
    db.commit()
    logger.info(f"Created ISP outage alert for {provider.name}")
