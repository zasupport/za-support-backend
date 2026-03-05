#!/bin/bash
# ============================================================
#  ZA SUPPORT — MACINTOSH DIAGNOSTIC EXPORT
#  Version: 2.1 (Served via Render endpoint v3.0)
#  Sections: 41
#  Output: ~/Desktop/ZA Support Logs/Diagnostic Export [timestamp].zip
#  Distribution: curl -s https://api.zasupport.com/diagnostics/run | bash
#  Contact: admin@zasupport.com | 064 529 5863
# ============================================================

# ─── macOS CHECK ───────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    echo ""
    echo "============================================"
    echo "  ⚠️  THIS SCRIPT IS FOR macOS ONLY"
    echo "============================================"
    echo "  Cannot run on $(uname)."
    exit 1
fi

# ─── OUTPUT SETUP ──────────────────────────────────
OUTPUT_DIR="$HOME/Desktop/ZA Support Logs"
mkdir -p "$OUTPUT_DIR"
TIMESTAMP=$(date '+%d %m %Y %H%M')
SAST_TIME=$(TZ="Africa/Johannesburg" date '+%d/%m/%Y %H:%M:%S SAST')
OUTPUT_FILE="$OUTPUT_DIR/Diagnostic Export $TIMESTAMP.txt"
ZIP_FILE="$OUTPUT_DIR/Diagnostic Export $TIMESTAMP.zip"

# ─── STARTUP WARNING ──────────────────────────────
clear
echo ""
echo "============================================"
echo "  ⚠️  ZA SUPPORT DIAGNOSTIC EXPORT v2.1"
echo "============================================"
echo ""
echo "  ⏱  Estimated time: 3–10 minutes"
echo "  🚫 DO NOT close this window"
echo "  ✅ Progress will be shown below"
echo ""
echo "  Started: $SAST_TIME"
echo ""
echo "============================================"
echo ""

# ─── HELPER FUNCTION ──────────────────────────────
section() {
    local num="$1"
    local title="$2"
    echo "  [$num/41] $title..."
    echo "" >> "$OUTPUT_FILE"
    echo "============================================" >> "$OUTPUT_FILE"
    echo "  SECTION $num: $title" >> "$OUTPUT_FILE"
    echo "  Collected: $(TZ='Africa/Johannesburg' date '+%d/%m/%Y %H:%M:%S SAST')" >> "$OUTPUT_FILE"
    echo "============================================" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
}

# ─── HEADER ────────────────────────────────────────
echo "============================================" > "$OUTPUT_FILE"
echo "  ZA SUPPORT — DIAGNOSTIC EXPORT" >> "$OUTPUT_FILE"
echo "  Version: 2.1" >> "$OUTPUT_FILE"
echo "  Generated: $SAST_TIME" >> "$OUTPUT_FILE"
echo "  Computer: $(scutil --get ComputerName 2>/dev/null || hostname)" >> "$OUTPUT_FILE"
echo "  User: $(whoami)" >> "$OUTPUT_FILE"
echo "============================================" >> "$OUTPUT_FILE"

# ════════════════════════════════════════════════════
#  SECTIONS 1-10: SYSTEM INFORMATION
# ════════════════════════════════════════════════════

section 1 "macOS Version & Build"
sw_vers >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Kernel Version ──" >> "$OUTPUT_FILE"
uname -a >> "$OUTPUT_FILE" 2>&1

section 2 "Hardware Overview"
system_profiler SPHardwareDataType >> "$OUTPUT_FILE" 2>&1

section 3 "System Uptime & Last Reboot"
uptime >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Last Reboot ──" >> "$OUTPUT_FILE"
last reboot | head -5 >> "$OUTPUT_FILE" 2>&1

section 4 "CPU Information"
sysctl -n machdep.cpu.brand_string >> "$OUTPUT_FILE" 2>&1
echo "Physical cores: $(sysctl -n hw.physicalcpu)" >> "$OUTPUT_FILE"
echo "Logical cores: $(sysctl -n hw.logicalcpu)" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo "Current CPU Usage:" >> "$OUTPUT_FILE"
top -l 1 -n 0 | grep "CPU usage" >> "$OUTPUT_FILE" 2>&1

section 5 "Memory (RAM)"
system_profiler SPMemoryDataType >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "Memory Pressure:" >> "$OUTPUT_FILE"
memory_pressure 2>/dev/null | head -5 >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "VM Statistics:" >> "$OUTPUT_FILE"
vm_stat >> "$OUTPUT_FILE" 2>&1

