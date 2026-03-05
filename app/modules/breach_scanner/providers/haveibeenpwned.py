"""
Have I Been Pwned (HIBP) API v3 provider.

Checks email addresses found in scan findings against known data breaches.
Requires paid API key for /breachedaccount endpoint.
Rate limit: 1 request per 1.5 seconds (enforced).

API docs: https://haveibeenpwned.com/API/v3
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

HIBP_BASE = "https://haveibeenpwned.com/api/v3"
RATE_LIMIT_DELAY = 1.6  # seconds — HIBP requires min 1500ms between requests


class HaveIBeenPwnedProvider(BaseThreatIntelProvider):
    """
    Have I Been Pwned provider — email breach lookup.

    Activated when a finding contains an email address (email_scanner findings,
    persistence findings with email references, or explicit email asset checks).
    """

    source = ThreatIntelSource.HAVE_I_BEEN_PWNED
    name = "HaveIBeenPwned"

    def __init__(self) -> None:
        self._api_key = ScannerConfig.HIBP_API_KEY
        self._client: Optional[httpx.AsyncClient] = None
        self._last_request: float = 0.0

    async def initialise(self) -> None:
        if not self._api_key:
            logger.warning("HIBP_API_KEY not configured — provider disabled")
            return
        self._client = httpx.AsyncClient(
            base_url=HIBP_BASE,
            headers={
                "hibp-api-key": self._api_key,
                "User-Agent": "ZASupport-HealthCheck/11.0 BreachScanner/1.0",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        logger.info("HaveIBeenPwned provider initialised")

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.get("/breaches")
            return resp.status_code == 200
        except Exception:
            return False

    async def corroborate(self, finding: RawFinding) -> Optional[CorroborationResult]:
        """Check if an email from the finding appears in known breach databases."""
        if not self._client:
            return self._unknown_result("HIBP not configured")

        email = self._extract_email(finding)
        if not email:
            return None  # Finding has no email — not applicable

        return await self._check_email(email)

    def _extract_email(self, finding: RawFinding) -> Optional[str]:
        """Pull email address from finding detail or path fields."""
        import re
        email_re = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

        for field in (finding.detail, finding.file_path, finding.raw_evidence):
            if field:
                match = email_re.search(str(field))
                if match:
                    return match.group(0).lower()
        return None

    async def _check_email(self, email: str) -> CorroborationResult:
        await self._rate_limit()
        try:
            resp = await self._client.get(
                f"/breachedaccount/{email}",
                params={"truncateResponse": "false", "includeUnverified": "true"},
            )

            # 404 = no breaches found — this is clean
            if resp.status_code == 404:
                return self._benign_result(
                    f"HIBP: {email} not found in any known breach",
                    confidence=0.9,
                )

            if resp.status_code == 401:
                return self._unknown_result("HIBP: invalid API key")

            if resp.status_code == 429:
                logger.warning("HIBP rate limit hit — backing off")
                await asyncio.sleep(2.0)
                return self._unknown_result("HIBP: rate limited")

            if resp.status_code != 200:
                return self._unknown_result(f"HIBP API error: {resp.status_code}")

            breaches = resp.json()
            count = len(breaches)

            # Assess severity by breach characteristics
            sensitive = [b for b in breaches if b.get("IsSensitive")]
            verified = [b for b in breaches if b.get("IsVerified")]
            high_risk_classes = {"Passwords", "Credit card numbers", "Bank account numbers",
                                  "Social security numbers", "Health records"}
            critical_breaches = [
                b for b in breaches
                if high_risk_classes.intersection(set(b.get("DataClasses", [])))
            ]

            breach_names = [b.get("Name", "") for b in breaches[:10]]
            data_types = list({dc for b in breaches for dc in b.get("DataClasses", [])})[:15]

            if critical_breaches or (count >= 3 and sensitive):
                status = CorroborationStatus.CONFIRMED_MALICIOUS
                confidence = min(0.95, 0.6 + count * 0.05)
            elif count >= 2 or verified:
                status = CorroborationStatus.LIKELY_MALICIOUS
                confidence = min(0.80, 0.45 + count * 0.05)
            else:
                status = CorroborationStatus.SUSPICIOUS
                confidence = 0.35

            return CorroborationResult(
                source=self.source,
                status=status,
                confidence=round(confidence, 3),
                detail=(
                    f"HIBP: {email} found in {count} breach(es): "
                    f"{', '.join(breach_names[:5])}{'...' if count > 5 else ''}"
                ),
                detection_names=breach_names,
                reference_urls=[f"https://haveibeenpwned.com/account/{email}"],
                raw_response={"breach_count": count, "data_classes": data_types},
            )

        except httpx.TimeoutException:
            return self._unknown_result("HIBP request timed out")
        except Exception as exc:
            logger.exception("HIBP lookup failed")
            return self._unknown_result(f"HIBP error: {exc}")

    async def _rate_limit(self) -> None:
        import time
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request = time.monotonic()
