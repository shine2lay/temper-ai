"""Tests for AutonomyPolicy."""

from unittest.mock import MagicMock

from temper_ai.safety.autonomy.approval_router import ApprovalDecision
from temper_ai.safety.autonomy.budget_enforcer import BudgetCheckResult
from temper_ai.safety.autonomy.constants import STATUS_ACTIVE, STATUS_EXHAUSTED
from temper_ai.safety.autonomy.policy import AutonomyPolicy
from temper_ai.safety.autonomy.schemas import AutonomyConfig, AutonomyLevel
from temper_ai.safety.interfaces import ViolationSeverity


def _context(enabled: bool = True, agent_id: str = "agent-a") -> dict:
    """Create a test context dict."""
    config = AutonomyConfig(enabled=enabled) if enabled else None
    return {
        "agent_id": agent_id,
        "stage_id": "general",
        "metadata": {
            "autonomy_config": config,
            "violations": [],
        },
    }


class TestNoOpWhenDisabled:
    """AutonomyPolicy is transparent when autonomy is disabled."""

    def test_no_violations_when_disabled(self) -> None:
        """Returns no violations when autonomy is disabled."""
        policy = AutonomyPolicy()
        result = policy.validate({"action": "test"}, _context(enabled=False))
        assert result.valid
        assert result.violations == []

    def test_no_violations_when_config_missing(self) -> None:
        """Returns no violations when autonomy_config is None."""
        policy = AutonomyPolicy()
        result = policy.validate({"action": "test"}, {"metadata": {}})
        assert result.valid
        assert result.violations == []


class TestEmergencyStopCheck:
    """Tests for emergency stop integration."""

    def test_blocks_when_emergency_active(self) -> None:
        """Blocks all actions when emergency stop is active."""
        policy = AutonomyPolicy()
        stop = MagicMock()
        stop.is_active.return_value = True
        policy.configure(emergency_stop=stop)

        result = policy.validate({"action": "test"}, _context())
        assert not result.valid
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.CRITICAL

    def test_passes_when_emergency_inactive(self) -> None:
        """Passes when emergency stop is not active."""
        policy = AutonomyPolicy()
        stop = MagicMock()
        stop.is_active.return_value = False
        policy.configure(emergency_stop=stop)

        result = policy.validate({"action": "test"}, _context())
        assert result.valid


class TestBudgetCheck:
    """Tests for budget enforcement integration."""

    def test_blocks_when_budget_exhausted(self) -> None:
        """Blocks actions when budget is exhausted."""
        policy = AutonomyPolicy()
        budget = MagicMock()
        budget.check_budget.return_value = BudgetCheckResult(
            allowed=False, remaining_usd=0.0,
            status=STATUS_EXHAUSTED, message="Budget exhausted",
        )
        policy.configure(budget_enforcer=budget)

        result = policy.validate({"action": "test"}, _context())
        assert not result.valid
        assert any(v.severity == ViolationSeverity.HIGH for v in result.violations)

    def test_passes_when_within_budget(self) -> None:
        """Passes when budget is sufficient."""
        policy = AutonomyPolicy()
        budget = MagicMock()
        budget.check_budget.return_value = BudgetCheckResult(
            allowed=True, remaining_usd=50.0, status=STATUS_ACTIVE,
        )
        policy.configure(budget_enforcer=budget)

        result = policy.validate({"action": "test"}, _context())
        assert result.valid


class TestApprovalRouting:
    """Tests for approval routing integration."""

    def test_violation_when_approval_required(self) -> None:
        """Adds MEDIUM violation when approval is required."""
        policy = AutonomyPolicy()
        manager = MagicMock()
        manager.get_level.return_value = AutonomyLevel.SUPERVISED
        router = MagicMock()
        router.route_action.return_value = ApprovalDecision(
            requires_approval=True, required_approvers=1,
            reason="Approval needed",
        )
        policy.configure(manager=manager, approval_router=router)

        result = policy.validate({"action": "test"}, _context())
        assert result.valid  # MEDIUM doesn't block (only HIGH+ blocks)
        assert len(result.violations) == 1
        assert result.violations[0].severity == ViolationSeverity.MEDIUM

    def test_no_violation_when_auto_approved(self) -> None:
        """No violation when auto-approved."""
        policy = AutonomyPolicy()
        manager = MagicMock()
        manager.get_level.return_value = AutonomyLevel.AUTONOMOUS
        router = MagicMock()
        router.route_action.return_value = ApprovalDecision(
            requires_approval=False, reason="Auto-approved",
        )
        policy.configure(manager=manager, approval_router=router)

        result = policy.validate({"action": "test"}, _context())
        assert result.valid
        assert result.violations == []


class TestPolicyProperties:
    """Tests for policy name, version, priority."""

    def test_name(self) -> None:
        """Policy name is autonomy_policy."""
        assert AutonomyPolicy().name == "autonomy_policy"

    def test_version(self) -> None:
        """Policy version is 1.0.0."""
        assert AutonomyPolicy().version == "1.0.0"

    def test_priority(self) -> None:
        """Policy priority is 98."""
        assert AutonomyPolicy().priority == 98
