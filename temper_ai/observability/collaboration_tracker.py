"""Collaboration event tracking for multi-agent interactions.

Extracted from ExecutionTracker to separate collaboration/safety
concerns from core execution tracking.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from temper_ai.observability.backend import (
    CollaborationEventData,
    ObservabilityBackend,
    SafetyViolationData,
)
from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


@dataclass
class CollaborationEventParams:
    """Parameters for tracking collaboration events."""

    event_type: str
    stage_id: str | None = None
    agents_involved: list[str] | None = None
    event_data: dict[str, Any] | None = None
    round_number: int | None = None
    resolution_strategy: str | None = None
    outcome: str | None = None
    confidence_score: float | None = None
    extra_metadata: dict[str, Any] | None = None


class CollaborationEventTracker:
    """Tracks collaboration events and safety violations.

    Handles multi-agent interaction events (voting, conflicts, resolutions,
    consensus, debate rounds) and safety policy violations.

    Args:
        backend: Observability backend for persistence.
        sanitize_fn: Function to sanitize dictionaries (removes secrets/PII).
        get_context: Callable returning current ExecutionContext.
    """

    def __init__(
        self,
        backend: ObservabilityBackend,
        sanitize_fn: Callable[[dict[str, Any] | None], dict[str, Any] | None],
        get_context: Callable,
    ):
        self.backend = backend
        self._sanitize_dict = sanitize_fn
        self._get_context = get_context

    def track_collaboration_event(
        self,
        params: CollaborationEventParams | None = None,
        **kwargs: Any,
    ) -> str:
        """Track collaboration event for multi-agent interactions."""
        if params is None:
            params = CollaborationEventParams(**kwargs)

        # Validate and process
        if not self._validate_collab_params(params):
            return ""

        # Delegate to backend
        return self._track_event_to_backend(params)

    def _validate_collab_params(self, params: CollaborationEventParams) -> bool:
        """Validate collaboration event parameters."""
        context = self._get_context()

        # Validation: Get stage_id from context if not provided
        if not params.stage_id:
            params.stage_id = context.stage_id
            if not params.stage_id:
                logger.warning(
                    "track_collaboration_event called without stage_id context",
                    extra={
                        "event_type": params.event_type,
                        "has_workflow_context": bool(context.workflow_id),
                        "has_stage_context": bool(context.stage_id),
                        "has_agent_context": bool(context.agent_id),
                    },
                )
                return False

        # Validation: event_type is required
        if not params.event_type:
            logger.error(
                "track_collaboration_event called without event_type",
                extra={
                    "stage_id": params.stage_id,
                    "has_workflow_context": bool(context.workflow_id),
                },
            )
            return False

        # Normalize agents_involved
        if params.agents_involved is None:
            params.agents_involved = []

        # Validate confidence_score range
        if params.confidence_score is not None and not (
            0.0 <= params.confidence_score <= 1.0
        ):
            logger.warning(
                f"Invalid confidence_score {params.confidence_score}, clamping to [0.0, 1.0]",
                extra={"event_type": params.event_type, "stage_id": params.stage_id},
            )
            params.confidence_score = max(0.0, min(1.0, params.confidence_score))

        return True

    def _track_event_to_backend(self, params: CollaborationEventParams) -> str:
        """Track event to backend with error handling."""
        if params.stage_id is None:  # validated by _validate_collab_params
            raise ValueError("stage_id is required for collaboration event tracking")
        try:
            data = CollaborationEventData(
                event_data=params.event_data,
                round_number=params.round_number,
                resolution_strategy=params.resolution_strategy,
                outcome=params.outcome,
                confidence_score=params.confidence_score,
                extra_metadata=params.extra_metadata,
                timestamp=utcnow(),
            )
            return self.backend.track_collaboration_event(
                stage_id=params.stage_id,
                event_type=params.event_type,
                agents_involved=params.agents_involved or [],
                data=data,
            )
        except Exception as e:
            logger.error(
                f"Failed to track collaboration event: {e}",
                exc_info=True,
                extra={"event_type": params.event_type, "stage_id": params.stage_id},
            )
            return ""

    def track_safety_violation(
        self,
        violation_severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"],
        violation_message: str,
        policy_name: str,
        service_name: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Track safety violation for observability and metrics.

        Args:
            violation_severity: Severity level (INFO, LOW, MEDIUM, HIGH, CRITICAL)
            violation_message: Detailed violation message
            policy_name: Name of policy that was violated
            service_name: Service that detected the violation
            context: Additional context (action, params, etc.)
        """
        exec_context = self._get_context()

        # SECURITY: Sanitize context to prevent sensitive data exposure
        sanitized_context = self._sanitize_dict(context) if context else None

        data = SafetyViolationData(
            workflow_id=exec_context.workflow_id,
            stage_id=exec_context.stage_id,
            agent_id=exec_context.agent_id,
            service_name=service_name,
            context=sanitized_context,
            timestamp=utcnow(),
        )
        self.backend.track_safety_violation(
            violation_severity=violation_severity,
            violation_message=violation_message,
            policy_name=policy_name,
            data=data,
        )
