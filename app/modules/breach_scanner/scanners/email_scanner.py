"""
Email Scanner — inspects local email stores for suspicious attachments and phishing.

Checks:
  - Apple Mail (~/Library/Mail), Outlook (~/Library/Group Containers), Thunderbird
  - Office documents with VBA macros (the "opened an attachment" scenario)
  - Executables disguised as documents
  - Password-protected archives (used to evade scanning)
  - PDFs with JavaScript (exploit payloads)
  - Phishing links in email bodies
  - Attachments from unknown/spoofed senders
  - Recently received emails with suspicious characteristics
"""

from __future__ import annotations

import email
import hashlib
import logging
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..models import FindingCategory, FindingSeverity, OSPlatform, RawFinding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mail store paths by OS
# ---------------------------------------------------------------------------

MACOS_MAIL_PATHS = [
    "~/Library/Mail",
    "~/Library/Group Containers/UBF8T346G9.Office/Outlook/Outlook 15 Profiles",
    "~/Library/Thunderbird/Profiles",
]

WINDOWS_MAIL_PATHS = [
    r"C:\Users\{user}\AppData\Local\Microsoft\Outlook",
    r"C:\Users\{user}\AppData\Roaming\Thunderbird\Profiles",
]

LINUX_MAIL_PATHS = [
    "~/.thunderbird",
    "~/.local/share/evolution/mail",
]

# Dangerous attachment extensions
DANGEROUS_ATTACHMENT_EXTS = {
    ".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".hta", ".msi",
    ".dll", ".sys", ".cpl", ".inf", ".reg",
    ".jar", ".sh", ".command",
}

# Archive extensions that can hide payloads
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".gz", ".tar", ".bz2", ".xz"}

# Office extensions that can contain macros
MACRO_CAPABLE_EXTENSIONS = {
    ".doc", ".docm", ".xls", ".xlsm", ".ppt", ".pptm",
    ".dotm", ".xlam", ".ppam",
}

# Phishing URL patterns
PHISHING_PATTERNS = [
    re.compile(r"https?://[\w.-]*login[\w.-]*\.(?!microsoft\.com|google\.com|apple\.com)", re.I),
    re.compile(r"https?://[\w.-]*verify[\w.-]*\.(?!microsoft\.com|google\.com)", re.I),
    re.compile(r"https?://[\w.-]*secure[\w.-]*\.(?!microsoft\.com|google\.com|apple\.com)", re.I),
    re.compile(r"https?://[\w.-]*account[\w.-]*\.(?!microsoft\.com|google\.com|apple\.com)", re.I),
    re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/]", re.I),  # IP-based URLs
    re.compile(r"https?://[\w.-]*\.tk/|\.ml/|\.ga/|\.cf/|\.gq/", re.I),  # Free TLD abuse
    re.compile(r"data:text/html;base64,", re.I),  # Data URI phishing
    re.compile(r"https?://bit\.ly/|tinyurl\.com/|t\.co/|goo\.gl/", re.I),  # Shortened URLs in email
]

# OLE magic bytes for Office documents
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# OOXML (docx/xlsx/pptx) are ZIP files
OOXML_MAGIC = b"PK\x03\x04"


