"""Integration tests for progressive autonomy lifecycle."""

from unittest.mock import MagicMock

import pytest

from temper_ai.safety.autonomy.approval_router import ApprovalRouter
from temper_ai.safety.autonomy.budget_enforcer import BudgetEnforcer
from temper_ai.safety.autonomy.constants import STATUS_EXHAUSTED
from temper_ai.safety.autonomy.emergency_stop import (
    EmergencyStopController,
    EmergencyStopError,
    reset_emergency_state,
)
from temper_ai.safety.autonomy.manager import AutonomyManager
from temper_ai.safety.autonomy.policy import AutonomyPolicy
from temper_ai.safety.autonomy.schemas import AutonomyConfig, AutonomyLevel
from temper_ai.safety.autonomy.shadow_mode import ShadowMode
from temper_ai.safety.autonomy.store import AutonomyStore
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity


@pytest.fixture(autouse=True)
def _reset_stop() -> None:
    reset_emergency_state()


@pytest.fixture
def store() -> AutonomyStore:
    return AutonomyStore(database_url="sqlite:///:memory:")


def _violation(severity: ViolationSeverity) -> SafetyViolation:
    return SafetyViolation(
        policy_name="test", severity=severity,
        message="test", action="test", context={},
    )


class TestFullLifecycle:
    """End-to-end: supervised -> escalate -> de-escalate."""

    def test_escalation_lifecycle(self, store: AutonomyStore) -> None:
        """Agent starts supervised, escalates, then de-escalates."""
        manager = AutonomyManager(
            store=store, max_level=AutonomyLevel.STRATEGIC,
        )

        # Start supervised
        assert manager.get_level("a", "d") == AutonomyLevel.SUPERVISED

        # Escalate to SPOT_CHECKED
        t = manager.escalate("a", "d", reason="good track record")
        assert t is not None
        assert t.to_level == AutonomyLevel.SPOT_CHECKED.value
        assert manager.get_level("a", "d") == AutonomyLevel.SPOT_CHECKED

        # De-escalate back to SUPERVISED
        t = manager.de_escalate("a", "d", reason="regression")
        assert t is not None
        assert t.to_level == AutonomyLevel.SUPERVISED.value
        assert manager.get_level("a", "d") == AutonomyLevel.SUPERVISED

    def test_force_to_strategic(self, store: AutonomyStore) -> None:
        """Force level bypasses all guards."""
        manager = AutonomyManager(store=store)
        t = manager.force_level("a", "d", AutonomyLevel.STRATEGIC, reason="admin override")
        assert t.to_level == AutonomyLevel.STRATEGIC.value
        assert manager.get_level("a", "d") == AutonomyLevel.STRATEGIC


class TestEmergencyStopIntegration:
    """Emergency stop halts all validations."""

    def test_stop_halts_policy(self, store: AutonomyStore) -> None:
        """Emergency stop causes policy to block all actions."""
        controller = EmergencyStopController(store=store)
        policy = AutonomyPolicy()
        policy.configure(emergency_stop=controller)

        context = {
            "agent_id": "a",
            "stage_id": "d",
            "metadata": {"autonomy_config": AutonomyConfig(enabled=True)},
        }

        # Normal operation
        result = policy.validate({"action": "test"}, context)
        assert result.valid

        # Activate emergency stop
        controller.activate(triggered_by="admin", reason="test")

        result = policy.validate({"action": "test"}, context)
        assert not result.valid
        assert any(v.severity == ViolationSeverity.CRITICAL for v in result.violations)

        # Resume
        controller.deactivate(resolution_reason="resolved")
        result = policy.validate({"action": "test"}, context)
        assert result.valid

    def test_check_or_raise(self, store: AutonomyStore) -> None:
        """check_or_raise raises after activate."""
        controller = EmergencyStopController(store=store)
        controller.activate(triggered_by="admin", reason="test")
        with pytest.raises(EmergencyStopError):
            controller.check_or_raise()


class TestBudgetExhaustion:
    """Budget exhaustion blocks actions."""

    def test_exhausted_budget_blocks(self, store: AutonomyStore) -> None:
        """Actions blocked when budget is exhausted."""
        enforcer = BudgetEnforcer(store=store, default_budget=10.0)
        enforcer.record_spend("agent-a", 10.0)

        result = enforcer.check_budget("agent-a")
        assert not result.allowed
        assert result.status == STATUS_EXHAUSTED


class TestApprovalRouterWithPolicy:
    """Approval router decisions flow through policy."""

    def test_supervised_high_violation_blocked(self, store: AutonomyStore) -> None:
        """HIGH violation at SUPERVISED level produces violation."""
        manager = AutonomyManager(store=store)
        router = ApprovalRouter()
        policy = AutonomyPolicy()
        policy.configure(manager=manager, approval_router=router)

        context = {
            "agent_id": "agent-a",
            "stage_id": "code",
            "metadata": {
                "autonomy_config": AutonomyConfig(enabled=True),
                "violations": [_violation(ViolationSeverity.HIGH)],
            },
        }

        result = policy.validate({"action": "deploy"}, context)
        # MEDIUM violation from approval routing (approval required at SUPERVISED)
        assert len(result.violations) > 0
        assert any(v.severity == ViolationSeverity.MEDIUM for v in result.violations)


class TestShadowWithApprovalRouter:
    """Shadow mode tracks agreement with approval router."""

    def test_shadow_agreement_tracking(self, store: AutonomyStore) -> None:
        """Shadow mode tracks agreement between current and proposed level."""
        shadow = ShadowMode(store=store)
        router = ApprovalRouter()

        violations = [_violation(ViolationSeverity.HIGH)]

        # At SUPERVISED, HIGH requires approval
        result = shadow.validate_shadow(
            "a", "d", violations,
            current_requires_approval=True,
            proposed_level=AutonomyLevel.RISK_GATED,  # Still requires approval for HIGH
            approval_router=router,
        )
        assert result.agrees  # Both require approval
        assert result.shadow_runs == 1
