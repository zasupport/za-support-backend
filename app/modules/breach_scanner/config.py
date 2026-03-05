"""
Configuration — loads from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from pathlib import Path


class ScannerConfig:
    """Central configuration for the Compromised Data Scanner."""

    # ── API Keys (threat intel corroboration) ──────────────────────────
    VIRUSTOTAL_API_KEY: str = os.getenv("VIRUSTOTAL_API_KEY", "")
    ABUSEIPDB_API_KEY: str = os.getenv("ABUSEIPDB_API_KEY", "")

    # ── Database ───────────────────────────────────────────────────────
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # ── Scan behaviour ────────────────────────────────────────────────
    DEFAULT_SCAN_INTERVAL_HOURS: int = int(os.getenv("SCANNER_INTERVAL_HOURS", "24"))
    MAX_FINDINGS_PER_SCAN: int = int(os.getenv("SCANNER_MAX_FINDINGS", "500"))
    SCAN_TIMEOUT_SECONDS: int = int(os.getenv("SCANNER_TIMEOUT", "600"))
    RECENT_DAYS_LOOKBACK: int = int(os.getenv("SCANNER_LOOKBACK_DAYS", "180"))

    # ── Threat intel thresholds ───────────────────────────────────────
    VT_MALICIOUS_THRESHOLD: int = int(os.getenv("VT_MALICIOUS_THRESHOLD", "3"))
    ABUSEIPDB_CONFIDENCE_THRESHOLD: int = int(os.getenv("ABUSEIPDB_THRESHOLD", "50"))

    # ── YARA rules ────────────────────────────────────────────────────
    YARA_RULES_DIR: str = os.getenv(
        "YARA_RULES_DIR",
        str(Path(__file__).parent / "yara_rules"),
    )

    # ── Alert webhooks ────────────────────────────────────────────────
    ALERT_WEBHOOK_URL: str = os.getenv("SCANNER_ALERT_WEBHOOK", "")
    ALERT_EMAIL_ENABLED: bool = os.getenv("SCANNER_ALERT_EMAIL", "false").lower() == "true"
    ALERT_COOLDOWN_MINUTES: int = int(os.getenv("SCANNER_ALERT_COOLDOWN", "60"))

    # ── Report generation ─────────────────────────────────────────────
    REPORT_OUTPUT_DIR: str = os.getenv(
        "SCANNER_REPORT_DIR",
        str(Path.home() / "Desktop" / "ZA Support Logs"),
    )

    # ── Paths ─────────────────────────────────────────────────────────
    MODULE_DIR: Path = Path(__file__).parent
    TEMPLATES_DIR: Path = MODULE_DIR / "templates"

    # ── Agent endpoint (where agents POST reports) ────────────────────
    AGENT_REPORT_ENDPOINT: str = os.getenv(
        "SCANNER_AGENT_ENDPOINT",
        "/api/v1/breach-scanner/submit-report",
    )
    BACKEND_BASE_URL: str = os.getenv("SCANNER_BACKEND_URL", "http://localhost:8000")

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing optional config items (warnings, not errors)."""
        warnings = []
        if not cls.VIRUSTOTAL_API_KEY:
            warnings.append("VIRUSTOTAL_API_KEY not set — hash corroboration disabled")
        if not cls.ABUSEIPDB_API_KEY:
            warnings.append("ABUSEIPDB_API_KEY not set — IP reputation disabled")
        if not cls.DATABASE_URL:
            warnings.append("DATABASE_URL not set — findings stored in memory only")
        if not cls.ALERT_WEBHOOK_URL:
            warnings.append("SCANNER_ALERT_WEBHOOK not set — webhook alerts disabled")
        return warnings

    @classmethod
    def as_dict(cls) -> dict:
        """Return non-secret config as dictionary for health-check responses."""
        return {
            "scan_interval_hours": cls.DEFAULT_SCAN_INTERVAL_HOURS,
            "max_findings_per_scan": cls.MAX_FINDINGS_PER_SCAN,
            "scan_timeout_seconds": cls.SCAN_TIMEOUT_SECONDS,
            "recent_days_lookback": cls.RECENT_DAYS_LOOKBACK,
            "vt_threshold": cls.VT_MALICIOUS_THRESHOLD,
            "abuseipdb_threshold": cls.ABUSEIPDB_CONFIDENCE_THRESHOLD,
            "yara_rules_dir": cls.YARA_RULES_DIR,
            "report_output_dir": cls.REPORT_OUTPUT_DIR,
            "virustotal_configured": bool(cls.VIRUSTOTAL_API_KEY),
            "abuseipdb_configured": bool(cls.ABUSEIPDB_API_KEY),
            "database_configured": bool(cls.DATABASE_URL),
            "webhook_configured": bool(cls.ALERT_WEBHOOK_URL),
        }
