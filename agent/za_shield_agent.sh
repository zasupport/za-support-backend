#!/bin/bash
# ZA Shield Agent — Real-Time File Monitor
# Watches file system for suspicious activity and reports to V11
# Runs as LaunchDaemon (root) for full filesystem visibility

set -o pipefail

INSTALL_DIR="${ZA_INSTALL_DIR:-/usr/local/za-support-diagnostics}"
source "$INSTALL_DIR/config/settings.conf" 2>/dev/null || true

SHIELD_LOG="/var/log/zasupport-shield.log"
API_URL="${ZA_API_URL:-https://za-health-check-v11.onrender.com}"
AUTH_TOKEN="${ZA_AUTH_TOKEN:-}"
SERIAL=$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Serial Number/{gsub(/^[ \t]+/,"",$2); print $2}')
HOSTNAME=$(hostname -s)

# Directories to monitor for suspicious changes
WATCH_DIRS=(
    "/Library/LaunchDaemons"
    "/Library/LaunchAgents"
    "$HOME/Library/LaunchAgents"
    "/Library/StartupItems"
    "/Library/Extensions"
    "/System/Library/Extensions"
    "/usr/local/bin"
    "/tmp"
    "/private/var/tmp"
)

# File patterns that indicate potential threats
SUSPICIOUS_PATTERNS=(
    "*.plist"       # LaunchAgent/Daemon creation
    "*.kext"        # Kernel extension
    "*.dylib"       # Dynamic library injection
    "*.command"     # Script execution
    "*.download"    # Downloaded files
)

log_event() {
    local severity="$1"
    local event_type="$2"
    local path="$3"
    local detail="$4"

    echo "$(date '+%d/%m/%Y %H:%M:%S SAST') [$severity] $event_type: $path — $detail" >> "$SHIELD_LOG"

    # Push to V11 if HIGH or CRITICAL
    if [[ "$severity" == "HIGH" || "$severity" == "CRITICAL" ]]; then
        curl -s --max-time 5 \
            -X POST "${API_URL}/api/v1/shield/events" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${AUTH_TOKEN}" \
            -d "{
                \"serial\": \"$SERIAL\",
                \"hostname\": \"$HOSTNAME\",
                \"severity\": \"$severity\",
                \"event_type\": \"$event_type\",
                \"path\": \"$path\",
                \"detail\": \"$detail\",
                \"timestamp\": \"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\"
            }" 2>/dev/null || true
    fi
}

# Monitor using log stream (built-in, no fswatch needed)
# Watches for file creation/modification in sensitive directories
monitor_filesystem() {
    log stream --predicate '
        subsystem == "com.apple.FSEvents" OR
        (process == "launchd" AND category == "service") OR
        (subsystem == "com.apple.securityd") OR
        (subsystem == "com.apple.authd")
    ' --style compact 2>/dev/null | while IFS= read -r line; do

        # New LaunchAgent/Daemon
        if echo "$line" | grep -qiE 'LaunchDaemon|LaunchAgent'; then
            log_event "HIGH" "PERSISTENCE" "LaunchAgent/Daemon change" "$line"
        fi

        # Kernel extension loaded
        if echo "$line" | grep -qi 'kext'; then
            log_event "HIGH" "KEXT_LOAD" "Kernel extension" "$line"
        fi

        # Authentication failure
        if echo "$line" | grep -qiE 'authentication.*fail|auth.*denied|invalid.*password'; then
            log_event "MEDIUM" "AUTH_FAIL" "Authentication failure" "$line"
        fi

        # Security policy change
        if echo "$line" | grep -qiE 'SIP.*disable|FileVault.*off|Gatekeeper.*disable'; then
            log_event "CRITICAL" "POLICY_CHANGE" "Security policy modified" "$line"
        fi

    done
}

# Periodic checks (every 5 minutes)
periodic_scan() {
    while true; do
        sleep 300

        # Check for new unsigned LaunchDaemons
        for plist in /Library/LaunchDaemons/*.plist; do
            [[ ! -f "$plist" ]] && continue
            local program
            program=$(defaults read "$plist" Program 2>/dev/null || echo "")
            if [[ -n "$program" ]] && ! codesign -v "$program" &>/dev/null 2>&1; then
                log_event "HIGH" "UNSIGNED_DAEMON" "$plist" "Unsigned binary: $program"
            fi
        done

        # Check for suspicious /tmp executables
        find /tmp -type f -perm +111 -newer /tmp/.za_shield_marker 2>/dev/null | while read -r f; do
            log_event "MEDIUM" "TEMP_EXECUTABLE" "$f" "New executable in /tmp"
        done
        touch /tmp/.za_shield_marker

        # Check for DNS changes
        local current_dns
        current_dns=$(scutil --dns 2>/dev/null | awk '/nameserver\[/{print $3}' | sort | md5)
        if [[ -f /tmp/.za_shield_dns ]]; then
            local prev_dns
            prev_dns=$(cat /tmp/.za_shield_dns)
            if [[ "$current_dns" != "$prev_dns" ]]; then
                log_event "HIGH" "DNS_CHANGE" "/etc/resolv.conf" "DNS servers changed"
            fi
        fi
        echo "$current_dns" > /tmp/.za_shield_dns

    done
}

echo "$(date '+%d/%m/%Y %H:%M:%S SAST') ZA Shield Agent started (PID $$)" >> "$SHIELD_LOG"

# Run both monitors
periodic_scan &
monitor_filesystem
