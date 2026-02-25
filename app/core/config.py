"""
Configuration and environment variable management.
"""
import os
from typing import List


class Settings:
    """Application settings loaded from environment."""

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # --- Security ---
    API_KEY: str = os.getenv("API_KEY", "")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")
    
    # --- Server ---
    PORT: str = os.getenv("PORT", "8080")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # --- CORS ---
    ALLOWED_ORIGINS: List[str] = os.getenv(
        "ALLOWED_ORIGINS", 
        "https://zasupport.com,https://app.zasupport.com,http://localhost:3000"
    ).split(",")
    
    # --- Alerting Thresholds ---
    CPU_CRITICAL: float = float(os.getenv("CPU_CRITICAL", "90"))
    CPU_WARNING: float = float(os.getenv("CPU_WARNING", "75"))
    MEMORY_CRITICAL: float = float(os.getenv("MEMORY_CRITICAL", "90"))
    MEMORY_WARNING: float = float(os.getenv("MEMORY_WARNING", "80"))
    DISK_CRITICAL: float = float(os.getenv("DISK_CRITICAL", "90"))
    DISK_WARNING: float = float(os.getenv("DISK_WARNING", "80"))
    BATTERY_CRITICAL: float = float(os.getenv("BATTERY_CRITICAL", "20"))
    THREAT_CRITICAL: int = int(os.getenv("THREAT_CRITICAL", "7"))
    
    # --- Data Retention ---
    DETAILED_RETENTION_DAYS: int = 90
    AGGREGATED_RETENTION_YEARS: int = 2

    @property
    def database_url_sync(self) -> str:
        """Ensure URL uses postgresql:// not postgres://"""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url


settings = Settings()
