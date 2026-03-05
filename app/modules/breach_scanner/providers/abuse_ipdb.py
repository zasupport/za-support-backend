"""
AbuseIPDB provider — IP address reputation and abuse confidence scoring.

Checks network-related findings against the AbuseIPDB database of
reported malicious IPs. Free tier: 1,000 checks/day.
"""

from __future__ import annotations

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

ABUSEIPDB_BASE = "https://api.abuseipdb.com/api/v2"


class AbuseIPDBProvider(BaseThreatIntelProvider):
    """AbuseIPDB — IP reputation and abuse confidence scoring."""

    source = ThreatIntelSource.ABUSE_IPDB
    name = "AbuseIPDB"

    def __init__(self) -> None:
        self._api_key = ScannerConfig.ABUSEIPDB_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._threshold = ScannerConfig.ABUSEIPDB_CONFIDENCE_THRESHOLD

    async def initialise(self) -> None:
        if not self._api_key:
            logger.warning("AbuseIPDB API key not configured — provider disabled")
            return
        self._client = httpx.AsyncClient(
            base_url=ABUSEIPDB_BASE,
            headers={
                "Key": self._api_key,
                "Accept": "application/json",
            },
            timeout=20.0,
        )
        logger.info("AbuseIPDB provider initialised")

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            # Check a known-safe IP to verify API access
            resp = await self._client.get(
                "/check",
                params={"ipAddress": "8.8.8.8", "maxAgeInDays": "1"},
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def corroborate(self, finding: RawFinding) -> Optional[CorroborationResult]:
        """Only applies to findings with network IPs."""
        if not finding.network_ip:
            return None  # Not our scope
        if not self._client:
            return self._unknown_result("AbuseIPDB not configured")

        return await self._check_ip(finding.network_ip)

    async def _check_ip(self, ip: str) -> CorroborationResult:
        try:
            resp = await self._client.get(
                "/check",
                params={
                    "ipAddress": ip,
                    "maxAgeInDays": "90",
                    "verbose": "",
                },
            )

            if resp.status_code == 429:
                return self._unknown_result("AbuseIPDB rate limit exceeded")
            if resp.status_code != 200:
                return self._unknown_result(f"AbuseIPDB error: {resp.status_code}")

            data = resp.json().get("data", {})
            abuse_score = data.get("abuseConfidenceScore", 0)
            total_reports = data.get("totalReports", 0)
            country = data.get("countryCode", "??")
            isp = data.get("isp", "Unknown")
            domain = data.get("domain", "")
            is_tor = data.get("isTor", False)
            usage_type = data.get("usageType", "")

            # Extract reported categories
            categories = data.get("reports", [])
            category_summary = {}
            for report in categories[:50]:
                for cat in report.get("categories", []):
                    cat_name = self._category_name(cat)
                    category_summary[cat_name] = category_summary.get(cat_name, 0) + 1

            # Verdict
            if abuse_score >= 80:
                status = CorroborationStatus.CONFIRMED_MALICIOUS
                confidence = 0.85 + (abuse_score - 80) / 200
            elif abuse_score >= self._threshold:
                status = CorroborationStatus.LIKELY_MALICIOUS
                confidence = 0.5 + (abuse_score - self._threshold) / 100
            elif abuse_score >= 20:
                status = CorroborationStatus.SUSPICIOUS
                confidence = 0.35
            elif total_reports > 0:
                status = CorroborationStatus.SUSPICIOUS
                confidence = 0.2
            else:
                status = CorroborationStatus.LIKELY_BENIGN
                confidence = 0.6

            # Tor exit nodes are always suspicious in a medical practice context
            if is_tor:
                status = CorroborationStatus.LIKELY_MALICIOUS
                confidence = max(confidence, 0.7)

            detail_parts = [
                f"AbuseIPDB score: {abuse_score}/100",
                f"{total_reports} reports",
                f"ISP: {isp}",
                f"Country: {country}",
            ]
            if is_tor:
                detail_parts.append("TOR EXIT NODE")
            if category_summary:
                top_cats = sorted(category_summary.items(), key=lambda x: -x[1])[:5]
                detail_parts.append(
                    "Categories: " + ", ".join(f"{k}({v})" for k, v in top_cats)
                )

            return CorroborationResult(
                source=self.source,
                status=status,
                confidence=round(min(confidence, 1.0), 3),
                detail=" | ".join(detail_parts),
                abuse_score=abuse_score,
                reference_urls=[f"https://www.abuseipdb.com/check/{ip}"],
                raw_response={
                    "abuse_score": abuse_score,
                    "total_reports": total_reports,
                    "country": country,
                    "isp": isp,
                    "domain": domain,
                    "is_tor": is_tor,
                    "usage_type": usage_type,
                    "categories": category_summary,
                },
            )

        except httpx.TimeoutException:
            return self._unknown_result("AbuseIPDB request timed out")
        except Exception as exc:
            logger.exception("AbuseIPDB lookup failed")
            return self._unknown_result(f"AbuseIPDB error: {exc}")

    @staticmethod
    def _category_name(cat_id: int) -> str:
        """Map AbuseIPDB category IDs to human-readable names."""
        categories = {
            1: "DNS Compromise",
            2: "DNS Poisoning",
            3: "Fraud Orders",
            4: "DDoS Attack",
            5: "FTP Brute-Force",
            6: "Ping of Death",
            7: "Phishing",
            8: "Fraud VoIP",
            9: "Open Proxy",
            10: "Web Spam",
            11: "Email Spam",
            12: "Blog Spam",
            13: "VPN IP",
            14: "Port Scan",
            15: "Hacking",
            16: "SQL Injection",
            17: "Spoofing",
            18: "Brute-Force",
            19: "Bad Web Bot",
            20: "Exploited Host",
            21: "Web App Attack",
            22: "SSH",
            23: "IoT Targeted",
        }
        return categories.get(cat_id, f"Category-{cat_id}")
