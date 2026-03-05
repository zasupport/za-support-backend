#!/bin/bash
# ============================================================================
# ZA SUPPORT — CyberPulse Assessment Engine v3.3
# Modular orchestrator — Bash 3.2 compatible
#
# Usage:
#   sudo ./run_diagnostic.sh [--quick] [--push] [--client CLIENT_ID] [--json-only]
#
# Output:
#   ~/Desktop/ZA_Diagnostic_<serial>_<timestamp>.txt
#   ~/Desktop/ZA_Diagnostic_<serial>_<timestamp>.json
# ============================================================================

set -o pipefail

# ─────────────────────────────────────────────────────────────────────────────
# RESOLVE PATHS
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODULES_DIR="$PROJECT_ROOT/modules"
CONFIG_DIR="$PROJECT_ROOT/config"
OUTPUT_DIR="$PROJECT_ROOT/output"

# Load client config early — sets ZA_API_URL, ZA_API_TOKEN, ZA_AUTH_TOKEN etc.
source "$PROJECT_ROOT/config/settings.conf" 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────────────
# FLAGS
# ─────────────────────────────────────────────────────────────────────────────
BOLD="\033[1m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"
RED="\033[0;31m"; CYAN="\033[0;36m"; NC="\033[0m"

QUICK_MODE=false
PUSH_MODE=false
JSON_ONLY=false
CLIENT_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --quick)     QUICK_MODE=true;  shift ;;
        --push)      PUSH_MODE=true;   shift ;;
        --json-only) JSON_ONLY=true;   shift ;;
        --client)    CLIENT_ID="$2";   shift 2 ;;
        --output)    OUTPUT_DIR="$2";  shift 2 ;;
        *) printf '%b[ERROR]%b Unknown option: %s\n' "$RED$BOLD" "$NC" "$1" >&2; exit 1 ;;
    esac
done

# ─────────────────────────────────────────────────────────────────────────────
# ROOT CHECK
# ─────────────────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    printf '%b[ERROR]%b This script must be run with sudo.\n' "$RED$BOLD" "$NC"
    printf 'Usage: sudo %s [--quick] [--push --client CLIENT_ID]\n' "$0"
    exit 1
fi

ACTUAL_USER="${SUDO_USER:-$(whoami)}"
ACTUAL_HOME=$(eval echo "~$ACTUAL_USER")

# ─────────────────────────────────────────────────────────────────────────────
# LOAD CORE (accumulator + environment)
# ─────────────────────────────────────────────────────────────────────────────
# shellcheck source=../core/za_diag_v3.sh
source "$PROJECT_ROOT/core/za_diag_v3.sh"

# Auto-detect client ID from serial if --client not passed
if [ -z "$CLIENT_ID" ]; then
    _SERIAL=$(system_profiler SPHardwareDataType 2>/dev/null | awk '/Serial Number/{print $NF}' || echo "UNKNOWN")
    CLIENT_ID=$(lookup_client_id "$_SERIAL")
    unset _SERIAL
fi

# ─────────────────────────────────────────────────────────────────────────────
# BANNER
# ─────────────────────────────────────────────────────────────────────────────
printf '%b╔══════════════════════════════════════════════════════════════╗%b\n' "$GREEN$BOLD" "$NC"
printf '%b║   ZA SUPPORT — CyberPulse Assessment Engine v3.3            ║%b\n' "$GREEN$BOLD" "$NC"
printf '%b║   %-58s║%b\n' "$GREEN$BOLD" \
    "$([ "$QUICK_MODE" = true ] && echo 'QUICK MODE (~2 min)' || echo 'FULL MODE')" "$NC"
printf '%b╚══════════════════════════════════════════════════════════════╝%b\n' "$GREEN$BOLD" "$NC"
printf '\n'

progress() { printf '%b  ▶ %s%b\n' "$CYAN" "$1" "$NC"; }

# ─────────────────────────────────────────────────────────────────────────────
# COLLECTION PHASE — source each module (modules auto-execute collect_*)
# ─────────────────────────────────────────────────────────────────────────────
COLLECT_MODULES="hardware_mod security_mod storage_mod battery_mod network_mod"
[ "$QUICK_MODE" = false ] && COLLECT_MODULES="$COLLECT_MODULES"

step=0
for mod_name in $COLLECT_MODULES; do
    mod_file="$MODULES_DIR/${mod_name}.sh"
    if [ -r "$mod_file" ]; then
        step=$((step + 1))
        progress "$step — Loading $mod_name"
        # shellcheck disable=SC1090
        source "$mod_file"
    else
        printf '%b  [SKIP] %s not found%b\n' "$YELLOW" "$mod_file" "$NC"
    fi
done

# ─────────────────────────────────────────────────────────────────────────────
# REPORT GENERATION PHASE
# ─────────────────────────────────────────────────────────────────────────────
step=$((step + 1))
progress "$step — Generating reports (recommendations + JSON + text)"

# Source report_gen which provides generate_reports()
source "$MODULES_DIR/report_gen.sh"

# Default output to Desktop
DESKTOP_OUTPUT="$ACTUAL_HOME/Desktop"
generate_reports "$DESKTOP_OUTPUT"

# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL API PUSH
# ─────────────────────────────────────────────────────────────────────────────
if [ "$PUSH_MODE" = true ]; then
    progress "Pushing to Health Check v11 API..."
    source "$MODULES_DIR/render_sync.sh"
    push_results "${ZA_JSON_OUT:-}" "$CLIENT_ID" || true
fi

# ─────────────────────────────────────────────────────────────────────────────
# COMPLETION
# ─────────────────────────────────────────────────────────────────────────────
printf '\n'
printf '%b╔══════════════════════════════════════════════════════════════╗%b\n' "$GREEN$BOLD" "$NC"
printf '%b║   CYBERPULSE ASSESSMENT COMPLETE — v3.3                     ║%b\n' "$GREEN$BOLD" "$NC"
printf '%b╠══════════════════════════════════════════════════════════════╣%b\n' "$GREEN$BOLD" "$NC"
printf '%b║   JSON:    %-50s║%b\n' "$GREEN$BOLD" "${ZA_JSON_OUT:-N/A}" "$NC"
printf '%b║   Report:  %-50s║%b\n' "$GREEN$BOLD" "${ZA_TXT_OUT:-N/A}"  "$NC"
printf '%b║   Runtime: %-3s seconds                                      ║%b\n' "$GREEN$BOLD" "$SECONDS" "$NC"
printf '%b╚══════════════════════════════════════════════════════════════╝%b\n' "$GREEN$BOLD" "$NC"
printf '\nEmail both files to: %badmin@zasupport.com%b\n\n' "$CYAN" "$NC"
