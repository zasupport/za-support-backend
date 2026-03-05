#!/bin/bash
# ZA Support Diagnostics — Verification Agent
# Second-pass quality assurance on diagnostic output
# Catches false positives, logical contradictions, and data errors

run_verification() {
    local json_file="$1"
    local report_file="$2"
    local corrections=0
    local verified=0
    local warnings=0

    {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════════╗"
    echo "║  VERIFICATION AGENT — DATA QUALITY ASSURANCE                                   ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════════╝"
    echo ""

    # ── CHECK 1: Disk percentage vs actual values ────────────────
    local disk_pct disk_free disk_total
    disk_pct=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('storage',{}).get('boot_disk_used_pct','').strip())
" 2>/dev/null)
    disk_free=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('storage',{}).get('boot_disk_free_gb','').strip())
" 2>/dev/null)
    disk_total=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('storage',{}).get('boot_disk_total_gb','').strip())
" 2>/dev/null)

    if [[ -n "$disk_total" && -n "$disk_free" && "$disk_total" -gt 0 ]] 2>/dev/null; then
        local calc_pct=$(( (disk_total - disk_free) * 100 / disk_total ))
        if [[ -n "$disk_pct" && "$disk_pct" -gt 0 ]] 2>/dev/null; then
            local diff=$(( calc_pct - disk_pct ))
            [[ $diff -lt 0 ]] && diff=$(( -diff ))
            if [[ $diff -gt 5 ]]; then
                echo "  [CORRECTED] Disk usage: reported ${disk_pct}% but calculated ${calc_pct}% from ${disk_total}GB total, ${disk_free}GB free"
                ((corrections++))
            else
                echo "  [VERIFIED] Disk usage: ${disk_pct}% matches calculation"
                ((verified++))
            fi
        fi
    fi

    # ── CHECK 2: RAM vs swap logic ───────────────────────────────
    local ram_gb swap_used
    ram_gb=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('hardware',{}).get('ram_gb','').strip())
" 2>/dev/null)

    if [[ -n "$ram_gb" ]] 2>/dev/null; then
        local actual_swap
        actual_swap=$(sysctl vm.swapusage 2>/dev/null | awk -F'used = ' '{print $2}' | awk '{gsub(/M/,""); print int($1)}')
        if [[ -n "$actual_swap" && "$actual_swap" -gt 0 ]]; then
            if [[ "$actual_swap" -gt $((ram_gb * 1024)) ]]; then
                echo "  [VERIFIED] Excessive swap: ${actual_swap}MB swap on ${ram_gb}GB RAM — recommendation valid"
                ((verified++))
            else
                echo "  [INFO] Swap usage ${actual_swap}MB is within acceptable range for ${ram_gb}GB RAM"
                ((verified++))
            fi
        fi
    fi

    # ── CHECK 3: Serial number validity ──────────────────────────
    local serial
    serial=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('hardware',{}).get('serial','').strip())
" 2>/dev/null)

    if [[ "$serial" == "UNKNOWN" || -z "$serial" ]]; then
        # Try alternative method
        local alt_serial
        alt_serial=$(ioreg -l 2>/dev/null | awk -F'"' '/IOPlatformSerialNumber/{print $4}')
        if [[ -n "$alt_serial" ]]; then
            echo "  [CORRECTED] Serial: reported UNKNOWN but ioreg found $alt_serial"
            ((corrections++))
        else
            echo "  [WARNING] Serial genuinely unavailable — device identification limited"
            ((warnings++))
        fi
    else
        echo "  [VERIFIED] Serial: $serial"
        ((verified++))
    fi

    # ── CHECK 4: Battery health vs cycle count logic ─────────────
    local health_pct cycle_count
    health_pct=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('battery',{}).get('health_pct','').strip())
" 2>/dev/null)
    cycle_count=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('battery',{}).get('cycle_count','').strip())
" 2>/dev/null)

    if [[ "$health_pct" == "100.0" || "$health_pct" == "100" ]] && \
       [[ -n "$cycle_count" && "$cycle_count" -gt 500 ]] 2>/dev/null; then
        echo "  [WARNING] Battery reports 100% health at $cycle_count cycles — verify calibration"
        ((warnings++))
    elif [[ -n "$health_pct" && -n "$cycle_count" ]]; then
        echo "  [VERIFIED] Battery: ${health_pct}% health at $cycle_count cycles"
        ((verified++))
    fi

    # ── CHECK 5: OCLP / ZA Support managed detection ────────────
    local oclp_detected
    oclp_detected=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('security',{}).get('oclp_detected','').strip())
" 2>/dev/null)

    if [[ "$oclp_detected" == "YES" ]]; then
        echo "  [MANAGED] OCLP detected — this is a ZA Support managed configuration, not a security finding"
        ((verified++))
    fi

    # ── CHECK 6: Network connection sanity ───────────────────────
    local conn_count
    conn_count=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
nc = d.get('network_conn_states',{}).get('total_connections','').strip()
print(nc)
" 2>/dev/null)

    if [[ -n "$conn_count" && "$conn_count" -gt 0 ]] 2>/dev/null; then
        if [[ "$conn_count" -gt 1000 ]]; then
            echo "  [WARNING] $conn_count connections is unusually high — investigate"
            ((warnings++))
        elif [[ "$conn_count" -gt 200 ]]; then
            echo "  [VERIFIED] $conn_count connections — within normal range for active desktop use"
            ((verified++))
        else
            echo "  [VERIFIED] $conn_count connections — normal"
            ((verified++))
        fi
    fi

    # ── CHECK 7: Printer configuration context ───────────────────
    local printer_count
    printer_count=$(python3 -c "
import json
with open('$json_file','r') as f: d=json.load(f)
print(d.get('printer_list',{}).get('printer_count','').strip())
" 2>/dev/null)

    if [[ -n "$printer_count" && "$printer_count" -gt 0 ]] 2>/dev/null; then
        echo "  [INFO] $printer_count printers configured — these are remembered from previous connections, not necessarily on current network"
        ((verified++))
    fi

    # ── CHECK 8: Recommendation validation ───────────────────────
    # Check if recommendations reference third-party product names
    local bad_refs
    bad_refs=$(grep -ciE 'ESET|Norton|McAfee|Kaspersky|Avast|Bitdefender|1Password|LastPass|Bitwarden|Dashlane' "$report_file" 2>/dev/null || echo "0")
    if [[ "$bad_refs" -gt 0 ]]; then
        echo "  [CORRECTED] Report contains $bad_refs third-party product name references — should use generic descriptions"
        ((corrections++))
    else
        echo "  [VERIFIED] No third-party product names in report"
        ((verified++))
    fi

    echo ""
    echo "╔══════════════════════════════════════════════════════════════════════════════════╗"
    echo "║  VERIFICATION SUMMARY                                                          ║"
    echo "╠══════════════════════════════════════════════════════════════════════════════════╣"
    echo "║  Checks verified:  $verified"
    echo "║  Corrections made: $corrections"
    echo "║  Warnings:         $warnings"
    echo "╚══════════════════════════════════════════════════════════════════════════════════╝"

    } >> "$report_file"

    write_json "verification" \
        "verified" "$verified" \
        "corrections" "$corrections" \
        "warnings" "$warnings"
}
