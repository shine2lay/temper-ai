"""Thread-safe event bus for real-time observability events."""
import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

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
    data: Dict[str, Any]
    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None
    agent_id: Optional[str] = None


class ObservabilityEventBus:
    """Thread-safe pub/sub for observability events.

    Subscribers are called synchronously in the emitting thread.
    Exceptions from individual subscribers are logged and do not
    prevent other subscribers from receiving the event.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, tuple] = {}  # id -> (callback, event_types_filter)
        self._lock = threading.Lock()

    def subscribe(
        self,
        callback: Callable[[ObservabilityEvent], None],
        event_types: Optional[Set[str]] = None,
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


# Async event bus constants
DEFAULT_ASYNC_QUEUE_SIZE = 1000
DEFAULT_SUBSCRIBER_TIMEOUT_SECONDS = 5


class AsyncObservabilityEventBus:
    """Async pub/sub for observability events.

    Uses an asyncio.Queue for bounded event buffering with a background
    drain loop that delivers events to subscribers.
    """

    def __init__(
        self,
        maxsize: int = DEFAULT_ASYNC_QUEUE_SIZE,
        subscriber_timeout: float = DEFAULT_SUBSCRIBER_TIMEOUT_SECONDS,
    ) -> None:
        self._queue: asyncio.Queue[Optional[ObservabilityEvent]] = asyncio.Queue(
            maxsize=maxsize,
        )
        self._subscriber_timeout = subscriber_timeout
        self._subscribers: Dict[str, tuple] = {}
        self._drain_task: Optional[asyncio.Task[None]] = None
        self._started = False

    def subscribe(
        self,
        callback: Callable[[ObservabilityEvent], Any],
        event_types: Optional[Set[str]] = None,
    ) -> str:
        """Subscribe to events. Returns subscription_id."""
        sub_id = str(uuid.uuid4())
        self._subscribers[sub_id] = (callback, event_types)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""
        self._subscribers.pop(subscription_id, None)

    def emit(self, event: ObservabilityEvent) -> None:
        """Enqueue event (non-blocking). Drops on full with warning."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "Async event bus queue full, dropping event: %s",
                event.event_type,
            )

    async def _drain_loop(self) -> None:
        """Background task: drain queue and deliver to subscribers."""
        while True:
            event = await self._queue.get()
            if event is None:  # Sentinel — stop signal
                self._queue.task_done()
                break
            await self._deliver(event)
            self._queue.task_done()

    async def _deliver(self, event: ObservabilityEvent) -> None:
        """Deliver event to all matching subscribers."""
        for callback, event_types in list(self._subscribers.values()):
            if event_types is not None and event.event_type not in event_types:
                continue
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(
                        result,
                        timeout=self._subscriber_timeout,
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "Async subscriber timed out for event: %s",
                    event.event_type,
                )
            except Exception:  # noqa: BLE001 — subscriber must not crash bus
                logger.warning(
                    "Async event subscriber raised exception",
                    exc_info=True,
                )

    def start(self) -> None:
        """Start the background drain loop."""
        if self._started:
            return
        loop = asyncio.get_running_loop()
        self._drain_task = loop.create_task(self._drain_loop())
        self._started = True

    async def stop(self, drain: bool = True) -> None:
        """Stop the event bus.

        Args:
            drain: If True, process remaining events before stopping.
        """
        if not self._started or self._drain_task is None:
            return
        if drain:
            # Wait for queue to be empty before sending sentinel
            await self._queue.join()
        await self._queue.put(None)  # Sentinel
        await self._drain_task
        self._started = False
        self._drain_task = None
