"""
Health Check v11 — Forensics Module
Tool Registry: Detects and manages available forensic tools.
All tools are optional. The module gracefully degrades when tools are absent.
"""

import shutil
import subprocess
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    MEMORY       = "memory_forensics"
    DISK         = "disk_forensics"
    NETWORK      = "network_forensics"
    MALWARE      = "malware_analysis"
    TIMELINE     = "timeline_analysis"
    LOG_ANALYSIS = "log_analysis"
    ARTIFACTS    = "artifact_collection"
    HASHING      = "integrity_hashing"
    REGISTRY     = "registry_analysis"
    MACOS        = "macos_specific"


@dataclass
class ForensicTool:
    id: str
    name: str
    description: str
    category: ToolCategory
    binary: str                        # executable name to check with shutil.which
    install_cmd: str                   # how to install if missing
    version_flag: str = "--version"
    min_version: Optional[str] = None
    python_package: Optional[str] = None  # pip package if applicable
    is_available: bool = False
    version: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        return d


# ─── Master Tool Catalogue ────────────────────────────────────────────────────
TOOL_CATALOGUE: list[ForensicTool] = [

    # ── Memory Forensics ──────────────────────────────────────────────────────
    ForensicTool(
        id="volatility3",
        name="Volatility 3",
        description="Memory forensics framework — analyses RAM dumps for running processes, "
                    "network connections, injected code, rootkits, and credential artefacts.",
        category=ToolCategory.MEMORY,
        binary="vol",
        install_cmd="pip install volatility3",
        version_flag="-h",
        python_package="volatility3",
    ),
    ForensicTool(
        id="winpmem",
        name="WinPmem",
        description="Windows physical memory acquisition tool. Creates raw memory images "
                    "for offline analysis with Volatility.",
        category=ToolCategory.MEMORY,
        binary="winpmem",
        install_cmd="Download from https://github.com/Velocidex/WinPmem/releases",
        version_flag="--version",
    ),

    # ── Disk Forensics ────────────────────────────────────────────────────────
    ForensicTool(
        id="sleuthkit",
        name="The Sleuth Kit (TSK)",
        description="Command-line toolkit for analysing disk images and file systems "
                    "(NTFS, FAT, HFS+, Ext2/3/4). Extracts deleted files, metadata, and timelines.",
        category=ToolCategory.DISK,
        binary="fls",
        install_cmd="brew install sleuthkit  (macOS)  |  apt install sleuthkit  (Linux)",
        version_flag="-V",
    ),
    ForensicTool(
        id="foremost",
        name="Foremost",
        description="File carving tool — recovers files from disk images based on file headers, "
                    "footers, and internal data structures. Works on fragmented or damaged media.",
        category=ToolCategory.DISK,
        binary="foremost",
        install_cmd="brew install foremost  (macOS)  |  apt install foremost  (Linux)",
        version_flag="-V",
    ),
    ForensicTool(
        id="photorec",
        name="PhotoRec (TestDisk)",
        description="File data recovery tool. Recovers lost files from hard disks, CD-ROMs, "
                    "and digital camera memory. Ignores the file system and goes after raw data.",
        category=ToolCategory.DISK,
        binary="photorec",
        install_cmd="brew install testdisk  (macOS)  |  apt install testdisk  (Linux)",
        version_flag="/help",
    ),
    ForensicTool(
        id="bulk_extractor",
        name="Bulk Extractor",
        description="Extracts features (email addresses, URLs, credit card numbers, GPS data) "
                    "from disk images without parsing the file system.",
        category=ToolCategory.DISK,
        binary="bulk_extractor",
        install_cmd="brew install bulk_extractor  |  apt install bulk-extractor",
        version_flag="-V",
    ),
    ForensicTool(
        id="dc3dd",
        name="dc3dd",
        description="Patched version of GNU dd with forensic features — hashing, split output, "
                    "progress reporting, and error logging during disk imaging.",
        category=ToolCategory.DISK,
        binary="dc3dd",
        install_cmd="brew install dc3dd  |  apt install dc3dd",
        version_flag="--version",
    ),

    # ── Timeline Analysis ─────────────────────────────────────────────────────
    ForensicTool(
        id="plaso",
        name="log2timeline / Plaso",
        description="Super-timeline generator. Parses artefacts from disk images, log files, "
                    "registries, and browser history into a unified chronological timeline.",
        category=ToolCategory.TIMELINE,
        binary="log2timeline.py",
        install_cmd="pip install plaso",
        python_package="plaso",
    ),
    ForensicTool(
        id="mactime",
        name="mactime (TSK)",
        description="Creates a timeline of file system activity from TSK body files. "
                    "Part of The Sleuth Kit toolset.",
        category=ToolCategory.TIMELINE,
        binary="mactime",
        install_cmd="Included with sleuthkit installation",
        version_flag="-V",
    ),

    # ── Network Forensics ─────────────────────────────────────────────────────
    ForensicTool(
        id="tshark",
        name="TShark (Wireshark CLI)",
        description="Command-line network protocol analyser. Captures and analyses network "
                    "packets. Decodes hundreds of protocols.",
        category=ToolCategory.NETWORK,
        binary="tshark",
        install_cmd="brew install wireshark  |  apt install tshark",
        version_flag="--version",
    ),
    ForensicTool(
        id="nmap",
        name="Nmap",
        description="Network discovery and security auditing. Maps open ports, services, "
                    "and operating systems on a network.",
        category=ToolCategory.NETWORK,
        binary="nmap",
        install_cmd="brew install nmap  |  apt install nmap",
        version_flag="--version",
    ),
    ForensicTool(
        id="tcpdump",
        name="tcpdump",
        description="Packet capture and analysis from the command line. Useful for capturing "
                    "live network traffic during an incident.",
        category=ToolCategory.NETWORK,
        binary="tcpdump",
        install_cmd="brew install tcpdump  |  apt install tcpdump",
        version_flag="--version",
    ),
    ForensicTool(
        id="zeek",
        name="Zeek (formerly Bro)",
        description="Network analysis framework that creates structured logs from packet captures. "
                    "Identifies connections, files transferred, and protocol behaviour.",
        category=ToolCategory.NETWORK,
        binary="zeek",
        install_cmd="brew install zeek  |  apt install zeek",
        version_flag="--version",
    ),

    # ── Malware Analysis ──────────────────────────────────────────────────────
    ForensicTool(
        id="yara",
        name="YARA",
        description="Pattern-matching tool for malware identification. Scans files and memory "
                    "for known malicious patterns using YARA rule sets.",
        category=ToolCategory.MALWARE,
        binary="yara",
        install_cmd="brew install yara  |  apt install yara  |  pip install yara-python",
        version_flag="--version",
        python_package="yara-python",
    ),
    ForensicTool(
        id="clamav",
        name="ClamAV",
        description="Open-source antivirus engine. Scans files for malware signatures. "
                    "Includes freshclam for database updates.",
        category=ToolCategory.MALWARE,
        binary="clamscan",
        install_cmd="brew install clamav  |  apt install clamav",
        version_flag="--version",
    ),
    ForensicTool(
        id="strings",
        name="strings",
        description="Extracts printable strings from binary files. Useful for identifying "
                    "hardcoded URLs, credentials, and C2 indicators in suspected malware.",
        category=ToolCategory.MALWARE,
        binary="strings",
        install_cmd="Typically pre-installed on macOS and Linux",
        version_flag="--version",
    ),
    ForensicTool(
        id="binwalk",
        name="Binwalk",
        description="Firmware analysis and extraction tool. Identifies embedded file systems, "
                    "executable code, and compressed data within binary files.",
        category=ToolCategory.MALWARE,
        binary="binwalk",
        install_cmd="pip install binwalk  |  apt install binwalk",
        version_flag="--version",
        python_package="binwalk",
    ),
    ForensicTool(
        id="ssdeep",
        name="ssdeep",
        description="Fuzzy hashing (context-triggered piecewise hashing). Compares files for "
                    "similarity even when partially modified — useful for malware variant detection.",
        category=ToolCategory.MALWARE,
        binary="ssdeep",
        install_cmd="brew install ssdeep  |  apt install ssdeep",
        version_flag="-V",
    ),

    # ── Log Analysis ──────────────────────────────────────────────────────────
    ForensicTool(
        id="chainsaw",
        name="Chainsaw",
        description="Fast Windows event log parser. Searches for threat indicators using "
                    "SIGMA rules. Identifies lateral movement, credential theft, and more.",
        category=ToolCategory.LOG_ANALYSIS,
        binary="chainsaw",
        install_cmd="Download from https://github.com/WithSecureLabs/chainsaw/releases",
        version_flag="--version",
    ),
    ForensicTool(
        id="evtx_dump",
        name="evtx_dump (python-evtx)",
        description="Parses Windows Event Log (.evtx) files into XML or JSON for analysis.",
        category=ToolCategory.LOG_ANALYSIS,
        binary="evtx_dump",
        install_cmd="pip install python-evtx",
        python_package="python-evtx",
    ),

    # ── Integrity Hashing ─────────────────────────────────────────────────────
    ForensicTool(
        id="sha256sum",
        name="sha256sum",
        description="Cryptographic hash verification. Creates and verifies SHA-256 hash values "
                    "to prove evidence integrity (chain of custody requirement).",
        category=ToolCategory.HASHING,
        binary="sha256sum",
        install_cmd="Pre-installed on Linux. macOS: use 'shasum -a 256'",
        version_flag="--version",
    ),
    ForensicTool(
        id="md5sum",
        name="md5sum",
        description="MD5 hash generation for legacy compatibility with older forensic tools "
                    "that require MD5 checksums alongside SHA-256.",
        category=ToolCategory.HASHING,
        binary="md5sum",
        install_cmd="Pre-installed on Linux. macOS uses 'md5'",
        version_flag="--version",
    ),

    # ── Registry Analysis ─────────────────────────────────────────────────────
    ForensicTool(
        id="regripper",
        name="RegRipper",
        description="Windows Registry analysis tool. Extracts and parses key forensic "
                    "artefacts from Registry hives (installed programs, USB history, recent files).",
        category=ToolCategory.REGISTRY,
        binary="rip.pl",
        install_cmd="Download from https://github.com/keydet89/RegRipper3.0",
        version_flag="-h",
    ),
    ForensicTool(
        id="regipy",
        name="regipy",
        description="Python library and CLI for Windows Registry hive parsing. "
                    "Supports offline analysis of Registry files.",
        category=ToolCategory.REGISTRY,
        binary="regipy",
        install_cmd="pip install regipy",
        python_package="regipy",
    ),
    ForensicTool(
        id="parseusbss",
        name="ParseUSBs",
        description="Extracts USB connection artefacts from Windows Registry hives and "
                    "Event Logs. Tracks external device usage history.",
        category=ToolCategory.REGISTRY,
        binary="parseusbss",
        install_cmd="pip install ParseUSBs  |  https://github.com/woanware/parseusbss",
        python_package="parseusbss",
    ),

    # ── macOS Specific ────────────────────────────────────────────────────────
    ForensicTool(
        id="mac_apt",
        name="mac_apt (macOS Artifact Parsing Tool)",
        description="Extracts forensic artefacts from macOS disk images or live systems. "
                    "Covers Safari history, Spotlight, user accounts, installed apps, and more.",
        category=ToolCategory.MACOS,
        binary="mac_apt.py",
        install_cmd="pip install mac_apt  |  https://github.com/ydkhatri/mac_apt",
        python_package="mac_apt",
    ),
    ForensicTool(
        id="osxcollector",
        name="OSXCollector",
        description="Forensic collection tool for macOS. Gathers system information, "
                    "browser history, installed software, and running processes.",
        category=ToolCategory.MACOS,
        binary="osxcollector.py",
        install_cmd="pip install osxcollector  |  https://github.com/Yelp/osxcollector",
        python_package="osxcollector",
    ),
    ForensicTool(
        id="knockknock",
        name="KnockKnock",
        description="Displays persistent macOS artefacts (items set to run at login/startup). "
                    "Identifies persistence mechanisms used by malware.",
        category=ToolCategory.MACOS,
        binary="KnockKnock.app",
        install_cmd="Download from https://objective-see.org/products/knockknock.html",
        version_flag="",
    ),

    # ── Artifact Collection Frameworks ────────────────────────────────────────
    ForensicTool(
        id="velociraptor",
        name="Velociraptor",
        description="Advanced DFIR platform. Collects forensic artefacts at scale via "
                    "VQL queries. Supports live response, triage collection, and hunting.",
        category=ToolCategory.ARTIFACTS,
        binary="velociraptor",
        install_cmd="Download from https://github.com/Velocidex/velociraptor/releases",
        version_flag="version",
    ),
    ForensicTool(
        id="osquery",
        name="osquery",
        description="Exposes the OS as a relational database. Query running processes, "
                    "open files, network connections, and more using SQL syntax.",
        category=ToolCategory.ARTIFACTS,
        binary="osqueryi",
        install_cmd="brew install osquery  |  https://osquery.io/downloads",
        version_flag="--version",
    ),
    ForensicTool(
        id="artifactcollector",
        name="artifactcollector",
        description="Customisable agent to collect forensic artefacts on Windows, macOS, "
                    "and Linux. Defined by ForensicArtifacts YAML specifications.",
        category=ToolCategory.ARTIFACTS,
        binary="artifactcollector",
        install_cmd="Download from https://github.com/forensicanalysis/artifactcollector",
        version_flag="--version",
    ),
]


