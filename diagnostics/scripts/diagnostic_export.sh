#!/bin/bash
# ============================================================================
# ZA SUPPORT — Health Check Scout
# Version: 3.3
# Purpose: Maximum-depth hardware, software, security, usage, and system
#          health diagnostics with auto-installed tooling, structured JSON
#          output, recommendation engine, and Health Check AI API push.
# Usage:   sudo ./za_diag_v3.sh [--quick] [--push --client CLIENT_ID] [--json-only]
# Output:  ~/Desktop/ZA_Diagnostic_<serial>_<date>.txt
#          ~/Desktop/ZA_Diagnostic_<serial>_<date>.json
# Requires: Root/admin access, ~10-15 minutes runtime (--quick: ~2 minutes)
# ============================================================================

set -o pipefail

if [[ $EUID -ne 0 ]]; then
    sudo -v 2>/dev/null || true
    while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit; done &
    SUDO_KEEPALIVE_PID=$!
    trap 'kill $SUDO_KEEPALIVE_PID 2>/dev/null' EXIT
fi

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION & FLAGS
# ═══════════════════════════════════════════════════════════════
BOLD="\033[1m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"
RED="\033[0;31m"; CYAN="\033[0;36m"; NC="\033[0m"

QUICK_MODE=false
PUSH_MODE=false
JSON_ONLY=false
CLIENT_ID=""

# Suppress Java JDK install popup and OS install environment
export JAVA_HOME="${JAVA_HOME:-/usr}"
export __OSINSTALL_ENVIRONMENT=1
API_URL="${ZA_API_URL:-https://za-health-check-v11.onrender.com}${ZA_API_ENDPOINT:-/api/v1/agent/diagnostics}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick)   QUICK_MODE=true; shift ;;
        --push)    PUSH_MODE=true; shift ;;
        --client)  CLIENT_ID="$2"; shift 2 ;;
        --json-only) JSON_ONLY=true; shift ;;
        --api-url) API_URL="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo -e "${YELLOW}[WARN] Not running as root — some sections may have limited data.${NC}"
    echo -e "${YELLOW}       For full data: sudo bash za_diag_full.sh${NC}"
fi

# Determine the real user — works in both contexts:
# - LaunchAgent: runs as user directly, whoami = courtneybentley
# - sudo bash za_diag_full.sh: SUDO_USER = courtneybentley, whoami = root
ACTUAL_USER="${SUDO_USER:-${CONSOLE_USER:-$(stat -f '%Su' /dev/console 2>/dev/null || whoami)}}"
ACTUAL_HOME=$(eval echo "~$ACTUAL_USER" 2>/dev/null || echo "$HOME")
mkdir -p "$ACTUAL_HOME/Desktop" 2>/dev/null || true
TIMESTAMP=$(date "+%Y-%m-%d_%H%M%S")
SERIAL=$(timeout 10 system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Serial Number/{gsub(/^[ \t]+/,"",$2); print $2}')
if [[ -z "$SERIAL" || "$SERIAL" == "Not Available" ]]; then
    SERIAL=$(timeout 5 ioreg -l 2>/dev/null | awk -F'"' '/IOPlatformSerialNumber/{print $4}')
fi
if [[ -z "$SERIAL" ]]; then
    SERIAL="ZA-$(hostname -s 2>/dev/null || echo UNKNOWN)"
fi
REPORT_FILE="$ACTUAL_HOME/Desktop/ZA_Diagnostic_${SERIAL}_${TIMESTAMP}.txt"
JSON_FILE="$ACTUAL_HOME/Desktop/ZA_Diagnostic_${SERIAL}_${TIMESTAMP}.json"
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# ── CONFIG LOADER: try known install paths, then env vars ──
for _conf in /usr/local/za-support-diagnostics/config/settings.conf \
             /etc/za-support/settings.conf \
             "$HOME/.za_support/settings.conf"; do
    [ -f "$_conf" ] && source "$_conf" 2>/dev/null && break
done
unset _conf
# ── INLINE PRICING CONFIGURATION ──
PRICE_SECURITY_CONFIG="Advanced Security Configuration|R 1,499"
PRICE_FIREWALL_CONFIG="Firewall Configuration|R 899"
PRICE_PASSWORD_MANAGER="Password Manager Setup|R 499"
PRICE_BACKUP_SETUP="Backup Configuration|R 899"
PRICE_OS_UPGRADE="macOS Upgrade Service|R 1,799"
PRICE_HEALTH_CHECK="ZA Support Health Check (Annual)|R 4,499/year"
PRICE_CYBERSHIELD="CyberShield Network Security|R 3,500/month"
PRICE_MAINTENANCE="Annual Maintenance Plan|R 4,999/year"
PRICE_DATA_MIGRATION="Data Migration Service|R 1,499"
PRICE_ENCRYPTION="Full Disk Encryption Setup|R 1,499"
PRICE_MALWARE_REMOVAL="Malware Removal & Cleanup|R 1,799"
PRICE_SECURITY_AUDIT="Full Security Audit|R 2,499"
PRICE_PERFORMANCE_OPT="Performance Optimisation|R 1,799"
PRICE_HOURLY="Hourly Rate|R 899/hr"

# Load NDJSON accumulator (write_json / write_json_raw / build_json)
# ─── INLINE: JSON ACCUMULATOR & LOOKUP (from za_diag_v3.sh) ───
ZA_JSON_TEMP="/tmp/za_sections_$$.jsonl"

# Clean up temp file on exit
trap 'rm -f "$ZA_JSON_TEMP"' EXIT

# Write a section whose value is a JSON object built from key=value pairs.
# Usage: write_json "section_key" "field1" "val1" "field2" "val2" ...
write_json() {
    local section_key="$1"; shift
    local obj="{"
    local first=1
    while [ $# -ge 2 ]; do
        local k="$1" v="$2"; shift 2
        # Escape double-quotes in value; collapse newlines; truncate to 500 chars
        v="$(printf '%s' "$v" | sed 's/"/\\"/g' | tr '\n' ' ' | cut -c1-500)"
        [ "$first" = "1" ] && first=0 || obj="${obj},"
        obj="${obj}\"${k}\":\"${v}\""
    done
    obj="${obj}}"
    printf '{"key":"%s","value":%s}\n' "$section_key" "$obj" >> "$ZA_JSON_TEMP"
}

# Write a section whose value is a simple scalar string.
# Usage: write_json_simple "section_key" "string_value"
write_json_simple() {
    local section_key="$1"
    local val="$(printf '%s' "$2" | sed 's/"/\\"/g' | tr '\n' ' ' | cut -c1-500)"
    printf '{"key":"%s","value":"%s"}\n' "$section_key" "$val" >> "$ZA_JSON_TEMP"
}

# Write a section whose value is a raw pre-formed JSON fragment (array or object).
# Usage: write_json_raw "section_key" '{"foo":1}'
write_json_raw() {
    local section_key="$1"
    local raw_json="$2"
    printf '{"key":"%s","value":%s}\n' "$section_key" "$raw_json" >> "$ZA_JSON_TEMP"
}

# Assemble all accumulated sections into a single JSON object and write to file.
# Usage: build_json "/path/to/output.json"
build_json() {
    local out_file="$1"
    printf '{' > "$out_file"
    local first=1
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # Extract key and value using parameter expansion (no jq required)
        # Line format: {"key":"KEY","value":VALUE}
        local key value
        key="$(printf '%s' "$line" | sed 's/^{"key":"\([^"]*\)".*$/\1/')"
        value="$(printf '%s' "$line" | sed 's/^{"key":"[^"]*","value":\(.*\)}$/\1/')"
        [ "$first" = "1" ] && first=0 || printf ',' >> "$out_file"
        printf '"%s":%s' "$key" "$value" >> "$out_file"
    done < "$ZA_JSON_TEMP"
    printf '}\n' >> "$out_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# CLIENT ID LOOKUP
# Resolves client_id for a given serial number.
# Priority: --client flag (handled before call) → ZA_CLIENT_ID in settings.conf
#           → V11 device registry (live lookup) → auto-SERIAL fallback
# Unknown serials are auto-registered by V11 on the next push.
# Usage: CLIENT_ID=$(lookup_client_id "$SERIAL")
# ─────────────────────────────────────────────────────────────────────────────
lookup_client_id() {
    local serial="$1"

    # 1. Manually assigned in settings.conf
    if [[ -n "${ZA_CLIENT_ID:-}" ]]; then
        echo "$ZA_CLIENT_ID"
        return
    fi

    # 2. Ask V11 backend for the registered client_id
    if [[ -n "${ZA_API_TOKEN:-}" && -n "${ZA_API_URL:-}" ]]; then
        local remote_id
        remote_id=$(curl -s --max-time 5 \
            -H "Authorization: Bearer $ZA_API_TOKEN" \
            "${ZA_API_URL}/api/v1/agent/devices/${serial}" 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin).get('client_id',''))" 2>/dev/null)
        if [[ -n "$remote_id" && "$remote_id" != "null" ]]; then
            echo "$remote_id"
            return
        fi
    fi

    # 3. Fallback — V11 will auto-register this serial on push
    echo "auto-${serial}"
}

# ─────────────────────────────────────────────────────────────────────────────
# RENDER BACKEND INTEGRATION
# ZA_API_URL  = base URL (no trailing slash)
# ZA_API_ENDPOINT = path (default: /api/v1/agent/diagnostics)
# ─────────────────────────────────────────────────────────────────────────────
push_to_render() {
    local json_file="$1"
    local base="${ZA_API_URL:-https://za-health-check-v11.onrender.com}"
    local path="${ZA_API_ENDPOINT:-/api/v1/agent/diagnostics}"
    local endpoint="${base}${path}"

    curl -s -X POST "$endpoint" \
        -H "Authorization: Bearer ${ZA_AUTH_TOKEN:-${ZA_API_TOKEN:-}}" \
        -H "Content-Type: application/json" \
        --data-binary @"$json_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# LOAD MODULES
# Each module may call write_json / write_json_simple / write_json_raw
# ─────────────────────────────────────────────────────────────────────────────
for mod in "$MODULES_DIR"/*.sh; do
    [ -r "$mod" ] && source "$mod"
done


# Auto-detect client ID from serial if not passed via --client
if [[ -z "${CLIENT_ID:-}" ]]; then
# Auto-detect client ID from settings.conf or serial fallback
if [[ -z "${CLIENT_ID:-}" ]]; then
    if [[ -n "${ZA_CLIENT_ID:-}" ]]; then
        CLIENT_ID="$ZA_CLIENT_ID"
    else
        CLIENT_ID="auto-${SERIAL}"
    fi
fi
fi

TOTAL_SECTIONS=120
[[ "$QUICK_MODE" == true ]] && TOTAL_SECTIONS=12

echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   ZA SUPPORT — CyberPulse Assessment v3.3      ║${NC}"
echo -e "${GREEN}${BOLD}║   ROOT ACCESS — $([ "$QUICK_MODE" == true ] && echo "QUICK MODE (~2 min)" || echo "FULL MODE (~10-15 min)")                       ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Serial: $SERIAL | Collecting $TOTAL_SECTIONS sections...${NC}"
echo ""

START_TIME=$(date +%s)

progress() {
    local lbl="$1"
    local num="${lbl%%/*}"
    local tot="${lbl##*/}"; tot="${tot%% *}"
    local pct=0; [[ "$tot" -gt 0 ]] 2>/dev/null && pct=$(( num * 100 / tot ))
    local el=$(( $(date +%s) - ${START_TIME:-$(date +%s)} ))
    local em=$(( el / 60 )); local es=$(( el % 60 ))
    local eta="--:--"
    if [[ "$num" -gt 1 && "$pct" -gt 0 ]] 2>/dev/null; then
        local te=$(( el * 100 / pct )); local rm=$(( te - el ))
        [[ "$rm" -lt 0 ]] && rm=0; eta="$(( rm / 60 ))m$(( rm % 60 ))s"
    fi
    local bw=30 fl=$(( pct * 30 / 100 )) bar=""
    for ((i=0;i<fl;i++)); do bar+="█"; done
    for ((i=fl;i<bw;i++)); do bar+="░"; done
    printf "\r  [%s] %3d%% | %02d:%02d | ETA %s | %s" "$bar" "$pct" "$em" "$es" "$eta" "$lbl" >&2
}
section() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║  $1"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    echo ""
}
subsection() { echo "--- $1 ---"; }

# ═══════════════════════════════════════════════════════════════
# DEPENDENCY INSTALLATION
# ═══════════════════════════════════════════════════════════════
install_dependencies() {
    progress "0/$TOTAL_SECTIONS — Installing diagnostic tools"
    
    BREW_BIN=""
    if [ -f "/opt/homebrew/bin/brew" ]; then
        BREW_BIN="/opt/homebrew/bin/brew"
    elif [ -f "/usr/local/bin/brew" ]; then
        BREW_BIN="/usr/local/bin/brew"
    fi
    
    if [[ -z "$BREW_BIN" ]]; then
        echo "  [INFO] Extended diagnostic tools will be installed during the next service visit"
    fi
    
    # Homebrew refuses to run as root — skip installs if running as root (e.g. launchd daemon)
    if [[ -n "$BREW_BIN" && "$ACTUAL_USER" != "root" ]]; then
        # Install smartmontools if missing
        if ! command -v smartctl &>/dev/null; then
            echo "  Installing smartmontools..."
            sudo -u "$ACTUAL_USER" "$BREW_BIN" install smartmontools 2>/dev/null || true
        fi
        # Install ioping if missing
        if ! command -v ioping &>/dev/null; then
            echo "  Installing ioping..."
            sudo -u "$ACTUAL_USER" "$BREW_BIN" install ioping 2>/dev/null || true
        fi
        echo "  [OK] Diagnostic tools ready"
    elif [[ "$ACTUAL_USER" == "root" ]]; then
        echo "  [INFO] Running as root daemon — skipping brew installs, using built-in tools"
    else
        echo "  [INFO] Extended diagnostic tools will be available after next service visit."
    fi
    echo ""
}

install_dependencies

# ═══════════════════════════════════════════════════════════════
# COLLECT — ALL DATA PIPED TO REPORT FILE
# ═══════════════════════════════════════════════════════════════
{
echo "╔══════════════════════════════════════════════════════════════════════════════════╗"
echo "║  ZA SUPPORT — CyberPulse Assessment v3.3                  ║"
echo "║  $([ "$QUICK_MODE" == true ] && echo "QUICK MODE" || echo "FULL MODE")                                                                  ║"
echo "╠══════════════════════════════════════════════════════════════════════════════════╣"
echo "║  Generated:  $(date '+%d/%m/%Y %H:%M:%S')"
echo "║  Serial:     $SERIAL"
echo "║  Hostname:   $(hostname)"
echo "║  Username:   $ACTUAL_USER (run as root)"
[[ -n "$CLIENT_ID" ]] && echo "║  Client ID:  $CLIENT_ID"
echo "╚══════════════════════════════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# 1. HARDWARE IDENTITY & PROVENANCE
# ═══════════════════════════════════════════════════════════════
progress "1/$TOTAL_SECTIONS — Hardware Identity"
section "1. HARDWARE IDENTITY & PROVENANCE"
timeout 30 system_profiler SPHardwareDataType 2>/dev/null || echo "[ERROR] Hardware data unavailable"
echo "Architecture: $(uname -m)"
echo "Processor:    $(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'Unknown')"
echo "Cores (Phys):  $(sysctl -n hw.physicalcpu 2>/dev/null || echo 'Unknown')"
echo "Cores (Logic): $(sysctl -n hw.logicalcpu 2>/dev/null || echo 'Unknown')"
echo "CPU Freq:      $(sysctl -n hw.cpufrequency 2>/dev/null | awk '{printf "%.2f GHz\n", $1/1000000000}' 2>/dev/null || echo 'N/A (Apple Silicon)')"
HW_UUID=$(timeout 30 system_profiler SPHardwareDataType 2>/dev/null | grep "Hardware UUID" | awk '{print $NF}')
HW_UUID="${HW_UUID:-Unknown}"
TOTAL_RAM=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}')
TOTAL_RAM="${TOTAL_RAM:-0}"
echo "Hardware UUID: $HW_UUID"
if sysctl -n machdep.cpu.brand_string 2>/dev/null | grep -qi "apple"; then
    CHIP_TYPE="APPLE_SILICON"
    echo "Chip Type: APPLE SILICON"
else
    CHIP_TYPE="INTEL"
    echo "Chip Type: INTEL"
    echo "CPU Microcode: $(sysctl -n machdep.cpu.microcode_version 2>/dev/null || echo 'N/A')"
    if timeout 30 system_profiler SPiBridgeDataType 2>/dev/null | grep -qi "T2"; then
        echo "Security Chip: Apple T2 detected"
        timeout 30 system_profiler SPiBridgeDataType 2>/dev/null
    else
        echo "Security Chip: No T2 chip detected"
    fi
fi

write_json "hardware" \
    "serial" "$SERIAL" \
    "model" "$(timeout 30 system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Model Name/{print $2}' | head -1)" \
    "chip_type" "$CHIP_TYPE" \
    "cpu" "$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo 'Apple Silicon')" \
    "cores_physical" "$(sysctl -n hw.physicalcpu 2>/dev/null || echo '?')" \
    "cores_logical" "$(sysctl -n hw.logicalcpu 2>/dev/null || echo '?')" \
    "ram_gb" "$TOTAL_RAM" \
    "hardware_uuid" "$HW_UUID"

subsection "Activation Lock / Find My Mac"
nvram -p 2>/dev/null | grep -i "fmm-mobileme-token-FMM" && echo "[WARN] Find My Mac token present — Activation Lock likely ON" || echo "[INFO] No Find My Mac token in NVRAM"
profiles -P -o stdout 2>/dev/null | grep -i "findmy" && echo "[INFO] Find My profile detected" || true

subsection "Firmware Password"
firmwarepasswd -check 2>/dev/null || echo "[INFO] firmwarepasswd not available (Apple Silicon or not supported)"

subsection "DEP / MDM Enrollment"
profiles status -type enrollment 2>/dev/null || echo "[INFO] Enrollment check not available"
echo ""

# ═══════════════════════════════════════════════════════════════
# 2. FIRMWARE / EFI / NVRAM
# ═══════════════════════════════════════════════════════════════
progress "2/$TOTAL_SECTIONS — Firmware & NVRAM"
section "2. FIRMWARE / EFI / NVRAM"
timeout 30 system_profiler SPHardwareDataType 2>/dev/null | grep -E "Boot ROM|SMC|Firmware"
subsection "NVRAM Variables"
nvram -xp 2>/dev/null | head -100 || echo "[ERROR] Could not read NVRAM"
subsection "Boot Arguments"
nvram boot-args 2>/dev/null || echo "[INFO] No custom boot arguments set"
subsection "Startup Disk"
bless --info --getBoot 2>/dev/null || echo "[INFO] Could not determine boot volume"
subsection "EFI Integrity (Intel)"
[[ "$CHIP_TYPE" == "INTEL" ]] && eficheck --integrity-check 2>/dev/null || echo "[INFO] eficheck not available or Apple Silicon"
echo ""

# ═══════════════════════════════════════════════════════════════
# 3. macOS & SYSTEM SOFTWARE
# ═══════════════════════════════════════════════════════════════
progress "3/$TOTAL_SECTIONS — macOS & System Software"
section "3. macOS & SYSTEM SOFTWARE"
sw_vers 2>/dev/null
uname -a 2>/dev/null
echo "Uptime: $(uptime 2>/dev/null)"
last reboot 2>/dev/null | head -10
subsection "Security Status"
SIP_STATUS=$(csrutil status 2>/dev/null | head -1)
echo "SIP: $SIP_STATUS"
csrutil authenticated-root status 2>/dev/null || echo "[INFO] Authenticated root not available"
GK_STATUS=$(timeout 10 spctl --status 2>/dev/null)
echo "Gatekeeper: $GK_STATUS"
FV_STATUS=$(fdesetup status 2>/dev/null)
echo "FileVault: $FV_STATUS"
FW_STATE=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)
echo "Firewall: $FW_STATE"
/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode 2>/dev/null
/usr/libexec/ApplicationFirewall/socketfilterfw --getblockall 2>/dev/null
subsection "Firewall — App Rules"
/usr/libexec/ApplicationFirewall/socketfilterfw --listapps 2>/dev/null || echo "[INFO] No explicit rules"
subsection "Remote Access"
systemsetup -getremotelogin 2>/dev/null || true
systemsetup -getremoteappleevents 2>/dev/null || true
launchctl list 2>/dev/null | grep -i screensharing || echo "[INFO] Screen sharing not loaded"
subsection "Time & NTP"
systemsetup -gettimezone 2>/dev/null; systemsetup -getusingnetworktime 2>/dev/null; systemsetup -getnetworktimeserver 2>/dev/null

subsection "Rosetta 2"
[ -f "/Library/Apple/usr/libexec/oah/libRosettaRuntime" ] && echo "[OK] Rosetta 2 installed" || echo "[INFO] Rosetta 2 not installed"
echo ""

MACOS_MAJOR=$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)
MACOS_MAJOR="${MACOS_MAJOR:-0}"

write_json "macos" \
    "version" "$(sw_vers -productVersion 2>/dev/null)" \
    "build" "$(sw_vers -buildVersion 2>/dev/null)" \
    "sip" "$SIP_STATUS" \
    "filevault" "$FV_STATUS" \
    "gatekeeper" "$GK_STATUS" \
    "firewall" "$FW_STATE"

# ═══════════════════════════════════════════════════════════════
# 4. CPU, THERMAL & POWER — EXTENDED
# ═══════════════════════════════════════════════════════════════
progress "4/$TOTAL_SECTIONS — CPU, Thermal & Power (extended sampling)"
section "4. CPU, THERMAL & POWER METRICS — EXTENDED"
ps aux -r | head -21
echo "Load Average: $(sysctl -n vm.loadavg 2>/dev/null)"
pmset -g therm 2>/dev/null || echo "[INFO] Thermal data not available"
pmset -g 2>/dev/null
subsection "Power Assertions (Full)"
pmset -g assertions 2>/dev/null
subsection "Energy Log"
timeout 15 pmset -g rawlog 2>/dev/null | tail -30 || echo "[INFO] Raw log not available"

