"""Tests for ApprovalRouter."""

from unittest.mock import patch

from src.safety.autonomy.approval_router import ApprovalRouter
from src.safety.autonomy.schemas import AutonomyLevel
from src.safety.interfaces import SafetyViolation, ViolationSeverity


def _violation(severity: ViolationSeverity) -> SafetyViolation:
    """Create a test violation."""
    return SafetyViolation(
        policy_name="test",
        severity=severity,
        message="test",
        action="test",
        context={},
    )


class TestApprovalRouter:
    """Tests for the severity x level decision matrix."""

    def test_critical_always_two_approvers(self) -> None:
        """CRITICAL violations always require 2 approvers at any level."""
        router = ApprovalRouter()
        for level in AutonomyLevel:
            decision = router.route_action(
                "agent", "domain", [_violation(ViolationSeverity.CRITICAL)], level,
            )
            assert decision.requires_approval
            assert decision.required_approvers == 2

    def test_high_at_supervised(self) -> None:
        """HIGH severity requires 1 approver at SUPERVISED."""
        router = ApprovalRouter()
        d = router.route_action(
            "a", "d", [_violation(ViolationSeverity.HIGH)], AutonomyLevel.SUPERVISED,
        )
        assert d.requires_approval
        assert d.required_approvers == 1

    def test_high_at_autonomous(self) -> None:
        """HIGH severity auto-approved at AUTONOMOUS."""
        router = ApprovalRouter()
        d = router.route_action(
            "a", "d", [_violation(ViolationSeverity.HIGH)], AutonomyLevel.AUTONOMOUS,
        )
        assert not d.requires_approval

    def test_medium_at_supervised(self) -> None:
        """MEDIUM severity requires approval at SUPERVISED."""
        router = ApprovalRouter()
        d = router.route_action(
            "a", "d", [_violation(ViolationSeverity.MEDIUM)], AutonomyLevel.SUPERVISED,
        )
        assert d.requires_approval

    def test_medium_at_risk_gated(self) -> None:
        """MEDIUM severity auto-approved at RISK_GATED."""
        router = ApprovalRouter()
        d = router.route_action(
            "a", "d", [_violation(ViolationSeverity.MEDIUM)], AutonomyLevel.RISK_GATED,
        )
        assert not d.requires_approval

    def test_medium_spot_checked_sampled(self) -> None:
        """MEDIUM severity at SPOT_CHECKED sampled at rate."""
        router = ApprovalRouter(spot_check_rate=0.10)
        # Force sample hit
        with patch("src.safety.autonomy.approval_router.random") as mock_random:
            mock_random.random.return_value = 0.05  # Below 0.10 threshold
            d = router.route_action(
                "a", "d", [_violation(ViolationSeverity.MEDIUM)], AutonomyLevel.SPOT_CHECKED,
            )
            assert d.requires_approval
            assert d.is_sampled

    def test_medium_spot_checked_not_sampled(self) -> None:
        """MEDIUM at SPOT_CHECKED passes when not sampled."""
        router = ApprovalRouter(spot_check_rate=0.10)
        with patch("src.safety.autonomy.approval_router.random") as mock_random:
            mock_random.random.return_value = 0.50  # Above 0.10
            d = router.route_action(
                "a", "d", [_violation(ViolationSeverity.MEDIUM)], AutonomyLevel.SPOT_CHECKED,
            )
            assert not d.requires_approval

    def test_low_always_auto(self) -> None:
        """LOW severity always auto-approved."""
        router = ApprovalRouter()
        for level in AutonomyLevel:
            d = router.route_action(
                "a", "d", [_violation(ViolationSeverity.LOW)], level,
            )
            assert not d.requires_approval

    def test_no_violations_auto(self) -> None:
        """No violations always auto-approved."""
        router = ApprovalRouter()
        d = router.route_action("a", "d", [], AutonomyLevel.SUPERVISED)
        assert not d.requires_approval

    def test_none_violations_auto(self) -> None:
        """None violations always auto-approved."""
        router = ApprovalRouter()
        d = router.route_action("a", "d", None, AutonomyLevel.SUPERVISED)
        assert not d.requires_approval

    def test_multiple_violations_uses_max(self) -> None:
        """Multiple violations use max severity."""
        router = ApprovalRouter()
        d = router.route_action(
            "a", "d",
            [_violation(ViolationSeverity.LOW), _violation(ViolationSeverity.CRITICAL)],
            AutonomyLevel.STRATEGIC,
        )
        assert d.requires_approval
        assert d.required_approvers == 2
