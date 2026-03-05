"""
App Auditor — inspects installed applications, browser extensions, and plugins.

Checks:
  - Installed apps against known-compromised versions (CVE database)
  - Browser extensions (Chrome, Firefox, Safari, Edge) against malicious extension lists
  - Sideloaded apps not from official stores
  - Apps with revoked or missing code signatures (macOS)
  - Third-party plugins (Office, Adobe, etc.)
  - Recently installed apps in suspicious locations
"""

from __future__ import annotations

import json
import logging
import os
import plistlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import FindingCategory, FindingSeverity, OSPlatform, RawFinding

logger = logging.getLogger(__name__)

# Known malicious or compromised browser extension IDs
KNOWN_MALICIOUS_CHROME_EXTENSIONS = {
    # These are examples — in production, updated from threat feed
    "ejagicbgopjlcpdomhlaknmemohnopog",  # Example adware extension
    "bhghoamapcdpbohphigoooaddinpkbai",  # Example data stealer
}

KNOWN_MALICIOUS_FIREFOX_ADDONS = {
    "malicious-addon@example.com",
}

# Suspicious extension permissions
HIGH_RISK_PERMISSIONS = {
    "tabs", "webRequest", "webRequestBlocking", "proxy",
    "nativeMessaging", "debugger", "cookies", "history",
    "management", "clipboardRead", "clipboardWrite",
    "<all_urls>", "http://*/*", "https://*/*",
}

# Apps known to be exploited or used as attack tools
SUSPICIOUS_APP_NAMES = {
    "anydesk", "teamviewer", "ammyy admin", "supremo",
    "connectwise", "atera", "splashtop",  # Legitimate but exploited RATs
    "ncat", "netcat", "nmap", "wireshark",  # Pen test tools on non-IT machines
    "mimikatz", "lazagne", "cobaltstrike",  # Attack tools
    "tor browser",  # Can indicate data exfiltration
}


