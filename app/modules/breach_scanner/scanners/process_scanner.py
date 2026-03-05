"""
Process Scanner — inspects running processes for indicators of compromise.

Checks:
  - Running processes with unsigned/ad-hoc signed binaries
  - Processes running from suspicious paths (/tmp, hidden dirs)
  - Known malware process names
  - Parent-child anomalies (e.g. Word spawning PowerShell)
  - Injected libraries (DYLD_INSERT_LIBRARIES, LD_PRELOAD)
  - Crypto mining indicators (high CPU + pool connections)
  - Remote access tools (RATs)
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import FindingCategory, FindingSeverity, OSPlatform, RawFinding

logger = logging.getLogger(__name__)

KNOWN_MALWARE_PROCESS_NAMES = {
    "xmrig", "cpuminer", "minerd", "minergate", "nicehash",  # Crypto miners
    "xcsset", "shlayer", "bundlore", "macma", "dazzlespy",   # macOS malware
    "cobaltstrike", "beacon", "mimikatz", "lazagne",          # Attack tools
    "meterpreter", "reverse_tcp", "bind_tcp",                 # Metasploit
    "netcat", "ncat", "socat",                                # Network tools (suspicious on endpoints)
}

# Legitimate parent -> child pairs (process trees that are expected)
LEGIT_PARENT_CHILD = {
    "launchd": {"*"},  # launchd can spawn anything
    "loginwindow": {"Finder", "Dock", "SystemUIServer"},
    "WindowServer": {"*"},
}

# Suspicious parent -> child relationships
SUSPICIOUS_SPAWNS = {
    # Office apps should not spawn shells or scripting engines
    "Microsoft Word": {"bash", "sh", "python", "python3", "osascript", "curl", "wget", "powershell"},
    "Microsoft Excel": {"bash", "sh", "python", "python3", "osascript", "curl", "wget", "powershell"},
    "Microsoft PowerPoint": {"bash", "sh", "python", "python3", "osascript", "curl", "wget"},
    "Preview": {"bash", "sh", "python", "python3", "curl", "wget"},
    "Safari": {"bash", "sh", "python", "python3", "osascript"},
    "Mail": {"bash", "sh", "python", "python3", "curl", "wget"},
    # Adobe products
    "AdobeReader": {"bash", "sh", "python", "python3", "curl", "wget", "powershell"},
}


class ProcessScanner:
    """
    Scans running processes for malicious or suspicious indicators.
    """

    name = "process_scanner"

    def __init__(
        self,
        os_platform: OSPlatform = OSPlatform.MACOS,
    ):
        self.os_platform = os_platform
        self.items_scanned = 0

    def scan(self) -> list[RawFinding]:
        """Run all process checks."""
        findings: list[RawFinding] = []

        processes = self._get_process_list()
        self.items_scanned = len(processes)

        for proc in processes:
            findings.extend(self._check_process(proc))

        findings.extend(self._check_parent_child_anomalies(processes))
        findings.extend(self._check_injected_libraries())

        return findings

    def _get_process_list(self) -> list[dict]:
        """Get list of running processes with metadata."""
        processes = []

        if self.os_platform in (OSPlatform.MACOS, OSPlatform.LINUX):
            try:
                result = subprocess.run(
                    ["ps", "aux", "-o", "pid,ppid,user,pcpu,pmem,command"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n")[1:]:
                        parts = line.split(None, 5)
                        if len(parts) >= 6:
                            processes.append({
                                "user": parts[0],
                                "pid": int(parts[1]) if parts[1].isdigit() else 0,
                                "ppid": 0,  # Will be populated separately
                                "cpu": float(parts[2]) if self._is_float(parts[2]) else 0.0,
                                "mem": float(parts[3]) if self._is_float(parts[3]) else 0.0,
                                "command": parts[5] if len(parts) > 5 else parts[-1],
                            })
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            # Get PPID separately for parent-child analysis
            try:
                result = subprocess.run(
                    ["ps", "-eo", "pid,ppid,comm"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    ppid_map = {}
                    name_map = {}
                    for line in result.stdout.strip().split("\n")[1:]:
                        parts = line.split(None, 2)
                        if len(parts) >= 3:
                            pid = int(parts[0]) if parts[0].isdigit() else 0
                            ppid = int(parts[1]) if parts[1].isdigit() else 0
                            ppid_map[pid] = ppid
                            name_map[pid] = parts[2].strip()

                    for proc in processes:
                        proc["ppid"] = ppid_map.get(proc["pid"], 0)
                        proc["name"] = name_map.get(proc["pid"], Path(proc["command"].split()[0]).name)
                        proc["parent_name"] = name_map.get(proc["ppid"], "")

            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return processes

    def _check_process(self, proc: dict) -> list[RawFinding]:
        """Check a single process for suspicious indicators."""
        findings: list[RawFinding] = []
        command = proc.get("command", "")
        name = proc.get("name", Path(command.split()[0]).name if command else "unknown")
        pid = proc.get("pid", 0)
        name_lower = name.lower()

        # --- Known malware process names ---
        for malware_name in KNOWN_MALWARE_PROCESS_NAMES:
            if malware_name in name_lower or malware_name in command.lower():
                findings.append(RawFinding(
                    category=FindingCategory.MALWARE,
                    severity=FindingSeverity.CRITICAL,
                    title=f"Known malicious process: {name} (PID {pid})",
                    description=(
                        f"Running process '{name}' (PID {pid}) matches known malware "
                        f"or attack tool '{malware_name}'. Command: {command[:200]}"
                    ),
                    process_name=name,
                    process_pid=pid,
                    scanner_name=self.name,
                    mitre_technique="T1059",
                    mitre_tactic="Execution",
                    raw_evidence={"full_command": command[:500], "user": proc.get("user")},
                    recommended_action="CRITICAL: Kill process immediately. Investigate origin.",
                ))
                break

        # --- Process running from suspicious path ---
        exe_path = command.split()[0] if command else ""
        suspicious_paths = ["/tmp/", "/var/tmp/", "/dev/shm/", "/Users/Shared/",
                           "/.hidden", "/Library/Caches/"]
        for sp in suspicious_paths:
            if sp in exe_path:
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_PROCESS,
                    severity=FindingSeverity.HIGH,
                    title=f"Process from suspicious path: {name} (PID {pid})",
                    description=(
                        f"Process '{name}' (PID {pid}) is running from '{exe_path}' "
                        f"which is in a suspicious location. Legitimate software does "
                        f"not typically execute from temporary or hidden directories."
                    ),
                    process_name=name,
                    process_pid=pid,
                    file_path=exe_path,
                    scanner_name=self.name,
                    mitre_technique="T1036.005",
                    mitre_tactic="Defense Evasion",
                    recommended_action="Investigate process origin. Kill if unrecognised.",
                ))
                break

        # --- Crypto mining indicators ---
        cpu = proc.get("cpu", 0.0)
        if cpu > 80.0 and any(kw in command.lower()
                              for kw in ["pool", "stratum", "mining", "hashrate", "xmr", "monero"]):
            findings.append(RawFinding(
                category=FindingCategory.CRYPTO_MINER,
                severity=FindingSeverity.HIGH,
                title=f"Crypto mining process: {name} (PID {pid})",
                description=(
                    f"Process '{name}' (PID {pid}) is using {cpu}% CPU and contains "
                    f"mining-related keywords. This machine may be running a "
                    f"cryptocurrency miner, either installed maliciously or as adware."
                ),
                process_name=name,
                process_pid=pid,
                scanner_name=self.name,
                mitre_technique="T1496",
                mitre_tactic="Impact",
                raw_evidence={"cpu_percent": cpu, "command": command[:500]},
                recommended_action="Kill process. Check for persistence mechanism.",
            ))
        elif cpu > 90.0:
            # Very high CPU without mining keywords — still suspicious
            findings.append(RawFinding(
                category=FindingCategory.SUSPICIOUS_PROCESS,
                severity=FindingSeverity.MEDIUM,
                title=f"High CPU process: {name} (PID {pid}) at {cpu}%",
                description=(
                    f"Process '{name}' (PID {pid}) is consuming {cpu}% CPU. "
                    f"This may indicate crypto mining, runaway malware, or resource abuse."
                ),
                process_name=name,
                process_pid=pid,
                scanner_name=self.name,
                raw_evidence={"cpu_percent": cpu, "command": command[:300]},
                recommended_action="Monitor process. Investigate if persistent.",
            ))

        # --- Check code signature on macOS ---
        if self.os_platform == OSPlatform.MACOS and exe_path and exe_path.startswith("/"):
            sig_finding = self._check_process_signature(name, pid, exe_path)
            if sig_finding:
                findings.append(sig_finding)

        return findings

    def _check_process_signature(self, name: str, pid: int, exe_path: str) -> Optional[RawFinding]:
        """Verify code signature of a running process binary (macOS)."""
        try:
            result = subprocess.run(
                ["codesign", "--verify", "--deep", exe_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                error = result.stderr.lower()
                if "not signed" in error or "invalid" in error:
                    return RawFinding(
                        category=FindingCategory.SUSPICIOUS_PROCESS,
                        severity=FindingSeverity.MEDIUM,
                        title=f"Unsigned running process: {name} (PID {pid})",
                        description=(
                            f"Process '{name}' (PID {pid}) binary at '{exe_path}' "
                            f"has no valid code signature. This binary may have been "
                            f"modified or was never properly signed."
                        ),
                        process_name=name,
                        process_pid=pid,
                        file_path=exe_path,
                        scanner_name=self.name,
                        mitre_technique="T1553.002",
                        mitre_tactic="Defense Evasion",
                        recommended_action="Verify binary origin. Re-install from trusted source.",
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def _check_parent_child_anomalies(self, processes: list[dict]) -> list[RawFinding]:
        """Detect suspicious process parent-child relationships."""
        findings: list[RawFinding] = []

        for proc in processes:
            parent_name = proc.get("parent_name", "")
            child_name = proc.get("name", "")

            for parent_pattern, child_set in SUSPICIOUS_SPAWNS.items():
                if parent_pattern.lower() in parent_name.lower():
                    if child_name.lower() in {c.lower() for c in child_set}:
                        findings.append(RawFinding(
                            category=FindingCategory.SUSPICIOUS_PROCESS,
                            severity=FindingSeverity.HIGH,
                            title=(
                                f"Suspicious process chain: {parent_name} → {child_name}"
                            ),
                            description=(
                                f"'{parent_name}' spawned '{child_name}' (PID {proc['pid']}). "
                                f"Office applications, PDF readers, and browsers should not "
                                f"spawn shells or scripting engines. This is a strong indicator "
                                f"of a macro payload or exploit execution."
                            ),
                            process_name=child_name,
                            process_pid=proc["pid"],
                            scanner_name=self.name,
                            mitre_technique="T1204.002",
                            mitre_tactic="Execution",
                            raw_evidence={
                                "parent": parent_name,
                                "child": child_name,
                                "child_pid": proc["pid"],
                                "child_command": proc.get("command", "")[:300],
                            },
                            recommended_action=(
                                "CRITICAL: This indicates active exploitation. Kill the "
                                "child process, save the parent document for analysis, "
                                "and run a full scan."
                            ),
                        ))

        return findings

    def _check_injected_libraries(self) -> list[RawFinding]:
        """Check for library injection environment variables."""
        findings: list[RawFinding] = []

        injection_vars = {
            "DYLD_INSERT_LIBRARIES": ("T1574.006", "macOS dylib injection"),
            "LD_PRELOAD": ("T1574.006", "Linux shared library injection"),
            "DYLD_FRAMEWORK_PATH": ("T1574.006", "macOS framework hijack"),
        }

        for var, (technique, desc) in injection_vars.items():
            value = os.environ.get(var)
            if value:
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_PROCESS,
                    severity=FindingSeverity.HIGH,
                    title=f"Library injection detected: {var}",
                    description=(
                        f"Environment variable '{var}' is set to '{value}'. "
                        f"This is a {desc} technique. Malware uses this to inject "
                        f"code into legitimate processes."
                    ),
                    scanner_name=self.name,
                    mitre_technique=technique,
                    mitre_tactic="Persistence",
                    raw_evidence={var: value},
                    recommended_action="Investigate source. Unset variable and restart affected processes.",
                ))

        return findings

    @staticmethod
    def _is_float(s: str) -> bool:
        try:
            float(s)
            return True
        except (ValueError, TypeError):
            return False
