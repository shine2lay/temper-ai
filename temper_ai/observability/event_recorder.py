"""Event recorder — records events to DB and notifies listeners.

The recorder is the single event dispatch point for a workflow run.
It writes to the database and forwards to a notifier (WebSocket, CLI, etc.).

Notifier protocol (duck-typed):
    notify_event(execution_id: str, event_type: str, data: dict) -> None
    cleanup(execution_id: str) -> None
    # Optional:
    notify_stream_chunk(execution_id, agent_id, content, chunk_type, done) -> None
    notify_script_log(execution_id, row) -> None   # a script agent's saved log row
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

        # parent_id goes out with the event: it is the only thing tying an
        # agent to the stage it runs in, and a completion to the agent it
        # closes (a completion is a new event with its own id). Without it a
        # live view can place neither until it refetches the whole run.
        self._notifier.notify_event(
            self._execution_id,
            str(event_type),
            {
                **(data or {}),
                "event_id": eid,
                "status": status,
                **({"parent_id": parent_id} if parent_id else {}),
            },
        )

        return eid

    def event_status(self, event_id) -> str | None:
        """Current persisted status of one event, or None when not persisting.

        Lets a worker process observe state changes made by another process
        through the database (the API approving a gate, for example).
        """
        if not self._persist:
            return None
        from temper_ai.observability.recorder import get_event
        event = get_event(event_id)
        return event.get("status") if event else None

    def event_data(self, event_id) -> dict | None:
        """Current persisted data of one event, or None when not persisting.

        The companion of :meth:`event_status` for state that carries a
        payload — the human's response to a gate, written by the API.
        """
        if not self._persist:
            return None
        from temper_ai.observability.recorder import get_event
        event = get_event(event_id)
        return dict(event.get("data") or {}) if event else None

    def update_event(self, event_id, status=None, data=None):
        if self._persist:
            from temper_ai.observability.recorder import update_event
            update_event(event_id, status=status, data=data)

        self._notifier.notify_event(
            self._execution_id,
            "event.updated",
            {"event_id": event_id, "status": status, **(data or {})},
        )

    def record_script_log_rows(
        self, attempt_id: str, rows: list[tuple[int, dict]], execution_id: str | None = None,
    ) -> list[str]:
        """Save rows of a script agent's log, ``[(seq, data), ...]``, then send them to whoever
        watches the run.

        Saved first, in one go, and sent only once saved (raising, unsent, when they were not), so
        a live viewer never sees output that a refresh would not show again. Rows go to the
        notifier's ``notify_script_log``, never through ``notify_event``: there can be thousands
        per run, and a run's live event stream is for its structure.
        """
        from temper_ai.observability.script_logs import (
            save_script_log_rows,
            script_log_event_id,
        )

        exec_id = execution_id or self._execution_id
        if self._persist:
            ids = save_script_log_rows(exec_id, attempt_id, rows)
        else:
            ids = [script_log_event_id(attempt_id, seq) for seq, _ in rows]
        notify = getattr(self._notifier, "notify_script_log", None)
        if notify is not None:
            for eid, (seq, data) in zip(ids, rows, strict=True):
                try:
                    notify(self._execution_id, {**data, "id": eid, "attempt_id": attempt_id, "seq": seq})
                except Exception:  # noqa: BLE001 - saved already; a viewer catches up from the database
                    logger.warning("Sending script log row %s failed", eid, exc_info=True)
        return ids

    def record_script_log(self, attempt_id: str, seq: int, data: dict, execution_id: str | None = None) -> str:
        """One row of a script agent's log: see :meth:`record_script_log_rows`."""
        return self.record_script_log_rows(attempt_id, [(seq, data)], execution_id=execution_id)[0]

    def broadcast_stream_chunk(
        self,
        agent_id: str,
        content: str,
        chunk_type: str = "content",
        done: bool = False,
        call_id: str | None = None,
    ):
        if hasattr(self._notifier, "notify_stream_chunk"):
            self._notifier.notify_stream_chunk(
                self._execution_id, agent_id, content, chunk_type, done,
                call_id=call_id,
            )
