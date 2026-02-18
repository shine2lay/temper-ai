"""Tests for the RolloutManager."""

from unittest.mock import MagicMock

import pytest

from src.autonomy.constants import DEFAULT_ROLLOUT_PHASES
from src.autonomy.rollout import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_ROLLED_BACK,
    STATUS_ROLLING_OUT,
    RolloutManager,
)


def _make_manager(experiment_service: MagicMock = None) -> RolloutManager:
    """Create a RolloutManager with a mock experiment service."""
    svc = experiment_service or MagicMock()
    svc.create_experiment.return_value = "exp-001"
    return RolloutManager(experiment_service=svc)


def _make_rollout(manager: RolloutManager = None) -> object:
    """Create a rollout via the manager for test convenience."""
    mgr = manager or _make_manager()
    return mgr.create_rollout(
        change_id="chg-001",
        config_path="configs/agents/test.yaml",
        baseline_config={"temperature": 0.7},
        candidate_config={"temperature": 0.5},
    )


class TestCreateRollout:
    """Tests for RolloutManager.create_rollout."""

    def test_creates_rollout_with_default_phases(self) -> None:
        rollout = _make_rollout()
        assert rollout.id.startswith("rollout-")
        assert len(rollout.phases) == len(DEFAULT_ROLLOUT_PHASES)
        for phase, expected_pct in zip(rollout.phases, DEFAULT_ROLLOUT_PHASES):
            assert phase.traffic_percent == expected_pct

    def test_first_phase_is_active(self) -> None:
        rollout = _make_rollout()
        assert rollout.phases[0].status == STATUS_ACTIVE
        assert rollout.status == STATUS_ROLLING_OUT

    def test_remaining_phases_are_pending(self) -> None:
        rollout = _make_rollout()
        for phase in rollout.phases[1:]:
            assert phase.status == STATUS_PENDING

    def test_custom_phases(self) -> None:
        mgr = _make_manager()
        custom_phases = [5, 50, 100]
        rollout = mgr.create_rollout(
            change_id="chg-002",
            config_path="configs/test.yaml",
            baseline_config={},
            candidate_config={},
            phases=custom_phases,
        )
        assert len(rollout.phases) == len(custom_phases)
        assert rollout.phases[0].traffic_percent == 5

    def test_experiment_id_is_set(self) -> None:
        rollout = _make_rollout()
        assert rollout.experiment_id == "exp-001"

    def test_experiment_creation_failure_sets_none(self) -> None:
        svc = MagicMock()
        svc.create_experiment.side_effect = RuntimeError("db error")
        mgr = RolloutManager(experiment_service=svc)
        rollout = mgr.create_rollout(
            change_id="chg-fail",
            config_path="configs/test.yaml",
            baseline_config={},
            candidate_config={},
        )
        assert rollout.experiment_id is None


class TestAdvancePhase:
    """Tests for RolloutManager.advance_phase."""

    def test_advances_to_next_phase(self) -> None:
        mgr = _make_manager()
        rollout = _make_rollout(mgr)
        new_phase = mgr.advance_phase(rollout)
        assert rollout.current_phase_index == 1
        assert rollout.phases[0].status == STATUS_COMPLETED
        assert new_phase.status == STATUS_ACTIVE

    def test_raises_on_final_phase(self) -> None:
        mgr = _make_manager()
        rollout = _make_rollout(mgr)
        # Advance to the last phase
        phase_count = len(rollout.phases)
        for _ in range(phase_count - 1):
            mgr.advance_phase(rollout)
        with pytest.raises(ValueError, match="final phase"):
            mgr.advance_phase(rollout)

    def test_multiple_advances(self) -> None:
        mgr = _make_manager()
        rollout = _make_rollout(mgr)
        mgr.advance_phase(rollout)
        mgr.advance_phase(rollout)
        assert rollout.current_phase_index == 2
        assert rollout.phases[0].status == STATUS_COMPLETED
        assert rollout.phases[1].status == STATUS_COMPLETED
        assert rollout.phases[2].status == STATUS_ACTIVE


class TestCheckGuardrails:
    """Tests for RolloutManager.check_guardrails."""

    def test_safe_when_no_experiment(self) -> None:
        mgr = _make_manager()
        rollout = _make_rollout(mgr)
        rollout.experiment_id = None
        assert mgr.check_guardrails(rollout) is True

    def test_safe_when_no_early_stop(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        svc.check_early_stopping.return_value = {"should_stop": False}
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        assert mgr.check_guardrails(rollout) is True

    def test_unsafe_when_should_stop(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        svc.check_early_stopping.return_value = {"should_stop": True}
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        assert mgr.check_guardrails(rollout) is False

    def test_exception_returns_false(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        svc.check_early_stopping.side_effect = RuntimeError("api error")
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        assert mgr.check_guardrails(rollout) is False


class TestCompleteRollout:
    """Tests for RolloutManager.complete_rollout."""

    def test_sets_status_to_completed(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        mgr.complete_rollout(rollout)
        assert rollout.status == STATUS_COMPLETED

    def test_all_phases_completed(self) -> None:
        mgr = _make_manager()
        rollout = _make_rollout(mgr)
        mgr.complete_rollout(rollout)
        for phase in rollout.phases:
            assert phase.status == STATUS_COMPLETED

    def test_stops_experiment(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        mgr.complete_rollout(rollout)
        svc.stop_experiment.assert_called_once_with("exp-001")


class TestRollbackRollout:
    """Tests for RolloutManager.rollback_rollout."""

    def test_sets_status_to_rolled_back(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        mgr.rollback_rollout(rollout)
        assert rollout.status == STATUS_ROLLED_BACK

    def test_stops_experiment(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        mgr.rollback_rollout(rollout)
        svc.stop_experiment.assert_called_once_with("exp-001")

    def test_experiment_stop_failure_does_not_raise(self) -> None:
        svc = MagicMock()
        svc.create_experiment.return_value = "exp-001"
        svc.stop_experiment.side_effect = RuntimeError("stop failed")
        mgr = RolloutManager(experiment_service=svc)
        rollout = _make_rollout(mgr)
        # Should not raise
        mgr.rollback_rollout(rollout)
        assert rollout.status == STATUS_ROLLED_BACK
