#!/bin/bash
# ============================================================================
# ZA SUPPORT — DIAGNOSTIC ENGINE v3.0 — Modular Core Entry Point
# Bash 3.2 compatible (macOS default shell)
# ============================================================================

# Resolve paths relative to the script's own location — works when sourced
# ($0 is the shell when sourced; BASH_SOURCE[0] is always the script file)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONFIG_DIR="$PROJECT_ROOT/config"
MODULES_DIR="$PROJECT_ROOT/modules"
OUTPUT_DIR="$PROJECT_ROOT/output"

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT
# ─────────────────────────────────────────────────────────────────────────────
[ -f "$CONFIG_DIR/settings.conf" ] && source "$CONFIG_DIR/settings.conf"

# ─────────────────────────────────────────────────────────────────────────────
# BASH 3.2 COMPATIBLE JSON ACCUMULATOR
# Replaces any declare -A associative-array pattern.
# Each section writes a NDJSON line:  {"key":"section_name","value":{...}}
# build_json() reads the temp file and assembles the final JSON object.
# ─────────────────────────────────────────────────────────────────────────────
ZA_JSON_TEMP="/tmp/za_sections_$$.jsonl"

# Clean up temp file on exit
trap 'rm -f "$ZA_JSON_TEMP"' EXIT

# Write a section whose value is a JSON object built from key=value pairs.
# Usage: write_json "section_key" "field1" "val1" "field2" "val2" ...
write_json() {
    local section_key="$1"; shift
    local obj="{"
    local first=1
    while [ $# -ge 2 ]; do
        local k="$1" v="$2"; shift 2
        # Escape double-quotes in value; collapse newlines; truncate to 500 chars
        v="$(printf '%s' "$v" | sed 's/"/\\"/g' | tr '\n' ' ' | cut -c1-500)"
        [ "$first" = "1" ] && first=0 || obj="${obj},"
        obj="${obj}\"${k}\":\"${v}\""
    done
    obj="${obj}}"
    printf '{"key":"%s","value":%s}\n' "$section_key" "$obj" >> "$ZA_JSON_TEMP"
}

# Write a section whose value is a simple scalar string.
# Usage: write_json_simple "section_key" "string_value"
write_json_simple() {
    local section_key="$1"
    local val="$(printf '%s' "$2" | sed 's/"/\\"/g' | tr '\n' ' ' | cut -c1-500)"
    printf '{"key":"%s","value":"%s"}\n' "$section_key" "$val" >> "$ZA_JSON_TEMP"
}

# Write a section whose value is a raw pre-formed JSON fragment (array or object).
# Usage: write_json_raw "section_key" '{"foo":1}'
write_json_raw() {
    local section_key="$1"
    local raw_json="$2"
    printf '{"key":"%s","value":%s}\n' "$section_key" "$raw_json" >> "$ZA_JSON_TEMP"
}

# Assemble all accumulated sections into a single JSON object and write to file.
# Usage: build_json "/path/to/output.json"
build_json() {
    local out_file="$1"
    printf '{' > "$out_file"
    local first=1
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # Extract key and value using parameter expansion (no jq required)
        # Line format: {"key":"KEY","value":VALUE}
        local key value
        key="$(printf '%s' "$line" | sed 's/^{"key":"\([^"]*\)".*$/\1/')"
        value="$(printf '%s' "$line" | sed 's/^{"key":"[^"]*","value":\(.*\)}$/\1/')"
        [ "$first" = "1" ] && first=0 || printf ',' >> "$out_file"
        printf '"%s":%s' "$key" "$value" >> "$out_file"
    done < "$ZA_JSON_TEMP"
    printf '}\n' >> "$out_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# CLIENT ID LOOKUP
# Resolves client_id for a given serial number.
# Priority: --client flag (handled before call) → ZA_CLIENT_ID in settings.conf
#           → V11 device registry (live lookup) → auto-SERIAL fallback
# Unknown serials are auto-registered by V11 on the next push.
# Usage: CLIENT_ID=$(lookup_client_id "$SERIAL")
# ─────────────────────────────────────────────────────────────────────────────
lookup_client_id() {
    local serial="$1"

    # 1. Manually assigned in settings.conf
    if [[ -n "${ZA_CLIENT_ID:-}" ]]; then
        echo "$ZA_CLIENT_ID"
        return
    fi

    # 2. Ask V11 backend for the registered client_id
    if [[ -n "${ZA_API_TOKEN:-}" && -n "${ZA_API_URL:-}" ]]; then
        local remote_id
        remote_id=$(curl -s --max-time 5 \
            -H "Authorization: Bearer $ZA_API_TOKEN" \
            "${ZA_API_URL}/api/v1/agent/devices/${serial}" 2>/dev/null \
            | python3 -c "import json,sys; print(json.load(sys.stdin).get('client_id',''))" 2>/dev/null)
        if [[ -n "$remote_id" && "$remote_id" != "null" ]]; then
            echo "$remote_id"
            return
        fi
    fi

    # 3. Fallback — V11 will auto-register this serial on push
    echo "auto-${serial}"
}

# ─────────────────────────────────────────────────────────────────────────────
# RENDER BACKEND INTEGRATION
# ZA_API_URL  = base URL (no trailing slash)
# ZA_API_ENDPOINT = path (default: /api/v1/agent/diagnostics)
# ─────────────────────────────────────────────────────────────────────────────
push_to_render() {
    local json_file="$1"
    local base="${ZA_API_URL:-https://za-health-check-v11.onrender.com}"
    local path="${ZA_API_ENDPOINT:-/api/v1/agent/diagnostics}"
    local endpoint="${base}${path}"

    curl -s -X POST "$endpoint" \
        -H "Authorization: Bearer ${ZA_AUTH_TOKEN:-${ZA_API_TOKEN:-}}" \
        -H "Content-Type: application/json" \
        --data-binary @"$json_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# LOAD MODULES
# Each module may call write_json / write_json_simple / write_json_raw
# ─────────────────────────────────────────────────────────────────────────────
for mod in "$MODULES_DIR"/*.sh; do
    [ -r "$mod" ] && source "$mod"
done

echo "ZA Support Diagnostic Core v3.0 Loaded."
