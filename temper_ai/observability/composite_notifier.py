"""CompositeNotifier — fan EventRecorder events out to multiple sinks.

EventRecorder takes one notifier; we want both the WS manager AND the
JSONL logger AND (for subprocess workers) the Redis chunk publisher.
This wraps N notifiers as one.

A failing sink doesn't poison the others — each sink's exception is
caught and logged so the worst-case effect of a broken JSONL writer
is loss of the file, not the whole run.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CompositeNotifier:
    """Forwards EventNotifier protocol calls to every wrapped notifier.

    Order matters for nothing observable today, but inserting the WS
    manager first keeps the live UI as snappy as possible (the JSONL
    write happens after the broadcast, not before).
    """

    def __init__(self, *notifiers: Any) -> None:
        # Filter out None so callers can pass optional sinks without
        # ifs at the call site (e.g., notifier_for_ws if needed else None).
        self._notifiers = [n for n in notifiers if n is not None]

    def notify_event(self, execution_id: str, event_type: str, data: dict) -> None:
        for n in self._notifiers:
            try:
                n.notify_event(execution_id, event_type, data)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Notifier %s.notify_event raised (%s); continuing",
                    type(n).__name__, exc,
                )

    def notify_stream_chunk(
        self,
        execution_id: str,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
    ) -> None:
        for n in self._notifiers:
            if not hasattr(n, "notify_stream_chunk"):
                continue
            try:
                n.notify_stream_chunk(
                    execution_id, agent_id, content, chunk_type, done,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Notifier %s.notify_stream_chunk raised (%s); continuing",
                    type(n).__name__, exc,
                )

    def cleanup(self, execution_id: str) -> None:
        for n in self._notifiers:
            try:
                n.cleanup(execution_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Notifier %s.cleanup raised (%s); continuing",
                    type(n).__name__, exc,
                )
