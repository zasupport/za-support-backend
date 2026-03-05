"""
Health Check v11 — Networking Integrations
===========================================
Plugs into the ISP Outage Detection Engine with real-world
ISP outage data providers for South African networks.

Providers integrated:
1. Cloudflare Radar    — Global internet outage detection (free API)
2. IODA / CAIDA        — Internet Outage Detection & Analysis (Georgia Tech)
3. RIPE Atlas          — Network measurement probes across SA
4. Statuspage.io API   — Structured status from ISPs using Atlassian Statuspage
5. ISP Webhook Receiver— Inbound webhooks from ISPs that push status updates
6. Looking Glass       — BGP/route health via public looking glass servers

Each provider returns a standardised ProviderCheckResult that feeds
directly into the OutageCorrelator in detection_engine.py.

Integration point:
    detection_engine.py → ISPDetectionEngine.check_isp()
    This module adds new check methods alongside the existing
    status_page, downdetector, and http_probe methods.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum

import httpx

from .config import config
from .schemas import StatusCheckResult, CheckMethod

logger = logging.getLogger("healthcheck.isp_monitor.networking")


# ==========================================================================
# Provider Configuration — maps ISP slugs to provider-specific identifiers
# ==========================================================================

# Cloudflare Radar uses ASN (Autonomous System Numbers) to identify networks
# These are the real ASNs for SA ISPs
CLOUDFLARE_ASN_MAP: Dict[str, int] = {
    "afrihost":     37611,
    "rain":         327741,
    "vumatel":      328364,
    "openserve":    36874,      # Telkom subsidiary
    "rsaweb":       37153,
    "coolideas":    328006,
    "webafrica":    37468,
    "herotel":      328210,
    "vodacom":      29975,
    "mtn":          16637,
    "telkom":       5713,
    "stem":         None,       # small provider — no public ASN mapping yet
    "x-dsl":        None,       # small provider — no public ASN mapping yet
}

# IODA uses the same ASNs but with their own entity format
IODA_ENTITY_MAP: Dict[str, str] = {
    slug: f"asn.{asn}" for slug, asn in CLOUDFLARE_ASN_MAP.items() if asn
}
# IODA also supports country-level: "country.ZA"
IODA_COUNTRY_ENTITY = "country.ZA"

# RIPE Atlas probe IDs located in South Africa (public probes)
# These are real SA-based probe IDs from the RIPE Atlas network
RIPE_ATLAS_SA_PROBES: List[int] = [
    6083,       # Johannesburg
    6354,       # Cape Town
    13498,      # Durban
    14018,      # Pretoria
    30808,      # Johannesburg (Vumatel)
    33362,      # Cape Town (RSAWEB)
    52148,      # Johannesburg (Afrihost)
]

# Statuspage.io — ISPs that use Atlassian Statuspage (structured JSON API)
# Format: base_url → appends /api/v2/status.json, /api/v2/incidents.json, etc.
STATUSPAGE_API_MAP: Dict[str, str] = {
    "afrihost":     "https://status.afrihost.com",
    "rsaweb":       "https://status.rsaweb.co.za",
    # Add more as ISPs adopt Statuspage or similar
}

# ISPs that support inbound webhook registration for push-based status
WEBHOOK_CAPABLE_ISPS: Dict[str, Dict[str, Any]] = {
    # Format: { "subscribe_url": "...", "auth_type": "bearer|apikey|none" }
    # Populated when ISPs provide webhook endpoints
}

# BGP Looking Glass servers in SA for route health checks
LOOKING_GLASS_SERVERS: Dict[str, str] = {
    "teraco-jnb":   "https://lg.teraco.co.za",      # Teraco Johannesburg IX
    "nap-africa":   "https://lg.napafrica.net",       # NAPAfrica peering
}


# ==========================================================================
# 1. CLOUDFLARE RADAR INTEGRATION
#    Free API — detects traffic anomalies per ASN
#    Docs: https://developers.cloudflare.com/radar/
# ==========================================================================
class CloudflareRadarProvider:
    """
    Queries Cloudflare Radar for traffic anomalies on SA ISP networks.

    Cloudflare sees ~20% of global internet traffic, making their
    anomaly detection highly reliable for large ISPs. For smaller
    ISPs (Stem, X-DSL), this won't have signal — we fall back to
    other methods.

    API: GET https://api.cloudflare.com/client/v4/radar/traffic/anomalies
    Auth: Bearer token (free tier available)
    """

    BASE_URL = "https://api.cloudflare.com/client/v4/radar"

    def __init__(self, http_client: httpx.AsyncClient):
        self.http = http_client

    async def check_isp(self, isp_id: int, isp_slug: str) -> Optional[StatusCheckResult]:
        """Check Cloudflare Radar for traffic anomalies on this ISP's ASN."""
        asn = CLOUDFLARE_ASN_MAP.get(isp_slug)
        if not asn:
            return None     # no ASN mapped — skip this provider

        if not config.CLOUDFLARE_RADAR_TOKEN:
            return None     # no API token configured

        try:
            # Check traffic anomalies for this ASN in last 2 hours
            response = await self.http.get(
                f"{self.BASE_URL}/traffic/anomalies",
                params={
                    "asn": asn,
                    "dateRange": "2h",
                    "limit": 5,
                    "status": "ACTIVE",
                },
                headers={
                    "Authorization": f"Bearer {config.CLOUDFLARE_RADAR_TOKEN}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 200:
                data = response.json()
                anomalies = data.get("result", {}).get("anomalies", [])

                if anomalies:
                    # Active anomaly detected
                    latest = anomalies[0]
                    anomaly_type = latest.get("type", "unknown")
                    start_time = latest.get("startDate", "")
                    description = latest.get("description", "Traffic anomaly detected")

                    return StatusCheckResult(
                        isp_id=isp_id,
                        check_method=CheckMethod.CLOUDFLARE_RADAR,
                        is_up=False,
                        raw_status=f"Cloudflare Radar: {anomaly_type} anomaly — {description}"[:500],
                        source=f"cloudflare_radar:asn_{asn}",
                    )
                else:
                    return StatusCheckResult(
                        isp_id=isp_id,
                        check_method=CheckMethod.CLOUDFLARE_RADAR,
                        is_up=True,
                        raw_status=f"Cloudflare Radar: No anomalies for ASN {asn}",
                        source=f"cloudflare_radar:asn_{asn}",
                    )

            elif response.status_code == 429:
                logger.warning("Cloudflare Radar rate limited — backing off")
                return None

            else:
                return StatusCheckResult(
                    isp_id=isp_id,
                    check_method=CheckMethod.CLOUDFLARE_RADAR,
                    is_up=None,
                    error_message=f"Cloudflare API HTTP {response.status_code}",
                    source=f"cloudflare_radar:asn_{asn}",
                )

        except Exception as e:
            logger.error(f"Cloudflare Radar check failed for {isp_slug}: {e}")
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.CLOUDFLARE_RADAR,
                is_up=None,
                error_message=str(e)[:500],
                source=f"cloudflare_radar:asn_{asn}",
            )

    async def get_country_overview(self) -> Optional[Dict]:
        """
        Get overall South Africa internet traffic status.
        Useful for detecting nationwide outages (load shedding, undersea cable cuts).
        """
        if not config.CLOUDFLARE_RADAR_TOKEN:
            return None

        try:
            response = await self.http.get(
                f"{self.BASE_URL}/traffic/anomalies",
                params={
                    "location": "ZA",
                    "dateRange": "6h",
                    "limit": 10,
                },
                headers={
                    "Authorization": f"Bearer {config.CLOUDFLARE_RADAR_TOKEN}",
                },
            )
            if response.status_code == 200:
                return response.json().get("result", {})
        except Exception as e:
            logger.error(f"Cloudflare country overview failed: {e}")
        return None


# ==========================================================================
# 2. IODA / CAIDA INTEGRATION
#    Internet Outage Detection and Analysis (Georgia Tech / CAIDA)
#    Free, no auth required
#    Docs: https://api.ioda.inetintel.cc.gatech.edu/v2/
# ==========================================================================
class IODAProvider:
    """
    Queries IODA for internet outage signals using three independent
    data sources:
    - BGP: routing table changes indicating network unreachability
    - Active Probing: ping/traceroute measurements to target networks
    - Darknet/Telescope: unsolicited traffic patterns indicating scanning
      from networks that have lost legitimate connectivity

    IODA is particularly good at detecting partial outages that
    Cloudflare might miss — e.g. a single ISP losing upstream connectivity
    while Cloudflare's CDN traffic looks normal.
    """

    BASE_URL = "https://api.ioda.inetintel.cc.gatech.edu/v2"

    def __init__(self, http_client: httpx.AsyncClient):
        self.http = http_client

    async def check_isp(self, isp_id: int, isp_slug: str) -> Optional[StatusCheckResult]:
        """Check IODA for outage alerts on this ISP's ASN."""
        entity = IODA_ENTITY_MAP.get(isp_slug)
        if not entity:
            return None     # no ASN mapped

        try:
            # Query IODA alerts for this entity in last 2 hours
            now = datetime.now(timezone.utc)
            two_hours_ago = now - timedelta(hours=2)

            response = await self.http.get(
                f"{self.BASE_URL}/alerts",
                params={
                    "entity": entity,
                    "from": int(two_hours_ago.timestamp()),
                    "until": int(now.timestamp()),
                    "limit": 10,
                },
            )

            if response.status_code == 200:
                data = response.json()
                alerts = data.get("data", [])

                # Filter for active / ongoing alerts
                active_alerts = [
                    a for a in alerts
                    if a.get("level", "").lower() in ("critical", "warning")
                ]

                if active_alerts:
                    highest = active_alerts[0]
                    level = highest.get("level", "unknown")
                    datasource = highest.get("datasource", "unknown")
                    condition = highest.get("condition", "")

                    is_up = False if level == "critical" else None
                    return StatusCheckResult(
                        isp_id=isp_id,
                        check_method=CheckMethod.IODA,
                        is_up=is_up,
                        raw_status=(
                            f"IODA {level}: {datasource} — {condition}"
                        )[:500],
                        source=f"ioda:{entity}",
                    )
                else:
                    return StatusCheckResult(
                        isp_id=isp_id,
                        check_method=CheckMethod.IODA,
                        is_up=True,
                        raw_status=f"IODA: No alerts for {entity}",
                        source=f"ioda:{entity}",
                    )

            elif response.status_code == 404:
                # Entity not tracked by IODA
                return None

            else:
                return StatusCheckResult(
                    isp_id=isp_id,
                    check_method=CheckMethod.IODA,
                    is_up=None,
                    error_message=f"IODA API HTTP {response.status_code}",
                    source=f"ioda:{entity}",
                )

        except Exception as e:
            logger.error(f"IODA check failed for {isp_slug}: {e}")
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.IODA,
                is_up=None,
                error_message=str(e)[:500],
                source=f"ioda:{entity}",
            )

    async def get_isp_timeseries(
        self, isp_slug: str, hours: int = 24
    ) -> Optional[Dict]:
        """
        Get IODA time-series data for an ISP — useful for charting
        outage history on the dashboard.
        Returns BGP, active probing, and darknet signals over time.
        """
        entity = IODA_ENTITY_MAP.get(isp_slug)
        if not entity:
            return None

        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=hours)

            response = await self.http.get(
                f"{self.BASE_URL}/signals/raw/{entity}",
                params={
                    "from": int(start.timestamp()),
                    "until": int(now.timestamp()),
                },
            )
            if response.status_code == 200:
                return response.json().get("data", {})
        except Exception as e:
            logger.error(f"IODA timeseries failed for {isp_slug}: {e}")
        return None

    async def check_south_africa(self) -> Optional[StatusCheckResult]:
        """
        Check overall South Africa internet health.
        Detects nationwide events: undersea cable cuts, Eskom load shedding
        impact on cell towers, etc.
        """
        try:
            now = datetime.now(timezone.utc)
            one_hour_ago = now - timedelta(hours=1)

            response = await self.http.get(
                f"{self.BASE_URL}/alerts",
                params={
                    "entity": IODA_COUNTRY_ENTITY,
                    "from": int(one_hour_ago.timestamp()),
                    "until": int(now.timestamp()),
                },
            )
            if response.status_code == 200:
                data = response.json()
                alerts = data.get("data", [])
                critical = [a for a in alerts if a.get("level") == "critical"]
                if critical:
                    return StatusCheckResult(
                        isp_id=0,       # country-level, no specific ISP
                        check_method=CheckMethod.IODA,
                        is_up=False,
                        raw_status=f"IODA: South Africa-wide internet disruption detected",
                        source="ioda:country.ZA",
                    )
        except Exception as e:
            logger.error(f"IODA SA country check failed: {e}")
        return None


