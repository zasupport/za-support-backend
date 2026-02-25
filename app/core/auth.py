"""
API key authentication dependency.
"""
from fastapi import Header, HTTPException
from app.core.config import settings


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """Verify the X-API-Key header matches the configured key."""
    if not settings.API_KEY:
        raise HTTPException(status_code=500, detail="Server API key not configured.")
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return x_api_key
