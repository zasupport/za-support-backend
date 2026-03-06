#!/bin/bash
# ============================================================================
# ZA Support — Auto-Updater
# Runs hourly via com.zasupport.updater LaunchDaemon.
#
# Update order:
#   0. Config health check — auto-repair settings.conf if empty/broken
#   1. Self  — downloads new update.sh and exec's it if changed
#   2. Shield Agent  — downloads + restarts LaunchDaemon if changed
#   3. V3 scripts    — downloads all 15 diagnostic scripts if any changed
#
# All version checks use hash comparison — no unnecessary downloads.
# ============================================================================

INSTALL_DIR=/usr/local/za-support-diagnostics
LOG=/var/log/zasupport-update.log
BOOTSTRAP_URL_FILE="$INSTALL_DIR/config/.bootstrap_url"

# ── 0. Settings.conf health check ────────────────────────────────────────────
# If settings.conf is empty or missing ZA_AUTH_TOKEN, auto-repair using the
# bootstrap URL written by the installer (chmod 600, root-only).
# This handles settings.conf getting wiped, corrupted, or missed on first install.
if ! grep -q "ZA_AUTH_TOKEN" "$INSTALL_DIR/config/settings.conf" 2>/dev/null; then
  echo "$(date) [BOOT] settings.conf invalid — attempting auto-repair" >> "$LOG"
  if [[ -f "$BOOTSTRAP_URL_FILE" ]]; then
    REPAIR_URL=$(cat "$BOOTSTRAP_URL_FILE" 2>/dev/null)
    if [[ -n "$REPAIR_URL" ]]; then
      TMP_REPAIR="$INSTALL_DIR/.repair.$$.sh"
      if curl -fsSL --max-time 30 "$REPAIR_URL" -o "$TMP_REPAIR" 2>/dev/null; then
        chmod 755 "$TMP_REPAIR"
        bash "$TMP_REPAIR" >> "$LOG" 2>&1 || true
        rm -f "$TMP_REPAIR"
        echo "$(date) [BOOT] Auto-repair complete" >> "$LOG"
      else
        rm -f "$TMP_REPAIR"
        echo "$(date) [BOOT] Auto-repair download failed — will retry next hour" >> "$LOG"
        exit 0
      fi
    fi
  else
    echo "$(date) [BOOT] settings.conf invalid and no .bootstrap_url found — manual repair needed" >> "$LOG"
    exit 0
  fi
fi

source "$INSTALL_DIR/config/settings.conf" 2>/dev/null || exit 0

# ── 1. Self-update ────────────────────────────────────────────────────────────
# Check if this script itself has a new version on the server.
# If so: download → replace → exec new version (continues from top, new logic).
REMOTE_SELF=$(curl -sf --max-time 10 \
  "$ZA_API_URL/api/v1/agent/updater-version" 2>/dev/null | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('hash',''))" 2>/dev/null)
LOCAL_SELF=$(shasum -a 256 "$0" 2>/dev/null | awk '{print $1}')

if [[ -n "$REMOTE_SELF" && "$REMOTE_SELF" != "$LOCAL_SELF" ]]; then
  echo "$(date) [UPDATE] Updater: new version detected — self-updating" >> "$LOG"
  TMP="$0.$$.tmp"
  if curl -fsSL --max-time 30 "$ZA_API_URL/agent/update.sh" -o "$TMP" 2>/dev/null; then
    chmod 755 "$TMP"
    mv "$TMP" "$0"
    echo "$(date) [UPDATE] Updater: self-update complete — re-executing" >> "$LOG"
    exec "$0" "$@"
  else
    rm -f "$TMP"
    echo "$(date) [UPDATE] Updater: self-update download failed — running current version" >> "$LOG"
  fi
fi

# ── 2. Shield Agent update ────────────────────────────────────────────────────
REMOTE_SHIELD=$(curl -sf --max-time 10 \
  "$ZA_API_URL/api/v1/agent/version" 2>/dev/null | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('hash',''))" 2>/dev/null)
LOCAL_SHIELD=$(shasum -a 256 "$INSTALL_DIR/agent/za_shield_agent.sh" 2>/dev/null | awk '{print $1}')

