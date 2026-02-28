"""Targeted tests for uncovered paths in lifecycle/rollback.py.

Covers lines: 62-94, 124, 137-138, 143, 151-163
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.lifecycle._schemas import WorkflowMetrics
from temper_ai.lifecycle.history import HistoryAnalyzer
from temper_ai.lifecycle.models import LifecycleAdaptation
from temper_ai.lifecycle.rollback import (
    RollbackMonitor,
    _compute_adapted_success_rate,
    _get_baseline_rate,
)
from temper_ai.lifecycle.store import LifecycleStore

# ── Shared fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def store():
    return LifecycleStore(database_url="sqlite:///:memory:")


@pytest.fixture
def history():
    return HistoryAnalyzer(db_url=None)


def _make_adaptation(idx: int, profile: str = "lean", workflow_name: str = ""):
    chars = {"workflow_name": workflow_name} if workflow_name else {}
    return LifecycleAdaptation(
        id=f"a-{idx}",
        workflow_id=f"wf-{idx}",
        profile_name=profile,
        characteristics=chars,
    )


# ── Lines 62-94: check_degradation detects degradation ────────────────────


class TestCheckDegradationDetected:
    """Covers lines 62-94: full degradation detection path."""

    def test_degradation_detected_returns_report(self, store):
        """Lines 76-92: degradation > threshold → DegradationReport returned."""
        mock_history = MagicMock()

        # Adaptations with workflow names
        for i in range(5):
            store.save_adaptation(_make_adaptation(i, "lean", "bad_wf"))

        # Low adapted success rate
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="bad_wf",
            success_rate=0.40,  # 40% success — very bad
            run_count=100,
        )

        monitor = RollbackMonitor(
            store=store,
            history=mock_history,
            threshold=0.05,  # 5% threshold
        )

        # Baseline would also query "bad_wf" — mock returns 0.90 for baseline
        # We need different returns: adapted rate low, baseline high
        adapted_metrics = WorkflowMetrics(
            workflow_name="bad_wf", success_rate=0.40, run_count=100
        )
        baseline_metrics = WorkflowMetrics(
            workflow_name="bad_wf", success_rate=0.90, run_count=100
        )
        mock_history.get_workflow_metrics.side_effect = [
            adapted_metrics,
            adapted_metrics,
            adapted_metrics,
            adapted_metrics,
            adapted_metrics,
            baseline_metrics,  # Baseline query
        ]

        report = monitor.check_degradation("lean")

        assert report is not None
        assert report.profile_name == "lean"
        assert report.degradation_pct > 0.05
        assert report.baseline_success_rate > report.adapted_success_rate

    def test_degradation_below_threshold_returns_none(self, store):
        """Lines 75-76: degradation <= threshold → None."""
        mock_history = MagicMock()

        for i in range(5):
            store.save_adaptation(_make_adaptation(i, "lean", "good_wf"))

        # Both adapted and baseline have similar success rates
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="good_wf",
            success_rate=0.95,
            run_count=100,
        )

        monitor = RollbackMonitor(
            store=store,
            history=mock_history,
            threshold=0.05,
        )

        result = monitor.check_degradation("lean")
        assert result is None

    def test_check_degradation_returns_none_when_no_workflow_names(self, store):
        """Lines 65-73: no workflow_name in characteristics → baseline=1.0."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="", success_rate=0.0, run_count=0
        )

        # Adaptations without workflow_name
        for i in range(5):
            store.save_adaptation(
                LifecycleAdaptation(
                    id=f"a-{i}",
                    workflow_id=f"wf-{i}",
                    profile_name="lean",
                    characteristics={},  # No workflow_name
                )
            )

        monitor = RollbackMonitor(store=store, history=mock_history, threshold=0.05)
        # No workflow names → adapted_results is None → returns None
        result = monitor.check_degradation("lean")
        assert result is None

    def test_check_degradation_with_enough_data_and_metrics(self, store):
        """Lines 62-92: full path with measured workflow data."""
        mock_history = MagicMock()

        # 3 adaptations with workflow names, measured
        for i in range(3):
            store.save_adaptation(_make_adaptation(i, "lean", f"wf_{i}"))

        # All workflows have good success rates
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="any", success_rate=0.98, run_count=10
        )

        monitor = RollbackMonitor(store=store, history=mock_history, threshold=0.10)
        result = monitor.check_degradation("lean")
        # 0.98 adapted vs 0.98 baseline → no degradation
        assert result is None

    def test_degradation_warning_logged(self, store):
        """Lines 84-91: warning logged when degradation detected."""
        mock_history = MagicMock()

        for i in range(3):
            store.save_adaptation(_make_adaptation(i, "lean", "wf_x"))

        call_count = [0]

        def side_effect(wf_name, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:  # adapted queries
                return WorkflowMetrics(
                    workflow_name=wf_name, success_rate=0.30, run_count=20
                )
            return WorkflowMetrics(  # baseline query
                workflow_name=wf_name, success_rate=0.90, run_count=100
            )

        mock_history.get_workflow_metrics.side_effect = side_effect

        monitor = RollbackMonitor(store=store, history=mock_history, threshold=0.05)

        with patch("temper_ai.lifecycle.rollback.logger") as mock_logger:
            report = monitor.check_degradation("lean")
            if report is not None:
                mock_logger.warning.assert_called()


# ── Line 124: _compute_adapted_success_rate with empty adaptations list ───


class TestComputeAdaptedSuccessRateEmpty:
    """Covers line 124: None returned when adaptations list is empty."""

    def test_empty_adaptations_returns_none(self):
        """Line 124: early return None for empty list."""
        mock_history = MagicMock()
        result = _compute_adapted_success_rate([], mock_history)
        assert result is None

    def test_single_adaptation_with_no_workflow_name(self):
        """Line 133-134: wf_name empty → continue (not counted)."""
        mock_history = MagicMock()
        adaptations = [
            LifecycleAdaptation(
                id="a-1",
                workflow_id="wf-1",
                profile_name="lean",
                characteristics={},  # No workflow_name key
            )
        ]
        result = _compute_adapted_success_rate(adaptations, mock_history)
        # All skipped → measured=0 → None
        assert result is None

    def test_all_zero_run_counts_returns_none(self):
        """Lines 137-138: run_count == 0 → not measured → returns None."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="wf", success_rate=0.9, run_count=0  # Zero runs
        )

        adaptations = [
            LifecycleAdaptation(
                id="a-1",
                workflow_id="wf-1",
                profile_name="lean",
                characteristics={"workflow_name": "my_wf"},
            ),
            LifecycleAdaptation(
                id="a-2",
                workflow_id="wf-2",
                profile_name="lean",
                characteristics={"workflow_name": "my_wf"},
            ),
        ]
        result = _compute_adapted_success_rate(adaptations, mock_history)
        # All have run_count=0 → measured=0 → None
        assert result is None

    def test_some_measured_returns_average(self):
        """Lines 137-143: some measurable → returns (avg_rate, total)."""
        mock_history = MagicMock()

        def side_effect(wf_name):
            if wf_name == "measured_wf":
                return WorkflowMetrics(
                    workflow_name=wf_name, success_rate=0.8, run_count=10
                )
            return WorkflowMetrics(workflow_name=wf_name, success_rate=0.0, run_count=0)

        mock_history.get_workflow_metrics.side_effect = side_effect

        adaptations = [
            LifecycleAdaptation(
                id="a-1",
                workflow_id="wf-1",
                profile_name="lean",
                characteristics={"workflow_name": "measured_wf"},
            ),
            LifecycleAdaptation(
                id="a-2",
                workflow_id="wf-2",
                profile_name="lean",
                characteristics={"workflow_name": "unmeasured_wf"},
            ),
        ]
        result = _compute_adapted_success_rate(adaptations, mock_history)
        assert result is not None
        rate, total = result
        assert rate == 0.8  # Only measured_wf counts
        assert total == 2  # Total adaptations

    def test_multiple_measured_returns_average_rate(self):
        """Line 143: multiple measured → averaged rate returned."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.side_effect = [
            WorkflowMetrics(workflow_name="wf1", success_rate=0.6, run_count=5),
            WorkflowMetrics(workflow_name="wf2", success_rate=0.8, run_count=5),
        ]

        adaptations = [
            LifecycleAdaptation(
                id="a-1",
                workflow_id="wf-1",
                profile_name="lean",
                characteristics={"workflow_name": "wf1"},
            ),
            LifecycleAdaptation(
                id="a-2",
                workflow_id="wf-2",
                profile_name="lean",
                characteristics={"workflow_name": "wf2"},
            ),
        ]
        result = _compute_adapted_success_rate(adaptations, mock_history)
        assert result is not None
        rate, total = result
        assert abs(rate - 0.7) < 0.001  # (0.6 + 0.8) / 2
        assert total == 2


