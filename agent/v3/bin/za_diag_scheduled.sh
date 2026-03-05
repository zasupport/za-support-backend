#!/bin/bash
set -o pipefail
INSTALL_DIR="${ZA_INSTALL_DIR:-/usr/local/za-support-diagnostics}"
STAMP_FILE="/tmp/za_diag_last_run"
LOG_FILE="/var/log/zasupport-diagnostic.log"
TODAY=$(date '+%Y-%m-%d')

# ── Bundled tool injection ────────────────────────────────────────────────────
# Prepend arch-specific bundled binaries to PATH so scripts use them
# without requiring Homebrew on client Macs.
MACHINE_ARCH="$(uname -m 2>/dev/null || echo unknown)"
BUNDLED_TOOLS="$INSTALL_DIR/tools/$MACHINE_ARCH"
if [[ -d "$BUNDLED_TOOLS" ]]; then
    export PATH="$BUNDLED_TOOLS:$PATH"
fi

if [[ -f "$STAMP_FILE" ]] && [[ "$(cat "$STAMP_FILE" 2>/dev/null)" == "$TODAY" ]]; then
    exit 0
fi

CONSOLE_USER=$(stat -f '%Su' /dev/console 2>/dev/null || echo "")
if [[ -z "$CONSOLE_USER" || "$CONSOLE_USER" == "root" || "$CONSOLE_USER" == "_windowserver" ]]; then
    echo "$(date '+%d/%m/%Y %H:%M:%S SAST') — No console user — will retry later" >> "$LOG_FILE"
    exit 0
fi

CONSOLE_HOME=$(eval echo "~$CONSOLE_USER" 2>/dev/null || echo "/Users/$CONSOLE_USER")

echo "" >> "$LOG_FILE"
echo "$(date '+%d/%m/%Y %H:%M:%S SAST') — Diagnostic starting (root, user: $CONSOLE_USER)" >> "$LOG_FILE"

cd "$INSTALL_DIR" || exit 1

# ── Homebrew fallback (only if bundled tools missing) ────────────────────────
# Bundled tools are preferred. Homebrew is used as fallback only if client
# already has it installed — we never install Homebrew on client Macs.
if [[ ! -d "$BUNDLED_TOOLS" ]]; then
    BREW_BIN=""
    [[ -f /opt/homebrew/bin/brew ]] && BREW_BIN="/opt/homebrew/bin/brew"
    [[ -z "$BREW_BIN" && -f /usr/local/bin/brew ]] && BREW_BIN="/usr/local/bin/brew"
    if [[ -n "$BREW_BIN" ]]; then
        for tool in smartmontools ioping nmap; do
            command -v "$tool" &>/dev/null || echo "$(date '+%d/%m/%Y %H:%M:%S') — [INFO] $tool not available — extended tools at next service visit" >> "$LOG_FILE"
        done
    fi
fi

export SUDO_USER="$CONSOLE_USER"
export CONSOLE_USER CONSOLE_HOME

if timeout 1800 bash bin/za_diag_full.sh --push >> "$LOG_FILE" 2>&1; then
    echo "$TODAY" > "$STAMP_FILE"
    echo "$(date '+%d/%m/%Y %H:%M:%S SAST') — CyberPulse Assessment completed successfully" >> "$LOG_FILE"
else
    EXIT_CODE=$?
    if [[ $EXIT_CODE -eq 124 ]]; then
        echo "$(date '+%d/%m/%Y %H:%M:%S SAST') — TIMED OUT after 1800s — will retry" >> "$LOG_FILE"
    else
        echo "$(date '+%d/%m/%Y %H:%M:%S SAST') — FAILED (exit $EXIT_CODE) — will retry" >> "$LOG_FILE"
    fi
fi