POWER_SAMPLE_TIME=30
[[ "$QUICK_MODE" == true ]] && POWER_SAMPLE_TIME=5
subsection "POWERMETRICS (${POWER_SAMPLE_TIME}s sample — all samplers)"
if command -v powermetrics &>/dev/null; then
    timeout $((POWER_SAMPLE_TIME + 2)) powermetrics --samplers cpu_power,gpu_power,thermal,smc,battery -i 5000 -n $((POWER_SAMPLE_TIME / 5)) 2>/dev/null || echo "[INFO] powermetrics failed or timed out"
else
    echo "[INFO] powermetrics not available"
fi

subsection "Sleep/Wake Failure Log"
if [[ "$QUICK_MODE" == false ]]; then
    timeout 15 pmset -g log 2>/dev/null | grep -iE "fail|Wake.*fail|DarkWake.*fail|Sleep.*fail" | tail -20 || echo "[OK] No sleep/wake failures in log"
fi

subsection "Thermal Shutdown History (30d)"
if [[ "$QUICK_MODE" == false ]]; then
    timeout 30 log show --predicate 'eventMessage CONTAINS[c] "thermal shutdown"' --style compact --last 30d 2>/dev/null | tail -10 || echo "[OK] No thermal shutdowns"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 5. FULL SMC KEY DUMP & SENSOR DATA
# ═══════════════════════════════════════════════════════════════
progress "5/$TOTAL_SECTIONS — SMC Sensors & Fan Data"
section "5. SMC SENSORS, FANS & VOLTAGE RAILS"
subsection "Fan Speeds"
timeout 15 ioreg -rn AppleSMC 2>/dev/null | grep -iE "fan|Fan" | head -20 || echo "[INFO] Fan data not available"
subsection "Temperature Sensors (IOHWSensor)"
timeout 15 ioreg -rn IOHWSensor 2>/dev/null | grep -iE "type|current-value|location" | head -60 || echo "[INFO] No sensor data"
subsection "Full SMC Tree"
timeout 15 ioreg -rn AppleSMC 2>/dev/null | head -200 || echo "[INFO] SMC tree not available"
subsection "Thunderbolt Controller"
timeout 15 ioreg -rc IOThunderboltController 2>/dev/null | grep -iE "temp|power|link" | head -10 || echo "[INFO] No Thunderbolt data"
subsection "Ambient Light Sensor"
timeout 15 ioreg -rc AppleLMUController 2>/dev/null | head -10 || echo "[INFO] No ALS data"
echo ""

# ═══════════════════════════════════════════════════════════════
# 6. MEMORY — DEEP
# ═══════════════════════════════════════════════════════════════
progress "6/$TOTAL_SECTIONS — Memory Deep"
section "6. MEMORY (RAM) — DEEP"
TOTAL_RAM=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}')
TOTAL_RAM="${TOTAL_RAM:-0}"
echo "Total RAM: ${TOTAL_RAM} GB"
RAM_UPGRADEABLE="UNKNOWN"
# Apple Silicon = always soldered. Intel depends on model.
if [[ "$CHIP_TYPE" == "APPLE_SILICON" ]]; then
    RAM_UPGRADEABLE="NO (soldered — Apple Silicon)"
else
    # Check if memory shows multiple DIMMs
    DIMM_COUNT=$(timeout 30 system_profiler SPMemoryDataType 2>/dev/null | grep -c "BANK" || echo "0")
    [[ "$DIMM_COUNT" -gt 1 ]] && RAM_UPGRADEABLE="LIKELY YES ($DIMM_COUNT slots)" || RAM_UPGRADEABLE="LIKELY NO (single module)"
fi
echo "Upgradeable: $RAM_UPGRADEABLE"

memory_pressure 2>/dev/null || echo "[INFO] memory_pressure not available"
subsection "VM Statistics (snapshot 1)"
vm_stat 2>/dev/null
sysctl vm.swapusage 2>/dev/null
subsection "Top Processes by Memory"
ps aux -m | head -21
timeout 30 system_profiler SPMemoryDataType 2>/dev/null

if [[ "$QUICK_MODE" == false ]]; then
    subsection "Memory Pressure Events (24h)"
    timeout 30 log show --predicate 'eventMessage CONTAINS[c] "memory pressure"' --style compact --last 24h 2>/dev/null | tail -20 || echo "[OK] No pressure events"
    subsection "Jetsam Kills"
    ls -lt /private/var/jetsam*.* 2>/dev/null | head -5 || echo "[OK] No jetsam logs"
    LATEST_JETSAM=$(ls -t /private/var/jetsam*.* 2>/dev/null | head -1)
    [[ -n "$LATEST_JETSAM" ]] && tail -30 "$LATEST_JETSAM" 2>/dev/null
    subsection "Kernel Zones"
    zprint 2>/dev/null | head -30 || echo "[INFO] zprint not available"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 7. STORAGE — DEEP + SMART + LATENCY
# ═══════════════════════════════════════════════════════════════
progress "7/$TOTAL_SECTIONS — Storage Deep + SMART + Latency"
section "7. STORAGE — DEEP + SMART + BENCHMARK + LATENCY"
df -h 2>/dev/null
BOOT_INFO=$(df -g / 2>/dev/null | awk 'NR==2{print $2, $3, $4}')
BOOT_TOTAL=$(echo "$BOOT_INFO" | awk '{print $1}')
BOOT_USED=$(echo "$BOOT_INFO" | awk '{print $2}')
BOOT_FREE=$(echo "$BOOT_INFO" | awk '{print $3}')
BOOT_PCT=$(df / 2>/dev/null | awk 'NR==2{gsub(/%/,""); print $5}')
# Aliases for recommendation engine
DISK_USED_PCT="${BOOT_PCT:-0}"
DISK_FREE_GB="${BOOT_FREE:-0}"
echo "Boot Disk Used: ${DISK_USED_PCT}% | Free: ${DISK_FREE_GB} GB | Total: ${BOOT_TOTAL:-0} GB"

write_json "storage" \
    "boot_disk_used_pct"  "${BOOT_PCT:-0}" \
    "boot_disk_free_gb"   "${BOOT_FREE:-0}" \
    "boot_disk_total_gb"  "${BOOT_TOTAL:-0}" \
    "boot_disk_used_gb"   "${BOOT_USED:-0}"

timeout 30 system_profiler SPStorageDataType 2>/dev/null
timeout 30 system_profiler SPNVMeDataType 2>/dev/null || echo "[INFO] No NVMe"
timeout 30 system_profiler SPSerialATADataType 2>/dev/null || echo "[INFO] No SATA"

subsection "TRIM Status"
TRIM_STATUS=$(timeout 30 system_profiler SPNVMeDataType 2>/dev/null | grep -i "TRIM" || timeout 30 system_profiler SPSerialATADataType 2>/dev/null | grep -i "TRIM" || echo "")
if echo "$TRIM_STATUS" | grep -qi "Yes\|Enabled"; then
    echo "[OK] TRIM enabled"
elif [[ -n "$TRIM_STATUS" ]]; then
    echo "  TRIM is not currently enabled. This will be enabled during the security configuration session to improve disk performance."
    TRIM_DISABLED="YES"
else
    echo "  TRIM status: not applicable (Apple SSD or not detected)"
fi

diskutil list 2>/dev/null
diskutil apfs list 2>/dev/null || echo "[INFO] No APFS"
diskutil cs list 2>/dev/null || echo "[INFO] No Core Storage / Fusion"

subsection "APFS Snapshots"
tmutil listlocalsnapshots / 2>/dev/null || echo "[INFO] No local snapshots"

subsection "Recovery Partition"
diskutil list 2>/dev/null | grep -i "Recovery" && echo "[OK] Recovery partition found" || echo "[WARN] No Recovery partition detected"

subsection "SMART (Full)"
if command -v smartctl &>/dev/null; then
    for disk in /dev/disk0 /dev/disk1; do
        [ -e "$disk" ] && { echo ">>> smartctl -x $disk:"; timeout 30 smartctl -x "$disk" 2>/dev/null || echo "[INFO] Could not read $disk"; }
    done
else
    echo "[WARN] smartctl not available — using IORegistry fallback"
    timeout 15 ioreg -rc IONVMeController 2>/dev/null | grep -iE "life|wear|endurance|temperature|error" | head -20
fi

subsection "Disk Error Counters (IOKit)"
timeout 15 ioreg -rc IOBlockStorageDriver 2>/dev/null | grep -iE "error|retry|timeout" | head -10 || echo "[OK] No disk errors in IOKit"

subsection "Throughput Benchmark (1GB)"
echo "Write:"
timeout 60 dd if=/dev/zero of=$TEMP_DIR/speedtest bs=1048576 count=1024 2>&1 | tail -1
echo "Read:"
timeout 60 dd if=$TEMP_DIR/speedtest of=/dev/null bs=1048576 count=1024 2>&1 | tail -1
rm -f $TEMP_DIR/speedtest

subsection "I/O Latency"
if command -v ioping &>/dev/null; then
    timeout 30 ioping -c 20 -q / 2>/dev/null || echo "[INFO] ioping failed"
else
    echo "[INFO] ioping not installed — using dd sync fallback"
    timeout 60 dd if=/dev/zero of=$TEMP_DIR/lattest bs=4096 count=100 oflag=sync 2>&1 | tail -1
    rm -f $TEMP_DIR/lattest
fi

if [[ "$QUICK_MODE" == false ]]; then
    subsection "Filesystem Verification"
    diskutil verifyVolume / 2>/dev/null || echo "[INFO] Could not verify — volume may be mounted read-write"
    
    subsection "Disk I/O Per Process (10s sample)"
    fs_usage -w -e diskio -t 10 2>/dev/null | head -50 || echo "[INFO] fs_usage not available"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 8. BATTERY — DEEP
# ═══════════════════════════════════════════════════════════════
progress "8/$TOTAL_SECTIONS — Battery Deep"
section "8. BATTERY & POWER — DEEP"
timeout 30 system_profiler SPPowerDataType 2>/dev/null || echo "[INFO] Desktop Mac — no battery"

subsection "Full Battery Dump"
timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null || echo "[INFO] No battery data"

# Parse key values
DESIGN_CAP=$(timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null | grep DesignCapacity | awk '{print $NF}' | tr -d '"' | head -1)
MAX_CAP=$(timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null | grep MaxCapacity | awk '{print $NF}' | tr -d '"' | head -1)
CYCLE=$(timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null | grep CycleCount | awk '{print $NF}' | tr -d '"' | head -1)
BATT_CONDITION=$(timeout 30 system_profiler SPPowerDataType 2>/dev/null | grep "Condition" | awk -F': ' '{print $2}' | head -1)
BATT_TEMP=$(timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null | grep Temperature | awk '{print $NF}' | tr -d '"' | head -1)

if [[ -n "$DESIGN_CAP" && -n "$MAX_CAP" && "$DESIGN_CAP" -gt 0 ]]; then
    HEALTH=$(echo "scale=1; ($MAX_CAP * 100) / $DESIGN_CAP" | bc 2>/dev/null || echo "N/A")
    echo ""
    echo "═══ BATTERY SUMMARY ═══"
    echo "Health:       ${HEALTH}%"
    echo "Cycles:       $CYCLE"
    echo "Design Cap:   ${DESIGN_CAP} mAh"
    echo "Current Max:  ${MAX_CAP} mAh"
    echo "Condition:    ${BATT_CONDITION:-Unknown}"
    [[ -n "$BATT_TEMP" ]] && echo "Temperature:  $(echo "scale=1; $BATT_TEMP / 100" | bc 2>/dev/null)°C"
else
    HEALTH="N/A"; CYCLE="N/A"
fi

write_json "battery" \
    "health_pct" "${HEALTH:-N/A}" \
    "cycle_count" "${CYCLE:-N/A}" \
    "design_capacity_mah" "${DESIGN_CAP:-N/A}" \
    "max_capacity_mah" "${MAX_CAP:-N/A}" \
    "condition" "${BATT_CONDITION:-Unknown}"

subsection "Cell Voltages"
timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null | grep -i "CellVoltage" || echo "[INFO] Cell voltage data not available"

subsection "Adapter Info"
timeout 15 ioreg -rn AppleSmartBattery 2>/dev/null | grep -iE "Adapter|ExternalConnected|Charging|Watts" | head -10

subsection "USB-C Power Delivery"
timeout 15 ioreg -rc IOUSBHostDevice 2>/dev/null | grep -iE "PD|power.delivery|voltage|current|USB Power" | head -10 || echo "[INFO] No USB-C PD data"

subsection "Power Events"
pmset -g batt 2>/dev/null

if [[ "$QUICK_MODE" == false ]]; then
    subsection "Charge/Discharge History (7d)"
    timeout 30 log show --predicate 'subsystem == "com.apple.powerd"' --style compact --last 7d 2>/dev/null | grep -iE "charge|discharge|battery" | tail -20 || echo "[INFO] No power events"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 9. NETWORK — DEEP
# ═══════════════════════════════════════════════════════════════
progress "9/$TOTAL_SECTIONS — Network Deep"
section "9. NETWORK — DEEP"
ifconfig -a 2>/dev/null
subsection "WiFi"
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I 2>/dev/null || echo "[INFO] airport not available"
subsection "WiFi Environment Scan"
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s 2>/dev/null || echo "[INFO] Scan not available"
subsection "Known WiFi Networks"
defaults read /Library/Preferences/com.apple.wifi.known-networks.plist 2>/dev/null | head -40 || defaults read /Library/Preferences/SystemConfiguration/com.apple.wifi.message-tracer.plist 2>/dev/null | head -20 || echo "[INFO] Known networks plist not readable"
subsection "DNS"
scutil --dns 2>/dev/null | head -40
subsection "Default Routes"
netstat -rn 2>/dev/null | grep default
subsection "Listening Ports"
timeout 15 lsof -i -P -n 2>/dev/null | grep LISTEN | head -30
subsection "Network Interface Errors"
netstat -i 2>/dev/null
subsection "Network Service Order"
timeout 10 networksetup -listnetworkserviceorder 2>/dev/null
subsection "Network Locations"
timeout 10 networksetup -listlocations 2>/dev/null

PING_COUNT=50
[[ "$QUICK_MODE" == true ]] && PING_COUNT=5
subsection "Ping Tests (${PING_COUNT} packets)"
GATEWAY=$(netstat -rn 2>/dev/null | grep "^default" | head -1 | awk '{print $2}')
[[ -n "$GATEWAY" ]] && ping -c $PING_COUNT "$GATEWAY" 2>/dev/null || echo "[WARN] Gateway ping failed"
ping -c 5 8.8.8.8 2>/dev/null || echo "[WARN] 8.8.8.8 unreachable"

if [[ "$QUICK_MODE" == false ]]; then
    subsection "Speed Test"
    if command -v networkQuality &>/dev/null; then
        networkQuality -s 2>/dev/null || echo "[INFO] networkQuality failed"
    fi
    subsection "Traceroute"
    traceroute -m 15 8.8.8.8 2>/dev/null || echo "[INFO] Traceroute failed"
    subsection "pf Firewall"
    pfctl -s info 2>/dev/null || echo "[INFO] pf not active"
    pfctl -sr 2>/dev/null || echo "[INFO] No pf rules"
    subsection "Proxy"
    scutil --proxy 2>/dev/null
    subsection "DNS Cache"
    dscacheutil -cachedump -entries Host 2>/dev/null | head -30 || echo "[INFO] DNS cache dump not available"
    subsection "TCP Stats"
    sysctl net.inet.tcp 2>/dev/null | grep -iE "sendspace|recvspace|rfc|mssdflt" | head -10
    subsection "mDNS/Bonjour (5s scan)"
    dns-sd -B _services._dns-sd._udp local 2>/dev/null & DNS_PID=$!; sleep 5; kill $DNS_PID 2>/dev/null; wait $DNS_PID 2>/dev/null || true
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 10. USB, THUNDERBOLT, BLUETOOTH
# ═══════════════════════════════════════════════════════════════
progress "10/$TOTAL_SECTIONS — Peripherals"
section "10. USB, THUNDERBOLT, BLUETOOTH"
timeout 30 system_profiler SPUSBDataType 2>/dev/null
timeout 30 system_profiler SPThunderboltDataType 2>/dev/null || echo "[INFO] No Thunderbolt"
timeout 30 system_profiler SPBluetoothDataType 2>/dev/null
echo ""

# ═══════════════════════════════════════════════════════════════
# 11. DISPLAY, GPU, INPUT DEVICES
# ═══════════════════════════════════════════════════════════════
progress "11/$TOTAL_SECTIONS — Display, GPU & Input"
section "11. DISPLAY, GPU & INPUT DEVICES"
timeout 30 system_profiler SPDisplaysDataType 2>/dev/null
subsection "EDID Data"
timeout 15 ioreg -lw0 -rc IODisplayConnect 2>/dev/null | grep -i EDID | head -5 || echo "[INFO] No EDID data"
subsection "Display Scaling"
defaults read /Library/Preferences/com.apple.windowserver.plist DisplayResolutionEnabled 2>/dev/null || echo "[INFO] Default scaling"
subsection "Night Shift / True Tone"
defaults read /private/var/root/Library/Preferences/com.apple.CoreBrightness.plist 2>/dev/null | head -15 || echo "[INFO] CoreBrightness not readable"
subsection "Keyboard"
timeout 15 ioreg -rc IOHIDKeyboard 2>/dev/null | grep -iE "Product|Manufacturer|VendorID|ProductID" | head -10 || echo "[INFO] No keyboard data"
subsection "Trackpad"
defaults read com.apple.AppleMultitouchTrackpad 2>/dev/null | head -15 || echo "[INFO] No trackpad"
subsection "Camera"
timeout 30 system_profiler SPCameraDataType 2>/dev/null || echo "[INFO] No camera"
subsection "SD Card Reader"
timeout 30 system_profiler SPCardReaderDataType 2>/dev/null || echo "[INFO] No card reader"
subsection "Touch Bar"
defaults read com.apple.controlstrip 2>/dev/null | head -10 || echo "[INFO] No Touch Bar / not configured"
echo ""

# ═══════════════════════════════════════════════════════════════
# 12. AUDIO
# ═══════════════════════════════════════════════════════════════
progress "12/$TOTAL_SECTIONS — Audio"
section "12. AUDIO"
timeout 30 system_profiler SPAudioDataType 2>/dev/null || echo "[INFO] No audio data"
echo ""

# ═══════════════════════════════════════════════════════════════
# QUICK MODE GATE — sections 13+ only run in full mode
# ═══════════════════════════════════════════════════════════════
if [[ "$QUICK_MODE" == true ]]; then
    progress "QUICK MODE — Skipping sections 13-56, jumping to Intelligence Engine"
    section "QUICK MODE — SECTIONS 13-56 SKIPPED"
    echo "Run without --quick for full 68-section diagnostic."
    echo ""
fi

if [[ "$QUICK_MODE" == false ]]; then

# ═══════════════════════════════════════════════════════════════
# 13. SECURITY & PRIVACY — MAXIMUM DEPTH
# ═══════════════════════════════════════════════════════════════
progress "13/$TOTAL_SECTIONS — Security & Privacy (Deep)"
section "13. SECURITY & PRIVACY — MAXIMUM DEPTH"

