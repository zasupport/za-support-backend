"""
Persistence Scanner — detects mechanisms malware uses to survive reboots.

Checks:
  - macOS: LaunchAgents, LaunchDaemons, Login Items, profiles, cron
  - Windows: Startup folders, Run/RunOnce registry, scheduled tasks, services
  - Linux: systemd services, cron, init.d, .bashrc/.profile modifications
  - All: Browser homepage/search hijacks, unauthorized SSH keys
"""

from __future__ import annotations

import json
import logging
import os
import plistlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import FindingCategory, FindingSeverity, OSPlatform, RawFinding

logger = logging.getLogger(__name__)

# Known legitimate launch agent/daemon prefixes (macOS)
KNOWN_LEGIT_PREFIXES = {
    "com.apple.", "com.microsoft.", "com.google.", "com.adobe.",
    "com.dropbox.", "com.spotify.", "com.docker.", "com.1password.",
    "com.objective-see.", "com.malwarebytes.", "org.mozilla.",
    "com.ui.", "com.ubnt.",  # UniFi
}


class PersistenceScanner:
    """
    Detects persistence mechanisms installed on the endpoint.
    Malware that persists is malware that is actively dangerous.
    """

    name = "persistence_scanner"

    def __init__(
        self,
        os_platform: OSPlatform = OSPlatform.MACOS,
    ):
        self.os_platform = os_platform
        self.items_scanned = 0

    def scan(self) -> list[RawFinding]:
        """Run all persistence checks for the platform."""
        findings: list[RawFinding] = []

        if self.os_platform == OSPlatform.MACOS:
            findings.extend(self._scan_launch_agents())
            findings.extend(self._scan_launch_daemons())
            findings.extend(self._scan_login_items())
            findings.extend(self._scan_cron_jobs())
            findings.extend(self._scan_profiles())
            findings.extend(self._scan_browser_hijacks())
            findings.extend(self._scan_ssh_keys())
        elif self.os_platform == OSPlatform.WINDOWS:
            findings.extend(self._scan_startup_folders())
            findings.extend(self._scan_scheduled_tasks())
            findings.extend(self._scan_browser_hijacks())
            findings.extend(self._scan_ssh_keys())
        elif self.os_platform == OSPlatform.LINUX:
            findings.extend(self._scan_systemd_services())
            findings.extend(self._scan_cron_jobs())
            findings.extend(self._scan_profile_scripts())
            findings.extend(self._scan_ssh_keys())

        return findings

    # -----------------------------------------------------------------------
    # macOS-specific checks
    # -----------------------------------------------------------------------

    def _scan_launch_agents(self) -> list[RawFinding]:
        """Check LaunchAgents for suspicious entries."""
        findings: list[RawFinding] = []
        agent_dirs = [
            Path.home() / "Library/LaunchAgents",
            Path("/Library/LaunchAgents"),
        ]

        for agent_dir in agent_dirs:
            if not agent_dir.exists():
                continue

            for plist_file in agent_dir.glob("*.plist"):
                self.items_scanned += 1
                findings.extend(self._check_plist(plist_file, "LaunchAgent"))

        return findings

    def _scan_launch_daemons(self) -> list[RawFinding]:
        """Check LaunchDaemons for suspicious entries."""
        findings: list[RawFinding] = []
        daemon_dirs = [
            Path("/Library/LaunchDaemons"),
        ]

        for daemon_dir in daemon_dirs:
            if not daemon_dir.exists():
                continue

            for plist_file in daemon_dir.glob("*.plist"):
                self.items_scanned += 1
                findings.extend(self._check_plist(plist_file, "LaunchDaemon"))

        return findings

    def _check_plist(self, plist_path: Path, plist_type: str) -> list[RawFinding]:
        """Analyse a launchd plist for suspicious characteristics."""
        findings: list[RawFinding] = []

        try:
            with open(plist_path, "rb") as f:
                plist = plistlib.load(f)
        except Exception:
            # Binary plist or corrupted
            try:
                result = subprocess.run(
                    ["plutil", "-convert", "json", "-o", "-", str(plist_path)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    plist = json.loads(result.stdout)
                else:
                    return findings
            except Exception:
                return findings

        label = plist.get("Label", plist_path.stem)
        program = plist.get("Program", "")
        program_args = plist.get("ProgramArguments", [])
        run_at_load = plist.get("RunAtLoad", False)
        keep_alive = plist.get("KeepAlive", False)

        # Get the executable path
        exe_path = program or (program_args[0] if program_args else "")

        # Check if label matches known legitimate patterns
        is_known = any(label.startswith(prefix) for prefix in KNOWN_LEGIT_PREFIXES)

        if is_known:
            return findings  # Skip known legitimate entries

        # --- Check 1: Unknown LaunchAgent/Daemon running at load ---
        if run_at_load:
            findings.append(RawFinding(
                category=FindingCategory.PERSISTENCE,
                severity=FindingSeverity.MEDIUM,
                title=f"Unknown {plist_type}: {label}",
                description=(
                    f"{plist_type} '{label}' is configured to run at load. "
                    f"Executable: {exe_path}. This is not from a recognised vendor. "
                    f"Malware commonly installs LaunchAgents to maintain persistence."
                ),
                file_path=str(plist_path),
                process_name=exe_path,
                scanner_name=self.name,
                mitre_technique="T1543.001" if "Daemon" in plist_type else "T1543.001",
                mitre_tactic="Persistence",
                raw_evidence={
                    "label": label,
                    "program": exe_path,
                    "run_at_load": run_at_load,
                    "keep_alive": keep_alive,
                },
                recommended_action=(
                    f"Investigate {plist_type} '{label}'. Check if executable "
                    f"at '{exe_path}' is legitimate. Remove plist if unrecognised."
                ),
            ))

        # --- Check 2: Executable in suspicious location ---
        suspicious_paths = ["/tmp/", "/var/tmp/", "/Users/Shared/", ".hidden", "/dev/"]
        if any(sp in str(exe_path) for sp in suspicious_paths):
            findings.append(RawFinding(
                category=FindingCategory.PERSISTENCE,
                severity=FindingSeverity.HIGH,
                title=f"{plist_type} running from suspicious path: {label}",
                description=(
                    f"{plist_type} '{label}' executes '{exe_path}' which is in a "
                    f"suspicious location. Legitimate software does not run from "
                    f"temp directories or hidden folders."
                ),
                file_path=str(plist_path),
                process_name=exe_path,
                scanner_name=self.name,
                mitre_technique="T1543.001",
                mitre_tactic="Persistence",
                recommended_action="HIGH PRIORITY: Investigate immediately. Likely malicious persistence.",
            ))

        # --- Check 3: Script-based persistence (bash, python, osascript) ---
        script_interpreters = {"bash", "sh", "python", "python3", "osascript", "perl", "ruby"}
        if program_args:
            interpreter = Path(program_args[0]).name.lower()
            if interpreter in script_interpreters and len(program_args) > 1:
                findings.append(RawFinding(
                    category=FindingCategory.PERSISTENCE,
                    severity=FindingSeverity.HIGH,
                    title=f"Script-based {plist_type}: {label}",
                    description=(
                        f"{plist_type} '{label}' runs a script via {interpreter}: "
                        f"{' '.join(program_args[:5])}. Script-based persistence is a "
                        f"common malware technique as scripts are easy to modify and "
                        f"difficult to detect."
                    ),
                    file_path=str(plist_path),
                    process_name=interpreter,
                    scanner_name=self.name,
                    mitre_technique="T1059",
                    mitre_tactic="Execution",
                    raw_evidence={"program_arguments": program_args[:10]},
                    recommended_action="Review script contents. Remove if not intentionally installed.",
                ))

        return findings

    def _scan_login_items(self) -> list[RawFinding]:
        """Check macOS Login Items."""
        findings: list[RawFinding] = []

        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get the name of every login item'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                items = [item.strip() for item in result.stdout.strip().split(",")]
                for item in items:
                    self.items_scanned += 1
                    item_lower = item.lower()
                    # Flag if item name doesn't match known patterns
                    if not any(item_lower.startswith(k.replace("com.", ""))
                               for k in KNOWN_LEGIT_PREFIXES):
                        findings.append(RawFinding(
                            category=FindingCategory.PERSISTENCE,
                            severity=FindingSeverity.LOW,
                            title=f"Login Item: {item}",
                            description=(
                                f"'{item}' is registered as a Login Item and will "
                                f"launch automatically when the user logs in."
                            ),
                            app_name=item,
                            scanner_name=self.name,
                            mitre_technique="T1547.015",
                            mitre_tactic="Persistence",
                            recommended_action="Verify this is an expected login item.",
                        ))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return findings

    def _scan_cron_jobs(self) -> list[RawFinding]:
        """Check crontab for the current user and system."""
        findings: list[RawFinding] = []

        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self.items_scanned += 1
                        findings.append(RawFinding(
                            category=FindingCategory.PERSISTENCE,
                            severity=FindingSeverity.MEDIUM,
                            title=f"Cron job detected",
                            description=(
                                f"Active cron job found: {line[:200]}. Cron jobs execute "
                                f"on a schedule and can be used for persistent malware execution."
                            ),
                            scanner_name=self.name,
                            mitre_technique="T1053.003",
                            mitre_tactic="Persistence",
                            raw_evidence={"cron_entry": line[:500]},
                            recommended_action="Verify cron job is intentional and inspect the command.",
                        ))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return findings

    def _scan_profiles(self) -> list[RawFinding]:
        """Check for configuration profiles (macOS MDM/management)."""
        findings: list[RawFinding] = []

        try:
            result = subprocess.run(
                ["profiles", "list", "-output", "stdout-xml"],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout:
                try:
                    profiles = plistlib.loads(result.stdout)
                    for profile in profiles.get("_computerlevel", []):
                        self.items_scanned += 1
                        name = profile.get("ProfileDisplayName", "Unknown")
                        org = profile.get("ProfileOrganization", "Unknown")
                        findings.append(RawFinding(
                            category=FindingCategory.PERSISTENCE,
                            severity=FindingSeverity.LOW,
                            title=f"Configuration profile: {name}",
                            description=(
                                f"Configuration profile '{name}' from '{org}' is installed. "
                                f"Profiles can modify system settings, install certificates, "
                                f"and configure network proxies."
                            ),
                            scanner_name=self.name,
                            mitre_technique="T1176",
                            mitre_tactic="Persistence",
                            raw_evidence={"profile_name": name, "organization": org},
                            recommended_action="Verify profile is from a trusted source.",
                        ))
                except Exception:
                    pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return findings

    def _scan_browser_hijacks(self) -> list[RawFinding]:
        """Check for browser homepage/search engine hijacks."""
        findings: list[RawFinding] = []

        # Chrome preferences
        chrome_prefs = {
            OSPlatform.MACOS: Path.home() / "Library/Application Support/Google/Chrome/Default/Preferences",
            OSPlatform.WINDOWS: Path.home() / "AppData/Local/Google/Chrome/User Data/Default/Preferences",
            OSPlatform.LINUX: Path.home() / ".config/google-chrome/Default/Preferences",
        }.get(self.os_platform)

        if chrome_prefs and chrome_prefs.exists():
            try:
                with open(chrome_prefs) as f:
                    prefs = json.load(f)

                homepage = prefs.get("homepage", "")
                search_url = (prefs.get("default_search_provider_data", {})
                              .get("template_url", ""))

                legitimate_search = {"google.com", "bing.com", "duckduckgo.com", "yahoo.com"}

                if homepage and not any(s in homepage for s in legitimate_search | {"chrome://"}):
                    self.items_scanned += 1
                    findings.append(RawFinding(
                        category=FindingCategory.BROWSER_EXTENSION,
                        severity=FindingSeverity.MEDIUM,
                        title=f"Non-standard browser homepage: {homepage[:100]}",
                        description=(
                            f"Chrome homepage is set to '{homepage}'. Browser hijacking "
                            f"malware commonly changes the homepage to redirect traffic "
                            f"through malicious search engines."
                        ),
                        file_path=str(chrome_prefs),
                        network_domain=homepage[:200],
                        scanner_name=self.name,
                        mitre_technique="T1185",
                        mitre_tactic="Collection",
                        recommended_action="Reset homepage to a known search engine.",
                    ))

            except (json.JSONDecodeError, OSError):
                pass

        return findings

    def _scan_ssh_keys(self) -> list[RawFinding]:
        """Check for unauthorized SSH keys."""
        findings: list[RawFinding] = []
        ssh_dir = Path.home() / ".ssh"

        if not ssh_dir.exists():
            return findings

        auth_keys = ssh_dir / "authorized_keys"
        if auth_keys.exists():
            try:
                content = auth_keys.read_text()
                keys = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]

                for key in keys:
                    self.items_scanned += 1
                    parts = key.split()
                    comment = parts[-1] if len(parts) >= 3 else "no comment"

                    findings.append(RawFinding(
                        category=FindingCategory.REMOTE_ACCESS,
                        severity=FindingSeverity.MEDIUM,
                        title=f"SSH authorized key: {comment[:80]}",
                        description=(
                            f"SSH authorized key found for '{comment}'. This key allows "
                            f"remote SSH access to this machine without a password. "
                            f"Attackers may add SSH keys for persistent remote access."
                        ),
                        file_path=str(auth_keys),
                        scanner_name=self.name,
                        mitre_technique="T1098.004",
                        mitre_tactic="Persistence",
                        raw_evidence={"key_comment": comment, "key_type": parts[0] if parts else ""},
                        recommended_action="Verify all authorized keys are intentional.",
                    ))

            except (OSError, PermissionError):
                pass

        return findings

    # -----------------------------------------------------------------------
    # Windows-specific checks
    # -----------------------------------------------------------------------

    def _scan_startup_folders(self) -> list[RawFinding]:
        """Check Windows startup folders."""
        findings: list[RawFinding] = []
        startup_dirs = [
            Path.home() / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
            Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"),
        ]

        for sd in startup_dirs:
            if not sd.exists():
                continue
            for item in sd.iterdir():
                if item.is_file():
                    self.items_scanned += 1
                    findings.append(RawFinding(
                        category=FindingCategory.PERSISTENCE,
                        severity=FindingSeverity.MEDIUM,
                        title=f"Startup item: {item.name}",
                        description=f"Item '{item.name}' in startup folder {sd}.",
                        file_path=str(item),
                        scanner_name=self.name,
                        mitre_technique="T1547.001",
                        mitre_tactic="Persistence",
                        recommended_action="Verify startup item is legitimate.",
                    ))

        return findings

    def _scan_scheduled_tasks(self) -> list[RawFinding]:
        """Check Windows scheduled tasks."""
        findings: list[RawFinding] = []
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/fo", "csv", "/v"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n")[1:]:
                    if line.strip():
                        self.items_scanned += 1
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return findings

    # -----------------------------------------------------------------------
    # Linux-specific checks
    # -----------------------------------------------------------------------

    def _scan_systemd_services(self) -> list[RawFinding]:
        """Check for user-created systemd services."""
        findings: list[RawFinding] = []
        service_dirs = [
            Path.home() / ".config/systemd/user",
            Path("/etc/systemd/system"),
        ]

        for sd in service_dirs:
            if not sd.exists():
                continue
            for service_file in sd.glob("*.service"):
                self.items_scanned += 1
                try:
                    content = service_file.read_text()
                    if "ExecStart=" in content:
                        exec_line = [l for l in content.split("\n") if "ExecStart=" in l]
                        findings.append(RawFinding(
                            category=FindingCategory.PERSISTENCE,
                            severity=FindingSeverity.LOW,
                            title=f"Systemd service: {service_file.name}",
                            description=(
                                f"Systemd service '{service_file.name}' found. "
                                f"Command: {exec_line[0] if exec_line else 'unknown'}"
                            ),
                            file_path=str(service_file),
                            scanner_name=self.name,
                            mitre_technique="T1543.002",
                            mitre_tactic="Persistence",
                            recommended_action="Verify service is intentional.",
                        ))
                except (OSError, PermissionError):
                    pass

        return findings

    def _scan_profile_scripts(self) -> list[RawFinding]:
        """Check .bashrc, .profile, .zshrc for suspicious additions."""
        findings: list[RawFinding] = []
        profile_files = [
            Path.home() / ".bashrc",
            Path.home() / ".bash_profile",
            Path.home() / ".profile",
            Path.home() / ".zshrc",
        ]

        suspicious_patterns = [
            "curl ", "wget ", "base64", "eval ", "exec(",
            "/dev/tcp/", "nc ", "ncat ", "python -c",
            "bash -i", "reverse", "bind",
        ]

        for pf in profile_files:
            if not pf.exists():
                continue
            try:
                content = pf.read_text()
                for pattern in suspicious_patterns:
                    if pattern in content.lower():
                        self.items_scanned += 1
                        findings.append(RawFinding(
                            category=FindingCategory.PERSISTENCE,
                            severity=FindingSeverity.HIGH,
                            title=f"Suspicious command in {pf.name}",
                            description=(
                                f"Shell profile '{pf.name}' contains suspicious pattern "
                                f"'{pattern}'. This could indicate a reverse shell, "
                                f"data exfiltration, or malware persistence."
                            ),
                            file_path=str(pf),
                            scanner_name=self.name,
                            mitre_technique="T1546.004",
                            mitre_tactic="Persistence",
                            recommended_action="Review profile file contents carefully.",
                        ))
                        break
            except (OSError, PermissionError):
                pass

        return findings
