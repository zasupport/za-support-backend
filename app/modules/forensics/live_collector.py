"""
Health Check v11 — Forensics Module
Collectors: Evidence acquisition in correct forensic order.
Order: volatile (RAM/processes/network) → semi-volatile → stable
"""

import hashlib
import json
import logging
import os
import platform
import subprocess
import time
from datetime import datetime

logger = logging.getLogger(__name__)


def _run(cmd: list, timeout: int = 60) -> tuple:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Not found: {cmd[0]}"
    except Exception as e:
        return -3, "", str(e)


def _sha256(filepath: str) -> str:
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


class QuickTriageCollector:
    """
    Captures volatile evidence from a live system in correct forensic order.
    All operations are read-only. Safe to run on a live system.
    
    Collection order (volatile first):
    1. Running processes
    2. Network connections + ARP
    3. Open files
    4. Logged-in users + login history
    5. Startup items / LaunchAgents / crontab
    6. Shell history
    7. System info + installed software
    8. DNS config
    9. Recently modified files
    """

    def collect(self, output_dir: str) -> dict:
        os.makedirs(output_dir, exist_ok=True)
        manifest = {
            "collection_start": datetime.utcnow().isoformat(),
            "collection_type":  "quick_triage",
            "os_platform":      platform.system(),
            "hostname":         platform.node(),
            "artifacts":        [],
            "errors":           [],
        }

        os_type = platform.system().lower()

        if os_type == "darwin":
            steps = self._macos_steps(output_dir)
        elif os_type == "linux":
            steps = self._linux_steps(output_dir)
        else:
            steps = self._windows_steps(output_dir)

        for step_name, cmd, out_file in steps:
            logger.info(f"[triage] {step_name}")
            code, stdout, stderr = _run(cmd, timeout=30)
            if stdout.strip():
                with open(out_file, "w") as f:
                    f.write(f"# {step_name}\n")
                    f.write(f"# Collected: {datetime.utcnow().isoformat()} UTC\n")
                    f.write(f"# Command: {' '.join(str(x) for x in cmd)}\n\n")
                    f.write(stdout)
                sha = _sha256(out_file)
                manifest["artifacts"].append({
                    "name":      step_name,
                    "filename":  os.path.basename(out_file),
                    "sha256":    sha,
                    "size":      os.path.getsize(out_file),
                    "collected": datetime.utcnow().isoformat(),
                })
            elif code != 0:
                manifest["errors"].append(f"{step_name}: {stderr[:200]}")

        manifest_file = os.path.join(output_dir, "triage_manifest.json")
        manifest["collection_end"] = datetime.utcnow().isoformat()
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)

        return manifest

    def _macos_steps(self, d: str) -> list:
        home = os.path.expanduser("~")
        return [
            ("Running Processes",        ["ps", "auxww"],
             os.path.join(d, "01_processes.txt")),
            ("Network Connections",      ["netstat", "-an"],
             os.path.join(d, "02_netstat.txt")),
            ("Network Interfaces",       ["ifconfig"],
             os.path.join(d, "02b_interfaces.txt")),
            ("ARP Table",                ["arp", "-a"],
             os.path.join(d, "02c_arp.txt")),
            ("Routing Table",            ["netstat", "-rn"],
             os.path.join(d, "02d_routes.txt")),
            ("Open Files",               ["lsof", "-n"],
             os.path.join(d, "03_open_files.txt")),
            ("Logged-in Users",          ["who"],
             os.path.join(d, "04_users.txt")),
            ("Login History",            ["last"],
             os.path.join(d, "04b_last_logins.txt")),
            ("LaunchD Services",         ["launchctl", "list"],
             os.path.join(d, "05_launchd.txt")),
            ("Crontab",                  ["crontab", "-l"],
             os.path.join(d, "05b_crontab.txt")),
            ("Zsh History",              ["cat", f"{home}/.zsh_history"],
             os.path.join(d, "06_zsh_history.txt")),
            ("Bash History",             ["cat", f"{home}/.bash_history"],
             os.path.join(d, "06b_bash_history.txt")),
            ("System Hardware Info",     ["system_profiler", "SPHardwareDataType"],
             os.path.join(d, "07_hardware.txt")),
            ("OS Version",               ["sw_vers"],
             os.path.join(d, "07b_osversion.txt")),
            ("Homebrew Packages",        ["brew", "list", "--versions"],
             os.path.join(d, "08_homebrew.txt")),
            ("DNS Configuration",        ["scutil", "--dns"],
             os.path.join(d, "09_dns.txt")),
            ("Recent Files (7 days)",    ["find", "/Users", "-mtime", "-7",
                                           "-type", "f", "-not", "-path", "*/.*",
                                           "-maxdepth", "6"],
             os.path.join(d, "10_recent_files.txt")),
            ("Firewall Status",          ["pfctl", "-sa"],
             os.path.join(d, "11_firewall.txt")),
            ("Loaded Kernel Extensions", ["kextstat"],
             os.path.join(d, "12_kextstat.txt")),
        ]

    def _linux_steps(self, d: str) -> list:
        home = os.path.expanduser("~")
        return [
            ("Running Processes",        ["ps", "auxf"],
             os.path.join(d, "01_processes.txt")),
            ("Network Connections",      ["ss", "-tulpn"],
             os.path.join(d, "02_netstat.txt")),
            ("Network Interfaces",       ["ip", "a"],
             os.path.join(d, "02b_interfaces.txt")),
            ("ARP Table",                ["arp", "-n"],
             os.path.join(d, "02c_arp.txt")),
            ("Routing Table",            ["ip", "route"],
             os.path.join(d, "02d_routes.txt")),
            ("Open Files",               ["lsof", "-n"],
             os.path.join(d, "03_open_files.txt")),
            ("Logged-in Users",          ["who"],
             os.path.join(d, "04_users.txt")),
            ("Login History",            ["last"],
             os.path.join(d, "04b_last_logins.txt")),
            ("Systemd Running Units",    ["systemctl", "list-units", "--state=running"],
             os.path.join(d, "05_systemd.txt")),
            ("Crontab",                  ["crontab", "-l"],
             os.path.join(d, "05b_crontab.txt")),
            ("Bash History",             ["cat", f"{home}/.bash_history"],
             os.path.join(d, "06_bash_history.txt")),
            ("OS Release",               ["cat", "/etc/os-release"],
             os.path.join(d, "07_osrelease.txt")),
            ("Uname",                    ["uname", "-a"],
             os.path.join(d, "07b_uname.txt")),
            ("Installed Packages (deb)", ["dpkg", "-l"],
             os.path.join(d, "08_dpkg.txt")),
            ("Installed Packages (rpm)", ["rpm", "-qa"],
             os.path.join(d, "08b_rpm.txt")),
            ("DNS Config",               ["cat", "/etc/resolv.conf"],
             os.path.join(d, "09_dns.txt")),
            ("Recent Files (7 days)",    ["find", "/home", "-mtime", "-7",
                                           "-type", "f", "-maxdepth", "6"],
             os.path.join(d, "10_recent_files.txt")),
            ("Auth Log",                 ["tail", "-n", "500", "/var/log/auth.log"],
             os.path.join(d, "11_auth_log.txt")),
            ("Syslog",                   ["tail", "-n", "500", "/var/log/syslog"],
             os.path.join(d, "12_syslog.txt")),
        ]

    def _windows_steps(self, d: str) -> list:
        return [
            ("Running Processes",        ["tasklist", "/v"],
             os.path.join(d, "01_processes.txt")),
            ("Network Connections",      ["netstat", "-ano"],
             os.path.join(d, "02_netstat.txt")),
            ("ARP Table",                ["arp", "-a"],
             os.path.join(d, "02c_arp.txt")),
            ("Logged-in Users",          ["query", "user"],
             os.path.join(d, "04_users.txt")),
            ("Startup Items",            ["wmic", "startup", "list", "full"],
             os.path.join(d, "05_startup.txt")),
            ("Scheduled Tasks",          ["schtasks", "/query", "/fo", "LIST"],
             os.path.join(d, "05b_schtasks.txt")),
            ("Services",                 ["sc", "query", "type=", "all"],
             os.path.join(d, "05c_services.txt")),
            ("System Info",              ["systeminfo"],
             os.path.join(d, "06_sysinfo.txt")),
            ("Installed Software",       ["wmic", "product", "get", "name,version"],
             os.path.join(d, "07_software.txt")),
            ("DNS Cache",                ["ipconfig", "/displaydns"],
             os.path.join(d, "08_dns.txt")),
            ("User Accounts",            ["net", "user"],
             os.path.join(d, "09_users.txt")),
            ("Local Admin Group",        ["net", "localgroup", "administrators"],
             os.path.join(d, "09b_admins.txt")),
        ]