subsection "XProtect Version"
XPROTECT_VER=$(defaults read "/Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "Not found")
echo "XProtect: $XPROTECT_VER"
subsection "MRT Version"
MRT_VER=$(defaults read "/Library/Apple/System/Library/CoreServices/MRT.app/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "Not found")
echo "MRT: $MRT_VER"
subsection "Install History (XProtect/MRT)"
timeout 30 system_profiler SPInstallHistoryDataType 2>/dev/null | grep -A3 "XProtect\|MRT" | tail -10

subsection "Configuration Profiles (All)"
profiles show -all 2>/dev/null || echo "[INFO] No profiles"

subsection "TCC Database (System)"
if [ -f "/Library/Application Support/com.apple.TCC/TCC.db" ]; then
    timeout 10 sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" "SELECT service, client, auth_value FROM access ORDER BY service;" 2>/dev/null || echo "[ERROR] TCC read failed"
fi
subsection "TCC Database (User)"
if [ -f "$ACTUAL_HOME/Library/Application Support/com.apple.TCC/TCC.db" ]; then
    timeout 10 sqlite3 "$ACTUAL_HOME/Library/Application Support/com.apple.TCC/TCC.db" "SELECT service, client, auth_value FROM access ORDER BY service;" 2>/dev/null || echo "[ERROR] User TCC read failed"
fi

subsection "Camera/Mic Access History"
timeout 10 sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" "SELECT service, client, last_modified FROM access WHERE service IN ('kTCCServiceCamera','kTCCServiceMicrophone') ORDER BY last_modified DESC LIMIT 20;" 2>/dev/null || echo "[INFO] No camera/mic TCC data"

subsection "Custom Root Certificates"
timeout 30 security find-certificate -a -p /Library/Keychains/System.keychain 2>/dev/null | openssl x509 -noout -subject 2>/dev/null | grep -v "Apple" | head -15 || echo "[OK] No custom root certs"

subsection "Keychains"
security list-keychains 2>/dev/null

subsection "Password Policy"
pwpolicy -getglobalpolicy 2>/dev/null || echo "[INFO] No global password policy"

subsection "Secure Token Status"
for u in $(timeout 10 dscl . list /Users 2>/dev/null | grep -v '^_'); do
    sysadminctl -secureTokenStatus "$u" 2>&1 | sed "s/^/  $u: /"
done 2>/dev/null

subsection "Bootstrap Token"
profiles status -type bootstraptoken 2>/dev/null || echo "[INFO] Bootstrap token check not available"

subsection "Quarantine Events (last 30 downloads)"
timeout 10 sqlite3 "$ACTUAL_HOME/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2" "SELECT LSQuarantineAgentName, LSQuarantineOriginURLString, datetime(LSQuarantineTimeStamp + 978307200, 'unixepoch', 'localtime') FROM LSQuarantineEvent ORDER BY LSQuarantineTimeStamp DESC LIMIT 30;" 2>/dev/null || echo "[INFO] Quarantine DB not available"

subsection "Endpoint Security Extensions"
systemextensionsctl list 2>/dev/null | grep -i "endpoint" || echo "[INFO] No endpoint security extensions"

subsection "Login/Logout History"
last -20 2>/dev/null

subsection "Failed Login Attempts (7d)"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "authentication failed"' --style compact --last 7d 2>/dev/null | tail -15 || echo "[OK] No failed logins"

subsection "Audit Trail (recent)"
praudit -l /var/audit/current 2>/dev/null | tail -30 || echo "[INFO] Audit trail not available"

subsection "Authorization DB"
security authorizationdb read system.preferences 2>/dev/null | head -15 || echo "[INFO] AuthDB not readable"
echo ""

write_json "security" \
    "xprotect_version" "$XPROTECT_VER" \
    "mrt_version" "$MRT_VER" \
    "sip_enabled" "$(csrutil status 2>/dev/null | grep -ci 'enabled')" \
    "filevault_on" "$(fdesetup status 2>/dev/null | grep -ci 'On')" \
    "firewall_on" "$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | grep -ci 'enabled')" \
    "gatekeeper_on" "$(timeout 10 spctl --status 2>/dev/null | grep -ci 'enabled')"

# ═══════════════════════════════════════════════════════════════
# 14. STARTUP, LOGIN ITEMS & SERVICES
# ═══════════════════════════════════════════════════════════════
progress "14/$TOTAL_SECTIONS — Startup & Services"
section "14. STARTUP, LOGIN ITEMS & SERVICES"
ls -la /Library/LaunchDaemons/ 2>/dev/null
ls -la /Library/LaunchAgents/ 2>/dev/null
ls -la "$ACTUAL_HOME/Library/LaunchAgents/" 2>/dev/null || echo "[INFO] No user launch agents"
subsection "Staged System Extensions"
ls -la /Library/StagedExtensions/ 2>/dev/null || echo "[INFO] No staged extensions"
subsection "Failed Services"
launchctl list 2>/dev/null | awk '$1 != "0" && $1 != "-" && $1 != "PID" {print $0}'
subsection "Login Items (BTM)"
sfltool dumpbtm 2>/dev/null | head -80 || echo "[INFO] BTM not available"
crontab -l 2>/dev/null || echo "[OK] No root crontab"
sudo -u "$ACTUAL_USER" crontab -l 2>/dev/null || echo "[OK] No user crontab"
echo ""

# ═══════════════════════════════════════════════════════════════
# 15. INSTALLED SOFTWARE — FULL INVENTORY
# ═══════════════════════════════════════════════════════════════
progress "15/$TOTAL_SECTIONS — Software Inventory"
section "15. INSTALLED SOFTWARE — FULL INVENTORY"
subsection "Applications List"
ls -1 /Applications/ 2>/dev/null
subsection "Full Application Details"
timeout 30 system_profiler SPApplicationsDataType 2>/dev/null || echo "[INFO] App inventory failed"

subsection "Homebrew"
if [[ -n "${BREW_BIN:-}" ]]; then
    echo "Homebrew: $(sudo -u "$ACTUAL_USER" "$BREW_BIN" --version 2>/dev/null | head -1)"
    sudo -u "$ACTUAL_USER" "$BREW_BIN" list --formula --versions 2>/dev/null
    sudo -u "$ACTUAL_USER" "$BREW_BIN" list --cask --versions 2>/dev/null
    sudo -u "$ACTUAL_USER" "$BREW_BIN" outdated 2>/dev/null
else
    echo "[INFO] Homebrew not installed"
fi

subsection "Developer Tools"
echo "Xcode CLT: $(pkgutil --pkg-info com.apple.pkg.CLTools_Executables 2>/dev/null | grep version || echo 'Not installed')"
echo "Python3: $(python3 --version 2>/dev/null || echo 'Not installed')"
echo "Node: $(node -v 2>/dev/null || echo 'Not installed')"
echo "Ruby: $(ruby -v 2>/dev/null || echo 'System default')"
echo "Git: $(git --version 2>/dev/null || echo 'Not installed')"
echo "Java: $(java -version 2>&1 | head -1 || echo 'Not installed')"

subsection "System/Kernel Extensions"
systemextensionsctl list 2>/dev/null || echo "[INFO] Not available"
timeout 15 kextstat 2>/dev/null | grep -v com.apple || echo "[OK] No third-party kexts"
echo "Total kexts: $(kextstat 2>/dev/null | wc -l | tr -d ' ')"

subsection "Browser Extensions (Safari)"
ls "$ACTUAL_HOME/Library/Safari/Extensions/" 2>/dev/null || echo "[INFO] No Safari extensions"

subsection "Shell Configuration"
echo "--- ~/.zshrc (first 20 lines) ---"
head -20 "$ACTUAL_HOME/.zshrc" 2>/dev/null || echo "[INFO] No .zshrc"
echo "--- ~/.bash_profile (first 20 lines) ---"
head -20 "$ACTUAL_HOME/.bash_profile" 2>/dev/null || echo "[INFO] No .bash_profile"

subsection "App Crash Frequency (by app name)"
ls /Library/Logs/DiagnosticReports/*.crash "$ACTUAL_HOME/Library/Logs/DiagnosticReports/"*.crash 2>/dev/null | sed 's/.*\///' | sed 's/_[0-9][0-9][0-9][0-9].*//' | sort | uniq -c | sort -rn | head -20 || echo "[OK] No crashes"

subsection "Rosetta 2 — x86 Apps"
ROSETTA_COUNT=$(file /Applications/*.app/Contents/MacOS/* 2>/dev/null | grep -c "x86_64" || echo "0")
echo "Apps requiring Rosetta (x86_64): $ROSETTA_COUNT"
echo ""

fi # end QUICK_MODE gate for sections 13-15

if [[ "$QUICK_MODE" == false ]]; then


# ═══════════════════════════════════════════════════════════════
# 16. SOFTWARE UPDATES
# ═══════════════════════════════════════════════════════════════
progress "16/$TOTAL_SECTIONS — Software Updates"
section "16. SOFTWARE UPDATES"
softwareupdate -l 2>/dev/null || echo "[INFO] Update check failed"
defaults read /Library/Preferences/com.apple.SoftwareUpdate.plist 2>/dev/null | head -20
subsection "Auto Update Settings"
defaults read /Library/Preferences/com.apple.commerce.plist 2>/dev/null || echo "[INFO] Commerce plist not available"
subsection "Install History (last 20)"
timeout 30 system_profiler SPInstallHistoryDataType 2>/dev/null | head -80
echo ""

# ═══════════════════════════════════════════════════════════════
# 17. KERNEL PANIC LOGS
# ═══════════════════════════════════════════════════════════════
progress "17/$TOTAL_SECTIONS — Kernel Panics"
section "17. KERNEL PANIC LOGS"
PANIC_COUNT=0
for d in /Library/Logs/DiagnosticReports /Library/Logs/CrashReporter "$ACTUAL_HOME/Library/Logs/DiagnosticReports"; do
    if ls "$d"/*.panic 2>/dev/null | head -1 >/dev/null 2>&1; then
        PANICS=$(ls -t "$d"/*.panic 2>/dev/null)
        THIS_COUNT=$(echo "$PANICS" | wc -l | tr -d ' ')
        PANIC_COUNT=$((PANIC_COUNT + THIS_COUNT))
        echo "Found $THIS_COUNT panics in $d"
        echo "$PANICS" | head -5
        echo ""
        LATEST=$(echo "$PANICS" | head -1)
        echo "=== LATEST PANIC: $LATEST ==="
        head -60 "$LATEST" 2>/dev/null
    fi
done
[[ "$PANIC_COUNT" -eq 0 ]] && echo "[OK] No kernel panics found"
echo "Total panic logs: $PANIC_COUNT"
echo ""

write_json_simple "kernel_panics" "$PANIC_COUNT"

# ═══════════════════════════════════════════════════════════════
# 18. I/O ERROR LOGS
# ═══════════════════════════════════════════════════════════════
progress "18/$TOTAL_SECTIONS — I/O Errors"
section "18. I/O ERROR LOGS"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "I/O error"' --style compact --last 7d 2>/dev/null | tail -20 || echo "[OK] No I/O errors"
subsection "Disk Arbitration Errors"
timeout 30 log show --predicate 'subsystem == "com.apple.DiskArbitration"' --style compact --last 7d 2>/dev/null | grep -iE "error|fail" | tail -10 || echo "[OK] No arbitration errors"
echo ""

# ═══════════════════════════════════════════════════════════════
# 19. GPU & DISPLAY ERRORS
# ═══════════════════════════════════════════════════════════════
progress "19/$TOTAL_SECTIONS — GPU Errors"
section "19. GPU & DISPLAY ERRORS"
timeout 30 log show --predicate 'process == "WindowServer" AND eventMessage CONTAINS[c] "error"' --style compact --last 7d 2>/dev/null | tail -15 || echo "[OK] No WindowServer errors"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "GPU" AND eventMessage CONTAINS[c] "error"' --style compact --last 7d 2>/dev/null | tail -10 || echo "[OK] No GPU errors"
subsection "GPU Restart History"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "GPU restart"' --style compact --last 30d 2>/dev/null | tail -5 || echo "[OK] No GPU restarts"
echo ""

# ═══════════════════════════════════════════════════════════════
# 20. USB ERROR LOGS
# ═══════════════════════════════════════════════════════════════
progress "20/$TOTAL_SECTIONS — USB Errors"
section "20. USB ERROR LOGS"
timeout 30 log show --predicate 'subsystem == "com.apple.usb" AND eventMessage CONTAINS[c] "error"' --style compact --last 7d 2>/dev/null | tail -15 || echo "[OK] No USB errors"
subsection "USB Overcurrent / Power"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "overcurrent" OR eventMessage CONTAINS[c] "USB power"' --style compact --last 30d 2>/dev/null | tail -10 || echo "[OK] No USB power issues"
echo ""

# ═══════════════════════════════════════════════════════════════
# 21. THERMAL EVENTS
# ═══════════════════════════════════════════════════════════════
progress "21/$TOTAL_SECTIONS — Thermal Events"
section "21. THERMAL EVENT LOGS"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "thermal" AND (eventMessage CONTAINS[c] "throttle" OR eventMessage CONTAINS[c] "shutdown" OR eventMessage CONTAINS[c] "warning")' --style compact --last 30d 2>/dev/null | tail -20 || echo "[OK] No thermal events"
echo ""

# ═══════════════════════════════════════════════════════════════
# 22. SHUTDOWN / SLEEP / WAKE LOGS
# ═══════════════════════════════════════════════════════════════
progress "22/$TOTAL_SECTIONS — Shutdown/Sleep/Wake"
section "22. SHUTDOWN / SLEEP / WAKE LOGS"
timeout 30 log show --predicate '(eventMessage CONTAINS[c] "SHUTDOWN" OR eventMessage CONTAINS[c] "Previous shutdown cause")' --style compact --last 30d 2>/dev/null | tail -20 || echo "[OK] No abnormal shutdowns"
subsection "Sleep/Wake Failures"
timeout 15 pmset -g log 2>/dev/null | grep -iE "Failure|DarkWake|Wake from" | tail -20
subsection "Hibernate Mode"
pmset -g 2>/dev/null | grep -i "hibernatemode"
echo ""

# ═══════════════════════════════════════════════════════════════
# 23. APPLICATION CRASH LOGS
# ═══════════════════════════════════════════════════════════════
progress "23/$TOTAL_SECTIONS — App Crash Logs"
section "23. APPLICATION CRASH LOGS (30 days)"
subsection "System Crash Reports"
timeout 30 find /Library/Logs/DiagnosticReports -name "*.crash" -mtime -30 -exec basename {} \; 2>/dev/null | sed 's/_[0-9][0-9][0-9][0-9]-.*//' | sort | uniq -c | sort -rn | head -20 || echo "[OK] No system crashes"
subsection "User Crash Reports"
find "$ACTUAL_HOME/Library/Logs/DiagnosticReports" -name "*.crash" -mtime -30 -exec basename {} \; 2>/dev/null | sed 's/_[0-9][0-9][0-9][0-9]-.*//' | sort | uniq -c | sort -rn | head -20 || echo "[OK] No user crashes"
subsection "Hang Reports"
timeout 30 find /Library/Logs/DiagnosticReports "$ACTUAL_HOME/Library/Logs/DiagnosticReports" -name "*.hang" -mtime -30 2>/dev/null | wc -l | tr -d ' ' | xargs -I {} echo "Hang reports (30d): {}"
subsection "Spin Dumps"
timeout 30 find /Library/Logs/DiagnosticReports "$ACTUAL_HOME/Library/Logs/DiagnosticReports" -name "*.spin" -mtime -30 2>/dev/null | wc -l | tr -d ' ' | xargs -I {} echo "Spin reports (30d): {}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 24. KERNEL ERRORS (30d)
# ═══════════════════════════════════════════════════════════════
progress "24/$TOTAL_SECTIONS — Kernel Errors (30d)"
section "24. KERNEL ERRORS — 30 DAY WINDOW"
timeout 30 log show --predicate 'process == "kernel" AND messageType == 16' --style compact --last 30d 2>/dev/null | tail -30 || echo "[OK] No kernel errors in 30 days"
subsection "Kernel Warning Count"
KWARN=$(timeout 30 log show --predicate 'process == "kernel" AND messageType == 16' --style compact --last 30d 2>/dev/null | wc -l | tr -d ' ' 2>/dev/null || echo "0")
echo "Kernel error/warning events (30d): $KWARN"
echo ""

# ═══════════════════════════════════════════════════════════════
# 25. PROCESS DEEP ANALYSIS
# ═══════════════════════════════════════════════════════════════
progress "25/$TOTAL_SECTIONS — Process Analysis"
section "25. PROCESS DEEP ANALYSIS"
subsection "Top 20 by CPU"
ps aux -r | head -21
subsection "Top 20 by Memory"
ps aux -m | head -21
subsection "Process Count by User"
ps aux | awk '{print $1}' | sort | uniq -c | sort -rn
TOTAL_PROCS=$(ps aux | wc -l | tr -d ' ')
echo "Total processes: $TOTAL_PROCS"

write_json_simple "total_processes" "${TOTAL_PROCS:-0}"

subsection "Zombie Processes"
ps aux | awk '$8 ~ /Z/ {print}' || echo "[OK] No zombies"
subsection "High CPU (>50%) Processes"
ps aux 2>/dev/null | awk 'NR>1 && $3>50.0 {print}' || echo "[OK] No high-CPU processes"
subsection "spindump (3s sample)"
timeout 10 spindump 3 3 -stdout 2>/dev/null | head -80 || echo "[INFO] spindump not available"
echo ""

# ═══════════════════════════════════════════════════════════════
# 26. PRINTERS
# ═══════════════════════════════════════════════════════════════
progress "26/$TOTAL_SECTIONS — Printers"
section "26. PRINTERS"
timeout 30 system_profiler SPPrintersDataType 2>/dev/null || echo "[INFO] No printers"
lpstat -p -d 2>/dev/null || echo "[INFO] CUPS not running"
subsection "Print Job History"
ls -lt /var/spool/cups/ 2>/dev/null | head -10 || echo "[INFO] No spool files"
echo ""

# ═══════════════════════════════════════════════════════════════
# 27. TIME MACHINE — DEEP
# ═══════════════════════════════════════════════════════════════
progress "27/$TOTAL_SECTIONS — Time Machine"
section "27. TIME MACHINE — DEEP"
tmutil destinationinfo 2>/dev/null || echo "[WARN] No Time Machine destination configured"
tmutil status 2>/dev/null
tmutil listbackups 2>/dev/null | tail -10 || echo "[INFO] No backups found"
subsection "Last Backup"
LAST_TM=$(defaults read /Library/Preferences/com.apple.TimeMachine.plist 2>/dev/null | grep -A1 "SnapshotDates" | tail -1 2>/dev/null || echo "Unknown")
echo "Last backup: $LAST_TM"
subsection "TM Preferences"
defaults read /Library/Preferences/com.apple.TimeMachine.plist 2>/dev/null | head -30
subsection "Third-Party Backup Agents"
for agent in "com.carbonite" "com.backblaze" "com.crashplan" "com.code42" "com.arqbackup" "com.econtechnologies" "com.cloudberry" "com.acronis"; do
    launchctl list 2>/dev/null | grep -i "$agent" && echo "[FOUND] $agent detected"
done
echo "[INFO] Backup agent scan complete"
echo ""

# ═══════════════════════════════════════════════════════════════
# 28. USERS & ACCOUNTS
# ═══════════════════════════════════════════════════════════════
progress "28/$TOTAL_SECTIONS — Users & Accounts"
section "28. USERS & ACCOUNTS"
timeout 10 dscl . list /Users UniqueID 2>/dev/null | awk '$2 >= 500 {print}'
subsection "Admin Users"
timeout 10 dscl . -read /Groups/admin GroupMembership 2>/dev/null
subsection "User Account Details"
for u in $(timeout 10 dscl . list /Users UniqueID 2>/dev/null | awk '$2 >= 500 {print $1}'); do
    echo ">>> User: $u"
    timeout 10 dscl . -read "/Users/$u" RealName 2>/dev/null | head -1
    LAST_LOGIN=$(last "$u" 2>/dev/null | head -1)
    echo "  Last login: $LAST_LOGIN"
    echo "  Home dir size: $(du -sh "/Users/$u" 2>/dev/null | awk '{print $1}' || echo 'Unknown')"
    sysadminctl -secureTokenStatus "$u" 2>&1 | sed 's/^/  /'
    echo ""
done
subsection "Guest Account"
timeout 10 dscl . -read /Users/Guest 2>/dev/null | head -5 || echo "[INFO] Guest account not configured"
echo ""

# ═══════════════════════════════════════════════════════════════
# 29. SPOTLIGHT
# ═══════════════════════════════════════════════════════════════
progress "29/$TOTAL_SECTIONS — Spotlight"
section "29. SPOTLIGHT"
timeout 10 mdutil -s / 2>/dev/null
timeout 10 mdutil -a -s 2>/dev/null
subsection "Index Size"
du -sh /.Spotlight-V100 2>/dev/null || echo "[INFO] Spotlight index not found at default location"
subsection "Privacy Exclusions"
defaults read /.Spotlight-V100/VolumeConfiguration.plist Exclusions 2>/dev/null || echo "[INFO] No exclusions"
echo ""

# ═══════════════════════════════════════════════════════════════
# 30. SYSTEM PREFERENCES & DEFAULTS
# ═══════════════════════════════════════════════════════════════
progress "30/$TOTAL_SECTIONS — System Preferences"
section "30. SYSTEM PREFERENCES & DEFAULTS"
subsection "Accessibility"
defaults read com.apple.universalaccess 2>/dev/null | head -20 || echo "[INFO] Default accessibility settings"
subsection "Energy Saver / Battery"
pmset -g custom 2>/dev/null
subsection "Screensaver / Lock"
echo "Lock delay: $(sysadminctl -screenLock status 2>/dev/null || echo 'Unknown')"
defaults read com.apple.screensaver 2>/dev/null | head -10 || echo "[INFO] Default screensaver"
subsection "Sharing"
echo "Computer Name: $(scutil --get ComputerName 2>/dev/null)"
echo "Local Hostname: $(scutil --get LocalHostName 2>/dev/null)"
sharing -l 2>/dev/null || echo "[INFO] Sharing status not available"
subsection "Location Services"
defaults read /var/db/locationd/clients.plist 2>/dev/null | head -20 || echo "[INFO] Location clients not readable"
echo ""

# ═══════════════════════════════════════════════════════════════
# 31. IOREGISTRY DEEP
# ═══════════════════════════════════════════════════════════════
progress "31/$TOTAL_SECTIONS — IORegistry"
section "31. IOREGISTRY DEEP"
subsection "ACPI Tables"
timeout 15 ioreg -rc IOACPIPlatformDevice 2>/dev/null | head -30 || echo "[INFO] No ACPI (Apple Silicon)"
subsection "PCI Devices"
timeout 15 ioreg -rc IOPCIDevice 2>/dev/null | grep -iE "name|vendor-id|device-id" | head -30 || echo "[INFO] No PCI devices"
subsection "NVMe Controller"
timeout 15 ioreg -rc IONVMeController 2>/dev/null | grep -iE "name|model|serial|firmware|capacity|life|wear" | head -20 || echo "[INFO] No NVMe"
subsection "USB Host Controllers"
timeout 15 ioreg -rc IOUSBHostDevice 2>/dev/null | grep -iE "Product|Vendor|speed|Power" | head -30
echo ""

# ═══════════════════════════════════════════════════════════════
# 32. CODE SIGNING INTEGRITY
# ═══════════════════════════════════════════════════════════════
progress "32/$TOTAL_SECTIONS — Code Signing"
section "32. CODE SIGNING INTEGRITY"
subsection "Critical System Binaries"
for bin in /usr/bin/sudo /usr/sbin/timeout 10 spctl /usr/libexec/ApplicationFirewall/socketfilterfw /usr/bin/ssh; do
    echo -n "$bin: "
    codesign -vv "$bin" 2>&1 | head -1
done
subsection "Gatekeeper Assessment (10 apps max)"
ls /Applications/*.app 2>/dev/null | head -10 | while read -r app; do
    echo -n "$(basename "$app"): "
    timeout 10 spctl -a -vv "$app" 2>&1 | head -1
done
echo ""

# ═══════════════════════════════════════════════════════════════
# 33. NETWORK SERVICES
# ═══════════════════════════════════════════════════════════════
progress "33/$TOTAL_SECTIONS — Network Services"
section "33. NETWORK SERVICES"
subsection "VPN"
scutil --nc list 2>/dev/null || echo "[INFO] No VPN configurations"
subsection "802.1X"
defaults read /Library/Preferences/SystemConfiguration/com.apple.network.eapolclient.configuration.plist 2>/dev/null || echo "[INFO] No 802.1X"
subsection "Signed Certificates (keychain)"
security find-identity -v 2>/dev/null | head -10 || echo "[INFO] No signing identities"
echo ""

# ═══════════════════════════════════════════════════════════════
# 34. VIRTUALISATION
# ═══════════════════════════════════════════════════════════════
progress "34/$TOTAL_SECTIONS — Virtualisation"
section "34. VIRTUALISATION"
sysctl kern.hv_support 2>/dev/null
echo "VMs in common locations:"
ls "$ACTUAL_HOME/Virtual Machines"/*.vmwarevm 2>/dev/null || echo "  No VMware VMs"
ls "$ACTUAL_HOME/Virtual Machines.localized/"*.vmwarevm 2>/dev/null || echo "  No VMware VMs (localized)"
ls "$ACTUAL_HOME/Parallels/"*.pvm 2>/dev/null || echo "  No Parallels VMs"
ls "$ACTUAL_HOME"/*.utm 2>/dev/null || echo "  No UTM VMs"
docker info 2>/dev/null | head -10 || echo "  Docker not installed/running"
echo ""

# ═══════════════════════════════════════════════════════════════
# 35. SYSCTL KERNEL PARAMETERS
# ═══════════════════════════════════════════════════════════════
progress "35/$TOTAL_SECTIONS — Sysctl"
section "35. SYSCTL KERNEL PARAMETERS"
subsection "Key Parameters"
sysctl kern.boottime kern.osversion kern.osrelease kern.hostname kern.maxproc kern.maxfilesperproc hw.memsize hw.ncpu 2>/dev/null
subsection "VM Stats"
sysctl vm.swapusage vm.page_free_count vm.page_pageable_internal_count 2>/dev/null
subsection "Network Tuning"
sysctl net.inet.tcp.mssdflt net.inet.tcp.sendspace net.inet.tcp.recvspace net.inet.tcp.win_scale_factor 2>/dev/null
echo ""

# ═══════════════════════════════════════════════════════════════
# 36-46. OCLP FULL VERIFICATION (11 subsections)
# ═══════════════════════════════════════════════════════════════
progress "36/$TOTAL_SECTIONS — OCLP Verification (11 checks)"
section "36. OPENCORE LEGACY PATCHER — FULL VERIFICATION"

OCLP_DETECTED="NO"
OCLP_VERSION="N/A"
OCLP_ROOT_PATCHED="NO"

subsection "36a. OCLP App Detection"
if [ -d "/Applications/OpenCore-Patcher.app" ]; then
    OCLP_DETECTED="YES"
    OCLP_VERSION=$(defaults read "/Applications/OpenCore-Patcher.app/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "Unknown")
    echo "[FOUND] OpenCore Legacy Patcher v${OCLP_VERSION}"
    echo "Bundle: $(defaults read "/Applications/OpenCore-Patcher.app/Contents/Info.plist" CFBundleIdentifier 2>/dev/null)"
else
    echo "[INFO] OpenCore-Patcher.app not found in /Applications"
fi
ls /Library/Application\ Support/Dortania/ 2>/dev/null && OCLP_DETECTED="YES" || echo "[INFO] No Dortania support files"

subsection "36b. EFI Partition"
EFI_DISK=$(diskutil list 2>/dev/null | grep -i "EFI" | head -1 | awk '{print $NF}')
if [[ -n "$EFI_DISK" ]]; then
    echo "EFI Partition: $EFI_DISK"
    mkdir -p /tmp/za_efi_mount 2>/dev/null
    mount -t msdos /dev/$EFI_DISK /tmp/za_efi_mount 2>/dev/null
    if [ -d "/tmp/za_efi_mount/EFI" ]; then
        echo "EFI Structure:"
        timeout 30 find /tmp/za_efi_mount/EFI -maxdepth 3 -type f 2>/dev/null | head -30
        subsection "36c. config.plist Analysis"
        CONFIG_PLIST="/tmp/za_efi_mount/EFI/OC/config.plist"
        if [ -f "$CONFIG_PLIST" ]; then
            echo "config.plist found"
            echo "SMBIOS Model: $(plutil -extract PlatformInfo.Generic.SystemProductName raw "$CONFIG_PLIST" 2>/dev/null || echo 'Not found')"
            echo "SecureBootModel: $(plutil -extract Misc.Security.SecureBootModel raw "$CONFIG_PLIST" 2>/dev/null || echo 'Not found')"
            echo "SIP (csr-active-config): $(plutil -extract NVRAM.Add.7C436110-AB2A-4BBB-A880-FE41995C9F82.csr-active-config raw "$CONFIG_PLIST" 2>/dev/null || echo 'Not found')"
            echo "Boot Args: $(plutil -extract NVRAM.Add.7C436110-AB2A-4BBB-A880-FE41995C9F82.boot-args raw "$CONFIG_PLIST" 2>/dev/null || echo 'Not found')"
            echo "ApECID: $(plutil -extract Misc.Security.ApECID raw "$CONFIG_PLIST" 2>/dev/null || echo 'Not found')"
            echo "Vault: $(plutil -extract Misc.Security.Vault raw "$CONFIG_PLIST" 2>/dev/null || echo 'Not found')"
            echo ""
            echo "Kexts in config.plist:"
            plutil -extract Kernel.Add json "$CONFIG_PLIST" 2>/dev/null | python3 -c "import sys,json; [print(f'  {k[\"BundlePath\"]} (enabled={k.get(\"Enabled\",True)})') for k in json.load(sys.stdin)]" 2>/dev/null || echo "[INFO] Could not parse kexts"
        else
            echo "[INFO] No OC config.plist found"
        fi
    fi
    umount /tmp/za_efi_mount 2>/dev/null
    rmdir /tmp/za_efi_mount 2>/dev/null
fi

subsection "36d. NVRAM OpenCore Keys"
nvram -p 2>/dev/null | grep -iE "opencore|4D1FDA02|revpatch|revblock" | head -10 || echo "[INFO] No OpenCore NVRAM keys"

subsection "36e. Root Patches Applied"
if [ -f "/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist" ]; then
    OCLP_ROOT_PATCHED="YES"
    echo "[FOUND] Root patches applied"
    defaults read "/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist" 2>/dev/null | head -20
else
    echo "[INFO] No root patches detected"
fi

subsection "36f. Third-Party Kexts (loaded)"
timeout 15 kextstat 2>/dev/null | grep -v com.apple | while read -r line; do
    echo "  $line"
done
THIRD_KEXT_COUNT=$(timeout 15 kextstat 2>/dev/null | grep -vc com.apple || echo "0")
echo "Third-party kexts: $THIRD_KEXT_COUNT"

subsection "36g. GPU Acceleration"
timeout 30 system_profiler SPDisplaysDataType 2>/dev/null | grep -iE "Metal|OpenGL|Chipset|VRAM"

subsection "36h. OCLP Log Files"
ls -lt "$ACTUAL_HOME/Library/Logs/Dortania/"*.log 2>/dev/null | head -5
LATEST_OCLP_LOG=$(ls -t "$ACTUAL_HOME/Library/Logs/Dortania/"*.log 2>/dev/null | head -1)
[[ -n "$LATEST_OCLP_LOG" ]] && tail -30 "$LATEST_OCLP_LOG" 2>/dev/null

subsection "36i. OCLP Unified Log Errors"
timeout 30 log show --predicate 'eventMessage CONTAINS[c] "OpenCore" OR eventMessage CONTAINS[c] "Dortania"' --style compact --last 7d 2>/dev/null | tail -15 || echo "[OK] No OCLP errors"

subsection "36j. OCLP Status Matrix"
echo "╔═══════════════════════════╦══════════╗"
echo "║ Check                     ║ Status   ║"
echo "╠═══════════════════════════╬══════════╣"
echo "║ OCLP App                  ║ $OCLP_DETECTED       ║"
echo "║ OCLP Version              ║ $OCLP_VERSION    ║"
echo "║ Root Patched              ║ $OCLP_ROOT_PATCHED       ║"
echo "║ Third-Party Kexts         ║ $THIRD_KEXT_COUNT        ║"
echo "║ SIP Status                ║ $(csrutil status 2>/dev/null | awk '{print $NF}') ║"
echo "╚═══════════════════════════╩══════════╝"
echo ""

write_json "oclp" \
    "detected" "$OCLP_DETECTED" \
    "version" "$OCLP_VERSION" \
    "root_patched" "$OCLP_ROOT_PATCHED" \
    "third_party_kexts" "$THIRD_KEXT_COUNT"

# ═══════════════════════════════════════════════════════════════
# 47. USAGE PATTERNS — CoreDuet / Screen Time
# ═══════════════════════════════════════════════════════════════
progress "47/$TOTAL_SECTIONS — Usage Patterns (CoreDuet)"
section "47. USAGE PATTERNS — APP USAGE & SCREEN TIME"

subsection "App Usage (CoreDuet — top 30 by duration)"
COREDUET_DB="/private/var/db/CoreDuet/Knowledge/knowledgeC.db"
if [ -f "$COREDUET_DB" ]; then
    timeout 10 sqlite3 "$COREDUET_DB" "
        SELECT 
            ZOBJECT.ZVALUESTRING AS app_bundle,
            ROUND(SUM(ZENDDATE - ZSTARTDATE) / 3600.0, 2) AS hours_used,
            COUNT(*) AS sessions
        FROM ZOBJECT 
        WHERE ZSTREAMNAME = '/app/usage'
            AND ZSTARTDATE > (strftime('%s', 'now') - 978307200 - 2592000)
        GROUP BY ZOBJECT.ZVALUESTRING
        ORDER BY hours_used DESC
        LIMIT 30;
    " 2>/dev/null || echo "[INFO] Could not query CoreDuet"
    
    subsection "Screen Time (daily averages, last 30d)"
    timeout 10 sqlite3 "$COREDUET_DB" "
        SELECT 
            DATE(ZSTARTDATE + 978307200, 'unixepoch', 'localtime') AS day,
            ROUND(SUM(ZENDDATE - ZSTARTDATE) / 3600.0, 1) AS hours_active,
            COUNT(DISTINCT ZVALUESTRING) AS unique_apps
        FROM ZOBJECT 
        WHERE ZSTREAMNAME = '/app/usage'
            AND ZSTARTDATE > (strftime('%s', 'now') - 978307200 - 2592000)
        GROUP BY day
        ORDER BY day DESC
        LIMIT 30;
    " 2>/dev/null || echo "[INFO] Screen time query failed"
    
    subsection "App Launch Frequency (top 20)"
    timeout 10 sqlite3 "$COREDUET_DB" "
        SELECT 
            ZOBJECT.ZVALUESTRING AS app_bundle,
            COUNT(*) AS launches
        FROM ZOBJECT 
        WHERE ZSTREAMNAME = '/app/inFocus'
            AND ZSTARTDATE > (strftime('%s', 'now') - 978307200 - 2592000)
        GROUP BY ZOBJECT.ZVALUESTRING
        ORDER BY launches DESC
        LIMIT 20;
    " 2>/dev/null || echo "[INFO] Launch frequency query failed"
else
    echo "[INFO] CoreDuet database not found"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 48. APPLICATION RESOURCE CONSUMPTION
# ═══════════════════════════════════════════════════════════════
progress "48/$TOTAL_SECTIONS — App Resource Consumption"
section "48. APPLICATION RESOURCE CONSUMPTION (POINT-IN-TIME)"

subsection "Memory by Application (top 20)"
ps aux -m 2>/dev/null | awk 'NR==1 || NR<=21 {printf "%-8s %6s %6s %s\n", $1, $3, $4, $11}' || true

subsection "Resident Memory by Process (sorted)"
ps -eo rss,comm 2>/dev/null | sort -rn | head -20 | awk '{printf "%8.1f MB  %s\n", $1/1024, $2}'

subsection "App-Level Summary (combine by app name)"
ps -eo rss,comm 2>/dev/null | awk '{mem[$2]+=$1} END {for (a in mem) printf "%8.1f MB  %s\n", mem[a]/1024, a}' | sort -rn | head -20

subsection "Chrome/Browser Tab Memory"
ps aux 2>/dev/null | grep -i "[C]hrome.*Helper" | wc -l | xargs -I {} echo "Chrome helper processes (≈tabs): {}"
ps aux 2>/dev/null | grep -i "[S]afari.*Web" | wc -l | xargs -I {} echo "Safari web processes (≈tabs): {}"
ps aux 2>/dev/null | grep -i "[F]irefox.*Web" | wc -l | xargs -I {} echo "Firefox web processes (≈tabs): {}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 49. FONT VALIDATION
# ═══════════════════════════════════════════════════════════════
progress "49/$TOTAL_SECTIONS — Fonts"
section "49. FONT VALIDATION"
FONT_COUNT=$(timeout 30 find /Library/Fonts "$ACTUAL_HOME/Library/Fonts" /System/Library/Fonts -type f 2>/dev/null | wc -l | tr -d ' ')
echo "Total fonts installed: $FONT_COUNT"
atsutil fonts -list 2>/dev/null | head -5 || echo "[INFO] atsutil not available"
subsection "Font Cache"
atsutil databases -remove 2>/dev/null && echo "[OK] Font cache cleared for fresh validation" || echo "[INFO] Could not clear font cache"
echo ""

# ═══════════════════════════════════════════════════════════════
# 50. TCC PRIVACY LOG (7d)
# ═══════════════════════════════════════════════════════════════
progress "50/$TOTAL_SECTIONS — TCC Privacy Events"
section "50. TCC PRIVACY ACCESS LOG (7d)"
timeout 30 log show --predicate 'subsystem == "com.apple.TCC"' --style compact --last 7d 2>/dev/null | grep -iE "request|denied|prompt" | tail -30 || echo "[OK] No TCC events"
echo ""

# ═══════════════════════════════════════════════════════════════
# 51. WiFi DIAGNOSTICS DUMP
# ═══════════════════════════════════════════════════════════════
progress "51/$TOTAL_SECTIONS — WiFi Diagnostics"
section "51. WiFi DIAGNOSTICS (DETAILED)"
subsection "Recent WiFi Drops"
timeout 30 log show --predicate 'subsystem == "com.apple.wifi" AND eventMessage CONTAINS[c] "disassociat"' --style compact --last 7d 2>/dev/null | tail -15 || echo "[OK] No WiFi drops"
subsection "WiFi Connection Events"
timeout 30 log show --predicate 'subsystem == "com.apple.wifi" AND eventMessage CONTAINS[c] "associat"' --style compact --last 7d 2>/dev/null | tail -15 || echo "[INFO] No WiFi events"
subsection "WiFi Scan (Current Environment)"
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -s 2>/dev/null || echo "[INFO] WiFi scan not available"
echo ""

# ═══════════════════════════════════════════════════════════════
# 52. POWER HISTORY (FULL pmset -g log)
# ═══════════════════════════════════════════════════════════════
progress "52/$TOTAL_SECTIONS — Power History"
section "52. POWER HISTORY (pmset log — key events)"
timeout 15 pmset -g log 2>/dev/null | grep -iE "Wake from|Sleep|DarkWake|Charge|Shutdown|Restart|Hibernate|Lid|AC|Battery" | tail -40
echo ""

# ═══════════════════════════════════════════════════════════════
# 53. ACCESSIBILITY & ASSISTIVE TECH
# ═══════════════════════════════════════════════════════════════
progress "53/$TOTAL_SECTIONS — Accessibility"
section "53. ACCESSIBILITY & ASSISTIVE TECHNOLOGY"
defaults read com.apple.universalaccess 2>/dev/null | grep -iE "voiceOver|zoom|reduceMotion|highContrast|differentiateWithoutColor|switchControl" | head -10 || echo "[INFO] Default accessibility"
subsection "TCC Accessibility Grants"
timeout 10 sqlite3 "/Library/Application Support/com.apple.TCC/TCC.db" "SELECT client, auth_value FROM access WHERE service='kTCCServiceAccessibility';" 2>/dev/null || echo "[INFO] No accessibility grants"
echo ""

# ═══════════════════════════════════════════════════════════════
# 54. iCLOUD & APPLE SERVICES STATUS
# ═══════════════════════════════════════════════════════════════
progress "54/$TOTAL_SECTIONS — iCloud & Apple Services"
section "54. iCLOUD & APPLE SERVICES"
subsection "iCloud Status"
defaults read MobileMeAccounts 2>/dev/null | head -15 || echo "[INFO] No iCloud accounts readable"
subsection "iCloud Drive"
ls "$ACTUAL_HOME/Library/Mobile Documents/com~apple~CloudDocs/" 2>/dev/null | head -10 || echo "[INFO] iCloud Drive not accessible"
brctl status 2>/dev/null | head -10 || echo "[INFO] brctl not available"
subsection "iCloud Sync Errors"
timeout 30 log show --predicate 'subsystem == "com.apple.cloudd" AND eventMessage CONTAINS[c] "error"' --style compact --last 7d 2>/dev/null | tail -10 || echo "[OK] No iCloud sync errors"
subsection "Apple Push Notifications"
timeout 30 log show --predicate 'subsystem == "com.apple.apsd"' --style compact --last 1d 2>/dev/null | grep -iE "error|fail|disconnect" | tail -5 || echo "[OK] No push notification errors"
echo ""

# ═══════════════════════════════════════════════════════════════
# 55. DISK ENCRYPTION DEEP
# ═══════════════════════════════════════════════════════════════
progress "55/$TOTAL_SECTIONS — Disk Encryption"
section "55. DISK ENCRYPTION — DEEP"
fdesetup status 2>/dev/null
fdesetup list 2>/dev/null || echo "[INFO] FileVault users not listed"
diskutil apfs listCryptoUsers disk1 2>/dev/null || echo "[INFO] No crypto users"
subsection "Volume Encryption"
diskutil apfs list 2>/dev/null | grep -iE "encrypt|locked|role"
echo ""

# ═══════════════════════════════════════════════════════════════
# 56. MAIL, CALENDAR & ACCOUNTS
# ═══════════════════════════════════════════════════════════════
progress "56/$TOTAL_SECTIONS — Mail & Accounts"
section "56. MAIL, CALENDAR & INTERNET ACCOUNTS"
subsection "Configured Accounts (types only — no credentials)"
defaults read "$ACTUAL_HOME/Library/Preferences/com.apple.mail.plist" 2>/dev/null | grep -iE "AccountName|AccountType|EmailAddress" | head -15 || echo "[INFO] No Mail accounts"
MAIL_COUNT=$(defaults read "$ACTUAL_HOME/Library/Preferences/com.apple.mail.plist" 2>/dev/null | grep -c "AccountName" || echo "0")
echo "Email accounts configured: $MAIL_COUNT"
subsection "Mail Data Size"
du -sh "$ACTUAL_HOME/Library/Mail" 2>/dev/null || echo "[INFO] No Mail data"
subsection "Calendar Accounts"
defaults read "$ACTUAL_HOME/Library/Calendars/" 2>/dev/null | head -10 || echo "[INFO] No calendar data readable"
echo ""

fi # end QUICK_MODE gate for sections 16-56

# ═══════════════════════════════════════════════════════════════
# 57. PASSWORD MANAGER DETECTION
# ═══════════════════════════════════════════════════════════════
progress "57/$TOTAL_SECTIONS — Password Managers"
section "57. PASSWORD MANAGER DETECTION"
PWMGR_FOUND=""
for pm in "1Password" "Bitwarden" "Dashlane" "LastPass" "KeePassXC" "Keeper" "NordPass" "RoboForm" "Enpass"; do
    if [ -d "/Applications/${pm}.app" ] || [ -d "/Applications/${pm} 7.app" ]; then
        echo "[FOUND] Password manager detected"
        PWMGR_FOUND="$PWMGR_FOUND $pm"
    fi
done
[[ -z "$PWMGR_FOUND" ]] && echo "[WARN] No password manager detected"
subsection "Apple Keychain Items (count)"
security dump-keychain 2>/dev/null | grep -c "class:" | xargs -I {} echo "Keychain entries: {}" || echo "[INFO] Keychain not readable"
echo ""

write_json_simple "password_manager" "${PWMGR_FOUND:-NONE}"

# ═══════════════════════════════════════════════════════════════
# 58. ANTIVIRUS / EDR DETECTION
# ═══════════════════════════════════════════════════════════════
progress "58/$TOTAL_SECTIONS — Antivirus / EDR"
section "58. ANTIVIRUS / EDR / SECURITY SOFTWARE"
AV_FOUND=""
for av in "Malwarebytes" "Sophos" "Norton" "McAfee" "Avast" "AVG" "Bitdefender" "ESET" "Kaspersky" "CrowdStrike Falcon" "SentinelOne" "Carbon Black" "Jamf Protect" "Intune" "Kandji" "Mosyle" "Addigy" "Hexnode"; do
    if [ -d "/Applications/${av}.app" ] || ls /Library/LaunchDaemons/ 2>/dev/null | grep -qi "$(echo "$av" | tr ' ' '.' | tr '[:upper:]' '[:lower:]')"; then
        echo "[FOUND] Security software detected"
        AV_FOUND="$AV_FOUND $av"
    fi
done
[[ -z "$AV_FOUND" ]] && echo "[INFO] No additional security software detected — macOS built-in protection active"
echo ""

write_json_simple "av_edr" "${AV_FOUND:-NONE}"

# ═══════════════════════════════════════════════════════════════
# 59. SCHEDULED TASKS & AUTOMATION
# ═══════════════════════════════════════════════════════════════
progress "59/$TOTAL_SECTIONS — Scheduled Tasks"
section "59. SCHEDULED TASKS & AUTOMATION"
subsection "at jobs"
atq 2>/dev/null || echo "[INFO] No at jobs"
subsection "periodic tasks"
ls /etc/periodic/daily/ /etc/periodic/weekly/ /etc/periodic/monthly/ 2>/dev/null
subsection "Automator Workflows"
find "$ACTUAL_HOME/Library/Services" -name "*.workflow" 2>/dev/null | head -10 || echo "[INFO] No Automator workflows"
subsection "Shortcuts"
find "$ACTUAL_HOME/Library/Shortcuts" -type f 2>/dev/null | head -10 || echo "[INFO] No Shortcuts"
echo ""

# ═══════════════════════════════════════════════════════════════
# 60. EXTERNAL DRIVES & VOLUMES
# ═══════════════════════════════════════════════════════════════
progress "60/$TOTAL_SECTIONS — External Drives"
section "60. EXTERNAL DRIVES & VOLUMES"
diskutil list external 2>/dev/null || echo "[INFO] No external drives"
mount | grep -v "^/" | head -10
ls /Volumes/ 2>/dev/null
echo ""

# ═══════════════════════════════════════════════════════════════
# 61. SYSTEM INTEGRITY SUMMARY
# ═══════════════════════════════════════════════════════════════
progress "61/$TOTAL_SECTIONS — System Integrity"
section "61. SYSTEM INTEGRITY SUMMARY"
echo "SIP:                 $(csrutil status 2>/dev/null | head -1)"
echo "Auth Root:           $(csrutil authenticated-root status 2>/dev/null | head -1 || echo 'N/A')"
echo "Gatekeeper:          $(spctl --status 2>/dev/null)"
echo "FileVault:           $(fdesetup status 2>/dev/null)"
echo "Firewall:            $(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)"
echo "XProtect:            $XPROTECT_VER"
echo "MRT:                 $MRT_VER"
echo "Kernel Panics:       $PANIC_COUNT"
echo "Third-Party Kexts:   $THIRD_KEXT_COUNT"
echo "OCLP:                $OCLP_DETECTED (v${OCLP_VERSION})"
echo "OCLP Root Patched:   $OCLP_ROOT_PATCHED"
echo "Password Manager:    ${PWMGR_FOUND:-NONE}"
echo "AV/EDR:              ${AV_FOUND:-NONE (XProtect only)}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 62. HARDWARE DIAGNOSTICS SUMMARY
# ═══════════════════════════════════════════════════════════════
progress "62/$TOTAL_SECTIONS — Hardware Summary"
section "62. HARDWARE DIAGNOSTICS SUMMARY"
echo "Serial:              $SERIAL"
echo "Chip:                $CHIP_TYPE"
echo "RAM:                 ${TOTAL_RAM} GB"
echo "RAM Upgradeable:     $RAM_UPGRADEABLE"
echo "Battery Health:      ${HEALTH:-N/A}%"
echo "Battery Cycles:      ${CYCLE:-N/A}"
echo "Battery Condition:   ${BATT_CONDITION:-N/A}"
echo "Boot Disk Used:      ${DISK_USED_PCT:-N/A}%"
echo "Boot Disk Free:      ${DISK_FREE_GB:-N/A} GB"
echo "Total Processes:     ${TOTAL_PROCS:-N/A}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 63. ML / COREML MODEL INVENTORY
# ═══════════════════════════════════════════════════════════════
progress "63/$TOTAL_SECTIONS — ML / CoreML model inventory"
section "63. ML / COREML MODEL INVENTORY"

ML_MODEL_COUNT=$(timeout 30 find /Applications /Library /Users 2>/dev/null \
    -name "*.mlmodelc" -maxdepth 8 | wc -l | tr -d ' ')
COREML_FRAMEWORK="NO"
[ -d "/System/Library/Frameworks/CoreML.framework" ] && COREML_FRAMEWORK="YES"
CREATE_ML="NO"
[ -d "/Applications/Create ML.app" ] && CREATE_ML="YES"
ANEUSERD_RUNNING="NO"
pgrep -x aneuserd &>/dev/null && ANEUSERD_RUNNING="YES"

echo "CoreML framework:  $COREML_FRAMEWORK"
echo "Create ML app:     $CREATE_ML"
echo "Compiled models:   $ML_MODEL_COUNT"
echo "ANE daemon active: $ANEUSERD_RUNNING"
echo ""

write_json "ml_coreml" \
    "coreml_framework"   "$COREML_FRAMEWORK" \
    "create_ml_app"      "$CREATE_ML" \
    "mlmodelc_count"     "$ML_MODEL_COUNT" \
    "ane_daemon_running" "$ANEUSERD_RUNNING"

# ═══════════════════════════════════════════════════════════════
# 64. SIRI & DICTATION CONFIGURATION
# ═══════════════════════════════════════════════════════════════
progress "64/$TOTAL_SECTIONS — Siri & Dictation configuration"
section "64. SIRI & DICTATION CONFIGURATION"

SIRI_ENABLED=$(defaults read com.apple.assistant.support "Assistant Enabled" 2>/dev/null || echo "unknown")
DICTATION_ENABLED=$(defaults read com.apple.HIToolbox AppleDictationAutoEnable 2>/dev/null || echo "0")
DICTATION_LANG=$(defaults read com.apple.speech.recognition.AppleSpeechRecognition.prefs \
    SpeechDefaultLocaleIdentifier 2>/dev/null || echo "unknown")
SIRI_VOICE_FEEDBACK=$(defaults read com.apple.Siri VoiceTriggerUserEnabled 2>/dev/null || echo "unknown")

echo "Siri enabled:       $SIRI_ENABLED"
echo "Voice trigger:      $SIRI_VOICE_FEEDBACK"
echo "Dictation enabled:  $DICTATION_ENABLED"
echo "Dictation language: $DICTATION_LANG"
echo ""

write_json "siri_dictation" \
    "siri_enabled"       "$SIRI_ENABLED" \
    "voice_trigger"      "$SIRI_VOICE_FEEDBACK" \
    "dictation_enabled"  "$DICTATION_ENABLED" \
    "dictation_language" "$DICTATION_LANG"

# ═══════════════════════════════════════════════════════════════
# 65. FOCUS MODES & DO NOT DISTURB
# ═══════════════════════════════════════════════════════════════
progress "65/$TOTAL_SECTIONS — Focus modes & Do Not Disturb"
section "65. FOCUS MODES & DO NOT DISTURB"

FOCUS_MODE_COUNT=0
FOCUS_DB="/Users/$ACTUAL_USER/Library/DoNotDisturb/DB/ModeConfigurations.json"
if [ -f "$FOCUS_DB" ]; then
    FOCUS_MODE_COUNT=$(python3 -c "
import json
with open('$FOCUS_DB') as f:
    d = json.load(f)
modes = d.get('data', [{}])[0].get('modeConfigurations', {})
print(len(modes))
" 2>/dev/null || echo "0")
fi

DND_ACTIVE="NO"
if [ -f "/Users/$ACTUAL_USER/Library/DoNotDisturb/DB/Assertions.json" ]; then
    DND_ACTIVE=$(python3 -c "
import json
with open('/Users/$ACTUAL_USER/Library/DoNotDisturb/DB/Assertions.json') as f:
    d = json.load(f)
entries = d.get('data', [{}])[0].get('storeAssertionRecords', [])
print('YES' if entries else 'NO')
" 2>/dev/null || echo "NO")
fi

echo "Focus modes configured: $FOCUS_MODE_COUNT"
echo "DND currently active:   $DND_ACTIVE"
echo ""

write_json "focus_modes" \
    "focus_mode_count" "$FOCUS_MODE_COUNT" \
    "dnd_active"       "$DND_ACTIVE"

# ═══════════════════════════════════════════════════════════════
# 66. UNIVERSAL CONTROL / HANDOFF / CONTINUITY
# ═══════════════════════════════════════════════════════════════
progress "66/$TOTAL_SECTIONS — Universal Control / Handoff / Continuity"
section "66. UNIVERSAL CONTROL / HANDOFF / CONTINUITY"

HANDOFF_ENABLED=$(defaults read /Users/"$ACTUAL_USER"/Library/Preferences/ByHost/com.apple.coreduet.sync.plist \
    HandoffEnabled 2>/dev/null || defaults read com.apple.coreduet.sync HandoffEnabled 2>/dev/null || echo "unknown")
AIRDROP_MODE=$(defaults read com.apple.NetworkBrowser DisableAirDrop 2>/dev/null \
    && echo "disabled" || echo "enabled")
AIRPLAY_RECEIVER=$(defaults read com.apple.controlcenter AirplayRecieverEnabled 2>/dev/null || echo "unknown")
UNIVERSAL_CTRL=$(defaults read com.apple.universalcontrol Disable 2>/dev/null \
    && echo "disabled" || echo "enabled")

echo "Handoff enabled:       $HANDOFF_ENABLED"
echo "AirDrop:               $AIRDROP_MODE"
echo "AirPlay receiver:      $AIRPLAY_RECEIVER"
echo "Universal Control:     $UNIVERSAL_CTRL"
echo ""

write_json "continuity" \
    "handoff_enabled"    "$HANDOFF_ENABLED" \
    "airdrop"            "$AIRDROP_MODE" \
    "airplay_receiver"   "$AIRPLAY_RECEIVER" \
    "universal_control"  "$UNIVERSAL_CTRL"

# ═══════════════════════════════════════════════════════════════
# 67. DISK I/O SCHEDULING & QoS
# ═══════════════════════════════════════════════════════════════
progress "67/$TOTAL_SECTIONS — Disk I/O scheduling & QoS"
section "67. DISK I/O SCHEDULING & QoS"

IO_STATS=$(iostat -d -c 3 2>/dev/null | tail -1 | awk '{print "KB/t="$1" tps="$2" MB/s="$3}' || echo "unavailable")
VM_PAGEINS=$(vm_stat 2>/dev/null | awk '/Pages paged in/{gsub(/\./,"",$NF); print $NF}' || echo "0")
VM_PAGEOUTS=$(vm_stat 2>/dev/null | awk '/Pages paged out/{gsub(/\./,"",$NF); print $NF}' || echo "0")
VM_SWAPUSED=$(sysctl vm.swapusage 2>/dev/null | awk '{print $7}' || echo "0")
DISK_QOS=$(timeout 30 log show --predicate 'subsystem == "com.apple.iokit"' \
    --last 10m --style compact 2>/dev/null | grep -c "QoS" 2>/dev/null || echo "0")

echo "iostat summary:  $IO_STATS"
echo "VM pages in:     $VM_PAGEINS"
echo "VM pages out:    $VM_PAGEOUTS"
echo "Swap used:       $VM_SWAPUSED"
echo "QoS log events:  $DISK_QOS (last 10 min)"
echo ""

write_json "disk_io_qos" \
    "iostat_summary" "$IO_STATS" \
    "vm_pageins"     "$VM_PAGEINS" \
    "vm_pageouts"    "$VM_PAGEOUTS" \
    "swap_used"      "$VM_SWAPUSED" \
    "qos_log_events" "$DISK_QOS"

# ═══════════════════════════════════════════════════════════════
# APPLICATION CRASH REPORTS
# ═══════════════════════════════════════════════════════════════
progress "CRASH/$TOTAL_SECTIONS — Application Crash Reports"
section "APPLICATION CRASH REPORTS"

echo "── Recent Crash Reports (last 30 days) ──"
timeout 30 find /Library/Logs/DiagnosticReports "$ACTUAL_HOME/Library/Logs/DiagnosticReports" \
    -name "*.crash" -mtime -30 2>/dev/null | while read -r f; do
    echo ""
    echo "File: $(basename "$f")"
    echo "Date: $(stat -f '%Sm' -t '%d/%m/%Y %H:%M' "$f" 2>/dev/null)"
    head -20 "$f" 2>/dev/null | grep -E 'Process:|Path:|Version:|Exception|Crashed Thread|Thread 0'
done

CRASH_COUNT=$(timeout 10 find /Library/Logs/DiagnosticReports "$ACTUAL_HOME/Library/Logs/DiagnosticReports" \
    -name "*.crash" -mtime -30 2>/dev/null | wc -l | tr -d ' ')
echo ""
echo "Total crash reports (30 days): ${CRASH_COUNT:-0}"

echo ""
echo "── Kernel Panics (last 90 days) ──"
timeout 30 find /Library/Logs/DiagnosticReports -name "*.panic" -mtime -90 2>/dev/null | while read -r f; do
    echo "Panic: $(basename "$f") — $(stat -f '%Sm' -t '%d/%m/%Y %H:%M' "$f" 2>/dev/null)"
    head -10 "$f" 2>/dev/null | grep -E 'panic|Kernel|BSD'
done
PANIC_COUNT=$(timeout 10 find /Library/Logs/DiagnosticReports -name "*.panic" -mtime -90 2>/dev/null | wc -l | tr -d ' ')
echo "Total kernel panics (90 days): ${PANIC_COUNT:-0}"

echo ""
echo "── Hang Reports (last 30 days) ──"
HANG_COUNT=$(timeout 10 find /Library/Logs/DiagnosticReports "$ACTUAL_HOME/Library/Logs/DiagnosticReports" \
    -name "*.hang" -mtime -30 2>/dev/null | wc -l | tr -d ' ')
echo "${HANG_COUNT:-0} application hang reports"

write_json "crash_data" \
    "crash_reports_30d" "${CRASH_COUNT:-0}" \
    "kernel_panics_90d" "${PANIC_COUNT:-0}" \
    "hang_reports_30d"  "${HANG_COUNT:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# PERFORMANCE DEEP ANALYSIS
# ═══════════════════════════════════════════════════════════════
progress "PERF/$TOTAL_SECTIONS — Performance Deep Analysis"
section "PERFORMANCE DEEP ANALYSIS"

echo "── Top 15 CPU Consumers ──"
ps aux 2>/dev/null | sort -nrk 3 | head -16 | awk '{printf "%-6s %5s%% CPU  %5s%% MEM  %s\n", $2, $3, $4, $11}'

echo ""
echo "── Top 15 Memory Consumers ──"
ps aux 2>/dev/null | sort -nrk 4 | head -16 | awk '{printf "%-6s %5s%% MEM  %5s%% CPU  %s\n", $2, $4, $3, $11}'

echo ""
echo "── Memory Breakdown ──"
vm_stat 2>/dev/null | awk '/Pages/{gsub(/\./,"",$NF); printf "%-30s %10s pages (%s MB)\n", $1" "$2" "$3, $NF, int($NF*4096/1048576)}'

echo ""
echo "── Swap Usage ──"
sysctl vm.swapusage 2>/dev/null

echo ""
echo "── Process Count by User ──"
ps aux 2>/dev/null | awk 'NR>1{print $1}' | sort | uniq -c | sort -rn | head -10

echo ""
echo "── Applications Using >100MB Memory ──"
ps aux 2>/dev/null | awk 'NR>1 && $6>102400{printf "%-40s %6.0f MB  %5s%% CPU\n", $11, $6/1024, $3}' | sort -nrk2 | head -15

echo ""
echo "── Long-Running Processes (>24 hours) ──"
ps -eo pid,etime,comm 2>/dev/null | awk '$2 ~ /-/{print $0}' | head -10

PERF_PROCS=$(ps aux 2>/dev/null | wc -l | tr -d ' ')
PERF_SWAP=$(sysctl vm.swapusage 2>/dev/null | awk -F'used = ' '{print $2}' | awk '{print $1}')

write_json "performance_deep" \
    "total_processes" "${PERF_PROCS:-0}" \
    "swap_used"       "${PERF_SWAP:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# SYSTEM CONSOLE LOG ANALYSIS
# ═══════════════════════════════════════════════════════════════
progress "CONSOLE/$TOTAL_SECTIONS — System Console Analysis"
section "SYSTEM CONSOLE LOG ANALYSIS"

echo "── Critical System Errors (last 24 hours) ──"
timeout 30 log show --predicate 'messageType == error' --style compact --last 24h 2>/dev/null | \
    awk '{print $NF}' | sort | uniq -c | sort -rn | head -20 || echo "[TIMEOUT] Console log query exceeded 30 seconds"

echo ""
echo "── Fault-Level Events (last 24 hours) ──"
timeout 30 log show --predicate 'messageType == fault' --style compact --last 24h 2>/dev/null | \
    awk -F']' '{print $NF}' | sort | uniq -c | sort -rn | head -15 || echo "[TIMEOUT]"

echo ""
echo "── Authentication Failures (last 7 days) ──"
timeout 30 log show --predicate 'category == "authorization" AND messageType == error' \
    --style compact --last 7d 2>/dev/null | head -20 || echo "[TIMEOUT]"

echo ""
echo "── Disk Errors in Console (last 7 days) ──"
timeout 30 log show --predicate 'subsystem == "com.apple.DiskManagement"' \
    --style compact --last 7d 2>/dev/null | grep -iE 'error|fail|warning' | head -15 || echo "[TIMEOUT]"
echo ""

# ═══════════════════════════════════════════════════════════════
# THREAT INTELLIGENCE — CROSS-REFERENCE AGAINST GLOBAL DATABASES
# ═══════════════════════════════════════════════════════════════
progress "TI/$TOTAL_SECTIONS — ZA Support Threat Intelligence"
: # Threat intelligence — requires full local install with API keys configured in settings.conf

# ═══════════════════════════════════════════════════════════════
# MALWARE & ADWARE SCAN
# ═══════════════════════════════════════════════════════════════
progress "MAL/$TOTAL_SECTIONS — Malware & Adware Scan"
# ─── INLINE: MALWARE SCAN MODULE (from malware_scan.sh) ───
run_malware_scan() {
    local REPORT_FILE="${1:-}"

    section "MALWARE & ADWARE SCAN"
    echo "  Scanning for known macOS threats, suspicious configurations, and indicators of compromise..."
    echo ""

    local FINDINGS=0
    local STATUS="CLEAN"

    flag() {
        local level="$1"; shift
        echo "  [$level] $*"
        FINDINGS=$((FINDINGS + 1))
        [[ "$level" == "MALWARE" ]] && STATUS="MALWARE DETECTED"
        [[ "$level" == "THREAT" && "$STATUS" == "CLEAN" ]] && STATUS="THREATS FOUND"
        [[ "$level" == "SUSPICIOUS" && "$STATUS" == "CLEAN" ]] && STATUS="SUSPICIOUS"
    }

    # ── 1. KNOWN MALWARE PATHS ────────────────────────────────────────────────
    echo "── Known Malware Paths ──"
    declare -a MALWARE_PATHS=(
        # Adware — VSearch
        "/Library/Application Support/VSearch"
        "/Library/LaunchAgents/com.vsearch.agent.plist"
        "/Library/LaunchDaemons/com.vsearch.daemon.plist"
        "/Library/LaunchDaemons/com.vsearch.helper.plist"
        # Adware — Conduit / Trovi
        "/Library/Application Support/Conduit"
        "/Applications/Conduit.app"
        "/Library/LaunchAgents/com.conduit.plist"
        # Adware — Genieo
        "/Library/Application Support/Genieo"
        "/Applications/Genieo.app"
        "/Library/LaunchAgents/com.genieo.engine.plist"
        "/Library/LaunchDaemons/com.genieoinnovation.macextension.client.plist"
        # Adware — Spigot
        "/Library/Application Support/Spigot"
        "/Library/LaunchAgents/com.spigot.ApplicationManager.plist"
        "/Library/LaunchAgents/com.spigot.SearchProtection.plist"
        # Trojan — Shlayer
        "/tmp/com.apple.Safari.plist"
        "/Library/LaunchAgents/com.adobe.fpsaud.plist"
        "/Library/Application Support/Adobe/Flash Player Install Manager"
        # Trojan — AdLoad
        "/Library/LaunchAgents/com.adload.plist"
        "/Library/Application Support/AdLoad"
        # Cryptominer paths
        "/Library/LaunchDaemons/com.daemon.plist"
        "/usr/local/bin/miner"
        "/usr/local/bin/xmrig"
        "/tmp/xmrig"
        "/tmp/minerd"
        # Browser hijackers
        "/Library/Application Support/SearchProtect"
        "/Library/LaunchAgents/com.searchprotect.plist"
        "/Applications/SearchProtect.app"
        "/Library/Application Support/MplayerX"
        "/Library/LaunchAgents/com.mplayerx.plist"
        # OSX/Pirrit
        "/Library/Application Support/UtilityParze"
        "/Library/Application Support/WebKitExt"
        "/Library/LaunchAgents/com.UtilityParze.plist"
        # OSX/Flashback (legacy but still checked)
        "/Applications/FlashPlayer.app"
        "/Library/Internet Plug-Ins/Flash Player.plugin"
        # OSX/Dok
        "/private/etc/launch.sh"
        # Mackeeper (PUP)
        "/Applications/MacKeeper.app"
        "/Library/LaunchDaemons/com.mackeeper.MacKeeperHelper.plist"
        # Mac Auto Fixer (PUP)
        "/Applications/Mac Auto Fixer.app"
    )

    local found_paths=0
    for path in "${MALWARE_PATHS[@]}"; do
        if [[ -e "$path" ]]; then
            flag "MALWARE" "Known malware path detected: $path"
            found_paths=$((found_paths + 1))
        fi
    done
    [[ $found_paths -eq 0 ]] && echo "  [OK] No known malware paths detected"
    echo ""

    # ── 2. SUSPICIOUS LAUNCHAGENTS / DAEMONS ─────────────────────────────────
    echo "── Suspicious LaunchAgents / Daemons ──"
    local suspicious_launch=0
    for plist_dir in /Library/LaunchAgents /Library/LaunchDaemons \
                     "$HOME/Library/LaunchAgents" /System/Library/LaunchDaemons; do
        [[ ! -d "$plist_dir" ]] && continue
        while IFS= read -r -d '' plist; do
            prog=$(defaults read "$plist" ProgramArguments 2>/dev/null | grep -oE '/[^"]+' | head -1)
            [[ -z "$prog" ]] && prog=$(defaults read "$plist" Program 2>/dev/null | tr -d '"')
            [[ -z "$prog" ]] && continue
            # Flag if pointing to /tmp or hidden dirs
            if echo "$prog" | grep -qE '^/tmp/|/\.[^/]'; then
                flag "SUSPICIOUS" "LaunchPlist points to suspicious path: $(basename "$plist") → $prog"
                suspicious_launch=$((suspicious_launch + 1))
            fi
        done < <(find "$plist_dir" -name "*.plist" -maxdepth 1 -print0 2>/dev/null)
    done
    [[ $suspicious_launch -eq 0 ]] && echo "  [OK] No suspicious LaunchAgent/Daemon paths detected"
    echo ""

    # ── 3. NON-APPLE LAUNCHDAEMONS WITH UNSIGNED BINARIES ────────────────────
    echo "── Non-Apple LaunchDaemons — Code Signature Check ──"
    local unsigned_daemons=0
    while IFS= read -r -d '' plist; do
        label=$(defaults read "$plist" Label 2>/dev/null | tr -d '"')
        [[ "$label" == com.apple.* ]] && continue
        prog=$(defaults read "$plist" Program 2>/dev/null | tr -d '"')
        [[ -z "$prog" ]] && prog=$(defaults read "$plist" ProgramArguments 2>/dev/null | \
            grep -oE '"[^"]*"' | head -1 | tr -d '"')
        [[ -z "$prog" || ! -f "$prog" ]] && continue
        if ! codesign -v "$prog" 2>/dev/null; then
            flag "SUSPICIOUS" "Unsigned LaunchDaemon binary: $prog ($(basename "$plist"))"
            unsigned_daemons=$((unsigned_daemons + 1))
        fi
    done < <(find /Library/LaunchDaemons -name "*.plist" -maxdepth 1 -print0 2>/dev/null)
    [[ $unsigned_daemons -eq 0 ]] && echo "  [OK] All non-Apple LaunchDaemon binaries are signed"
    echo ""

    # ── 4. KNOWN MALICIOUS CHROME EXTENSION IDs ──────────────────────────────
    echo "── Malicious Browser Extension Check ──"
    declare -a BAD_EXTENSIONS=(
        "aapbdbdomjkkjkaonfhkkikfgjllcleb"  # Searchbar
        "ihcjicgdanjaechkgeegckofjjedodee"  # Superfish
        "ngpampappnmepgilojfohadhhmbhlaek"  # Genieo
        "gaiilaahiahdejapggenmdmafpmbipje"  # SearchMine
        "bbjciahceamgodcoidkjpchnokgfpphh"  # PriceMeter
        "jifpbeccnghkjeaalbbjmodiffmgedin"  # eBay shopping assistant (adware variant)
        "kmendfapggjehodndflmmgagdbamhnfd"  # Various adware
        "igdhbblpcellaljokkpfhcjlagemhgjl"  # Kompas browser
        "ebgfedhmgnhpgcfafbmpafgebgomdiog"  # Search encrypt (adware)
        "oadboiipflhobonjjffjbfekfjcgkhco"  # Hola VPN (suspicious)
    )

    local found_exts=0
    CHROME_EXTS_DIR="$HOME/Library/Application Support/Google/Chrome/Default/Extensions"
    if [[ -d "$CHROME_EXTS_DIR" ]]; then
        for ext_id in "${BAD_EXTENSIONS[@]}"; do
            if [[ -d "$CHROME_EXTS_DIR/$ext_id" ]]; then
                flag "THREAT" "Known malicious Chrome extension: $ext_id"
                found_exts=$((found_exts + 1))
            fi
        done
    fi
    [[ $found_exts -eq 0 ]] && echo "  [OK] No known malicious browser extensions detected"
    echo ""

    # ── 5. SUSPICIOUS PORT CONNECTIONS ───────────────────────────────────────
    echo "── Suspicious Network Port Check ──"
    declare -a SUSPICIOUS_PORTS=(4444 5555 6666 6667 8888 31337 12345 1337 9001 9050)
    local found_ports=0
    for port in "${SUSPICIOUS_PORTS[@]}"; do
        hit=$(netstat -an 2>/dev/null | grep -E "\.${port}\s|:${port}\s" | grep -v "LISTEN" | head -3)
        if [[ -n "$hit" ]]; then
            flag "SUSPICIOUS" "Connection on suspicious port $port: $(echo "$hit" | head -1)"
            found_ports=$((found_ports + 1))
        fi
    done
    [[ $found_ports -eq 0 ]] && echo "  [OK] No connections on known suspicious ports"
    echo ""

    # ── 6. DNS SERVER CHECK ───────────────────────────────────────────────────
    echo "── DNS Server Configuration Check ──"
    declare -a KNOWN_GOOD_DNS=(
        "8.8.8.8" "8.8.4.4"         # Google
        "1.1.1.1" "1.0.0.1"         # Cloudflare
        "9.9.9.9" "149.112.112.112" # Quad9
        "208.67.222.222" "208.67.220.220" # OpenDNS
        "4.2.2.1" "4.2.2.2"         # Level3
    )
    local dns_suspicious=0
    while IFS= read -r dns_server; do
        [[ -z "$dns_server" ]] && continue
        # Skip private ranges
        echo "$dns_server" | grep -qE '^10\.|^192\.168\.|^172\.(1[6-9]|2[0-9]|3[01])\.|^127\.' && continue
        local is_known=false
        for known in "${KNOWN_GOOD_DNS[@]}"; do
            [[ "$dns_server" == "$known" ]] && { is_known=true; break; }
        done
        if [[ "$is_known" == false ]]; then
            flag "SUSPICIOUS" "Non-standard DNS server: $dns_server (could indicate hijacking)"
            dns_suspicious=$((dns_suspicious + 1))
        fi
    done < <(scutil --dns 2>/dev/null | awk '/nameserver/{print $3}' | sort -u)
    [[ $dns_suspicious -eq 0 ]] && echo "  [OK] DNS servers are standard or private"
    echo ""

    # ── 7. BROWSER HISTORY PHISHING CHECK ────────────────────────────────────
    echo "── Browser History Phishing Domain Check ──"
    declare -a PHISHING_DOMAINS=(
        "appleid-verify" "apple-security" "icloud-login" "apple-account-locked"
        "paypal-secure" "paypal-update" "paypal-verify"
        "bank-secure-login" "banking-alert" "account-suspended"
        "microsoft-alert" "windows-defender-alert" "tech-support-alert"
        "amazon-security" "amazon-account-verify"
        "netflix-billing" "netflix-account"
        "bit.ly" "tinyurl.com" "ow.ly" "goo.gl"  # Flagged if in history frequently
    )
    local phishing_found=0
    for browser_db in \
        "$HOME/Library/Application Support/Google/Chrome/Default/History" \
        "$HOME/Library/Application Support/Google/Chrome/Profile*/History" \
        "$HOME/Library/Safari/History.db"; do
        [[ ! -f "$browser_db" ]] && continue
        for domain in "${PHISHING_DOMAINS[@]}"; do
            hit=$(timeout 5 sqlite3 "$browser_db" \
                "SELECT count(*) FROM urls WHERE url LIKE '%${domain}%';" 2>/dev/null || echo "0")
            if [[ "${hit:-0}" -gt 0 ]]; then
                flag "SUSPICIOUS" "Browser history contains visits to suspicious domain pattern: $domain ($hit visit(s)) — $(basename "$browser_db")"
                phishing_found=$((phishing_found + 1))
            fi
        done
    done
    [[ $phishing_found -eq 0 ]] && echo "  [OK] No known phishing domain patterns in browser history"
    echo ""

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    echo "── Malware Scan Summary ──"
    echo "  Total findings: $FINDINGS"
    echo "  Status: $STATUS"
    echo ""
    if [[ "$FINDINGS" -gt 0 ]]; then
        echo "  [ACTION REQUIRED] Malware scan findings require immediate attention."
        echo "  Contact ZA Support: admin@zasupport.com | 064 529 5863"
    else
        echo "  [CLEAR] No malware or adware indicators detected."
    fi
    echo ""

    write_json "malware_scan" \
        "findings_count" "$FINDINGS" \
        "status"         "$STATUS"
}

run_malware_scan "$REPORT_FILE"

# ═══════════════════════════════════════════════════════════════
# 68. INTELLIGENCE ENGINE — PERSONALISED RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════
progress "68/$TOTAL_SECTIONS — Intelligence Engine (generating recommendations)"
section "68. PERSONALISED RECOMMENDATIONS — Based on your Mac's diagnostic data"
echo "The following recommendations are generated from the data collected above."
echo "Each recommendation cites the specific finding that triggered it."
echo ""

REC_COUNT=0
RECS_JSON="["

add_rec() {
    local SEV="$1"; local TITLE="$2"; local EVIDENCE="$3"; local PRODUCT="$4"; local PRICE="$5"; local RISK="${6:-}"
    REC_COUNT=$((REC_COUNT + 1))
    echo "  ${SEV} #${REC_COUNT}: ${TITLE}"
    echo "    Evidence: ${EVIDENCE}"
    [[ -n "$RISK" ]] && echo "    Risk: ${RISK}"
    echo "    → ${PRODUCT}: ${PRICE}"
    echo ""
    RECS_JSON="${RECS_JSON}{\"severity\":\"$SEV\",\"title\":\"$(echo "$TITLE" | sed 's/"/\\"/g')\",\"evidence\":\"$(echo "$EVIDENCE" | sed 's/"/\\"/g')\",\"product\":\"$(echo "$PRODUCT" | sed 's/"/\\"/g')\",\"price\":\"$PRICE\",\"risk_scenario\":\"$(echo "$RISK" | sed 's/"/\\"/g')\"},"
}

# --- BACKUP TRIGGERS ---
TM_DEST=$(tmutil destinationinfo 2>/dev/null | grep -c "Name" || echo "0")
if [[ "$TM_DEST" -eq 0 ]]; then
    USED_GB=$(df -g / 2>/dev/null | awk 'NR==2{print $3}')
    add_rec "CRITICAL" "No backup configured" \
        "No Time Machine destination. No backup agent detected. ${USED_GB:-Unknown} GB at risk of total loss." \
        "Automated backup configuration" "Included" \
        "If the hard drive fails tomorrow — and drives of this age do fail without warning — every document, email attachment, photo, and file is permanently gone. Forensic data recovery starts at R 8,000 with no guarantee of success. Ransomware attacks, which encrypt all files and demand payment, are now the most common cyber attack in South Africa. Without a backup, the only options are to pay the ransom (with no guarantee of file return) or accept total data loss."
fi

LAST_TM_EPOCH=$(defaults read /Library/Preferences/com.apple.TimeMachine.plist Destinations 2>/dev/null | grep -A2 "SnapshotDates" | grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2}" | tail -1)
if [[ -n "$LAST_TM_EPOCH" ]]; then
    DAYS_SINCE=$(( ( $(date +%s) - $(date -jf "%Y-%m-%d" "$LAST_TM_EPOCH" +%s 2>/dev/null || echo "0") ) / 86400 ))
    if [[ "$DAYS_SINCE" -gt 30 ]]; then
        add_rec "HIGH" "Backup is ${DAYS_SINCE} days old" \
            "Last backup: ${LAST_TM_EPOCH}. ${DAYS_SINCE} days of work would be lost if the drive failed today." \
            "Automated backup configuration" "Included" \
            "If the hard drive fails — and drives of this age do fail without warning — every document, email, photo, and file created since the last backup is permanently gone. There is no recovery service that can guarantee retrieval from a failed drive. Ransomware attacks, which encrypt all files and demand payment, are now the most common cyber attack in South Africa. Without a current backup, the only options are to pay the ransom or accept total data loss."
    fi
fi

# --- BATTERY TRIGGERS ---
if [[ -n "$HEALTH" && "$HEALTH" != "N/A" ]]; then
    HEALTH_INT=${HEALTH%.*}
    if [[ "$HEALTH_INT" -lt 80 ]]; then
        add_rec "CRITICAL" "Battery needs replacement" \
            "Battery health: ${HEALTH}%, ${CYCLE} cycles. Condition: ${BATT_CONDITION}. Design: ${DESIGN_CAP}mAh, Current max: ${MAX_CAP}mAh." \
            "Battery Replacement" "R 1,899–R 3,499" ""
    elif [[ "$HEALTH_INT" -lt 85 ]]; then
        add_rec "HIGH" "Battery health declining — approaching service threshold" \
            "Battery health: ${HEALTH}% (Apple service threshold: 80%). ${CYCLE} cycles. Condition: ${BATT_CONDITION}." \
            "Battery Replacement (preventive)" "R 1,899–R 3,499" ""
    elif [[ "$HEALTH_INT" -lt 90 ]]; then
        add_rec "MEDIUM" "Battery showing wear" \
            "Battery health: ${HEALTH}%, ${CYCLE} cycles. Monitor for further degradation." \
            "$(echo "$PRICE_MAINTENANCE" | cut -d'|' -f1)" "$(echo "$PRICE_MAINTENANCE" | cut -d'|' -f2)" ""
    fi
fi

# --- STORAGE TRIGGERS ---
if [[ -n "$DISK_USED_PCT" ]]; then
    if [[ "$DISK_USED_PCT" -gt 90 ]]; then
        add_rec "CRITICAL" "Boot disk critically full" \
            "Disk ${DISK_USED_PCT}% full (${DISK_FREE_GB} GB free). macOS requires 15-20% free. Updates will fail, performance severely degraded." \
            "$(echo "$PRICE_PERFORMANCE_OPT" | cut -d'|' -f1) + External SSD" "$(echo "$PRICE_PERFORMANCE_OPT" | cut -d'|' -f2) + SSD from R 1,499" ""
    elif [[ "$DISK_USED_PCT" -gt 85 ]]; then
        add_rec "HIGH" "Boot disk running low" \
            "Disk ${DISK_USED_PCT}% full (${DISK_FREE_GB} GB free). Approaching threshold for performance degradation." \
            "$(echo "$PRICE_PERFORMANCE_OPT" | cut -d'|' -f1)" "$(echo "$PRICE_PERFORMANCE_OPT" | cut -d'|' -f2)" ""
    fi
fi

# --- SECURITY TRIGGERS (bundled into one session) ---
SECURITY_ISSUES=""
FV_CHECK=$(fdesetup status 2>/dev/null | grep -ci "off")
[[ "$FV_CHECK" -gt 0 ]] && SECURITY_ISSUES="${SECURITY_ISSUES}FileVault encryption is off. "

FW_CHECK=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null | grep -ci "disabled")
[[ "$FW_CHECK" -gt 0 ]] && SECURITY_ISSUES="${SECURITY_ISSUES}Firewall is disabled. "

GK_CHECK=$(timeout 10 spctl --status 2>/dev/null | grep -ci "disabled")
[[ "$GK_CHECK" -gt 0 ]] && SECURITY_ISSUES="${SECURITY_ISSUES}Gatekeeper is disabled. "

SIP_CHECK=$(csrutil status 2>/dev/null | grep -ci "disabled")
if [[ "$SIP_CHECK" -gt 0 && "$OCLP_DETECTED" == "YES" ]]; then
    echo "  [MANAGED] SIP disabled — macOS compatibility layer managed by ZA Support [MANAGED]"
elif [[ "$SIP_CHECK" -gt 0 ]]; then
    SECURITY_ISSUES="${SECURITY_ISSUES}SIP is disabled. "
fi

[[ -z "$PWMGR_FOUND" ]] && SECURITY_ISSUES="${SECURITY_ISSUES}No password manager detected. "
[[ "${TRIM_DISABLED:-NO}" == "YES" ]] && SECURITY_ISSUES="${SECURITY_ISSUES}TRIM not enabled. "

SECURITY_RISK_SCENARIO=""
[[ "$FV_CHECK" -gt 0 ]] && SECURITY_RISK_SCENARIO="${SECURITY_RISK_SCENARIO}FileVault off: If this MacBook is stolen, every file — documents, emails, saved passwords, photos — is readable by anyone without needing your password. They simply remove the drive and connect it to another computer. No technical skill is required. "
[[ "$FW_CHECK" -gt 0 ]] && SECURITY_RISK_SCENARIO="${SECURITY_RISK_SCENARIO}Firewall disabled: On any shared Wi-Fi — a coffee shop, hotel, or home network with guests — another device on the same network can attempt to connect to this Mac. With the firewall off, any application listening for connections is exposed. "
[[ -z "$PWMGR_FOUND" ]] && SECURITY_RISK_SCENARIO="${SECURITY_RISK_SCENARIO}No password manager: Without a password manager, most people reuse the same 2-3 passwords. When one service is breached, automated tools try that password on every major service — email, banking, cloud storage. This credential stuffing accounts for over 80% of account takeovers. "

if [[ -n "$SECURITY_ISSUES" ]]; then
    add_rec "HIGH" "Security configuration required" \
        "$SECURITY_ISSUES Covers FileVault, firewall, stealth mode, password manager setup, startup review, TRIM, and disk optimisation." \
        "Security Configuration" "R 899" \
        "$SECURITY_RISK_SCENARIO"
fi

# --- PERFORMANCE TRIGGERS ---
PERF_ISSUES=""
PERF_RISK_SCENARIO=""
SWAP_USED=$(sysctl vm.swapusage 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /used/) print $(i+2)}' | tr -d 'M.' | head -1)
if [[ -n "$SWAP_USED" && "${SWAP_USED:-0}" -gt 4000 ]]; then
    PERF_ISSUES="${PERF_ISSUES}Excessive swap: $(echo "scale=1; ${SWAP_USED:-0} / 1024" | bc 2>/dev/null || echo "$SWAP_USED")GB. "
    PERF_RISK_SCENARIO="${PERF_RISK_SCENARIO}Excessive swap: The system is using the hard drive as temporary memory because RAM is insufficient for the current workload. This makes everything slower — applications take longer to switch, files take longer to open, and the system may freeze when memory pressure spikes. On an older machine, accelerated drive wear from swap usage increases the risk of sudden drive failure. "
