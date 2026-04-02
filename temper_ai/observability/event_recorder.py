"""Event recorder — records events to DB and notifies listeners.

The recorder is the single event dispatch point for a workflow run.
It writes to the database and forwards to a notifier (WebSocket, CLI, etc.).

Notifier protocol (duck-typed):
    notify_event(execution_id: str, event_type: str, data: dict) -> None
    cleanup(execution_id: str) -> None
    # Optional:
    notify_stream_chunk(execution_id, agent_id, content, chunk_type, done) -> None
"""

import logging
import uuid
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EventNotifier(Protocol):
    """Interface for event listeners (WebSocket, CLI printer, etc.)."""

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None: ...
    def cleanup(self, execution_id: str) -> None: ...


class NullNotifier:
    """No-op notifier for headless/test runs."""

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None:
        pass

    def cleanup(self, execution_id: str) -> None:
        pass


class EventRecorder:
    """Records events to DB and forwards to a notifier.

    Used by both server mode (notifier=WebSocketManager) and
    CLI mode (notifier=CLIPrinter).
    """

    def __init__(
        self,
        execution_id: str,
        notifier: EventNotifier | None = None,
        persist: bool = True,
    ):
        self._execution_id = execution_id
        self._notifier = notifier or NullNotifier()
        self._persist = persist

    def record(
        self,
        event_type,
        data=None,
        parent_id=None,
        execution_id=None,
        status=None,
        event_id=None,
    ) -> str:
        eid = event_id or str(uuid.uuid4())

        if self._persist:
            from temper_ai.observability.recorder import record as db_record
            eid = db_record(
                event_type,
                data=data,
                parent_id=parent_id,
                execution_id=execution_id or self._execution_id,
                status=status,
                event_id=eid,
            )

        self._notifier.notify_event(
            self._execution_id,
            str(event_type),
            {**(data or {}), "event_id": eid, "status": status},
        )

        return eid

    def update_event(self, event_id, status=None, data=None):
        if self._persist:
            from temper_ai.observability.recorder import update_event
            update_event(event_id, status=status, data=data)

        self._notifier.notify_event(
            self._execution_id,
            "event.updated",
            {"event_id": event_id, "status": status, **(data or {})},
        )

    def broadcast_stream_chunk(
        self,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
    ):
        if hasattr(self._notifier, "notify_stream_chunk"):
            self._notifier.notify_stream_chunk(
                self._execution_id, agent_id, content, chunk_type, done,
            )
