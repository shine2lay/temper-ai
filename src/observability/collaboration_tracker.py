"""Collaboration event tracking for multi-agent interactions.

Extracted from ExecutionTracker to separate collaboration/safety
concerns from core execution tracking.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional

from src.database.datetime_utils import utcnow
from src.observability.backend import (
    CollaborationEventData,
    ObservabilityBackend,
    SafetyViolationData,
)

logger = logging.getLogger(__name__)


@dataclass
class CollaborationEventParams:
    """Parameters for tracking collaboration events."""
    event_type: str
    stage_id: Optional[str] = None
    agents_involved: Optional[List[str]] = None
    event_data: Optional[Dict[str, Any]] = None
    round_number: Optional[int] = None
    resolution_strategy: Optional[str] = None
    outcome: Optional[str] = None
    confidence_score: Optional[float] = None
    extra_metadata: Optional[Dict[str, Any]] = None


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
        sanitize_fn: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
        get_context: Callable,
    ):
        self.backend = backend
        self._sanitize_dict = sanitize_fn
        self._get_context = get_context

    def track_collaboration_event(
        self,
        event_type: str,
        stage_id: Optional[str] = None,
        agents_involved: Optional[List[str]] = None,
        event_data: Optional[Dict[str, Any]] = None,
        round_number: Optional[int] = None,
        resolution_strategy: Optional[str] = None,
        outcome: Optional[str] = None,
        confidence_score: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        # Legacy parameters for backward compatibility with executors
        stage_name: Optional[str] = None,
        agents: Optional[List[str]] = None,
        decision: Optional[str] = None,
        confidence: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Track collaboration event for multi-agent interactions.

        Supports both schema-aligned parameters and legacy executor calls.

        Returns:
            ID of created collaboration event record, or empty string on failure.
        """
        # Create params and map legacy parameters
        params = CollaborationEventParams(
            event_type=event_type,
            stage_id=stage_id,
            agents_involved=agents_involved,
            event_data=event_data,
            round_number=round_number,
            resolution_strategy=resolution_strategy,
            outcome=outcome,
            confidence_score=confidence_score,
            extra_metadata=extra_metadata
        )

        # Map legacy parameters to new schema
        self._map_legacy_params(params, stage_name, agents, decision, confidence, metadata)

        # Validate and process
        if not self._validate_collab_params(params):
            return ""

        # Delegate to backend
        return self._track_event_to_backend(params)

    def _map_legacy_params(
        self,
        params: CollaborationEventParams,
        stage_name: Optional[str],
        agents: Optional[List[str]],
        decision: Optional[str],
        confidence: Optional[float],
        metadata: Optional[Dict[str, Any]]
    ) -> None:
        """Map legacy parameters to params dataclass."""
        context = self._get_context()

        if stage_name and not params.stage_id:
            params.stage_id = context.stage_id or stage_name

        if agents and not params.agents_involved:
            params.agents_involved = agents

        if decision is not None and not params.outcome:
            params.outcome = decision

        if confidence is not None and params.confidence_score is None:
            params.confidence_score = confidence

        if metadata and not params.event_data:
            params.event_data = metadata

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
        if params.confidence_score is not None and not (0.0 <= params.confidence_score <= 1.0):
            logger.warning(
                f"Invalid confidence_score {params.confidence_score}, clamping to [0.0, 1.0]",
                extra={"event_type": params.event_type, "stage_id": params.stage_id},
            )
            params.confidence_score = max(0.0, min(1.0, params.confidence_score))

        return True

    def _track_event_to_backend(self, params: CollaborationEventParams) -> str:
        """Track event to backend with error handling."""
        assert params.stage_id is not None  # validated by _validate_collab_params
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
        service_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
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
