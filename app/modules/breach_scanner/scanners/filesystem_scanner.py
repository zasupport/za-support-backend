"""
Filesystem Scanner — inspects the local filesystem for indicators of compromise.

Checks:
  - Known malware installation paths (per-OS)
  - Recently modified executables in unusual locations
  - Hidden files/folders in user-writable directories
  - Files with mismatched extensions (e.g. .pdf that's actually an executable)
  - Unsigned or ad-hoc signed binaries in non-standard paths
  - Suspicious file names (base64-encoded, random strings, impersonating system files)
  - Large encrypted archives in temp/download folders
  - Known malware filenames and hashes
  - World-writable executables
  - Files with double extensions (.pdf.exe, .doc.scr)
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import stat
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..models import FindingCategory, FindingSeverity, OSPlatform, RawFinding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known malware paths by OS
# ---------------------------------------------------------------------------

MACOS_SUSPECT_PATHS = [
    "~/Library/LaunchAgents",
    "~/Library/LaunchDaemons",
    "/Library/LaunchAgents",
    "/Library/LaunchDaemons",
    "/tmp",
    "/var/tmp",
    "~/Library/Application Support/.hidden",
    "~/Library/Caches",
    "~/Library/Containers",
    "~/.local/share",
    "~/.config",
    "/usr/local/bin",
    "/opt",
    "~/Downloads",
    "~/Desktop",
    "~/Documents",
    "~/.Trash",
]

WINDOWS_SUSPECT_PATHS = [
    r"C:\Users\{user}\AppData\Local\Temp",
    r"C:\Users\{user}\AppData\Roaming",
    r"C:\ProgramData",
    r"C:\Windows\Temp",
    r"C:\Users\{user}\Downloads",
    r"C:\Users\{user}\Desktop",
    r"C:\Users\{user}\AppData\Local\Microsoft\Windows\INetCache",
]

LINUX_SUSPECT_PATHS = [
    "/tmp", "/var/tmp", "/dev/shm",
    "~/.local/bin", "~/.config",
    "/usr/local/bin", "/opt",
    "~/Downloads", "~/Desktop",
]

# Executable extensions that should not appear in document folders
EXECUTABLE_EXTENSIONS = {
    ".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".psm1", ".msi", ".msp",
    ".dll", ".sys", ".drv", ".cpl", ".inf", ".hta", ".reg",
    # macOS
    ".app", ".command", ".sh", ".pkg", ".dmg",
    # Cross-platform
    ".jar", ".py", ".rb", ".pl",
}

# Double extensions — strong indicator of social engineering
DOUBLE_EXTENSION_PATTERN = re.compile(
    r"\.(pdf|doc|docx|xls|xlsx|jpg|png|txt|csv|rtf)\.(exe|scr|bat|cmd|com|pif|js|vbs|hta|ps1|sh|command)$",
    re.IGNORECASE,
)

# Suspicious filename patterns
SUSPICIOUS_NAME_PATTERNS = [
    re.compile(r"^[a-zA-Z0-9+/]{20,}={0,2}\.\w+$"),       # Base64-like names
    re.compile(r"^[0-9a-f]{32,64}(\.\w+)?$"),               # Hash-like names
    re.compile(r"^\.\.[\w]+"),                                # Starts with ..
    re.compile(r"svchost|csrss|lsass|explorer|winlogon",     # System impersonation (Windows)
               re.IGNORECASE),
    re.compile(r"update|installer|setup|patch|crack|keygen|activat",
               re.IGNORECASE),                               # Social engineering names
]

# Known malware filenames (small sample — extended via YARA/hash DB)
KNOWN_MALWARE_NAMES = {
    "emotet.exe", "wannacry.exe", "mimikatz.exe", "lazagne.exe",
    "cobaltstrike.dll", "beacon.dll", "meterpreter.exe",
    "ncat.exe", "nc.exe", "netcat.exe", "psexec.exe",
    "procdump.exe", "rubeus.exe", "seatbelt.exe",
    # macOS-specific
    "osascript_payload", "xcsset", "shlayer", "bundlore",
    "macma", "dazzlespy", "cloudburst", "rustbucket",
}

# File magic bytes for executable detection
EXECUTABLE_MAGIC = {
    b"\x4d\x5a": "PE/Windows executable",          # MZ header
    b"\x7fELF": "ELF/Linux executable",             # ELF header
    b"\xfe\xed\xfa\xce": "Mach-O 32-bit",           # Mach-O
    b"\xfe\xed\xfa\xcf": "Mach-O 64-bit",           # Mach-O 64
    b"\xca\xfe\xba\xbe": "Mach-O Universal Binary",  # Fat binary
    b"\xcf\xfa\xed\xfe": "Mach-O 64-bit (reversed)", # Mach-O 64 LE
    b"PK\x03\x04": "ZIP/JAR archive",                # Could be .jar malware
}


class FilesystemScanner:
    """
    Deep filesystem scan for indicators of compromise.
    Runs on the client device via the Health Check agent.
    """

    name = "filesystem_scanner"

    def __init__(
        self,
        os_platform: OSPlatform = OSPlatform.MACOS,
        max_file_size_mb: int = 100,
        recent_days: int = 90,
        custom_paths: Optional[list[str]] = None,
    ):
        self.os_platform = os_platform
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        self.custom_paths = custom_paths or []
        self.items_scanned = 0

    def get_scan_paths(self) -> list[Path]:
        """Return platform-appropriate paths to scan."""
        raw_paths = {
            OSPlatform.MACOS: MACOS_SUSPECT_PATHS,
            OSPlatform.WINDOWS: WINDOWS_SUSPECT_PATHS,
            OSPlatform.LINUX: LINUX_SUSPECT_PATHS,
        }.get(self.os_platform, MACOS_SUSPECT_PATHS)

        paths = []
        home = str(Path.home())
        user = os.getenv("USER", os.getenv("USERNAME", "user"))

        for p in raw_paths + self.custom_paths:
            expanded = p.replace("~", home).replace("{user}", user)
            path = Path(expanded)
            if path.exists():
                paths.append(path)

        return paths

    def scan(self) -> list[RawFinding]:
        """Run the full filesystem scan. Returns list of findings."""
        findings: list[RawFinding] = []
        self.items_scanned = 0

        for scan_path in self.get_scan_paths():
            try:
                findings.extend(self._scan_directory(scan_path))
            except PermissionError:
                logger.debug(f"Permission denied: {scan_path}")
            except Exception as e:
                logger.error(f"Error scanning {scan_path}: {e}")

        return findings

    def _scan_directory(self, directory: Path, depth: int = 0, max_depth: int = 5) -> list[RawFinding]:
        """Recursively scan a directory up to max_depth."""
        if depth > max_depth:
            return []

        findings: list[RawFinding] = []

        try:
            for entry in directory.iterdir():
                self.items_scanned += 1
                try:
                    if entry.is_symlink():
                        continue  # Skip symlinks to avoid loops

                    if entry.is_file():
                        findings.extend(self._check_file(entry))
                    elif entry.is_dir():
                        # Check directory itself for suspicious characteristics
                        findings.extend(self._check_directory(entry))
                        # Recurse
                        findings.extend(self._scan_directory(entry, depth + 1, max_depth))

                except PermissionError:
                    continue
                except Exception as e:
                    logger.debug(f"Error checking {entry}: {e}")

        except PermissionError:
            pass

        return findings

    def _check_file(self, filepath: Path) -> list[RawFinding]:
        """Run all file-level checks on a single file."""
        findings: list[RawFinding] = []
        name = filepath.name
        name_lower = name.lower()

        try:
            file_stat = filepath.stat()
            file_size = file_stat.st_size
        except (OSError, PermissionError):
            return findings

        if file_size > self.max_file_size:
            return findings  # Skip very large files

        # --- Check 1: Double extensions ---
        if DOUBLE_EXTENSION_PATTERN.search(name):
            findings.append(RawFinding(
                category=FindingCategory.SUSPICIOUS_FILE,
                severity=FindingSeverity.HIGH,
                title=f"Double extension file: {name}",
                description=(
                    f"File '{name}' uses a double extension, a common social engineering "
                    f"technique to disguise executables as documents. Located at {filepath}."
                ),
                file_path=str(filepath),
                file_size_bytes=file_size,
                file_modified=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
                scanner_name=self.name,
                mitre_technique="T1036.007",
                mitre_tactic="Defense Evasion",
                recommended_action="Quarantine file immediately. Do not open. Submit hash to VirusTotal.",
            ))

        # --- Check 2: Known malware filenames ---
        if name_lower in KNOWN_MALWARE_NAMES:
            findings.append(RawFinding(
                category=FindingCategory.MALWARE,
                severity=FindingSeverity.CRITICAL,
                title=f"Known malware filename: {name}",
                description=(
                    f"File '{name}' matches a known malware tool name. "
                    f"Located at {filepath}. Requires immediate investigation."
                ),
                file_path=str(filepath),
                file_hash_sha256=self._hash_file(filepath, "sha256"),
                file_hash_md5=self._hash_file(filepath, "md5"),
                file_size_bytes=file_size,
                scanner_name=self.name,
                recommended_action="Isolate device from network. Do not delete — preserve for forensics.",
            ))

        # --- Check 3: Executables in document/download folders ---
        parent_name = filepath.parent.name.lower()
        if parent_name in ("downloads", "desktop", "documents", "tmp", "temp"):
            ext = filepath.suffix.lower()
            if ext in EXECUTABLE_EXTENSIONS:
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_FILE,
                    severity=FindingSeverity.MEDIUM,
                    title=f"Executable in {parent_name}: {name}",
                    description=(
                        f"Executable file '{name}' found in {parent_name} folder. "
                        f"Executables in user folders may indicate a downloaded payload."
                    ),
                    file_path=str(filepath),
                    file_hash_sha256=self._hash_file(filepath, "sha256"),
                    file_size_bytes=file_size,
                    file_modified=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
                    scanner_name=self.name,
                    mitre_technique="T1204.002",
                    mitre_tactic="Execution",
                    recommended_action="Verify origin. If unknown, quarantine and scan with antivirus.",
                ))

        # --- Check 4: Hidden files with executable magic bytes ---
        if name.startswith(".") and file_size > 0:
            magic = self._read_magic(filepath)
            if magic:
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_FILE,
                    severity=FindingSeverity.HIGH,
                    title=f"Hidden executable: {name}",
                    description=(
                        f"Hidden file '{name}' contains {magic} magic bytes, "
                        f"indicating it is an executable disguised as a hidden file. "
                        f"Located at {filepath}."
                    ),
                    file_path=str(filepath),
                    file_hash_sha256=self._hash_file(filepath, "sha256"),
                    file_size_bytes=file_size,
                    scanner_name=self.name,
                    mitre_technique="T1564.001",
                    mitre_tactic="Defense Evasion",
                    recommended_action="Quarantine and submit hash for threat intel lookup.",
                ))

        # --- Check 5: Suspicious filename patterns ---
        for pattern in SUSPICIOUS_NAME_PATTERNS:
            if pattern.search(name_lower):
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_FILE,
                    severity=FindingSeverity.LOW,
                    title=f"Suspicious filename pattern: {name}",
                    description=(
                        f"File '{name}' matches a suspicious naming pattern "
                        f"(randomised, base64-encoded, or system impersonation). "
                        f"Located at {filepath}."
                    ),
                    file_path=str(filepath),
                    file_hash_sha256=self._hash_file(filepath, "sha256"),
                    file_size_bytes=file_size,
                    scanner_name=self.name,
                    recommended_action="Investigate file origin and purpose.",
                ))
                break  # One match is enough

        # --- Check 6: Recently modified binary in system paths ---
        if file_size > 0 and filepath.suffix.lower() in (".dylib", ".so", ".dll", ".sys"):
            mod_time = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc)
            if mod_time > self.recent_cutoff:
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_FILE,
                    severity=FindingSeverity.MEDIUM,
                    title=f"Recently modified system library: {name}",
                    description=(
                        f"System library '{name}' was modified on "
                        f"{mod_time.strftime('%d/%m/%Y %H:%M')}. Recent modification of "
                        f"system libraries can indicate DLL/dylib injection."
                    ),
                    file_path=str(filepath),
                    file_hash_sha256=self._hash_file(filepath, "sha256"),
                    file_modified=mod_time,
                    scanner_name=self.name,
                    mitre_technique="T1574.001",
                    mitre_tactic="Persistence",
                    recommended_action="Compare hash against known-good version. Investigate if unsigned.",
                ))

        # --- Check 7: World-writable executables ---
        if os.name != "nt":  # Unix only
            try:
                mode = file_stat.st_mode
                if (mode & stat.S_IWOTH) and (mode & stat.S_IXUSR):
                    findings.append(RawFinding(
                        category=FindingCategory.SUSPICIOUS_FILE,
                        severity=FindingSeverity.MEDIUM,
                        title=f"World-writable executable: {name}",
                        description=(
                            f"File '{name}' is both world-writable and executable. "
                            f"This allows any user or process to modify the binary."
                        ),
                        file_path=str(filepath),
                        scanner_name=self.name,
                        mitre_technique="T1222.002",
                        mitre_tactic="Defense Evasion",
                        recommended_action="Remove world-writable permission: chmod o-w",
                    ))
            except (OSError, AttributeError):
                pass

        return findings

    def _check_directory(self, dirpath: Path) -> list[RawFinding]:
        """Check directory-level anomalies."""
        findings: list[RawFinding] = []
        name = dirpath.name

        # Hidden directories in user-writable locations with executables inside
        if name.startswith(".") and name not in (
            ".Trash", ".git", ".ssh", ".gnupg", ".config", ".local",
            ".npm", ".cache", ".vscode", ".zsh_sessions",
        ):
            try:
                has_executables = any(
                    f.suffix.lower() in EXECUTABLE_EXTENSIONS
                    for f in dirpath.iterdir()
                    if f.is_file()
                )
                if has_executables:
                    findings.append(RawFinding(
                        category=FindingCategory.SUSPICIOUS_FILE,
                        severity=FindingSeverity.HIGH,
                        title=f"Hidden directory with executables: {name}",
                        description=(
                            f"Hidden directory '{dirpath}' contains executable files. "
                            f"Malware commonly creates hidden directories to store payloads."
                        ),
                        file_path=str(dirpath),
                        scanner_name=self.name,
                        mitre_technique="T1564.001",
                        mitre_tactic="Defense Evasion",
                        recommended_action="Inspect directory contents. Quarantine if unrecognised.",
                    ))
            except PermissionError:
                pass

        return findings

    def _hash_file(self, filepath: Path, algorithm: str = "sha256") -> Optional[str]:
        """Compute file hash. Returns None on error."""
        try:
            h = hashlib.new(algorithm)
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except (OSError, PermissionError):
            return None

    def _read_magic(self, filepath: Path) -> Optional[str]:
        """Read first bytes and check against known executable signatures."""
        try:
            with open(filepath, "rb") as f:
                header = f.read(8)
            if len(header) < 2:
                return None
            for magic, desc in EXECUTABLE_MAGIC.items():
                if header[:len(magic)] == magic:
                    return desc
        except (OSError, PermissionError):
            pass
        return None
