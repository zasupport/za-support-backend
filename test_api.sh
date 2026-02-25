#!/bin/bash
# ============================================================
# ZA Support API Test Suite v11.1
# Tests all endpoints including diagnostic upload
# Usage: bash test_api.sh [BASE_URL] [API_KEY]
# ============================================================

BASE_URL="${1:-http://localhost:8080}"
API_KEY="${2:-test-key}"
PASS=0; FAIL=0

green() { echo -e "\033[32m✓ $1\033[0m"; PASS=$((PASS+1)); }
red()   { echo -e "\033[31m✗ $1\033[0m"; FAIL=$((FAIL+1)); }
header(){ echo ""; echo "--- $1 ---"; }

header "1. Root Endpoint"
RESP=$(curl -s "$BASE_URL/")
echo "$RESP" | grep -q '"status":"running"' && green "GET /" || red "GET / → ${RESP}"

header "2. Health Check"
RESP=$(curl -s "$BASE_URL/health")
echo "$RESP" | grep -q '"status"' && green "GET /health" || red "GET /health → ${RESP}"

header "3. Register Device"
RESP=$(curl -s -X POST "$BASE_URL/api/v1/devices/register" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "machine_id": "TEST-UUID-001",
    "hostname": "test-macbook",
    "device_type": "mac_laptop",
    "model_identifier": "MacBookPro18,2",
    "serial_number": "TESTSERIAL01",
    "os_version": "14.3",
    "agent_version": "1.0.0",
    "client_id": "CS001"
  }')
echo "$RESP" | grep -q '"machine_id"' && green "POST /devices/register" || red "POST /devices/register → ${RESP}"

header "4. Submit Health Telemetry"
RESP=$(curl -s -X POST "$BASE_URL/api/v1/devices/health" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "machine_id": "TEST-UUID-001",
    "cpu_percent": 45.2,
    "memory_percent": 72.1,
    "disk_percent": 68.0,
    "battery_percent": 85.0,
    "battery_cycle_count": 347,
    "battery_health": "Normal",
    "threat_score": 2,
    "uptime_hours": 48.5
  }')
echo "$RESP" | grep -q '"success"' && green "POST /devices/health" || red "POST /devices/health → ${RESP}"

header "5. List Devices"
RESP=$(curl -s "$BASE_URL/api/v1/devices/" \
  -H "X-API-Key: ${API_KEY}")
echo "$RESP" | grep -q 'TEST-UUID-001' && green "GET /devices/" || red "GET /devices/ → ${RESP}"

header "6. Device History"
RESP=$(curl -s "$BASE_URL/api/v1/devices/TEST-UUID-001/history?hours=24" \
  -H "X-API-Key: ${API_KEY}")
echo "$RESP" | grep -q '"cpu"' && green "GET /devices/{id}/history" || red "GET /devices/{id}/history → ${RESP}"

header "7. List Alerts"
RESP=$(curl -s "$BASE_URL/api/v1/alerts/?unresolved_only=false&limit=5" \
  -H "X-API-Key: ${API_KEY}")
echo "$RESP" | grep -q '\[' && green "GET /alerts/" || red "GET /alerts/ → ${RESP}"

header "8. Dashboard Overview"
RESP=$(curl -s "$BASE_URL/api/v1/dashboard/overview" \
  -H "X-API-Key: ${API_KEY}")
echo "$RESP" | grep -q '"total_devices"' && green "GET /dashboard/overview" || red "GET /dashboard/overview → ${RESP}"

header "9. Submit Network Telemetry"
RESP=$(curl -s -X POST "$BASE_URL/api/v1/network/submit" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${API_KEY}" \
  -d '{
    "controller_id": "UNIFI-001",
    "total_clients": 12,
    "total_devices": 8,
    "wan_status": "connected",
    "wan_latency_ms": 14.5
  }')
echo "$RESP" | grep -q '"success"' && green "POST /network/submit" || red "POST /network/submit → ${RESP}"

header "10. Auth Rejection (no key)"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/devices/health" \
  -H "Content-Type: application/json" \
  -d '{"machine_id":"x","cpu_percent":0,"memory_percent":0,"disk_percent":0,"threat_score":0}')
[ "$CODE" = "422" ] || [ "$CODE" = "401" ] && green "Auth rejection → ${CODE}" || red "Auth rejection → ${CODE}"

header "11. DIAGNOSTIC UPLOAD (za_diag_v3.sh output)"
RESP=$(curl -s -X POST "$BASE_URL/api/v1/diagnostics/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "3.0",
    "generated": "2026-02-25T10:00:00Z",
    "mode": "full",
    "serial": "TESTSERIAL01",
    "hostname": "test-macbook",
    "client_id": "CS001",
    "hardware": {
      "serial": "TESTSERIAL01",
      "chip_type": "APPLE_SILICON",
      "model": "MacBook Pro",
      "model_id": "MacBookPro18,2",
      "hw_uuid": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
      "ram_gb": 32,
      "ram_upgradeable": "NO (soldered)",
      "cpu": "Apple M1 Pro",
      "cores_physical": 10,
      "cores_logical": 10
    },
    "macos": {"version": "14.3", "build": "23D56", "uptime_seconds": 172800},
    "security": {"sip_enabled": 1, "filevault_on": 1, "firewall_on": 0, "gatekeeper_on": 1, "xprotect_version": "2190", "password_manager": "1Password", "av_edr": "none"},
    "battery": {"health_pct": "89.2", "cycles": "347", "design_capacity_mah": "8693", "max_capacity_mah": "7755", "condition": "Normal"},
    "storage": {"boot_disk_used_pct": 68, "boot_disk_free_gb": 150},
    "oclp": {"detected": false, "version": "N/A", "root_patched": false, "third_party_kexts": 0},
    "diagnostics": {"kernel_panics": 0, "total_processes": 412},
    "recommendations": [
      {"severity": "HIGH", "title": "Firewall is disabled", "evidence": "Any application can accept incoming connections.", "product": "Advanced Security Configuration", "price": "R 1,499"}
    ],
    "recommendation_count": 1,
    "runtime_seconds": 847
  }')
echo "$RESP" | grep -q '"success"' && green "POST /diagnostics/upload" || red "POST /diagnostics/upload → ${RESP}"

header "12. List Diagnostics for Device"
RESP=$(curl -s "$BASE_URL/api/v1/diagnostics/device/TESTSERIAL01" \
  -H "X-API-Key: ${API_KEY}")
echo "$RESP" | grep -q 'TESTSERIAL01' && green "GET /diagnostics/device/{serial}" || red "GET /diagnostics/device/{serial} → ${RESP}"

header "13. List All Diagnostics"
RESP=$(curl -s "$BASE_URL/api/v1/diagnostics/" \
  -H "X-API-Key: ${API_KEY}")
echo "$RESP" | grep -q '\[' && green "GET /diagnostics/" || red "GET /diagnostics/ → ${RESP}"

# ---- Summary ----
echo ""
echo "============================================"
echo -e "Results: \033[32m${PASS} passed\033[0m, \033[31m${FAIL} failed\033[0m"
echo "============================================"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
