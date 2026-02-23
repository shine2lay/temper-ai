"""Merit score service for agent reputation tracking.

Handles agent merit score computation including Bayesian updates,
exponential moving averages, and time-windowed success rates.
This is business logic extracted from ExecutionTracker.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from temper_ai.observability.constants import DEFAULT_MERIT_WINDOW_DAYS
from temper_ai.shared.constants.durations import DAYS_90
from temper_ai.shared.constants.probabilities import (
    PROB_MEDIUM,
    WEIGHT_MINIMAL,
    WEIGHT_VERY_LARGE,
)
from temper_ai.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)

# UUID hex string length for merit score IDs
UUID_HEX_LENGTH = 12

# Merit score weights (success rate vs confidence)
MERIT_SUCCESS_RATE_WEIGHT = 0.7
MERIT_CONFIDENCE_WEIGHT = 0.3


class MeritScoreService:
    """Service for updating agent merit scores based on decision outcomes.

    Manages cumulative and time-windowed metrics for agent reputation tracking.
    Requires SQL session access for persistence.

    Usage:
        service = MeritScoreService()
        service.update(session, agent_name="researcher", domain="analysis",
                       decision_outcome="success", confidence=0.85)
    """

    def __init__(self, merit_bridge: Any = None) -> None:
        self._merit_bridge = merit_bridge

    def update(
        self,
        session: Any,
        agent_name: str,
        domain: str,
        decision_outcome: str,
        confidence: float | None = None,
    ) -> None:
        """Update agent merit score based on decision outcome.

        Args:
            session: Database session for persistence
            agent_name: Name of the agent
            domain: Domain of expertise
            decision_outcome: Outcome ("success", "failure", "neutral", "mixed")
            confidence: Confidence score (0.0-1.0)
        """
        # Get or create merit score record
        merit_score = self._get_or_create_merit_score(session, agent_name, domain)

        # Update decision counts
        self._update_decision_counts(merit_score, decision_outcome)

        # Update cumulative metrics
        self._update_cumulative_metrics(merit_score, confidence)

        # Update time-windowed metrics
        self._update_time_windowed_metrics(session, merit_score, agent_name)

        # NOTE: Caller is responsible for session.commit().
        # This allows atomic transactions when merit updates are part of
        # a larger operation (e.g., DecisionTracker.track()).
        session.flush()

        # Optional bridge: trigger autonomy evaluation if configured
        if self._merit_bridge is not None:
            try:
                self._merit_bridge.on_decision_recorded(
                    session,
                    agent_name,
                    domain,
                    decision_outcome,
                )
            except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
                logger.debug("Merit bridge notification failed: %s", exc)

        self._log_merit_update(merit_score, agent_name, domain)

    def _get_or_create_merit_score(
        self, session: Any, agent_name: str, domain: str
    ) -> Any:
        """Get existing merit score or create new one."""
        from sqlmodel import select

        from temper_ai.storage.database.models import AgentMeritScore

        statement = select(AgentMeritScore).where(
            AgentMeritScore.agent_name == agent_name, AgentMeritScore.domain == domain
        )
        merit_score = session.exec(statement).first()

        if not merit_score:
            merit_score = AgentMeritScore(
                id=f"merit-{uuid.uuid4().hex[:UUID_HEX_LENGTH]}",
                agent_name=agent_name,
                domain=domain,
                total_decisions=0,
                successful_decisions=0,
                failed_decisions=0,
                overridden_decisions=0,
                first_decision_date=utcnow(),
                last_decision_date=utcnow(),
                last_updated=utcnow(),
            )
            session.add(merit_score)

        return merit_score

    def _update_decision_counts(self, merit_score: Any, decision_outcome: str) -> None:
        """Update decision counts based on outcome."""
        merit_score.total_decisions += 1
        merit_score.last_decision_date = utcnow()
        merit_score.last_updated = utcnow()

        if decision_outcome == "success":
            merit_score.successful_decisions += 1
        elif decision_outcome == "failure":
            merit_score.failed_decisions += 1
        elif decision_outcome == "mixed":
            merit_score.mixed_decisions += 1

    def _update_cumulative_metrics(
        self, merit_score: Any, confidence: float | None
    ) -> None:
        """Update cumulative success rate, confidence, and expertise score."""
        # Update cumulative metrics
        # Mixed decisions count as half-success for rate calculation
        if merit_score.total_decisions > 0:
            effective_successes = (
                merit_score.successful_decisions
                + PROB_MEDIUM * merit_score.mixed_decisions
            )
            merit_score.success_rate = effective_successes / merit_score.total_decisions

        # Update average confidence (exponential moving average, alpha=WEIGHT_MINIMAL)
        if confidence is not None:
            if merit_score.average_confidence is None:
                merit_score.average_confidence = confidence
            else:
                merit_score.average_confidence = (
                    WEIGHT_VERY_LARGE * merit_score.average_confidence
                    + WEIGHT_MINIMAL * confidence
                )

        # Compute expertise score (weighted: 70% success rate, 30% confidence)
        if merit_score.success_rate is not None:
            confidence_component = merit_score.average_confidence or PROB_MEDIUM
            merit_score.expertise_score = (
                MERIT_SUCCESS_RATE_WEIGHT * merit_score.success_rate
                + MERIT_CONFIDENCE_WEIGHT * confidence_component
            )

    def _log_merit_update(self, merit_score: Any, agent_name: str, domain: str) -> None:
        """Log merit score update."""
        success_rate_val = (
            merit_score.success_rate if merit_score.success_rate is not None else 0.0
        )
        expertise_val = (
            merit_score.expertise_score
            if merit_score.expertise_score is not None
            else 0.0
        )
        logger.info(
            f"Updated merit score for {agent_name} in {domain}: "
            f"total={merit_score.total_decisions}, "
            f"success_rate={success_rate_val:.3f}, "
            f"expertise={expertise_val:.3f}"
        )

    def _update_time_windowed_metrics(
        self, session: Any, merit_score: Any, agent_name: str
    ) -> None:
        """Update 30-day and 90-day success rates from DecisionOutcome records."""
        try:
            from sqlalchemy import String, cast, func
            from sqlmodel import select

            from temper_ai.storage.database.models import DecisionOutcome

            thirty_days_ago = utcnow() - timedelta(days=DEFAULT_MERIT_WINDOW_DAYS)
            ninety_days_ago = utcnow() - timedelta(days=DAYS_90)

            # Use cast() for portable JSON field access (works on both SQLite and PostgreSQL)
            agent_name_field = cast(DecisionOutcome.decision_data["agent_name"], String)

            # 30-day success rate
            recent_statement = (
                select(
                    func.count().label("total"),
                    func.sum(
                        func.case((DecisionOutcome.outcome == "success", 1), else_=0)
                    ).label("successful"),
                )
                .select_from(DecisionOutcome)
                .where(
                    agent_name_field == agent_name,
                    DecisionOutcome.validation_timestamp.is_not(None),  # type: ignore[union-attr]
                    DecisionOutcome.validation_timestamp >= thirty_days_ago,  # type: ignore[operator]
                )
            )

            recent_result = session.exec(recent_statement).first()
            if recent_result and recent_result.total > 0:
                merit_score.last_30_days_success_rate = (
                    recent_result.successful / recent_result.total
                )

            # 90-day success rate
            ninety_statement = (
                select(
                    func.count().label("total"),
                    func.sum(
                        func.case((DecisionOutcome.outcome == "success", 1), else_=0)
                    ).label("successful"),
                )
                .select_from(DecisionOutcome)
                .where(
                    agent_name_field == agent_name,
                    DecisionOutcome.validation_timestamp.is_not(None),  # type: ignore[union-attr]
                    DecisionOutcome.validation_timestamp >= ninety_days_ago,  # type: ignore[operator]
                )
            )

            ninety_result = session.exec(ninety_statement).first()
            if ninety_result and ninety_result.total > 0:
                merit_score.last_90_days_success_rate = (
                    ninety_result.successful / ninety_result.total
                )

        except Exception as e:
            logger.debug(f"Could not compute time-windowed metrics: {e}")
