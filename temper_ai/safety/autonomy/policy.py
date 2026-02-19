"""AutonomyPolicy — safety policy for progressive autonomy enforcement."""

import logging
from typing import Any, Dict, List, Optional

from temper_ai.safety.autonomy.constants import AUTONOMY_POLICY_PRIORITY
from temper_ai.safety.base import BaseSafetyPolicy
from temper_ai.safety.interfaces import ValidationResult, ViolationSeverity, SafetyViolation

logger = logging.getLogger(__name__)

POLICY_NAME = "autonomy_policy"


class AutonomyPolicy(BaseSafetyPolicy):
    """Safety policy that enforces progressive autonomy rules.

    Integrates with AutonomyManager, BudgetEnforcer, ApprovalRouter,
    and EmergencyStopController to provide trust-based access control.

    When autonomy is disabled for an agent (default), this policy
    returns no violations for full backward compatibility.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config or {})
        self._manager: Any = None
        self._budget_enforcer: Any = None
        self._approval_router: Any = None
        self._emergency_stop: Any = None

    @property
    def name(self) -> str:
        """Return policy name."""
        return POLICY_NAME

    @property
    def version(self) -> str:
        """Return policy version."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Return policy priority."""
        return AUTONOMY_POLICY_PRIORITY

    def configure(
        self,
        manager: Any = None,
        budget_enforcer: Any = None,
        approval_router: Any = None,
        emergency_stop: Any = None,
    ) -> None:
        """Wire in autonomy components after construction."""
        self._manager = manager
        self._budget_enforcer = budget_enforcer
        self._approval_router = approval_router
        self._emergency_stop = emergency_stop

    def _validate_impl(
        self, action: Dict[str, Any], context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against autonomy rules."""
        autonomy_config = context.get("metadata", {}).get("autonomy_config")
        if autonomy_config is None or not getattr(autonomy_config, "enabled", False):
            return ValidationResult(valid=True, violations=[], policy_name=self.name)

        violations: List[SafetyViolation] = []

        # Emergency stop check
        estop = self._check_emergency_stop(action, context)
        if estop is not None:
            return ValidationResult(valid=False, violations=[estop], policy_name=self.name)

        # Budget check
        self._check_budget(action, context, violations)

        # Approval routing
        self._check_approval(action, context, violations)

        valid = not any(v.severity >= ViolationSeverity.HIGH for v in violations)
        return ValidationResult(valid=valid, violations=violations, policy_name=self.name)

    def _check_emergency_stop(
        self, action: Dict[str, Any], context: Dict[str, Any]
    ) -> Optional[SafetyViolation]:
        """Check emergency stop; return violation if active."""
        if self._emergency_stop is None:
            return None
        try:
            if self._emergency_stop.is_active():
                return SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.CRITICAL,
                    message="Emergency stop is active — all actions blocked",
                    action=str(action),
                    context=context,
                )
        except (AttributeError, RuntimeError) as exc:
            logger.debug("Emergency stop check error: %s", exc)
        return None

    def _check_budget(
        self, action: Dict[str, Any], context: Dict[str, Any],
        violations: List[SafetyViolation],
    ) -> None:
        """Check budget enforcement; append violation if over budget."""
        if self._budget_enforcer is None:
            return
        agent_name = context.get("agent_id", "unknown")
        try:
            budget_result = self._budget_enforcer.check_budget(agent_name)
            if not budget_result.allowed:
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.HIGH,
                    message=budget_result.message,
                    action=str(action),
                    context=context,
                    metadata={"budget_status": budget_result.status},
                ))
        except (AttributeError, RuntimeError) as exc:
            logger.debug("Budget check error: %s", exc)

    def _check_approval(
        self, action: Dict[str, Any], context: Dict[str, Any],
        violations: List[SafetyViolation],
    ) -> None:
        """Check approval routing; append violation if approval required."""
        if self._approval_router is None or self._manager is None:
            return
        agent_name = context.get("agent_id", "unknown")
        domain = context.get("stage_id", "general")
        try:
            level = self._manager.get_level(agent_name, domain)
            existing_violations = context.get("metadata", {}).get("violations", [])
            decision = self._approval_router.route_action(
                agent_name, domain, existing_violations, level,
            )
            if decision.requires_approval:
                violations.append(SafetyViolation(
                    policy_name=self.name,
                    severity=ViolationSeverity.MEDIUM,
                    message=decision.reason,
                    action=str(action),
                    context=context,
                    metadata={
                        "required_approvers": decision.required_approvers,
                        "is_sampled": decision.is_sampled,
                        "autonomy_level": level.name,
                    },
                ))
        except (AttributeError, RuntimeError) as exc:
            logger.debug("Approval routing error: %s", exc)