section 6 "Storage & Disk Health"
diskutil list >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Disk Space Usage ──" >> "$OUTPUT_FILE"
df -h >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── APFS Container Info ──" >> "$OUTPUT_FILE"
diskutil apfs list 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── SMART Status ──" >> "$OUTPUT_FILE"
diskutil info disk0 | grep -i "SMART\|Media Name\|Protocol\|Solid State" >> "$OUTPUT_FILE" 2>&1

section 7 "Battery Health (Laptops)"
if system_profiler SPPowerDataType 2>/dev/null | grep -q "Battery"; then
    system_profiler SPPowerDataType >> "$OUTPUT_FILE" 2>&1
    echo "" >> "$OUTPUT_FILE"
    echo "── Battery Condition ──" >> "$OUTPUT_FILE"
    pmset -g batt >> "$OUTPUT_FILE" 2>&1
    echo "" >> "$OUTPUT_FILE"
    echo "── Cycle Count ──" >> "$OUTPUT_FILE"
    ioreg -r -c AppleSmartBattery | grep -i "CycleCount\|MaxCapacity\|CurrentCapacity\|DesignCapacity\|BatteryHealth" >> "$OUTPUT_FILE" 2>&1
else
    echo "Not a laptop or no battery detected." >> "$OUTPUT_FILE"
fi

section 8 "Display Information"
system_profiler SPDisplaysDataType >> "$OUTPUT_FILE" 2>&1

section 9 "USB Devices"
system_profiler SPUSBDataType >> "$OUTPUT_FILE" 2>&1

section 10 "Thunderbolt / USB-C Devices"
system_profiler SPThunderboltDataType >> "$OUTPUT_FILE" 2>&1

# ════════════════════════════════════════════════════
#  SECTIONS 11-15: NETWORK
# ════════════════════════════════════════════════════

section 11 "Network Interfaces"
ifconfig -a >> "$OUTPUT_FILE" 2>&1

section 12 "Wi-Fi Information"
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Preferred Networks ──" >> "$OUTPUT_FILE"
networksetup -listpreferredwirelessnetworks en0 2>/dev/null >> "$OUTPUT_FILE" 2>&1

section 13 "DNS Configuration"
scutil --dns | head -60 >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── /etc/resolv.conf ──" >> "$OUTPUT_FILE"
cat /etc/resolv.conf 2>/dev/null >> "$OUTPUT_FILE" 2>&1

section 14 "External IP & Connectivity"
echo "External IP:" >> "$OUTPUT_FILE"
curl -s --connect-timeout 5 ifconfig.me >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Ping Test (google.com) ──" >> "$OUTPUT_FILE"
ping -c 3 -t 5 google.com >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Ping Test (1.1.1.1) ──" >> "$OUTPUT_FILE"
ping -c 3 -t 5 1.1.1.1 >> "$OUTPUT_FILE" 2>&1

section 15 "Active Network Connections"
netstat -an | grep ESTABLISHED | head -30 >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Listening Ports ──" >> "$OUTPUT_FILE"
lsof -i -P -n | grep LISTEN | head -30 >> "$OUTPUT_FILE" 2>&1

# ════════════════════════════════════════════════════
#  SECTIONS 16-25: SECURITY & SOFTWARE
# ════════════════════════════════════════════════════

section 16 "Firewall Status"
/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate >> "$OUTPUT_FILE" 2>&1
/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode >> "$OUTPUT_FILE" 2>&1
/usr/libexec/ApplicationFirewall/socketfilterfw --getblockall >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Firewall App Rules ──" >> "$OUTPUT_FILE"
/usr/libexec/ApplicationFirewall/socketfilterfw --listapps 2>/dev/null | head -40 >> "$OUTPUT_FILE" 2>&1

section 17 "FileVault Encryption"
fdesetup status >> "$OUTPUT_FILE" 2>&1

section 18 "Gatekeeper & SIP Status"
spctl --status >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── System Integrity Protection ──" >> "$OUTPUT_FILE"
csrutil status >> "$OUTPUT_FILE" 2>&1

