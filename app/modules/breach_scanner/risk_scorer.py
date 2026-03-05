"""
Risk Scorer — calculates a 0-100 risk score for each device
based on finding severity, corroboration confidence, active threats,
and time since last scan.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import (
    CorroborationStatus,
    FindingResponse,
    FindingSeverity,
    ScanSessionResponse,
)

logger = logging.getLogger(__name__)

# Severity weights
SEVERITY_WEIGHTS = {
    FindingSeverity.CRITICAL: 25,
    FindingSeverity.HIGH: 15,
    FindingSeverity.MEDIUM: 8,
    FindingSeverity.LOW: 3,
    FindingSeverity.INFO: 0,
}

# Corroboration multipliers
CORROBORATION_MULTIPLIER = {
    CorroborationStatus.CONFIRMED_MALICIOUS: 1.5,
    CorroborationStatus.LIKELY_MALICIOUS: 1.2,
    CorroborationStatus.SUSPICIOUS: 0.8,
    CorroborationStatus.UNKNOWN: 0.5,
    CorroborationStatus.LIKELY_BENIGN: 0.1,
    CorroborationStatus.CONFIRMED_BENIGN: 0.0,
    CorroborationStatus.PENDING: 0.5,
}


class RiskScorer:
    """Calculate device risk scores from scan findings."""

    @staticmethod
    def calculate_device_risk(
        findings: list[FindingResponse],
        last_scan: Optional[ScanSessionResponse] = None,
    ) -> float:
        """
        Calculate a 0-100 risk score for a device.

        Score components:
        - Finding severity × corroboration confidence (0-70 points)
        - Active unresolved threats bonus (0-15 points)
        - Scan recency penalty (0-15 points — stale scans = higher risk)
        """
        if not findings:
            # No findings but also no recent scan = some uncertainty
            base = 5.0 if last_scan else 15.0
            return min(base + RiskScorer._recency_penalty(last_scan), 100.0)

        # ── Component 1: Finding severity scores (max 70) ────────────
        raw_score = 0.0
        for f in findings:
            if f.is_false_positive:
                continue
            if f.resolved_at is not None:
                continue  # Resolved findings don't count

            weight = SEVERITY_WEIGHTS.get(f.severity, 0)
            multiplier = CORROBORATION_MULTIPLIER.get(
                f.corroboration_status, 0.5
            )
            confidence_factor = max(f.corroboration_confidence, 0.1)
            raw_score += weight * multiplier * confidence_factor

        # Normalize to 0-70 range (diminishing returns)
        finding_score = min(70.0, raw_score * (1 - raw_score / (raw_score + 100)))

        # ── Component 2: Active threat bonus (max 15) ────────────────
        active_confirmed = sum(
            1
            for f in findings
            if f.corroboration_status == CorroborationStatus.CONFIRMED_MALICIOUS
            and not f.is_false_positive
            and f.resolved_at is None
        )
        threat_bonus = min(15.0, active_confirmed * 5.0)

        # ── Component 3: Scan recency penalty (max 15) ───────────────
        recency = RiskScorer._recency_penalty(last_scan)

        total = finding_score + threat_bonus + recency
        return round(min(max(total, 0.0), 100.0), 1)

    @staticmethod
    def _recency_penalty(last_scan: Optional[ScanSessionResponse]) -> float:
        """Penalty for stale or missing scans."""
        if not last_scan or not last_scan.completed_at:
            return 15.0  # Never scanned = maximum recency penalty

        age = datetime.now(timezone.utc) - last_scan.completed_at.replace(
            tzinfo=timezone.utc
            if last_scan.completed_at.tzinfo is None
            else last_scan.completed_at.tzinfo
        )

        if age < timedelta(days=1):
            return 0.0
        elif age < timedelta(days=7):
            return 3.0
        elif age < timedelta(days=14):
            return 6.0
        elif age < timedelta(days=30):
            return 10.0
        else:
            return 15.0

    @staticmethod
    def risk_label(score: float) -> str:
        """Human-readable risk label."""
        if score >= 80:
            return "CRITICAL"
        elif score >= 60:
            return "HIGH"
        elif score >= 35:
            return "MEDIUM"
        elif score >= 10:
            return "LOW"
        else:
            return "MINIMAL"

    @staticmethod
    def risk_colour(score: float) -> str:
        """Brand-consistent colour for risk level."""
        if score >= 80:
            return "#CC0000"  # RED
        elif score >= 60:
            return "#FF9900"  # ORANGE
        elif score >= 35:
            return "#FFCC00"  # YELLOW
        else:
            return "#16A34A"  # GREEN
