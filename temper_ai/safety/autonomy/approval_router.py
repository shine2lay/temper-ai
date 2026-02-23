"""Approval routing based on violation severity and autonomy level."""

import logging
import random
from dataclasses import dataclass

from temper_ai.safety.autonomy.constants import SPOT_CHECK_SAMPLE_RATE
from temper_ai.safety.autonomy.schemas import AutonomyLevel
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity

logger = logging.getLogger(__name__)

# Required approvers for CRITICAL violations at all levels
CRITICAL_APPROVERS = 2


@dataclass
class ApprovalDecision:
    """Decision from the approval router."""

    requires_approval: bool = False
    required_approvers: int = 0
    is_sampled: bool = False
    reason: str = ""


class ApprovalRouter:
    """Route approval decisions based on severity x autonomy level matrix.

    Decision matrix:

    | Severity | SUPERVISED | SPOT_CHECKED | RISK_GATED | AUTONOMOUS | STRATEGIC |
    |----------|-----------|--------------|------------|------------|-----------|
    | CRITICAL | 2 approv  | 2 approv     | 2 approv   | 2 approv   | 2 approv  |
    | HIGH     | 1 approv  | 1 approv     | 1 approv   | auto       | auto      |
    | MEDIUM   | 1 approv  | 10% sample   | auto       | auto       | auto      |
    | LOW/None | auto      | auto         | auto       | auto       | auto      |
    """

    def __init__(self, spot_check_rate: float = SPOT_CHECK_SAMPLE_RATE) -> None:
        self._spot_check_rate = spot_check_rate

    def route_action(
        self,
        agent_name: str,
        domain: str,
        violations: list[SafetyViolation] | None = None,
        autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED,
    ) -> ApprovalDecision:
        """Determine approval requirements for an action.

        Args:
            agent_name: Agent identifier.
            domain: Domain of the action.
            violations: Safety violations detected (if any).
            autonomy_level: Current autonomy level.

        Returns:
            ApprovalDecision with approval requirements.
        """
        max_severity = self._get_max_severity(violations)

        # CRITICAL: always 2 approvers
        if max_severity == ViolationSeverity.CRITICAL:
            return ApprovalDecision(
                requires_approval=True,
                required_approvers=CRITICAL_APPROVERS,
                reason="CRITICAL violation requires 2 approvers",
            )

        # HIGH severity
        if max_severity == ViolationSeverity.HIGH:
            if autonomy_level >= AutonomyLevel.AUTONOMOUS:
                return ApprovalDecision(reason="HIGH auto-approved at AUTONOMOUS+")
            return ApprovalDecision(
                requires_approval=True,
                required_approvers=1,
                reason="HIGH violation requires 1 approver",
            )

        # MEDIUM severity
        if max_severity == ViolationSeverity.MEDIUM:
            if autonomy_level >= AutonomyLevel.RISK_GATED:
                return ApprovalDecision(reason="MEDIUM auto-approved at RISK_GATED+")
            if autonomy_level == AutonomyLevel.SPOT_CHECKED:
                return self._spot_check_decision()
            # SUPERVISED
            return ApprovalDecision(
                requires_approval=True,
                required_approvers=1,
                reason="MEDIUM violation requires approval at SUPERVISED",
            )

        # LOW/INFO/None: always auto-approved
        return ApprovalDecision(reason="No blocking violations")

    def _get_max_severity(
        self, violations: list[SafetyViolation] | None
    ) -> ViolationSeverity | None:
        """Get the highest severity from a list of violations."""
        if not violations:
            return None
        return max(v.severity for v in violations)

    def _spot_check_decision(self) -> ApprovalDecision:
        """Randomly sample for spot-check at configured rate."""
        if (
            random.random() < self._spot_check_rate
        ):  # noqa: S311 — non-security random for sampling
            return ApprovalDecision(
                requires_approval=True,
                required_approvers=1,
                is_sampled=True,
                reason=f"Spot-check sample ({self._spot_check_rate:.0%} rate)",
            )
        return ApprovalDecision(reason="MEDIUM auto-approved (not sampled)")
