"""
Health Check AI — Forensics Module
Tool Wrappers: One class per forensic tool.
Each wrapper handles subprocess execution, output parsing, and finding extraction.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Base Tool Wrapper ─────────────────────────────────────────────────────────

class ToolResult:
    """Standard result object returned by all tool wrappers."""
    def __init__(self, tool_id: str, task_type: str):
        self.tool_id        = tool_id
        self.task_type      = task_type
        self.success        = False
        self.exit_code      = None
        self.command        = ""
        self.raw_output     = ""
        self.error_output   = ""
        self.duration_secs  = 0.0
        self.findings:  list[dict] = []
        self.artifacts: list[dict] = []   # files created
        self.summary        = ""          # human-readable one-liner

    def add_finding(self, severity: str, category: str, title: str,
                    detail: str = "", source: str = "", raw: str = ""):
        self.findings.append({
            "severity":        severity,
            "category":        category,
            "title":           title,
            "detail":          detail,
            "source_artifact": source,
            "raw_indicator":   raw,
        })

    def add_artifact(self, filename: str, path: str, size_bytes: int, sha256: str = ""):
        self.artifacts.append({
            "filename":     filename,
            "file_path":    path,
            "size_bytes":   size_bytes,
            "sha256_intake": sha256,
        })

    def to_dict(self) -> dict:
        return {
            "tool_id":       self.tool_id,
            "task_type":     self.task_type,
            "success":       self.success,
            "exit_code":     self.exit_code,
            "command":       self.command,
            "duration_secs": self.duration_secs,
            "summary":       self.summary,
            "findings":      self.findings,
            "artifacts":     self.artifacts,
            "error":         self.error_output if not self.success else "",
        }


class BaseTool(ABC):
    """Abstract base for all forensic tool wrappers."""

    tool_id   = ""
    tool_name = ""

    def _run(self, cmd: list[str], timeout: int = 300,
             cwd: Optional[str] = None) -> tuple[int, str, str, float]:
        """Run a subprocess command. Returns (exit_code, stdout, stderr, duration_secs)."""
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return proc.returncode, proc.stdout, proc.stderr, time.time() - start
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout}s", time.time() - start
        except FileNotFoundError:
            return -2, "", f"Binary not found: {cmd[0]}", 0.0
        except Exception as e:
            return -3, "", str(e), time.time() - start

    def _sha256(self, filepath: str) -> str:
        """Calculate SHA-256 hash of a file."""
        h = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    @abstractmethod
    def run(self, output_dir: str, **kwargs) -> ToolResult:
        """Execute the tool and return a ToolResult."""
        pass


# ─── Volatility 3 — Memory Forensics ─────────────────────────────────────────

class VolatilityTool(BaseTool):
    """
    Volatility 3 wrapper for memory dump analysis.
    Runs multiple plugins to extract process list, network connections,
    cmd line history, injected code indicators, and loaded modules.
    """
    tool_id   = "volatility3"
    tool_name = "Volatility 3"

    PLUGINS = {
        "windows.pslist.PsList":       "Running processes (Windows)",
        "windows.netstat.NetStat":     "Network connections (Windows)",
        "windows.cmdline.CmdLine":     "Command line history (Windows)",
        "windows.dlllist.DllList":     "Loaded DLLs (Windows)",
        "windows.malfind.Malfind":     "Injected code / suspicious memory regions",
        "mac.pslist.PsList":           "Running processes (macOS)",
        "mac.netstat.Netstat":         "Network connections (macOS)",
        "linux.pslist.PsList":         "Running processes (Linux)",
        "linux.netstat.Netstat":       "Network connections (Linux)",
    }

    # Suspicious indicators in process / cmdline output
    SUSPICIOUS_PATTERNS = [
        (r"powershell.*-enc",            "high",    "malware_indicator",  "Encoded PowerShell command"),
        (r"powershell.*-nop",            "high",    "malware_indicator",  "PowerShell no-profile execution"),
        (r"cmd\.exe.*\/c.*http",         "high",    "malware_indicator",  "cmd.exe fetching remote content"),
        (r"wscript|cscript",             "medium",  "malware_indicator",  "Script interpreter running"),
        (r"mshta\.exe",                  "high",    "malware_indicator",  "MSHTA execution (common in LOLBin attacks)"),
        (r"regsvr32.*http",              "critical","malware_indicator",  "Regsvr32 remote code execution"),
        (r"rundll32.*javascript",        "critical","malware_indicator",  "Rundll32 JavaScript execution"),
        (r"certutil.*-decode",           "high",    "malware_indicator",  "certutil decoding (common malware dropper technique)"),
    ]

    def run(self, output_dir: str, memory_image: str, os_type: str = "windows", **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "memory_analysis")
        os.makedirs(output_dir, exist_ok=True)
        all_output = []

        # Determine which plugins apply based on OS
        plugins_to_run = {
            k: v for k, v in self.PLUGINS.items()
            if k.startswith(os_type.lower())
        }
        if not plugins_to_run:
            result.error_output = f"No Volatility plugins found for OS type: {os_type}"
            result.summary = "No compatible plugins found"
            return result

        for plugin, description in plugins_to_run.items():
            logger.info(f"[volatility] Running plugin: {plugin}")
            out_file = os.path.join(output_dir, f"vol3_{plugin.replace('.', '_')}.txt")
            cmd = ["vol", "-f", memory_image, plugin]
            code, stdout, stderr, duration = self._run(cmd, timeout=600)

            if code == 0 and stdout:
                with open(out_file, "w") as f:
                    f.write(stdout)
                sha = self._sha256(out_file)
                size = os.path.getsize(out_file)
                result.add_artifact(os.path.basename(out_file), out_file, size, sha)
                all_output.append(f"\n=== {description} ===\n{stdout[:5000]}")

                # Scan output for suspicious patterns
                for pattern, severity, category, title in self.SUSPICIOUS_PATTERNS:
                    for line in stdout.splitlines():
                        if re.search(pattern, line, re.IGNORECASE):
                            result.add_finding(
                                severity=severity, category=category,
                                title=title, detail=description,
                                source=plugin, raw=line.strip()[:200]
                            )

        result.success = True
        result.summary = (
            f"Memory analysis complete: {len(result.findings)} indicators found "
            f"across {len(plugins_to_run)} plugins."
        )
        return result


# ─── The Sleuth Kit — Disk Forensics ─────────────────────────────────────────

class SleuthKitTool(BaseTool):
    """
    TSK wrapper: lists files, recovers deleted items, and extracts a body file
    for timeline analysis. Runs on disk images or mounted volumes.
    """
    tool_id   = "sleuthkit"
    tool_name = "The Sleuth Kit"

    def run(self, output_dir: str, image_path: str, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "disk_analysis")
        os.makedirs(output_dir, exist_ok=True)

        # fls — file system listing including deleted files
        fls_out = os.path.join(output_dir, "tsk_file_listing.txt")
        body_out = os.path.join(output_dir, "tsk_body.txt")

        cmd_fls = ["fls", "-r", "-l", image_path]
        code, stdout, stderr, duration = self._run(cmd_fls, timeout=300)

        if code == 0:
            with open(fls_out, "w") as f:
                f.write(stdout)
            sha = self._sha256(fls_out)
            result.add_artifact("tsk_file_listing.txt", fls_out,
                                 os.path.getsize(fls_out), sha)

            # Look for recently deleted files
            deleted = [l for l in stdout.splitlines() if l.startswith("d/d") or "* " in l]
            if deleted:
                result.add_finding(
                    severity="medium", category="data_deletion",
                    title=f"{len(deleted)} deleted file entries found",
                    detail="Deleted files found in file system metadata. "
                           "File carving may recover content.",
                    source="fls", raw="\n".join(deleted[:20])
                )

        # Generate body file for timeline
        cmd_body = ["fls", "-r", "-m", "/", "-p", image_path]
        code2, stdout2, stderr2, _ = self._run(cmd_body, timeout=300)
        if code2 == 0:
            with open(body_out, "w") as f:
                f.write(stdout2)
            sha2 = self._sha256(body_out)
            result.add_artifact("tsk_body.txt", body_out,
                                 os.path.getsize(body_out), sha2)

        result.success = (code == 0 or code2 == 0)
        result.summary = (
            f"Disk analysis: file listing {'OK' if code == 0 else 'failed'}, "
            f"body file {'OK' if code2 == 0 else 'failed'}, "
            f"{len(result.findings)} indicators."
        )
        return result


# ─── YARA — Malware Pattern Matching ─────────────────────────────────────────

BUILTIN_YARA_RULES = """
rule Suspicious_Base64_Payload {
    meta:
        description = "Large base64-encoded payload (possible dropper)"
        severity = "high"
    strings:
        $b64 = /[A-Za-z0-9+\\/]{500,}={0,2}/
    condition:
        $b64
}

