"""Helper functions for subscription matching and handler resolution."""

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_HANDLER_REGISTRY: dict[str, Callable] = {}  # type: ignore[type-arg]


def register_handler(name: str, fn: Callable) -> None:  # type: ignore[type-arg]
    """Register a named event handler."""
    _HANDLER_REGISTRY[name] = fn


def matches_filter(
    subscription: Any,
    event_type: str,
    payload: dict[str, Any] | None,
    source_workflow_id: str | None,
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

    if (
        subscription.source_workflow_filter
        and subscription.source_workflow_filter != source_workflow_id
    ):
        return False

    if subscription.payload_filter and payload:
        for key, expected in subscription.payload_filter.items():
            if payload.get(key) != expected:
                return False

    return True


def resolve_handler(handler_ref: str) -> Callable | None:  # type: ignore[type-arg]
    """Look up a registered handler by name.

    Args:
        handler_ref: Name the handler was registered under via register_handler().

    Returns:
        Callable if found, None if not registered.
    """
    handler = _HANDLER_REGISTRY.get(handler_ref)
    if handler is None:
        logger.warning("Unknown handler: %s", handler_ref)
    return handler
