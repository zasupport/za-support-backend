#!/bin/bash
# ============================================================================
# ZA Support — Hardware Module
# Collects: serial, model, chip type, CPU, RAM, UUID, firmware
# Writes:   "hardware" section via write_json_raw
# ============================================================================

collect_hardware() {
    local serial model chip cpu cores_phys cores_logic ram_gb uuid boot_rom smc arch
    local activation_lock mdm_enrolled firmware_pw

    serial=$(system_profiler SPHardwareDataType 2>/dev/null \
        | awk '/Serial Number/{print $NF}')
    model=$(system_profiler SPHardwareDataType 2>/dev/null \
        | awk -F': ' '/Model Name/{print $2}' | head -1)
    arch=$(uname -m)
    cpu=$(sysctl -n machdep.cpu.brand_string 2>/dev/null \
        || system_profiler SPHardwareDataType 2>/dev/null \
           | awk -F': ' '/Chip/{print $2}' | head -1 \
        || echo "Unknown")
    cores_phys=$(sysctl -n hw.physicalcpu 2>/dev/null || echo "?")
    cores_logic=$(sysctl -n hw.logicalcpu 2>/dev/null || echo "?")
    ram_gb=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}' || echo "?")
    uuid=$(system_profiler SPHardwareDataType 2>/dev/null \
        | awk '/Hardware UUID/{print $NF}')
    boot_rom=$(system_profiler SPHardwareDataType 2>/dev/null \
        | awk -F': ' '/Boot ROM Version/{print $2}' | head -1)
    smc=$(system_profiler SPHardwareDataType 2>/dev/null \
        | awk -F': ' '/SMC Version/{print $2}' | head -1)

    # Chip type
    if printf '%s' "$cpu" | grep -qi "apple"; then
        chip="APPLE_SILICON"
    else
        chip="INTEL"
    fi

    # Activation lock / Find My
    if nvram -p 2>/dev/null | grep -q "fmm-mobileme-token-FMM"; then
        activation_lock="YES"
    else
        activation_lock="NO"
    fi

    # MDM enrollment
    if profiles status -type enrollment 2>/dev/null | grep -qi "enrolled"; then
        mdm_enrolled="YES"
    else
        mdm_enrolled="NO"
    fi

    # Firmware password — only meaningful on Intel; Apple Silicon uses Activation Lock
    firmware_pw=$(firmwarepasswd -check 2>/dev/null \
        | grep -i "Password Enabled" | awk -F': ' '{print $2}' | xargs)
    firmware_pw="${firmware_pw:-N/A (Apple Silicon)}"

    write_json "hardware" \
        "serial"          "$serial" \
        "model"           "$model" \
        "architecture"    "$arch" \
        "chip_type"       "$chip" \
        "cpu"             "$cpu" \
        "cores_physical"  "$cores_phys" \
        "cores_logical"   "$cores_logic" \
        "ram_gb"          "$ram_gb" \
        "hardware_uuid"   "$uuid" \
        "boot_rom"        "$boot_rom" \
        "smc_version"     "${smc:-N/A}" \
        "activation_lock" "$activation_lock" \
        "mdm_enrolled"    "$mdm_enrolled" \
        "firmware_pw"     "${firmware_pw:-N/A}"
}

collect_hardware
