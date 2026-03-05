"""
Agent Delivery — serves the Shield Agent installer and auto-update files.

GET /agent/install?client_id=CLIENT_ID&token=AGENT_TOKEN
    Returns a bash installer script with credentials baked in.
    Run: curl -fsSL "https://api.zasupport.com/agent/install?client_id=X&token=Y" | sudo bash

GET /agent/za_shield_agent.sh
    Returns the raw agent script (used by installer and self-updates).

GET /api/v1/agent/version
    Returns current agent SHA-256 hash (update check by deployed agents).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["Agent Delivery"])

AGENT_SCRIPT = Path(__file__).parent.parent.parent / "agent" / "za_shield_agent.sh"
API_URL = "https://api.zasupport.com"


def _agent_hash() -> str:
    return hashlib.sha256(AGENT_SCRIPT.read_bytes()).hexdigest()


def _valid_token() -> str:
    return os.getenv("AGENT_AUTH_TOKEN", "")


@router.get("/agent/install", response_class=PlainTextResponse)
async def get_installer(
    client_id: str = Query(...),
    token: str = Query(...),
):
    """Generate a bash installer for a specific client with credentials baked in."""
    valid = _valid_token()
    if valid and token != valid:
        raise HTTPException(status_code=403, detail="Invalid token")

    script = (
        "#!/bin/bash\n"
        "# ZA Support Shield Agent Installer\n"
        f"# Client: {client_id}\n"
        "set -euo pipefail\n"
        "\n"
        "INSTALL_DIR=/usr/local/za-support-diagnostics\n"
        f'CLIENT_ID="{client_id}"\n'
        f'AUTH_TOKEN="{token}"\n'
        f'API_URL="{API_URL}"\n'
        "\n"
        'echo "=== ZA Support Shield Agent Installer ==="\n'
        'echo "Client: $CLIENT_ID"\n'
        'echo ""\n'
        "\n"
        "if [[ $EUID -ne 0 ]]; then echo 'ERROR: Run with sudo'; exit 1; fi\n"
        "\n"
        "mkdir -p $INSTALL_DIR/agent $INSTALL_DIR/config\n"
        "\n"
        "# Write settings\n"
        'printf "export ZA_AUTH_TOKEN=\'%s\'\\n" "$AUTH_TOKEN" > $INSTALL_DIR/config/settings.conf\n'
        'printf "export ZA_CLIENT_ID=\'%s\'\\n" "$CLIENT_ID" >> $INSTALL_DIR/config/settings.conf\n'
        'printf "export ZA_API_URL=\'%s\'\\n" "$API_URL" >> $INSTALL_DIR/config/settings.conf\n'
        "chmod 600 $INSTALL_DIR/config/settings.conf\n"
        'echo "[OK] settings.conf"\n'
        "\n"
        "# Download agent script from backend\n"
        'curl -fsSL "$API_URL/agent/za_shield_agent.sh" -o $INSTALL_DIR/agent/za_shield_agent.sh\n'
        "chmod 755 $INSTALL_DIR/agent/za_shield_agent.sh\n"
        'echo "[OK] agent script downloaded"\n'
        "\n"
        "# Write self-update script (runs hourly, restarts agent if hash changed)\n"
        "cat > $INSTALL_DIR/update.sh << 'UPDATEEOF'\n"
        "#!/bin/bash\n"
        "source /usr/local/za-support-diagnostics/config/settings.conf 2>/dev/null || exit 0\n"
        "REMOTE=$(curl -sf --max-time 10 \"$ZA_API_URL/api/v1/agent/version\" 2>/dev/null | python3 -c \"import sys,json; print(json.load(sys.stdin).get('hash',''))\" 2>/dev/null)\n"
        "LOCAL=$(shasum -a 256 /usr/local/za-support-diagnostics/agent/za_shield_agent.sh | awk '{print $1}')\n"
        "if [[ -n \"$REMOTE\" && \"$REMOTE\" != \"$LOCAL\" ]]; then\n"
        "  echo \"$(date) update available\" >> /var/log/zasupport-update.log\n"
        "  curl -fsSL --max-time 30 \"$ZA_API_URL/agent/za_shield_agent.sh\" \\\n"
        "    -o /usr/local/za-support-diagnostics/agent/za_shield_agent.sh.tmp && \\\n"
        "  chmod 755 /usr/local/za-support-diagnostics/agent/za_shield_agent.sh.tmp && \\\n"
        "  mv /usr/local/za-support-diagnostics/agent/za_shield_agent.sh.tmp \\\n"
        "     /usr/local/za-support-diagnostics/agent/za_shield_agent.sh\n"
        "  launchctl kickstart -k system/com.zasupport.shield 2>/dev/null\n"
        "  echo \"$(date) updated and restarted\" >> /var/log/zasupport-update.log\n"
        "fi\n"
        "UPDATEEOF\n"
        "chmod 755 $INSTALL_DIR/update.sh\n"
        'echo "[OK] update.sh"\n'
        "\n"
        "# Shield Agent LaunchDaemon\n"
        "cat > /Library/LaunchDaemons/com.zasupport.shield.plist << 'PLISTEOF'\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        "<plist version=\"1.0\"><dict>\n"
        "  <key>Label</key><string>com.zasupport.shield</string>\n"
        "  <key>ProgramArguments</key><array>\n"
        "    <string>/bin/bash</string>\n"
        "    <string>/usr/local/za-support-diagnostics/agent/za_shield_agent.sh</string>\n"
        "  </array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>KeepAlive</key><true/>\n"
        "  <key>StandardOutPath</key><string>/var/log/zasupport-shield.log</string>\n"
        "  <key>StandardErrorPath</key><string>/var/log/zasupport-shield-error.log</string>\n"
        "  <key>EnvironmentVariables</key><dict>\n"
        "    <key>ZA_INSTALL_DIR</key><string>/usr/local/za-support-diagnostics</string>\n"
        "  </dict>\n"
        "</dict></plist>\n"
        "PLISTEOF\n"
        "chmod 644 /Library/LaunchDaemons/com.zasupport.shield.plist\n"
        "\n"
        "# Hourly updater LaunchDaemon\n"
        "cat > /Library/LaunchDaemons/com.zasupport.updater.plist << 'PLISTEOF'\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        "<plist version=\"1.0\"><dict>\n"
        "  <key>Label</key><string>com.zasupport.updater</string>\n"
        "  <key>ProgramArguments</key><array>\n"
        "    <string>/bin/bash</string>\n"
        "    <string>/usr/local/za-support-diagnostics/update.sh</string>\n"
        "  </array>\n"
        "  <key>StartInterval</key><integer>3600</integer>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>StandardOutPath</key><string>/var/log/zasupport-update.log</string>\n"
        "  <key>StandardErrorPath</key><string>/var/log/zasupport-update-error.log</string>\n"
        "</dict></plist>\n"
        "PLISTEOF\n"
        "chmod 644 /Library/LaunchDaemons/com.zasupport.updater.plist\n"
        "\n"
        "# Stop if already running\n"
        "launchctl unload /Library/LaunchDaemons/com.zasupport.shield.plist 2>/dev/null || true\n"
        "launchctl unload /Library/LaunchDaemons/com.zasupport.updater.plist 2>/dev/null || true\n"
        "\n"
        "# Load and start\n"
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.shield.plist\n"
        "launchctl load -w /Library/LaunchDaemons/com.zasupport.updater.plist\n"
        "\n"
        'echo ""\n'
        'echo "=== Install complete ==="\n'
        'echo "Shield Agent running. Logs: /var/log/zasupport-shield.log"\n'
        'echo "Auto-update: hourly check for new agent versions"\n'
        'echo "Verify: sudo launchctl list | grep zasupport"\n'
    )
    return PlainTextResponse(script, media_type="text/plain")


@router.get("/agent/za_shield_agent.sh", response_class=PlainTextResponse)
async def get_agent_script():
    """Serve raw agent script — used by installer and self-update mechanism."""
    return PlainTextResponse(AGENT_SCRIPT.read_text(), media_type="text/plain")


@router.get("/api/v1/agent/version")
async def get_agent_version():
    """Return current agent script hash — deployed agents poll this to check for updates."""
    h = _agent_hash()
    return {"hash": h, "version": h[:12]}