section 19 "macOS Security Updates"
softwareupdate --list 2>&1 | head -20 >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"
echo "── XProtect Version ──" >> "$OUTPUT_FILE"
system_profiler SPInstallHistoryDataType | grep -A 2 "XProtect" | tail -6 >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── MRT Version ──" >> "$OUTPUT_FILE"
system_profiler SPInstallHistoryDataType | grep -A 2 "MRT" | tail -6 >> "$OUTPUT_FILE" 2>&1

section 20 "Installed Applications"
ls /Applications/ >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── User Applications ──" >> "$OUTPUT_FILE"
ls ~/Applications/ 2>/dev/null >> "$OUTPUT_FILE" 2>&1

section 21 "Login Items & Startup Apps"
osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Launch Agents (User) ──" >> "$OUTPUT_FILE"
ls ~/Library/LaunchAgents/ 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Launch Agents (System) ──" >> "$OUTPUT_FILE"
ls /Library/LaunchAgents/ 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Launch Daemons ──" >> "$OUTPUT_FILE"
ls /Library/LaunchDaemons/ 2>/dev/null >> "$OUTPUT_FILE" 2>&1

section 22 "Running Processes (Top 25 by CPU)"
ps aux | sort -nrk 3 | head -25 >> "$OUTPUT_FILE" 2>&1

section 23 "Running Processes (Top 25 by Memory)"
ps aux | sort -nrk 4 | head -25 >> "$OUTPUT_FILE" 2>&1

section 24 "Printer Configuration"
lpstat -p -d 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── CUPS Printers ──" >> "$OUTPUT_FILE"
system_profiler SPPrintersDataType >> "$OUTPUT_FILE" 2>&1

section 25 "Bluetooth Devices"
system_profiler SPBluetoothDataType >> "$OUTPUT_FILE" 2>&1

# ════════════════════════════════════════════════════
#  SECTIONS 26-31: USER & SYSTEM CONFIG
# ════════════════════════════════════════════════════

section 26 "User Accounts"
dscl . list /Users | grep -v "^_" >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Current User Groups ──" >> "$OUTPUT_FILE"
groups $(whoami) >> "$OUTPUT_FILE" 2>&1

section 27 "Time Machine Backup"
tmutil destinationinfo 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Last Backup ──" >> "$OUTPUT_FILE"
tmutil latestbackup 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Backup Status ──" >> "$OUTPUT_FILE"
tmutil status 2>/dev/null >> "$OUTPUT_FILE" 2>&1

section 28 "Sharing Services"
echo "File Sharing:" >> "$OUTPUT_FILE"
launchctl list | grep smbd >> "$OUTPUT_FILE" 2>&1
echo "Screen Sharing:" >> "$OUTPUT_FILE"
launchctl list | grep screensharing >> "$OUTPUT_FILE" 2>&1
echo "Remote Login (SSH):" >> "$OUTPUT_FILE"
systemsetup -getremotelogin 2>/dev/null >> "$OUTPUT_FILE" 2>&1
echo "Remote Management:" >> "$OUTPUT_FILE"
launchctl list | grep ARDAgent >> "$OUTPUT_FILE" 2>&1

section 29 "Energy & Power Settings"
pmset -g >> "$OUTPUT_FILE" 2>&1

section 30 "Kernel Extensions"
kextstat 2>/dev/null | grep -v "com.apple" >> "$OUTPUT_FILE" 2>&1
if [ $? -ne 0 ] || [ -z "$(kextstat 2>/dev/null | grep -v 'com.apple')" ]; then
    echo "No third-party kernel extensions found." >> "$OUTPUT_FILE"
fi

section 31 "System Extensions"
systemextensionsctl list 2>/dev/null >> "$OUTPUT_FILE" 2>&1

# ════════════════════════════════════════════════════
#  ⚠️  MID-PROCESS WARNING
#  Sections 32-41 extract Console logs — longest running
# ════════════════════════════════════════════════════
echo ""
echo "  ════════════════════════════════════════"
echo "  ⚠️  ENTERING LOG EXTRACTION PHASE"
echo "  ════════════════════════════════════════"
echo "  Sections 32-41 extract system logs."
echo "  This is the longest part of the process."
echo "  ⏱  Estimated: 2-5 minutes remaining"
echo "  🚫 DO NOT close this window"
echo "  ════════════════════════════════════════"
echo ""

# ════════════════════════════════════════════════════
#  SECTIONS 32-41: CONSOLE LOGS & SYSTEM EVENTS
# ════════════════════════════════════════════════════

