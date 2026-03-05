"""
YARA Rules provider — local pattern matching against compiled rulesets.

Scans file content / memory buffers against YARA signatures for known
malware patterns, packer signatures, exploit kits, and suspicious constructs.
Zero API calls — all local. Rulesets auto-updated from community feeds.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from ..config import ScannerConfig
from ..models import (
    CorroborationResult,
    CorroborationStatus,
    RawFinding,
    ThreatIntelSource,
)
from . import BaseThreatIntelProvider

logger = logging.getLogger(__name__)


class YaraRulesProvider(BaseThreatIntelProvider):
    """YARA signature matching — local, no API calls."""

    source = ThreatIntelSource.YARA
    name = "YARA Rules"

    def __init__(self) -> None:
        self._rules_dir = Path(ScannerConfig.YARA_RULES_DIR)
        self._compiled_rules = None  # yara.Rules object
        self._yara = None  # yara module reference
        self._rule_count = 0
        self._available = False

    async def initialise(self) -> None:
        try:
            import yara  # noqa: F811

            self._yara = yara
        except ImportError:
            logger.warning(
                "yara-python not installed — YARA provider disabled. "
                "Install: pip install yara-python"
            )
            return

        self._rules_dir.mkdir(parents=True, exist_ok=True)

        # Ensure we have at least a base ruleset
        base_rules = self._rules_dir / "base_rules.yar"
        if not base_rules.exists():
            self._write_base_rules(base_rules)

        # Compile all .yar / .yara files in the rules directory
        rule_files = {}
        for ext in ("*.yar", "*.yara"):
            for f in self._rules_dir.glob(ext):
                namespace = f.stem
                rule_files[namespace] = str(f)

        if not rule_files:
            logger.warning("No YARA rule files found in %s", self._rules_dir)
            return

        try:
            self._compiled_rules = self._yara.compile(filepaths=rule_files)
            self._rule_count = len(rule_files)
            self._available = True
            logger.info(
                "YARA provider initialised: %d rule files compiled from %s",
                self._rule_count,
                self._rules_dir,
            )
        except self._yara.SyntaxError as exc:
            logger.error("YARA compilation error: %s", exc)
        except Exception as exc:
            logger.exception("YARA initialisation failed: %s", exc)

    async def health_check(self) -> bool:
        return self._available and self._compiled_rules is not None

    async def corroborate(self, finding: RawFinding) -> Optional[CorroborationResult]:
        """Scan the file referenced by the finding against YARA rules."""
        if not self._available or not self._compiled_rules:
            return None

        # Only scan findings with a file path that exists
        if not finding.file_path:
            return None

        file_path = Path(finding.file_path)
        if not file_path.exists() or not file_path.is_file():
            return None

        # Skip very large files (>50 MB)
        try:
            size = file_path.stat().st_size
            if size > 50 * 1024 * 1024:
                return self._unknown_result(f"File too large for YARA scan ({size} bytes)")
        except OSError:
            return None

        return await self._scan_file(file_path)

    async def _scan_file(self, file_path: Path) -> CorroborationResult:
        try:
            matches = self._compiled_rules.match(str(file_path), timeout=30)

            if not matches:
                return CorroborationResult(
                    source=self.source,
                    status=CorroborationStatus.LIKELY_BENIGN,
                    confidence=0.4,
                    detail=f"No YARA rules matched ({self._rule_count} rulesets checked)",
                    yara_rules_matched=[],
                )

            # Analyse matches
            rule_names = [m.rule for m in matches]
            namespaces = list(set(m.namespace for m in matches))
            tags_all = []
            for m in matches:
                tags_all.extend(m.tags)
            tags = list(set(tags_all))

            # Severity from tags
            has_malware_tag = any(
                t in tags for t in ("malware", "trojan", "ransomware", "backdoor", "rootkit")
            )
            has_suspicious_tag = any(
                t in tags for t in ("suspicious", "packer", "obfuscation", "exploit")
            )

            if has_malware_tag or len(matches) >= 3:
                status = CorroborationStatus.CONFIRMED_MALICIOUS
                confidence = 0.85 + min(len(matches) * 0.03, 0.15)
            elif has_suspicious_tag or len(matches) >= 2:
                status = CorroborationStatus.LIKELY_MALICIOUS
                confidence = 0.65
            else:
                status = CorroborationStatus.SUSPICIOUS
                confidence = 0.5

            # Extract match meta for detail
            meta_details = []
            for m in matches[:10]:
                meta = m.meta
                desc = meta.get("description", meta.get("info", m.rule))
                meta_details.append(f"{m.rule}: {desc}")

            return CorroborationResult(
                source=self.source,
                status=status,
                confidence=round(min(confidence, 1.0), 3),
                detail=f"YARA: {len(matches)} rules matched — {'; '.join(meta_details[:5])}",
                yara_rules_matched=rule_names,
                raw_response={
                    "matches": len(matches),
                    "rules": rule_names,
                    "namespaces": namespaces,
                    "tags": tags,
                },
            )

        except self._yara.TimeoutError:
            return self._unknown_result("YARA scan timed out")
        except self._yara.Error as exc:
            return self._unknown_result(f"YARA scan error: {exc}")
        except Exception as exc:
            logger.exception("YARA scan failed for %s", file_path)
            return self._unknown_result(f"YARA error: {exc}")

    @staticmethod
    def _write_base_rules(path: Path) -> None:
        """Write a baseline YARA ruleset covering common malware indicators."""
        rules = '''\
/*
    ZA Support — Base YARA Rules
    Covers: common packers, suspicious strings, macro payloads,
    cryptocurrency miners, web shells, reverse shells.
    Updated: 2026-03-03
*/

rule Suspicious_PowerShell_Download
{
    meta:
        description = "PowerShell download cradle patterns"
        severity = "high"
        mitre = "T1059.001"
    strings:
        $a1 = "IEX" ascii nocase
        $a2 = "Invoke-Expression" ascii nocase
        $a3 = "DownloadString" ascii nocase
        $a4 = "Net.WebClient" ascii nocase
        $a5 = "Invoke-WebRequest" ascii nocase
        $a6 = "-enc " ascii nocase
        $a7 = "FromBase64String" ascii nocase
    condition:
        2 of them
}

rule Suspicious_Macro_Payload
{
    meta:
        description = "Office macro with suspicious function calls"
        severity = "high"
        mitre = "T1204.002"
    strings:
        $auto = "Auto_Open" ascii nocase
        $doc = "Document_Open" ascii nocase
        $shell = "Shell(" ascii nocase
        $wscript = "WScript.Shell" ascii nocase
        $exec = "CreateObject" ascii nocase
        $powershell = "powershell" ascii nocase
    condition:
        ($auto or $doc) and 2 of ($shell, $wscript, $exec, $powershell)
}

rule CryptoMiner_Strings
{
    meta:
        description = "Cryptocurrency mining indicators"
        severity = "medium"
        mitre = "T1496"
    strings:
        $pool1 = "stratum+tcp://" ascii
        $pool2 = "stratum+ssl://" ascii
        $xmr = "monero" ascii nocase
        $wallet = /[48][0-9AB][1-9A-HJ-NP-Za-km-z]{93}/ ascii
        $miner1 = "xmrig" ascii nocase
        $miner2 = "cpuminer" ascii nocase
        $miner3 = "hashrate" ascii nocase
    condition:
        2 of them
}

rule WebShell_Indicators
{
    meta:
        description = "Common web shell patterns"
        severity = "critical"
        mitre = "T1505.003"
    strings:
        $php1 = "eval($_" ascii
        $php2 = "base64_decode($_" ascii
        $php3 = "system($_" ascii
        $php4 = "passthru(" ascii
        $php5 = "shell_exec(" ascii
        $asp1 = "eval(Request" ascii nocase
        $asp2 = "Execute(Request" ascii nocase
        $jsp1 = "Runtime.getRuntime().exec" ascii
    condition:
        any of them
}

rule ReverseShell_Pattern
{
    meta:
        description = "Reverse shell connection patterns"
        severity = "critical"
        mitre = "T1059"
    strings:
        $bash1 = "/bin/bash -i" ascii
        $bash2 = "/bin/sh -i" ascii
        $nc1 = "nc -e /bin" ascii
        $nc2 = "ncat -e /bin" ascii
        $py1 = "socket.socket" ascii
        $py2 = "subprocess.call" ascii
        $py3 = "pty.spawn" ascii
    condition:
        ($py1 and $py2 and $py3) or 2 of ($bash1, $bash2, $nc1, $nc2)
}

rule Suspicious_Encoded_Executable
{
    meta:
        description = "Base64-encoded PE/Mach-O header inside text file"
        severity = "high"
        mitre = "T1027"
    strings:
        $pe_b64 = "TVqQAAMAAAA" ascii    // MZ header base64
        $macho_b64 = "z0BAAAAAAA" ascii  // Mach-O magic base64
        $elf_b64 = "f0VMRg" ascii        // ELF header base64
    condition:
        any of them
}

rule macOS_Persistence_Suspicious
{
    meta:
        description = "Suspicious macOS persistence plist content"
        severity = "medium"
        mitre = "T1543.001"
    strings:
        $plist = "<!DOCTYPE plist" ascii
        $run = "RunAtLoad" ascii
        $prog = "ProgramArguments" ascii
        $hidden = "/tmp/" ascii
        $usr_hidden = "/var/tmp/" ascii
        $dot_dir = "/Users/" ascii
    condition:
        $plist and $run and $prog and ($hidden or $usr_hidden)
}
'''
        path.write_text(rules)
        logger.info("Base YARA rules written to %s", path)
