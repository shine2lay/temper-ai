"""Thread-safe event bus for real-time observability events."""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ObservabilityEvent:
    """Event emitted by the tracker.

    Carries full data payloads so consumers (e.g. WebSocket clients)
    never need to query the database for event details.
    """

    event_type: str  # workflow_start, stage_start, agent_start, agent_end,
    # llm_call, tool_call, stage_end, workflow_end,
    # agent_output, stage_output, collaboration_event,
    # safety_violation, llm_stream_chunk
    timestamp: datetime
    data: dict[str, Any]
    workflow_id: str | None = None
    stage_id: str | None = None
    agent_id: str | None = None


class ObservabilityEventBus:
    """Thread-safe pub/sub for observability events.

    Subscribers are called synchronously in the emitting thread.
    Exceptions from individual subscribers are logged and do not
    prevent other subscribers from receiving the event.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, tuple] = {}  # id -> (callback, event_types_filter)
        self._lock = threading.Lock()

    def subscribe(
        self,
        callback: Callable[[ObservabilityEvent], None],
        event_types: set[str] | None = None,
    ) -> str:
        """Subscribe to events. Returns subscription_id.

        Args:
            callback: Function called with each matching event.
            event_types: If provided, only events with matching event_type
                are delivered. None means all events.

        Returns:
            Subscription ID that can be passed to unsubscribe().
        """
        sub_id = str(uuid.uuid4())
        with self._lock:
            self._subscribers[sub_id] = (callback, event_types)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""
        with self._lock:
            self._subscribers.pop(subscription_id, None)

    def emit(self, event: ObservabilityEvent) -> None:
        """Emit event to all matching subscribers.

        Subscriber exceptions are caught, logged, and do not propagate.
        """
        with self._lock:
            subscribers = list(self._subscribers.values())

        for callback, event_types in subscribers:
            if event_types is not None and event.event_type not in event_types:
                continue
            try:
                callback(event)
            except Exception:
                logger.warning("Event subscriber raised exception", exc_info=True)