fi
if [[ -n "$TOTAL_PROCS" && "${TOTAL_PROCS:-0}" -gt 350 ]]; then
    PERF_ISSUES="${PERF_ISSUES}High process count: ${TOTAL_PROCS}. "
    PERF_RISK_SCENARIO="${PERF_RISK_SCENARIO}High process count: ${TOTAL_PROCS} processes running in the background, each consuming memory and CPU. On a machine already under memory pressure, every unnecessary process pushes more data to swap and slows everything down further. Some may be forgotten installers, updaters, or services that are no longer needed. "
fi

if [[ -n "$PERF_ISSUES" ]]; then
    add_rec "MEDIUM" "Mail/application performance investigation" \
        "$PERF_ISSUES Performance investigation and optimisation included as part of the diagnostic service." \
        "Mail/application performance investigation" "Included" \
        "$PERF_RISK_SCENARIO"
fi

# --- macOS UPGRADE TRIGGER (2012–2017 Intel Macs not yet on Ventura) ---
if [[ "$CHIP_TYPE" == "INTEL" && "${MACOS_MAJOR:-0}" -lt 13 ]]; then
    add_rec "MEDIUM" "macOS upgrade to Ventura available" \
        "This Intel Mac is running macOS $(sw_vers -productVersion 2>/dev/null || echo "< 13"). Ventura (macOS 13) provides improved security, performance, and continued software compatibility." \
        "macOS upgrade to Ventura" "R 1,799" \
        "This version of macOS has not received a security update since 2022. Every vulnerability discovered since then is publicly documented — meaning attackers know exactly how to exploit this system. The existing security software can block known malware, but cannot fix vulnerabilities in the operating system itself. A single visit to a compromised website, a malicious email attachment, or a targeted attack can exploit these known weaknesses. The device is effectively running with unlocked doors that cannot be locked without an OS upgrade."
