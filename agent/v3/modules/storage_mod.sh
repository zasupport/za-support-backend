#!/bin/bash
# ============================================================================
# ZA Support — Storage Module
# Collects: disk usage, APFS info, SMART health, TRIM, snapshots, recovery
# Writes:   "storage" section via write_json
# ============================================================================

collect_storage() {
    local used_pct free_gb total_gb smart_status trim apfs_volumes
    local snapshot_count recovery_present fusion_present

    # Disk usage for boot volume
    used_pct=$(df -h / 2>/dev/null | awk 'NR==2{print $5}' | tr -d '%')
    free_gb=$(df -g / 2>/dev/null | awk 'NR==2{print $4}')
    total_gb=$(df -g / 2>/dev/null | awk 'NR==2{print $2}')

    # TRIM status
    trim=$(system_profiler SPNVMeDataType 2>/dev/null | grep -i "TRIM" | awk -F': ' '{print $2}' | head -1)
    trim="${trim:-$(system_profiler SPSerialATADataType 2>/dev/null | grep -i "TRIM" | awk -F': ' '{print $2}' | head -1)}"
    trim="${trim:-Unknown}"

    # APFS volume count
    apfs_volumes=$(diskutil apfs list 2>/dev/null | grep -c "APFS Volume" || echo "0")

    # Local snapshots count
    snapshot_count=$(tmutil listlocalsnapshots / 2>/dev/null | grep -c "com.apple.TimeMachine" 2>/dev/null || true)
    snapshot_count="${snapshot_count:-0}"

    # Recovery partition
    if diskutil list 2>/dev/null | grep -qi "Recovery"; then
        recovery_present="YES"
    else
        recovery_present="NO"
    fi

    # Fusion / Core Storage
    if diskutil cs list 2>/dev/null | grep -qi "Fusion"; then
        fusion_present="YES"
    else
        fusion_present="NO"
    fi

    # SMART status via smartctl or IORegistry fallback
    smart_status="Unknown"
    if command -v smartctl &>/dev/null; then
        smart_status=$(smartctl -H /dev/disk0 2>/dev/null \
            | grep -i "overall-health" | awk -F': ' '{print $2}' | tr -d ' ' || echo "Unknown")
    else
        # IORegistry NVMe life/wear
        local nvme_life
        nvme_life=$(ioreg -rc IONVMeController 2>/dev/null \
            | grep -i "life\|wear\|endurance" | head -1 | awk '{print $NF}' | tr -d '"')
        smart_status="${nvme_life:-IOKit-fallback}"
    fi

    # IOKit disk error counters
    local disk_errors
    disk_errors=$(ioreg -rc IOBlockStorageDriver 2>/dev/null \
        | grep -iE "error|retry|timeout" | wc -l | tr -d ' ')

    write_json "storage" \
        "boot_disk_used_pct"   "${used_pct:-0}" \
        "boot_disk_free_gb"    "${free_gb:-0}" \
        "boot_disk_total_gb"   "${total_gb:-0}" \
        "trim_status"          "$trim" \
        "smart_status"         "$smart_status" \
        "apfs_volumes"         "$apfs_volumes" \
        "local_snapshots"      "$snapshot_count" \
        "recovery_partition"   "$recovery_present" \
        "fusion_drive"         "$fusion_present" \
        "iokit_disk_errors"    "$disk_errors"
}

collect_storage