# ==========================================================================
# 3. RIPE ATLAS INTEGRATION
#    Network measurement platform with probes across SA
#    API key required (free tier: 500K credits/day)
#    Docs: https://atlas.ripe.net/docs/apis/
# ==========================================================================
class RIPEAtlasProvider:
    """
    Uses RIPE Atlas probes physically located in South Africa to run
    active measurements against ISP infrastructure.

    This gives us ground truth from actual SA locations — unlike
    Cloudflare/IODA which infer from traffic patterns, RIPE Atlas
    probes physically try to reach targets from within SA networks.

    Measurement types:
    - Ping: latency + packet loss to ISP gateway/DNS
    - DNS: can the ISP's DNS servers resolve?
    - Traceroute: is the path to the ISP healthy?
    """

    BASE_URL = "https://atlas.ripe.net/api/v2"

    def __init__(self, http_client: httpx.AsyncClient):
        self.http = http_client
        # Cache of active measurement IDs: {isp_slug: measurement_id}
        self._active_measurements: Dict[str, int] = {}

    async def check_isp(self, isp_id: int, isp_slug: str) -> Optional[StatusCheckResult]:
        """
        Check latest RIPE Atlas measurement results for this ISP.
        Uses existing one-off measurements or creates new ones.
        """
        if not config.RIPE_ATLAS_API_KEY:
            return None

        asn = CLOUDFLARE_ASN_MAP.get(isp_slug)
        if not asn:
            return None

        try:
            # Check if we have an active measurement for this ISP
            msm_id = self._active_measurements.get(isp_slug)

            if msm_id:
                # Fetch latest results from existing measurement
                return await self._get_measurement_results(isp_id, isp_slug, msm_id)
            else:
                # Use built-in RIPE Atlas anchoring measurements
                # Query for any recent measurements targeting this ASN
                return await self._check_anchor_measurements(isp_id, isp_slug, asn)

        except Exception as e:
            logger.error(f"RIPE Atlas check failed for {isp_slug}: {e}")
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.RIPE_ATLAS,
                is_up=None,
                error_message=str(e)[:500],
                source=f"ripe_atlas:asn_{asn}",
            )

    async def create_one_off_measurement(
        self, isp_slug: str, target_ip: str, description: str = ""
    ) -> Optional[int]:
        """
        Create a one-off ping measurement from SA probes to an ISP target.
        Returns measurement ID for result retrieval.
        Uses RIPE Atlas credits (free tier: 500K/day).
        """
        if not config.RIPE_ATLAS_API_KEY:
            return None

        try:
            payload = {
                "definitions": [
                    {
                        "type": "ping",
                        "af": 4,
                        "target": target_ip,
                        "description": description or f"HC-v11 ISP check: {isp_slug}",
                        "packets": 5,
                        "size": 48,
                    }
                ],
                "probes": [
                    {
                        "type": "probes",
                        "value": ",".join(str(p) for p in RIPE_ATLAS_SA_PROBES[:5]),
                        "requested": min(5, len(RIPE_ATLAS_SA_PROBES)),
                    }
                ],
                "is_oneoff": True,
            }

            response = await self.http.post(
                f"{self.BASE_URL}/measurements/",
                json=payload,
                headers={"Authorization": f"Key {config.RIPE_ATLAS_API_KEY}"},
            )

            if response.status_code == 201:
                result = response.json()
                msm_id = result.get("measurements", [None])[0]
                if msm_id:
                    self._active_measurements[isp_slug] = msm_id
                    logger.info(f"RIPE Atlas measurement created: {msm_id} for {isp_slug}")
                return msm_id
            else:
                logger.warning(
                    f"RIPE Atlas measurement creation failed: {response.status_code}"
                )
                return None

        except Exception as e:
            logger.error(f"RIPE Atlas measurement creation failed: {e}")
            return None

    async def _get_measurement_results(
        self, isp_id: int, isp_slug: str, msm_id: int
    ) -> StatusCheckResult:
        """Fetch and interpret results from a RIPE Atlas measurement."""
        response = await self.http.get(
            f"{self.BASE_URL}/measurements/{msm_id}/latest/",
            params={"format": "json"},
            headers={"Authorization": f"Key {config.RIPE_ATLAS_API_KEY}"},
        )

        if response.status_code != 200:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.RIPE_ATLAS,
                is_up=None,
                error_message=f"Measurement {msm_id} fetch failed: HTTP {response.status_code}",
                source=f"ripe_atlas:msm_{msm_id}",
            )

        results = response.json()
        if not results:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.RIPE_ATLAS,
                is_up=None,
                raw_status="No results yet for measurement",
                source=f"ripe_atlas:msm_{msm_id}",
            )

        # Analyse probe results
        reachable = 0
        unreachable = 0
        total_rtt = 0.0
        rtt_count = 0
        total_loss = 0.0

        for probe_result in results:
            avg_rtt = probe_result.get("avg", -1)
            if avg_rtt >= 0:
                reachable += 1
                total_rtt += avg_rtt
                rtt_count += 1
            else:
                unreachable += 1

            # Packet loss
            sent = probe_result.get("sent", 0)
            rcvd = probe_result.get("rcvd", 0)
            if sent > 0:
                total_loss += ((sent - rcvd) / sent) * 100

        total_probes = reachable + unreachable
        avg_latency = total_rtt / rtt_count if rtt_count > 0 else None
        avg_loss = total_loss / total_probes if total_probes > 0 else None

        # Decision: >50% probes can reach → up, otherwise down
        if total_probes == 0:
            is_up = None
            status = "No probe data available"
        elif reachable / total_probes > 0.5:
            is_up = True
            status = f"RIPE Atlas: {reachable}/{total_probes} probes reachable, avg {avg_latency:.1f}ms"
        else:
            is_up = False
            status = f"RIPE Atlas: Only {reachable}/{total_probes} probes reachable"

        return StatusCheckResult(
            isp_id=isp_id,
            check_method=CheckMethod.RIPE_ATLAS,
            is_up=is_up,
            latency_ms=round(avg_latency, 2) if avg_latency else None,
            packet_loss_pct=round(avg_loss, 2) if avg_loss else None,
            raw_status=status[:500],
            source=f"ripe_atlas:msm_{msm_id}",
        )

    async def _check_anchor_measurements(
        self, isp_id: int, isp_slug: str, asn: int
    ) -> Optional[StatusCheckResult]:
        """
        Check RIPE Atlas anchor measurements that target this ASN.
        Anchors run continuous measurements — we piggyback on existing data.
        """
        try:
            response = await self.http.get(
                f"{self.BASE_URL}/measurements/",
                params={
                    "target_asn": asn,
                    "type": "ping",
                    "status": 2,        # ongoing
                    "sort": "-id",
                    "page_size": 3,
                },
                headers={"Authorization": f"Key {config.RIPE_ATLAS_API_KEY}"},
            )

            if response.status_code == 200:
                data = response.json()
                measurements = data.get("results", [])
                if measurements:
                    msm_id = measurements[0]["id"]
                    return await self._get_measurement_results(isp_id, isp_slug, msm_id)

        except Exception as e:
            logger.debug(f"RIPE Atlas anchor check failed for ASN {asn}: {e}")

        return None


