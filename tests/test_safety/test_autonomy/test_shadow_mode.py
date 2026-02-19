"""Tests for ShadowMode."""

from unittest.mock import MagicMock

from temper_ai.safety.autonomy.approval_router import ApprovalDecision
from temper_ai.safety.autonomy.schemas import AutonomyLevel
from temper_ai.safety.autonomy.shadow_mode import ShadowMode
from temper_ai.safety.autonomy.store import AutonomyStore
from temper_ai.safety.interfaces import SafetyViolation, ViolationSeverity


def _violation(severity: ViolationSeverity) -> SafetyViolation:
    """Create a test violation."""
    return SafetyViolation(
        policy_name="test", severity=severity,
        message="test", action="test", context={},
    )


class TestValidateShadow:
    """Tests for validate_shadow."""

    def test_agreement_tracked(self) -> None:
        """Shadow runs and agreements increment on agreement."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        router = MagicMock()
        router.route_action.return_value = ApprovalDecision(requires_approval=True)

        result = shadow.validate_shadow(
            "agent-a", "domain", [_violation(ViolationSeverity.HIGH)],
            current_requires_approval=True,
            proposed_level=AutonomyLevel.RISK_GATED,
            approval_router=router,
        )
        assert result.agrees
        assert result.shadow_runs == 1
        assert result.shadow_agreements == 1
        assert result.agreement_rate == 1.0

    def test_disagreement_tracked(self) -> None:
        """Disagreement increments runs but not agreements."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        router = MagicMock()
        router.route_action.return_value = ApprovalDecision(requires_approval=False)

        result = shadow.validate_shadow(
            "agent-a", "domain", [_violation(ViolationSeverity.HIGH)],
            current_requires_approval=True,
            proposed_level=AutonomyLevel.AUTONOMOUS,
            approval_router=router,
        )
        assert not result.agrees
        assert result.shadow_runs == 1
        assert result.shadow_agreements == 0
        assert result.agreement_rate == 0.0

    def test_accumulates_over_runs(self) -> None:
        """Multiple runs accumulate correctly."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        router = MagicMock()
        # First run: agree
        router.route_action.return_value = ApprovalDecision(requires_approval=True)
        shadow.validate_shadow(
            "a", "d", [], current_requires_approval=True,
            proposed_level=AutonomyLevel.SPOT_CHECKED, approval_router=router,
        )
        # Second run: disagree
        router.route_action.return_value = ApprovalDecision(requires_approval=False)
        result = shadow.validate_shadow(
            "a", "d", [], current_requires_approval=True,
            proposed_level=AutonomyLevel.SPOT_CHECKED, approval_router=router,
        )
        assert result.shadow_runs == 2
        assert result.shadow_agreements == 1
        assert abs(result.agreement_rate - 0.5) < 0.01


class TestCheckPromotionReady:
    """Tests for check_promotion_ready."""

    def test_not_ready_no_state(self) -> None:
        """Not ready when no shadow state exists."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)
        assert not shadow.check_promotion_ready("agent-a", "domain")

    def test_not_ready_insufficient_runs(self) -> None:
        """Not ready with fewer than SHADOW_MIN_RUNS."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        from temper_ai.safety.autonomy.models import AutonomyState
        state = AutonomyState(
            id="as-test", agent_name="a", domain="d",
            shadow_runs=10, shadow_agreements=10,
        )
        store.save_state(state)
        assert not shadow.check_promotion_ready("a", "d")

    def test_ready_when_thresholds_met(self) -> None:
        """Ready when shadow_runs >= 50 and agreement_rate >= 0.98."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        from temper_ai.safety.autonomy.models import AutonomyState
        state = AutonomyState(
            id="as-test", agent_name="a", domain="d",
            shadow_runs=50, shadow_agreements=49,
        )
        store.save_state(state)
        assert shadow.check_promotion_ready("a", "d")

    def test_not_ready_low_agreement(self) -> None:
        """Not ready when agreement rate is below threshold."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        from temper_ai.safety.autonomy.models import AutonomyState
        state = AutonomyState(
            id="as-test", agent_name="a", domain="d",
            shadow_runs=50, shadow_agreements=45,
        )
        store.save_state(state)
        assert not shadow.check_promotion_ready("a", "d")


class TestResetShadow:
    """Tests for reset_shadow."""

    def test_resets_counters(self) -> None:
        """Reset clears shadow tracking counters."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)

        from temper_ai.safety.autonomy.models import AutonomyState
        state = AutonomyState(
            id="as-test", agent_name="a", domain="d",
            shadow_runs=25, shadow_agreements=24, shadow_level=2,
        )
        store.save_state(state)

        shadow.reset_shadow("a", "d")
        updated = store.get_state("a", "d")
        assert updated is not None
        assert updated.shadow_runs == 0
        assert updated.shadow_agreements == 0
        assert updated.shadow_level is None

    def test_reset_no_state_noop(self) -> None:
        """Reset is no-op when no state exists."""
        store = AutonomyStore(database_url="sqlite:///:memory:")
        shadow = ShadowMode(store=store)
        shadow.reset_shadow("nonexistent", "domain")
        assert store.get_state("nonexistent", "domain") is None
