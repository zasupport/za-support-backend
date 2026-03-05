#!/bin/bash
# ============================================================================
# ZA Support — CyberPulse Smart Scheduler v2.0
#
# Runs every 4h via LaunchDaemon (StartInterval=14400).
# On EVERY tick:
#   1. Attempt to flush any queued diagnostics to the API (offline recovery)
#   2. Decide whether to run a full scan:
#      - Only once per calendar day
#      - Only if a console user is logged in
#      - Only if CPU load is below threshold (defers if machine under heavy use)
#      - Retries on next 4h tick if any condition fails
#   3. After scan: queue JSON locally, then immediately attempt flush
#
# Queue persists for up to 30 days — handles machines offline for days/weeks.
# ============================================================================

set -o pipefail

INSTALL_DIR="${ZA_INSTALL_DIR:-/usr/local/za-support-diagnostics}"
LOG_FILE="/var/log/zasupport-diagnostic.log"
STAMP_FILE="/tmp/za_diag_last_run"
QUEUE_DIR="$INSTALL_DIR/output/queued"
TODAY=$(date '+%Y-%m-%d')

# ── Bundled tool injection ────────────────────────────────────────────────────
MACHINE_ARCH="$(uname -m 2>/dev/null || echo unknown)"
BUNDLED_TOOLS="$INSTALL_DIR/tools/$MACHINE_ARCH"
if [[ -d "$BUNDLED_TOOLS" ]]; then
    export PATH="$BUNDLED_TOOLS:$PATH"
fi

# ── Config & auth ─────────────────────────────────────────────────────────────
source "$INSTALL_DIR/config/settings.conf" 2>/dev/null || true
source "$INSTALL_DIR/modules/render_sync.sh" 2>/dev/null || true

LOGTS() { date '+%d/%m/%Y %H:%M:%S SAST'; }
log()   { echo "$(LOGTS) — $*" >> "$LOG_FILE"; }

# ── Network check ─────────────────────────────────────────────────────────────
# Returns 0 (true) if internet is reachable.
network_available() {
    ping -c 1 -t 5 8.8.8.8 &>/dev/null ||
    ping -c 1 -t 5 1.1.1.1 &>/dev/null ||
    curl -sf --max-time 8 "https://api.zasupport.com/health" -o /dev/null &>/dev/null
}

# ── CPU load check ────────────────────────────────────────────────────────────
# Returns 0 (true) if 1-min load average is below 70% of available CPUs.
# Defers the scan if the machine is busy — avoids disrupting active users.
cpu_idle() {
    local load ncpu
    # sysctl vm.loadavg returns: "{ 1.23 0.98 0.87 }" — field 2 is 1-min avg
    load=$(sysctl -n vm.loadavg 2>/dev/null | awk '{gsub(/[{}]/,""); print $1}')
    ncpu=$(sysctl -n hw.ncpu 2>/dev/null || echo 1)
    # Allow load up to 70% of nCPU (e.g. nCPU=8 → threshold=5.6)
    awk -v load="$load" -v ncpu="$ncpu" 'BEGIN { exit (load+0 > ncpu * 0.7) ? 1 : 0 }'
}

# ── Push a single queued JSON file ───────────────────────────────────────────
push_json_file() {
    local json_file="$1"
    local client_id="${ZA_CLIENT_ID:-${ZA_API_TOKEN:-}}"
    if type push_results &>/dev/null; then
        push_results "$json_file" "$client_id"
    else
        log "[WARN] render_sync not loaded — cannot push $json_file"
        return 1
    fi
}

# ── Queue a JSON file for later push ─────────────────────────────────────────
queue_json() {
    local src="$1"
    [[ -f "$src" ]] || { log "[WARN] queue_json: file not found: $src"; return 1; }
    mkdir -p "$QUEUE_DIR"
    local dest="$QUEUE_DIR/za_diag_$(date '+%Y%m%d_%H%M%S')_$$.json"
    cp "$src" "$dest" && log "[QUEUE] Saved for later push: $(basename "$dest")"
}

