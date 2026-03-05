#!/bin/bash
# ============================================================
# Forensics Module — Tool Installation Script
# Health Check AI
# ============================================================
# Installs all open-source forensic tools supported by the module.
# Run as root or with sudo on the Health Check AI server.
#
# Usage:
#   chmod +x install_tools.sh
#   sudo ./install_tools.sh
#
# To install only a specific category:
#   sudo ./install_tools.sh memory
#   sudo ./install_tools.sh disk
#   sudo ./install_tools.sh network
#   sudo ./install_tools.sh malware
#   sudo ./install_tools.sh live
#   sudo ./install_tools.sh log
#   sudo ./install_tools.sh all (default)
# ============================================================

set -e

CATEGORY=${1:-all}
LOG_FILE="/var/log/healthcheck_forensics_install.log"

log() {
    echo "[$(date '+%d/%m/%Y %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

section() {
    echo ""
    echo "============================================================"
    log ">>> $1"
    echo "============================================================"
}

ok()   { log "  ✓ $1"; }
skip() { log "  - SKIP: $1"; }
warn() { log "  ⚠ WARN: $1"; }
fail() { log "  ✗ FAIL: $1"; }

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo "ERROR: This script must be run as root (sudo ./install_tools.sh)"
        exit 1
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
    elif command -v lsb_release >/dev/null 2>&1; then
        OS=$(lsb_release -si | tr '[:upper:]' '[:lower:]')
    else
        OS="unknown"
    fi
    log "Detected OS: $OS $OS_VERSION"
}

apt_update() {
    log "Updating package lists..."
    apt-get update -qq 2>&1 | tail -5
}

install_apt() {
    local pkg=$1
    if dpkg -l "$pkg" >/dev/null 2>&1; then
        ok "$pkg (already installed)"
    else
        apt-get install -y -qq "$pkg" >/dev/null 2>&1 && ok "$pkg" || warn "Failed to install $pkg"
    fi
}

install_pip() {
    local pkg=$1
    if pip3 show "$pkg" >/dev/null 2>&1; then
        ok "$pkg (pip, already installed)"
    else
        pip3 install -q "$pkg" >/dev/null 2>&1 && ok "$pkg (pip)" || warn "Failed to install pip:$pkg"
    fi
}

check_root
detect_os

log "Starting forensics tool installation — category: $CATEGORY"
log "Log file: $LOG_FILE"

# --------------------------------------------------------
# PREREQUISITES
# --------------------------------------------------------

section "Prerequisites"
apt_update
install_apt python3
install_apt python3-pip
install_apt python3-venv
install_apt git
install_apt curl
install_apt wget
install_apt unzip
install_apt build-essential
install_apt libssl-dev
install_apt libffi-dev
install_apt python3-dev

# --------------------------------------------------------
# MEMORY FORENSICS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "memory" ]]; then
    section "Memory Forensics Tools"

    # Volatility 3 — memory analysis framework
    if ! command -v vol >/dev/null 2>&1 && [ ! -d /opt/volatility3 ]; then
        log "Installing Volatility 3..."
        cd /opt
        git clone --depth 1 https://github.com/volatilityfoundation/volatility3.git >/dev/null 2>&1
        cd volatility3
        pip3 install -q -r requirements.txt >/dev/null 2>&1
        ln -sf /opt/volatility3/vol.py /usr/local/bin/vol
        chmod +x /opt/volatility3/vol.py
        ok "Volatility 3"
    else
        ok "Volatility 3 (already installed)"
    fi

    # WinPmem — Windows memory acquisition (binary available for cross-platform use)
    if [ ! -f /opt/winpmem/winpmem.exe ]; then
        log "Downloading WinPmem..."
        mkdir -p /opt/winpmem
        wget -q -O /opt/winpmem/winpmem.exe \
            https://github.com/Velocidex/WinPmem/releases/latest/download/winpmem_mini_x64_rc2.exe \
            2>/dev/null && ok "WinPmem (Windows agent)" || warn "WinPmem download failed (optional)"
    else
        ok "WinPmem (already present)"
    fi
