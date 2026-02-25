"""
Encryption service for sensitive device telemetry.
Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
"""
from cryptography.fernet import Fernet
from app.core.config import settings
import json
import logging

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.ENCRYPTION_KEY
        if not key:
            raise RuntimeError("ENCRYPTION_KEY not set — cannot encrypt/decrypt data.")
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_payload(data: dict) -> str:
    """Encrypt a dict → base64 Fernet token string."""
    f = _get_fernet()
    raw = json.dumps(data, default=str).encode("utf-8")
    return f.encrypt(raw).decode("utf-8")


def decrypt_payload(token: str) -> dict:
    """Decrypt a Fernet token string → dict."""
    f = _get_fernet()
    raw = f.decrypt(token.encode("utf-8"))
    return json.loads(raw)
