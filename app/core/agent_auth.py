"""
Bearer token authentication for Mac agent endpoints.
Validates Authorization: Bearer <AGENT_AUTH_TOKEN> header.
"""
from fastapi import Header, HTTPException
from app.core.config import settings


async def verify_agent_token(authorization: str = Header(...)):
    """Verify Bearer token matches AGENT_AUTH_TOKEN. Supports dual-token rotation."""
    if not settings.AGENT_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="AGENT_AUTH_TOKEN not configured.")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header. Use: Bearer <token>")
    token = authorization[7:]
    if token == settings.AGENT_AUTH_TOKEN:
        return token
    # During rotation: accept old token if configured
    if settings.AGENT_AUTH_TOKEN_OLD and token == settings.AGENT_AUTH_TOKEN_OLD:
        return token
    raise HTTPException(status_code=401, detail="Invalid agent token.")
