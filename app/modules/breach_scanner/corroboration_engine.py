"""
Corroboration Engine — cross-references raw findings against all
threat intelligence providers concurrently, aggregates verdicts,
and calculates composite confidence scores.

This is the brain that separates false positives from real threats.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .config import ScannerConfig
from .models import (
    CorroborationResult,
    CorroborationStatus,
    FindingSeverity,
    RawFinding,
    ThreatIntelSource,
)
from .providers import ALL_PROVIDERS, BaseThreatIntelProvider

logger = logging.getLogger(__name__)

# Provider weight when aggregating verdicts
PROVIDER_WEIGHTS: dict[ThreatIntelSource, float] = {
    ThreatIntelSource.VIRUSTOTAL: 1.0,    # Gold standard — 70+ engines
    ThreatIntelSource.HASH_DB: 0.95,      # Known-malware DB — very high confidence
    ThreatIntelSource.YARA: 0.85,         # Pattern match — strong but can FP
    ThreatIntelSource.ABUSE_IPDB: 0.7,    # IP reputation — good for network findings
    ThreatIntelSource.MITRE_ATTACK: 0.4,  # Context enrichment, not direct detection
}

# Corroboration status to numeric score for aggregation
STATUS_SCORES: dict[CorroborationStatus, float] = {
    CorroborationStatus.CONFIRMED_MALICIOUS: 1.0,
    CorroborationStatus.LIKELY_MALICIOUS: 0.75,
    CorroborationStatus.SUSPICIOUS: 0.4,
    CorroborationStatus.UNKNOWN: 0.0,
    CorroborationStatus.LIKELY_BENIGN: -0.5,
    CorroborationStatus.CONFIRMED_BENIGN: -1.0,
    CorroborationStatus.PENDING: 0.0,
}


class CorroborationEngine:
    """
    Runs findings through all available threat intel providers
    and produces an aggregated verdict.
    """

    def __init__(self) -> None:
        self._providers: list[BaseThreatIntelProvider] = []
        self._initialised = False

    async def initialise(self) -> None:
        """Start all providers."""
        for provider_cls in ALL_PROVIDERS:
            try:
                provider = provider_cls()
                await provider.initialise()
                self._providers.append(provider)
                logger.info("Provider ready: %s", provider.name)
            except Exception as exc:
                logger.error("Failed to initialise provider %s: %s", provider_cls.name, exc)

        self._initialised = True
        logger.info(
            "Corroboration engine ready: %d providers active", len(self._providers)
        )

    async def corroborate_finding(
        self, finding: RawFinding
    ) -> tuple[CorroborationStatus, float, list[CorroborationResult]]:
        """
        Run a single finding through all providers concurrently.

        Returns:
            (aggregate_status, aggregate_confidence, individual_results)
        """
        if not self._initialised:
            await self.initialise()

        # Fan out to all providers concurrently
        tasks = [
            self._safe_corroborate(provider, finding) for provider in self._providers
        ]
        raw_results = await asyncio.gather(*tasks)

        # Filter out None (provider couldn't assess this finding type)
        results: list[CorroborationResult] = [r for r in raw_results if r is not None]

        if not results:
            return CorroborationStatus.UNKNOWN, 0.0, []

        # Aggregate
        status, confidence = self._aggregate_results(results)
        return status, confidence, results

    async def corroborate_batch(
        self, findings: list[RawFinding]
    ) -> list[tuple[CorroborationStatus, float, list[CorroborationResult]]]:
        """Corroborate multiple findings with rate-limit awareness."""
        results = []
        for finding in findings:
            result = await self.corroborate_finding(finding)
            results.append(result)
        return results

    async def provider_health(self) -> dict[str, bool]:
        """Check health of all providers."""
        health = {}
        for provider in self._providers:
            try:
                health[provider.name] = await provider.health_check()
            except Exception:
                health[provider.name] = False
        return health

    # ── Internal ──────────────────────────────────────────────────────

    @staticmethod
    async def _safe_corroborate(
        provider: BaseThreatIntelProvider, finding: RawFinding
    ) -> Optional[CorroborationResult]:
        """Call provider with error isolation."""
        try:
            return await asyncio.wait_for(
                provider.corroborate(finding),
                timeout=ScannerConfig.SCAN_TIMEOUT_SECONDS / 2,
            )
        except asyncio.TimeoutError:
            logger.warning("Provider %s timed out for finding: %s", provider.name, finding.title)
            return None
        except Exception as exc:
            logger.error("Provider %s error: %s", provider.name, exc)
            return None

    def _aggregate_results(
        self, results: list[CorroborationResult]
    ) -> tuple[CorroborationStatus, float]:
        """
        Weighted aggregation of provider verdicts.

        Logic:
        - If ANY provider confirms malicious with high confidence → confirmed
        - Weighted average of scores determines overall status
        - Provider weights reflect reliability
        """
        if not results:
            return CorroborationStatus.UNKNOWN, 0.0

        # Check for strong confirmations
        for r in results:
            if (
                r.status == CorroborationStatus.CONFIRMED_MALICIOUS
                and r.confidence >= 0.85
                and r.source in (ThreatIntelSource.VIRUSTOTAL, ThreatIntelSource.HASH_DB)
            ):
                # One high-confidence confirmation from a gold source is enough
                return CorroborationStatus.CONFIRMED_MALICIOUS, r.confidence

        # Weighted average
        total_weight = 0.0
        weighted_score = 0.0

        for r in results:
            weight = PROVIDER_WEIGHTS.get(r.source, 0.5) * r.confidence
            score = STATUS_SCORES.get(r.status, 0.0)
            weighted_score += score * weight
            total_weight += weight

        if total_weight == 0:
            return CorroborationStatus.UNKNOWN, 0.0

        avg_score = weighted_score / total_weight

        # Map score to status
        if avg_score >= 0.7:
            status = CorroborationStatus.CONFIRMED_MALICIOUS
        elif avg_score >= 0.45:
            status = CorroborationStatus.LIKELY_MALICIOUS
        elif avg_score >= 0.15:
            status = CorroborationStatus.SUSPICIOUS
        elif avg_score >= -0.2:
            status = CorroborationStatus.UNKNOWN
        elif avg_score >= -0.6:
            status = CorroborationStatus.LIKELY_BENIGN
        else:
            status = CorroborationStatus.CONFIRMED_BENIGN

        # Confidence is the absolute certainty in the verdict
        confidence = min(abs(avg_score), 1.0)

        # Boost confidence if multiple providers agree
        agreeing = sum(
            1
            for r in results
            if STATUS_SCORES.get(r.status, 0) * avg_score > 0  # Same direction
        )
        if agreeing >= 3:
            confidence = min(confidence + 0.1, 1.0)

        return status, round(confidence, 3)

    def adjust_severity(
        self,
        original: FindingSeverity,
        corroboration_status: CorroborationStatus,
        confidence: float,
        results: list[CorroborationResult],
    ) -> FindingSeverity:
        """
        Adjust finding severity based on corroboration outcome.

        Confirmed malicious → escalate. Confirmed benign → downgrade.
        """
        severity_order = [
            FindingSeverity.INFO,
            FindingSeverity.LOW,
            FindingSeverity.MEDIUM,
            FindingSeverity.HIGH,
            FindingSeverity.CRITICAL,
        ]
        idx = severity_order.index(original)

        if corroboration_status == CorroborationStatus.CONFIRMED_MALICIOUS:
            # Escalate by 1-2 levels
            boost = 2 if confidence >= 0.85 else 1
            idx = min(idx + boost, len(severity_order) - 1)
        elif corroboration_status == CorroborationStatus.LIKELY_MALICIOUS:
            idx = min(idx + 1, len(severity_order) - 1)
        elif corroboration_status == CorroborationStatus.CONFIRMED_BENIGN:
            idx = max(idx - 2, 0)
        elif corroboration_status == CorroborationStatus.LIKELY_BENIGN:
            idx = max(idx - 1, 0)

        # MITRE kill-chain bonus: multiple tactics = escalate
        for r in results:
            if r.source == ThreatIntelSource.MITRE_ATTACK and len(r.mitre_techniques) >= 3:
                idx = min(idx + 1, len(severity_order) - 1)
                break

        return severity_order[idx]