if [[ -n "$REMOTE_SHIELD" && "$REMOTE_SHIELD" != "$LOCAL_SHIELD" ]]; then
  echo "$(date) [UPDATE] Shield Agent: new version — downloading" >> "$LOG"
  TMP="$INSTALL_DIR/agent/za_shield_agent.sh.$$.tmp"
  if curl -fsSL --max-time 30 "$ZA_API_URL/agent/za_shield_agent.sh" -o "$TMP" 2>/dev/null; then
    chmod 755 "$TMP"
    mv "$TMP" "$INSTALL_DIR/agent/za_shield_agent.sh"
    launchctl kickstart -k system/com.zasupport.shield 2>/dev/null
    echo "$(date) [UPDATE] Shield Agent updated" >> "$LOG"
  else
    rm -f "$TMP"
    echo "$(date) [UPDATE] Shield Agent download failed — will retry" >> "$LOG"
  fi
fi

# ── 3. V3 diagnostic scripts update ──────────────────────────────────────────
REMOTE_V3=$(curl -sf --max-time 10 \
  "$ZA_API_URL/api/v1/agent/v3-version" 2>/dev/null | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('hash',''))" 2>/dev/null)
LOCAL_V3_HASH_FILE="$INSTALL_DIR/.v3_hash"
LOCAL_V3=$(cat "$LOCAL_V3_HASH_FILE" 2>/dev/null || echo '')

if [[ -n "$REMOTE_V3" && "$REMOTE_V3" != "$LOCAL_V3" ]]; then
  echo "$(date) [UPDATE] V3 scripts: new version — downloading" >> "$LOG"
  FAILED=0

  _update_file() {
    local url="$ZA_API_URL$1"
    local dest="$INSTALL_DIR/$2"
    local tmp="${dest}.$$.tmp"
    if curl -fsSL --max-time 30 "$url" -o "$tmp" 2>/dev/null; then
      mv "$tmp" "$dest"
    else
      rm -f "$tmp"
      FAILED=$((FAILED + 1))
      echo "$(date) [UPDATE] V3: failed to download $2" >> "$LOG"
    fi
  }

  _update_file /agent/v3/core/za_diag_v3.sh              core/za_diag_v3.sh
  _update_file /agent/v3/bin/za_diag_full.sh              bin/za_diag_full.sh
  _update_file /agent/v3/bin/za_diag_scheduled.sh         bin/za_diag_scheduled.sh
  _update_file /agent/v3/bin/run_diagnostic.sh            bin/run_diagnostic.sh
  _update_file /agent/v3/modules/battery_mod.sh           modules/battery_mod.sh
  _update_file /agent/v3/modules/forensic_mod.sh          modules/forensic_mod.sh
  _update_file /agent/v3/modules/hardware_mod.sh          modules/hardware_mod.sh
  _update_file /agent/v3/modules/malware_scan.sh          modules/malware_scan.sh
  _update_file /agent/v3/modules/network_mod.sh           modules/network_mod.sh
  _update_file /agent/v3/modules/render_sync.sh           modules/render_sync.sh
  _update_file /agent/v3/modules/report_gen.sh            modules/report_gen.sh
  _update_file /agent/v3/modules/security_mod.sh          modules/security_mod.sh
  _update_file /agent/v3/modules/storage_mod.sh           modules/storage_mod.sh
  _update_file /agent/v3/modules/threat_intel.sh          modules/threat_intel.sh
  _update_file /agent/v3/modules/verification_agent.sh    modules/verification_agent.sh

  chmod -R 755 "$INSTALL_DIR/bin" "$INSTALL_DIR/modules" "$INSTALL_DIR/core" 2>/dev/null

  if [[ $FAILED -eq 0 ]]; then
    echo "$REMOTE_V3" > "$LOCAL_V3_HASH_FILE"
    echo "$(date) [UPDATE] V3 scripts updated (all 15 files)" >> "$LOG"
  else
    echo "$(date) [UPDATE] V3 update partial — $FAILED file(s) failed, will retry next hour" >> "$LOG"
  fi
fi
