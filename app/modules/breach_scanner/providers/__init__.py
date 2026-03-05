"""
Threat Intelligence Providers for the Compromised Data Scanner.

Each provider takes a RawFinding and returns a CorroborationResult
indicating whether the finding is confirmed malicious, benign, or unknown.
"""

from __future__ import annotations

import abc
import logging
from typing import Optional

from ..models import CorroborationResult, CorroborationStatus, RawFinding, ThreatIntelSource

logger = logging.getLogger(__name__)


class BaseThreatIntelProvider(abc.ABC):
    """Abstract base for all threat intelligence providers."""

    source: ThreatIntelSource
    name: str

    @abc.abstractmethod
    async def initialise(self) -> None:
        """One-time setup — load rules, check API keys, warm caches."""

    @abc.abstractmethod
    async def corroborate(self, finding: RawFinding) -> Optional[CorroborationResult]:
        """
        Evaluate a finding against this intelligence source.

        Returns CorroborationResult if this provider can assess the finding,
        or None if the finding type is outside this provider's scope.
        """

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True if provider is operational."""

    def _unknown_result(self, detail: str) -> CorroborationResult:
        return CorroborationResult(
            source=self.source,
            status=CorroborationStatus.UNKNOWN,
            confidence=0.0,
            detail=detail,
        )

    def _benign_result(self, detail: str, confidence: float = 0.8) -> CorroborationResult:
        return CorroborationResult(
            source=self.source,
            status=CorroborationStatus.CONFIRMED_BENIGN,
            confidence=confidence,
            detail=detail,
        )


from .virustotal import VirusTotalProvider  # noqa: E402
from .abuse_ipdb import AbuseIPDBProvider  # noqa: E402
from .yara_rules import YaraRulesProvider  # noqa: E402
from .hash_db import HashDBProvider  # noqa: E402
from .mitre_attack import MitreAttackProvider  # noqa: E402

ALL_PROVIDERS: list[type[BaseThreatIntelProvider]] = [
    VirusTotalProvider,
    AbuseIPDBProvider,
    YaraRulesProvider,
    HashDBProvider,
    MitreAttackProvider,
]

__all__ = [
    "BaseThreatIntelProvider",
    "VirusTotalProvider",
    "AbuseIPDBProvider",
    "YaraRulesProvider",
    "HashDBProvider",
    "MitreAttackProvider",
    "ALL_PROVIDERS",
]