fi

# --- THERMAL TRIGGERS ---
if [[ "${PANIC_COUNT:-0}" -gt 0 ]]; then
    add_rec "CRITICAL" "${PANIC_COUNT} kernel panics found" \
        "Kernel panics indicate hardware or driver-level failures. Immediate investigation required." \
        "Hardware Diagnostic + Repair" "$(echo "$PRICE_HOURLY" | cut -d'|' -f2)" ""
fi

# --- LOAD SHEDDING / UPS TRIGGER ---
UNSAFE_SHUTDOWNS=$(timeout 30 system_profiler SPNVMeDataType 2>/dev/null | grep -i "Unsafe Shutdowns" | awk '{print $NF}' || echo "0")
if [[ "${UNSAFE_SHUTDOWNS:-0}" -gt 20 ]]; then
    add_rec "HIGH" "${UNSAFE_SHUTDOWNS} unsafe shutdowns recorded" \
        "Each unsafe shutdown risks data corruption. In South Africa, this typically means load shedding without a UPS." \
        "UPS Power Protection" "R 2,499–R 4,999" ""
fi

# --- MONITORING TRIGGER ---
HC_AGENT=$(launchctl list 2>/dev/null | grep -ci "zasupport\|healthcheck" || echo "0")
if [[ "$HC_AGENT" -eq 0 ]]; then
    if [[ "$REC_COUNT" -gt 3 ]]; then
        add_rec "HIGH" "No monitoring — ${REC_COUNT} issues found in this diagnostic" \
            "This diagnostic found ${REC_COUNT} issues. Without ongoing monitoring, these patterns repeat." \
            "$(echo "$PRICE_HEALTH_CHECK" | cut -d'|' -f1)" "$(echo "$PRICE_HEALTH_CHECK" | cut -d'|' -f2)" ""
    else
        add_rec "MEDIUM" "No continuous monitoring installed" \
            "No ZA Support monitoring agent detected. Proactive monitoring catches problems early, reducing repair costs." \
            "$(echo "$PRICE_HEALTH_CHECK" | cut -d'|' -f1)" "$(echo "$PRICE_HEALTH_CHECK" | cut -d'|' -f2)" ""
    fi