# ─── Registry Functions ───────────────────────────────────────────────────────

def check_tool_availability(tool: ForensicTool) -> ForensicTool:
    """Check if a single tool binary is available on this system."""
    binary_path = shutil.which(tool.binary)
    if binary_path:
        tool.is_available = True
        # Try to get version
        try:
            result = subprocess.run(
                [tool.binary, tool.version_flag],
                capture_output=True, text=True, timeout=5
            )
            raw = (result.stdout + result.stderr).strip().split("\n")[0]
            tool.version = raw[:80] if raw else "installed"
        except Exception:
            tool.version = "installed (version unknown)"
    else:
        tool.is_available = False
    return tool


def scan_all_tools() -> list[ForensicTool]:
    """Scan system for all tools in the catalogue. Returns updated catalogue."""
    updated = []
    for tool in TOOL_CATALOGUE:
        updated.append(check_tool_availability(tool))
        logger.debug(f"[forensics] {tool.name}: {'✓' if tool.is_available else '✗'}")
    return updated


def get_available_tools() -> list[ForensicTool]:
    return [t for t in scan_all_tools() if t.is_available]


def get_missing_tools() -> list[ForensicTool]:
    return [t for t in scan_all_tools() if not t.is_available]


def get_tools_by_category(category: ToolCategory) -> list[ForensicTool]:
    return [t for t in TOOL_CATALOGUE if t.category == category]


def get_tool(tool_id: str) -> Optional[ForensicTool]:
    return next((t for t in TOOL_CATALOGUE if t.id == tool_id), None)


def registry_summary() -> dict:
    """Returns a summary dict for the API health endpoint."""
    tools = scan_all_tools()
    available = [t for t in tools if t.is_available]
    missing = [t for t in tools if not t.is_available]
    by_category = {}
    for cat in ToolCategory:
        cat_tools = [t for t in tools if t.category == cat]
        by_category[cat.value] = {
            "total": len(cat_tools),
            "available": len([t for t in cat_tools if t.is_available]),
            "tools": [t.to_dict() for t in cat_tools],
        }
    return {
        "total_tools": len(tools),
        "available": len(available),
        "missing": len(missing),
        "coverage_pct": round(len(available) / len(tools) * 100, 1) if tools else 0,
        "by_category": by_category,
    }
