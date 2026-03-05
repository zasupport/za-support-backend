"""
Health Check AI — ISP Outage Detection Engine
Multi-method outage detection: status page scraping, Downdetector,
HTTP probes, Health Check agent correlation, AND Networking Integrations
(Cloudflare Radar, IODA, RIPE Atlas, Statuspage API, BGP Looking Glass).

Updated: Networking Integrations section wired into check_isp() pipeline.
"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

import httpx
from bs4 import BeautifulSoup

from .config import config
from .schemas import StatusCheckResult, CheckMethod
from .isp_registry import (
    DOWNDETECTOR_SLUGS,
    STATUS_PAGE_CONFIGS,
    HTTP_PROBE_TARGETS,
)

logger = logging.getLogger("healthcheck.isp_monitor.detection")


class ISPDetectionEngine:
    """
    Runs multiple detection methods against an ISP and returns
    a list of StatusCheckResult objects per check cycle.

    Detection methods (original):
    1. Status page scraping — official ISP status pages
    2. Downdetector scraping — crowd-sourced outage reports
    3. HTTP probe — can we reach the ISP's website?
    4. Agent correlation — Health Check agents reporting offline

    Detection methods (Networking Integrations):
    5. Cloudflare Radar — traffic anomaly detection per ASN
    6. IODA / CAIDA — BGP, active probing, darknet signals
    7. RIPE Atlas — measurement probes physically in SA
    8. Statuspage.io API — structured JSON from ISP status pages
    9. BGP Looking Glass — route visibility via RIPE RIS
    10. ISP Webhooks — push-based status from ISPs (processed via router)
    """

    def __init__(self):
        self.http_client: Optional[httpx.AsyncClient] = None

        # === Networking Integrations ===
        self.networking = None      # initialised in start() if enabled

    async def start(self):
        """Initialise shared HTTP client and networking providers."""
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.SCRAPE_TIMEOUT),
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=True,
            verify=True,
        )

        # Start Networking Integrations if enabled
        if config.NETWORKING_INTEGRATIONS_ENABLED:
            from .networking_integrations import NetworkingIntegrationManager
            self.networking = NetworkingIntegrationManager()
            await self.networking.start()
            logger.info("Networking Integrations enabled — all providers active")
        else:
            logger.info("Networking Integrations disabled — using original methods only")

        logger.info("ISP Detection Engine started")

    async def stop(self):
        """Shut down HTTP client and networking providers."""
        if self.http_client:
            await self.http_client.aclose()

        if self.networking:
            await self.networking.stop()

        logger.info("ISP Detection Engine stopped")

    # ==========================================================
    # PUBLIC: Run all checks for a single ISP
    # ==========================================================
    async def check_isp(self, isp_id: int, isp_slug: str) -> List[StatusCheckResult]:
        """
        Run all available detection methods for a given ISP.
        Returns a list of results (one per method that ran).

        Includes both original methods and Networking Integrations.
        """
        tasks = []

        # --- Original Detection Methods ---

        # 1. Status page scrape
        if isp_slug in STATUS_PAGE_CONFIGS:
            tasks.append(self._check_status_page(isp_id, isp_slug))

        # 2. Downdetector scrape
        if DOWNDETECTOR_SLUGS.get(isp_slug):
            tasks.append(self._check_downdetector(isp_id, isp_slug))

        # 3. HTTP probe (always available)
        if isp_slug in HTTP_PROBE_TARGETS:
            tasks.append(self._check_http_probe(isp_id, isp_slug))

        # --- Networking Integrations ---
        # Runs all enabled providers (Cloudflare, IODA, RIPE Atlas,
        # Statuspage API, BGP) concurrently and returns combined results
        if self.networking:
            tasks.append(self._check_networking_providers(isp_id, isp_slug))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        check_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Detection method failed for {isp_slug}: {r}")
            elif isinstance(r, StatusCheckResult):
                check_results.append(r)
            elif isinstance(r, list):
                # Networking integrations return a list of results
                for item in r:
                    if isinstance(item, StatusCheckResult):
                        check_results.append(item)

        return check_results

    # ==========================================================
    # NETWORKING INTEGRATIONS — Provider Check Wrapper
    # ==========================================================
    async def _check_networking_providers(
        self, isp_id: int, isp_slug: str
    ) -> List[StatusCheckResult]:
        """
        Run all Networking Integration provider checks for an ISP.
        Returns list of StatusCheckResult from all applicable providers.

        This is the integration point between the original detection
        engine and the networking_integrations.py module.
        """
        try:
            results = await self.networking.check_all(isp_id, isp_slug)
            if results:
                providers = [r.check_method.value for r in results]
                logger.debug(
                    f"Networking providers returned {len(results)} results "
                    f"for {isp_slug}: {providers}"
                )
            return results
        except Exception as e:
            logger.error(f"Networking integration check failed for {isp_slug}: {e}")
            return []

    # ==========================================================
    # METHOD 1: Status Page Scraping (original)
    # ==========================================================
    async def _check_status_page(self, isp_id: int, isp_slug: str) -> StatusCheckResult:
        """Scrape an ISP's official status page."""
        cfg = STATUS_PAGE_CONFIGS[isp_slug]
        url = cfg["url"]

        try:
            response = await self.http_client.get(url)
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            page_text = soup.get_text(separator=" ", strip=True).lower()

            # Check for known indicators
            is_up = None
            raw_status = ""

            for indicator in cfg.get("down_indicators", []):
                if indicator.lower() in page_text:
                    is_up = False
                    raw_status = f"Down indicator found: {indicator}"
                    break

            if is_up is None:
                for indicator in cfg.get("up_indicators", []):
                    if indicator.lower() in page_text:
                        is_up = True
                        raw_status = f"Up indicator found: {indicator}"
                        break

            if is_up is None:
                raw_status = "No known indicators matched"

            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.STATUS_PAGE,
                is_up=is_up,
                status_code=response.status_code,
                raw_status=raw_status[:500],
                source=f"status_page:{url}",
            )

        except Exception as e:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.STATUS_PAGE,
                is_up=None,
                error_message=str(e)[:500],
                source=f"status_page:{url}",
            )

    # ==========================================================
    # METHOD 2: Downdetector Scraping (original)
    # ==========================================================
    async def _check_downdetector(self, isp_id: int, isp_slug: str) -> StatusCheckResult:
        """
        Scrape Downdetector ZA for current outage reports.
        Looks for the report count and baseline comparison.
        """
        dd_slug = DOWNDETECTOR_SLUGS.get(isp_slug)
        if not dd_slug:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.DOWNDETECTOR,
                is_up=None,
                error_message="No Downdetector slug configured",
                source="downdetector:none",
            )

        url = f"{config.DOWNDETECTOR_BASE_URL}/{dd_slug}/"

        try:
            response = await self.http_client.get(url)
            html = response.text
            soup = BeautifulSoup(html, "html.parser")

            # Extract report count from the page
            report_count = self._extract_downdetector_reports(soup, html)
            is_up = None
            raw_status = ""

            if report_count is not None:
                if report_count > 100:
                    is_up = False
                    raw_status = f"Downdetector: {report_count} reports (likely outage)"
                elif report_count > 50:
                    is_up = False
                    raw_status = f"Downdetector: {report_count} reports (possible issues)"
                else:
                    is_up = True
                    raw_status = f"Downdetector: {report_count} reports (normal)"
            else:
                page_text = soup.get_text(separator=" ", strip=True).lower()
                if "problems at" in page_text or "outage" in page_text:
                    is_up = False
                    raw_status = "Downdetector: Outage text detected on page"
                elif "no problems" in page_text or "no current problems" in page_text:
                    is_up = True
                    raw_status = "Downdetector: No problems reported"
                else:
                    raw_status = "Downdetector: Unable to determine status"

            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.DOWNDETECTOR,
                is_up=is_up,
                status_code=response.status_code,
                raw_status=raw_status[:500],
                source=f"downdetector:{url}",
            )

        except Exception as e:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.DOWNDETECTOR,
                is_up=None,
                error_message=str(e)[:500],
                source=f"downdetector:{url}",
            )

    def _extract_downdetector_reports(self, soup: BeautifulSoup, html: str) -> Optional[int]:
        """
        Extract the current report count from Downdetector.
        Downdetector's HTML structure changes frequently, so we try
        multiple extraction strategies.
        """
        # Strategy 1: Look for JSON-LD or embedded data
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict) and "reports" in str(data):
                    count = re.search(r'"reports":\s*(\d+)', str(data))
                    if count:
                        return int(count.group(1))
            except (json.JSONDecodeError, AttributeError):
                continue

        # Strategy 2: Regex for report count in page text
        patterns = [
            r'(\d+)\s*(?:reports?|problems?)\s*(?:in the last|reported)',
            r'(?:reports?|problems?)\s*(?:in the last|today)[:\s]*(\d+)',
            r'"currentReports":\s*(\d+)',
            r'data-reports="(\d+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return int(match.group(1))

        # Strategy 3: Look for chart/graph data
        chart_match = re.search(r'"reports":\[([^\]]+)\]', html)
        if chart_match:
            try:
                values = [int(x) for x in re.findall(r'\d+', chart_match.group(1))]
                if values:
                    return max(values[-6:])
            except (ValueError, IndexError):
                pass

        return None

    # ==========================================================
    # METHOD 3: HTTP Probe (original)
    # ==========================================================
    async def _check_http_probe(self, isp_id: int, isp_slug: str) -> StatusCheckResult:
        """
        Simple HTTP GET to the ISP's website.
        If we can reach it, basic DNS/routing is working.
        NOTE: This checks from OUR server, not the client's location.
        """
        url = HTTP_PROBE_TARGETS.get(isp_slug)
        if not url:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.HTTP,
                is_up=None,
                error_message="No HTTP probe target configured",
                source="http_probe:none",
            )

        try:
            start_time = asyncio.get_event_loop().time()
            response = await self.http_client.get(url)
            elapsed_ms = (asyncio.get_event_loop().time() - start_time) * 1000

            is_up = response.status_code < 500
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.HTTP,
                is_up=is_up,
                latency_ms=round(elapsed_ms, 2),
                status_code=response.status_code,
                raw_status=f"HTTP {response.status_code} in {elapsed_ms:.0f}ms",
                source=f"http_probe:{url}",
            )

        except httpx.TimeoutException:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.HTTP,
                is_up=False,
                error_message=f"Timeout after {config.SCRAPE_TIMEOUT}s",
                source=f"http_probe:{url}",
            )
        except Exception as e:
            return StatusCheckResult(
                isp_id=isp_id,
                check_method=CheckMethod.HTTP,
                is_up=None,
                error_message=str(e)[:500],
                source=f"http_probe:{url}",
            )