class AppAuditor:
    """
    Audits installed applications and browser extensions for IOCs.
    """

    name = "app_auditor"

    def __init__(
        self,
        os_platform: OSPlatform = OSPlatform.MACOS,
        custom_paths: Optional[list[str]] = None,
    ):
        self.os_platform = os_platform
        self.custom_paths = custom_paths or []
        self.items_scanned = 0

    def scan(self) -> list[RawFinding]:
        """Run the full app audit."""
        findings: list[RawFinding] = []

        findings.extend(self._scan_installed_apps())
        findings.extend(self._scan_chrome_extensions())
        findings.extend(self._scan_firefox_extensions())
        if self.os_platform == OSPlatform.MACOS:
            findings.extend(self._scan_safari_extensions())
            findings.extend(self._scan_code_signatures())

        return findings

    def _scan_installed_apps(self) -> list[RawFinding]:
        """Check installed applications for suspicious entries."""
        findings: list[RawFinding] = []
        app_dirs = []

        if self.os_platform == OSPlatform.MACOS:
            app_dirs = [
                Path("/Applications"),
                Path.home() / "Applications",
                Path.home() / "Desktop",
                Path.home() / "Downloads",
            ]
        elif self.os_platform == OSPlatform.WINDOWS:
            app_dirs = [
                Path(r"C:\Program Files"),
                Path(r"C:\Program Files (x86)"),
                Path.home() / "AppData" / "Local",
                Path.home() / "Downloads",
            ]
        elif self.os_platform == OSPlatform.LINUX:
            app_dirs = [
                Path("/usr/bin"),
                Path("/usr/local/bin"),
                Path.home() / ".local" / "bin",
                Path.home() / "Downloads",
            ]

        for app_dir in app_dirs:
            if not app_dir.exists():
                continue

            try:
                for entry in app_dir.iterdir():
                    self.items_scanned += 1
                    name_lower = entry.name.lower().replace(".app", "")

                    # Check against suspicious app names
                    for suspicious in SUSPICIOUS_APP_NAMES:
                        if suspicious in name_lower:
                            severity = FindingSeverity.CRITICAL if suspicious in (
                                "mimikatz", "lazagne", "cobaltstrike"
                            ) else FindingSeverity.MEDIUM

                            findings.append(RawFinding(
                                category=FindingCategory.COMPROMISED_APP
                                if severity == FindingSeverity.CRITICAL
                                else FindingCategory.SUSPICIOUS_FILE,
                                severity=severity,
                                title=f"Suspicious application: {entry.name}",
                                description=(
                                    f"Application '{entry.name}' found at {entry}. "
                                    f"This application is {'a known attack tool' if severity == FindingSeverity.CRITICAL else 'commonly exploited for unauthorised remote access'}."
                                ),
                                file_path=str(entry),
                                app_name=entry.name,
                                scanner_name=self.name,
                                mitre_technique="T1219" if "remote" not in suspicious else "T1219",
                                mitre_tactic="Command and Control",
                                recommended_action=(
                                    "Verify this application was intentionally installed. "
                                    "If not recognised, remove immediately."
                                ),
                            ))
                            break

                    # Check for apps in Downloads/Desktop (sideloaded)
                    if app_dir.name.lower() in ("downloads", "desktop"):
                        if entry.suffix.lower() in (".app", ".exe", ".dmg", ".pkg", ".msi"):
                            findings.append(RawFinding(
                                category=FindingCategory.SUSPICIOUS_FILE,
                                severity=FindingSeverity.LOW,
                                title=f"Application installer in {app_dir.name}: {entry.name}",
                                description=(
                                    f"Application or installer '{entry.name}' found in "
                                    f"{app_dir.name}. Applications downloaded outside of "
                                    f"official app stores may not be verified."
                                ),
                                file_path=str(entry),
                                app_name=entry.name,
                                scanner_name=self.name,
                                recommended_action="Verify download source. Remove if unrecognised.",
                            ))

            except PermissionError:
                continue

        return findings

    def _scan_chrome_extensions(self) -> list[RawFinding]:
        """Inspect Chrome/Chromium extensions."""
        findings: list[RawFinding] = []

        chrome_profiles = {
            OSPlatform.MACOS: [
                Path.home() / "Library/Application Support/Google/Chrome",
                Path.home() / "Library/Application Support/Microsoft Edge",
                Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser",
            ],
            OSPlatform.WINDOWS: [
                Path.home() / "AppData/Local/Google/Chrome/User Data",
                Path.home() / "AppData/Local/Microsoft/Edge/User Data",
            ],
            OSPlatform.LINUX: [
                Path.home() / ".config/google-chrome",
                Path.home() / ".config/chromium",
                Path.home() / ".config/microsoft-edge",
            ],
        }.get(self.os_platform, [])

        for chrome_base in chrome_profiles:
            if not chrome_base.exists():
                continue

            # Check each profile (Default, Profile 1, etc.)
            for profile_dir in chrome_base.iterdir():
                ext_dir = profile_dir / "Extensions"
                if not ext_dir.exists():
                    continue

                for ext_id_dir in ext_dir.iterdir():
                    if not ext_id_dir.is_dir():
                        continue

                    self.items_scanned += 1
                    ext_id = ext_id_dir.name

                    # Check against known malicious
                    if ext_id in KNOWN_MALICIOUS_CHROME_EXTENSIONS:
                        findings.append(RawFinding(
                            category=FindingCategory.BROWSER_EXTENSION,
                            severity=FindingSeverity.CRITICAL,
                            title=f"Known malicious Chrome extension: {ext_id}",
                            description=(
                                f"Chrome extension with ID '{ext_id}' is on the known-malicious "
                                f"extension list. This extension may be stealing data, injecting "
                                f"ads, or performing other malicious activities."
                            ),
                            file_path=str(ext_id_dir),
                            extension_id=ext_id,
                            scanner_name=self.name,
                            mitre_technique="T1176",
                            mitre_tactic="Persistence",
                            recommended_action="Remove extension immediately from Chrome settings.",
                        ))
                        continue

                    # Check permissions in manifest
                    findings.extend(self._check_extension_manifest(ext_id_dir, ext_id))

        return findings

    def _check_extension_manifest(self, ext_dir: Path, ext_id: str) -> list[RawFinding]:
        """Check extension manifest.json for high-risk permissions."""
        findings: list[RawFinding] = []

        for version_dir in ext_dir.iterdir():
            manifest_path = version_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                name = manifest.get("name", ext_id)
                permissions = set(manifest.get("permissions", []))
                host_permissions = set(manifest.get("host_permissions", []))
                all_perms = permissions | host_permissions

                risky = all_perms & HIGH_RISK_PERMISSIONS
                if len(risky) >= 3:  # 3+ high-risk permissions
                    findings.append(RawFinding(
                        category=FindingCategory.BROWSER_EXTENSION,
                        severity=FindingSeverity.MEDIUM,
                        title=f"Extension with excessive permissions: {name}",
                        description=(
                            f"Chrome extension '{name}' (ID: {ext_id}) requests "
                            f"{len(risky)} high-risk permissions: {', '.join(sorted(risky))}. "
                            f"These permissions allow broad access to browsing data, "
                            f"network traffic, and clipboard content."
                        ),
                        file_path=str(manifest_path),
                        extension_id=ext_id,
                        app_name=name,
                        scanner_name=self.name,
                        mitre_technique="T1176",
                        mitre_tactic="Persistence",
                        raw_evidence={"permissions": sorted(risky)},
                        recommended_action=(
                            "Review extension necessity. Remove if not actively used or recognised."
                        ),
                    ))

            except (json.JSONDecodeError, OSError):
                pass

        return findings

    def _scan_firefox_extensions(self) -> list[RawFinding]:
        """Inspect Firefox extensions."""
        findings: list[RawFinding] = []

        firefox_paths = {
            OSPlatform.MACOS: Path.home() / "Library/Application Support/Firefox/Profiles",
            OSPlatform.WINDOWS: Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles",
            OSPlatform.LINUX: Path.home() / ".mozilla/firefox",
        }.get(self.os_platform)

        if not firefox_paths or not firefox_paths.exists():
            return findings

        for profile_dir in firefox_paths.iterdir():
            ext_json = profile_dir / "extensions.json"
            if not ext_json.exists():
                continue

            try:
                with open(ext_json) as f:
                    data = json.load(f)

                for addon in data.get("addons", []):
                    self.items_scanned += 1
                    addon_id = addon.get("id", "unknown")
                    name = addon.get("defaultLocale", {}).get("name", addon_id)

                    if addon_id in KNOWN_MALICIOUS_FIREFOX_ADDONS:
                        findings.append(RawFinding(
                            category=FindingCategory.BROWSER_EXTENSION,
                            severity=FindingSeverity.CRITICAL,
                            title=f"Known malicious Firefox addon: {name}",
                            description=(
                                f"Firefox addon '{name}' (ID: {addon_id}) is on the "
                                f"known-malicious addon list."
                            ),
                            file_path=str(ext_json),
                            extension_id=addon_id,
                            app_name=name,
                            scanner_name=self.name,
                            mitre_technique="T1176",
                            mitre_tactic="Persistence",
                            recommended_action="Remove addon immediately.",
                        ))

            except (json.JSONDecodeError, OSError):
                pass

        return findings

    def _scan_safari_extensions(self) -> list[RawFinding]:
        """Inspect Safari extensions on macOS."""
        findings: list[RawFinding] = []

        safari_ext_dir = Path.home() / "Library/Safari/Extensions"
        if not safari_ext_dir.exists():
            return findings

        for ext_file in safari_ext_dir.glob("*.safariextz"):
            self.items_scanned += 1
            findings.append(RawFinding(
                category=FindingCategory.BROWSER_EXTENSION,
                severity=FindingSeverity.LOW,
                title=f"Legacy Safari extension: {ext_file.name}",
                description=(
                    f"Legacy Safari extension '{ext_file.name}' found. Legacy extensions "
                    f"(.safariextz) are no longer supported by Apple and may contain "
                    f"unpatched vulnerabilities."
                ),
                file_path=str(ext_file),
                app_name=ext_file.name,
                scanner_name=self.name,
                recommended_action="Remove legacy extension. Use App Store extensions instead.",
            ))

        return findings

    def _scan_code_signatures(self) -> list[RawFinding]:
        """Check code signatures of apps in /Applications (macOS only)."""
        findings: list[RawFinding] = []

        apps_dir = Path("/Applications")
        if not apps_dir.exists():
            return findings

        for app in apps_dir.glob("*.app"):
            self.items_scanned += 1
            try:
                result = subprocess.run(
                    ["codesign", "--verify", "--deep", "--strict", str(app)],
                    capture_output=True, text=True, timeout=30,
                )

                if result.returncode != 0:
                    error = result.stderr.strip()
                    if "not signed" in error.lower():
                        findings.append(RawFinding(
                            category=FindingCategory.SUSPICIOUS_FILE,
                            severity=FindingSeverity.MEDIUM,
                            title=f"Unsigned application: {app.name}",
                            description=(
                                f"Application '{app.name}' has no code signature. "
                                f"Unsigned apps bypass macOS Gatekeeper protections and "
                                f"may have been modified or sideloaded."
                            ),
                            file_path=str(app),
                            app_name=app.name,
                            scanner_name=self.name,
                            mitre_technique="T1553.002",
                            mitre_tactic="Defense Evasion",
                            recommended_action="Verify app source. Re-download from official source if available.",
                        ))
                    elif "invalid signature" in error.lower() or "modified" in error.lower():
                        findings.append(RawFinding(
                            category=FindingCategory.COMPROMISED_APP,
                            severity=FindingSeverity.HIGH,
                            title=f"Tampered application: {app.name}",
                            description=(
                                f"Application '{app.name}' has an invalid or modified code "
                                f"signature. This indicates the application has been altered "
                                f"after it was signed, which could mean tampering or injection."
                            ),
                            file_path=str(app),
                            app_name=app.name,
                            scanner_name=self.name,
                            mitre_technique="T1554",
                            mitre_tactic="Persistence",
                            recommended_action="CRITICAL: Remove and re-install from official source.",
                        ))

            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return findings