fi

# --- OCLP MANAGED TAG ---
if [[ "$OCLP_DETECTED" == "YES" ]]; then
    echo "  [MANAGED] macOS compatibility layer managed by ZA Support [MANAGED]"
fi

# --- SUMMARY ---
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  TOTAL RECOMMENDATIONS: $REC_COUNT"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "These recommendations are based solely on this Mac's diagnostic data."
echo "For questions or to action any recommendation, contact ZA Support:"
echo "  Phone:  064 529 5863"
echo "  Email:  admin@zasupport.com"
echo "  Web:    www.zasupport.com"
echo "  Address: 1 Hyde Park Lane, Hyde Park, Johannesburg, 2196"
echo ""

# --- CYBERPULSE MONITOR UPSELL ---
echo "═══════════════════════════════════════════════════════════"
echo "  CYBERPULSE MONITOR — CONTINUOUS PROTECTION"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  CyberPulse Monitor         R 299/month"
echo "    Daily health checks, monthly reports"
echo ""
echo "  CyberPulse Monitor Pro     R 599/month"
echo "    Everything in Monitor + threat intelligence,"
echo "    malware scanning, and breach detection"
echo ""
echo "  Speak to ZA Support to add CyberPulse Monitor"
echo "  to your service plan."
echo ""

# Trim trailing comma from RECS_JSON
RECS_JSON="${RECS_JSON%,}]"

write_json_raw "recommendations" "$RECS_JSON"
write_json_simple "recommendation_count" "$REC_COUNT"
write_json "metadata" \
    "version" "3.3" \
    "serial" "$SERIAL" \
    "hostname" "$(hostname)" \
    "client_id" "${CLIENT_ID:-}" \
    "mode" "$([ "$QUICK_MODE" = true ] && echo 'quick' || echo 'full')" \
    "runtime_seconds" "$SECONDS"

# ═══════════════════════════════════════════════════════════════
# END OF REPORT
# ═══════════════════════════════════════════════════════════════
echo "═══════════════════════════════════════════════════════════"
echo "  END OF DIAGNOSTIC — $(date '+%d/%m/%Y %H:%M:%S')"
echo "  Runtime: $SECONDS seconds"
echo "═══════════════════════════════════════════════════════════"

} > "$REPORT_FILE" 2>&1

# ═══════════════════════════════════════════════════════════════
# 69. SMART FULL ATTRIBUTES
# ═══════════════════════════════════════════════════════════════
progress "69/$TOTAL_SECTIONS — SMART Full Attributes"
section "69. SMART FULL ATTRIBUTES"
if command -v smartctl &>/dev/null; then
    SMART_ATTRS=$(timeout 30 smartctl -A /dev/disk0 2>/dev/null | tail -n +8 | head -30 || echo "unavailable")
    SMART_DEVICE=$(timeout 30 smartctl -i /dev/disk0 2>/dev/null | grep -E "Device Model|Rotation Rate|Form Factor" | tr '\n' ' ' || echo "")
    echo "$SMART_DEVICE"
    echo "$SMART_ATTRS"
    write_json "smart_attributes" \
        "device_info" "${SMART_DEVICE:-unavailable}" \
        "attributes_raw" "${SMART_ATTRS:-unavailable}"
