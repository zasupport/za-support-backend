#!/bin/bash
# ============================================================================
# ZA Support — Per-Client macOS .pkg Builder
# Run on a Mac (requires macOS pkgbuild + productbuild — Xcode CLI tools).
#
# Usage:
#   sudo bash scripts/build_client_pkg.sh <client_id> [output_dir]
#
# Example:
#   sudo bash scripts/build_client_pkg.sh evan-shoul ~/Desktop
#   → ~/Desktop/ZA Support Installer evan-shoul.pkg
#
# Requires:
#   - AGENT_AUTH_TOKEN env var (or set TOKEN below)
#   - Xcode Command Line Tools (xcode-select --install)
#   - macOS only
# ============================================================================

set -euo pipefail

CLIENT_ID="${1:-}"
OUT_DIR="${2:-$HOME/Desktop}"
API_URL="https://api.zasupport.com"
TOKEN="${AGENT_AUTH_TOKEN:-fTiuW8z2Aspb8O0Q0kqEr8U7Fe3iIwXdmNmWqP7XOrOs88Pv8teOwpplf_6y0SYU}"

if [[ -z "$CLIENT_ID" ]]; then
  echo "Usage: sudo bash scripts/build_client_pkg.sh <client_id> [output_dir]"
  echo "Example: sudo bash scripts/build_client_pkg.sh evan-shoul ~/Desktop"
  exit 1
fi

if ! command -v pkgbuild &>/dev/null; then
  echo "ERROR: pkgbuild not found. Install Xcode Command Line Tools: xcode-select --install"
  exit 1
fi

echo "=== ZA Support .pkg Builder ==="
echo "Client: $CLIENT_ID"
echo "Output: $OUT_DIR"
echo ""

BUILD_DIR=$(mktemp -d)
PKG_ROOT="$BUILD_DIR/root"
SCRIPTS_DIR="$BUILD_DIR/scripts"
mkdir -p "$PKG_ROOT/usr/local/za-support-diagnostics/config" "$SCRIPTS_DIR"

# ── preinstall: write settings.conf + bootstrap_url ──────────────────────────
cat > "$SCRIPTS_DIR/preinstall" << PREEOF
#!/bin/bash
set -e
INSTALL_DIR="/usr/local/za-support-diagnostics"
mkdir -p "\$INSTALL_DIR/config"

cat > "\$INSTALL_DIR/config/settings.conf" << CONFEOF
# ZA Support — Client Configuration
# Client: ${CLIENT_ID}
ZA_API_URL="${API_URL}"
ZA_API_ENDPOINT="/api/v1/agent/diagnostics"
ZA_AUTH_TOKEN="${TOKEN}"
ZA_API_TOKEN="${TOKEN}"
ZA_CLIENT_ID="${CLIENT_ID}"
CONFEOF

chmod 600 "\$INSTALL_DIR/config/settings.conf"
printf '%s' "${API_URL}/agent/repair?client_id=${CLIENT_ID}&token=${TOKEN}" > "\$INSTALL_DIR/config/.bootstrap_url"
chmod 600 "\$INSTALL_DIR/config/.bootstrap_url"
PREEOF
chmod 755 "$SCRIPTS_DIR/preinstall"

# ── postinstall: download all agent scripts + register LaunchDaemons ─────────
cat > "$SCRIPTS_DIR/postinstall" << 'POSTEOF'
#!/bin/bash
set -e
INSTALL_DIR="/usr/local/za-support-diagnostics"
API_URL="__API_URL__"
TOKEN="__TOKEN__"
CLIENT_ID="__CLIENT_ID__"

mkdir -p "$INSTALL_DIR/agent" "$INSTALL_DIR/bin" "$INSTALL_DIR/modules" "$INSTALL_DIR/core" "$INSTALL_DIR/output"

echo "[1/4] Downloading Shield Agent..."
curl -fsSL --max-time 60 "$API_URL/agent/za_shield_agent.sh" -o "$INSTALL_DIR/agent/za_shield_agent.sh"
chmod 755 "$INSTALL_DIR/agent/za_shield_agent.sh"

echo "[2/4] Downloading Auto-Updater..."
curl -fsSL --max-time 60 "$API_URL/agent/update.sh" -o "$INSTALL_DIR/agent/update.sh"
chmod 755 "$INSTALL_DIR/agent/update.sh"

