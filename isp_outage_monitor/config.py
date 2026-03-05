"""
Health Check v11 — ISP Outage Monitor Configuration

Updated: Networking Integrations — added API keys and settings
for Cloudflare Radar, IODA, RIPE Atlas, Statuspage, and BGP providers.
"""
from pydantic_settings import BaseSettings
from typing import Optional


class ISPMonitorConfig(BaseSettings):
    """Configuration loaded from environment variables or .env file."""

    # Database (reuses Health Check DB)
    DATABASE_URL: str = "postgresql+asyncpg://healthcheck:password@localhost:5432/healthcheck"

    # Redis (reuses Health Check Redis)
    REDIS_URL: str = "redis://localhost:6379/1"

    # Monitoring intervals (seconds)
    STATUS_PAGE_CHECK_INTERVAL: int = 300       # 5 min — scrape ISP status pages
    DOWNDETECTOR_CHECK_INTERVAL: int = 300      # 5 min — scrape Downdetector
    PING_CHECK_INTERVAL: int = 60               # 1 min — active ping checks
    AGENT_HEARTBEAT_TIMEOUT: int = 180          # 3 min — agent considered offline
    OUTAGE_CONFIRMATION_THRESHOLD: int = 3      # consecutive failures to confirm outage
    OUTAGE_DEGRADED_THRESHOLD: float = 10.0     # packet loss % to flag degraded

    # Scraping
    DOWNDETECTOR_BASE_URL: str = "https://downdetector.co.za/status"
    USER_AGENT: str = "HealthCheck-v11-ISP-Monitor/1.0 (+https://zasupport.com)"
    SCRAPE_TIMEOUT: int = 15                    # seconds
    MAX_RETRIES: int = 2

    # Alerting
    ALERT_WEBHOOK_URL: Optional[str] = None     # Slack/Teams webhook
    ALERT_EMAIL_FROM: str = "alerts@zasupport.com"
    ALERT_COOLDOWN_MINS: int = 30               # don't repeat same alert within window
    WHATSAPP_ENABLED: bool = False               # future: WhatsApp Business API
    WHATSAPP_API_URL: Optional[str] = None

    # Agent connectivity endpoint (Health Check agents POST here)
    AGENT_CONNECTIVITY_ENDPOINT: str = "/api/v1/isp/agent-report"

    # ==================================================================
    # NETWORKING INTEGRATIONS — Provider API Keys & Settings
    # ==================================================================

    # --- Cloudflare Radar ---
    # Free tier available at https://dash.cloudflare.com/profile/api-tokens
    # Permissions needed: Radar:Read
    CLOUDFLARE_RADAR_TOKEN: Optional[str] = None
    CLOUDFLARE_RADAR_CHECK_INTERVAL: int = 600      # 10 min — API rate limits
    CLOUDFLARE_RADAR_ENABLED: bool = True

    # --- IODA / CAIDA ---
    # Free, no auth required
    # Docs: https://api.ioda.inetintel.cc.gatech.edu/v2/
    IODA_ENABLED: bool = True
    IODA_CHECK_INTERVAL: int = 600                   # 10 min
    IODA_COUNTRY_CHECK_ENABLED: bool = True          # also check country.ZA

    # --- RIPE Atlas ---
    # Free tier: 500K credits/day
    # Get key at https://atlas.ripe.net/keys/
    RIPE_ATLAS_API_KEY: Optional[str] = None
    RIPE_ATLAS_ENABLED: bool = True
    RIPE_ATLAS_CHECK_INTERVAL: int = 900             # 15 min — conserve credits
    RIPE_ATLAS_MAX_PROBES_PER_CHECK: int = 5         # limit credit usage

    # --- Statuspage.io API ---
    # No auth required for public pages
    STATUSPAGE_API_ENABLED: bool = True
    STATUSPAGE_CHECK_INTERVAL: int = 300             # 5 min

    # --- BGP / Looking Glass ---
    # Uses RIPE RIS — free, no auth
    BGP_LOOKING_GLASS_ENABLED: bool = True
    BGP_CHECK_INTERVAL: int = 900                    # 15 min

    # --- ISP Webhooks ---
    # Receive inbound status webhooks from ISPs
    WEBHOOK_ENABLED: bool = True
    WEBHOOK_SIGNATURE_HEADER: str = "X-Webhook-Signature"

    # --- Networking Integration Global ---
    NETWORKING_INTEGRATIONS_ENABLED: bool = True      # master switch
    PROVIDER_TIMEOUT: int = 20                        # seconds per provider call

    class Config:
        env_prefix = "ISP_MONITOR_"
        env_file = ".env"
        extra = "ignore"


config = ISPMonitorConfig()