else
    echo "[SKIPPED] smartctl not installed"
    write_json "smart_attributes" "status" "skipped — smartctl not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 70. SMART ERROR LOG
# ═══════════════════════════════════════════════════════════════
progress "70/$TOTAL_SECTIONS — SMART Error Log"
section "70. SMART ERROR LOG"
if command -v smartctl &>/dev/null; then
    SMART_ERRORS=$(timeout 30 smartctl -l error /dev/disk0 2>/dev/null | grep -E "Error|Count|occurred" | head -20 || echo "No errors logged")
    echo "$SMART_ERRORS"
    write_json "smart_error_log" "errors" "${SMART_ERRORS:-No errors logged}"
else
    echo "[SKIPPED] smartctl not installed"
    write_json "smart_error_log" "status" "skipped — smartctl not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 71. SMART SELF-TEST LOG
# ═══════════════════════════════════════════════════════════════
progress "71/$TOTAL_SECTIONS — SMART Self-Test Log"
section "71. SMART SELF-TEST LOG"
if command -v smartctl &>/dev/null; then
    SMART_TESTS=$(timeout 30 smartctl -l selftest /dev/disk0 2>/dev/null | tail -n +6 | head -10 || echo "No tests recorded")
    echo "$SMART_TESTS"
    write_json "smart_selftest_log" "tests" "${SMART_TESTS:-No tests recorded}"
else
    echo "[SKIPPED] smartctl not installed"
    write_json "smart_selftest_log" "status" "skipped — smartctl not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 72. DISK I/O LATENCY (ioping)
# ═══════════════════════════════════════════════════════════════
progress "72/$TOTAL_SECTIONS — Disk I/O Latency"
section "72. DISK I/O LATENCY (ioping)"
if command -v ioping &>/dev/null; then
    IOPING_OUT=$(timeout 30 ioping -c 10 / 2>/dev/null | tail -3 || echo "unavailable")
    echo "$IOPING_OUT"
    write_json "disk_io_latency" "ioping_summary" "${IOPING_OUT:-unavailable}"
else
    echo "[SKIPPED] ioping not installed"
    write_json "disk_io_latency" "status" "skipped — ioping not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 73. SEQUENTIAL READ BENCHMARK
# ═══════════════════════════════════════════════════════════════
progress "73/$TOTAL_SECTIONS — Sequential Read Benchmark"
section "73. SEQUENTIAL READ BENCHMARK"
SEQ_READ=$(timeout 60 dd if=/dev/zero bs=1m count=256 2>&1 | tail -1 || echo "unavailable")
echo "dd sequential (from zero device): $SEQ_READ"
write_json "seq_read_bench" "dd_result" "${SEQ_READ:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 74. SEQUENTIAL WRITE BENCHMARK
# ═══════════════════════════════════════════════════════════════
progress "74/$TOTAL_SECTIONS — Sequential Write Benchmark"
section "74. SEQUENTIAL WRITE BENCHMARK"
SEQ_WRITE=$(timeout 60 dd if=/dev/zero of=/tmp/za_bench_write bs=1m count=256 2>&1 | tail -1 || echo "unavailable")
rm -f /tmp/za_bench_write
echo "dd sequential write: $SEQ_WRITE"
write_json "seq_write_bench" "dd_result" "${SEQ_WRITE:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 75. RANDOM I/O BENCHMARK (ioping)
# ═══════════════════════════════════════════════════════════════
progress "75/$TOTAL_SECTIONS — Random I/O Benchmark"
section "75. RANDOM I/O BENCHMARK"
if command -v ioping &>/dev/null; then
    RANDOM_IO=$(timeout 30 ioping -R -c 20 /tmp 2>/dev/null | tail -3 || echo "unavailable")
    echo "$RANDOM_IO"
    write_json "random_io_bench" "ioping_random" "${RANDOM_IO:-unavailable}"
else
    echo "[SKIPPED] ioping not installed"
    write_json "random_io_bench" "status" "skipped — ioping not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 76. NETWORK INTERFACE THROUGHPUT
# ═══════════════════════════════════════════════════════════════
progress "76/$TOTAL_SECTIONS — Network Interface Throughput"
section "76. NETWORK INTERFACE THROUGHPUT"
NET_THROUGHPUT=$(netstat -ibn 2>/dev/null | head -20 || echo "unavailable")
echo "$NET_THROUGHPUT"
write_json "network_throughput" "netstat_ibn" "${NET_THROUGHPUT:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 77. NETWORK CONNECTION STATES
# ═══════════════════════════════════════════════════════════════
progress "77/$TOTAL_SECTIONS — Network Connection States"
section "77. NETWORK CONNECTION STATES"
CONN_STATES=$(netstat -an 2>/dev/null | awk '{print $6}' | sort | uniq -c | sort -rn | head -15 || echo "unavailable")
TOTAL_CONNS=$(netstat -an 2>/dev/null | wc -l | tr -d ' ' || echo "0")
echo "Total connections: $TOTAL_CONNS"
echo "$CONN_STATES"
write_json "network_conn_states" \
    "total_connections" "${TOTAL_CONNS:-0}" \
    "state_summary" "${CONN_STATES:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 78. TCP CONNECTION DETAILS
# ═══════════════════════════════════════════════════════════════
progress "78/$TOTAL_SECTIONS — TCP Connection Details"
section "78. TCP CONNECTION DETAILS"
TCP_CONNS=$(netstat -anp tcp 2>/dev/null | grep -v "127.0.0.1\|::1" | head -30 || echo "unavailable")
echo "$TCP_CONNS"
write_json "tcp_connections" "tcp_detail" "${TCP_CONNS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 79. UDP LISTENERS
# ═══════════════════════════════════════════════════════════════
progress "79/$TOTAL_SECTIONS — UDP Listeners"
section "79. UDP LISTENERS"
UDP_LISTENERS=$(netstat -anp udp 2>/dev/null | grep "LISTEN\|\*\.\*" | head -20 || echo "unavailable")
echo "$UDP_LISTENERS"
write_json "udp_listeners" "udp_detail" "${UDP_LISTENERS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 80. NETWORK ROUTE TABLE
# ═══════════════════════════════════════════════════════════════
progress "80/$TOTAL_SECTIONS — Network Route Table"
section "80. NETWORK ROUTE TABLE"
ROUTE_TABLE=$(netstat -rn 2>/dev/null | head -30 || echo "unavailable")
DEFAULT_GATEWAY=$(netstat -rn 2>/dev/null | awk '/^default/{print $2}' | head -1 || echo "Unknown")
echo "Default gateway: $DEFAULT_GATEWAY"
echo "$ROUTE_TABLE"
write_json "network_routes" \
    "default_gateway" "${DEFAULT_GATEWAY:-Unknown}" \
    "route_table" "${ROUTE_TABLE:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 81. SYSTEM CERTIFICATES
# ═══════════════════════════════════════════════════════════════
progress "81/$TOTAL_SECTIONS — System Certificates"
section "81. SYSTEM CERTIFICATES"
CERT_COUNT=$(timeout 30 security find-certificate -a /Library/Keychains/System.keychain 2>/dev/null | grep -c "labl" || echo "0")
USER_CERT_COUNT=$(timeout 30 security find-certificate -a 2>/dev/null | grep -c "labl" || echo "0")
echo "System keychain certificates: $CERT_COUNT"
echo "User keychain certificates:   $USER_CERT_COUNT"
write_json "system_certificates" \
    "system_keychain_count" "${CERT_COUNT:-0}" \
    "user_keychain_count" "${USER_CERT_COUNT:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 82. EXPIRED CERTIFICATES
# ═══════════════════════════════════════════════════════════════
progress "82/$TOTAL_SECTIONS — Expired Certificates"
section "82. EXPIRED CERTIFICATES"
EXPIRED=$(timeout 30 security find-certificate -a -p 2>/dev/null | \
    openssl crl2pkcs7 -nocrl -certfile /dev/stdin 2>/dev/null | \
    openssl pkcs7 -print_certs -text -noout 2>/dev/null | \
    grep -A2 "Not After" | grep -i "20[012][0-9]" | \
    awk '{if ($NF+0 < 2026) print}' | wc -l | tr -d ' ' || echo "0")
echo "Potentially expired or near-expired certificates: ${EXPIRED:-0}"
write_json "expired_certificates" "count" "${EXPIRED:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 83. KEYCHAIN LIST
# ═══════════════════════════════════════════════════════════════
progress "83/$TOTAL_SECTIONS — Keychain List"
section "83. KEYCHAIN LIST"
KEYCHAINS=$(security list-keychains 2>/dev/null | tr -d '"' | tr -d ' ' | tr '\n' '|' || echo "unavailable")
echo "$KEYCHAINS" | tr '|' '\n'
write_json "keychain_list" "keychains" "${KEYCHAINS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 84. AUTHORIZATION DATABASE
# ═══════════════════════════════════════════════════════════════
progress "84/$TOTAL_SECTIONS — Authorization Database"
section "84. AUTHORIZATION DATABASE"
AUTH_RIGHTS=$(security authorizationdb read system.privilege.admin 2>/dev/null | \
    grep -E "class|group|shared" | head -10 || echo "unavailable")
echo "$AUTH_RIGHTS"
write_json "authorization_db" "admin_rights" "${AUTH_RIGHTS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 85. SIGNED BINARY VERIFICATION
# ═══════════════════════════════════════════════════════════════
progress "85/$TOTAL_SECTIONS — Signed Binary Verification"
section "85. SIGNED BINARY VERIFICATION"
UNSIGNED=""
for bin in /usr/bin/ssh /usr/bin/curl /usr/bin/python3 /bin/bash /usr/sbin/sshd; do
    if [[ -f "$bin" ]]; then
        RESULT=$(codesign -v "$bin" 2>&1 && echo "OK" || echo "FAIL")
        echo "  $bin: $RESULT"
        [[ "$RESULT" == "FAIL" ]] && UNSIGNED="$UNSIGNED $bin"
    fi
done
echo "Unsigned system binaries: ${UNSIGNED:-none}"
write_json "signed_binaries" "unsigned_found" "${UNSIGNED:-none}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 86. PRIVACY PREFERENCES (TCC)
# ═══════════════════════════════════════════════════════════════
progress "86/$TOTAL_SECTIONS — Privacy Preferences (TCC)"
section "86. PRIVACY PREFERENCES (TCC)"
TCC_DB="/Users/$ACTUAL_USER/Library/Application Support/com.apple.TCC/TCC.db"
if [[ -f "$TCC_DB" ]]; then
    TCC_COUNT=$(timeout 10 sqlite3 "$TCC_DB" "SELECT count(*) FROM access;" 2>/dev/null || echo "locked")
    TCC_CAMERA=$(timeout 10 sqlite3 "$TCC_DB" "SELECT client FROM access WHERE service='kTCCServiceCamera' AND allowed=1;" 2>/dev/null | tr '\n' ',' || echo "locked")
    TCC_MIC=$(timeout 10 sqlite3 "$TCC_DB" "SELECT client FROM access WHERE service='kTCCServiceMicrophone' AND allowed=1;" 2>/dev/null | tr '\n' ',' || echo "locked")
    echo "TCC access records: $TCC_COUNT"
    echo "Camera access: $TCC_CAMERA"
    echo "Microphone access: $TCC_MIC"
    write_json "tcc_privacy" \
        "total_records" "${TCC_COUNT:-0}" \
        "camera_apps" "${TCC_CAMERA:-none}" \
        "mic_apps" "${TCC_MIC:-none}"
else
    echo "TCC database not accessible"
    write_json "tcc_privacy" "status" "db not accessible"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 87. SANDBOX STATUS
# ═══════════════════════════════════════════════════════════════
progress "87/$TOTAL_SECTIONS — Sandbox Status"
section "87. SANDBOX STATUS"
SANDBOXED_APPS=$(ps aux 2>/dev/null | grep -c "com.apple.security.sandbox" || echo "0")
APP_SANDBOX=$(csrutil sandbox status 2>/dev/null || echo "unavailable")
echo "Sandboxed processes visible: $SANDBOXED_APPS"
echo "Sandbox status: $APP_SANDBOX"
write_json "sandbox_status" \
    "sandboxed_processes" "${SANDBOXED_APPS:-0}" \
    "csrutil_sandbox" "${APP_SANDBOX:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 88. APP TRANSPORT SECURITY EXCEPTIONS
# ═══════════════════════════════════════════════════════════════
progress "88/$TOTAL_SECTIONS — App Transport Security"
section "88. APP TRANSPORT SECURITY EXCEPTIONS"
ATS_EXCEPTIONS=$(timeout 30 find /Applications -name "Info.plist" -maxdepth 4 2>/dev/null \
    -exec plutil -extract NSAppTransportSecurity.NSAllowsArbitraryLoads raw -o - {} \; 2>/dev/null \
    | grep -c "true" || echo "0")
echo "Apps with ATS arbitrary loads disabled: $ATS_EXCEPTIONS"
write_json "ats_exceptions" "apps_with_ats_disabled" "${ATS_EXCEPTIONS:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 89. KERNEL EXTENSION AUDIT
# ═══════════════════════════════════════════════════════════════
progress "89/$TOTAL_SECTIONS — Kernel Extension Audit"
section "89. KERNEL EXTENSION AUDIT"
KEXT_COUNT=$(timeout 15 kextstat 2>/dev/null | grep -cv "com.apple" || echo "0")
THIRD_PARTY_KEXTS=$(timeout 15 kextstat 2>/dev/null | grep -v "com.apple" | awk '{print $6}' | head -20 | tr '\n' ',' || echo "none")
echo "Third-party kernel extensions: $KEXT_COUNT"
echo "$THIRD_PARTY_KEXTS" | tr ',' '\n' | head -20
write_json "kernel_extensions" \
    "third_party_count" "${KEXT_COUNT:-0}" \
    "third_party_list" "${THIRD_PARTY_KEXTS:-none}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 90. SYSTEM POLICY ASSESSMENT
# ═══════════════════════════════════════════════════════════════
progress "90/$TOTAL_SECTIONS — System Policy Assessment"
section "90. SYSTEM POLICY ASSESSMENT"
SPCTL_STATUS=$(timeout 10 spctl --status 2>/dev/null || echo "unavailable")
SPCTL_GLOBAL=$(timeout 10 spctl --list 2>/dev/null | wc -l | tr -d ' ' || echo "0")
echo "Gatekeeper: $SPCTL_STATUS"
echo "Policy rules: $SPCTL_GLOBAL"
write_json "system_policy" \
    "gatekeeper_status" "${SPCTL_STATUS:-unavailable}" \
    "policy_rules" "${SPCTL_GLOBAL:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 91. FIRMWARE INTEGRITY (iBridge / T2)
# ═══════════════════════════════════════════════════════════════
progress "91/$TOTAL_SECTIONS — Firmware Integrity"
section "91. FIRMWARE INTEGRITY"
T2_INFO=$(timeout 30 system_profiler SPiBridgeDataType 2>/dev/null | grep -E "Model|Firmware" | head -5 || echo "No T2/iBridge chip")
SECURE_BOOT=$(nvram 94b73556-2197-4702-82a8-3e1337dafbfb:AppleSecureBootPolicy 2>/dev/null | awk '{print $2}' || echo "unavailable")
echo "$T2_INFO"
echo "Secure Boot Policy: $SECURE_BOOT"
write_json "firmware_integrity" \
    "ibridge_info" "${T2_INFO:-none}" \
    "secure_boot_policy" "${SECURE_BOOT:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 92. SECURE TOKEN USERS
# ═══════════════════════════════════════════════════════════════
progress "92/$TOTAL_SECTIONS — Secure Token Users"
section "92. SECURE TOKEN USERS"
SECURE_TOKEN_USERS=$(sysadminctl -secureTokenStatus "$ACTUAL_USER" 2>/dev/null || echo "unavailable")
ALL_USERS=$(timeout 10 dscl . -list /Users 2>/dev/null | grep -v "^_" | tr '\n' ',' || echo "unavailable")
echo "Secure token — $ACTUAL_USER: $SECURE_TOKEN_USERS"
write_json "secure_token" \
    "current_user_status" "${SECURE_TOKEN_USERS:-unavailable}" \
    "local_users" "${ALL_USERS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 93. KERNEL TASK INFO
# ═══════════════════════════════════════════════════════════════
progress "93/$TOTAL_SECTIONS — Kernel Task Info"
section "93. KERNEL TASK INFO"
KERN_VERSION=$(sysctl -n kern.version 2>/dev/null | head -1 || echo "Unknown")
KERN_MAXFILES=$(sysctl -n kern.maxfiles 2>/dev/null || echo "Unknown")
KERN_MAXPROC=$(sysctl -n kern.maxproc 2>/dev/null || echo "Unknown")
KERN_BOOTTIME=$(sysctl -n kern.boottime 2>/dev/null | awk '{print $4}' | tr -d ',' || echo "Unknown")
echo "Kernel version: $KERN_VERSION"
echo "Max open files: $KERN_MAXFILES"
echo "Max processes:  $KERN_MAXPROC"
echo "Boot time:      $KERN_BOOTTIME"
write_json "kernel_task_info" \
    "kernel_version" "${KERN_VERSION:-Unknown}" \
    "max_open_files" "${KERN_MAXFILES:-Unknown}" \
    "max_processes" "${KERN_MAXPROC:-Unknown}" \
    "boot_time" "${KERN_BOOTTIME:-Unknown}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 94. VM STATISTICS DETAILED
# ═══════════════════════════════════════════════════════════════
progress "94/$TOTAL_SECTIONS — VM Statistics Detailed"
section "94. VM STATISTICS DETAILED"
VM_STATS=$(vm_stat 2>/dev/null || echo "unavailable")
PAGE_SIZE=$(vm_stat 2>/dev/null | awk '/page size/{print $8}' || echo "4096")
FREE_PAGES=$(vm_stat 2>/dev/null | awk '/Pages free/{gsub(/\./,"",$3); print $3}' || echo "0")
FREE_MB=$(( (${FREE_PAGES:-0} * ${PAGE_SIZE:-4096}) / 1048576 ))
echo "Free memory: ${FREE_MB} MB"
echo "$VM_STATS"
write_json "vm_statistics" \
    "free_memory_mb" "${FREE_MB:-0}" \
    "vm_stat_raw" "${VM_STATS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 95. MEMORY PRESSURE DETAILED
# ═══════════════════════════════════════════════════════════════
progress "95/$TOTAL_SECTIONS — Memory Pressure Detailed"
section "95. MEMORY PRESSURE DETAILED"
MEM_PRESSURE=$(memory_pressure 2>/dev/null | head -5 || echo "unavailable")
echo "$MEM_PRESSURE"
write_json "memory_pressure_detail" "memory_pressure_output" "${MEM_PRESSURE:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 96. COMPRESSED MEMORY STATS
# ═══════════════════════════════════════════════════════════════
progress "96/$TOTAL_SECTIONS — Compressed Memory Stats"
section "96. COMPRESSED MEMORY STATS"
COMPRESSOR_MODE=$(sysctl -n vm.compressor_mode 2>/dev/null || echo "Unknown")
COMPRESSED_PAGES=$(sysctl -n vm.compressor_page_count 2>/dev/null || echo "0")
COMPRESSION_RATIO=$(sysctl -n vm.compression_failed 2>/dev/null || echo "0")
echo "Compressor mode:   $COMPRESSOR_MODE"
echo "Compressed pages:  $COMPRESSED_PAGES"
echo "Compression fails: $COMPRESSION_RATIO"
write_json "compressed_memory" \
    "compressor_mode" "${COMPRESSOR_MODE:-Unknown}" \
    "compressed_pages" "${COMPRESSED_PAGES:-0}" \
    "compression_fails" "${COMPRESSION_RATIO:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 97. GPU UTILIZATION
# ═══════════════════════════════════════════════════════════════
progress "97/$TOTAL_SECTIONS — GPU Utilization"
section "97. GPU UTILIZATION"
GPU_INFO=$(timeout 15 ioreg -r -d 1 -c AGXAccelerator 2>/dev/null | grep -E '"PerformanceStatistics"|"Device"|"model"' | head -10 || \
           timeout 15 ioreg -r -d 1 -c IOPCIDevice 2>/dev/null | grep -i "display\|gpu\|graphics" | head -5 || \
           echo "unavailable")
GPU_NAME=$(timeout 30 system_profiler SPDisplaysDataType 2>/dev/null | awk '/Chipset Model/{print $NF; exit}' || echo "Unknown")
echo "GPU: $GPU_NAME"
echo "$GPU_INFO"
write_json "gpu_utilization" \
    "gpu_name" "${GPU_NAME:-Unknown}" \
    "gpu_stats" "${GPU_INFO:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 98. METAL DEVICE INFO
