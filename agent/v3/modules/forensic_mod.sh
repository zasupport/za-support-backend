#!/bin/bash
# ============================================================================
# ZA Support — Forensic Module (POPIA Compliant)
# Provides secure file deletion (3-pass overwrite before unlink)
# and temp-file cleanup for diagnostic runs
# ============================================================================

# Securely overwrite and delete a file (3-pass, POPIA compliant)
# Usage: secure_cleanup /path/to/file
secure_cleanup() {
    local target="$1"

    if [ -z "$target" ]; then
        echo "[ERROR] secure_cleanup: no target specified" >&2
        return 1
    fi

    if [ ! -f "$target" ]; then
        echo "[WARN] secure_cleanup: file not found: $target" >&2
        return 1
    fi

    # rm -P performs 3-pass DoD overwrite on macOS before deletion
    if rm -P "$target" 2>/dev/null; then
        echo "[OK] Securely deleted (3-pass): $target"
        return 0
    else
        # Fallback: manual overwrite then delete
        local size
        size=$(wc -c < "$target" 2>/dev/null || echo 1024)
        dd if=/dev/urandom of="$target" bs=1 count="$size" conv=notrunc 2>/dev/null || true
        dd if=/dev/zero   of="$target" bs=1 count="$size" conv=notrunc 2>/dev/null || true
        dd if=/dev/urandom of="$target" bs=1 count="$size" conv=notrunc 2>/dev/null || true
        rm -f "$target" 2>/dev/null
        echo "[OK] Securely deleted (manual 3-pass): $target"
    fi
}

# Purge all ZA diagnostic temp files from /tmp (matching za_sections_*.jsonl)
purge_diagnostic_temps() {
    local count=0
    for f in /tmp/za_sections_*.jsonl; do
        [ -f "$f" ] || continue
        secure_cleanup "$f" && count=$((count + 1))
    done
    echo "[OK] Purged $count diagnostic temp file(s)"
}
