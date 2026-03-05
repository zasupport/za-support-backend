#!/bin/bash
# ============================================================================
# ZA Support — Report Generation Module
# Reads the NDJSON accumulator and writes final JSON + human-readable report
# Also generates personalised recommendations based on collected data
# ============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# RECOMMENDATIONS ENGINE
# Reads fields from the NDJSON accumulator and fires triggers
# ─────────────────────────────────────────────────────────────────────────────

_get_field() {
    # Extract a scalar string value from the NDJSON accumulator by section + field
    # Usage: _get_field "section_key" "field_name"
    local section="$1" field="$2"
    grep "\"key\":\"$section\"" "$ZA_JSON_TEMP" 2>/dev/null \
        | sed "s/.*\"$field\":\"\([^\"]*\)\".*/\1/" \
        | head -1
}

generate_recommendations() {
    local rec_count=0
    local recs_json="["

    _add_rec() {
        local sev="$1" title="$2" evidence="$3" product="$4" price="$5"
        rec_count=$((rec_count + 1))
        local t e p
        t="$(printf '%s' "$title"    | sed 's/"/\\"/g')"
        e="$(printf '%s' "$evidence" | sed 's/"/\\"/g')"
        p="$(printf '%s' "$product"  | sed 's/"/\\"/g')"
        recs_json="${recs_json}{\"id\":${rec_count},\"severity\":\"${sev}\",\"title\":\"${t}\",\"evidence\":\"${e}\",\"product\":\"${p}\",\"price\":\"${price}\"},"
        printf '  [%s] #%d: %s\n' "$sev" "$rec_count" "$title"
        printf '        Evidence: %s\n' "$evidence"
        printf '        → %s: %s\n\n' "$product" "$price"
    }

    # Pull key fields
    local health  cycle fv_status gk_on fw_status sip_status oclp
    local used_pct free_gb pwmgr av swap_mb

    health=$(_get_field "battery" "health_pct")
    cycle=$(_get_field "battery" "cycle_count")
    fv_status=$(_get_field "security" "filevault")
    gk_on=$(_get_field "security" "gatekeeper_on")
    fw_status=$(_get_field "security" "firewall")
    sip_status=$(_get_field "security" "sip")
    oclp=$(_get_field "security" "oclp_detected")
    used_pct=$(_get_field "storage" "boot_disk_used_pct")
    free_gb=$(_get_field "storage" "boot_disk_free_gb")
    pwmgr=$(_get_field "security" "password_manager")
    av=$(_get_field "security" "av_edr")

    # BATTERY
    if [ -n "$health" ] && [ "$health" != "N/A" ]; then
        local h_int
        h_int=$(printf '%.0f' "$health" 2>/dev/null || echo "0")
        if [ "$h_int" -lt 80 ] 2>/dev/null; then
            _add_rec "CRITICAL" "Battery needs replacement" \
                "Battery health ${health}% (${cycle} cycles). Below Apple 80% service threshold." \
                "Battery Replacement" "R 1,899–R 3,499"
        elif [ "$h_int" -lt 85 ] 2>/dev/null; then
            _add_rec "HIGH" "Battery health declining — approaching service threshold" \
                "Battery health ${health}%, ${cycle} cycles. Apple threshold: 80%." \
                "Battery Replacement (preventive) OR AppleCare+" "R 1,899–R 3,499"
        elif [ "$h_int" -lt 90 ] 2>/dev/null; then
            _add_rec "MEDIUM" "Battery showing wear" \
                "Battery health ${health}%, ${cycle} cycles. Monitor for further degradation." \
                "Annual Maintenance Plan (includes battery monitoring)" "R 4,999/yr"
        fi
    fi

    # STORAGE
    if [ -n "$used_pct" ] && [ "$used_pct" != "0" ]; then
        if [ "$used_pct" -gt 90 ] 2>/dev/null; then
            _add_rec "CRITICAL" "Boot disk critically full" \
                "Disk ${used_pct}% full (${free_gb} GB free). macOS needs 15-20% free; updates will fail." \
                "Storage Cleanup + External SSD" "R 1,799 + SSD from R 1,499"
        elif [ "$used_pct" -gt 85 ] 2>/dev/null; then
            _add_rec "HIGH" "Boot disk running low" \
                "Disk ${used_pct}% full (${free_gb} GB free). Approaching performance threshold." \
                "macOS Performance Optimisation (includes cleanup)" "R 1,799"
        fi
    fi

    # FILEVAULT
    if printf '%s' "$fv_status" | grep -qi "off"; then
        _add_rec "CRITICAL" "FileVault disk encryption is OFF" \
            "Disk is unencrypted. If lost or stolen, all files are readable without a password." \
            "Advanced Security Configuration" "R 1,499"
    fi

    # FIREWALL
    if printf '%s' "$fw_status" | grep -qi "disabled\|off"; then
        _add_rec "HIGH" "macOS Firewall is disabled" \
            "Any application can accept incoming network connections without restriction." \
            "Advanced Security Configuration" "R 1,499"
    fi

    # GATEKEEPER
    if [ "${gk_on:-1}" = "0" ]; then
        _add_rec "HIGH" "Gatekeeper is disabled" \
            "Your Mac will run any unsigned application without developer verification." \
            "Advanced Security Configuration" "R 1,499"
    fi

    # SIP (only flag if no OCLP)
    if printf '%s' "$sip_status" | grep -qi "disabled" && [ "${oclp:-NO}" = "NO" ]; then
        _add_rec "CRITICAL" "System Integrity Protection disabled (no OCLP found)" \
            "SIP is off but OpenCore Legacy Patcher is not installed. SIP should only be disabled for OCLP machines." \
            "Security Audit + SIP Re-enable" "R 899/hr"
    fi

    # PASSWORD MANAGER
    if [ "${pwmgr:-NONE}" = "NONE" ]; then
        _add_rec "MEDIUM" "No password manager detected" \
            "Password reuse is the #1 cause of account compromise. No password manager found." \
            "Advanced Security Configuration (includes password manager setup)" "R 1,499"
    fi

    # BACKUP (Time Machine check)
    local tm_dest
    tm_dest=$(tmutil destinationinfo 2>/dev/null | grep -c "Name" || echo "0")
    if [ "$tm_dest" -eq 0 ] 2>/dev/null; then
        local used_gb
        used_gb=$(df -g / 2>/dev/null | awk 'NR==2{print $3}')
        _add_rec "CRITICAL" "No backup configured" \
            "No Time Machine destination and no third-party backup agent. ${used_gb:-Unknown} GB at risk of total loss." \
            "Managed iCloud Backup Setup OR External SSD Backup" "R 899 setup + R 159/mo (iCloud 2TB)"
    fi

    # Close recommendations JSON array (strip trailing comma)
    recs_json="${recs_json%,}]"
    [ "$recs_json" = "]" ] && recs_json="[]"

    # Write recommendations as a raw JSON section
    write_json_raw "recommendations" "$recs_json"
    write_json_simple "recommendation_count" "$rec_count"
}

