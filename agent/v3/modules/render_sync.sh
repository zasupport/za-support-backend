#!/bin/bash
# ============================================================================
# ZA Support — Render Sync Module
# Pushes a JSON file to the Health Check v11 API on za-health-check-v11.onrender.com
# Requires: ZA_API_URL, ZA_API_ENDPOINT, and ZA_AUTH_TOKEN set in config/settings.conf
#
# Deployed endpoint: POST /api/v1/agent/diagnostics  (main_integrated.py)
# Schema: DiagnosticSubmission = { serial, hostname, client_id, payload: {} }
# Auth:   Authorization: Bearer <AGENT_AUTH_TOKEN>
# ============================================================================

push_results() {
    local file="$1"
    local client_id="${2:-}"

    if [ ! -f "$file" ]; then
        echo "[ERROR] push_results: file not found: $file"
        return 1
    fi

    local endpoint="${ZA_API_URL:-https://za-health-check-v11.onrender.com}${ZA_API_ENDPOINT:-/api/v1/agent/diagnostics}"

    if [ -z "${ZA_AUTH_TOKEN:-}" ]; then
        echo "[WARN] ZA_AUTH_TOKEN is not set — push will likely be rejected"
    fi

    # The deployed endpoint expects DiagnosticSubmission:
    #   { "serial": "...", "hostname": "...", "client_id": "...", "payload": { <full json> } }
    # Extract serial/hostname from the JSON file, then wrap.
    local serial hostname envelope_file
    serial=$(python3 -c "
import json, sys
with open('$file') as f:
    d = json.load(f)
print(d.get('hardware', {}).get('serial') or d.get('serial') or 'UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

    hostname=$(python3 -c "
import json
with open('$file') as f:
    d = json.load(f)
print(d.get('metadata', {}).get('hostname') or d.get('hostname') or 'unknown')
" 2>/dev/null || echo "unknown")

    envelope_file="/tmp/za_push_envelope_$$.json"

    # Strip ANSI codes and control characters that break JSON
    if [[ -f "$file" ]]; then
        python3 -c "
import json, re, sys
with open('$file', 'r', errors='replace') as f:
    raw = f.read()
raw = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
raw = re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', '', raw)
try:
    data = json.loads(raw)
    with open('$file', 'w') as f:
        json.dump(data, f)
except:
    pass
" 2>/dev/null
    fi

    python3 - <<PYEOF
import json
with open('$file') as f:
    payload = json.load(f)
envelope = {
    "serial":    "$serial",
    "hostname":  "$hostname",
    "client_id": "$client_id",
    "payload":   payload,
}
with open('$envelope_file', 'w') as f:
    json.dump(envelope, f)
PYEOF

    if [ ! -f "$envelope_file" ]; then
        echo "[ERROR] Failed to build upload envelope"
        return 1
    fi

    local response_body http_code
    response_body=$(curl -s -w "\n__HTTP_CODE__%{http_code}" \
        -X POST "$endpoint" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${ZA_AUTH_TOKEN:-}" \
        --data-binary @"$envelope_file" 2>/dev/null || echo "__HTTP_CODE__000")

    http_code=$(printf '%s' "$response_body" | grep -oE '__HTTP_CODE__[0-9]+' | sed 's/__HTTP_CODE__//')
    response_body=$(printf '%s' "$response_body" | sed 's/__HTTP_CODE__[0-9]*$//')

    rm -f "$envelope_file"

    printf 'Endpoint : %s\n' "$endpoint"
    printf 'HTTP Code: %s\n' "${http_code:-000}"
    printf 'Response : %s\n' "$response_body"

    if [ "${http_code:-000}" = "200" ] || [ "${http_code:-000}" = "201" ]; then
        echo "[OK] Pushed to Render API — HTTP $http_code"
        return 0
    else
        echo "[WARN] Render API push failed — HTTP ${http_code:-000}. JSON saved locally: $file"
        return 1
    fi
}

# Legacy alias
push_to_render() {
    push_results "$1" "${2:-}"
}
