"""Decision outcome tracking for self-improvement learning loop.

Records decisions made by the M5 self-improvement system and their outcomes,
enabling audit trails and learning from past decisions. Extracted from
ExecutionTracker to separate SQL model manipulation from observability tracking.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.observability.merit_score_service import MeritScoreService

logger = logging.getLogger(__name__)

# UUID hex string length for decision IDs
UUID_HEX_LENGTH = 12


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
        decision_type: str,
        decision_data: Dict[str, Any],
        outcome: str,
        impact_metrics: Optional[Dict[str, Any]] = None,
        lessons_learned: Optional[str] = None,
        should_repeat: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        agent_execution_id: Optional[str] = None,
        stage_execution_id: Optional[str] = None,
        workflow_execution_id: Optional[str] = None,
        validation_method: Optional[str] = None,
        validation_timestamp: Optional[datetime] = None,
        validation_duration_seconds: Optional[float] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Track a decision outcome and optionally update merit scores.

        Args:
            session: Database session for persistence
            decision_type: Type of decision
            decision_data: Decision details
            outcome: Decision outcome ("success", "failure", "neutral", "mixed")
            impact_metrics: Measured impact of decision
            lessons_learned: What was learned
            should_repeat: Whether to repeat in similar contexts
            tags: Categorization tags
            agent_execution_id: Related agent execution ID
            stage_execution_id: Related stage execution ID
            workflow_execution_id: Related workflow execution ID
            validation_method: How outcome was validated
            validation_timestamp: When outcome was validated
            validation_duration_seconds: How long validation took
            extra_metadata: Additional metadata

        Returns:
            Decision ID or empty string on failure
        """
        decision_id = f"decision-{uuid.uuid4().hex[:UUID_HEX_LENGTH]}"

        safe_decision_data = self._sanitize(decision_data, 0) if decision_data else {}
        safe_impact_metrics = self._sanitize(impact_metrics, 0) if impact_metrics else None

        try:
            from src.database.models import DecisionOutcome
        except ImportError as e:
            logger.error(
                f"Failed to import DecisionOutcome model: {e}",
                exc_info=True,
                extra={
                    "decision_type": decision_type,
                    "outcome": outcome
                }
            )
            return ""

        try:
            decision_record = DecisionOutcome(
                id=decision_id,
                agent_execution_id=agent_execution_id,
                stage_execution_id=stage_execution_id,
                workflow_execution_id=workflow_execution_id,
                decision_type=decision_type,
                decision_data=safe_decision_data,
                validation_method=validation_method,
                validation_timestamp=validation_timestamp,
                validation_duration_seconds=validation_duration_seconds,
                outcome=outcome,
                impact_metrics=safe_impact_metrics,
                lessons_learned=lessons_learned,
                should_repeat=should_repeat,
                tags=tags or [],
                extra_metadata=extra_metadata
            )
        except (TypeError, ValueError) as e:
            logger.error(
                f"Failed to create DecisionOutcome record (invalid data): {e}",
                exc_info=True,
                extra={
                    "decision_type": decision_type,
                    "outcome": outcome,
                    "decision_id": decision_id
                }
            )
            return ""

        try:
            session.add(decision_record)

            # Update agent merit score if agent_name present in decision_data
            if decision_data and 'agent_name' in decision_data:
                try:
                    agent_name_val = decision_data['agent_name']
                    domain = tags[0] if tags and len(tags) > 0 else decision_type
                    confidence_val = None
                    if impact_metrics and 'confidence' in impact_metrics:
                        confidence_val = impact_metrics['confidence']

                    self._merit_service.update(
                        session=session,
                        agent_name=agent_name_val,
                        domain=domain,
                        decision_outcome=outcome,
                        confidence=confidence_val
                    )
                except Exception as merit_e:
                    logger.warning(f"Failed to update merit score for decision {decision_id}: {merit_e}")

            # Single commit for both decision record and merit score update
            session.commit()

            logger.info(
                f"Tracked decision outcome: {decision_type} -> {outcome}",
                extra={
                    "decision_id": decision_id,
                    "decision_type": decision_type,
                    "outcome": outcome
                }
            )

            return decision_id

        except AttributeError as e:
            logger.error(
                f"Invalid session object (missing required methods): {e}",
                exc_info=True,
                extra={
                    "decision_type": decision_type,
                    "outcome": outcome,
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
                    "decision_type": decision_type,
                    "outcome": outcome,
                    "decision_id": decision_id
                }
            )
            try:
                session.rollback()
            except Exception as rollback_e:
                logger.error(f"Failed to rollback session: {rollback_e}")
            return ""
