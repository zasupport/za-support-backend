"""
Health Check v11 — Agent Connectivity Checker
Lightweight module that runs on each client device as part of the
Health Check agent. Reports connectivity status back to the server.

This runs locally on the client's machine (Mac, Windows, etc.)
and sends periodic reports to the Health Check backend.

Add to your existing Health Check agent's main loop:
    from agent_connectivity import ConnectivityChecker
    checker = ConnectivityChecker(api_url, device_id, client_id)
    await checker.check_and_report()  # call every 60 seconds
"""
import asyncio
import platform
import subprocess
import socket
import time
import logging
from typing import Optional, Dict
from dataclasses import dataclass, asdict

logger = logging.getLogger("healthcheck.agent.connectivity")


@dataclass
class ConnectivityResult:
    """Result of a local connectivity check."""
    device_id: int
    client_id: int
    is_online: bool
    wan_ip: Optional[str] = None
    gateway_ip: Optional[str] = None
    gateway_ping_ms: Optional[float] = None
    dns_resolves: Optional[bool] = None
    latency_ms: Optional[float] = None
    packet_loss_pct: Optional[float] = None


class ConnectivityChecker:
    """
    Runs on the client device to check internet connectivity.
    Reports results to the Health Check backend every check interval.
    """

    def __init__(
        self,
        api_url: str,
        device_id: int,
        client_id: int,
        check_interval: int = 60,
    ):
        self.api_url = api_url.rstrip("/")
        self.device_id = device_id
        self.client_id = client_id
        self.check_interval = check_interval

        # Probe targets for connectivity testing
        self.dns_test_hosts = ["google.com", "cloudflare.com", "microsoft.com"]
        self.http_test_urls = [
            "https://www.google.com/generate_204",      # Google connectivity check
            "https://cp.cloudflare.com/",                 # Cloudflare connectivity check
            "http://connectivitycheck.gstatic.com/generate_204",
        ]
        self.ping_targets = ["8.8.8.8", "1.1.1.1"]      # Google DNS, Cloudflare DNS

    async def check_and_report(self) -> ConnectivityResult:
        """
        Run all local connectivity checks and report to backend.
        Call this from the Health Check agent's main loop.
        """
        result = await self._run_checks()

        # Report to backend (fire and forget, don't block agent)
        try:
            await self._send_report(result)
        except Exception as e:
            logger.warning(f"Failed to send connectivity report: {e}")
            # If we can't reach our own backend, we're definitely offline
            # Store locally for retry when connection returns

        return result

    async def _run_checks(self) -> ConnectivityResult:
        """Run all connectivity checks."""
        is_online = False
        gateway_ip = None
        gateway_ping_ms = None
        dns_resolves = None
        latency_ms = None
        packet_loss_pct = None
        wan_ip = None

        # 1. Check gateway (local network)
        gateway_ip = self._get_default_gateway()
        if gateway_ip:
            gateway_ping_ms = await self._ping(gateway_ip)

        # 2. Check DNS resolution
        dns_resolves = self._check_dns()

        # 3. Check internet reachability (ping external)
        ping_results = []
        for target in self.ping_targets:
            ms = await self._ping(target, count=5)
            if ms is not None:
                ping_results.append(ms)

        if ping_results:
            latency_ms = sum(ping_results) / len(ping_results)
            is_online = True

        # 4. Packet loss check
        packet_loss_pct = await self._check_packet_loss()

        # 5. HTTP connectivity check (fallback if ping blocked)
        if not is_online:
            http_ok, http_latency = await self._check_http()
            if http_ok:
                is_online = True
                latency_ms = http_latency

        # 6. Get WAN IP (if online)
        if is_online:
            wan_ip = await self._get_wan_ip()

        return ConnectivityResult(
            device_id=self.device_id,
            client_id=self.client_id,
            is_online=is_online,
            wan_ip=wan_ip,
            gateway_ip=gateway_ip,
            gateway_ping_ms=gateway_ping_ms,
            dns_resolves=dns_resolves,
            latency_ms=round(latency_ms, 2) if latency_ms else None,
            packet_loss_pct=round(packet_loss_pct, 2) if packet_loss_pct is not None else None,
        )

    # ==========================================================
    # Individual checks
    # ==========================================================
    def _get_default_gateway(self) -> Optional[str]:
        """Get the default gateway IP address."""
        try:
            system = platform.system().lower()
            if system == "darwin":  # macOS
                result = subprocess.run(
                    ["route", "-n", "get", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if "gateway:" in line.lower():
                        return line.split(":")[-1].strip()

            elif system == "windows":
                result = subprocess.run(
                    ["ipconfig"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.splitlines():
                    if "default gateway" in line.lower():
                        parts = line.split(":")
                        if len(parts) > 1:
                            gw = parts[-1].strip()
                            if gw:
                                return gw

            elif system == "linux":
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True, timeout=5,
                )
                parts = result.stdout.split()
                if "via" in parts:
                    return parts[parts.index("via") + 1]

        except Exception as e:
            logger.debug(f"Gateway detection failed: {e}")
        return None

    async def _ping(self, host: str, count: int = 3) -> Optional[float]:
        """Ping a host and return average latency in ms, or None if unreachable."""
        try:
            system = platform.system().lower()
            flag = "-c" if system in ("darwin", "linux") else "-n"

            proc = await asyncio.create_subprocess_exec(
                "ping", flag, str(count), "-W", "3", host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            output = stdout.decode()

            # Parse average from "min/avg/max" line
            if "avg" in output or "Average" in output:
                import re
                # macOS/Linux: rtt min/avg/max/mdev = 1.2/2.3/3.4/0.5 ms
                match = re.search(r'[\d.]+/([\d.]+)/[\d.]+', output)
                if match:
                    return float(match.group(1))

                # Windows: Average = 2ms
                match = re.search(r'Average\s*=\s*(\d+)', output)
                if match:
                    return float(match.group(1))

        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Ping to {host} failed: {e}")
        return None

    async def _check_packet_loss(self) -> Optional[float]:
        """Check packet loss percentage to external targets."""
        try:
            system = platform.system().lower()
            flag = "-c" if system in ("darwin", "linux") else "-n"

            proc = await asyncio.create_subprocess_exec(
                "ping", flag, "20", "-W", "2", "8.8.8.8",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode()

            import re
            # "X% packet loss"
            match = re.search(r'([\d.]+)%\s*(?:packet\s*)?loss', output)
            if match:
                return float(match.group(1))

        except Exception as e:
            logger.debug(f"Packet loss check failed: {e}")
        return None

    def _check_dns(self) -> Optional[bool]:
        """Check if DNS resolution works."""
        for host in self.dns_test_hosts:
            try:
                socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM)
                return True
            except socket.gaierror:
                continue
        return False

    async def _check_http(self) -> tuple[bool, Optional[float]]:
        """HTTP connectivity check — works even if ICMP is blocked."""
        try:
            import urllib.request
            for url in self.http_test_urls:
                try:
                    start = time.monotonic()
                    req = urllib.request.Request(url, method="HEAD")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        elapsed = (time.monotonic() - start) * 1000
                        if resp.status < 400:
                            return True, elapsed
                except Exception:
                    continue
        except Exception:
            pass
        return False, None

    async def _get_wan_ip(self) -> Optional[str]:
        """Get external WAN IP address."""
        try:
            import urllib.request
            with urllib.request.urlopen("https://api.ipify.org", timeout=5) as resp:
                return resp.read().decode().strip()
        except Exception:
            return None

    # ==========================================================
    # Report to backend
    # ==========================================================
    async def _send_report(self, result: ConnectivityResult):
        """Send connectivity report to Health Check backend."""
        try:
            import urllib.request
            import json

            data = json.dumps(asdict(result)).encode()
            req = urllib.request.Request(
                f"{self.api_url}/api/v1/isp/agent-report",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 202:
                    logger.debug("Connectivity report sent successfully")
                else:
                    logger.warning(f"Report response: {resp.status}")

        except Exception as e:
            # Can't reach backend — store for later retry
            logger.warning(f"Cannot reach backend to send report: {e}")
            # TODO: Queue locally in SQLite for retry when connection returns


# ==========================================================
# Integration with Health Check agent main loop
# ==========================================================
async def connectivity_check_loop(
    api_url: str,
    device_id: int,
    client_id: int,
    interval: int = 60,
):
    """
    Standalone loop for agent integration.
    Add to your Health Check agent's async task group.

    Example:
        asyncio.create_task(connectivity_check_loop(
            api_url="https://healthcheck.zasupport.com",
            device_id=42,
            client_id=7,
        ))
    """
    checker = ConnectivityChecker(api_url, device_id, client_id, interval)
    logger.info(f"Connectivity checker started (device={device_id}, interval={interval}s)")

    while True:
        try:
            result = await checker.check_and_report()
            status = "ONLINE" if result.is_online else "OFFLINE"
            logger.info(
                f"Connectivity: {status} | "
                f"Latency: {result.latency_ms}ms | "
                f"Loss: {result.packet_loss_pct}% | "
                f"Gateway: {result.gateway_ip}"
            )
        except Exception as e:
            logger.error(f"Connectivity check failed: {e}")

        await asyncio.sleep(interval)
