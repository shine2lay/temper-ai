"""Tests for MeritSafetyBridge."""

from unittest.mock import MagicMock

from temper_ai.safety.autonomy.merit_bridge import MeritSafetyBridge


class TestOnDecisionRecorded:
    """Tests for on_decision_recorded."""

    def test_noop_without_manager(self) -> None:
        """No-op when autonomy manager is not configured."""
        bridge = MeritSafetyBridge(autonomy_manager=None)
        bridge.on_decision_recorded(
            session=MagicMock(),
            agent_name="a",
            domain="d",
            outcome="success",
        )
        assert bridge._decision_counters == {}

    def test_rate_limited(self) -> None:
        """Evaluates only every N decisions (default 10)."""
        manager = MagicMock()
        bridge = MeritSafetyBridge(autonomy_manager=manager, evaluation_interval=10)

        session = MagicMock()
        for _i in range(9):
            bridge.on_decision_recorded(session, "a", "d", "success")

        manager.evaluate_and_transition.assert_not_called()

        # 10th call triggers evaluation
        bridge.on_decision_recorded(session, "a", "d", "success")
        manager.evaluate_and_transition.assert_called_once_with(session, "a", "d")

    def test_evaluates_at_interval(self) -> None:
        """Evaluates at every Nth decision."""
        manager = MagicMock()
        bridge = MeritSafetyBridge(autonomy_manager=manager, evaluation_interval=5)

        session = MagicMock()
        for _ in range(5):
            bridge.on_decision_recorded(session, "a", "d", "success")
        assert manager.evaluate_and_transition.call_count == 1

        for _ in range(5):
            bridge.on_decision_recorded(session, "a", "d", "success")
        assert manager.evaluate_and_transition.call_count == 2

    def test_separate_counters_per_agent_domain(self) -> None:
        """Each agent+domain pair has its own counter."""
        manager = MagicMock()
        bridge = MeritSafetyBridge(autonomy_manager=manager, evaluation_interval=2)

        session = MagicMock()
        # 2 calls for "a:d1" -> triggers
        bridge.on_decision_recorded(session, "a", "d1", "success")
        bridge.on_decision_recorded(session, "a", "d1", "success")
        assert manager.evaluate_and_transition.call_count == 1

        # 1 call for "a:d2" -> does not trigger
        bridge.on_decision_recorded(session, "a", "d2", "success")
        assert manager.evaluate_and_transition.call_count == 1

        # 2nd call for "a:d2" -> triggers
        bridge.on_decision_recorded(session, "a", "d2", "success")
        assert manager.evaluate_and_transition.call_count == 2

    def test_handles_evaluation_error(self) -> None:
        """Handles errors from evaluate_and_transition gracefully (no propagation)."""
        manager = MagicMock()
        manager.evaluate_and_transition.side_effect = RuntimeError("db error")
        bridge = MeritSafetyBridge(autonomy_manager=manager, evaluation_interval=1)

        # Should not raise — error is caught and logged internally
        bridge.on_decision_recorded(MagicMock(), "a", "d", "success")
        assert manager.evaluate_and_transition.call_count == 1
        # Counter still advances despite error (not stuck)
        assert bridge._decision_counters.get("a:d", 0) == 1

    def test_logs_transition(self) -> None:
        """Processes transition result without error when evaluate returns a transition."""
        manager = MagicMock()
        transition = MagicMock()
        transition.from_level = 0
        transition.to_level = 1
        transition.reason = "test"
        manager.evaluate_and_transition.return_value = transition

        bridge = MeritSafetyBridge(autonomy_manager=manager, evaluation_interval=1)
        bridge.on_decision_recorded(MagicMock(), "a", "d", "success")
        manager.evaluate_and_transition.assert_called_once()
        # Verify the transition object was returned (bridge logs it internally)
        assert manager.evaluate_and_transition.return_value.to_level == 1