echo "[3/4] Downloading Health Check Scout V3..."
for pair in \
  "core/za_diag_v3.sh:core" \
  "bin/za_diag_full.sh:bin" \
  "bin/za_diag_scheduled.sh:bin" \
  "bin/run_diagnostic.sh:bin" \
  "modules/battery_mod.sh:modules" \
  "modules/forensic_mod.sh:modules" \
  "modules/hardware_mod.sh:modules" \
  "modules/malware_scan.sh:modules" \
  "modules/network_mod.sh:modules" \
  "modules/render_sync.sh:modules" \
  "modules/report_gen.sh:modules" \
  "modules/security_mod.sh:modules" \
  "modules/storage_mod.sh:modules" \
  "modules/threat_intel.sh:modules" \
  "modules/verification_agent.sh:modules"; do
  file="${pair%%:*}"
  dir="${pair##*:}"
  curl -fsSL --max-time 60 "$API_URL/agent/v3/$file" -o "$INSTALL_DIR/$file" || true
done
chmod -R 755 "$INSTALL_DIR/bin" "$INSTALL_DIR/modules" "$INSTALL_DIR/core" 2>/dev/null || true

echo "[4/4] Registering LaunchDaemons..."

# Shield Agent daemon
cat > /Library/LaunchDaemons/com.zasupport.shield.plist << 'PLIST1'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.zasupport.shield</string>
  <key>ProgramArguments</key><array><string>/usr/local/za-support-diagnostics/agent/za_shield_agent.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/zasupport-shield.log</string>
  <key>StandardErrorPath</key><string>/var/log/zasupport-shield.log</string>
</dict>
</plist>
PLIST1

# Updater daemon (hourly)
cat > /Library/LaunchDaemons/com.zasupport.updater.plist << 'PLIST2'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.zasupport.updater</string>
  <key>ProgramArguments</key><array><string>/usr/local/za-support-diagnostics/agent/update.sh</string></array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/var/log/zasupport-update.log</string>
  <key>StandardErrorPath</key><string>/var/log/zasupport-update.log</string>
</dict>
</plist>
PLIST2

# Diagnostic scheduler (4-hour tick)
cat > /Library/LaunchDaemons/com.zasupport.diagnostic.plist << 'PLIST3'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.zasupport.diagnostic</string>
  <key>ProgramArguments</key><array><string>/usr/local/za-support-diagnostics/bin/za_diag_scheduled.sh</string></array>
  <key>StartInterval</key><integer>14400</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>/var/log/zasupport-diag.log</string>
  <key>StandardErrorPath</key><string>/var/log/zasupport-diag.log</string>
</dict>
</plist>
PLIST3

chmod 644 /Library/LaunchDaemons/com.zasupport.*.plist

launchctl load /Library/LaunchDaemons/com.zasupport.shield.plist 2>/dev/null || true
launchctl load /Library/LaunchDaemons/com.zasupport.updater.plist 2>/dev/null || true
launchctl load /Library/LaunchDaemons/com.zasupport.diagnostic.plist 2>/dev/null || true

echo ""
echo "=== ZA Support installed successfully ==="
echo "Shield Agent, Auto-Updater and Health Check Scout are now running."
POSTEOF

# Substitute placeholders in postinstall
sed -i '' "s|__API_URL__|${API_URL}|g" "$SCRIPTS_DIR/postinstall"
sed -i '' "s|__TOKEN__|${TOKEN}|g" "$SCRIPTS_DIR/postinstall"
sed -i '' "s|__CLIENT_ID__|${CLIENT_ID}|g" "$SCRIPTS_DIR/postinstall"
chmod 755 "$SCRIPTS_DIR/postinstall"

# ── Build .pkg ────────────────────────────────────────────────────────────────
SAFE_NAME=$(echo "$CLIENT_ID" | tr '[:lower:]' '[:upper:]' | sed 's/-/ /g')
OUT_PKG="$OUT_DIR/ZA Support Installer ${CLIENT_ID}.pkg"

pkgbuild \
  --root "$PKG_ROOT" \
  --scripts "$SCRIPTS_DIR" \
  --identifier "com.zasupport.agent" \
  --version "3.5" \
  --install-location "/" \
  "$OUT_PKG"

rm -rf "$BUILD_DIR"

echo ""
echo "✓ Package built: $OUT_PKG"
echo ""
echo "Deliver to client:"
echo "  - Send the .pkg file to the client"
echo "  - Client double-clicks and follows the macOS installer prompts"
echo "  - macOS will prompt for admin password — this is normal"
echo "  - All ZA Support components install automatically"
