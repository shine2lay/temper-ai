"""Safety policy for goal proposals — validates risk and autonomy constraints."""

import logging
from dataclasses import dataclass, field

from temper_ai.goals._schemas import GoalProposal, GoalRiskLevel
from temper_ai.goals.constants import (
    AUTO_APPROVE_RISK_MATRIX,
    MAX_BLAST_RADIUS_AUTO,
    MAX_BUDGET_IMPACT_AUTO_USD,
    MAX_PROPOSALS_PER_DAY,
)
from temper_ai.goals.store import GoalStore

logger = logging.getLogger(__name__)

# Risk level ordering for comparison
RISK_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


@dataclass
class GoalSafetyResult:
    """Result of safety policy validation."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    requires_approval: bool = True
    approval_level: str = "human"


class GoalSafetyPolicy:
    """Validates goal proposals against safety constraints."""

    def __init__(
        self,
        store: GoalStore,
        autonomy_manager: object | None = None,
        budget_enforcer: object | None = None,
        max_proposals_per_day: int = MAX_PROPOSALS_PER_DAY,
    ) -> None:
        self._store = store
        self._autonomy_manager = autonomy_manager
        self._budget_enforcer = budget_enforcer
        self._max_per_day = max_proposals_per_day

    def validate_proposal(self, proposal: GoalProposal) -> GoalSafetyResult:
        """Validate a proposal against safety constraints."""
        reasons: list[str] = []

        # Check daily rate limit
        today_count = self._store.count_proposals_today()
        if today_count >= self._max_per_day:
            return GoalSafetyResult(
                allowed=False,
                reasons=[
                    f"Daily proposal limit reached ({today_count}/{self._max_per_day})"
                ],
            )

        # Check risk level
        if proposal.risk_assessment.level == GoalRiskLevel.CRITICAL:
            reasons.append("Critical risk proposals always require human review")

        # Check budget impact if enforcer available
        if self._budget_enforcer is not None:
            budget_ok = self._check_budget(proposal)
            if not budget_ok:
                reasons.append("Estimated budget impact exceeds auto-approve threshold")

        # Check blast radius
        blast = proposal.risk_assessment.blast_radius
        if blast:
            # Count affected items (comma-separated or single)
            affected = len(blast.split(","))
            if affected > MAX_BLAST_RADIUS_AUTO:
                reasons.append(
                    f"Blast radius ({affected} items) exceeds "
                    f"auto-approve limit ({MAX_BLAST_RADIUS_AUTO})"
                )

        requires_approval = proposal.risk_assessment.level != GoalRiskLevel.LOW or bool(
            reasons
        )

        return GoalSafetyResult(
            allowed=True,
            reasons=reasons,
            requires_approval=requires_approval,
            approval_level=("human" if requires_approval else "auto"),
        )

    def can_auto_approve(self, proposal: GoalProposal, autonomy_level: int) -> bool:
        """Check if a proposal can be auto-approved at the given autonomy level."""
        # Look up the max risk level auto-approvable at this autonomy level
        max_risk_str = AUTO_APPROVE_RISK_MATRIX.get(autonomy_level)
        if max_risk_str is None:
            return False

        proposal_risk = RISK_ORDER.get(
            proposal.risk_assessment.level.value, 3  # noqa: scanner: skip-magic
        )
        max_risk = RISK_ORDER.get(max_risk_str, 0)

        if proposal_risk > max_risk:
            return False

        # Never auto-approve critical risk
        if proposal.risk_assessment.level == GoalRiskLevel.CRITICAL:
            return False

        # Check budget constraint for auto-approve
        if self._budget_enforcer is not None:
            if not self._check_budget(proposal):
                return False

        return True

    def _check_budget(self, proposal: GoalProposal) -> bool:
        """Check if proposal's cost impact is within auto-approve limits."""
        if self._budget_enforcer is None:
            return True

        # Estimate cost impact from expected impacts
        for impact in proposal.expected_impacts:
            if "cost" in impact.metric_name.lower():
                estimated_impact = abs(impact.current_value - impact.expected_value)
                if estimated_impact > MAX_BUDGET_IMPACT_AUTO_USD:
                    return False

        return True