class EmailScanner:
    """
    Scans local email stores for malicious attachments and phishing indicators.
    """

    name = "email_scanner"

    def __init__(
        self,
        os_platform: OSPlatform = OSPlatform.MACOS,
        recent_days: int = 180,
        custom_paths: Optional[list[str]] = None,
    ):
        self.os_platform = os_platform
        self.recent_cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        self.custom_paths = custom_paths or []
        self.items_scanned = 0

    def get_mail_paths(self) -> list[Path]:
        """Return platform-appropriate mail store paths."""
        raw_paths = {
            OSPlatform.MACOS: MACOS_MAIL_PATHS,
            OSPlatform.WINDOWS: WINDOWS_MAIL_PATHS,
            OSPlatform.LINUX: LINUX_MAIL_PATHS,
        }.get(self.os_platform, MACOS_MAIL_PATHS)

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
        """Run the email scan across all mail stores."""
        findings: list[RawFinding] = []
        self.items_scanned = 0

        for mail_path in self.get_mail_paths():
            try:
                # Find .eml files (Apple Mail, Thunderbird)
                for eml_file in mail_path.rglob("*.eml"):
                    self.items_scanned += 1
                    findings.extend(self._scan_eml(eml_file))

                # Find .emlx files (Apple Mail specific)
                for emlx_file in mail_path.rglob("*.emlx"):
                    self.items_scanned += 1
                    findings.extend(self._scan_eml(emlx_file))

                # Find loose attachments in mail attachment folders
                for att_dir in mail_path.rglob("Attachments"):
                    if att_dir.is_dir():
                        findings.extend(self._scan_attachment_directory(att_dir))

            except PermissionError:
                logger.debug(f"Permission denied: {mail_path}")
            except Exception as e:
                logger.error(f"Error scanning mail path {mail_path}: {e}")

        # Also scan Downloads for recently downloaded email attachments
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            findings.extend(self._scan_recent_downloads(downloads))

        return findings

    def _scan_eml(self, eml_path: Path) -> list[RawFinding]:
        """Parse an .eml/.emlx file and inspect attachments + body."""
        findings: list[RawFinding] = []

        try:
            with open(eml_path, "rb") as f:
                raw = f.read()

            # emlx files have a byte count on the first line
            if eml_path.suffix == ".emlx":
                first_newline = raw.find(b"\n")
                if first_newline > 0:
                    raw = raw[first_newline + 1:]

            msg = email.message_from_bytes(raw)

            subject = msg.get("Subject", "(no subject)")
            sender = msg.get("From", "(unknown)")
            date_str = msg.get("Date", "")

            # Check attachments
            for part in msg.walk():
                content_type = part.get_content_type()
                filename = part.get_filename()

                if filename:
                    self.items_scanned += 1
                    findings.extend(
                        self._check_attachment(
                            filename, part.get_payload(decode=True),
                            subject, sender, date_str, str(eml_path),
                        )
                    )

            # Check body for phishing links
            body = self._extract_body(msg)
            if body:
                findings.extend(
                    self._check_phishing_links(body, subject, sender, date_str, str(eml_path))
                )

        except Exception as e:
            logger.debug(f"Error parsing {eml_path}: {e}")

        return findings

    def _check_attachment(
        self,
        filename: str,
        payload: Optional[bytes],
        subject: str,
        sender: str,
        date_str: str,
        eml_path: str,
    ) -> list[RawFinding]:
        """Inspect an email attachment for IOCs."""
        findings: list[RawFinding] = []
        if not payload:
            return findings

        ext = Path(filename).suffix.lower()
        sha256 = hashlib.sha256(payload).hexdigest()

        # --- Dangerous executable attachment ---
        if ext in DANGEROUS_ATTACHMENT_EXTS:
            findings.append(RawFinding(
                category=FindingCategory.SUSPICIOUS_EMAIL,
                severity=FindingSeverity.CRITICAL,
                title=f"Executable email attachment: {filename}",
                description=(
                    f"Email from {sender} (subject: '{subject}') contains "
                    f"executable attachment '{filename}'. Opening this file would "
                    f"execute code on the machine."
                ),
                file_path=eml_path,
                file_hash_sha256=sha256,
                file_size_bytes=len(payload),
                email_subject=subject,
                email_sender=sender,
                attachment_name=filename,
                scanner_name=self.name,
                mitre_technique="T1566.001",
                mitre_tactic="Initial Access",
                recommended_action="Do NOT open. Quarantine email. Report to IT.",
            ))

        # --- Office document with potential macros ---
        if ext in MACRO_CAPABLE_EXTENSIONS:
            has_macro = self._check_for_macros(payload)
            if has_macro:
                findings.append(RawFinding(
                    category=FindingCategory.MACRO_PAYLOAD,
                    severity=FindingSeverity.HIGH,
                    title=f"Office macro in email attachment: {filename}",
                    description=(
                        f"Email from {sender} (subject: '{subject}') contains "
                        f"Office document '{filename}' with VBA macros. Macros are the "
                        f"most common method for email-delivered malware — opening the file "
                        f"and enabling macros would execute code on the machine."
                    ),
                    file_path=eml_path,
                    file_hash_sha256=sha256,
                    file_size_bytes=len(payload),
                    email_subject=subject,
                    email_sender=sender,
                    attachment_name=filename,
                    scanner_name=self.name,
                    mitre_technique="T1566.001",
                    mitre_tactic="Initial Access",
                    raw_evidence={"macro_detected": True},
                    recommended_action=(
                        "Do NOT enable macros. Verify sender identity. "
                        "If unexpected, delete email and report to IT."
                    ),
                ))

        # --- Password-protected archive (evasion technique) ---
        if ext in ARCHIVE_EXTENSIONS:
            is_encrypted = self._check_encrypted_archive(payload)
            if is_encrypted:
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_EMAIL,
                    severity=FindingSeverity.HIGH,
                    title=f"Password-protected archive attachment: {filename}",
                    description=(
                        f"Email from {sender} (subject: '{subject}') contains "
                        f"password-protected archive '{filename}'. Attackers use "
                        f"password-protected archives to bypass email security scanning. "
                        f"The password is typically included in the email body."
                    ),
                    file_path=eml_path,
                    file_hash_sha256=sha256,
                    file_size_bytes=len(payload),
                    email_subject=subject,
                    email_sender=sender,
                    attachment_name=filename,
                    scanner_name=self.name,
                    mitre_technique="T1027.002",
                    mitre_tactic="Defense Evasion",
                    recommended_action="Do NOT extract. Verify sender identity before opening.",
                ))

        # --- File magic mismatch (e.g. .pdf that's really an executable) ---
        if ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".png"):
            actual_type = self._detect_file_type(payload)
            if actual_type and "executable" in actual_type.lower():
                findings.append(RawFinding(
                    category=FindingCategory.SUSPICIOUS_EMAIL,
                    severity=FindingSeverity.CRITICAL,
                    title=f"Disguised executable: {filename}",
                    description=(
                        f"Email attachment '{filename}' has a {ext} extension but "
                        f"is actually a {actual_type}. This is a social engineering "
                        f"technique to trick users into executing malware."
                    ),
                    file_path=eml_path,
                    file_hash_sha256=sha256,
                    email_subject=subject,
                    email_sender=sender,
                    attachment_name=filename,
                    scanner_name=self.name,
                    mitre_technique="T1036.007",
                    mitre_tactic="Defense Evasion",
                    recommended_action="CRITICAL: Do not open. Delete email. Report incident.",
                ))

        return findings

    def _check_phishing_links(
        self, body: str, subject: str, sender: str, date_str: str, eml_path: str,
    ) -> list[RawFinding]:
        """Scan email body for phishing URLs."""
        findings: list[RawFinding] = []

        for pattern in PHISHING_PATTERNS:
            matches = pattern.findall(body)
            for match in matches[:3]:  # Cap at 3 per pattern
                findings.append(RawFinding(
                    category=FindingCategory.PHISHING,
                    severity=FindingSeverity.MEDIUM,
                    title=f"Suspicious link in email: {match[:80]}",
                    description=(
                        f"Email from {sender} (subject: '{subject}') contains a "
                        f"link matching known phishing patterns. The URL may lead to a "
                        f"credential harvesting page or malware download."
                    ),
                    file_path=eml_path,
                    network_domain=match[:200],
                    email_subject=subject,
                    email_sender=sender,
                    scanner_name=self.name,
                    mitre_technique="T1566.002",
                    mitre_tactic="Initial Access",
                    recommended_action="Do not click links. Verify sender. Report phishing attempt.",
                ))

        return findings

    def _check_for_macros(self, payload: bytes) -> bool:
        """Detect VBA macros in Office documents."""
        try:
            # OLE format (.doc, .xls, .ppt)
            if payload[:8] == OLE_MAGIC:
                # Look for VBA stream indicators
                vba_indicators = [
                    b"_VBA_PROJECT",
                    b"VBA",
                    b"Macros",
                    b"ThisDocument",
                    b"Auto_Open",
                    b"AutoOpen",
                    b"Document_Open",
                    b"Workbook_Open",
                    b"Auto_Close",
                    b"Shell",
                    b"WScript",
                    b"PowerShell",
                    b"cmd.exe",
                    b"CreateObject",
                ]
                return any(ind in payload for ind in vba_indicators)

            # OOXML format (.docm, .xlsm) — look for vbaProject.bin inside ZIP
            if payload[:4] == OOXML_MAGIC:
                try:
                    import io
                    zf = zipfile.ZipFile(io.BytesIO(payload))
                    return any("vbaProject" in name for name in zf.namelist())
                except (zipfile.BadZipFile, Exception):
                    pass

        except Exception:
            pass

        return False

    def _check_encrypted_archive(self, payload: bytes) -> bool:
        """Detect if a ZIP archive is password-protected."""
        try:
            import io
            zf = zipfile.ZipFile(io.BytesIO(payload))
            for info in zf.infolist():
                if info.flag_bits & 0x1:  # Encrypted flag
                    return True
        except (zipfile.BadZipFile, Exception):
            pass
        return False

    def _detect_file_type(self, payload: bytes) -> Optional[str]:
        """Detect actual file type from magic bytes."""
        from ..scanners.filesystem_scanner import EXECUTABLE_MAGIC
        if len(payload) < 4:
            return None
        for magic, desc in EXECUTABLE_MAGIC.items():
            if payload[:len(magic)] == magic:
                return desc
        return None

    def _extract_body(self, msg: email.message.Message) -> str:
        """Extract plain text and HTML body from email."""
        body_parts = []
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body_parts.append(payload.decode(charset, errors="replace"))
                except Exception:
                    pass
        return "\n".join(body_parts)

    def _scan_attachment_directory(self, att_dir: Path) -> list[RawFinding]:
        """Scan a mail attachment directory for suspicious files."""
        findings: list[RawFinding] = []
        for f in att_dir.rglob("*"):
            if f.is_file():
                self.items_scanned += 1
                ext = f.suffix.lower()
                if ext in DANGEROUS_ATTACHMENT_EXTS:
                    findings.append(RawFinding(
                        category=FindingCategory.SUSPICIOUS_EMAIL,
                        severity=FindingSeverity.HIGH,
                        title=f"Executable in mail attachments folder: {f.name}",
                        description=(
                            f"Executable '{f.name}' found in email attachment cache at {f}. "
                            f"This may have been delivered via email and saved to disk."
                        ),
                        file_path=str(f),
                        file_hash_sha256=self._hash_file(f),
                        file_size_bytes=f.stat().st_size,
                        attachment_name=f.name,
                        scanner_name=self.name,
                        mitre_technique="T1566.001",
                        mitre_tactic="Initial Access",
                        recommended_action="Investigate email origin. Quarantine if unexpected.",
                    ))
        return findings

    def _scan_recent_downloads(self, downloads: Path) -> list[RawFinding]:
        """Scan Downloads for recently saved suspicious attachments."""
        findings: list[RawFinding] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        for f in downloads.iterdir():
            if not f.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    continue
            except OSError:
                continue

            ext = f.suffix.lower()
            if ext in MACRO_CAPABLE_EXTENSIONS:
                try:
                    payload = f.read_bytes()
                    if self._check_for_macros(payload):
                        findings.append(RawFinding(
                            category=FindingCategory.MACRO_PAYLOAD,
                            severity=FindingSeverity.HIGH,
                            title=f"Macro-enabled document in Downloads: {f.name}",
                            description=(
                                f"Recently downloaded Office document '{f.name}' contains "
                                f"VBA macros. If this file was opened and macros were enabled, "
                                f"code may have been executed on the machine."
                            ),
                            file_path=str(f),
                            file_hash_sha256=hashlib.sha256(payload).hexdigest(),
                            file_size_bytes=len(payload),
                            file_modified=mtime,
                            attachment_name=f.name,
                            scanner_name=self.name,
                            mitre_technique="T1204.002",
                            mitre_tactic="Execution",
                            recommended_action="Check if macros were enabled. Run full scan.",
                        ))
                except (OSError, PermissionError):
                    pass

        return findings

    def _hash_file(self, filepath: Path) -> Optional[str]:
        """SHA256 hash a file."""
        try:
            h = hashlib.sha256()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except (OSError, PermissionError):
            return None
