"""Pipeline phase tracker for pre-execution observability.

Records phase start/end/fail before the real ExecutionTracker exists,
then replays them as events once the tracker scope opens. This fills
the observability gap where config loading, validation, lifecycle
adaptation, and compilation were previously invisible.
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class PipelinePhaseTracker:
    """Lightweight buffer that records pipeline phase timing.

    Captures phase start/end/fail timestamps before the tracker scope
    exists, then replays them as observability events once the tracker
    is available.
    """

    def __init__(self) -> None:
        self._phases: list[dict[str, Any]] = []
        self._current_phase: str | None = None

    def start_phase(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        """Record the start of a pipeline phase."""
        self._current_phase = name
        self._phases.append(
            {
                "name": name,
                "status": "running",
                "started_at": utcnow(),
                "completed_at": None,
                "duration_ms": None,
                "metadata": metadata or {},
                "error": None,
            }
        )

    def end_phase(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        """Record the successful end of a pipeline phase."""
        for phase in reversed(self._phases):
            if phase["name"] == name and phase["status"] == "running":
                now = utcnow()
                phase["status"] = "completed"
                phase["completed_at"] = now
                phase["duration_ms"] = (
                    now - phase["started_at"]
                ).total_seconds() * 1000
                if metadata:
                    phase["metadata"].update(metadata)
                if self._current_phase == name:
                    self._current_phase = None
                return
        logger.warning("end_phase called for unknown/inactive phase: %s", name)

    def fail_phase(self, name: str, error: str) -> None:
        """Record the failure of a specific pipeline phase."""
        for phase in reversed(self._phases):
            if phase["name"] == name and phase["status"] == "running":
                now = utcnow()
                phase["status"] = "failed"
                phase["completed_at"] = now
                phase["duration_ms"] = (
                    now - phase["started_at"]
                ).total_seconds() * 1000
                phase["error"] = error
                if self._current_phase == name:
                    self._current_phase = None
                return
        logger.warning("fail_phase called for unknown/inactive phase: %s", name)

    def fail_current(self, error: str) -> None:
        """Fail whichever phase is currently running (if any)."""
        if self._current_phase is not None:
            self.fail_phase(self._current_phase, error)

    def replay_to_event_bus(
        self,
        event_bus: Any | None,
        workflow_id: str | None,
    ) -> None:
        """Replay buffered phases as observability events.

        Called once the tracker scope is open and the event bus is available.
        """
        if event_bus is None:
            return

        from temper_ai.observability.constants import (
            EVENT_PIPELINE_PHASE_END,
            EVENT_PIPELINE_PHASE_FAIL,
            EVENT_PIPELINE_PHASE_START,
        )
        from temper_ai.observability.event_bus import ObservabilityEvent

        for phase in self._phases:
            # Emit start event
            event_bus.emit(
                ObservabilityEvent(
                    event_type=EVENT_PIPELINE_PHASE_START,
                    timestamp=phase["started_at"],
                    data={
                        "phase": phase["name"],
                        "metadata": phase["metadata"],
                    },
                    workflow_id=workflow_id,
                )
            )

            # Emit end or fail event
            if phase["status"] == "completed":
                event_bus.emit(
                    ObservabilityEvent(
                        event_type=EVENT_PIPELINE_PHASE_END,
                        timestamp=phase["completed_at"],
                        data={
                            "phase": phase["name"],
                            "duration_ms": phase["duration_ms"],
                            "metadata": phase["metadata"],
                        },
                        workflow_id=workflow_id,
                    )
                )
            elif phase["status"] == "failed":
                event_bus.emit(
                    ObservabilityEvent(
                        event_type=EVENT_PIPELINE_PHASE_FAIL,
                        timestamp=phase["completed_at"],
                        data={
                            "phase": phase["name"],
                            "duration_ms": phase["duration_ms"],
                            "error": phase["error"],
                            "metadata": phase["metadata"],
                        },
                        workflow_id=workflow_id,
                    )
                )

    @property
    def phases(self) -> list[dict[str, Any]]:
        """Return phase data for persisting to DB.

        Converts datetime objects to ISO strings for JSON serialization.
        """
        serializable = []
        for phase in self._phases:
            p = dict(phase)
            if p["started_at"] is not None:
                p["started_at"] = p["started_at"].isoformat()
            if p["completed_at"] is not None:
                p["completed_at"] = p["completed_at"].isoformat()
            serializable.append(p)
        return serializable
