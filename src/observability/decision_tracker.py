"""Decision outcome tracking for self-improvement learning loop.

Records decisions made by the M5 self-improvement system and their outcomes,
enabling audit trails and learning from past decisions. Extracted from
ExecutionTracker to separate SQL model manipulation from observability tracking.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.observability.merit_score_service import MeritScoreService

logger = logging.getLogger(__name__)

# UUID hex string length for decision IDs
UUID_HEX_LENGTH = 12


@dataclass
class DecisionTrackingParams:
    """Parameters for tracking decision outcomes."""
    decision_type: str
    decision_data: Dict[str, Any]
    outcome: str
    impact_metrics: Optional[Dict[str, Any]] = None
    lessons_learned: Optional[str] = None
    should_repeat: Optional[bool] = None
    tags: Optional[List[str]] = None
    agent_execution_id: Optional[str] = None
    stage_execution_id: Optional[str] = None
    workflow_execution_id: Optional[str] = None
    validation_method: Optional[str] = None
    validation_timestamp: Optional[datetime] = None
    validation_duration_seconds: Optional[float] = None
    extra_metadata: Optional[Dict[str, Any]] = None


class DecisionTracker:
    """Tracks decision outcomes and delegates merit score updates.

    Usage:
        tracker = DecisionTracker(sanitize_fn=sanitizer._sanitize_dict)
        decision_id = tracker.track(
            session=session,
            decision_type="experiment_selection",
            decision_data={...},
            outcome="success",
        )
    """

    def __init__(self, sanitize_fn: Optional[Callable[[Dict[str, Any], int], Dict[str, Any]]] = None) -> None:
        """Initialize decision tracker.

        Args:
            sanitize_fn: Function to sanitize dicts (removes secrets/PII).
                         Signature: (dict, depth) -> dict
        """
        # Default no-op sanitizer with explicit type
        def default_sanitize(d: Dict[str, Any], _depth: int = 0) -> Dict[str, Any]:
            """Default no-op sanitizer that returns dict unchanged."""
            return d

        self._sanitize = sanitize_fn or default_sanitize
        self._merit_service = MeritScoreService()

    def track(
        self,
        session: Any,
        params: DecisionTrackingParams
    ) -> str:
        """Track a decision outcome and optionally update merit scores.

        Args:
            session: Database session for persistence
            params: DecisionTrackingParams with all decision tracking parameters

        Returns:
            Decision ID or empty string on failure
        """

        decision_id = f"decision-{uuid.uuid4().hex[:UUID_HEX_LENGTH]}"

        # Create decision record
        decision_record = self._create_decision_record(params, decision_id)
        if decision_record is None:
            return ""

        # Persist to database
        return self._persist_decision(session, decision_record, params, decision_id)

    def _create_decision_record(
        self,
        params: DecisionTrackingParams,
        decision_id: str
    ) -> Optional[Any]:
        """Create DecisionOutcome record from params."""
        safe_decision_data = self._sanitize(params.decision_data, 0) if params.decision_data else {}
        safe_impact_metrics = self._sanitize(params.impact_metrics, 0) if params.impact_metrics else None

        try:
            from src.database.models import DecisionOutcome
        except ImportError as e:
            logger.error(
                f"Failed to import DecisionOutcome model: {e}",
                exc_info=True,
                extra={
                    "decision_type": params.decision_type,
                    "outcome": params.outcome
                }
            )
            return None

        try:
            return DecisionOutcome(
                id=decision_id,
                agent_execution_id=params.agent_execution_id,
                stage_execution_id=params.stage_execution_id,
                workflow_execution_id=params.workflow_execution_id,
                decision_type=params.decision_type,
                decision_data=safe_decision_data,
                validation_method=params.validation_method,
                validation_timestamp=params.validation_timestamp,
                validation_duration_seconds=params.validation_duration_seconds,
                outcome=params.outcome,
                impact_metrics=safe_impact_metrics,
                lessons_learned=params.lessons_learned,
                should_repeat=params.should_repeat,
                tags=params.tags or [],
                extra_metadata=params.extra_metadata
            )
        except (TypeError, ValueError) as e:
            logger.error(
                f"Failed to create DecisionOutcome record (invalid data): {e}",
                exc_info=True,
                extra={
                    "decision_type": params.decision_type,
                    "outcome": params.outcome,
                    "decision_id": decision_id
                }
            )
            return None

    def _persist_decision(
        self,
        session: Any,
        decision_record: Any,
        params: DecisionTrackingParams,
        decision_id: str
    ) -> str:
        """Persist decision record and update merit scores."""
        try:
            session.add(decision_record)

            # Update agent merit score if agent_name present in decision_data
            self._update_merit_score_if_applicable(session, params, decision_id)

            # Single commit for both decision record and merit score update
            session.commit()

            logger.info(
                f"Tracked decision outcome: {params.decision_type} -> {params.outcome}",
                extra={
                    "decision_id": decision_id,
                    "decision_type": params.decision_type,
                    "outcome": params.outcome
                }
            )

            return decision_id

        except AttributeError as e:
            logger.error(
                f"Invalid session object (missing required methods): {e}",
                exc_info=True,
                extra={
                    "decision_type": params.decision_type,
                    "outcome": params.outcome,
                    "decision_id": decision_id
                }
            )
            return ""
        except Exception as e:
            # Catch database-specific errors (SQLAlchemy exceptions)
            logger.error(
                f"Database error while tracking decision outcome: {e}",
                exc_info=True,
                extra={
                    "decision_type": params.decision_type,
                    "outcome": params.outcome,
                    "decision_id": decision_id
                }
            )
            try:
                session.rollback()
            except Exception as rollback_e:
                logger.error(f"Failed to rollback session: {rollback_e}")
            return ""

    def _update_merit_score_if_applicable(
        self,
        session: Any,
        params: DecisionTrackingParams,
        decision_id: str
    ) -> None:
        """Update merit score if agent_name is present in decision data."""
        if params.decision_data and 'agent_name' in params.decision_data:
            try:
                agent_name_val = params.decision_data['agent_name']
                domain = params.tags[0] if params.tags and len(params.tags) > 0 else params.decision_type
                confidence_val = None
                if params.impact_metrics and 'confidence' in params.impact_metrics:
                    confidence_val = params.impact_metrics['confidence']

                self._merit_service.update(
                    session=session,
                    agent_name=agent_name_val,
                    domain=domain,
                    decision_outcome=params.outcome,
                    confidence=confidence_val
                )
            except Exception as merit_e:
                logger.warning(f"Failed to update merit score for decision {decision_id}: {merit_e}")
