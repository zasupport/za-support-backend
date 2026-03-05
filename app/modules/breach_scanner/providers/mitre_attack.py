"""
MITRE ATT&CK provider — maps findings to techniques, tactics, and procedures.

Does not make external API calls. Uses a built-in mapping of common techniques
to enrich findings with ATT&CK context for reporting and correlation.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..models import (
    CorroborationResult,
    CorroborationStatus,
    FindingCategory,
    RawFinding,
    ThreatIntelSource,
)
from . import BaseThreatIntelProvider

logger = logging.getLogger(__name__)


# ── ATT&CK Technique Database (relevant subset) ──────────────────────

TECHNIQUES: dict[str, dict] = {
    # Initial Access
    "T1566.001": {
        "name": "Spearphishing Attachment",
        "tactic": "Initial Access",
        "description": "Malicious email attachment used to gain initial access",
        "severity_boost": 0.1,
    },
    "T1566.002": {
        "name": "Spearphishing Link",
        "tactic": "Initial Access",
        "description": "Malicious link in email used to gain initial access",
        "severity_boost": 0.1,
    },
    # Execution
    "T1059.001": {
        "name": "PowerShell",
        "tactic": "Execution",
        "description": "PowerShell commands used for execution",
        "severity_boost": 0.15,
    },
    "T1059.004": {
        "name": "Unix Shell",
        "tactic": "Execution",
        "description": "Unix/macOS shell used for command execution",
        "severity_boost": 0.1,
    },
    "T1059.005": {
        "name": "Visual Basic",
        "tactic": "Execution",
        "description": "VBA macro execution in Office documents",
        "severity_boost": 0.15,
    },
    "T1059.006": {
        "name": "Python",
        "tactic": "Execution",
        "description": "Python scripts used for execution",
        "severity_boost": 0.05,
    },
    "T1059.007": {
        "name": "JavaScript",
        "tactic": "Execution",
        "description": "JavaScript used for execution",
        "severity_boost": 0.1,
    },
    "T1204.001": {
        "name": "Malicious Link",
        "tactic": "Execution",
        "description": "User executed malicious link",
        "severity_boost": 0.1,
    },
    "T1204.002": {
        "name": "Malicious File",
        "tactic": "Execution",
        "description": "User executed malicious file",
        "severity_boost": 0.15,
    },
    # Persistence
    "T1543.001": {
        "name": "Launch Agent",
        "tactic": "Persistence",
        "description": "macOS Launch Agent for persistence",
        "severity_boost": 0.15,
    },
    "T1543.004": {
        "name": "Launch Daemon",
        "tactic": "Persistence",
        "description": "macOS Launch Daemon for persistence",
        "severity_boost": 0.2,
    },
    "T1547.001": {
        "name": "Registry Run Keys / Startup Folder",
        "tactic": "Persistence",
        "description": "Windows startup persistence mechanism",
        "severity_boost": 0.15,
    },
    "T1547.009": {
        "name": "Shortcut Modification",
        "tactic": "Persistence",
        "description": "Shortcut modified for persistence",
        "severity_boost": 0.1,
    },
    "T1053.003": {
        "name": "Cron",
        "tactic": "Persistence",
        "description": "Cron job used for persistence",
        "severity_boost": 0.1,
    },
    "T1053.005": {
        "name": "Scheduled Task",
        "tactic": "Persistence",
        "description": "Windows Scheduled Task for persistence",
        "severity_boost": 0.1,
    },
    # Defence Evasion
    "T1027": {
        "name": "Obfuscated Files or Information",
        "tactic": "Defence Evasion",
        "description": "Files or information obfuscated to evade detection",
        "severity_boost": 0.1,
    },
    "T1036.005": {
        "name": "Match Legitimate Name or Location",
        "tactic": "Defence Evasion",
        "description": "Malware disguised as legitimate software",
        "severity_boost": 0.1,
    },
    "T1036.007": {
        "name": "Double File Extension",
        "tactic": "Defence Evasion",
        "description": "File uses double extension to masquerade",
        "severity_boost": 0.15,
    },
    "T1564.001": {
        "name": "Hidden Files and Directories",
        "tactic": "Defence Evasion",
        "description": "Files hidden to evade discovery",
        "severity_boost": 0.05,
    },
    "T1574.001": {
        "name": "DLL Search Order Hijacking",
        "tactic": "Defence Evasion",
        "description": "DLL/dylib search order hijacked",
        "severity_boost": 0.15,
    },
    "T1222.002": {
        "name": "Linux and Mac File and Directory Permissions Modification",
        "tactic": "Defence Evasion",
        "description": "File permissions modified to enable execution",
        "severity_boost": 0.05,
    },
    # Credential Access
    "T1555.001": {
        "name": "Keychain",
        "tactic": "Credential Access",
        "description": "macOS Keychain credential access",
        "severity_boost": 0.2,
    },
    "T1555.003": {
        "name": "Credentials from Web Browsers",
        "tactic": "Credential Access",
        "description": "Browser credential extraction",
        "severity_boost": 0.2,
    },
    # Discovery
    "T1082": {
        "name": "System Information Discovery",
        "tactic": "Discovery",
        "description": "System information gathered for reconnaissance",
        "severity_boost": 0.0,
    },
    # Command and Control
    "T1071.001": {
        "name": "Web Protocols",
        "tactic": "Command and Control",
        "description": "HTTP/HTTPS used for C2 communication",
        "severity_boost": 0.15,
    },
    "T1071.004": {
        "name": "DNS",
        "tactic": "Command and Control",
        "description": "DNS used for C2 communication",
        "severity_boost": 0.2,
    },
    "T1095": {
        "name": "Non-Application Layer Protocol",
        "tactic": "Command and Control",
        "description": "Raw TCP/UDP for C2",
        "severity_boost": 0.15,
    },
    "T1572": {
        "name": "Protocol Tunnelling",
        "tactic": "Command and Control",
        "description": "Traffic tunnelled through legitimate protocols",
        "severity_boost": 0.15,
    },
    # Exfiltration
    "T1041": {
        "name": "Exfiltration Over C2 Channel",
        "tactic": "Exfiltration",
        "description": "Data exfiltrated over command-and-control channel",
        "severity_boost": 0.2,
    },
    "T1048": {
        "name": "Exfiltration Over Alternative Protocol",
        "tactic": "Exfiltration",
        "description": "Data exfiltrated via non-standard protocol",
        "severity_boost": 0.2,
    },
    # Impact
    "T1486": {
        "name": "Data Encrypted for Impact",
        "tactic": "Impact",
        "description": "Ransomware — data encrypted to extort payment",
        "severity_boost": 0.3,
    },
    "T1496": {
        "name": "Resource Hijacking",
        "tactic": "Impact",
        "description": "System resources hijacked for cryptocurrency mining",
        "severity_boost": 0.1,
    },
    "T1505.003": {
        "name": "Web Shell",
        "tactic": "Persistence",
        "description": "Web shell installed for persistent access",
        "severity_boost": 0.25,
    },
}

# Category → most likely techniques mapping
CATEGORY_TECHNIQUE_MAP: dict[FindingCategory, list[str]] = {
    FindingCategory.MALWARE: ["T1204.002"],
    FindingCategory.SUSPICIOUS_FILE: ["T1036.007", "T1564.001", "T1027"],
    FindingCategory.SUSPICIOUS_EMAIL: ["T1566.001", "T1566.002"],
    FindingCategory.COMPROMISED_APP: ["T1574.001"],
    FindingCategory.PERSISTENCE: ["T1543.001", "T1543.004", "T1547.001", "T1053.003"],
    FindingCategory.BROWSER_EXTENSION: ["T1555.003", "T1176"],
    FindingCategory.SUSPICIOUS_PROCESS: ["T1059.004", "T1059.001"],
    FindingCategory.NETWORK_ANOMALY: ["T1071.001", "T1095"],
    FindingCategory.DATA_EXFILTRATION: ["T1041", "T1048"],
    FindingCategory.CRYPTO_MINER: ["T1496"],
    FindingCategory.REMOTE_ACCESS: ["T1071.001", "T1572"],
    FindingCategory.MACRO_PAYLOAD: ["T1059.005", "T1204.002"],
    FindingCategory.PHISHING: ["T1566.001", "T1566.002"],
    FindingCategory.ROOTKIT: ["T1014"],
    FindingCategory.ADWARE: ["T1176"],
    FindingCategory.PUP: [],
}


class MitreAttackProvider(BaseThreatIntelProvider):
    """MITRE ATT&CK technique mapper — enriches findings with TTP context."""

    source = ThreatIntelSource.MITRE_ATTACK
    name = "MITRE ATT&CK"

    async def initialise(self) -> None:
        logger.info(
            "MITRE ATT&CK provider initialised: %d techniques loaded",
            len(TECHNIQUES),
        )

    async def health_check(self) -> bool:
        return True  # Always available — no external deps

    async def corroborate(self, finding: RawFinding) -> Optional[CorroborationResult]:
        """
        Enrich finding with MITRE ATT&CK context. Does not change
        the malicious/benign verdict — that's the other providers' job.
        This adds tactical context for reporting.
        """
        matched_techniques: list[str] = []
        total_severity_boost = 0.0

        # If scanner already tagged a technique, validate and enrich
        if finding.mitre_technique and finding.mitre_technique in TECHNIQUES:
            matched_techniques.append(finding.mitre_technique)
            total_severity_boost += TECHNIQUES[finding.mitre_technique].get(
                "severity_boost", 0
            )

        # Map from category to likely techniques
        category_techniques = CATEGORY_TECHNIQUE_MAP.get(finding.category, [])
        for tech_id in category_techniques:
            if tech_id not in matched_techniques and tech_id in TECHNIQUES:
                matched_techniques.append(tech_id)
                total_severity_boost += (
                    TECHNIQUES[tech_id].get("severity_boost", 0) * 0.5
                )  # Inferred gets half weight

        if not matched_techniques:
            return None  # No ATT&CK context to add

        # Build detail
        technique_details = []
        tactics_seen = set()
        for tech_id in matched_techniques[:5]:
            tech = TECHNIQUES[tech_id]
            technique_details.append(f"{tech_id} {tech['name']}")
            tactics_seen.add(tech["tactic"])

        # Determine status — MITRE enriches but doesn't confirm/deny on its own
        if len(tactics_seen) >= 3:
            # Multiple tactics = potential kill chain progression
            status = CorroborationStatus.LIKELY_MALICIOUS
            confidence = 0.6 + min(total_severity_boost, 0.3)
        elif len(tactics_seen) >= 2:
            status = CorroborationStatus.SUSPICIOUS
            confidence = 0.45 + min(total_severity_boost, 0.2)
        else:
            status = CorroborationStatus.SUSPICIOUS
            confidence = 0.3 + min(total_severity_boost, 0.15)

        kill_chain_note = ""
        if len(tactics_seen) >= 3:
            chain = " → ".join(sorted(tactics_seen))
            kill_chain_note = f" | Kill chain: {chain}"

        return CorroborationResult(
            source=self.source,
            status=status,
            confidence=round(min(confidence, 1.0), 3),
            detail=(
                f"ATT&CK: {', '.join(technique_details)}"
                f" | Tactics: {', '.join(sorted(tactics_seen))}"
                f"{kill_chain_note}"
            ),
            mitre_techniques=matched_techniques,
            reference_urls=[
                f"https://attack.mitre.org/techniques/{t.replace('.', '/')}/"
                for t in matched_techniques[:3]
            ],
        )
