#!/bin/bash
# ============================================================
# ZA Support — Render Environment Setup
# Sets all required env vars on the Health Check AI v11 service
# via the Render API.
#
# Usage:
#   export RENDER_API_KEY=rnd_xxxxxxxx
#   export RENDER_SERVICE_ID=srv-xxxxxxxx
#   bash za-render-setup.sh
#
# Get these from:
#   RENDER_API_KEY    → https://dashboard.render.com/u/account/api-keys
#   RENDER_SERVICE_ID → Render dashboard → your service → Settings → Service ID
# ============================================================

set -euo pipefail

RENDER_API_KEY="${RENDER_API_KEY:-}"
RENDER_SERVICE_ID="${RENDER_SERVICE_ID:-}"

if [[ -z "$RENDER_API_KEY" || -z "$RENDER_SERVICE_ID" ]]; then
    echo "ERROR: Set RENDER_API_KEY and RENDER_SERVICE_ID before running."
    echo "  export RENDER_API_KEY=rnd_xxxx"
    echo "  export RENDER_SERVICE_ID=srv-xxxx"
    exit 1
fi

green() { echo -e "\033[32m✓ $1\033[0m"; }
yellow() { echo -e "\033[33m⚠ $1\033[0m"; }
red() { echo -e "\033[31m✗ $1\033[0m"; }

API="https://api.render.com/v1"

# ── Prompt for secrets ────────────────────────────────────────────────────────
echo "=== ZA Support — Render Environment Setup ==="
echo ""
echo "Enter values for each environment variable."
echo "Press ENTER to skip (leave unchanged on Render)."
echo ""

prompt() {
    local var="$1"; local desc="$2"; local current="$3"
    read -rsp "  ${var} [${desc}]${current:+ (current: ${current})}: " val
    echo ""
    echo "$val"
}

read -rp "DATABASE_URL (PostgreSQL connection string): " DATABASE_URL
read -rp "REDIS_URL (Redis connection string): " REDIS_URL
read -rsp "AGENT_AUTH_TOKEN (primary bearer token): " AGENT_AUTH_TOKEN; echo ""
read -rsp "AGENT_AUTH_TOKEN_OLD (rotation fallback, blank=disabled): " AGENT_AUTH_TOKEN_OLD; echo ""
read -rsp "FORMBRICKS_WEBHOOK_SECRET (from Formbricks → Webhooks → secret): " FORMBRICKS_WEBHOOK_SECRET; echo ""
read -rsp "VIRUSTOTAL_API_KEY: " VIRUSTOTAL_API_KEY; echo ""
read -rsp "ABUSEIPDB_API_KEY: " ABUSEIPDB_API_KEY; echo ""
read -rsp "HIBP_API_KEY: " HIBP_API_KEY; echo ""
read -rp "SMTP_HOST (e.g. smtp.gmail.com): " SMTP_HOST
read -rp "SMTP_PORT (e.g. 587): " SMTP_PORT
read -rp "SMTP_USER (e.g. admin@zasupport.com): " SMTP_USER
read -rsp "SMTP_PASSWORD: " SMTP_PASSWORD; echo ""
read -rp "NOTIFICATION_EMAIL_TO (e.g. courtney@zasupport.com): " NOTIFICATION_EMAIL_TO
read -rp "SLACK_WEBHOOK_URL (optional): " SLACK_WEBHOOK_URL

# ── Build env vars array (skip empty values) ──────────────────────────────────
declare -a ENV_VARS

add_var() {
    local key="$1"; local val="$2"
    [[ -z "$val" ]] && return
    ENV_VARS+=("{\"key\":\"${key}\",\"value\":$(echo "$val" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))')}")
}

add_var "DATABASE_URL"              "$DATABASE_URL"
add_var "REDIS_URL"                 "$REDIS_URL"
add_var "AGENT_AUTH_TOKEN"          "$AGENT_AUTH_TOKEN"
add_var "AGENT_AUTH_TOKEN_OLD"      "$AGENT_AUTH_TOKEN_OLD"
add_var "FORMBRICKS_WEBHOOK_SECRET" "$FORMBRICKS_WEBHOOK_SECRET"
add_var "VIRUSTOTAL_API_KEY"        "$VIRUSTOTAL_API_KEY"
add_var "ABUSEIPDB_API_KEY"         "$ABUSEIPDB_API_KEY"
add_var "HIBP_API_KEY"              "$HIBP_API_KEY"
add_var "SMTP_HOST"                 "$SMTP_HOST"
add_var "SMTP_PORT"                 "$SMTP_PORT"
add_var "SMTP_USER"                 "$SMTP_USER"
add_var "SMTP_PASSWORD"             "$SMTP_PASSWORD"
add_var "NOTIFICATION_EMAIL_TO"     "$NOTIFICATION_EMAIL_TO"
add_var "SLACK_WEBHOOK_URL"         "$SLACK_WEBHOOK_URL"

# Static / non-secret vars
add_var "ISP_MONITOR_STATUS_PAGE_CHECK_INTERVAL" "300"
add_var "ISP_MONITOR_AGENT_HEARTBEAT_TIMEOUT"    "180"
add_var "ISP_MONITOR_OUTAGE_CONFIRMATION_THRESHOLD" "3"
add_var "ISP_MONITOR_OUTAGE_DEGRADED_THRESHOLD"  "10.0"
add_var "ISP_MONITOR_ALERT_COOLDOWN_MINS"         "30"
add_var "NETWORKING_INTEGRATIONS_ENABLED"         "false"

if [[ ${#ENV_VARS[@]} -eq 0 ]]; then
    yellow "No variables entered — nothing to update."
    exit 0
fi

BODY="[$(IFS=','; echo "${ENV_VARS[*]}")]"

echo ""
echo "Pushing ${#ENV_VARS[@]} environment variable(s) to Render..."

STATUS=$(curl -s -o /tmp/render_resp.json -w "%{http_code}" \
    -X PUT \
    -H "Authorization: Bearer ${RENDER_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$BODY" \
    "${API}/services/${RENDER_SERVICE_ID}/env-vars")

if [[ "$STATUS" == "200" ]]; then
    green "Environment variables updated on Render."
    echo ""
    echo "Render will auto-deploy the service with the new vars."
    echo "Monitor: https://dashboard.render.com/web/${RENDER_SERVICE_ID}/deploys"
else
    red "Render API returned HTTP ${STATUS}"
    cat /tmp/render_resp.json
    exit 1
fi

rm -f /tmp/render_resp.json
