#!/bin/bash
# ZA Shield Agent — Real-Time File Monitor
# Watches file system for suspicious activity and reports to V11
# Runs as LaunchDaemon (root) for full filesystem visibility

set -o pipefail

INSTALL_DIR="${ZA_INSTALL_DIR:-/usr/local/za-support-diagnostics}"
source "$INSTALL_DIR/config/settings.conf" 2>/dev/null || true

SHIELD_LOG="/var/log/zasupport-shield.log"
API_URL="${ZA_API_URL:-https://api.zasupport.com}"
AUTH_TOKEN="${ZA_AUTH_TOKEN:-}"
SERIAL=$(system_profiler SPHardwareDataType 2>/dev/null | awk -F': ' '/Serial Number/{gsub(/^[ \t]+/,"",$2); print $2}')
HOSTNAME=$(hostname -s)

log_event() {
    local severity="$1"
    local event_type="$2"
    local path="$3"
    local detail="$4"

    echo "$(date '+%d/%m/%Y %H:%M:%S SAST') [$severity] $event_type: $path — $detail" >> "$SHIELD_LOG"

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

monitor_filesystem() {
    log stream --predicate '
        subsystem == "com.apple.FSEvents" OR
        (process == "launchd" AND category == "service") OR
        (subsystem == "com.apple.securityd") OR
        (subsystem == "com.apple.authd")
    ' --style compact 2>/dev/null | while IFS= read -r line; do

        if echo "$line" | grep -qiE 'LaunchDaemon|LaunchAgent'; then
            log_event "HIGH" "PERSISTENCE" "LaunchAgent/Daemon change" "$line"
        fi

        if echo "$line" | grep -qi 'kext'; then
            log_event "HIGH" "KEXT_LOAD" "Kernel extension" "$line"
        fi

        if echo "$line" | grep -qiE 'authentication.*fail|auth.*denied|invalid.*password'; then
            log_event "MEDIUM" "AUTH_FAIL" "Authentication failure" "$line"
        fi

        if echo "$line" | grep -qiE 'SIP.*disable|FileVault.*off|Gatekeeper.*disable'; then
            log_event "CRITICAL" "POLICY_CHANGE" "Security policy modified" "$line"
        fi

    done
}

periodic_scan() {
    while true; do
        sleep 300

        for plist in /Library/LaunchDaemons/*.plist; do
            [[ ! -f "$plist" ]] && continue
            local program
            program=$(defaults read "$plist" Program 2>/dev/null || echo "")
            if [[ -n "$program" ]] && ! codesign -v "$program" &>/dev/null 2>&1; then
                log_event "HIGH" "UNSIGNED_DAEMON" "$plist" "Unsigned binary: $program"
            fi
        done

        find /tmp -type f -perm +111 -newer /tmp/.za_shield_marker 2>/dev/null | while read f; do
            log_event "MEDIUM" "TEMP_EXECUTABLE" "$f" "New executable in /tmp"
        done
        touch /tmp/.za_shield_marker

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

periodic_scan &
monitor_filesystem