section 32 "System Log — Last 100 Lines"
log show --last 1h --style compact 2>/dev/null | tail -100 >> "$OUTPUT_FILE" 2>&1

section 33 "Kernel Log — Last Hour"
log show --last 1h --predicate 'process == "kernel"' --style compact 2>/dev/null | tail -50 >> "$OUTPUT_FILE" 2>&1

section 34 "Authentication Events — Last 24h"
log show --last 24h --predicate 'category == "authentication"' --style compact 2>/dev/null | tail -50 >> "$OUTPUT_FILE" 2>&1

section 35 "Install History — Last 30 Days"
system_profiler SPInstallHistoryDataType 2>/dev/null | head -200 >> "$OUTPUT_FILE" 2>&1

section 36 "Crash Reports — Last 30 Days"
find ~/Library/Logs/DiagnosticReports -name "*.crash" -mtime -30 -exec basename {} \; 2>/dev/null | head -30 >> "$OUTPUT_FILE" 2>&1
find /Library/Logs/DiagnosticReports -name "*.crash" -mtime -30 -exec basename {} \; 2>/dev/null | head -30 >> "$OUTPUT_FILE" 2>&1
if [ -z "$(find ~/Library/Logs/DiagnosticReports /Library/Logs/DiagnosticReports -name '*.crash' -mtime -30 2>/dev/null)" ]; then
    echo "No crash reports in the last 30 days." >> "$OUTPUT_FILE"
fi

section 37 "Disk Errors & I/O Events"
log show --last 24h --predicate 'process == "kernel" AND messageType == error' --style compact 2>/dev/null | grep -i "disk\|I/O\|storage\|apfs" | tail -30 >> "$OUTPUT_FILE" 2>&1
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "No disk-related errors in last 24 hours." >> "$OUTPUT_FILE"
fi

section 38 "Network Events — Last 24h"
log show --last 24h --predicate 'subsystem == "com.apple.network"' --style compact 2>/dev/null | tail -50 >> "$OUTPUT_FILE" 2>&1

section 39 "Security Events — Last 24h"
log show --last 24h --predicate 'subsystem == "com.apple.securityd" OR subsystem == "com.apple.Authorization"' --style compact 2>/dev/null | tail -50 >> "$OUTPUT_FILE" 2>&1

section 40 "Software Update Log"
cat /var/log/install.log 2>/dev/null | tail -50 >> "$OUTPUT_FILE" 2>&1

section 41 "System Diagnostics Summary"
echo "── Disk Usage Summary ──" >> "$OUTPUT_FILE"
df -h / >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Memory Summary ──" >> "$OUTPUT_FILE"
top -l 1 -n 0 | grep "PhysMem" >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Load Average ──" >> "$OUTPUT_FILE"
sysctl -n vm.loadavg >> "$OUTPUT_FILE" 2>&1
echo "" >> "$OUTPUT_FILE"
echo "── Collection Complete ──" >> "$OUTPUT_FILE"
echo "Total sections: 41" >> "$OUTPUT_FILE"
echo "Completed: $(TZ='Africa/Johannesburg' date '+%d/%m/%Y %H:%M:%S SAST')" >> "$OUTPUT_FILE"

# ════════════════════════════════════════════════════
#  AUTO-ZIP COMPRESSION
# ════════════════════════════════════════════════════
if [ -f "$OUTPUT_FILE" ]; then
    cd "$OUTPUT_DIR"
    zip -j "$ZIP_FILE" "$OUTPUT_FILE" > /dev/null 2>&1
    if [ -f "$ZIP_FILE" ]; then
        rm "$OUTPUT_FILE"
        FINAL_FILE="$ZIP_FILE"
        FINAL_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
    else
        FINAL_FILE="$OUTPUT_FILE"
        FINAL_SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
    fi
else
    FINAL_FILE="$OUTPUT_FILE"
    FINAL_SIZE="0B"
fi

# ════════════════════════════════════════════════════
#  EXPORT COMPLETE BANNER
# ════════════════════════════════════════════════════
echo ""
echo "============================================"
echo "  ✅ EXPORT COMPLETE"
echo "  File: $FINAL_FILE"
echo "  Size: $FINAL_SIZE"
echo "============================================"
echo ""
echo "  Please send this file to ZA Support"
echo "  via WhatsApp or email."
echo ""
echo "  admin@zasupport.com | 064 529 5863"
echo ""
echo "============================================"