fi

# --------------------------------------------------------
# DISK & FILE SYSTEM FORENSICS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "disk" ]]; then
    section "Disk & File System Forensics Tools"

    # Sleuth Kit — file system analysis
    install_apt sleuthkit

    # Foremost — file carving
    install_apt foremost

    # PhotoRec (part of testdisk) — file recovery
    install_apt testdisk

    # Bulk Extractor — structured data extraction
    install_apt bulk-extractor

    # dc3dd — forensic disk imaging
    install_apt dc3dd

    # dcfldd — enhanced dd with hashing
    install_apt dcfldd

    # ddrescue — disk imaging with error recovery
    install_apt gddrescue

    # safecopy — recovers data from damaged media
    install_apt safecopy || warn "safecopy not available in this repo (optional)"
fi

# --------------------------------------------------------
# TIMELINE ANALYSIS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "timeline" ]]; then
    section "Timeline Analysis Tools"

    # Plaso (log2timeline) — supertimeline generator
    if ! command -v log2timeline.py >/dev/null 2>&1; then
        log "Installing Plaso (log2timeline)..."
        pip3 install -q plaso 2>/dev/null && ok "Plaso (log2timeline)" || \
            warn "Plaso install failed — try: pip3 install plaso"
    else
        ok "Plaso (already installed)"
    fi
fi

# --------------------------------------------------------
# NETWORK FORENSICS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "network" ]]; then
    section "Network Forensics Tools"

    # TShark (Wireshark CLI) — packet analysis
    install_apt tshark

    # tcpdump — packet capture
    install_apt tcpdump

    # nmap — network scanning
    install_apt nmap

    # Zeek (formerly Bro) — network analysis framework
    if ! command -v zeek >/dev/null 2>&1; then
        log "Adding Zeek repository..."
        echo 'deb http://download.opensuse.org/repositories/security:/zeek/xUbuntu_22.04/ /' \
            > /etc/apt/sources.list.d/security:zeek.list 2>/dev/null || true
        curl -fsSL https://download.opensuse.org/repositories/security:/zeek/xUbuntu_22.04/Release.key \
            | gpg --dearmor > /etc/apt/trusted.gpg.d/security_zeek.gpg 2>/dev/null || true
        apt-get update -qq 2>/dev/null || true
        install_apt zeek || warn "Zeek install failed — add repo manually for your distro"
    else
        ok "Zeek (already installed)"
    fi

    # NetworkMiner — Linux-compatible via Mono (optional)
    warn "NetworkMiner requires Mono on Linux — skip if not needed"
fi

# --------------------------------------------------------
# MALWARE ANALYSIS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "malware" ]]; then
    section "Malware Analysis Tools"

    # YARA — pattern matching engine
    install_apt yara
    install_pip yara-python

    # ClamAV — open-source antivirus
    install_apt clamav
    install_apt clamav-daemon
    log "Updating ClamAV signatures..."
    freshclam --quiet 2>/dev/null || warn "freshclam update failed (network issue?)"
    ok "ClamAV signatures updated"

    # strings — extract printable strings
    install_apt binutils

    # Binwalk — firmware analysis and extraction
    install_pip binwalk

    # ssdeep — fuzzy hashing for similarity
    install_apt ssdeep
    install_pip ssdeep

    # pefile — Windows PE analysis
    install_pip pefile

    # python-magic — file type detection
    install_apt libmagic1
    install_pip python-magic

    # exiftool — metadata extraction
    install_apt libimage-exiftool-perl
fi