# ── Flush all queued files when network is available ─────────────────────────
# Called on every tick regardless of whether a scan runs.
flush_queue() {
    [[ -d "$QUEUE_DIR" ]] || return 0

    # Remove files older than 30 days (data too stale to be useful)
    find "$QUEUE_DIR" -name "*.json" -mtime +30 -delete 2>/dev/null

    # Count queued files
    local queued
    queued=$(find "$QUEUE_DIR" -name "*.json" -type f 2>/dev/null | wc -l | tr -d ' ')
    [[ "$queued" -eq 0 ]] && return 0

    if ! network_available; then
        log "[QUEUE] Network unavailable — $queued file(s) pending, will retry next interval"
        return 1
    fi

    log "[QUEUE] Network up — flushing $queued queued diagnostic(s)"
    local pushed=0 failed=0
    for qf in "$QUEUE_DIR"/*.json; do
        [[ -f "$qf" ]] || continue
        if push_json_file "$qf" >> "$LOG_FILE" 2>&1; then
            rm -f "$qf"
            pushed=$((pushed + 1))
        else
            failed=$((failed + 1))
            log "[QUEUE] Flush failed: $(basename "$qf") — will retry"
        fi
    done
    log "[QUEUE] Flush complete — pushed: $pushed, failed: $failed"
}

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — Always flush queue first (offline data recovery)
# ═════════════════════════════════════════════════════════════════════════════
flush_queue

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — Check if a full scan is needed today
# ═════════════════════════════════════════════════════════════════════════════
if [[ -f "$STAMP_FILE" ]] && [[ "$(cat "$STAMP_FILE" 2>/dev/null)" == "$TODAY" ]]; then
    log "[SKIP] Scan already completed today — next window: tomorrow"
    exit 0
fi

# ─ Require a real console user (not root or display server) ──────────────────
CONSOLE_USER=$(stat -f '%Su' /dev/console 2>/dev/null || echo "")
if [[ -z "$CONSOLE_USER" || "$CONSOLE_USER" == "root" || "$CONSOLE_USER" == "_windowserver" ]]; then
    log "[DEFER] No console user active — will retry next 4h interval"
    exit 0
fi

# ─ CPU idle check — defer if machine is under load ───────────────────────────
if ! cpu_idle; then
    LOAD=$(sysctl -n vm.loadavg 2>/dev/null | awk '{gsub(/[{}]/,""); print $1}')
    NCPU=$(sysctl -n hw.ncpu 2>/dev/null || echo "?")
    log "[DEFER] CPU load ${LOAD} / ${NCPU} CPUs — system busy, deferring scan to next interval"
    exit 0
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — Run full diagnostic (without --push; we handle push via queue)
# ═════════════════════════════════════════════════════════════════════════════
CONSOLE_HOME=$(eval echo "~$CONSOLE_USER" 2>/dev/null || echo "/Users/$CONSOLE_USER")

log ""
log "[START] CyberPulse diagnostic starting (user: $CONSOLE_USER)"

export SUDO_USER="$CONSOLE_USER"
export CONSOLE_USER CONSOLE_HOME

# Homebrew fallback (only if no bundled tools)
if [[ ! -d "$BUNDLED_TOOLS" ]]; then
    BREW_BIN=""
    [[ -f /opt/homebrew/bin/brew ]] && BREW_BIN="/opt/homebrew/bin/brew"
    [[ -z "$BREW_BIN" && -f /usr/local/bin/brew ]] && BREW_BIN="/usr/local/bin/brew"
fi

# Snapshot Desktop before scan to detect new files created by it
DESKTOP_BEFORE=$(mktemp)
ls -1t "$CONSOLE_HOME/Desktop"/ZA_Diagnostic_*.json 2>/dev/null > "$DESKTOP_BEFORE" || true

cd "$INSTALL_DIR" || exit 1

# Run the full scan — 30-minute cap; output goes to log
SCAN_EXIT=0
timeout 1800 bash bin/za_diag_full.sh >> "$LOG_FILE" 2>&1 || SCAN_EXIT=$?

if [[ $SCAN_EXIT -eq 124 ]]; then
    log "[WARN] Scan timed out after 1800s — will retry tomorrow"
    rm -f "$DESKTOP_BEFORE"
    exit 0
elif [[ $SCAN_EXIT -ne 0 ]]; then
    log "[WARN] Scan exited with code $SCAN_EXIT — will retry tomorrow"
    # Mark today so we don't immediately retry in every remaining tick today
    echo "$TODAY" > "$STAMP_FILE"
    rm -f "$DESKTOP_BEFORE"
    exit 0
fi

log "[OK] Scan complete"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — Find the JSON output file and queue it
# ═════════════════════════════════════════════════════════════════════════════
# Find the newest .json on Desktop that was NOT there before the scan started
JSON_FILE=""
while IFS= read -r candidate; do
    if ! grep -qxF "$candidate" "$DESKTOP_BEFORE" 2>/dev/null; then
        JSON_FILE="$candidate"
        break
    fi
done < <(ls -1t "$CONSOLE_HOME/Desktop"/ZA_Diagnostic_*.json 2>/dev/null)
rm -f "$DESKTOP_BEFORE"

if [[ -z "$JSON_FILE" || ! -f "$JSON_FILE" ]]; then
    # Fallback: find any ZA_Diagnostic JSON from today
    JSON_FILE=$(find "$CONSOLE_HOME/Desktop" -name "ZA_Diagnostic_*.json" \
        -newer "$STAMP_FILE" -type f 2>/dev/null | sort | tail -1)
fi

if [[ -z "$JSON_FILE" || ! -f "$JSON_FILE" ]]; then
    log "[WARN] Could not locate diagnostic JSON output — data not queued"
else
    log "[OK] Diagnostic JSON: $JSON_FILE"
    queue_json "$JSON_FILE"
fi

# Mark scan as done for today
echo "$TODAY" > "$STAMP_FILE"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — Immediately attempt to push (flush queue)
# ═════════════════════════════════════════════════════════════════════════════
flush_queue

log "[DONE] CyberPulse diagnostic cycle complete"
