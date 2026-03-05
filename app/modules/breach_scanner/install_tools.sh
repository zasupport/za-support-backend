#!/usr/bin/env bash
# =============================================================================
# Breach Scanner — Complete Dependency Installer
# Health Check AI Module
# ZA Support | admin@zasupport.com | 064 529 5863
# =============================================================================
set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_header()  { echo -e "\n${CYAN}${BOLD}═══ $1 ═══${NC}\n"; }
INSTALLED=0; SKIPPED=0; FAILED=0; WARNINGS=0
track_install() { ((INSTALLED++)) || true; }
track_skip()    { ((SKIPPED++)) || true; }
track_fail()    { ((FAILED++)) || true; log_error "$1"; }
track_warn()    { ((WARNINGS++)) || true; log_warn "$1"; }

detect_os() {
    if [[ "$OSTYPE" == "darwin"* ]]; then OS="macos"
    elif [ -f /etc/debian_version ]; then OS="debian"
    elif [ -f /etc/alpine-release ]; then OS="alpine"
    elif [ -f /etc/redhat-release ]; then OS="rhel"
    else OS="unknown"; fi
    log_info "Detected OS: ${BOLD}${OS}${NC}"
}

MODE="${1:-auto}"
detect_mode() {
    case "$MODE" in
        --server) MODE="server" ;;
        --agent)  MODE="agent" ;;
        --check)  MODE="check" ;;
        auto)
            if command -v psql &>/dev/null; then MODE="server"
            else MODE="agent"; fi ;;
    esac
    log_info "Mode: ${BOLD}${MODE}${NC}"
}

install_macos_homebrew() {
    if ! command -v brew &>/dev/null; then
        log_info "Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
        track_install
    else track_skip; log_success "Homebrew present"; fi
}

install_brew_pkg() {
    if brew list "$1" &>/dev/null; then track_skip
    else
        log_info "Installing $1..."
        brew install "$1" 2>/dev/null && track_install && log_success "$1 installed" || track_fail "$1 failed"
    fi
}

install_macos_deps() {
    log_header "macOS Dependencies (Homebrew)"
    install_macos_homebrew
    for pkg in python@3.12 yara libmagic ssdeep openssl@3 jq curl; do install_brew_pkg "$pkg"; done
    if [[ "$MODE" == "server" ]]; then
        log_header "Server Dependencies"
        for pkg in postgresql@16 redis libpq; do install_brew_pkg "$pkg"; done
        brew services list | grep postgresql | grep -q started || brew services start postgresql@16 2>/dev/null || true
        brew services list | grep redis | grep -q started || brew services start redis 2>/dev/null || true
    fi
}

install_debian_deps() {
    log_header "Debian/Ubuntu Dependencies (apt)"
    export DEBIAN_FRONTEND=noninteractive
    sudo apt-get update -qq
    local pkgs=(python3 python3-pip python3-venv python3-dev build-essential libyara-dev yara libmagic1 libmagic-dev libfuzzy-dev ssdeep libssl-dev openssl curl wget jq git)
    [[ "$MODE" == "server" ]] && pkgs+=(postgresql-client libpq-dev redis-tools)
    for pkg in "${pkgs[@]}"; do
        dpkg -s "$pkg" &>/dev/null && track_skip || { sudo apt-get install -y -qq "$pkg" 2>/dev/null && track_install && log_success "$pkg" || track_fail "$pkg"; }
    done
}

install_alpine_deps() {
    log_header "Alpine Dependencies (apk)"
    apk update
    local pkgs=(python3 py3-pip python3-dev build-base yara yara-dev file libmagic ssdeep openssl curl jq git)
    [[ "$MODE" == "server" ]] && pkgs+=(postgresql-client postgresql-dev redis)
    for pkg in "${pkgs[@]}"; do
        apk info -e "$pkg" &>/dev/null && track_skip || { apk add --no-cache "$pkg" 2>/dev/null && track_install || track_warn "$pkg unavailable"; }
    done
}

install_rhel_deps() {
    log_header "RHEL/CentOS Dependencies"
    local PM="dnf"; command -v dnf &>/dev/null || PM="yum"
    sudo $PM install -y epel-release 2>/dev/null || true
    local pkgs=(python3 python3-pip python3-devel gcc gcc-c++ make yara yara-devel file-libs ssdeep openssl curl jq git)
    [[ "$MODE" == "server" ]] && pkgs+=(postgresql postgresql-devel redis)
    for pkg in "${pkgs[@]}"; do
        rpm -q "$pkg" &>/dev/null && track_skip || { sudo $PM install -y "$pkg" 2>/dev/null && track_install || track_warn "$pkg unavailable"; }
    done
}