# ==========================================================================
# 4. STATUSPAGE.IO API INTEGRATION
#    Structured JSON API from ISPs using Atlassian Statuspage
#    No auth required for public status pages
#    Docs: https://developer.statuspage.io/
# ==========================================================================
class StatuspageProvider:
    """
    Queries the Statuspage.io JSON API for ISPs that use Atlassian
    Statuspage (Afrihost, RSAWEB, etc.).

    This is more reliable than HTML scraping because:
    - Structured JSON response with defined fields
    - Component-level status (not just overall)
    - Active incidents with updates and timelines
    - Scheduled maintenance windows
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self.http = http_client

    async def check_isp(self, isp_id: int, isp_slug: str) -> Optional[StatusCheckResult]:
        """Check Statuspage.io API for ISP status."""
        base_url = STATUSPAGE_API_MAP.get(isp_slug)
        if not base_url:
            return None

        try:
            # Get overall status
            status_result = await self._get_status(base_url)

            # Get active incidents
            incidents = await self._get_active_incidents(base_url)

            # Combine signals
            is_up = True
            status_parts = []

            if status_result:
                indicator = status_result.get("status", {}).get("indicator", "none")
                description = status_result.get("status", {}).get("description", "")

                if indicator in ("critical", "major"):
                    is_up = False
                    status_parts.append(f"Statuspage: {description}")
                elif indicator in ("minor", "maintenance"):
                    # Degraded but not fully down
                    status_parts.append(f"Statuspage: {description}")
                else:
                    status_parts.append(f"Statuspage: {description}")

            if incidents:
                # Active incidents override status
                for incident in incidents[:3]:
                    impact = incident.get("impact", "none")
                    name = incident.get("name", "Unknown incident")
                    if impact in ("critical", "major"):
                        is_up = False
                    status_parts.append(f"Incident: {name} ({impact})")

            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.STATUSPAGE_API,
                is_up=is_up,
                raw_status=" | ".join(status_parts)[:500] if status_parts else "No status data",
                source=f"statuspage_api:{base_url}",
            )

        except Exception as e:
            logger.error(f"Statuspage check failed for {isp_slug}: {e}")
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.STATUSPAGE_API,
                is_up=None,
                error_message=str(e)[:500],
                source=f"statuspage_api:{base_url}",
            )

    async def _get_status(self, base_url: str) -> Optional[Dict]:
        """GET /api/v2/status.json — overall page status."""
        try:
            response = await self.http.get(
                f"{base_url}/api/v2/status.json",
                timeout=10,
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    async def _get_active_incidents(self, base_url: str) -> List[Dict]:
        """GET /api/v2/incidents/unresolved.json — active incidents."""
        try:
            response = await self.http.get(
                f"{base_url}/api/v2/incidents/unresolved.json",
                timeout=10,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("incidents", [])
        except Exception:
            pass
        return []

    async def get_components(self, isp_slug: str) -> List[Dict]:
        """
        Get individual component statuses — useful for distinguishing
        between 'Fibre' vs 'DSL' vs 'Email' outages.
        """
        base_url = STATUSPAGE_API_MAP.get(isp_slug)
        if not base_url:
            return []

        try:
            response = await self.http.get(
                f"{base_url}/api/v2/components.json",
                timeout=10,
            )
            if response.status_code == 200:
                return response.json().get("components", [])
        except Exception:
            pass
        return []

    async def get_scheduled_maintenances(self, isp_slug: str) -> List[Dict]:
        """
        Get upcoming scheduled maintenance windows.
        Useful for: not alerting during planned maintenance,
        and proactively warning clients.
        """
        base_url = STATUSPAGE_API_MAP.get(isp_slug)
        if not base_url:
            return []

        try:
            response = await self.http.get(
                f"{base_url}/api/v2/scheduled-maintenances/upcoming.json",
                timeout=10,
            )
            if response.status_code == 200:
                return response.json().get("scheduled_maintenances", [])
        except Exception:
            pass
        return []


# ==========================================================================
# 5. ISP WEBHOOK RECEIVER
#    Receives push-based status updates from ISPs that support webhooks
#    FastAPI endpoint to register in router.py
# ==========================================================================
class ISPWebhookHandler:
    """
    Handles inbound webhooks from ISPs that push status updates.

    Supported formats:
    - Statuspage.io webhook format (JSON)
    - Custom ISP webhook format (JSON)
    - PagerDuty-style event format (JSON)

    Register in router.py:
        @router.post("/webhooks/{isp_slug}")
        async def receive_isp_webhook(isp_slug: str, payload: dict):
            result = webhook_handler.process(isp_slug, payload)
    """

    def __init__(self):
        # Shared secret per ISP for webhook signature verification
        self._secrets: Dict[str, str] = {}

    def register_secret(self, isp_slug: str, secret: str):
        """Register webhook signing secret for an ISP."""
        self._secrets[isp_slug] = secret

    def process_statuspage_webhook(
        self, isp_id: int, isp_slug: str, payload: Dict
    ) -> Optional[StatusCheckResult]:
        """
        Process a Statuspage.io webhook payload.

        Statuspage sends webhooks for:
        - component_update: individual component status change
        - incident_update: incident created/updated/resolved
        - maintenance_update: scheduled maintenance changes
        """
        try:
            event_type = payload.get("meta", {}).get("event", "")

            if "incident" in event_type:
                incident = payload.get("incident", {})
                status = incident.get("status", "investigating")
                impact = incident.get("impact", "none")
                name = incident.get("name", "Unknown")

                is_up = impact not in ("critical", "major")

                return StatusCheckResult(
                    isp_id=isp_id,
                    check_method=CheckMethod.WEBHOOK,
                    is_up=is_up,
                    raw_status=f"Webhook: {name} — status={status}, impact={impact}"[:500],
                    source=f"webhook:statuspage:{isp_slug}",
                )

            elif "component" in event_type:
                component = payload.get("component", {})
                comp_name = component.get("name", "Unknown")
                comp_status = component.get("status", "operational")

                is_up = comp_status == "operational"

                return StatusCheckResult(
                    isp_id=isp_id,
                    check_method=CheckMethod.WEBHOOK,
                    is_up=is_up,
                    raw_status=f"Webhook: {comp_name} → {comp_status}"[:500],
                    source=f"webhook:statuspage:{isp_slug}",
                )

        except Exception as e:
            logger.error(f"Webhook processing failed for {isp_slug}: {e}")

        return None

    def process_generic_webhook(
        self, isp_id: int, isp_slug: str, payload: Dict
    ) -> Optional[StatusCheckResult]:
        """
        Process a generic ISP webhook with flexible field mapping.

        Expected fields (any combination):
        - status: "up" | "down" | "degraded" | "maintenance"
        - message: description
        - severity: "critical" | "major" | "minor" | "none"
        - affected_services: list of service names
        """
        try:
            status = payload.get("status", "").lower()
            message = payload.get("message", "No details provided")
            severity = payload.get("severity", "unknown").lower()

            is_up = None
            if status in ("up", "operational", "resolved"):
                is_up = True
            elif status in ("down", "outage", "critical"):
                is_up = False
            elif severity in ("critical", "major"):
                is_up = False

            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.WEBHOOK,
                is_up=is_up,
                raw_status=f"Webhook: {status} — {message}"[:500],
                source=f"webhook:generic:{isp_slug}",
            )

        except Exception as e:
            logger.error(f"Generic webhook processing failed: {e}")

        return None

    def verify_signature(
        self, isp_slug: str, payload_body: bytes, signature: str
    ) -> bool:
        """
        Verify webhook signature using HMAC-SHA256.
        Returns True if signature is valid.
        """
        import hmac
        import hashlib

        secret = self._secrets.get(isp_slug)
        if not secret:
            logger.warning(f"No webhook secret registered for {isp_slug}")
            return False

        expected = hmac.new(
            secret.encode(), payload_body, hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, signature)


# ==========================================================================
# 6. BGP / LOOKING GLASS INTEGRATION
#    Checks BGP route health via public looking glass servers in SA
#    Detects routing issues that other providers might miss
# ==========================================================================
class BGPLookingGlassProvider:
    """
    Checks BGP route advertisements for SA ISP prefixes via
    public looking glass servers at SA internet exchanges.

    BGP issues (route leaks, hijacks, withdrawn routes) are often
    the root cause of ISP outages. Detecting them early gives us
    a head start on alerting.
    """

    def __init__(self, http_client: httpx.AsyncClient):
        self.http = http_client

    async def check_isp(self, isp_id: int, isp_slug: str) -> Optional[StatusCheckResult]:
        """
        Check BGP route health for an ISP using RIPE RIS (Routing
        Information Service) — free, no auth.
        """
        asn = CLOUDFLARE_ASN_MAP.get(isp_slug)
        if not asn:
            return None

        try:
            # RIPE RIS Looking Glass API
            response = await self.http.get(
                f"https://stat.ripe.net/data/routing-status/data.json",
                params={"resource": f"AS{asn}"},
                timeout=15,
            )

            if response.status_code == 200:
                data = response.json()
                status = data.get("data", {}).get("routing_status", {})

                visibility = status.get("visibility", {})
                v4_full = visibility.get("v4", {}).get("full_table_peers_seeing", 0)
                v4_total = visibility.get("v4", {}).get("full_table_peers_total", 1)

                if v4_total > 0:
                    visibility_pct = (v4_full / v4_total) * 100
                else:
                    visibility_pct = 0

                # If visibility drops below 50%, routes are likely withdrawn
                if visibility_pct < 50:
                    is_up = False
                    status_text = (
                        f"BGP: AS{asn} visibility {visibility_pct:.0f}% "
                        f"({v4_full}/{v4_total} peers) — routes may be withdrawn"
                    )
                elif visibility_pct < 80:
                    is_up = None    # degraded signal, not conclusive
                    status_text = (
                        f"BGP: AS{asn} reduced visibility {visibility_pct:.0f}% "
                        f"({v4_full}/{v4_total} peers)"
                    )
                else:
                    is_up = True
                    status_text = (
                        f"BGP: AS{asn} healthy visibility {visibility_pct:.0f}% "
                        f"({v4_full}/{v4_total} peers)"
                    )

                return StatusCheckResult(
                    isp_id=isp_id,
                    check_method=CheckMethod.BGP_LOOKING_GLASS,
                    is_up=is_up,
                    raw_status=status_text[:500],
                    source=f"ripe_ris:AS{asn}",
                )

        except Exception as e:
            logger.error(f"BGP check failed for {isp_slug}: {e}")
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.BGP_LOOKING_GLASS,
                is_up=None,
                error_message=str(e)[:500],
                source=f"ripe_ris:AS{asn}",
            )

        return None

    async def get_prefix_overview(self, isp_slug: str) -> Optional[Dict]:
        """
        Get announced prefixes for an ISP — useful for detecting
        route hijacks or leaks.
        """
        asn = CLOUDFLARE_ASN_MAP.get(isp_slug)
        if not asn:
            return None

        try:
            response = await self.http.get(
                "https://stat.ripe.net/data/announced-prefixes/data.json",
                params={"resource": f"AS{asn}"},
                timeout=15,
            )
            if response.status_code == 200:
                return response.json().get("data", {})
        except Exception:
            pass
        return None


# ==========================================================================
# INTEGRATION ORCHESTRATOR
# Wires all providers into the detection engine
# ==========================================================================
class NetworkingIntegrationManager:
    """
    Central manager that initialises all networking providers and
    exposes a single check_isp() method that the detection engine calls.

    Add to ISPDetectionEngine.check_isp() to include these providers:

        # In detection_engine.py → ISPDetectionEngine.check_isp():
        from .networking_integrations import NetworkingIntegrationManager

        # In __init__:
        self.networking = NetworkingIntegrationManager()

        # In check_isp() tasks list:
        tasks.append(self.networking.check_all(isp_id, isp_slug))
    """

    def __init__(self):
        self.http_client: Optional[httpx.AsyncClient] = None
        self.cloudflare: Optional[CloudflareRadarProvider] = None
        self.ioda: Optional[IODAProvider] = None
        self.ripe_atlas: Optional[RIPEAtlasProvider] = None
        self.statuspage: Optional[StatuspageProvider] = None
        self.bgp: Optional[BGPLookingGlassProvider] = None
        self.webhook_handler = ISPWebhookHandler()

    async def start(self):
        """Initialise all providers with shared HTTP client."""
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(20),
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
        )
        self.cloudflare = CloudflareRadarProvider(self.http_client)
        self.ioda = IODAProvider(self.http_client)
        self.ripe_atlas = RIPEAtlasProvider(self.http_client)
        self.statuspage = StatuspageProvider(self.http_client)
        self.bgp = BGPLookingGlassProvider(self.http_client)
        logger.info("Networking Integration Manager started — all providers initialised")

    async def stop(self):
        """Shut down shared HTTP client."""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("Networking Integration Manager stopped")

    async def check_all(
        self, isp_id: int, isp_slug: str
    ) -> List[StatusCheckResult]:
        """
        Run all networking provider checks for an ISP.
        Returns list of StatusCheckResult — one per provider that returned data.

        Call this from ISPDetectionEngine.check_isp() alongside existing methods.
        """
        tasks = [
            self.cloudflare.check_isp(isp_id, isp_slug),
            self.ioda.check_isp(isp_id, isp_slug),
            self.ripe_atlas.check_isp(isp_id, isp_slug),
            self.statuspage.check_isp(isp_id, isp_slug),
            self.bgp.check_isp(isp_id, isp_slug),
        ]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for r in raw_results:
            if isinstance(r, StatusCheckResult):
                results.append(r)
            elif isinstance(r, Exception):
                logger.error(f"Provider check failed for {isp_slug}: {r}")
            # None results = provider not applicable for this ISP

        return results

    async def check_country_health(self) -> Dict[str, Any]:
        """
        Run country-level health checks for South Africa.
        Returns combined signal from Cloudflare + IODA.
        """
        results = {}

        if self.cloudflare:
            results["cloudflare_za"] = await self.cloudflare.get_country_overview()

        if self.ioda:
            za_result = await self.ioda.check_south_africa()
            results["ioda_za"] = za_result

        return results
