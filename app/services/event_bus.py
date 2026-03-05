"""
Event bus — central event publication for the automation layer.
Every monitor, scheduler, and notification action emits an event.
"""
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import logging

from app.models.models import SystemEvent

logger = logging.getLogger(__name__)

# In-memory subscribers for real-time hooks (notification engine subscribes here)
_subscribers = []


def subscribe(callback):
    """Register a callback that receives every new SystemEvent."""
    _subscribers.append(callback)


def publish(
    db: Session,
    event_type: str,
    source: str,
    summary: str,
    severity: str = "info",
    detail: Optional[dict] = None,
    device_serial: Optional[str] = None,
    client_id: Optional[str] = None,
) -> SystemEvent:
    """Create a system event and notify subscribers."""
    event = SystemEvent(
        event_type=event_type,
        source=source,
        severity=severity,
        summary=summary,
        detail=detail,
        device_serial=device_serial,
        client_id=client_id,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()

    logger.info(f"[EVENT] {source}/{event_type}: {summary}")

    for cb in _subscribers:
        try:
            cb(event, db)
        except Exception as e:
            logger.error(f"Event subscriber error: {e}")

    return event