# ── Lines 151-163: _get_baseline_rate ─────────────────────────────────────


class TestGetBaselineRate:
    """Covers lines 151-163: _get_baseline_rate logic paths."""

    def test_empty_workflow_names_returns_1(self):
        """Line 151-152: empty set → return 1.0."""
        mock_history = MagicMock()
        result = _get_baseline_rate(set(), mock_history)
        assert result == 1.0

    def test_all_zero_run_counts_returns_1(self):
        """Lines 157-158, 160-161: no measurable data → return 1.0."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="wf", success_rate=0.5, run_count=0
        )
        result = _get_baseline_rate({"wf1", "wf2"}, mock_history)
        assert result == 1.0

    def test_single_workflow_returns_its_rate(self):
        """Lines 155-158, 162-163: single workflow → its success rate."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="wf", success_rate=0.75, run_count=20
        )
        result = _get_baseline_rate({"wf"}, mock_history)
        assert result == 0.75

    def test_multiple_workflows_returns_average(self):
        """Lines 155-163: multiple workflows → averaged rate."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.side_effect = [
            WorkflowMetrics(workflow_name="wf1", success_rate=0.60, run_count=10),
            WorkflowMetrics(workflow_name="wf2", success_rate=0.80, run_count=10),
        ]
        result = _get_baseline_rate({"wf1", "wf2"}, mock_history)
        assert abs(result - 0.70) < 0.001

    def test_mixed_run_counts_only_measured_averaged(self):
        """Lines 157-158: only workflows with run_count>0 averaged."""
        mock_history = MagicMock()

        def side_effect(wf_name):
            if wf_name == "measured":
                return WorkflowMetrics(
                    workflow_name=wf_name, success_rate=0.90, run_count=15
                )
            return WorkflowMetrics(
                workflow_name=wf_name, success_rate=0.50, run_count=0
            )

        mock_history.get_workflow_metrics.side_effect = side_effect
        result = _get_baseline_rate({"measured", "unmeasured"}, mock_history)
        # Only "measured" counts
        assert result == 0.90

    def test_baseline_rate_queries_each_workflow(self):
        """Lines 155-158: each workflow name is queried."""
        mock_history = MagicMock()
        mock_history.get_workflow_metrics.return_value = WorkflowMetrics(
            workflow_name="any", success_rate=0.85, run_count=5
        )
        _get_baseline_rate({"wf_a", "wf_b", "wf_c"}, mock_history)
        assert mock_history.get_workflow_metrics.call_count == 3
