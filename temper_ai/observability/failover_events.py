"""Failover event tracking for LLM provider failover sequences.

Provides structured dataclasses and emit helpers that route through the existing
tracker.track_collaboration_event infrastructure, following the same pattern as
resilience_events.py.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Event type constant
EVENT_TYPE_FAILOVER = "resilience_failover_provider"


@dataclass
class FailoverEventData:
    """Structured data for an LLM provider failover event."""

    from_provider: str
    to_provider: str
    failover_sequence: list[str]
    total_attempts: int
    successful_provider: str | None = None
    stage_name: str | None = None


def emit_failover_event(
    tracker: Any,
    stage_id: str,
    event_data: FailoverEventData,
) -> None:
    """Emit a failover event through the tracker and structured log.

    Args:
        tracker: ExecutionTracker with track_collaboration_event method
        stage_id: Current stage ID for event correlation
        event_data: Structured failover event data
    """
    event_dict = asdict(event_data)

    logger.info(
        "Failover event: from=%s to=%s attempts=%d",
        event_data.from_provider,
        event_data.to_provider,
        event_data.total_attempts,
        extra={"resilience_event": EVENT_TYPE_FAILOVER, **event_dict},
    )

    _emit_via_tracker(tracker, stage_id, EVENT_TYPE_FAILOVER, event_dict)


def _emit_via_tracker(
    tracker: Any,
    stage_id: str,
    event_type: str,
    event_dict: dict[str, Any],
) -> None:
    """Route a failover event through the tracker's collaboration event API."""
    if tracker is None:
        return
    if not hasattr(tracker, "track_collaboration_event"):
        return

    try:
        from temper_ai.observability._tracker_helpers import CollaborationEventData

        tracker.track_collaboration_event(
            CollaborationEventData(
                event_type=event_type,
                stage_id=stage_id,
                event_data=event_dict,
            )
        )
    except Exception:  # noqa: BLE001 — best-effort observability
        logger.debug(
            "Failed to emit %s event via tracker",
            event_type,
            exc_info=True,
        )
