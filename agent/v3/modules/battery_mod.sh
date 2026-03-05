#!/bin/bash
# ============================================================================
# ZA Support — Battery Module
# Collects: health%, cycle count, design/max capacity, condition, temp,
#           charge state, adapter info
# Writes:   "battery" section via write_json
# ============================================================================

collect_battery() {
    local design_cap max_cap cycle condition temp_raw temp_c health
    local charging external_connected adapter_watts is_desktop

    # Check if this is a desktop (no battery)
    if ! ioreg -rn AppleSmartBattery 2>/dev/null | grep -q '"CycleCount" ='; then
        write_json "battery" \
            "present"   "NO" \
            "note"      "Desktop Mac or no battery data available"
        return 0
    fi

    # Anchor all greps to ' =' so we match the scalar property line, not embedded dict blobs
    design_cap=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"DesignCapacity" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)
    max_cap=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"MaxCapacity" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)
    cycle=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"CycleCount" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)
    condition=$(system_profiler SPPowerDataType 2>/dev/null \
        | awk -F': ' '/Condition/{print $2}' | head -1 | xargs)
    temp_raw=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"Temperature" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)

    # Calculate health percentage
    # Apple Silicon: MaxCapacity is already a % (0-100); Intel: MaxCapacity is mAh
    local is_apple_silicon
    is_apple_silicon=$(sysctl -n machdep.cpu.brand_string 2>/dev/null | grep -ci "apple" || echo "0")
    if [ -n "$max_cap" ] && [ "${max_cap:-0}" -gt 0 ] 2>/dev/null; then
        if [ "${is_apple_silicon:-0}" -gt 0 ] && [ "${max_cap:-0}" -le 100 ] 2>/dev/null; then
            # Apple Silicon: MaxCapacity IS the health percentage
            health="${max_cap}"
        elif [ -n "$design_cap" ] && [ "${design_cap:-0}" -gt 0 ] 2>/dev/null; then
            # Intel: derive health from mAh ratio
            health=$(echo "scale=1; ($max_cap * 100) / $design_cap" | bc 2>/dev/null || echo "N/A")
        else
            health="N/A"
        fi
    else
        health="N/A"
    fi

    # Temperature in °C (raw value is in units of 0.01°C)
    if [ -n "$temp_raw" ] && [ "${temp_raw:-0}" -gt 0 ] 2>/dev/null; then
        temp_c=$(echo "scale=1; $temp_raw / 100" | bc 2>/dev/null || echo "N/A")
    else
        temp_c="N/A"
    fi

    # Charge state — anchored greps
    charging=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"IsCharging" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)
    [ "$charging" = "Yes" ] && charging="YES" || charging="NO"

    external_connected=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"ExternalConnected" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)
    [ "$external_connected" = "Yes" ] && external_connected="YES" || external_connected="NO"

    # Adapter wattage
    adapter_watts=$(ioreg -rn AppleSmartBattery 2>/dev/null \
        | grep '"Watts" =' | awk -F'= ' '{print $2}' | tr -d ' ' | head -1)
    adapter_watts="${adapter_watts:-N/A}"

    write_json "battery" \
        "present"              "YES" \
        "health_pct"           "${health:-N/A}" \
        "cycle_count"          "${cycle:-N/A}" \
        "design_capacity_mah"  "${design_cap:-N/A}" \
        "max_capacity_mah"     "${max_cap:-N/A}" \
        "condition"            "${condition:-Unknown}" \
        "temp_celsius"         "$temp_c" \
        "is_charging"          "$charging" \
        "external_connected"   "$external_connected" \
        "adapter_watts"        "${adapter_watts:-N/A}"
}

collect_battery