# --------------------------------------------------------
# LOG ANALYSIS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "log" ]]; then
    section "Log Analysis Tools"

    # Chainsaw — Windows event log analysis
    if ! command -v chainsaw >/dev/null 2>&1; then
        log "Installing Chainsaw..."
        CHAINSAW_VERSION=$(curl -s https://api.github.com/repos/WithSecureLabs/chainsaw/releases/latest \
            | grep '"tag_name"' | cut -d'"' -f4 2>/dev/null || echo "v2.8.1")
        mkdir -p /opt/chainsaw
        wget -q -O /tmp/chainsaw.tar.gz \
            "https://github.com/WithSecureLabs/chainsaw/releases/download/${CHAINSAW_VERSION}/chainsaw_x86_64-unknown-linux-musl.tar.gz" \
            2>/dev/null && \
            tar -xzf /tmp/chainsaw.tar.gz -C /opt/chainsaw --strip-components=1 >/dev/null 2>&1 && \
            ln -sf /opt/chainsaw/chainsaw /usr/local/bin/chainsaw && \
            ok "Chainsaw $CHAINSAW_VERSION" || warn "Chainsaw install failed (optional for Windows log analysis)"
    else
        ok "Chainsaw (already installed)"
    fi

    # evtx_dump — Windows Event Log parser (Python)
    install_pip python-evtx

    # loki — IoC scanner
    if [ ! -d /opt/loki ]; then
        log "Installing Loki IoC scanner..."
        cd /opt
        git clone --depth 1 https://github.com/Neo23x0/Loki.git loki >/dev/null 2>&1 && \
            cd loki && pip3 install -q -r requirements.txt >/dev/null 2>&1 && \
            ok "Loki IoC scanner" || warn "Loki install failed (optional)"
    else
        ok "Loki (already installed)"
    fi
fi

# --------------------------------------------------------
# LIVE SYSTEM INTERROGATION
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "live" ]]; then
    section "Live System Interrogation Tools"

    # osquery — SQL-based system interrogation
    if ! command -v osqueryi >/dev/null 2>&1; then
        log "Installing osquery..."
        export OSQUERY_KEY=1484120AC4E9F8A1A577AEEE97A80C63C9D8B80B
        gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys $OSQUERY_KEY >/dev/null 2>&1 || true
        gpg --export --armor $OSQUERY_KEY | apt-key add - >/dev/null 2>&1 || true
        add-apt-repository "deb [arch=amd64] https://pkg.osquery.io/deb deb main" >/dev/null 2>&1 || true
        apt-get update -qq >/dev/null 2>&1
        install_apt osquery
    else
        ok "osquery (already installed)"
    fi

    # Velociraptor — live forensics and threat hunting
    if ! command -v velociraptor >/dev/null 2>&1; then
        log "Installing Velociraptor..."
        VR_VERSION=$(curl -s https://api.github.com/repos/Velocidex/velociraptor/releases/latest \
            | grep '"tag_name"' | cut -d'"' -f4 2>/dev/null || echo "v0.72.0")
        wget -q -O /usr/local/bin/velociraptor \
            "https://github.com/Velocidex/velociraptor/releases/download/${VR_VERSION}/velociraptor-${VR_VERSION}-linux-amd64" \
            2>/dev/null && \
            chmod +x /usr/local/bin/velociraptor && \
            ok "Velociraptor $VR_VERSION" || warn "Velociraptor install failed (optional)"
    else
        ok "Velociraptor (already installed)"
    fi

    # artifactcollector
    install_pip artifactcollector || warn "artifactcollector install optional"
fi

# --------------------------------------------------------
# REGISTRY ANALYSIS (Windows artifacts)
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "registry" ]]; then
    section "Registry & Artifact Analysis Tools"

    # regipy — Python registry parser
    install_pip regipy

    # python-registry
    install_pip python-registry || warn "python-registry optional"

    # RegRipper — comprehensive registry parser
    if ! command -v rip.pl >/dev/null 2>&1; then
        install_apt libparse-win32registry-perl || true
        if [ ! -d /opt/regripper ]; then
            cd /opt
            git clone --depth 1 https://github.com/keydet89/RegRipper3.0.git regripper >/dev/null 2>&1 && \
                chmod +x /opt/regripper/rip.pl && \
                ln -sf /opt/regripper/rip.pl /usr/local/bin/rip.pl && \
                ok "RegRipper" || warn "RegRipper install failed (optional for Windows registry)"
        else
            ok "RegRipper (already installed)"
        fi
    else
        ok "RegRipper (already installed)"
    fi
