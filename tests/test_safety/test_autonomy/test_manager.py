"""Tests for AutonomyManager."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.safety.autonomy.manager import AutonomyManager
from temper_ai.safety.autonomy.schemas import AutonomyLevel
from temper_ai.safety.autonomy.store import AutonomyStore


@pytest.fixture
def store() -> AutonomyStore:
    return AutonomyStore(database_url="sqlite:///:memory:")


@pytest.fixture
def manager(store: AutonomyStore) -> AutonomyManager:
    return AutonomyManager(store=store)


class TestGetLevel:
    """Tests for get_level."""

    def test_default_supervised(self, manager: AutonomyManager) -> None:
        """Default level is SUPERVISED."""
        assert manager.get_level("a", "d") == AutonomyLevel.SUPERVISED

    def test_returns_stored_level(self, manager: AutonomyManager) -> None:
        """Returns stored level after escalation."""
        manager.escalate("a", "d", reason="test")
        assert manager.get_level("a", "d") == AutonomyLevel.SPOT_CHECKED


class TestEscalation:
    """Tests for escalation."""

    def test_escalate_one_step(self, manager: AutonomyManager) -> None:
        """Escalates one step at a time."""
        t = manager.escalate("a", "d", reason="test")
        assert t is not None
        assert t.from_level == 0
        assert t.to_level == 1

    def test_max_level_cap(self, manager: AutonomyManager) -> None:
        """Cannot exceed max_level."""
        # Default max is RISK_GATED (2)
        manager.escalate("a", "d", reason="1")
        manager.escalate("a", "d", reason="2")
        # Now at RISK_GATED, should not escalate further
        t = manager.escalate("a", "d", reason="3")
        assert t is None

    def test_escalate_to_target(self, store: AutonomyStore) -> None:
        """Can escalate to a specific target level."""
        m = AutonomyManager(store=store, max_level=AutonomyLevel.STRATEGIC)
        t = m.escalate("a", "d", reason="test", target_level=AutonomyLevel.RISK_GATED)
        assert t is not None
        assert t.to_level == AutonomyLevel.RISK_GATED.value

    def test_cooldown_blocks(self, manager: AutonomyManager) -> None:
        """Cooldown prevents rapid escalation."""
        manager.escalate("a", "d", reason="first")
        # Second escalation should be blocked by cooldown
        t = manager.escalate("a", "d", reason="second")
        assert t is None

    def test_already_at_target(self, manager: AutonomyManager) -> None:
        """No-op when already at target level."""
        manager.escalate("a", "d", reason="1")
        # Try to escalate to same level
        t = manager.escalate("a", "d", reason="2", target_level=AutonomyLevel.SUPERVISED)
        assert t is None


class TestDeEscalation:
    """Tests for de-escalation."""

    def test_de_escalate(self, store: AutonomyStore) -> None:
        """Can de-escalate one step."""
        m = AutonomyManager(store=store, max_level=AutonomyLevel.STRATEGIC)
        m.escalate("a", "d", reason="up")
        t = m.de_escalate("a", "d", reason="down")
        assert t is not None
        assert t.from_level == 1
        assert t.to_level == 0

    def test_no_de_escalate_at_supervised(self, manager: AutonomyManager) -> None:
        """Cannot de-escalate below SUPERVISED."""
        t = manager.de_escalate("a", "d", reason="test")
        assert t is None


class TestForceLevel:
    """Tests for force_level."""

    def test_force_to_level(self, manager: AutonomyManager) -> None:
        """Force level bypasses cooldown and max_level."""
        t = manager.force_level("a", "d", AutonomyLevel.AUTONOMOUS, reason="emergency")
        assert t is not None
        assert t.to_level == AutonomyLevel.AUTONOMOUS.value
        assert manager.get_level("a", "d") == AutonomyLevel.AUTONOMOUS


class TestEvaluateAndTransition:
    """Tests for evaluate_and_transition."""

    def test_auto_escalation(self, store: AutonomyStore) -> None:
        """Auto-escalates when evaluator says eligible."""
        evaluator = MagicMock()
        eval_result = MagicMock()
        eval_result.eligible_for_escalation = True
        eval_result.needs_de_escalation = False
        eval_result.recommended_level = AutonomyLevel.SPOT_CHECKED
        eval_result.evidence = {"success_rate": 0.95}
        eval_result.reasons = ["test reason"]
        evaluator.evaluate.return_value = eval_result

        m = AutonomyManager(store=store, trust_evaluator=evaluator)
        session = MagicMock()
        t = m.evaluate_and_transition(session, "a", "d")
        assert t is not None
        assert t.to_level == 1
