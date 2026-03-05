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
GET /api/v1/agent/version             — Current Shield Agent hash (update check)
GET /api/v1/agent/v3-version          — Combined hash of all V3 scripts (update check)
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


def _valid_token() -> str:
    return os.getenv("AGENT_AUTH_TOKEN", "")


def _serve_script(path: Path) -> PlainTextResponse:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Script not found")
    return PlainTextResponse(path.read_text(), media_type="text/plain")


# ── Script serving endpoints ──────────────────────────────────────────────────

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
        "# ── Self-update script (hourly — updates shield agent + V3 scripts when new version deployed) ──",
        "cat > $INSTALL_DIR/update.sh << 'UPDATEEOF'",
        "#!/bin/bash",
        "INSTALL_DIR=/usr/local/za-support-diagnostics",
        "LOG=/var/log/zasupport-update.log",
        "source \"$INSTALL_DIR/config/settings.conf\" 2>/dev/null || exit 0",
        "",
        "# ── Shield Agent update ──",
        "REMOTE_SHIELD=$(curl -sf --max-time 10 \"$ZA_API_URL/api/v1/agent/version\" 2>/dev/null | python3 -c \"import sys,json; print(json.load(sys.stdin).get('hash',''))\" 2>/dev/null)",
        "LOCAL_SHIELD=$(shasum -a 256 \"$INSTALL_DIR/agent/za_shield_agent.sh\" 2>/dev/null | awk '{print $1}')",
        "if [[ -n \"$REMOTE_SHIELD\" && \"$REMOTE_SHIELD\" != \"$LOCAL_SHIELD\" ]]; then",
        "  echo \"$(date) [UPDATE] Shield Agent: new version detected\" >> \"$LOG\"",
        "  curl -fsSL --max-time 30 \"$ZA_API_URL/agent/za_shield_agent.sh\" \\",
        "    -o \"$INSTALL_DIR/agent/za_shield_agent.sh.tmp\" && \\",
        "  chmod 755 \"$INSTALL_DIR/agent/za_shield_agent.sh.tmp\" && \\",
        "  mv \"$INSTALL_DIR/agent/za_shield_agent.sh.tmp\" \"$INSTALL_DIR/agent/za_shield_agent.sh\"",
        "  launchctl kickstart -k system/com.zasupport.shield 2>/dev/null",
        "  echo \"$(date) [UPDATE] Shield Agent updated\" >> \"$LOG\"",
        "fi",
        "",
        "# ── V3 diagnostic scripts update ──",
        "REMOTE_V3=$(curl -sf --max-time 10 \"$ZA_API_URL/api/v1/agent/v3-version\" 2>/dev/null | python3 -c \"import sys,json; print(json.load(sys.stdin).get('hash',''))\" 2>/dev/null)",
        "LOCAL_V3_HASH_FILE=\"$INSTALL_DIR/.v3_hash\"",
        "LOCAL_V3=$(cat \"$LOCAL_V3_HASH_FILE\" 2>/dev/null || echo '')",
        "if [[ -n \"$REMOTE_V3\" && \"$REMOTE_V3\" != \"$LOCAL_V3\" ]]; then",
        "  echo \"$(date) [UPDATE] V3 scripts: new version detected — downloading\" >> \"$LOG\"",
        "  FAILED=0",
        f'  for remote_local in "{API_URL}/agent/v3/core/za_diag_v3.sh:core/za_diag_v3.sh" \\',
        f'    "{API_URL}/agent/v3/bin/za_diag_full.sh:bin/za_diag_full.sh" \\',
        f'    "{API_URL}/agent/v3/bin/za_diag_scheduled.sh:bin/za_diag_scheduled.sh" \\',
        f'    "{API_URL}/agent/v3/bin/run_diagnostic.sh:bin/run_diagnostic.sh" \\',
        f'    "{API_URL}/agent/v3/modules/battery_mod.sh:modules/battery_mod.sh" \\',
        f'    "{API_URL}/agent/v3/modules/forensic_mod.sh:modules/forensic_mod.sh" \\',
        f'    "{API_URL}/agent/v3/modules/hardware_mod.sh:modules/hardware_mod.sh" \\',
        f'    "{API_URL}/agent/v3/modules/malware_scan.sh:modules/malware_scan.sh" \\',
        f'    "{API_URL}/agent/v3/modules/network_mod.sh:modules/network_mod.sh" \\',
        f'    "{API_URL}/agent/v3/modules/render_sync.sh:modules/render_sync.sh" \\',
        f'    "{API_URL}/agent/v3/modules/report_gen.sh:modules/report_gen.sh" \\',
        f'    "{API_URL}/agent/v3/modules/security_mod.sh:modules/security_mod.sh" \\',
        f'    "{API_URL}/agent/v3/modules/storage_mod.sh:modules/storage_mod.sh" \\',
        f'    "{API_URL}/agent/v3/modules/threat_intel.sh:modules/threat_intel.sh" \\',
        f'    "{API_URL}/agent/v3/modules/verification_agent.sh:modules/verification_agent.sh"',
        "  do",
        "    URL=\"${remote_local%%:*}\"",
        "    DEST=\"$INSTALL_DIR/${remote_local##*:}\"",
        "    TMP=\"${DEST}.tmp\"",
        "    curl -fsSL --max-time 30 \"$URL\" -o \"$TMP\" 2>/dev/null && mv \"$TMP\" \"$DEST\" || { FAILED=$((FAILED+1)); rm -f \"$TMP\"; }",
        "  done",
        "  chmod -R 755 \"$INSTALL_DIR/bin\" \"$INSTALL_DIR/modules\" \"$INSTALL_DIR/core\" 2>/dev/null",
        "  if [[ $FAILED -eq 0 ]]; then",
        "    echo \"$REMOTE_V3\" > \"$LOCAL_V3_HASH_FILE\"",
        "    echo \"$(date) [UPDATE] V3 scripts updated successfully\" >> \"$LOG\"",
        "  else",
        "    echo \"$(date) [UPDATE] V3 update partial — $FAILED file(s) failed, will retry\" >> \"$LOG\"",
        "  fi",
        "fi",
        "UPDATEEOF",
        "chmod 755 $INSTALL_DIR/update.sh",
        'echo "[OK] auto-update script (Shield Agent + V3 scripts)"',
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
