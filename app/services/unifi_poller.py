"""
UniFi Network Poller — Network module service
Polls UniFi controllers via:
  - UI.com Site Manager cloud API (works from Render, no VPN needed)
  - Local controller API (requires LAN access — use local poller script for remote sites)

Clients: Dr Evan Shoul (192.168.1.252, UniFi Express 7), Charles Chemel (UniFi Site Manager)
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.modules.vault.encryption import decrypt_value
from app.models.models import UniFiSnapshot, UniFiDeviceState, UniFiControllerConfig

logger = logging.getLogger(__name__)

CLOUD_API_BASE = "https://api.ui.com"
LOCAL_API_TIMEOUT = 10
CLOUD_API_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Cloud API client (UI.com)
# ---------------------------------------------------------------------------

class UniFiCloudClient:
    """
    Polls the UniFi Site Manager API at api.ui.com.
    Requires an API key generated in UI.com account → Settings → API Keys.
    Works from anywhere — no VPN, no local network access required.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get(self, path: str) -> dict:
        with httpx.Client(timeout=CLOUD_API_TIMEOUT, verify=True) as client:
            resp = client.get(f"{CLOUD_API_BASE}{path}", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def get_hosts(self) -> list:
        """List all UniFi consoles registered on this account."""
        data = self._get("/ea/hosts")
        return data.get("data", [])

    def get_sites(self) -> list:
        """List all sites across all consoles."""
        data = self._get("/ea/sites")
        return data.get("data", [])

    def get_devices(self) -> list:
        """List all devices across all sites."""
        data = self._get("/ea/devices")
        return data.get("data", [])

    def build_snapshot_payload(self, controller_id: str, client_id: str, site_name: str = "default") -> dict:
        """
        Build a normalised snapshot payload from cloud API data.
        The cloud API gives device list + status — WAN stats are best-effort.
        """
        try:
            devices = self.get_devices()
            hosts = self.get_hosts()

            devices_total = len(devices)
            devices_online = sum(1 for d in devices if d.get("status", {}).get("state") == "online")

            wan_status = "unknown"
            wan_ip = None
            uptime_seconds = None

            for host in hosts:
                if host.get("id") == controller_id or host.get("reportedState", {}).get("hostname"):
                    rs = host.get("reportedState", {})
                    wan_status = "online" if rs.get("wanStatus") == "WAN_UP" else "offline"
                    uptime_seconds = rs.get("uptime")
                    wan_ip = rs.get("wanIp")
                    break

            device_list = []
            for d in devices:
                state = d.get("status", {})
                device_list.append({
                    "mac":              d.get("mac", ""),
                    "name":             d.get("name") or d.get("model"),
                    "model":            d.get("model"),
                    "type":             d.get("type"),
                    "ip":               d.get("ip"),
                    "status":           "online" if state.get("state") == "online" else "offline",
                    "uptime_seconds":   d.get("uptime"),
                    "firmware_version": d.get("version"),
                    "last_seen":        None,
                })

            return {
                "client_id":       client_id,
                "controller_id":   controller_id,
                "source":          "cloud",
                "wan_status":      wan_status,
                "wan_ip":          wan_ip,
                "uptime_seconds":  uptime_seconds,
                "devices_total":   devices_total,
                "devices_online":  devices_online,
                "site_name":       site_name,
                "devices":         device_list,
                "raw_json":        {"hosts": hosts[:5], "devices": devices[:20]},
            }
        except Exception as e:
            logger.error(f"UniFi cloud API error for {controller_id}: {e}")
            return {
                "client_id":     client_id,
                "controller_id": controller_id,
                "source":        "cloud",
                "wan_status":    "unknown",
            }


# ---------------------------------------------------------------------------
# Local controller client (direct HTTPS to controller on LAN)
# ---------------------------------------------------------------------------

class UniFiLocalClient:
    """
    Polls the UniFi Network Application running on the controller itself.
    Only works when the caller is on the same network (or via VPN).
    For remote sites: use scripts/unifi_local_poller.py which runs on-site.
    """

    def __init__(self, host: str, port: int, username: str, password: str, site: str = "default"):
        self.base = f"https://{host}:{port}"
        self.username = username
        self.password = password
        self.site = site
        self._session_cookies: Optional[dict] = None
        self._csrf_token: Optional[str] = None

    def _login(self, client: httpx.Client):
        resp = client.post(
            f"{self.base}/api/auth/login",
            json={"username": self.username, "password": self.password, "rememberMe": False},
            timeout=LOCAL_API_TIMEOUT,
        )
        resp.raise_for_status()
        self._csrf_token = resp.headers.get("x-updated-csrf-token") or resp.headers.get("x-csrf-token")

    def _get(self, client: httpx.Client, path: str) -> dict:
        headers = {}
        if self._csrf_token:
            headers["x-csrf-token"] = self._csrf_token
        resp = client.get(f"{self.base}/proxy/network/api/s/{self.site}{path}", headers=headers, timeout=LOCAL_API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def collect(self) -> dict:
        """Login, collect health/devices/clients, return normalised payload."""
        with httpx.Client(verify=False, timeout=LOCAL_API_TIMEOUT) as client:  # noqa: S501 — self-signed cert
            self._login(client)

            health_resp = self._get(client, "/stat/health")
            devices_resp = self._get(client, "/stat/device")
            clients_resp = self._get(client, "/stat/sta")

            health = health_resp.get("data", [])
            devices = devices_resp.get("data", [])
            clients = clients_resp.get("data", [])

            # Parse WAN health
            wan_status = "unknown"
            wan_ip = None
            wan_rx_bytes = None
            wan_tx_bytes = None
            wan_latency_ms = None
            uptime_seconds = None

            for h in health:
                if h.get("subsystem") == "wan":
                    wan_status = "online" if h.get("status") == "ok" else "offline"
                    wan_ip = h.get("wan_ip")
                    wan_latency_ms = h.get("latency")
                    uptime_seconds = h.get("uptime")
                elif h.get("subsystem") == "wlan":
                    pass  # future: wifi health details

            # Aggregate throughput from gateway device
            for d in devices:
                if d.get("type") in ("ugw", "udm", "uxg"):
                    uptime_seconds = uptime_seconds or d.get("uptime")
                    uplink = d.get("uplink", {})
                    wan_rx_bytes = uplink.get("rx_bytes")
                    wan_tx_bytes = uplink.get("tx_bytes")
                    break

            wireless = sum(1 for c in clients if not c.get("is_wired", False))
            wired    = sum(1 for c in clients if c.get("is_wired", False))

            devices_online = sum(1 for d in devices if d.get("state") == 1)

            device_list = []
            for d in devices:
                device_list.append({
                    "mac":              d.get("mac", ""),
                    "name":             d.get("name") or d.get("model"),
                    "model":            d.get("model"),
                    "type":             d.get("type"),
                    "ip":               d.get("ip"),
                    "status":           "online" if d.get("state") == 1 else "offline",
                    "uptime_seconds":   d.get("uptime"),
                    "firmware_version": d.get("version"),
                    "last_seen":        datetime.fromtimestamp(d["last_seen"], tz=timezone.utc).isoformat()
                                        if d.get("last_seen") else None,
                })

            return {
                "source":           "local",
                "wan_status":       wan_status,
                "wan_ip":           wan_ip,
                "wan_rx_bytes":     wan_rx_bytes,
                "wan_tx_bytes":     wan_tx_bytes,
                "wan_latency_ms":   wan_latency_ms,
                "connected_clients": len(clients),
                "wireless_clients":  wireless,
                "wired_clients":     wired,
                "devices_total":     len(devices),
                "devices_online":    devices_online,
                "uptime_seconds":    uptime_seconds,
                "devices":           device_list,
                "raw_json":          {
                    "health": health,
                    "devices": [{"mac": d["mac"], "name": d.get("name"), "type": d.get("type"), "state": d.get("state")} for d in devices],
                },
            }


# ---------------------------------------------------------------------------
# Orchestrator — runs the cloud poll for all enabled configs
# ---------------------------------------------------------------------------

def store_snapshot(db: Session, config: UniFiControllerConfig, payload: dict) -> None:
    """Persist a snapshot + upsert device states."""
    snapshot = UniFiSnapshot(
        client_id        = config.client_id,
        controller_id    = config.controller_id if hasattr(config, "controller_id") else payload.get("controller_id", config.client_id),
        source           = payload.get("source", "cloud"),
        wan_status       = payload.get("wan_status"),
        wan_ip           = payload.get("wan_ip"),
        wan_rx_bytes     = payload.get("wan_rx_bytes"),
        wan_tx_bytes     = payload.get("wan_tx_bytes"),
        wan_rx_mbps      = payload.get("wan_rx_mbps"),
        wan_tx_mbps      = payload.get("wan_tx_mbps"),
        wan_latency_ms   = payload.get("wan_latency_ms"),
        connected_clients  = payload.get("connected_clients"),
        wireless_clients   = payload.get("wireless_clients"),
        wired_clients      = payload.get("wired_clients"),
        devices_total      = payload.get("devices_total"),
        devices_online     = payload.get("devices_online"),
        site_name          = payload.get("site_name"),
        uptime_seconds     = payload.get("uptime_seconds"),
        raw_json           = payload.get("raw_json"),
        polled_at          = datetime.now(timezone.utc),
    )
    db.add(snapshot)

    for dev in payload.get("devices", []):
        mac = dev.get("mac")
        if not mac:
            continue
        existing = db.query(UniFiDeviceState).filter_by(
            client_id=config.client_id, mac=mac
        ).first()
        last_seen = None
        if dev.get("last_seen"):
            try:
                last_seen = datetime.fromisoformat(dev["last_seen"].replace("Z", "+00:00"))
            except Exception:
                pass

        if existing:
            existing.name             = dev.get("name") or existing.name
            existing.model            = dev.get("model") or existing.model
            existing.type             = dev.get("type") or existing.type
            existing.ip               = dev.get("ip") or existing.ip
            existing.status           = dev.get("status") or existing.status
            existing.uptime_seconds   = dev.get("uptime_seconds") or existing.uptime_seconds
            existing.firmware_version = dev.get("firmware_version") or existing.firmware_version
            existing.last_seen        = last_seen or existing.last_seen
            existing.updated_at       = datetime.now(timezone.utc)
        else:
            db.add(UniFiDeviceState(
                client_id        = config.client_id,
                controller_id    = config.client_id,
                mac              = mac,
                name             = dev.get("name"),
                model            = dev.get("model"),
                type             = dev.get("type"),
                ip               = dev.get("ip"),
                status           = dev.get("status"),
                uptime_seconds   = dev.get("uptime_seconds"),
                firmware_version = dev.get("firmware_version"),
                last_seen        = last_seen,
            ))

    db.commit()
    logger.info(f"UniFi snapshot stored for {config.client_id} (source={payload.get('source')})")


def run_unifi_cloud_poll(db: Session = None) -> None:
    """
    Scheduled job: poll all enabled UniFi configs via UI.com cloud API.
    Runs every 5 min from automation_scheduler.
    """
    close_db = False
    if db is None:
        db = get_session_factory()()
        close_db = True

    try:
        configs = db.query(UniFiControllerConfig).filter_by(enabled=True).all()
        if not configs:
            logger.debug("UniFi poll: no enabled configs")
            return

        for config in configs:
            if not config.cloud_api_key_enc:
                logger.debug(f"UniFi poll: {config.client_id} has no cloud API key, skipping cloud poll")
                continue
            try:
                api_key = decrypt_value(config.cloud_api_key_enc)
                client = UniFiCloudClient(api_key=api_key)
                payload = client.build_snapshot_payload(
                    controller_id=config.client_id,
                    client_id=config.client_id,
                    site_name=config.site_name,
                )
                store_snapshot(db, config, payload)
            except Exception as e:
                logger.error(f"UniFi cloud poll failed for {config.client_id}: {e}")
    finally:
        if close_db:
            db.close()