rule Suspicious_PowerShell_Encoded {
    meta:
        description = "PowerShell encoded command execution"
        severity = "high"
    strings:
        $s1 = "-EncodedCommand" nocase
        $s2 = "-enc " nocase
        $s3 = "powershell" nocase
    condition:
        $s3 and ($s1 or $s2)
}

rule Suspicious_Windows_Credentials {
    meta:
        description = "Credential-related strings in binary"
        severity = "medium"
    strings:
        $s1 = "password" nocase
        $s2 = "lsass" nocase
        $s3 = "mimikatz" nocase
        $s4 = "sekurlsa" nocase
    condition:
        2 of them
}

rule Suspicious_Network_C2_Patterns {
    meta:
        description = "Possible C2 beaconing patterns"
        severity = "high"
    strings:
        $s1 = "Mozilla/4.0 (compatible; MSIE 6.0"
        $s2 = "cmd.exe /c"
        $s3 = "net user"
        $s4 = "whoami"
    condition:
        2 of them
}

rule Suspicious_Ransomware_Indicators {
    meta:
        description = "Ransomware-related strings"
        severity = "critical"
    strings:
        $s1 = "encrypt" nocase
        $s2 = "bitcoin" nocase
        $s3 = "ransom" nocase
        $s4 = "your files" nocase
        $s5 = ".onion" nocase
    condition:
        3 of them
}
"""


class YARATool(BaseTool):
    """
    YARA wrapper. Scans a target path (file, directory, or memory dump)
    against built-in rules and any custom rule files provided.
    """
    tool_id   = "yara"
    tool_name = "YARA"

    def run(self, output_dir: str, scan_target: str,
            custom_rules_path: Optional[str] = None, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "yara_scan")
        os.makedirs(output_dir, exist_ok=True)

        # Write built-in rules to temp file
        rules_file = os.path.join(output_dir, "builtin_rules.yar")
        with open(rules_file, "w") as f:
            f.write(BUILTIN_YARA_RULES)

        rules_to_scan = [rules_file]
        if custom_rules_path and os.path.exists(custom_rules_path):
            rules_to_scan.append(custom_rules_path)

        all_matches = []
        for rule_file in rules_to_scan:
            out_file = os.path.join(output_dir,
                                    f"yara_{Path(rule_file).stem}_results.txt")
            cmd = ["yara", "-r", rule_file, scan_target]
            code, stdout, stderr, duration = self._run(cmd, timeout=300)

            if stdout.strip():
                with open(out_file, "w") as f:
                    f.write(stdout)
                sha = self._sha256(out_file)
                result.add_artifact(os.path.basename(out_file), out_file,
                                     os.path.getsize(out_file), sha)

                for line in stdout.strip().splitlines():
                    all_matches.append(line)
                    parts = line.split(" ", 1)
                    rule_name  = parts[0] if parts else "unknown"
                    match_file = parts[1] if len(parts) > 1 else scan_target

                    # Map rule names to severity
                    severity = "medium"
                    if "Ransomware" in rule_name:  severity = "critical"
                    elif "C2" in rule_name:         severity = "high"
                    elif "PowerShell" in rule_name: severity = "high"

                    result.add_finding(
                        severity=severity,
                        category="malware_indicator",
                        title=f"YARA rule matched: {rule_name}",
                        detail="YARA pattern match detected. This is an indicator "
                               "requiring human review — not a confirmed infection.",
                        source=rule_file,
                        raw=f"Rule: {rule_name} | File: {match_file}"
                    )

        result.success = True
        result.summary = (
            f"YARA scan complete: {len(all_matches)} rule matches across "
            f"{len(rules_to_scan)} rule files. All matches require human review."
        )
        return result


# ─── Strings — String Extraction ─────────────────────────────────────────────

class StringsTool(BaseTool):
    """
    Extracts printable strings from binaries. Useful for identifying
    hardcoded URLs, IP addresses, credentials, and C2 indicators.
    """
    tool_id   = "strings"
    tool_name = "strings"

    IP_RE  = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    URL_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

    def run(self, output_dir: str, target_file: str, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "string_extraction")
        os.makedirs(output_dir, exist_ok=True)

        out_file = os.path.join(output_dir, "strings_output.txt")
        cmd = ["strings", "-n", "8", target_file]
        code, stdout, stderr, duration = self._run(cmd, timeout=120)

        if code == 0 and stdout:
            with open(out_file, "w") as f:
                f.write(stdout)
            sha = self._sha256(out_file)
            result.add_artifact("strings_output.txt", out_file,
                                 os.path.getsize(out_file), sha)

            # Extract interesting values
            urls    = list(set(self.URL_RE.findall(stdout)))[:50]
            ips     = list(set(self.IP_RE.findall(stdout)))[:50]
            emails  = list(set(self.EMAIL_RE.findall(stdout)))[:50]

            if urls:
                result.add_finding(
                    severity="medium", category="network_indicator",
                    title=f"{len(urls)} URL(s) found in binary strings",
                    detail="URLs embedded in the binary may indicate network communication "
                           "targets, update servers, or command-and-control infrastructure.",
                    source=target_file,
                    raw="\n".join(urls[:10])
                )
            if ips:
                result.add_finding(
                    severity="low", category="network_indicator",
                    title=f"{len(ips)} IP address(es) found in binary strings",
                    source=target_file, raw="\n".join(ips[:10])
                )

        result.success = (code == 0)
        result.summary = (
            f"String extraction: {len(result.findings)} network indicators found."
        )
        return result


# ─── Bulk Extractor ────────────────────────────────────────────────────────────

class BulkExtractorTool(BaseTool):
    """
    Bulk extractor scans disk images for email addresses, URLs, credit card numbers,
    GPS coordinates, and other structured data — without parsing the file system.
    """
    tool_id   = "bulk_extractor"
    tool_name = "Bulk Extractor"

    def run(self, output_dir: str, image_path: str, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "bulk_extraction")
        be_out = os.path.join(output_dir, "bulk_extractor_output")
        os.makedirs(be_out, exist_ok=True)

        cmd = ["bulk_extractor", "-o", be_out, image_path]
        code, stdout, stderr, duration = self._run(cmd, timeout=3600)

        if code == 0:
            # Process each output file
            for fname in os.listdir(be_out):
                fpath = os.path.join(be_out, fname)
                if not os.path.isfile(fpath):
                    continue
                size = os.path.getsize(fpath)
                if size == 0:
                    continue
                sha = self._sha256(fpath)
                result.add_artifact(fname, fpath, size, sha)

                # Flag notable scanner outputs
                if fname == "email.txt" and size > 0:
                    result.add_finding(
                        severity="low", category="pii_exposure",
                        title="Email addresses found in disk image",
                        detail="Email addresses recovered from unallocated space or deleted files. "
                               "May indicate POPIA-relevant personal information.",
                        source="bulk_extractor", raw=f"{fname}: {size} bytes"
                    )
                elif fname == "ccn.txt" and size > 0:
                    result.add_finding(
                        severity="high", category="pii_exposure",
                        title="Possible credit card numbers found in disk image",
                        detail="Credit card number patterns detected. Requires immediate review.",
                        source="bulk_extractor", raw=f"{fname}: {size} bytes"
                    )
                elif fname == "url.txt" and size > 100:
                    result.add_finding(
                        severity="low", category="network_artefacts",
                        title="URL history recovered from disk",
                        source="bulk_extractor", raw=f"{fname}: {size} bytes"
                    )

        result.success = (code == 0)
        result.summary = (
            f"Bulk extraction: {len(result.artifacts)} artefact files created, "
            f"{len(result.findings)} notable findings."
        )
        return result


# ─── TShark — Network Capture Analysis ───────────────────────────────────────

class TSharkTool(BaseTool):
    """
    TShark wrapper for analysing existing PCAP captures or
    performing a live capture for a specified duration.
    """
    tool_id   = "tshark"
    tool_name = "TShark"

    def run(self, output_dir: str, pcap_file: Optional[str] = None,
            capture_interface: Optional[str] = None,
            capture_duration: int = 60, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "network_analysis")
        os.makedirs(output_dir, exist_ok=True)

        if pcap_file and os.path.exists(pcap_file):
            target = pcap_file
        elif capture_interface:
            # Live capture
            target = os.path.join(output_dir, "live_capture.pcap")
            cmd_cap = ["tshark", "-i", capture_interface,
                       "-a", f"duration:{capture_duration}",
                       "-w", target]
            code, _, stderr, _ = self._run(cmd_cap, timeout=capture_duration + 30)
            if code != 0:
                result.error_output = stderr
                result.summary = "Live capture failed"
                return result
        else:
            result.error_output = "No PCAP file or capture interface provided"
            result.summary = "No input provided"
            return result

        # Analyse the PCAP
        stats_file = os.path.join(output_dir, "tshark_conversations.txt")
        dns_file   = os.path.join(output_dir, "tshark_dns.txt")
        http_file  = os.path.join(output_dir, "tshark_http.txt")

        analyses = [
            (["tshark", "-r", target, "-q", "-z", "conv,tcp"],    stats_file),
            (["tshark", "-r", target, "-Y", "dns", "-T", "fields",
              "-e", "dns.qry.name"],                               dns_file),
            (["tshark", "-r", target, "-Y", "http.request",
              "-T", "fields", "-e", "http.host", "-e", "http.request.uri"], http_file),
        ]

        for cmd, out_f in analyses:
            code, stdout, stderr, _ = self._run(cmd, timeout=120)
            if stdout.strip():
                with open(out_f, "w") as f:
                    f.write(stdout)
                sha = self._sha256(out_f)
                result.add_artifact(os.path.basename(out_f), out_f,
                                     os.path.getsize(out_f), sha)

        # Check for suspicious DNS (long domains = DGA?)
        if os.path.exists(dns_file):
            with open(dns_file) as f:
                domains = [l.strip() for l in f if l.strip()]
            dga_suspects = [d for d in domains if len(d) > 30 and d.count(".") == 1]
            if dga_suspects:
                result.add_finding(
                    severity="high", category="network_indicator",
                    title=f"{len(dga_suspects)} possible DGA domain(s) detected",
                    detail="Long random-looking domain names may indicate "
                           "domain generation algorithm (DGA) malware beaconing.",
                    source="tshark_dns",
                    raw="\n".join(dga_suspects[:10])
                )

        result.success = True
        result.summary = (
            f"Network analysis: {len(result.artifacts)} analysis files, "
            f"{len(result.findings)} indicators."
        )
        return result


# ─── Foremost — File Carving ──────────────────────────────────────────────────

class ForemostTool(BaseTool):
    """
    File carving — recovers files from disk images based on file signatures,
    regardless of the file system state.
    """
    tool_id   = "foremost"
    tool_name = "Foremost"

    def run(self, output_dir: str, image_path: str, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "file_carving")
        carve_dir = os.path.join(output_dir, "foremost_carved")
        os.makedirs(carve_dir, exist_ok=True)

        cmd = ["foremost", "-t", "all", "-i", image_path, "-o", carve_dir]
        code, stdout, stderr, duration = self._run(cmd, timeout=3600)

        if code == 0:
            # Parse audit.txt for summary
            audit = os.path.join(carve_dir, "audit.txt")
            if os.path.exists(audit):
                sha = self._sha256(audit)
                result.add_artifact("foremost_audit.txt", audit,
                                     os.path.getsize(audit), sha)
                with open(audit) as f:
                    content = f.read()
                # Count recovered files
                total_match = re.search(r"Total\s+(\d+)", content)
                total = int(total_match.group(1)) if total_match else 0
                if total > 0:
                    result.add_finding(
                        severity="info", category="recovered_files",
                        title=f"{total} file(s) recovered via file carving",
                        detail="Files recovered from unallocated disk space. "
                               "These may include deleted documents, images, and archives.",
                        source="foremost", raw=f"Total recovered: {total}"
                    )

        result.success = (code == 0)
        result.summary = f"File carving {'complete' if code == 0 else 'failed'}: {len(result.findings)} findings."
        return result


# ─── osquery — Live System Interrogation ─────────────────────────────────────

OSQUERY_QUERIES = {
    "running_processes": (
        "SELECT pid, name, path, cmdline, start_time FROM processes ORDER BY start_time DESC LIMIT 100;",
        "low", "system_state", "Running process snapshot"
    ),
    "network_connections": (
        "SELECT pid, fd, socket, local_address, local_port, remote_address, remote_port, protocol "
        "FROM process_open_sockets WHERE remote_port != 0 LIMIT 100;",
        "low", "network_state", "Active network connections"
    ),
    "startup_items": (
        "SELECT name, path, status FROM startup_items;",
        "medium", "persistence", "Startup / persistence items"
    ),
    "crontabs": (
        "SELECT command, path FROM crontab;",
        "medium", "persistence", "Scheduled task entries"
    ),
    "installed_software": (
        "SELECT name, version, install_time FROM programs ORDER BY install_time DESC LIMIT 200;",
        "info", "inventory", "Installed software list"
    ),
    "open_files": (
        "SELECT pid, path FROM process_open_files WHERE path NOT LIKE '/dev/%' LIMIT 200;",
        "info", "system_state", "Files currently open by processes"
    ),
    "listening_ports": (
        "SELECT pid, port, protocol, address FROM listening_ports;",
        "low", "network_state", "Ports listening for connections"
    ),
    "launchd_overrides": (
        "SELECT label, disabled FROM launchd WHERE disabled = 0;",
        "medium", "persistence", "Active launchd services (macOS)"
    ),
}

# Suspicious process paths / names
SUSPICIOUS_PROCESS_INDICATORS = [
    ("/tmp/", "high",    "malware_indicator",  "Process running from /tmp/"),
    ("/var/tmp/", "high","malware_indicator",  "Process running from /var/tmp/"),
    ("nc ", "high",      "network_indicator",  "netcat detected — possible reverse shell"),
    ("ncat", "high",     "network_indicator",  "ncat detected — possible reverse shell"),
    ("socat", "medium",  "network_indicator",  "socat process detected"),
    ("cryptominer", "critical","malware_indicator","Possible cryptominer process"),
    ("kworker", "medium","malware_indicator",  "Suspicious kworker process (common rootkit disguise on Linux)"),
]


class OsQueryTool(BaseTool):
    """
    osquery wrapper for live system interrogation.
    Runs SQL queries against the live OS to capture forensic state.
    """
    tool_id   = "osquery"
    tool_name = "osquery"

    def run(self, output_dir: str, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "live_system_query")
        os.makedirs(output_dir, exist_ok=True)
        all_results = {}

        for query_name, (sql, severity, category, description) in OSQUERY_QUERIES.items():
            out_file = os.path.join(output_dir, f"osquery_{query_name}.json")
            cmd = ["osqueryi", "--json", sql]
            code, stdout, stderr, _ = self._run(cmd, timeout=30)

            if code == 0 and stdout.strip():
                try:
                    data = json.loads(stdout)
                    with open(out_file, "w") as f:
                        json.dump(data, f, indent=2)
                    sha = self._sha256(out_file)
                    result.add_artifact(
                        os.path.basename(out_file), out_file,
                        os.path.getsize(out_file), sha
                    )
                    all_results[query_name] = data

                    # Analyse process results for suspicious indicators
                    if query_name == "running_processes":
                        for proc in data:
                            path = proc.get("path", "")
                            cmdline = proc.get("cmdline", "")
                            combined = f"{path} {cmdline}"
                            for indicator, sev, cat, title in SUSPICIOUS_PROCESS_INDICATORS:
                                if indicator.lower() in combined.lower():
                                    result.add_finding(
                                        severity=sev, category=cat,
                                        title=title,
                                        detail=f"Process: {proc.get('name')} (PID {proc.get('pid')})",
                                        source="osquery_processes",
                                        raw=json.dumps(proc)[:200]
                                    )

                    elif query_name == "startup_items":
                        if len(data) > 20:
                            result.add_finding(
                                severity="medium", category="persistence",
                                title=f"Unusually high number of startup items ({len(data)})",
                                detail="A high number of startup items may indicate "
                                       "multiple persistence mechanisms.",
                                source="osquery_startup"
                            )
                except json.JSONDecodeError:
                    pass

        result.success = True
        result.summary = (
            f"Live system query: {len(all_results)} queries executed, "
            f"{len(result.findings)} indicators found."
        )
        return result


# ─── Integrity Hasher ─────────────────────────────────────────────────────────

class IntegrityHasher(BaseTool):
    """
    Chain of custody hashing.
    Creates SHA-256 hashes for all collected evidence files.
    """
    tool_id   = "sha256sum"
    tool_name = "Integrity Hashing"

    def run(self, output_dir: str, target_paths: list[str] = None, **kwargs) -> ToolResult:
        result = ToolResult(self.tool_id, "integrity_hashing")
        os.makedirs(output_dir, exist_ok=True)

        hash_manifest = []
        targets = target_paths or []

        # Also hash everything in output_dir itself
        for root, dirs, files in os.walk(output_dir):
            for fname in files:
                if fname == "hash_manifest.txt":
                    continue
                fpath = os.path.join(root, fname)
                targets.append(fpath)

        for fpath in set(targets):
            if not os.path.isfile(fpath):
                continue
            sha = self._sha256(fpath)
            size = os.path.getsize(fpath)
            hash_manifest.append({
                "file":   fpath,
                "sha256": sha,
                "size":   size,
                "timestamp": datetime.utcnow().isoformat(),
            })

        manifest_file = os.path.join(output_dir, "hash_manifest.txt")
        with open(manifest_file, "w") as f:
            f.write(f"# ZA Support Forensics — Evidence Integrity Manifest\n")
            f.write(f"# Generated: {datetime.utcnow().isoformat()} UTC\n\n")
            for entry in hash_manifest:
                f.write(f"{entry['sha256']}  {entry['file']}  "
                        f"({entry['size']} bytes)  {entry['timestamp']}\n")

        result.add_artifact(
            "hash_manifest.txt", manifest_file,
            os.path.getsize(manifest_file),
            self._sha256(manifest_file)
        )
        result.success = True
        result.summary = f"Integrity manifest created: {len(hash_manifest)} files hashed."
        return result


# ─── Tool Factory ─────────────────────────────────────────────────────────────

TOOL_MAP: dict[str, type[BaseTool]] = {
    "volatility3":     VolatilityTool,
    "sleuthkit":       SleuthKitTool,
    "yara":            YARATool,
    "strings":         StringsTool,
    "bulk_extractor":  BulkExtractorTool,
    "tshark":          TSharkTool,
    "foremost":        ForemostTool,
    "osquery":         OsQueryTool,
    "sha256sum":       IntegrityHasher,
}


def get_tool_instance(tool_id: str) -> Optional[BaseTool]:
    cls = TOOL_MAP.get(tool_id)
    return cls() if cls else None
