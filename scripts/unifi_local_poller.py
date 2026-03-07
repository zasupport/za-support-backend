#!/usr/bin/env python3
"""
ZA Support — UniFi Local Poller
Runs on any machine on the client's local network.
Connects directly to the UniFi controller, collects real-time data,
and POSTs it to the ZA Support backend API.

Usage:
    python3 unifi_local_poller.py

Setup (one-time):
    Edit the CONFIG section below with the client's details.
    Then add to cron: */5 * * * * /usr/bin/python3 /path/to/unifi_local_poller.py

Or run continuously with --loop:
    python3 unifi_local_poller.py --loop

Requirements:
    pip3 install httpx  (only dependency)

Dr Evan Shoul config:
    CONTROLLER_HOST = 192.168.1.252
    CLIENT_ID       = dr-evan-shoul
    CONTROLLER_ID   = dr-evan-shoul
"""

import sys
import time
import logging
import argparse
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip3 install httpx")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# CONFIG — edit these values for each client site
# ─────────────────────────────────────────────────────────────

CONTROLLER_HOST   = "192.168.1.252"   # UniFi Express IP (Dr Evan Shoul gateway)
CONTROLLER_PORT   = 443
CONTROLLER_USER   = "admin"           # UniFi local admin username
CONTROLLER_PASS   = ""                # UniFi local admin password — fill in
SITE_NAME         = "default"         # UniFi site name (usually 'default')

CLIENT_ID         = "dr-evan-shoul"   # ZA Support client_id
CONTROLLER_ID     = "dr-evan-shoul"   # Identifier for this controller

BACKEND_URL       = "https://api.zasupport.com"
API_KEY           = ""                # ZA Support API key — fill in

POLL_INTERVAL_SEC = 300               # 5 minutes (used in --loop mode)

# ─────────────────────────────────────────────────────────────
# END CONFIG
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%d/%m/%Y %H:%M:%S",
)
logger = logging.getLogger("unifi_poller")


def login(client: httpx.Client) -> str | None:
    """Login to UniFi OS controller. Returns CSRF token."""
    resp = client.post(
        f"https://{CONTROLLER_HOST}:{CONTROLLER_PORT}/api/auth/login",
        json={"username": CONTROLLER_USER, "password": CONTROLLER_PASS, "rememberMe": False},
        timeout=10,
    )
    resp.raise_for_status()
    csrf = resp.headers.get("x-updated-csrf-token") or resp.headers.get("x-csrf-token")
    logger.info(f"Logged in to UniFi controller at {CONTROLLER_HOST}")
    return csrf


def get(client: httpx.Client, path: str, csrf: str | None = None) -> dict:
    headers = {}
    if csrf:
        headers["x-csrf-token"] = csrf
    resp = client.get(
        f"https://{CONTROLLER_HOST}:{CONTROLLER_PORT}/proxy/network/api/s/{SITE_NAME}{path}",
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def collect() -> dict:
    """Connect to local UniFi controller and collect all relevant stats."""
    with httpx.Client(verify=False, timeout=10) as client:  # noqa: S501 — self-signed cert
        csrf = login(client)

        health_data  = get(client, "/stat/health",  csrf).get("data", [])
        devices_data = get(client, "/stat/device",  csrf).get("data", [])
        clients_data = get(client, "/stat/sta",     csrf).get("data", [])

    # --- WAN ---
    wan_status    = "unknown"
    wan_ip        = None
    wan_rx_bytes  = None
    wan_tx_bytes  = None
    wan_latency   = None
    uptime_secs   = None

    for h in health_data:
        if h.get("subsystem") == "wan":
            wan_status  = "online" if h.get("status") == "ok" else "offline"
            wan_ip      = h.get("wan_ip")
            wan_latency = h.get("latency")
            uptime_secs = h.get("uptime")

    # Supplement from gateway device
    for d in devices_data:
        if d.get("type") in ("ugw", "udm", "uxg", "usg"):
            uptime_secs = uptime_secs or d.get("uptime")
            uplink = d.get("uplink", {})
            wan_rx_bytes = uplink.get("rx_bytes")
            wan_tx_bytes = uplink.get("tx_bytes")
            break

    # --- Clients ---
    wireless = sum(1 for c in clients_data if not c.get("is_wired", False))
    wired    = sum(1 for c in clients_data if c.get("is_wired", False))

    # --- Devices ---
    devices_online = sum(1 for d in devices_data if d.get("state") == 1)

    device_list = []
    for d in devices_data:
        last_seen = None
        if d.get("last_seen"):
            last_seen = datetime.fromtimestamp(d["last_seen"], tz=timezone.utc).isoformat()
        device_list.append({
            "mac":              d.get("mac", ""),
            "name":             d.get("name") or d.get("model"),
            "model":            d.get("model"),
            "type":             d.get("type"),
            "ip":               d.get("ip"),
            "status":           "online" if d.get("state") == 1 else "offline",
            "uptime_seconds":   d.get("uptime"),
            "firmware_version": d.get("version"),
            "last_seen":        last_seen,
        })

    payload = {
        "client_id":         CLIENT_ID,
        "controller_id":     CONTROLLER_ID,
        "source":            "local",
        "wan_status":        wan_status,
        "wan_ip":            wan_ip,
        "wan_rx_bytes":      wan_rx_bytes,
        "wan_tx_bytes":      wan_tx_bytes,
        "wan_latency_ms":    wan_latency,
        "connected_clients": len(clients_data),
        "wireless_clients":  wireless,
        "wired_clients":     wired,
        "devices_total":     len(devices_data),
        "devices_online":    devices_online,
        "site_name":         SITE_NAME,
        "uptime_seconds":    uptime_secs,
        "devices":           device_list,
        "raw_json": {
            "health":  health_data,
            "devices": [{"mac": d.get("mac"), "name": d.get("name"), "type": d.get("type"), "state": d.get("state")} for d in devices_data],
        },
    }

    logger.info(
        f"Collected: WAN={wan_status} | clients={len(clients_data)} "
        f"(WiFi={wireless}, wired={wired}) | devices={len(devices_data)} online={devices_online}"
    )
    return payload


def push(payload: dict) -> bool:
    """POST snapshot to ZA Support backend."""
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{BACKEND_URL}/api/v1/network/unifi/snapshot",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        logger.info(f"Snapshot pushed to backend: {resp.json()}")
        return True


def run_once() -> bool:
    try:
        payload = collect()
        return push(payload)
    except httpx.RequestError as e:
        logger.error(f"Network error: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    return False


def run_loop():
    logger.info(f"UniFi local poller starting — {CONTROLLER_HOST} → {BACKEND_URL} (every {POLL_INTERVAL_SEC}s)")
    while True:
        run_once()
        logger.info(f"Sleeping {POLL_INTERVAL_SEC}s until next poll...")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZA Support UniFi Local Poller")
    parser.add_argument("--loop", action="store_true", help="Run continuously (otherwise runs once and exits)")
    args = parser.parse_args()

    if not CONTROLLER_PASS:
        print("ERROR: Set CONTROLLER_PASS in the CONFIG section before running.")
        sys.exit(1)
    if not API_KEY:
        print("ERROR: Set API_KEY in the CONFIG section before running.")
        sys.exit(1)

    if args.loop:
        run_loop()
    else:
        success = run_once()
        sys.exit(0 if success else 1)