class OutageCorrelator:
    """
    Correlates multiple detection signals to determine if a real outage
    is occurring and its severity.

    Updated decision logic (includes Networking Integrations):
    - 2+ methods report DOWN → confirm outage
    - 1 method DOWN + agent(s) offline → confirm outage
    - Agent(s) offline only → possible outage (needs investigation)
    - 1 method DOWN only → flag for monitoring
    - Packet loss > threshold → degraded
    - BGP visibility drop → confirm outage (routing issue)
    - Cloudflare + IODA both flag → confirm outage (high confidence)

    Networking Integration signals are weighted:
    - CLOUDFLARE_RADAR: high weight (sees 20% of global traffic)
    - IODA: high weight (3 independent data sources)
    - RIPE_ATLAS: highest weight (ground truth from SA probes)
    - STATUSPAGE_API: medium weight (ISP self-reported)
    - BGP_LOOKING_GLASS: high weight (routing = root cause)
    - WEBHOOK: high weight (ISP push = confirmed)
    """

    # Methods with higher reliability get higher weight in correlation
    METHOD_WEIGHTS = {
        "ripe_atlas": 3,            # ground truth from physical probes
        "agent": 3,                 # ground truth from client device
        "bgp_looking_glass": 2,     # routing issues = root cause
        "cloudflare_radar": 2,      # massive traffic visibility
        "ioda": 2,                  # 3 independent data sources
        "webhook": 2,               # ISP confirmed
        "statuspage_api": 1,        # ISP self-reported (may lag)
        "status_page": 1,           # scraped (fragile)
        "downdetector": 1,          # crowd-sourced (noisy)
        "http": 1,                  # server-side only
        "ping": 1,                  # server-side only
    }

    def __init__(self, confirmation_threshold: int = 3):
        self.confirmation_threshold = confirmation_threshold
        # Track consecutive failures per ISP: {isp_id: {method: count}}
        self.failure_counts: Dict[int, Dict[str, int]] = {}

    def evaluate(
        self,
        isp_id: int,
        check_results: List[StatusCheckResult],
        agents_offline: int = 0,
        agents_total: int = 0,
    ) -> Tuple[Optional[str], str]:
        """
        Evaluate check results and return (severity, reason).
        Returns (None, "") if no outage detected.

        severity: "full", "partial", "degraded", or None
        reason: human-readable explanation
        """
        if isp_id not in self.failure_counts:
            self.failure_counts[isp_id] = {}

        down_methods = []
        degraded_methods = []
        up_methods = []
        weighted_down_score = 0
        weighted_up_score = 0

        for result in check_results:
            method = result.check_method.value
            weight = self.METHOD_WEIGHTS.get(method, 1)

            if result.is_up is False:
                down_methods.append(method)
                weighted_down_score += weight
                self.failure_counts[isp_id][method] = \
                    self.failure_counts[isp_id].get(method, 0) + 1
            elif result.is_up is True:
                up_methods.append(method)
                weighted_up_score += weight
                self.failure_counts[isp_id][method] = 0

            # Check for degraded (high packet loss or latency)
            if result.packet_loss_pct and result.packet_loss_pct > config.OUTAGE_DEGRADED_THRESHOLD:
                degraded_methods.append(method)

        # Count how many methods have consecutive failures above threshold
        confirmed_down = sum(
            1 for m, c in self.failure_counts[isp_id].items()
            if c >= self.confirmation_threshold
        )

        # Agent status
        agent_pct_offline = (agents_offline / agents_total * 100) if agents_total > 0 else 0

        # ===========================================================
        # ENHANCED DECISION MATRIX (with Networking Integration weights)
        # ===========================================================

        # Full outage: high-weight providers confirm down
        if weighted_down_score >= 4 and confirmed_down >= 1:
            return "full", (
                f"High-confidence outage confirmed by weighted providers: "
                f"{', '.join(down_methods)} (score: {weighted_down_score})"
            )

        # Full outage: 2+ methods confirmed down (original logic)
        if confirmed_down >= 2:
            return "full", f"Multiple detection methods confirm outage: {', '.join(down_methods)}"

        # Full outage: BGP visibility drop (routing = root cause)
        if "bgp_looking_glass" in down_methods and confirmed_down >= 1:
            return "full", (
                f"BGP route withdrawal detected + {', '.join(down_methods)} confirming"
            )

        # Full outage: 1 method + most agents offline (original logic)
        if confirmed_down >= 1 and agent_pct_offline > 50:
            return "full", (
                f"Detection method ({', '.join(down_methods)}) + "
                f"{agents_offline}/{agents_total} client agents offline"
            )

        # Partial: 1 method down consistently
        if confirmed_down >= 1:
            return "partial", f"Detection method reports down: {', '.join(down_methods)}"

        # Degraded: agents reporting high packet loss or agents partially offline
        if degraded_methods:
            return "degraded", f"High packet loss detected via: {', '.join(degraded_methods)}"

        if 0 < agent_pct_offline <= 50:
            return "degraded", f"{agents_offline}/{agents_total} client agents reporting issues"

        # All agents offline but no external signals
        if agents_total > 0 and agents_offline == agents_total and not up_methods:
            return "partial", f"All {agents_total} client agents offline (no external confirmation)"

        return None, ""

    def clear_isp(self, isp_id: int):
        """Reset failure counts when outage resolved."""
        self.failure_counts.pop(isp_id, None)
