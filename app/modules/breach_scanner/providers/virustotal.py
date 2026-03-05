"""
VirusTotal API v3 provider — file hash lookup, URL/domain reputation.

Checks findings against 70+ AV engines via VirusTotal.
Free tier: 4 requests/minute, 500/day. Premium: unlimited.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from ..config import ScannerConfig
from ..models import (
    CorroborationResult,
    CorroborationStatus,
    RawFinding,
    ThreatIntelSource,
)
from . import BaseThreatIntelProvider

logger = logging.getLogger(__name__)

VT_BASE = "https://www.virustotal.com/api/v3"
RATE_LIMIT_DELAY = 15.5  # seconds between calls (free tier safe)


class VirusTotalProvider(BaseThreatIntelProvider):
    """VirusTotal API v3 — file hash / URL / domain / IP reputation."""

    source = ThreatIntelSource.VIRUSTOTAL
    name = "VirusTotal"

    def __init__(self) -> None:
        self._api_key = ScannerConfig.VIRUSTOTAL_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request: float = 0
        self._threshold = ScannerConfig.VT_MALICIOUS_THRESHOLD

    async def initialise(self) -> None:
        if not self._api_key:
            logger.warning("VirusTotal API key not configured — provider disabled")
            return
        self._client = httpx.AsyncClient(
            base_url=VT_BASE,
            headers={"x-apikey": self._api_key},
            timeout=30.0,
        )
        logger.info("VirusTotal provider initialised")

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.get("/metadata")
            return resp.status_code == 200
        except Exception:
            return False

    async def corroborate(self, finding: RawFinding) -> Optional[CorroborationResult]:
        if not self._client:
            return self._unknown_result("VirusTotal not configured")

        # File hash lookup (primary)
        if finding.file_hash_sha256:
            return await self._lookup_hash(finding.file_hash_sha256)

        if finding.file_hash_md5:
            return await self._lookup_hash(finding.file_hash_md5)

        # Domain/URL lookup
        if finding.network_domain:
            return await self._lookup_domain(finding.network_domain)

        # IP lookup
        if finding.network_ip:
            return await self._lookup_ip(finding.network_ip)

        return None  # Nothing to check against VT

    # ── Hash Lookup ───────────────────────────────────────────────────

    async def _lookup_hash(self, file_hash: str) -> CorroborationResult:
        await self._rate_limit()
        try:
            resp = await self._client.get(f"/files/{file_hash}")
            if resp.status_code == 404:
                return CorroborationResult(
                    source=self.source,
                    status=CorroborationStatus.UNKNOWN,
                    confidence=0.2,
                    detail=f"Hash {file_hash[:16]}... not found in VirusTotal",
                )
            if resp.status_code != 200:
                return self._unknown_result(f"VT API error: {resp.status_code}")

            data = resp.json().get("data", {}).get("attributes", {})
            stats = data.get("last_analysis_stats", {})
            malicious = stats.get("malicious", 0)
            suspicious = stats.get("suspicious", 0)
            undetected = stats.get("undetected", 0)
            total = malicious + suspicious + undetected + stats.get("harmless", 0)
            detection_ratio = f"{malicious}/{total}" if total else "0/0"

            # Extract detection names
            results = data.get("last_analysis_results", {})
            detection_names = [
                f"{engine}: {info.get('result', '')}"
                for engine, info in results.items()
                if info.get("category") == "malicious" and info.get("result")
            ][:20]  # Cap at 20

            # Verdict
            if malicious >= self._threshold:
                status = CorroborationStatus.CONFIRMED_MALICIOUS
                confidence = min(1.0, 0.5 + (malicious / max(total, 1)) * 0.5)
            elif malicious > 0 or suspicious > 0:
                status = CorroborationStatus.LIKELY_MALICIOUS
                confidence = 0.3 + (malicious + suspicious * 0.5) / max(total, 1) * 0.4
            else:
                status = CorroborationStatus.CONFIRMED_BENIGN
                confidence = 0.85

            return CorroborationResult(
                source=self.source,
                status=status,
                confidence=round(confidence, 3),
                detail=f"VirusTotal: {detection_ratio} engines flagged as malicious",
                detection_names=detection_names,
                detection_ratio=detection_ratio,
                reference_urls=[f"https://www.virustotal.com/gui/file/{file_hash}"],
                raw_response={"stats": stats},
            )

        except httpx.TimeoutException:
            return self._unknown_result("VirusTotal request timed out")
        except Exception as exc:
            logger.exception("VirusTotal hash lookup failed")
            return self._unknown_result(f"VT error: {exc}")

    # ── Domain Lookup ─────────────────────────────────────────────────

    async def _lookup_domain(self, domain: str) -> CorroborationResult:
        await self._rate_limit()
        try:
            resp = await self._client.get(f"/domains/{domain}")
            if resp.status_code == 404:
                return self._unknown_result(f"Domain {domain} not in VT")
            if resp.status_code != 200:
                return self._unknown_result(f"VT domain API error: {resp.status_code}")

            data = resp.json().get("data", {}).get("attributes", {})
            stats = data.get("last_analysis_stats", {})
            malicious = stats.get("malicious", 0)
            suspicious = stats.get("suspicious", 0)
            total = sum(stats.values())

            if malicious >= 3:
                status = CorroborationStatus.CONFIRMED_MALICIOUS
                confidence = 0.7 + (malicious / max(total, 1)) * 0.3
            elif malicious > 0 or suspicious > 0:
                status = CorroborationStatus.SUSPICIOUS
                confidence = 0.4
            else:
                status = CorroborationStatus.LIKELY_BENIGN
                confidence = 0.6

            return CorroborationResult(
                source=self.source,
                status=status,
                confidence=round(confidence, 3),
                detail=f"VT domain scan: {malicious}/{total} malicious",
                detection_ratio=f"{malicious}/{total}",
                reference_urls=[f"https://www.virustotal.com/gui/domain/{domain}"],
            )

        except Exception as exc:
            logger.exception("VirusTotal domain lookup failed")
            return self._unknown_result(f"VT domain error: {exc}")

    # ── IP Lookup ─────────────────────────────────────────────────────

    async def _lookup_ip(self, ip: str) -> CorroborationResult:
        await self._rate_limit()
        try:
            resp = await self._client.get(f"/ip_addresses/{ip}")
            if resp.status_code != 200:
                return self._unknown_result(f"VT IP API error: {resp.status_code}")

            data = resp.json().get("data", {}).get("attributes", {})
            stats = data.get("last_analysis_stats", {})
            malicious = stats.get("malicious", 0)
            total = sum(stats.values())

            if malicious >= 3:
                status = CorroborationStatus.CONFIRMED_MALICIOUS
                confidence = 0.65 + (malicious / max(total, 1)) * 0.3
            elif malicious > 0:
                status = CorroborationStatus.SUSPICIOUS
                confidence = 0.35
            else:
                status = CorroborationStatus.LIKELY_BENIGN
                confidence = 0.5

            return CorroborationResult(
                source=self.source,
                status=status,
                confidence=round(confidence, 3),
                detail=f"VT IP scan: {malicious}/{total} malicious",
                detection_ratio=f"{malicious}/{total}",
                reference_urls=[f"https://www.virustotal.com/gui/ip-address/{ip}"],
            )

        except Exception as exc:
            logger.exception("VirusTotal IP lookup failed")
            return self._unknown_result(f"VT IP error: {exc}")

    # ── Rate Limiting ─────────────────────────────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce free-tier rate limit: 4 requests/minute."""
        import time

        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request = time.monotonic()
