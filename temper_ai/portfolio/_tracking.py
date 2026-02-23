"""Portfolio observability tracking helper (best-effort)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def track_portfolio_event(
    decision_type: str,
    decision_data: dict[str, Any],
    outcome: str,
    impact_metrics: dict[str, Any] | None = None,
    duration_s: float | None = None,
    tags: list[str] | None = None,
) -> None:
    """Record a portfolio operation in the observability tracker.

    Uses lazy imports to avoid circular dependencies. Silently degrades
    if the tracker is unavailable (e.g., in tests or CLI-only mode).
    """
    try:
        from temper_ai.observability import get_tracker
        from temper_ai.observability._tracker_helpers import DecisionTrackingData

        tracker = get_tracker()
        tracker.track_decision_outcome(
            DecisionTrackingData(
                decision_type=decision_type,
                decision_data=decision_data,
                outcome=outcome,
                impact_metrics=impact_metrics,
                validation_duration_seconds=duration_s,
                tags=tags or ["portfolio"],
            )
        )
    except Exception as exc:
        logger.debug("Portfolio tracking failed: %s", exc)
