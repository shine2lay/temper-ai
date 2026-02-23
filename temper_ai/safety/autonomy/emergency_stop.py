"""Emergency stop controller for progressive autonomy.

Provides O(1) cross-thread signaling via threading.Event to immediately
halt all autonomous agent operations.
"""

import logging
import threading
import time
import uuid

from temper_ai.safety.autonomy.constants import EMERGENCY_STOP_TIMEOUT_SECONDS
from temper_ai.safety.autonomy.models import EmergencyStopEvent
from temper_ai.safety.autonomy.store import AutonomyStore
from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)

UUID_HEX_LEN = 12

# Module-level event for O(1) cross-thread signaling
_stop_event = threading.Event()
_stop_lock = threading.Lock()
_active_event_id: str | None = None


class EmergencyStopError(Exception):
    """Raised when emergency stop is active."""

    def __init__(self, reason: str = "Emergency stop is active") -> None:
        super().__init__(reason)
        self.reason = reason


class EmergencyStopController:
    """Controller for emergency stop operations.

    Uses a module-level threading.Event for O(1) is_active() checks.
    All state is persisted to AutonomyStore for audit trail.
    """

    def __init__(self, store: AutonomyStore | None = None) -> None:
        self._store = store

    def activate(
        self,
        triggered_by: str,
        reason: str,
        agents_halted: list[str] | None = None,
    ) -> EmergencyStopEvent:
        """Activate emergency stop.

        Args:
            triggered_by: Who triggered the stop (user, system, etc.).
            reason: Why the stop was triggered.
            agents_halted: Optional list of agent names halted.

        Returns:
            EmergencyStopEvent record.
        """
        global _active_event_id  # noqa: PLW0603

        start = time.monotonic()

        with _stop_lock:
            _stop_event.set()
            event_id = f"es-{uuid.uuid4().hex[:UUID_HEX_LEN]}"
            _active_event_id = event_id

        elapsed_ms = (time.monotonic() - start) * 1000  # scanner: skip-magic

        event_record = EmergencyStopEvent(
            id=event_id,
            triggered_by=triggered_by,
            reason=reason,
            agents_halted=agents_halted or [],
            halt_duration_ms=elapsed_ms,
        )

        if self._store is not None:
            self._store.save_emergency_event(event_record)

        logger.warning(
            "EMERGENCY STOP activated by %s: %s (%.1fms)",
            triggered_by,
            reason,
            elapsed_ms,
        )
        return event_record

    def deactivate(self, resolution_reason: str = "resolved") -> None:
        """Deactivate emergency stop.

        Args:
            resolution_reason: Why the stop was resolved.
        """
        global _active_event_id  # noqa: PLW0603

        with _stop_lock:
            _stop_event.clear()
            event_id = _active_event_id
            _active_event_id = None

        # Update the event record with resolution timestamp
        if self._store is not None and event_id is not None:
            event_record = EmergencyStopEvent(
                id=event_id,
                triggered_by="",
                reason=resolution_reason,
                resolved_at=utcnow(),
            )
            self._store.save_emergency_event(event_record)

        logger.info("Emergency stop deactivated: %s", resolution_reason)

    def is_active(self) -> bool:
        """Check if emergency stop is active. O(1) operation."""
        return _stop_event.is_set()

    def check_or_raise(self) -> None:
        """Raise EmergencyStopError if emergency stop is active."""
        if _stop_event.is_set():
            raise EmergencyStopError()

    def get_timeout(self) -> int:
        """Get emergency stop timeout in seconds."""
        return EMERGENCY_STOP_TIMEOUT_SECONDS


def reset_emergency_state() -> None:
    """Reset module-level emergency stop state (for tests only)."""
    global _active_event_id  # noqa: PLW0603
    with _stop_lock:
        _stop_event.clear()
        _active_event_id = None