# ═══════════════════════════════════════════════════════════════
progress "98/$TOTAL_SECTIONS — Metal Device Info"
section "98. METAL DEVICE INFO"
METAL_INFO=$(timeout 30 system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Metal|VRAM|Resolution|Display Type" | head -10 || echo "unavailable")
echo "$METAL_INFO"
write_json "metal_device_info" "display_info" "${METAL_INFO:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 99. SPOTLIGHT INDEX STATUS
# ═══════════════════════════════════════════════════════════════
progress "99/$TOTAL_SECTIONS — Spotlight Index Status"
section "99. SPOTLIGHT INDEX STATUS"
SPOTLIGHT_STATUS=$(timeout 10 mdutil -s / 2>/dev/null || echo "unavailable")
SPOTLIGHT_ENABLED=$(echo "$SPOTLIGHT_STATUS" | grep -c "enabled" || echo "0")
echo "$SPOTLIGHT_STATUS"
write_json "spotlight_status" \
    "root_volume_status" "${SPOTLIGHT_STATUS:-unavailable}" \
    "indexing_enabled" "${SPOTLIGHT_ENABLED:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 100. SPOTLIGHT EXCLUSIONS
# ═══════════════════════════════════════════════════════════════
progress "100/$TOTAL_SECTIONS — Spotlight Exclusions"
section "100. SPOTLIGHT EXCLUSIONS"
SPOTLIGHT_EXCL=$(timeout 10 mdutil -a -s 2>/dev/null | grep -i "disabled\|off" | head -10 || echo "No exclusions found")
echo "$SPOTLIGHT_EXCL"
write_json "spotlight_exclusions" "excluded_volumes" "${SPOTLIGHT_EXCL:-none}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 101. CORE STORAGE INFO
# ═══════════════════════════════════════════════════════════════
progress "101/$TOTAL_SECTIONS — Core Storage Info"
section "101. CORE STORAGE INFO"
CS_INFO=$(diskutil cs list 2>/dev/null | head -20 || echo "No Core Storage volumes")
echo "$CS_INFO"
write_json "core_storage" "cs_list" "${CS_INFO:-No Core Storage volumes}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 102. APFS ENCRYPTION STATUS
# ═══════════════════════════════════════════════════════════════
progress "102/$TOTAL_SECTIONS — APFS Encryption Status"
section "102. APFS ENCRYPTION STATUS"
FV_STATUS=$(fdesetup status 2>/dev/null || echo "unavailable")
APFS_CRYPTO=$(diskutil apfs list 2>/dev/null | grep -E "Encryption|FileVault" | head -10 || echo "unavailable")
echo "$FV_STATUS"
echo "$APFS_CRYPTO"
write_json "apfs_encryption" \
    "filevault_status" "${FV_STATUS:-unavailable}" \
    "apfs_crypto" "${APFS_CRYPTO:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 103. LOGIN WINDOW CONFIG
# ═══════════════════════════════════════════════════════════════
progress "103/$TOTAL_SECTIONS — Login Window Config"
section "103. LOGIN WINDOW CONFIG"
LW_HIDE_USERS=$(defaults read /Library/Preferences/com.apple.loginwindow HideLocalUsers 2>/dev/null || echo "0")
LW_AUTO_LOGIN=$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null || echo "disabled")
LW_GUEST=$(defaults read /Library/Preferences/com.apple.loginwindow GuestEnabled 2>/dev/null || echo "0")
echo "Hide local users: $LW_HIDE_USERS"
echo "Auto-login user:  $LW_AUTO_LOGIN"
echo "Guest account:    $LW_GUEST"
write_json "login_window_config" \
    "hide_local_users" "${LW_HIDE_USERS:-0}" \
    "auto_login_user" "${LW_AUTO_LOGIN:-disabled}" \
    "guest_enabled" "${LW_GUEST:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 104. REMOTE ACCESS SERVICES
# ═══════════════════════════════════════════════════════════════
progress "104/$TOTAL_SECTIONS — Remote Access Services"
section "104. REMOTE ACCESS SERVICES"
SCREEN_SHARING=$(launchctl list 2>/dev/null | grep -i "screen\|vnc\|ScreenSharing" | head -5 || echo "not running")
ARD_STATUS=$(launchctl list 2>/dev/null | grep "com.apple.RemoteDesktop" | head -3 || echo "not loaded")
echo "Screen sharing / VNC: $SCREEN_SHARING"
echo "Apple Remote Desktop: $ARD_STATUS"
write_json "remote_access" \
    "screen_sharing" "${SCREEN_SHARING:-not running}" \
    "ard_status" "${ARD_STATUS:-not loaded}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 105. REMOTE LOGIN (SSH)
# ═══════════════════════════════════════════════════════════════
progress "105/$TOTAL_SECTIONS — Remote Login SSH"
section "105. REMOTE LOGIN SSH"
SSH_STATUS=$(systemsetup -getremotelogin 2>/dev/null || echo "unavailable")
SSH_DAEMON=$(launchctl list 2>/dev/null | grep "com.openssh.sshd" | head -2 || echo "not loaded")
echo "$SSH_STATUS"
echo "SSH daemon: $SSH_DAEMON"
write_json "remote_login_ssh" \
    "systemsetup_status" "${SSH_STATUS:-unavailable}" \
    "sshd_launchd" "${SSH_DAEMON:-not loaded}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 106. WAKE ON LAN / NETWORK ACCESS
# ═══════════════════════════════════════════════════════════════
progress "106/$TOTAL_SECTIONS — Wake on Network Access"
section "106. WAKE ON LAN / NETWORK ACCESS"
WOL_STATUS=$(systemsetup -getwakeonnetworkaccess 2>/dev/null || echo "unavailable")
SLEEP_STATUS=$(systemsetup -getcomputersleep 2>/dev/null || echo "unavailable")
echo "Wake on network: $WOL_STATUS"
echo "Computer sleep:  $SLEEP_STATUS"
write_json "wake_on_network" \
    "wake_on_network" "${WOL_STATUS:-unavailable}" \
    "computer_sleep" "${SLEEP_STATUS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 107. TIMEZONE AND NTP
# ═══════════════════════════════════════════════════════════════
progress "107/$TOTAL_SECTIONS — Timezone and NTP"
section "107. TIMEZONE AND NTP"
TIMEZONE=$(systemsetup -gettimezone 2>/dev/null || echo "unavailable")
NTP_SERVER=$(systemsetup -getnetworktimeserver 2>/dev/null || echo "unavailable")
NTP_SYNC=$(sntp -t 1 time.apple.com 2>/dev/null | head -2 || echo "unavailable")
echo "$TIMEZONE"
echo "$NTP_SERVER"
echo "NTP sync: $NTP_SYNC"
write_json "timezone_ntp" \
    "timezone" "${TIMEZONE:-unavailable}" \
    "ntp_server" "${NTP_SERVER:-unavailable}" \
    "ntp_sync" "${NTP_SYNC:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 108. SOFTWARE UPDATE SERVER
# ═══════════════════════════════════════════════════════════════
progress "108/$TOTAL_SECTIONS — Software Update Configuration"
section "108. SOFTWARE UPDATE CONFIGURATION"
SU_SERVER=$(defaults read /Library/Preferences/com.apple.SoftwareUpdate CatalogURL 2>/dev/null || echo "Apple default")
SU_AUTO=$(defaults read /Library/Preferences/com.apple.SoftwareUpdate AutomaticCheckEnabled 2>/dev/null || echo "Unknown")
SU_AUTO_DL=$(defaults read /Library/Preferences/com.apple.SoftwareUpdate AutomaticDownload 2>/dev/null || echo "Unknown")
SU_CRIT=$(defaults read /Library/Preferences/com.apple.SoftwareUpdate CriticalUpdateInstall 2>/dev/null || echo "Unknown")
echo "Update catalog:      $SU_SERVER"
echo "Auto-check enabled:  $SU_AUTO"
echo "Auto-download:       $SU_AUTO_DL"
echo "Critical auto-install: $SU_CRIT"
write_json "software_update_config" \
    "catalog_url" "${SU_SERVER:-Apple default}" \
    "auto_check" "${SU_AUTO:-Unknown}" \
    "auto_download" "${SU_AUTO_DL:-Unknown}" \
    "critical_auto_install" "${SU_CRIT:-Unknown}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 109. PRINTER LIST
# ═══════════════════════════════════════════════════════════════
progress "109/$TOTAL_SECTIONS — Printer List"
section "109. PRINTER LIST"
PRINTERS=$(lpstat -a 2>/dev/null || echo "No printers configured")
PRINTER_COUNT=$(lpstat -a 2>/dev/null | wc -l | tr -d ' ' || echo "0")
echo "Configured printers: $PRINTER_COUNT"
echo "$PRINTERS"
write_json "printer_list" \
    "printer_count" "${PRINTER_COUNT:-0}" \
    "printers" "${PRINTERS:-none}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 110. AUDIO DEVICES
# ═══════════════════════════════════════════════════════════════
progress "110/$TOTAL_SECTIONS — Audio Devices"
section "110. AUDIO DEVICES"
AUDIO_DEVICES=$(timeout 30 system_profiler SPAudioDataType 2>/dev/null | grep -E "Device Name|Manufacturer|Channels" | head -20 || echo "unavailable")
echo "$AUDIO_DEVICES"
write_json "audio_devices" "audio_info" "${AUDIO_DEVICES:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 111. CAMERA AND MICROPHONE DEVICES
# ═══════════════════════════════════════════════════════════════
progress "111/$TOTAL_SECTIONS — Camera and Microphone Devices"
section "111. CAMERA AND MICROPHONE DEVICES"
CAMERAS=$(timeout 30 system_profiler SPCameraDataType 2>/dev/null | grep -E "Model|Manufacturer|Unique" | head -10 || echo "unavailable")
echo "$CAMERAS"
write_json "camera_microphone" "camera_info" "${CAMERAS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 112. ACCESSIBILITY SETTINGS
# ═══════════════════════════════════════════════════════════════
progress "112/$TOTAL_SECTIONS — Accessibility Settings"
section "112. ACCESSIBILITY SETTINGS"
A11Y_ZOOM=$(defaults read com.apple.universalaccess closeViewScrollWheelToggle 2>/dev/null || echo "0")
A11Y_VOICE=$(defaults read com.apple.universalaccess voiceOverOnOffKey 2>/dev/null || echo "0")
A11Y_REDUCE=$(defaults read com.apple.universalaccess reduceMotion 2>/dev/null || echo "0")
A11Y_CONTRAST=$(defaults read com.apple.universalaccess increaseContrast 2>/dev/null || echo "0")
echo "Zoom (scroll wheel): $A11Y_ZOOM"
echo "VoiceOver key:       $A11Y_VOICE"
echo "Reduce motion:       $A11Y_REDUCE"
echo "Increase contrast:   $A11Y_CONTRAST"
write_json "accessibility_settings" \
    "zoom_scroll_toggle" "${A11Y_ZOOM:-0}" \
    "voiceover_key" "${A11Y_VOICE:-0}" \
    "reduce_motion" "${A11Y_REDUCE:-0}" \
    "increase_contrast" "${A11Y_CONTRAST:-0}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 113. OPEN FILES ANALYSIS (lsof)
# ═══════════════════════════════════════════════════════════════
progress "113/$TOTAL_SECTIONS — Open Files Analysis"
section "113. OPEN FILES ANALYSIS"
if command -v lsof &>/dev/null; then
    TOTAL_FD=$(timeout 15 lsof 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    TOP_FD_PROCS=$(timeout 15 lsof 2>/dev/null | awk '{print $1}' | sort | uniq -c | sort -rn | head -10 | tr '\n' '|' || echo "unavailable")
    INET_CONNS=$(timeout 15 lsof -i 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    echo "Total open file descriptors: $TOTAL_FD"
    echo "Network connections (lsof):  $INET_CONNS"
    echo "Top processes by FD:"
    echo "$TOP_FD_PROCS" | tr '|' '\n'
    write_json "open_files_analysis" \
        "total_fd" "${TOTAL_FD:-0}" \
        "inet_connections" "${INET_CONNS:-0}" \
        "top_fd_procs" "${TOP_FD_PROCS:-unavailable}"
else
    echo "[SKIPPED] lsof not installed"
    write_json "open_files_analysis" "status" "skipped — lsof not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 114. NETWORK SCAN — LOCAL SUBNET (nmap)
# ═══════════════════════════════════════════════════════════════
progress "114/$TOTAL_SECTIONS — Local Subnet Scan"
section "114. LOCAL SUBNET SCAN (nmap)"
if command -v nmap &>/dev/null; then
    DEFAULT_GW=$(netstat -rn 2>/dev/null | awk '/^default/{print $2; exit}' || echo "")
    if [[ -n "$DEFAULT_GW" ]]; then
        SUBNET=$(echo "$DEFAULT_GW" | awk -F'.' '{print $1"."$2"."$3".0/24"}')
        NMAP_OUT=$(timeout 60 nmap -sn --host-timeout 5s "$SUBNET" 2>/dev/null | grep -E "Nmap scan|Host is up|report" | head -20 || echo "scan failed")
        HOST_COUNT=$(echo "$NMAP_OUT" | grep -c "Host is up" || echo "0")
        echo "Subnet: $SUBNET"
        echo "Hosts up: $HOST_COUNT"
        echo "$NMAP_OUT"
        write_json "subnet_scan" \
            "subnet" "${SUBNET:-unknown}" \
            "hosts_up" "${HOST_COUNT:-0}" \
            "scan_output" "${NMAP_OUT:-unavailable}"
    else
        echo "No default gateway found — skipping scan"
        write_json "subnet_scan" "status" "no gateway found"
    fi
else
    echo "[SKIPPED] nmap not installed"
    write_json "subnet_scan" "status" "skipped — nmap not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 115. PROCESS TREE
# ═══════════════════════════════════════════════════════════════
progress "115/$TOTAL_SECTIONS — Process Tree"
section "115. PROCESS TREE"
TOP_CPU_PROCS=$(ps -eo pid,pcpu,pmem,comm 2>/dev/null | sort -k2 -rn | head -20 | tr '\n' '|' || echo "unavailable")
TOP_MEM_PROCS=$(ps -eo pid,pmem,pcpu,comm 2>/dev/null | sort -k2 -rn | head -10 | tr '\n' '|' || echo "unavailable")
TOTAL_PROCS_COUNT=$(ps aux 2>/dev/null | wc -l | tr -d ' ' || echo "0")
echo "Total processes: $TOTAL_PROCS_COUNT"
echo "Top by CPU:"
echo "$TOP_CPU_PROCS" | tr '|' '\n' | head -10
write_json "process_tree" \
    "total_processes" "${TOTAL_PROCS_COUNT:-0}" \
    "top_cpu" "${TOP_CPU_PROCS:-unavailable}" \
    "top_mem" "${TOP_MEM_PROCS:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 116. FILE DESCRIPTORS PER PROCESS (lsof)
# ═══════════════════════════════════════════════════════════════
progress "116/$TOTAL_SECTIONS — File Descriptors Per Process"
section "116. FILE DESCRIPTORS PER PROCESS"
if command -v lsof &>/dev/null; then
    FD_PER_PROC=$(timeout 15 lsof 2>/dev/null | awk 'NR>1{print $1}' | sort | uniq -c | sort -rn | head -15 | tr '\n' '|' || echo "unavailable")
    echo "Top processes by open file descriptors:"
    echo "$FD_PER_PROC" | tr '|' '\n'
    write_json "fd_per_process" "top_fd_consumers" "${FD_PER_PROC:-unavailable}"
else
    echo "[SKIPPED] lsof not installed"
    write_json "fd_per_process" "status" "skipped — lsof not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 117. LISTENING SERVICES DETAILED (lsof)
# ═══════════════════════════════════════════════════════════════
progress "117/$TOTAL_SECTIONS — Listening Services Detailed"
section "117. LISTENING SERVICES DETAILED"
if command -v lsof &>/dev/null; then
    LISTENING=$(timeout 15 lsof -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $1, $9}' | sort -u | head -30 || echo "unavailable")
    LISTEN_COUNT=$(timeout 15 lsof -iTCP -sTCP:LISTEN 2>/dev/null | wc -l | tr -d ' ' || echo "0")
    echo "Listening TCP services: $LISTEN_COUNT"
    echo "$LISTENING"
    write_json "listening_services" \
        "tcp_listener_count" "${LISTEN_COUNT:-0}" \
        "listeners" "${LISTENING:-unavailable}"
else
    echo "[SKIPPED] lsof not installed"
    write_json "listening_services" "status" "skipped — lsof not installed"
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 118. DNS CACHE STATS
# ═══════════════════════════════════════════════════════════════
progress "118/$TOTAL_SECTIONS — DNS Cache Stats"
section "118. DNS CACHE STATS"
DNS_STATS=$(dscacheutil -statistics 2>/dev/null | head -20 || echo "unavailable")
DNS_FLUSH_NEEDED="NO"
DNS_CACHE_SIZE=$(dscacheutil -statistics 2>/dev/null | awk '/Total/{print $NF}' | head -1 || echo "0")
[[ "${DNS_CACHE_SIZE:-0}" -gt 5000 ]] 2>/dev/null && DNS_FLUSH_NEEDED="YES"
echo "$DNS_STATS"
echo "Cache flush recommended: $DNS_FLUSH_NEEDED"
write_json "dns_cache" \
    "cache_stats" "${DNS_STATS:-unavailable}" \
    "flush_recommended" "${DNS_FLUSH_NEEDED:-NO}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 119. DIRECTORY SERVICE CONFIG
# ═══════════════════════════════════════════════════════════════
progress "119/$TOTAL_SECTIONS — Directory Service Config"
section "119. DIRECTORY SERVICE CONFIG"
LOCAL_USERS=$(timeout 10 dscl . -list /Users 2>/dev/null | grep -v "^_\|daemon\|nobody\|root" | tr '\n' ',' || echo "unavailable")
ADMIN_USERS=$(timeout 10 dscl . -read /Groups/admin GroupMembership 2>/dev/null | sed 's/GroupMembership: //' || echo "unavailable")
BOUND_TO=$(timeout 10 dscl localhost -list / 2>/dev/null | grep -v "Local\|Search\|Contact" | head -5 | tr '\n' ',' || echo "local only")
echo "Local users: $LOCAL_USERS"
echo "Admin group: $ADMIN_USERS"
echo "Directory bindings: $BOUND_TO"
write_json "directory_service" \
    "local_users" "${LOCAL_USERS:-unavailable}" \
    "admin_group" "${ADMIN_USERS:-unavailable}" \
    "directory_bindings" "${BOUND_TO:-local only}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 120. SYSTEM PROFILER FULL SUMMARY
# ═══════════════════════════════════════════════════════════════
progress "120/$TOTAL_SECTIONS — System Profiler Full Summary"
section "120. SYSTEM PROFILER FULL SUMMARY"
SP_HW_OVERVIEW=$(timeout 30 system_profiler SPHardwareDataType SPSoftwareDataType SPMemoryDataType 2>/dev/null | \
    grep -E "System Version|Kernel Version|Memory|Processor|Serial|Hardware UUID|Boot Volume|Computer Name" | \
    head -15 | tr '\n' '|' || echo "unavailable")
echo "$SP_HW_OVERVIEW" | tr '|' '\n'
write_json "system_profiler_summary" "overview" "${SP_HW_OVERVIEW:-unavailable}"
echo ""

# ═══════════════════════════════════════════════════════════════
# JSON OUTPUT
# ═══════════════════════════════════════════════════════════════
progress "Generating JSON output..."

build_json "$JSON_FILE"

# Fix ownership
chown "$ACTUAL_USER" "$REPORT_FILE" "$JSON_FILE" 2>/dev/null

# ═══════════════════════════════════════════════════════════════
# API PUSH (if --push)
# Uses push_results() from render_sync.sh — wraps JSON in the
# DiagnosticSubmission envelope {serial, hostname, client_id, payload}
# ═══════════════════════════════════════════════════════════════
if [[ "$PUSH_MODE" == true ]]; then
    progress "Pushing to Health Check AI API..."
# ─── INLINE: RENDER SYNC MODULE (from render_sync.sh) ───
push_results() {
    local file="$1"
    local client_id="${2:-}"

    if [ ! -f "$file" ]; then
        echo "[ERROR] push_results: file not found: $file"
        return 1
    fi

    local endpoint="${ZA_API_URL:-https://za-health-check-v11.onrender.com}${ZA_API_ENDPOINT:-/api/v1/agent/diagnostics}"

    if [ -z "${ZA_AUTH_TOKEN:-}" ]; then
        echo "[WARN] ZA_AUTH_TOKEN is not set — push will likely be rejected"
    fi

    # The deployed endpoint expects DiagnosticSubmission:
    #   { "serial": "...", "hostname": "...", "client_id": "...", "payload": { <full json> } }
    # Extract serial/hostname from the JSON file, then wrap.
    local serial hostname envelope_file
    serial=$(python3 -c "
import json, sys
with open('$file') as f:
    d = json.load(f)
print(d.get('hardware', {}).get('serial') or d.get('serial') or 'UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

    hostname=$(python3 -c "
import json
with open('$file') as f:
    d = json.load(f)
print(d.get('metadata', {}).get('hostname') or d.get('hostname') or 'unknown')
" 2>/dev/null || echo "unknown")

    envelope_file="/tmp/za_push_envelope_$$.json"

    # Strip ANSI codes and control characters that break JSON
    if [[ -f "$file" ]]; then
        python3 -c "
import json, re, sys
with open('$file', 'r', errors='replace') as f:
    raw = f.read()
raw = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
raw = re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', '', raw)
try:
    data = json.loads(raw)
    with open('$file', 'w') as f:
        json.dump(data, f)
except:
    pass
" 2>/dev/null
    fi

    python3 - <<PYEOF
import json
with open('$file') as f:
    payload = json.load(f)
envelope = {
    "serial":    "$serial",
    "hostname":  "$hostname",
    "client_id": "$client_id",
    "payload":   payload,
}
with open('$envelope_file', 'w') as f:
    json.dump(envelope, f)
PYEOF

    if [ ! -f "$envelope_file" ]; then
        echo "[ERROR] Failed to build upload envelope"
        return 1
    fi

    local response_body http_code
    response_body=$(curl -s -w "\n__HTTP_CODE__%{http_code}" \
        -X POST "$endpoint" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${ZA_AUTH_TOKEN:-}" \
        --data-binary @"$envelope_file" 2>/dev/null || echo "__HTTP_CODE__000")

    http_code=$(printf '%s' "$response_body" | grep -oE '__HTTP_CODE__[0-9]+' | sed 's/__HTTP_CODE__//')
    response_body=$(printf '%s' "$response_body" | sed 's/__HTTP_CODE__[0-9]*$//')

    rm -f "$envelope_file"

    printf 'Endpoint : %s\n' "$endpoint"
    printf 'HTTP Code: %s\n' "${http_code:-000}"
    printf 'Response : %s\n' "$response_body"

    if [ "${http_code:-000}" = "200" ] || [ "${http_code:-000}" = "201" ]; then
        echo "[OK] Pushed to Render API — HTTP $http_code"
        return 0
    else
        echo "[WARN] Render API push failed — HTTP ${http_code:-000}. JSON saved locally: $file"
        return 1
    fi
}

# Legacy alias
push_to_render() {
    push_results "$1" "${2:-}"
}

    push_results "$JSON_FILE" "$CLIENT_ID"
fi

# ═══════════════════════════════════════════════════════════════
# COMPLETION
# ═══════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║   CYBERPULSE ASSESSMENT COMPLETE — v3.3                                ║${NC}"
echo -e "${GREEN}${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}${BOLD}║   Report:  $REPORT_FILE${NC}"
echo -e "${GREEN}${BOLD}║   JSON:    $JSON_FILE${NC}"
echo -e "${GREEN}${BOLD}║   Runtime: $SECONDS seconds                                  ║${NC}"
echo -e "${GREEN}${BOLD}║   Recommendations: $REC_COUNT items                          ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Please email both files to: ${CYAN}admin@zasupport.com${NC}"
echo ""
