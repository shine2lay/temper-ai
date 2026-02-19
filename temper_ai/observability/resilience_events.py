"""Resilience event tracking for retries, fallbacks, and circuit breaker transitions.

Provides structured dataclasses and emit helpers that route through the existing
tracker.track_collaboration_event infrastructure using resilience_* event types.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Event type constants for resilience events
EVENT_TYPE_RETRY = "resilience_retry"
EVENT_TYPE_FALLBACK = "resilience_fallback"
EVENT_TYPE_CIRCUIT_BREAKER = "resilience_circuit_breaker"

# Retry outcome constants
RETRY_OUTCOME_SUCCESS = "success"
RETRY_OUTCOME_FAILED = "failed"
RETRY_OUTCOME_EXHAUSTED = "exhausted"


@dataclass
class RetryEventData:
    """Structured data for an agent retry event."""

    attempt_number: int
    max_retries: int
    agent_name: str
    stage_name: str
    outcome: str  # success / failed / exhausted
    error_type: Optional[str] = None
    is_transient: Optional[bool] = None
    backoff_delay_seconds: Optional[float] = None


@dataclass
class FallbackEventData:
    """Structured data for an adaptive mode fallback event."""

    from_mode: str
    to_mode: str
    reason: str
    stage_name: str
    disagreement_rate: Optional[float] = None
    threshold: Optional[float] = None
    agents: Optional[List[str]] = None
    error_message: Optional[str] = None


@dataclass
class CircuitBreakerEventData:
    """Structured data for a circuit breaker state transition."""

    breaker_name: str
    old_state: str
    new_state: str
    failure_count: int = 0
    success_count: int = 0


def emit_retry_event(
    tracker: Any,
    stage_id: str,
    event_data: RetryEventData,
) -> None:
    """Emit a retry event through the tracker and structured log.

    Args:
        tracker: ExecutionTracker with track_collaboration_event method
        stage_id: Current stage ID for event correlation
        event_data: Structured retry event data
    """
    event_dict = asdict(event_data)

    logger.info(
        "Retry event: agent=%s stage=%s attempt=%d/%d outcome=%s",
        event_data.agent_name,
        event_data.stage_name,
        event_data.attempt_number,
        event_data.max_retries,
        event_data.outcome,
        extra={"resilience_event": EVENT_TYPE_RETRY, **event_dict},
    )

    _emit_via_tracker(tracker, stage_id, EVENT_TYPE_RETRY, event_dict)


def emit_fallback_event(
    tracker: Any,
    stage_id: str,
    event_data: FallbackEventData,
) -> None:
    """Emit a fallback event through the tracker and structured log.

    Args:
        tracker: ExecutionTracker with track_collaboration_event method
        stage_id: Current stage ID for event correlation
        event_data: Structured fallback event data
    """
    event_dict = asdict(event_data)

    logger.info(
        "Fallback event: stage=%s from=%s to=%s reason=%s",
        event_data.stage_name,
        event_data.from_mode,
        event_data.to_mode,
        event_data.reason,
        extra={"resilience_event": EVENT_TYPE_FALLBACK, **event_dict},
    )

    _emit_via_tracker(tracker, stage_id, EVENT_TYPE_FALLBACK, event_dict)


def emit_circuit_breaker_event(
    callback: Optional[Callable[[CircuitBreakerEventData], None]],
    event_data: CircuitBreakerEventData,
) -> None:
    """Emit a circuit breaker state transition event.

    Logs the event and fires the opt-in observability callback if provided.

    Args:
        callback: Optional callback to fire with the event data
        event_data: Structured circuit breaker event data
    """
    logger.info(
        "Circuit breaker event: breaker=%s %s -> %s failures=%d",
        event_data.breaker_name,
        event_data.old_state,
        event_data.new_state,
        event_data.failure_count,
        extra={
            "resilience_event": EVENT_TYPE_CIRCUIT_BREAKER,
            **asdict(event_data),
        },
    )

    if callback is not None:
        try:
            callback(event_data)
        except Exception:  # noqa: BLE001 — best-effort observability
            logger.debug(
                "Circuit breaker observability callback failed for %s",
                event_data.breaker_name,
                exc_info=True,
            )


def _emit_via_tracker(
    tracker: Any,
    stage_id: str,
    event_type: str,
    event_dict: Dict[str, Any],
) -> None:
    """Route a resilience event through the tracker's collaboration event API.

    Args:
        tracker: ExecutionTracker (or None)
        stage_id: Stage identifier
        event_type: Resilience event type string
        event_dict: Serialized event data dictionary
    """
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
                outcome=event_dict.get("outcome"),
            )
        )
    except Exception:  # noqa: BLE001 — best-effort observability
        logger.debug(
            "Failed to emit %s event via tracker", event_type, exc_info=True,
        )