fi

# --------------------------------------------------------
# macOS ARTIFACT ANALYSIS
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "macos" ]]; then
    section "macOS Artifact Analysis Tools"

    # mac_apt — macOS artifacts parser
    if [ ! -d /opt/mac_apt ]; then
        cd /opt
        git clone --depth 1 https://github.com/ydkhatri/mac_apt.git >/dev/null 2>&1 && \
            cd mac_apt && pip3 install -q -r requirements.txt >/dev/null 2>&1 && \
            ok "mac_apt" || warn "mac_apt install failed (optional, macOS artifacts only)"
    else
        ok "mac_apt (already installed)"
    fi

    # OSXCollector
    if [ ! -d /opt/osxcollector ]; then
        cd /opt
        git clone --depth 1 https://github.com/Yelp/osxcollector.git >/dev/null 2>&1 && \
            ok "OSXCollector" || warn "OSXCollector install failed (optional)"
    else
        ok "OSXCollector (already installed)"
    fi
fi

# --------------------------------------------------------
# INTEGRITY & HASHING
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" || "$CATEGORY" == "hash" ]]; then
    section "Integrity & Hashing Tools"

    install_apt coreutils       # sha256sum, md5sum, sha512sum
    install_apt hashdeep        # recursive hashing and hash matching
    install_apt rhash           # multi-algorithm hashing
fi

# --------------------------------------------------------
# PYTHON FORENSICS LIBRARIES
# --------------------------------------------------------

if [[ "$CATEGORY" == "all" ]]; then
    section "Python Forensics Libraries"

    install_pip dfvfs            # Digital Forensics Virtual File System
    install_pip libscca-python   # Windows Prefetch parser
    install_pip liblnk-python    # Windows LNK/shortcut parser
    install_pip libregf-python   # Windows Registry parser
    install_pip libevtx-python   # Windows Event Log parser
    install_pip pytsk3           # Sleuth Kit Python bindings
    install_pip construct        # Binary data structure parser
    install_pip hexdump           # Hex dump utility
fi

# --------------------------------------------------------
# SUMMARY
# --------------------------------------------------------

section "Installation Complete"

echo ""
echo "Tool availability summary:"
echo ""

tools=(
    "vol:Volatility 3"
    "tsk_loaddb:Sleuth Kit"
    "foremost:Foremost"
    "bulk_extractor:Bulk Extractor"
    "tshark:TShark"
    "nmap:Nmap"
    "yara:YARA"
    "clamscan:ClamAV"
    "osqueryi:osquery"
    "velociraptor:Velociraptor"
    "chainsaw:Chainsaw"
    "rip.pl:RegRipper"
    "zeek:Zeek"
    "log2timeline.py:Plaso"
    "sha256sum:sha256sum"
    "hashdeep:hashdeep"
)

installed=0
missing=0

for entry in "${tools[@]}"; do
    bin="${entry%%:*}"
    name="${entry##*:}"
    if command -v "$bin" >/dev/null 2>&1; then
        echo "  ✓ $name"
        ((installed++))
    else
        echo "  ✗ $name (not installed)"
        ((missing++))
    fi
done

echo ""
echo "  Installed: $installed / $((installed + missing)) tools"
echo ""

if [ "$missing" -gt 0 ]; then
    echo "  Some tools are not installed. The module will still work with"
    echo "  the tools that ARE installed. To install missing tools, re-run"
    echo "  this script or install them manually."
    echo ""
fi

log "Installation complete. See $LOG_FILE for full log."
