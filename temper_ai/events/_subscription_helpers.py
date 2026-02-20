"""Helper functions for subscription matching and handler resolution."""

import importlib
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def matches_filter(
    subscription: Any,
    event_type: str,
    payload: Optional[Dict[str, Any]],
    source_workflow_id: Optional[str],
) -> bool:
    """Check if a subscription matches the given event.

    Args:
        subscription: EventSubscription record.
        event_type: The event type being emitted.
        payload: Event payload dict.
        source_workflow_id: Originating workflow ID.

    Returns:
        True if the subscription should receive this event.
    """
    if subscription.event_type != event_type:
        return False

    if subscription.source_workflow_filter and subscription.source_workflow_filter != source_workflow_id:
        return False

    if subscription.payload_filter and payload:
        for key, expected in subscription.payload_filter.items():
            if payload.get(key) != expected:
                return False

    return True


def resolve_handler(handler_ref: str) -> Optional[Callable]:  # type: ignore[type-arg]
    """Import and resolve a dotted-path handler reference.

    Args:
        handler_ref: Dotted path like ``mymodule.submodule.function``.

    Returns:
        Callable if found, None if import fails.
    """
    parts = handler_ref.rsplit(".", maxsplit=1)
    if len(parts) != 2:  # noqa: PLR2004
        logger.warning("Invalid handler_ref format (expected 'module.name'): %s", handler_ref)
        return None

    module_path, attr = parts
    try:
        module = importlib.import_module(module_path)
        return getattr(module, attr)
    except (ImportError, AttributeError) as exc:
        logger.warning("Could not resolve handler_ref %s: %s", handler_ref, exc)
        return None