# ─────────────────────────────────────────────────────────────────────────────
# GENERATE FINAL REPORTS
# ─────────────────────────────────────────────────────────────────────────────

generate_reports() {
    local output_dir="${1:-$OUTPUT_DIR}"
    local serial client_id timestamp json_out txt_out

    serial=$(_get_field "hardware" "serial")
    serial="${serial:-UNKNOWN}"
    client_id="${CLIENT_ID:-}"
    timestamp=$(date "+%Y-%m-%d_%H%M%S")

    json_out="${output_dir}/ZA_Diagnostic_${serial}_${timestamp}.json"
    txt_out="${output_dir}/ZA_Diagnostic_${serial}_${timestamp}.txt"

    mkdir -p "$output_dir"

    # Add runtime metadata
    write_json "metadata" \
        "version"        "3.0" \
        "timestamp"      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        "serial"         "$serial" \
        "hostname"       "$(hostname)" \
        "client_id"      "${client_id:-not-set}" \
        "runtime_secs"   "${SECONDS:-0}"

    # Generate recommendations
    printf '\n=== GENERATING RECOMMENDATIONS ===\n\n'
    generate_recommendations

    # Build JSON output
    build_json "$json_out"
    printf '\n[OK] JSON report: %s\n' "$json_out"

    # Generate human-readable text report
    {
        printf '╔══════════════════════════════════════════════════════════════════════╗\n'
        printf '║  ZA SUPPORT — DIAGNOSTIC ENGINE v3.0                              ║\n'
        printf '╠══════════════════════════════════════════════════════════════════════╣\n'
        printf '║  Serial:     %-54s║\n' "$serial"
        printf '║  Generated:  %-54s║\n' "$(date '+%d/%m/%Y %H:%M:%S')"
        [ -n "$client_id" ] && printf '║  Client:     %-54s║\n' "$client_id"
        printf '╚══════════════════════════════════════════════════════════════════════╝\n\n'

        printf 'Full JSON diagnostic: %s\n\n' "$json_out"

        # Print each NDJSON section as a readable block
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            local key
            key="$(printf '%s' "$line" | sed 's/^{"key":"\([^"]*\)".*$/\1/')"
            printf '─── %s ─────\n' "$key"
            printf '%s' "$line" \
                | sed 's/^{"key":"[^"]*","value"://' \
                | sed 's/}$//' \
                | tr ',' '\n' \
                | sed 's/^"//; s/":/: /; s/"$//' \
                | grep -v '^{$\|^}$'
            printf '\n'
        done < "$ZA_JSON_TEMP"

        printf '\nPlease email both files to: admin@zasupport.com\n'
    } > "$txt_out"

    printf '[OK] Text report:  %s\n' "$txt_out"

    # Fix ownership if running as root
    if [ -n "${ACTUAL_USER:-}" ]; then
        chown "$ACTUAL_USER" "$json_out" "$txt_out" 2>/dev/null
    fi

    # Export paths for orchestrator to use in push
    ZA_JSON_OUT="$json_out"
    ZA_TXT_OUT="$txt_out"
}
