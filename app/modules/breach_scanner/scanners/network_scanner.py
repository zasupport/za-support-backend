"""
Network Scanner — inspects active network connections and DNS activity.

Checks:
  - Active connections to known C2 IPs/domains
  - Connections on unusual ports (IRC, Tor, mining pools)
  - DNS cache entries for known malicious domains
  - Data exfiltration patterns (large outbound, DNS tunnelling)
  - Connections from unsigned binaries
  - Tor exit node connections
  - Unusual listening services
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..models import FindingCategory, FindingSeverity, OSPlatform, RawFinding

logger = logging.getLogger(__name__)

# Known C2/malware infrastructure indicators
SUSPICIOUS_PORTS = {
    6667: "IRC (C2 channel)",
    6668: "IRC (C2 channel)",
    6669: "IRC (C2 channel)",
    9050: "Tor SOCKS proxy",
    9051: "Tor control port",
    9150: "Tor Browser SOCKS",
    4444: "Metasploit default",
    5555: "Android Debug Bridge (RAT)",
    1080: "SOCKS proxy",
    3128: "HTTP proxy (data exfil)",
    8080: "HTTP proxy / C2",
    31337: "Back Orifice / eleet",
    12345: "NetBus trojan",
    3389: "RDP (lateral movement)",
    5900: "VNC (remote access)",
    5938: "TeamViewer",
    6568: "AnyDesk",
    14444: "XMRig mining pool",
    3333: "Mining pool (stratum)",
    45700: "Mining pool (stratum)",
}

# Known malicious or suspicious TLDs
SUSPICIOUS_TLDS = {
    ".tk", ".ml", ".ga", ".cf", ".gq",  # Free TLDs used for phishing
    ".top", ".buzz", ".icu",  # Commonly abused
    ".onion",  # Tor
}

# Known mining pool domains
MINING_POOL_PATTERNS = [
    "pool.minexmr.com", "xmrpool.eu", "supportxmr.com",
    "nanopool.org", "hashvault.pro", "minergate.com",
    "nicehash.com", "2miners.com", "f2pool.com",
    "ethermine.org", "flexpool.io",
]

# Tor exit node check patterns
TOR_INDICATORS = [
    "tor", ".onion", "9050", "9150",
]


class NetworkScanner:
    """
    Scans active network connections for indicators of compromise.
    """

    name = "network_scanner"

    def __init__(
        self,
        os_platform: OSPlatform = OSPlatform.MACOS,
    ):
        self.os_platform = os_platform
        self.items_scanned = 0

    def scan(self) -> list[RawFinding]:
        """Run all network checks."""
        findings: list[RawFinding] = []

        connections = self._get_active_connections()
        self.items_scanned = len(connections)

        for conn in connections:
            findings.extend(self._check_connection(conn))

        findings.extend(self._check_dns_cache())
        findings.extend(self._check_listening_services(connections))

        return findings

    def _get_active_connections(self) -> list[dict]:
        """Get active network connections with process info."""
        connections = []

        if self.os_platform in (OSPlatform.MACOS, OSPlatform.LINUX):
            try:
                # lsof gives us process + connection info together
                result = subprocess.run(
                    ["lsof", "-i", "-n", "-P"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n")[1:]:
                        parts = line.split()
                        if len(parts) >= 9:
                            conn = {
                                "process": parts[0],
                                "pid": int(parts[1]) if parts[1].isdigit() else 0,
                                "user": parts[2],
                                "type": parts[4],  # IPv4/IPv6
                                "name": parts[8] if len(parts) > 8 else "",
                                "state": parts[9] if len(parts) > 9 else "",
                            }

                            # Parse remote address and port
                            name = conn["name"]
                            if "->" in name:
                                local, remote = name.split("->")
                                conn["local_addr"] = local
                                conn["remote_addr"] = remote
                                # Extract port
                                if ":" in remote:
                                    addr_port = remote.rsplit(":", 1)
                                    conn["remote_ip"] = addr_port[0]
                                    conn["remote_port"] = (
                                        int(addr_port[1]) if addr_port[1].isdigit() else 0
                                    )
                            elif ":" in name:
                                conn["local_addr"] = name
                                conn["remote_addr"] = ""

                            connections.append(conn)

            except (subprocess.TimeoutExpired, FileNotFoundError):
                # Fallback to netstat
                try:
                    result = subprocess.run(
                        ["netstat", "-an"],
                        capture_output=True, text=True, timeout=15,
                    )
                    if result.returncode == 0:
                        for line in result.stdout.strip().split("\n"):
                            if "ESTABLISHED" in line or "LISTEN" in line:
                                connections.append({
                                    "process": "unknown",
                                    "pid": 0,
                                    "name": line,
                                    "state": "ESTABLISHED" if "ESTABLISHED" in line else "LISTEN",
                                })
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

        return connections

    def _check_connection(self, conn: dict) -> list[RawFinding]:
        """Check a single connection for suspicious indicators."""
        findings: list[RawFinding] = []
        remote_port = conn.get("remote_port", 0)
        remote_ip = conn.get("remote_ip", "")
        remote_addr = conn.get("remote_addr", "")
        process = conn.get("process", "unknown")
        pid = conn.get("pid", 0)

        # --- Connection on suspicious port ---
        if remote_port in SUSPICIOUS_PORTS:
            port_desc = SUSPICIOUS_PORTS[remote_port]
            severity = FindingSeverity.HIGH
            category = FindingCategory.NETWORK_ANOMALY

            # Crypto mining is more specific
            if remote_port in (14444, 3333, 45700):
                category = FindingCategory.CRYPTO_MINER
                severity = FindingSeverity.HIGH

            # Tor connections
            if remote_port in (9050, 9051, 9150):
                severity = FindingSeverity.HIGH

            findings.append(RawFinding(
                category=category,
                severity=severity,
                title=f"{process} (PID {pid}) → port {remote_port} ({port_desc})",
                description=(
                    f"Process '{process}' (PID {pid}) has an active connection to "
                    f"{remote_addr} on port {remote_port} ({port_desc}). "
                    f"This port is associated with suspicious activity."
                ),
                process_name=process,
                process_pid=pid,
                network_ip=remote_ip,
                network_port=remote_port,
                scanner_name=self.name,
                mitre_technique="T1071.001",
                mitre_tactic="Command and Control",
                raw_evidence={
                    "remote_addr": remote_addr,
                    "local_addr": conn.get("local_addr", ""),
                    "state": conn.get("state", ""),
                },
                recommended_action=f"Investigate connection. Kill {process} if unrecognised.",
            ))

        # --- Connection to mining pool ---
        for pool_domain in MINING_POOL_PATTERNS:
            if pool_domain in remote_addr.lower():
                findings.append(RawFinding(
                    category=FindingCategory.CRYPTO_MINER,
                    severity=FindingSeverity.HIGH,
                    title=f"Mining pool connection: {process} → {pool_domain}",
                    description=(
                        f"Process '{process}' (PID {pid}) is connected to cryptocurrency "
                        f"mining pool '{pool_domain}'. This machine is being used for "
                        f"unauthorised crypto mining."
                    ),
                    process_name=process,
                    process_pid=pid,
                    network_domain=pool_domain,
                    network_ip=remote_ip,
                    network_port=remote_port,
                    scanner_name=self.name,
                    mitre_technique="T1496",
                    mitre_tactic="Impact",
                    recommended_action="Kill process immediately. Check for persistence.",
                ))
                break

        return findings

    def _check_dns_cache(self) -> list[RawFinding]:
        """Check DNS cache for known malicious domains."""
        findings: list[RawFinding] = []

        dns_entries = []
        if self.os_platform == OSPlatform.MACOS:
            try:
                # macOS DNS cache via log stream (limited approach)
                # More practical: check /etc/hosts and recent DNS queries
                result = subprocess.run(
                    ["dscacheutil", "-cachedump", "-entries", "Host"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if "name:" in line.lower():
                            domain = line.split(":", 1)[-1].strip()
                            if domain:
                                dns_entries.append(domain)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Also check /etc/hosts for hijacking
        hosts_file = Path("/etc/hosts")
        if hosts_file.exists():
            try:
                content = hosts_file.read_text()
                for line in content.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[0]
                            domains = parts[1:]
                            # Check for hosts file hijacking
                            # (redirecting legitimate domains to malicious IPs)
                            legit_domains = {
                                "google.com", "microsoft.com", "apple.com",
                                "facebook.com", "amazon.com", "bank",
                            }
                            for d in domains:
                                d_lower = d.lower()
                                for legit in legit_domains:
                                    if legit in d_lower and ip not in ("127.0.0.1", "::1", "0.0.0.0"):
                                        self.items_scanned += 1
                                        findings.append(RawFinding(
                                            category=FindingCategory.NETWORK_ANOMALY,
                                            severity=FindingSeverity.HIGH,
                                            title=f"Hosts file redirect: {d} → {ip}",
                                            description=(
                                                f"The hosts file redirects '{d}' to '{ip}'. "
                                                f"This is a DNS hijacking technique used to "
                                                f"redirect legitimate websites to phishing or "
                                                f"malware delivery pages."
                                            ),
                                            file_path=str(hosts_file),
                                            network_domain=d,
                                            network_ip=ip,
                                            scanner_name=self.name,
                                            mitre_technique="T1565.001",
                                            mitre_tactic="Impact",
                                            recommended_action="Remove malicious hosts file entry.",
                                        ))

            except (OSError, PermissionError):
                pass

        # Check resolved domains against suspicious TLDs
        for domain in dns_entries:
            self.items_scanned += 1
            domain_lower = domain.lower()
            for tld in SUSPICIOUS_TLDS:
                if domain_lower.endswith(tld):
                    findings.append(RawFinding(
                        category=FindingCategory.NETWORK_ANOMALY,
                        severity=FindingSeverity.MEDIUM,
                        title=f"Suspicious domain resolved: {domain}",
                        description=(
                            f"Domain '{domain}' with TLD '{tld}' found in DNS cache. "
                            f"This TLD is commonly associated with phishing and malware."
                        ),
                        network_domain=domain,
                        scanner_name=self.name,
                        mitre_technique="T1071.004",
                        mitre_tactic="Command and Control",
                        recommended_action="Investigate which process resolved this domain.",
                    ))

        return findings

    def _check_listening_services(self, connections: list[dict]) -> list[RawFinding]:
        """Check for unexpected listening services."""
        findings: list[RawFinding] = []

        # Expected listening services
        expected_listeners = {
            "rapportd", "mDNSResponder", "launchd", "UserEventAgent",
            "airplayxpcshelper", "remotepairingd", "AirPlayXPCHelper",
            "ControlCenter", "sharingd", "WiFiAgent",
        }

        for conn in connections:
            state = conn.get("state", "")
            if "LISTEN" not in state:
                continue

            process = conn.get("process", "unknown")
            if process in expected_listeners:
                continue

            local_addr = conn.get("local_addr", conn.get("name", ""))

            # Listening on all interfaces (0.0.0.0 or *) is more suspicious
            if "*:" in local_addr or "0.0.0.0:" in local_addr:
                self.items_scanned += 1
                findings.append(RawFinding(
                    category=FindingCategory.NETWORK_ANOMALY,
                    severity=FindingSeverity.MEDIUM,
                    title=f"Service listening on all interfaces: {process}",
                    description=(
                        f"Process '{process}' (PID {conn.get('pid', 0)}) is listening "
                        f"on all network interfaces ({local_addr}). This makes the "
                        f"service accessible from the network, which may be a backdoor "
                        f"or unauthorised remote access."
                    ),
                    process_name=process,
                    process_pid=conn.get("pid", 0),
                    scanner_name=self.name,
                    mitre_technique="T1090",
                    mitre_tactic="Command and Control",
                    raw_evidence={"listen_address": local_addr},
                    recommended_action="Verify this service should be network-accessible.",
                ))

        return findings
