#!/bin/bash
# ============================================================================
# ZA Support — Security Module
# Collects: SIP, FileVault, Gatekeeper, Firewall, XProtect, MRT,
#           password manager, AV/EDR, OCLP, profiles, TCC grants
# Writes:   "security" section via write_json
# ============================================================================

collect_security() {
    local sip fv gk fw xprotect mrt stealth block_all pwmgr av oclp_det oclp_ver
    local third_kexts root_patched profiles_count

    # Core security posture
    sip=$(csrutil status 2>/dev/null | head -1)
    fv=$(fdesetup status 2>/dev/null | head -1)
    gk=$(spctl --status 2>/dev/null)
    fw=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>/dev/null)
    stealth=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode 2>/dev/null)
    block_all=$(/usr/libexec/ApplicationFirewall/socketfilterfw --getblockall 2>/dev/null)

    # XProtect / MRT versions
    xprotect=$(defaults read \
        "/Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist" \
        CFBundleShortVersionString 2>/dev/null || echo "Not found")
    mrt=$(defaults read \
        "/Library/Apple/System/Library/CoreServices/MRT.app/Contents/Info.plist" \
        CFBundleShortVersionString 2>/dev/null || echo "Not found")

    # Password manager detection
    pwmgr=""
    for pm in "1Password" "Bitwarden" "Dashlane" "LastPass" "KeePassXC" \
              "Keeper" "NordPass" "RoboForm" "Enpass"; do
        if [ -d "/Applications/${pm}.app" ] || [ -d "/Applications/${pm} 7.app" ]; then
            pwmgr="${pwmgr}${pm} "
        fi
    done
    pwmgr="${pwmgr:-NONE}"

    # AV/EDR detection
    av=""
    for product in "Malwarebytes" "Sophos" "Norton" "McAfee" "Avast" "AVG" \
                   "Bitdefender" "ESET" "Kaspersky" "CrowdStrike Falcon" \
                   "SentinelOne" "Carbon Black" "Jamf Protect" "Intune" \
                   "Kandji" "Mosyle" "Addigy" "Hexnode"; do
        if [ -d "/Applications/${product}.app" ] || \
           ls /Library/LaunchDaemons/ 2>/dev/null \
               | grep -qi "$(printf '%s' "$product" | tr ' ' '.' | tr '[:upper:]' '[:lower:]')"; then
            av="${av}${product} "
        fi
    done
    av="${av:-NONE (XProtect/MRT only)}"

    # OCLP detection
    oclp_det="NO"
    oclp_ver="N/A"
    if [ -d "/Applications/OpenCore-Patcher.app" ]; then
        oclp_det="YES"
        oclp_ver=$(defaults read \
            "/Applications/OpenCore-Patcher.app/Contents/Info.plist" \
            CFBundleShortVersionString 2>/dev/null || echo "Unknown")
    fi
    ls /Library/Application\ Support/Dortania/ 2>/dev/null && oclp_det="YES"

    root_patched="NO"
    [ -f "/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist" ] && root_patched="YES"

    third_kexts=$(kextstat 2>/dev/null | grep -vc com.apple || echo "0")

    # MDM profiles count
    profiles_count=$(profiles show -all 2>/dev/null | grep -c "profileIdentifier" 2>/dev/null || true)
    profiles_count="${profiles_count:-0}"

    # Gatekeeper enabled flag (0/1 for JSON)
    local gk_on
    gk_on=$(spctl --status 2>/dev/null | grep -ci "enabled" || echo "0")

    write_json "security" \
        "sip"                   "$sip" \
        "filevault"             "$fv" \
        "gatekeeper"            "$gk" \
        "gatekeeper_on"         "$gk_on" \
        "firewall"              "$fw" \
        "stealth_mode"          "$stealth" \
        "block_all_incoming"    "$block_all" \
        "xprotect_version"      "$xprotect" \
        "mrt_version"           "$mrt" \
        "password_manager"      "$pwmgr" \
        "av_edr"                "$av" \
        "oclp_detected"         "$oclp_det" \
        "oclp_version"          "$oclp_ver" \
        "oclp_root_patched"     "$root_patched" \
        "third_party_kexts"     "$third_kexts" \
        "mdm_profiles_count"    "$profiles_count"
}

collect_security
