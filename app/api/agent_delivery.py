"""
Agent Delivery — serves the combined Shield Agent + CyberPulse installer and all script files.

GET /agent/install?client_id=X&token=Y
    Generates a combined bash installer:
    - ZA Shield Agent (real-time monitoring, LaunchDaemon, auto-update)
    - CyberPulse V3 Diagnostic (daily scheduled run → pushes JSON to V11)

GET /agent/za_shield_agent.sh         — Shield Agent script (for self-updates)
GET /agent/v3/bin/<file>              — V3 diagnostic bin scripts
GET /agent/v3/modules/<file>          — V3 diagnostic modules
GET /agent/v3/core/<file>             — V3 diagnostic core
GET /agent/update.sh                  — Auto-updater script (self-updating)
GET /api/v1/agent/version             — Current Shield Agent hash (update check)
GET /api/v1/agent/v3-version          — Combined hash of all V3 scripts (update check)
GET /api/v1/agent/updater-version     — Hash of update.sh itself (self-update check)
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["Agent Delivery"])

AGENT_DIR = Path(__file__).parent.parent.parent / "agent"
SHIELD_SCRIPT = AGENT_DIR / "za_shield_agent.sh"
V3_DIR = AGENT_DIR / "v3"
API_URL = "https://api.zasupport.com"

# All V3 files to download during install — (remote_path, local_dest)
V3_FILES = [
    ("/agent/v3/core/za_diag_v3.sh",                   "core/za_diag_v3.sh"),
    ("/agent/v3/bin/za_diag_full.sh",                   "bin/za_diag_full.sh"),
    ("/agent/v3/bin/za_diag_scheduled.sh",              "bin/za_diag_scheduled.sh"),
    ("/agent/v3/bin/run_diagnostic.sh",                 "bin/run_diagnostic.sh"),
    ("/agent/v3/modules/battery_mod.sh",                "modules/battery_mod.sh"),
    ("/agent/v3/modules/forensic_mod.sh",               "modules/forensic_mod.sh"),
    ("/agent/v3/modules/hardware_mod.sh",               "modules/hardware_mod.sh"),
    ("/agent/v3/modules/malware_scan.sh",               "modules/malware_scan.sh"),
    ("/agent/v3/modules/network_mod.sh",                "modules/network_mod.sh"),
    ("/agent/v3/modules/render_sync.sh",                "modules/render_sync.sh"),
    ("/agent/v3/modules/report_gen.sh",                 "modules/report_gen.sh"),
    ("/agent/v3/modules/security_mod.sh",               "modules/security_mod.sh"),
    ("/agent/v3/modules/storage_mod.sh",                "modules/storage_mod.sh"),
    ("/agent/v3/modules/threat_intel.sh",               "modules/threat_intel.sh"),
    ("/agent/v3/modules/verification_agent.sh",         "modules/verification_agent.sh"),
]


def _shield_hash() -> str:
    return hashlib.sha256(SHIELD_SCRIPT.read_bytes()).hexdigest()


def _v3_hash() -> str:
    """Combined SHA-256 of all V3 scripts — changes whenever any script is updated."""
    h = hashlib.sha256()
    for remote, local in V3_FILES:
        path = V3_DIR / local
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()


UPDATER_SCRIPT = AGENT_DIR / "update.sh"


def _updater_hash() -> str:
    return hashlib.sha256(UPDATER_SCRIPT.read_bytes()).hexdigest()


def _valid_token() -> str:
    return os.getenv("AGENT_AUTH_TOKEN", "")


def _serve_script(path: Path) -> PlainTextResponse:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Script not found")
    return PlainTextResponse(path.read_text(), media_type="text/plain")


# ── Script serving endpoints ──────────────────────────────────────────────────

@router.get("/agent/update.sh", response_class=PlainTextResponse)
async def get_updater():
    return _serve_script(UPDATER_SCRIPT)


@router.get("/agent/za_shield_agent.sh", response_class=PlainTextResponse)
async def get_shield_agent():
    return _serve_script(SHIELD_SCRIPT)


@router.get("/agent/v3/bin/{filename}", response_class=PlainTextResponse)
async def get_v3_bin(filename: str):
    return _serve_script(V3_DIR / "bin" / filename)


@router.get("/agent/v3/modules/{filename}", response_class=PlainTextResponse)
async def get_v3_module(filename: str):
    return _serve_script(V3_DIR / "modules" / filename)


@router.get("/agent/v3/core/{filename}", response_class=PlainTextResponse)
async def get_v3_core(filename: str):
    return _serve_script(V3_DIR / "core" / filename)


@router.get("/api/v1/agent/version")
async def get_agent_version():
    h = _shield_hash()
    return {"hash": h, "version": h[:12]}


@router.get("/api/v1/agent/v3-version")
async def get_v3_version():
    h = _v3_hash()
    return {"hash": h, "version": h[:12]}


@router.get("/api/v1/agent/updater-version")
async def get_updater_version():
    h = _updater_hash()
    return {"hash": h, "version": h[:12]}


# ── Combined installer ────────────────────────────────────────────────────────

@router.get("/agent/install", response_class=PlainTextResponse)
async def get_installer(
    client_id: str = Query(...),
    token: str = Query(...),
):
    """
    Generate combined bash installer for a client.
    Installs: ZA Shield Agent (real-time) + CyberPulse V3 (daily diagnostic push).
    Usage: curl -fsSL "https://api.zasupport.com/agent/install?client_id=X&token=Y" | sudo bash
    """
    valid = _valid_token()
    if valid and token != valid:
        raise HTTPException(status_code=403, detail="Invalid token")

    vt_key = os.getenv("VIRUSTOTAL_API_KEY", "")
    abuseipdb_key = os.getenv("ABUSEIPDB_API_KEY", "")
    hibp_key = os.getenv("HIBP_API_KEY", "")

    # Build V3 download commands
    download_cmds = []
    for remote, local in V3_FILES:
        download_cmds.append(
            f'curl -fsSL --max-time 30 "{API_URL}{remote}" -o "$INSTALL_DIR/{local}"'
        )
    downloads = "\n".join(download_cmds)

    lines = [
        "#!/bin/bash",
        "# ZA Support — Combined Agent Installer",
        f"# Client: {client_id}",
        "# Installs: Shield Agent (real-time) + CyberPulse V3 (daily diagnostic)",
        "set -eo pipefail",
        "",
        f'INSTALL_DIR="/usr/local/za-support-diagnostics"',
        f'CLIENT_ID="{client_id}"',
        f'AUTH_TOKEN="{token}"',
        f'API_URL="{API_URL}"',
        f'VT_API_KEY="{vt_key}"',
        f'ABUSEIPDB_KEY="{abuseipdb_key}"',
        f'HIBP_API_KEY="{hibp_key}"',
        "",
        'echo "=== ZA Support Agent Installer ==="',
        'echo "Client:  $CLIENT_ID"',
        'echo "Installs: Shield Agent + CyberPulse Diagnostic"',
        'echo ""',
        "",
        "if [[ $EUID -ne 0 ]]; then echo 'ERROR: Run with sudo'; exit 1; fi",
        "",
        "# Create directory structure",
        "mkdir -p $INSTALL_DIR/agent $INSTALL_DIR/config $INSTALL_DIR/bin $INSTALL_DIR/modules $INSTALL_DIR/core $INSTALL_DIR/output",
        "",
        "# ── settings.conf (shared by Shield Agent and V3 diagnostic) ──",
        'cat > "$INSTALL_DIR/config/settings.conf" << CONFEOF',
        "# ZA Support — Client Configuration",
        f"# Client: {client_id}",
        f'ZA_API_URL="{API_URL}"',
        'ZA_API_ENDPOINT="/api/v1/agent/diagnostics"',
        f'ZA_AUTH_TOKEN="{token}"',
        f'ZA_API_TOKEN="{token}"',
        f'ZA_CLIENT_ID="{client_id}"',
        f'ZA_VT_API_KEY="{vt_key}"',
        f'ZA_ABUSEIPDB_KEY="{abuseipdb_key}"',
        f'ZA_HIBP_API_KEY="{hibp_key}"',
        "CONFEOF",
        'chmod 600 "$INSTALL_DIR/config/settings.conf"',
        'echo "[OK] settings.conf"',
        "",
        "# ── Download Shield Agent ──",
        f'curl -fsSL "{API_URL}/agent/za_shield_agent.sh" -o "$INSTALL_DIR/agent/za_shield_agent.sh"',
        'chmod 755 "$INSTALL_DIR/agent/za_shield_agent.sh"',
        'echo "[OK] Shield Agent"',
        "",
        "# ── Download CyberPulse V3 diagnostic scripts ──",
        downloads,
        "chmod -R 755 $INSTALL_DIR/bin $INSTALL_DIR/modules $INSTALL_DIR/core",
        'echo "[OK] CyberPulse V3 scripts"',
        "",
        "# ── Download auto-updater (self-updating — Shield Agent + V3 scripts) ──",
        f'curl -fsSL "{API_URL}/agent/update.sh" -o "$INSTALL_DIR/update.sh"',
        'chmod 755 "$INSTALL_DIR/update.sh"',
        'echo "[OK] auto-updater"',
        "",
        "# ── Shield Agent LaunchDaemon (real-time monitoring, KeepAlive) ──",
        "cat > /Library/LaunchDaemons/com.zasupport.shield.plist << 'PLISTEOF'",
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0"><dict>',
        "  <key>Label</key><string>com.zasupport.shield</string>",
        "  <key>ProgramArguments</key><array>",
        "    <string>/bin/bash</string>",
        "    <string>/usr/local/za-support-diagnostics/agent/za_shield_agent.sh</string>",
        "  </array>",
        "  <key>RunAtLoad</key><true/>",
        "  <key>KeepAlive</key><true/>",
        "  <key>StandardOutPath</key><string>/var/log/zasupport-shield.log</string>",
        "  <key>StandardErrorPath</key><string>/var/log/zasupport-shield-error.log</string>",
        "  <key>EnvironmentVariables</key><dict>",
        "    <key>ZA_INSTALL_DIR</key><string>/usr/local/za-support-diagnostics</string>",
        "  </dict>",
        "</dict></plist>",
        "PLISTEOF",
        "chmod 644 /Library/LaunchDaemons/com.zasupport.shield.plist",
        "",
        "# ── CyberPulse Diagnostic LaunchDaemon (runs once daily, every 4h check) ──",
        "cat > /Library/LaunchDaemons/com.zasupport.diagnostic.plist << 'PLISTEOF'",
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0"><dict>',
        "  <key>Label</key><string>com.zasupport.diagnostic</string>",
        "  <key>ProgramArguments</key><array>",
        "    <string>/bin/bash</string>",
        "    <string>/usr/local/za-support-diagnostics/bin/za_diag_scheduled.sh</string>",
        "  </array>",
        "  <key>RunAtLoad</key><true/>",
        "  <key>StartInterval</key><integer>14400</integer>",
        "  <key>StandardOutPath</key><string>/var/log/zasupport-diagnostic.log</string>",
        "  <key>StandardErrorPath</key><string>/var/log/zasupport-diagnostic.log</string>",
        "  <key>EnvironmentVariables</key><dict>",
        "    <key>ZA_INSTALL_DIR</key><string>/usr/local/za-support-diagnostics</string>",
        "    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>",
        "  </dict>",
        "</dict></plist>",
        "PLISTEOF",
        "chmod 644 /Library/LaunchDaemons/com.zasupport.diagnostic.plist",
        "",
        "# ── Hourly updater LaunchDaemon ──",
        "cat > /Library/LaunchDaemons/com.zasupport.updater.plist << 'PLISTEOF'",
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0"><dict>',
        "  <key>Label</key><string>com.zasupport.updater</string>",
        "  <key>ProgramArguments</key><array>",
        "    <string>/bin/bash</string>",
        "    <string>/usr/local/za-support-diagnostics/update.sh</string>",
        "  </array>",
        "  <key>StartInterval</key><integer>3600</integer>",
        "  <key>RunAtLoad</key><true/>",
        "  <key>StandardOutPath</key><string>/var/log/zasupport-update.log</string>",
        "  <key>StandardErrorPath</key><string>/var/log/zasupport-update-error.log</string>",
        "</dict></plist>",
        "PLISTEOF",
        "chmod 644 /Library/LaunchDaemons/com.zasupport.updater.plist",
        "",
        "# ── Create log files ──",
        "touch /var/log/zasupport-shield.log /var/log/zasupport-diagnostic.log /var/log/zasupport-update.log",
        "chmod 666 /var/log/zasupport-shield.log /var/log/zasupport-diagnostic.log /var/log/zasupport-update.log",
        "",
        "# ── Stop existing (safe — suppress errors if not running) ──",
        "launchctl unload /Library/LaunchDaemons/com.zasupport.shield.plist 2>/dev/null || true",
        "launchctl unload /Library/LaunchDaemons/com.zasupport.diagnostic.plist 2>/dev/null || true",
        "launchctl unload /Library/LaunchDaemons/com.zasupport.updater.plist 2>/dev/null || true",
        "sleep 1",
        "",
        "# ── Load and start all three daemons ──",
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.shield.plist",
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.diagnostic.plist",
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.updater.plist",
        "",
        'echo ""',
        'echo "=== ZA Support Installation Complete ==="',
        'echo ""',
        'echo "  Shield Agent:      RUNNING — real-time security monitoring"',
        'echo "  CyberPulse Diag:   RUNNING — daily full diagnostic (pushes to V11)"',
        'echo "  Auto-Updater:      RUNNING — hourly version check, self-updates"',
        'echo ""',
        'echo "  Logs:"',
        'echo "    Shield:     /var/log/zasupport-shield.log"',
        'echo "    Diagnostic: /var/log/zasupport-diagnostic.log"',
        'echo "    Updates:    /var/log/zasupport-update.log"',
        'echo ""',
        'echo "  Verify: sudo launchctl list | grep zasupport"',
        'echo ""',
        'echo "  First CyberPulse diagnostic will run now in the background."',
        'echo "  Results will push to api.zasupport.com automatically."',
    ]

    return PlainTextResponse("\n".join(lines), media_type="text/plain")


# ── Repair / re-bootstrap ─────────────────────────────────────────────────────

@router.get("/agent/repair", response_class=PlainTextResponse)
async def get_repair_script(
    client_id: str = Query(...),
    token: str = Query(...),
):
    """
    Generate a one-shot repair script for an already-installed agent.
    Fixes config, refreshes all scripts, reloads daemons, runs a forced
    diagnostic push, and verifies data arrived in the API.
    Usage: curl -fsSL "https://api.zasupport.com/agent/repair?client_id=X&token=Y" -o /tmp/za_repair.sh
           sudo bash /tmp/za_repair.sh
    """
    valid = _valid_token()
    if valid and token != valid:
        raise HTTPException(status_code=403, detail="Invalid token")

    vt_key = os.getenv("VIRUSTOTAL_API_KEY", "")
    abuseipdb_key = os.getenv("ABUSEIPDB_API_KEY", "")
    hibp_key = os.getenv("HIBP_API_KEY", "")

    # V3 download commands (one curl per file, atomic tmp→dest swap)
    v3_downloads = []
    for remote, local in V3_FILES:
        v3_downloads.append(
            f'_fetch "{remote}" "{local}"'
        )
    v3_dl = "\n".join(v3_downloads)

    lines = [
        "#!/bin/bash",
        "# ZA Support — Agent Repair & Verify",
        f"# Client: {client_id}",
        "# Fixes config, refreshes all scripts, runs forced diagnostic, verifies push.",
        "set -eo pipefail",
        "",
        f'INSTALL_DIR="/usr/local/za-support-diagnostics"',
        f'CLIENT_ID="{client_id}"',
        f'AUTH_TOKEN="{token}"',
        f'API_URL="{API_URL}"',
        'BLOG="/var/log/zasupport-bootstrap.log"',
        "",
        'if [[ $EUID -ne 0 ]]; then echo "ERROR: run with sudo"; exit 1; fi',
        "",
        'ts() { date "+%d/%m/%Y %H:%M:%S"; }',
        'log() { echo "$(ts) $*" | tee -a "$BLOG"; }',
        "",
        "# Atomic download helper — tmp file then rename, skips if download fails",
        '_fetch() {',
        '  local remote="$1" local_rel="$2"',
        '  local dest="$INSTALL_DIR/$local_rel"',
        '  local tmp="${dest}.$$.tmp"',
        f'  if curl -fsSL --max-time 60 "$API_URL$remote" -o "$tmp" 2>/dev/null; then',
        '    mv "$tmp" "$dest"',
        '  else',
        '    rm -f "$tmp"',
        '    log "[WARN] Failed to download $local_rel — keeping existing"',
        '  fi',
        '}',
        "",
        'echo ""',
        'echo "╔══════════════════════════════════════════╗"',
        'echo "║   ZA Support — Agent Repair & Verify    ║"',
        f'echo "║   Client: {client_id:<32}║"',
        'echo "╚══════════════════════════════════════════╝"',
        'echo ""',
        "",
        "# ── 1. Write settings.conf ───────────────────────────────────────────────────",
        'log "[1/6] Writing settings.conf..."',
        'mkdir -p "$INSTALL_DIR/config"',
        'cat > "$INSTALL_DIR/config/settings.conf" << CONFEOF',
        "# ZA Support — Client Configuration",
        f"# Client: {client_id}",
        f'ZA_API_URL="{API_URL}"',
        'ZA_API_ENDPOINT="/api/v1/agent/diagnostics"',
        f'ZA_AUTH_TOKEN="{token}"',
        f'ZA_API_TOKEN="{token}"',
        f'ZA_CLIENT_ID="{client_id}"',
        f'ZA_VT_API_KEY="{vt_key}"',
        f'ZA_ABUSEIPDB_KEY="{abuseipdb_key}"',
        f'ZA_HIBP_API_KEY="{hibp_key}"',
        "CONFEOF",
        'chmod 600 "$INSTALL_DIR/config/settings.conf"',
        'log "[OK] settings.conf"',
        "",
        "# ── 2. Refresh all V3 scripts from API ───────────────────────────────────────",
        'log "[2/6] Downloading latest V3 scripts..."',
        'mkdir -p "$INSTALL_DIR/bin" "$INSTALL_DIR/modules" "$INSTALL_DIR/core"',
        v3_dl,
        'chmod -R 755 "$INSTALL_DIR/bin" "$INSTALL_DIR/modules" "$INSTALL_DIR/core"',
        'log "[OK] V3 scripts refreshed"',
        "",
        "# ── 3. Refresh Shield Agent + auto-updater ───────────────────────────────────",
        'log "[3/6] Refreshing Shield Agent and auto-updater..."',
        'mkdir -p "$INSTALL_DIR/agent"',
        f'_fetch "/agent/za_shield_agent.sh" "agent/za_shield_agent.sh"',
        f'curl -fsSL --max-time 30 "{API_URL}/agent/update.sh" -o "$INSTALL_DIR/update.sh" 2>/dev/null || true',
        'chmod 755 "$INSTALL_DIR/agent/za_shield_agent.sh" "$INSTALL_DIR/update.sh" 2>/dev/null',
        '# Store current V3 hash so updater knows baseline',
        f'curl -sf --max-time 10 "{API_URL}/api/v1/agent/v3-version" 2>/dev/null | \\',
        '  python3 -c "import sys,json; print(json.load(sys.stdin).get(\'hash\',\'\'))" > "$INSTALL_DIR/.v3_hash" 2>/dev/null || true',
        'log "[OK] Shield Agent + updater refreshed"',
        "",
        "# ── 4. Reload LaunchDaemon (picks up new scheduler) ──────────────────────────",
        'log "[4/6] Reloading diagnostic daemon..."',
        "launchctl unload /Library/LaunchDaemons/com.zasupport.diagnostic.plist 2>/dev/null || true",
        "launchctl unload /Library/LaunchDaemons/com.zasupport.updater.plist 2>/dev/null || true",
        "sleep 1",
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.diagnostic.plist 2>/dev/null || true",
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.updater.plist 2>/dev/null || true",
        "rm -f /tmp/za_diag_last_run",
        'log "[OK] Daemons reloaded, stamp cleared"',
        "",
        "# ── 5. Forced diagnostic push ────────────────────────────────────────────────",
        'log "[5/6] Running full diagnostic (10-15 min)..."',
        'echo ""',
        'DIAG_START=$(date +%s)',
        'bash "$INSTALL_DIR/bin/za_diag_full.sh" --push 2>&1 | tee -a "$BLOG"',
        'DIAG_END=$(date +%s)',
        'log "[OK] Diagnostic complete in $(( DIAG_END - DIAG_START ))s"',
        "",
        "# ── 6. Verify data in API ────────────────────────────────────────────────────",
        'log "[6/6] Verifying push in API..."',
        "sleep 8",
        'SERIAL=$(system_profiler SPHardwareDataType 2>/dev/null | awk \'/Serial Number/{print $NF}\' || echo "UNKNOWN")',
        f'RESP=$(curl -sf --max-time 15 -H "Authorization: Bearer {token}" \\',
        f'  "{API_URL}/api/v1/diagnostics/devices/$SERIAL" 2>/dev/null || echo "{{}}")',
        'SCAN_DATE=$(python3 -c "',
        'import json,sys',
        "d=json.loads(sys.argv[1])",
        "snap=d.get('latest_snapshot') or {}",
        "print(snap.get('scan_date','NOT_FOUND')[:16])",
        "\" \"$RESP\" 2>/dev/null || echo 'ERROR')",
        'RISK=$(python3 -c "',
        'import json,sys',
        "d=json.loads(sys.argv[1])",
        "snap=d.get('latest_snapshot') or {}",
        "print(snap.get('risk_score','?'))",
        "\" \"$RESP\" 2>/dev/null || echo '?')",
        'echo ""',
        'echo "╔══════════════════════════════════════════╗"',
        'echo "║           REPAIR COMPLETE                ║"',
        'echo "╠══════════════════════════════════════════╣"',
        'printf "║  Device:    %-29s║\\n" "$SERIAL"',
        f'printf "║  Client:    %-29s║\\n" "{client_id}"',
        'printf "║  Last scan: %-29s║\\n" "$SCAN_DATE"',
        'printf "║  Risk score:%-29s║\\n" "$RISK"',
        'echo "╚══════════════════════════════════════════╝"',
        'echo ""',
        'if [[ "$SCAN_DATE" == "NOT_FOUND" || "$SCAN_DATE" == "ERROR" ]]; then',
        '  echo "[FAIL] Data not confirmed in API — check log: $BLOG"',
        '  exit 1',
        'else',
        '  echo "[PASS] Data confirmed in API — all systems operational"',
        'fi',
    ]

    return PlainTextResponse("\n".join(lines), media_type="text/plain")
