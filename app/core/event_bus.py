"""
ZA Support Health Check AI — Inter-Module Event Bus
Modules communicate via events. NEVER import directly between modules.

Usage:
    from app.core.event_bus import emit_event, subscribe

    # Emit (in service.py):
    await emit_event("diagnostics.upload_received", {"serial": serial, "client_id": client_id})

    # Subscribe (in module __init__.py or tasks.py):
    @subscribe("diagnostics.upload_received")
    async def handle_upload(payload: dict):
        ...

Event naming convention: {module}.{past_tense_action}
Examples:
    diagnostics.upload_received
    diagnostics.anomaly_detected
    shield.critical_event
    isp.outage_confirmed
    vault.credential_accessed
    breach_scanner.breach_detected
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

# Registry: event_name -> list of async handler functions
_handlers: Dict[str, List[Callable]] = {}


def subscribe(event_name: str):
    """Decorator to register an async handler for an event."""
    def decorator(func: Callable):
        if event_name not in _handlers:
            _handlers[event_name] = []
        _handlers[event_name].append(func)
        logger.debug(f"Event bus: registered handler {func.__name__} for '{event_name}'")
        return func
    return decorator


async def emit_event(event_name: str, payload: Any = None) -> None:
    """
    Emit an event. All registered handlers are called concurrently.
    Errors in individual handlers are logged but do not block other handlers.
    """
    handlers = _handlers.get(event_name, [])
    if not handlers:
        logger.debug(f"Event bus: no handlers for '{event_name}'")
        return

    logger.info(f"Event bus: emitting '{event_name}' to {len(handlers)} handler(s)")

    async def safe_call(handler: Callable, event: str, data: Any):
        try:
            await handler(data)
        except Exception as e:
            logger.error(f"Event bus: handler {handler.__name__} failed for '{event}': {e}", exc_info=True)

    await asyncio.gather(*[safe_call(h, event_name, payload) for h in handlers])


def get_registered_events() -> Dict[str, List[str]]:
    """Return all registered events and their handler names (for diagnostics)."""
    return {
        event: [h.__name__ for h in handlers]
        for event, handlers in _handlers.items()
    }