install_python_deps() {
    log_header "Python Dependencies (pip)"
    local SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local PIP="pip3"; command -v pip3 &>/dev/null || PIP="python3 -m pip"
    local REQ="$SCRIPT_DIR/requirements-agent.txt"
    [[ "$MODE" == "server" ]] && REQ="$SCRIPT_DIR/requirements.txt"
    [[ ! -f "$REQ" ]] && { track_fail "Missing $REQ"; return 1; }
    local BRK=""; $PIP install --help 2>/dev/null | grep -q "break-system-packages" && BRK="--break-system-packages"
    $PIP install $BRK -r "$REQ" 2>&1 | tail -3 && track_install && log_success "Python deps installed" || track_fail "Python deps failed"
}

create_yara_rules() {
    log_header "YARA Rules — Foundational Signatures"
    local SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local RD="${SCRIPT_DIR}/yara_rules"; mkdir -p "$RD"

    cat > "$RD/eicar_test.yar" << 'YR'
rule EICAR_Test_File { meta: description="EICAR test" severity="info" strings: $e="X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*" condition: $e at 0 }
YR

    cat > "$RD/vba_macros.yar" << 'YR'
rule Suspicious_VBA_Macro { meta: description="Suspicious VBA macro" severity="high" mitre="T1204.002"
  strings: $ao="Auto_Open" nocase $do="Document_Open" nocase $wo="Workbook_Open" nocase
    $sh="Shell(" nocase $ws="WScript.Shell" nocase $ps="powershell" nocase $cm="cmd.exe" nocase
    $dl="URLDownloadToFile" nocase $xh="XMLHTTP" nocase $co="CreateObject" nocase
  condition: any of ($ao,$do,$wo) and 2 of ($sh,$ws,$ps,$cm,$dl,$xh,$co) }
rule VBA_Obfuscation { meta: description="Obfuscated VBA" severity="critical" mitre="T1027"
  strings: $chr=/Chr\(\d+\)/ nocase $chain=/Chr\(\d+\)\s*[&+]\s*Chr\(\d+\)\s*[&+]\s*Chr\(\d+\)/ nocase
    $rev="StrReverse" nocase
  condition: #chr > 10 or #chain > 3 or $rev }
YR

    cat > "$RD/powershell_obfuscation.yar" << 'YR'
rule PowerShell_Encoded_Command { meta: description="Base64 PowerShell" severity="high" mitre="T1059.001"
  strings: $e1="-EncodedCommand" nocase $e2="-enc " nocase $h1="-WindowStyle Hidden" nocase
    $b1="-ExecutionPolicy Bypass" nocase $d1="IEX(New-Object" nocase $d2="Invoke-Expression" nocase
    $d3="DownloadString(" nocase $amsi="AmsiUtils" nocase
  condition: any of ($e1,$e2) or (any of ($h1,$b1) and any of ($d1,$d2,$d3)) or $amsi }
YR

    cat > "$RD/crypto_miners.yar" << 'YR'
rule CryptoMiner_Indicators { meta: description="Crypto mining indicators" severity="high" mitre="T1496"
  strings: $s1="stratum+tcp://" nocase $s2="stratum+ssl://" nocase
    $p1="pool.minexmr" nocase $p2="nanopool.org" nocase $p3="nicehash.com" nocase
    $x1="xmrig" nocase $c1="cryptonight" nocase $c2="randomx" nocase
    $ch="CoinHive" nocase
  condition: any of ($s*) or any of ($p*) or ($x1 and any of ($c*)) or $ch }
YR

    cat > "$RD/webshells.yar" << 'YR'
rule PHP_WebShell { meta: description="PHP web shell" severity="critical" mitre="T1505.003"
  strings: $e1="eval($_" $e2="assert($_" $s1="system($_" $s2="passthru($_"
    $s3="shell_exec($_" $b64=/eval\s*\(\s*base64_decode\s*\(/ $c99="c99shell" nocase $r57="r57shell" nocase
  condition: any of them }
YR

    cat > "$RD/ransomware.yar" << 'YR'
rule Ransomware_Note { meta: description="Ransomware note patterns" severity="critical" mitre="T1486"
  strings: $n1="Your files have been encrypted" nocase $n2="All your files are encrypted" nocase
    $r1="send bitcoin" nocase $r2="pay the ransom" nocase $r3=".onion"
    $sd1="vssadmin delete shadows" nocase $sd2="wmic shadowcopy delete" nocase
  condition: (any of ($n*) and any of ($r*)) or 2 of ($sd*) }
YR

    cat > "$RD/macos_threats.yar" << 'YR'
rule macOS_Suspicious_LaunchAgent { meta: description="Suspicious macOS LaunchAgent" severity="high" mitre="T1543.001"
  strings: $ph="<?xml" $pa="<key>ProgramArguments</key>" $rl="<key>RunAtLoad</key>"
    $sp1="/tmp/" $sp2="/var/tmp/" $sp3="/Users/Shared/" $sc1="curl " $sc2="osascript"
  condition: $ph and $pa and $rl and (any of ($sp*) or all of ($sc*)) }
YR

    cat > "$RD/credential_harvesting.yar" << 'YR'
rule Credential_Harvester { meta: description="Credential harvesting tools" severity="critical" mitre="T1003"
  strings: $m1="mimikatz" nocase $m2="sekurlsa" nocase $l1="lsass.dmp" nocase
    $k1="security find-generic-password" $k2="security dump-keychain"
    $b1="Login Data" $b2="logins.json" $lz="lazagne" nocase
  condition: any of ($m*) or $l1 or $lz or 2 of ($k*) or all of ($b*) }
YR

    log_success "Created 8 YARA rule files in $RD/"
}

create_agent_config() {
    log_header "Agent Configuration"
    local CFG="$HOME/.healthcheck/scanner_config.json"
    mkdir -p "$(dirname "$CFG")"
    [[ -f "$CFG" ]] && { track_skip; log_success "Config exists: $CFG"; return; }
    cat > "$CFG" << 'CFGEOF'
{
    "server_url": "https://healthcheck.zasupport.com",
    "api_key": "REPLACE_WITH_AGENT_API_KEY",
    "client_id": null, "device_id": null,
    "scan_interval_minutes": 60, "scan_on_startup": true,
    "scanners": {
        "filesystem": {"enabled": true, "max_file_size_mb": 100, "exclude_paths": ["/System","/Library/Apple","node_modules",".git"]},
        "email": {"enabled": true, "scan_attachments": true, "max_attachment_size_mb": 50},
        "app_auditor": {"enabled": true, "check_browser_extensions": true, "browsers": ["chrome","firefox","safari","edge"]},
        "persistence": {"enabled": true, "check_launch_agents": true, "check_launch_daemons": true, "check_login_items": true, "check_cron": true},
        "process": {"enabled": true, "cpu_threshold_percent": 80},
        "network": {"enabled": true, "check_dns": true, "check_connections": true, "check_hosts_file": true, "known_c2_check": true}
    },
    "yara_rules_path": null, "log_level": "INFO", "upload_results": true, "dry_run": false
}
CFGEOF
    track_install; log_success "Config created: $CFG"
}

verify_dependencies() {
    log_header "Dependency Verification"
    command -v python3 &>/dev/null && log_success "Python: $(python3 --version 2>&1)" || log_error "Python3 missing"
    command -v yara &>/dev/null && log_success "YARA: $(yara --version 2>&1)" || log_error "YARA missing"
    python3 -c "import yara" 2>/dev/null && log_success "yara-python OK" || log_warn "yara-python not importable"
    python3 -c "import magic" 2>/dev/null && log_success "python-magic OK" || log_warn "python-magic not importable"
    command -v ssdeep &>/dev/null && log_success "ssdeep OK" || log_warn "ssdeep missing"
    command -v jq &>/dev/null && log_success "jq OK" || log_warn "jq missing"
    if [[ "$MODE" == "server" ]]; then
        command -v psql &>/dev/null && log_success "PostgreSQL client OK" || log_error "psql missing"
        command -v redis-cli &>/dev/null && log_success "Redis CLI OK" || log_warn "redis-cli missing"
        for p in fastapi uvicorn asyncpg redis httpx pydantic; do
            python3 -c "import $p" 2>/dev/null && log_success "Python: $p" || log_warn "Python: $p missing"
        done
    fi
    if [[ "$MODE" == "agent" ]]; then
        for p in httpx yara pydantic aiofiles; do
            python3 -c "import $p" 2>/dev/null && log_success "Python: $p" || log_warn "Python: $p missing"
        done
    fi
    local SD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    [[ -d "$SD/yara_rules" ]] && log_success "YARA rules: $(find "$SD/yara_rules" -name '*.yar' | wc -l | tr -d ' ') files" || log_warn "No YARA rules dir"
}

main() {
    echo -e "\n${CYAN}${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║   Breach Scanner — Dependency Installer                  ║${NC}"
    echo -e "${CYAN}${BOLD}║   Health Check AI | ZA Support                          ║${NC}"
    echo -e "${CYAN}${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}\n"
    detect_os; detect_mode
    [[ "$MODE" == "check" ]] && { verify_dependencies; exit 0; }
    case "$OS" in
        macos)  install_macos_deps ;; debian) install_debian_deps ;;
        alpine) install_alpine_deps ;; rhel) install_rhel_deps ;;
        *) log_warn "Unknown OS — install python3, yara, libmagic, ssdeep manually" ;;
    esac
    install_python_deps; create_yara_rules; create_agent_config; verify_dependencies
    log_header "Summary"
    echo -e "  ${GREEN}Installed:${NC} $INSTALLED  ${BLUE}Skipped:${NC} $SKIPPED  ${YELLOW}Warnings:${NC} $WARNINGS  ${RED}Failed:${NC} $FAILED"
    [[ $FAILED -gt 0 ]] && { log_error "Some installs failed"; exit 1; }
    log_success "Done. Mode: $MODE"
}
main "$@"
