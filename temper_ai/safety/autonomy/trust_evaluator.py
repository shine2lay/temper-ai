"""Trust evaluation based on agent merit scores."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from temper_ai.safety.autonomy.constants import (
    DE_ESCALATION_FAILURE_RATE,
    ESCALATION_SUCCESS_RATE,
    MIN_DECISIONS_FOR_ESCALATION,
)
from temper_ai.safety.autonomy.schemas import AutonomyLevel

logger = logging.getLogger(__name__)


@dataclass
class TrustEvaluation:
    """Result of a trust evaluation for an agent."""

    eligible_for_escalation: bool = False
    needs_de_escalation: bool = False
    recommended_level: Optional[AutonomyLevel] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)


class TrustEvaluator:
    """Evaluate agent trust based on merit score history.

    Reads AgentMeritScore records and checks against escalation/de-escalation
    thresholds to determine if an agent is ready for more or less autonomy.
    """

    def __init__(
        self,
        min_decisions: int = MIN_DECISIONS_FOR_ESCALATION,
        escalation_rate: float = ESCALATION_SUCCESS_RATE,
        de_escalation_rate: float = DE_ESCALATION_FAILURE_RATE,
    ) -> None:
        self._min_decisions = min_decisions
        self._escalation_rate = escalation_rate
        self._de_escalation_rate = de_escalation_rate

    def evaluate(
        self,
        session: Any,
        agent_name: str,
        domain: str,
        current_level: AutonomyLevel = AutonomyLevel.SUPERVISED,
    ) -> TrustEvaluation:
        """Evaluate whether an agent should be escalated or de-escalated.

        Args:
            session: Database session.
            agent_name: Agent identifier.
            domain: Domain of expertise.
            current_level: Current autonomy level.

        Returns:
            TrustEvaluation with escalation/de-escalation recommendation.
        """
        merit = self._load_merit_score(session, agent_name, domain)
        if merit is None:
            return TrustEvaluation(
                evidence={"reason": "no_merit_record"},
                reasons=["No merit score record found"],
            )

        evidence = self._build_evidence(merit)
        result = TrustEvaluation(evidence=evidence)

        # Check de-escalation first (safety priority)
        failure_rate = self._compute_failure_rate(merit)
        if failure_rate >= self._de_escalation_rate and current_level > AutonomyLevel.SUPERVISED:
            result.needs_de_escalation = True
            new_level = AutonomyLevel(max(0, current_level - 1))
            result.recommended_level = new_level
            result.reasons.append(
                f"Failure rate {failure_rate:.2%} >= {self._de_escalation_rate:.2%}"
            )
            return result

        # Check escalation eligibility
        if merit.total_decisions < self._min_decisions:
            result.reasons.append(
                f"Insufficient decisions: {merit.total_decisions} < {self._min_decisions}"
            )
            return result

        success_rate = merit.success_rate if merit.success_rate is not None else 0.0
        if success_rate >= self._escalation_rate:
            result.eligible_for_escalation = True
            new_level = AutonomyLevel(min(current_level + 1, AutonomyLevel.STRATEGIC))
            result.recommended_level = new_level
            result.reasons.append(
                f"Success rate {success_rate:.2%} >= {self._escalation_rate:.2%} "
                f"with {merit.total_decisions} decisions"
            )

        return result

    def _load_merit_score(
        self, session: Any, agent_name: str, domain: str
    ) -> Any:
        """Load AgentMeritScore from database."""
        try:
            from sqlmodel import select
            from temper_ai.storage.database.models import AgentMeritScore

            stmt = select(AgentMeritScore).where(
                AgentMeritScore.agent_name == agent_name,
                AgentMeritScore.domain == domain,
            )
            return session.exec(stmt).first()
        except (ImportError, AttributeError) as exc:
            logger.debug("Could not load merit score: %s", exc)
            return None

    def _compute_failure_rate(self, merit: Any) -> float:
        """Compute recent failure rate from merit score."""
        if merit.total_decisions == 0:
            return 0.0
        return float(merit.failed_decisions / merit.total_decisions)

    def _build_evidence(self, merit: Any) -> Dict[str, Any]:
        """Build evidence dict from merit score fields."""
        return {
            "total_decisions": merit.total_decisions,
            "successful_decisions": merit.successful_decisions,
            "failed_decisions": merit.failed_decisions,
            "success_rate": merit.success_rate,
            "average_confidence": merit.average_confidence,
            "expertise_score": merit.expertise_score,
        }
