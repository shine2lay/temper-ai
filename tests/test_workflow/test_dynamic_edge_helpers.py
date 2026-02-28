"""Tests for dynamic edge routing helpers in the workflow engine.

Tests follow_dynamic_edges, _follow_sequential_targets, _dedup_targets,
_execute_convergence, and _follow_sequential_signals_dedup.

Mock strategy:
  _extract_next_stage_signal  → temper_ai.workflow.engines._dynamic_edge_helpers
  _run_parallel_stage_batch   → temper_ai.workflow.engines._dynamic_edge_helpers
  _build_dynamic_input_wrappers → temper_ai.workflow.engines._dynamic_edge_helpers
  _merge_stage_result         → temper_ai.workflow.engines.workflow_executor
  (local import inside _follow_parallel_targets)
"""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.engines._dynamic_edge_helpers import (
    _dedup_targets,
    _execute_convergence,
    _follow_sequential_signals_dedup,
    _follow_sequential_targets,
    follow_dynamic_edges,
)
from temper_ai.workflow.engines.workflow_executor import DEFAULT_MAX_DYNAMIC_HOPS

MODULE = "temper_ai.workflow.engines._dynamic_edge_helpers"
WF_EXECUTOR_MODULE = "temper_ai.workflow.engines.workflow_executor"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_negotiate_fn(return_state: dict[str, Any] | None = None):
    """Return a negotiate_fn stub that returns the passed-in state or a copy."""

    def negotiate(stage_name, stage_nodes, state, workflow_config):
        return dict(return_state) if return_state is not None else dict(state)

    return negotiate


def _seq_signal(targets: list[str], inputs_map: dict | None = None) -> dict[str, Any]:
    """Build a minimal sequential signal dict."""
    return {
        "mode": "sequential",
        "targets": [
            {"name": t, "inputs": (inputs_map or {}).get(t, {})} for t in targets
        ],
    }


def _par_signal(targets: list[str], converge: str | None = None) -> dict[str, Any]:
    """Build a minimal parallel signal dict."""
    sig: dict[str, Any] = {
        "mode": "parallel",
        "targets": [{"name": t, "inputs": {}} for t in targets],
    }
    if converge:
        sig["converge"] = {"name": converge}
    return sig


# ---------------------------------------------------------------------------
# follow_dynamic_edges
# ---------------------------------------------------------------------------


class TestFollowDynamicEdges:
    """Tests for follow_dynamic_edges top-level function."""

    def test_none_signal_returns_state_unchanged(self):
        """When _extract_next_stage_signal returns None, state is returned as-is."""
        state = {"existing": True}
        stage_nodes = {"stage_a": MagicMock()}
        negotiate = _make_negotiate_fn()

        with patch(f"{MODULE}._extract_next_stage_signal", return_value=None):
            result = follow_dynamic_edges("stage_a", stage_nodes, state, {}, negotiate)

        assert result == state

    def test_sequential_hop_executes_next_stage(self):
        """A sequential signal causes the target stage to be executed via negotiate_fn."""
        executed: list[str] = []

        def negotiate(stage_name, stage_nodes, state, wf_cfg):
            executed.append(stage_name)
            return dict(state)

        stage_nodes = {"target_b": MagicMock()}
        state = {"data": 1}

        signals = [_seq_signal(["target_b"]), None]  # one hop then stop

        with patch(f"{MODULE}._extract_next_stage_signal", side_effect=signals):
            follow_dynamic_edges("stage_a", stage_nodes, state, {}, negotiate)

        assert "target_b" in executed

    def test_parallel_signal_exits_loop_after_batch(self):
        """A parallel signal executes a batch and then breaks (no further chaining)."""
        state = {"v": 1}
        stage_nodes = {"p1": MagicMock(), "p2": MagicMock()}
        negotiate = _make_negotiate_fn()

        par_sig = _par_signal(["p1", "p2"])

        with (
            patch(f"{MODULE}._extract_next_stage_signal", return_value=par_sig),
            patch(
                f"{MODULE}._run_parallel_stage_batch", return_value={"p1": {}, "p2": {}}
            ),
            patch(
                f"{MODULE}._build_dynamic_input_wrappers",
                return_value={"p1": MagicMock(), "p2": MagicMock()},
            ),
            patch(
                f"{WF_EXECUTOR_MODULE}._merge_stage_result",
                side_effect=lambda s, r: {**s, **r},
            ),
            # Sequential dedup calls after parallel – no further signals
            patch(
                f"{MODULE}._extract_next_stage_signal", return_value=par_sig
            ) as mock_sig,
        ):
            # Override: first call returns parallel, subsequent return None
            mock_sig.side_effect = [par_sig, None, None]
            result = follow_dynamic_edges("stage_a", stage_nodes, state, {}, negotiate)

        assert isinstance(result, dict)

    def test_max_hops_logs_warning(self, caplog):
        """Reaching DEFAULT_MAX_DYNAMIC_HOPS emits a warning log."""
        # Each call to _extract_next_stage_signal returns a sequential signal
        # with a valid target, so we exhaust hops quickly.
        stage_nodes = {"next": MagicMock()}
        negotiate = _make_negotiate_fn()

        def always_seq(stage_name, state):
            return _seq_signal(["next"])

        with (
            caplog.at_level(logging.WARNING, logger=MODULE),
            patch(f"{MODULE}._extract_next_stage_signal", side_effect=always_seq),
        ):
            follow_dynamic_edges("start", stage_nodes, {}, {}, negotiate)

        assert any("max hops" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _follow_sequential_targets
# ---------------------------------------------------------------------------


class TestFollowSequentialTargets:
    """Tests for _follow_sequential_targets."""

    def test_known_target_negotiated(self):
        """A target present in stage_nodes is passed to negotiate_fn."""
        executed: list[str] = []

        def negotiate(stage_name, stage_nodes, state, wf_cfg):
            executed.append(stage_name)
            return dict(state)

        stage_nodes = {"target": MagicMock()}
        targets = [{"name": "target", "inputs": {}}]

        _follow_sequential_targets(
            targets, stage_nodes, {}, {}, "current", 0, negotiate
        )
        assert "target" in executed

    def test_unknown_target_skipped_with_warning(self, caplog):
        """A target not in stage_nodes is skipped and a warning is emitted."""
        negotiate = _make_negotiate_fn()
        targets = [{"name": "ghost", "inputs": {}}]

        with caplog.at_level(logging.WARNING, logger=MODULE):
            state, last, hops = _follow_sequential_targets(
                targets, {}, {}, {}, "current", 0, negotiate
            )

        assert hops == 0  # No hop made
        assert any("ghost" in r.message for r in caplog.records)

    def test_inputs_injected_into_state(self):
        """When a target has inputs, DYNAMIC_INPUTS is set in state before negotiate."""
        seen_inputs: list[Any] = []

        def negotiate(stage_name, stage_nodes, state, wf_cfg):
            seen_inputs.append(state.get(StateKeys.DYNAMIC_INPUTS))
            return dict(state)

        stage_nodes = {"t": MagicMock()}
        targets = [{"name": "t", "inputs": {"x": 42}}]

        _follow_sequential_targets(targets, stage_nodes, {}, {}, "src", 0, negotiate)
        assert seen_inputs[0] == {"x": 42}

    def test_dynamic_inputs_cleaned_after_execution(self):
        """DYNAMIC_INPUTS is removed from state after negotiate_fn returns."""

        def negotiate(stage, nodes, state, cfg):
            state[StateKeys.DYNAMIC_INPUTS] = {"injected": True}
            return dict(state)

        stage_nodes = {"t": MagicMock()}
        targets = [{"name": "t", "inputs": {"x": 1}}]

        final_state, _, _ = _follow_sequential_targets(
            targets, stage_nodes, {}, {}, "src", 0, negotiate
        )
        assert StateKeys.DYNAMIC_INPUTS not in final_state

    def test_hop_count_incremented_per_valid_target(self):
        """Each known target increments hop_count by 1."""
        negotiate = _make_negotiate_fn()
        stage_nodes = {"a": MagicMock(), "b": MagicMock()}
        targets = [
            {"name": "a", "inputs": {}},
            {"name": "b", "inputs": {}},
        ]

        _, _, hops = _follow_sequential_targets(
            targets, stage_nodes, {}, {}, "src", 0, negotiate
        )
        assert hops == 2

    def test_hop_limit_stops_iteration(self):
        """When hop_count already equals DEFAULT_MAX_DYNAMIC_HOPS, no targets run."""
        executed: list[str] = []

        def negotiate(stage_name, nodes, state, cfg):
            executed.append(stage_name)
            return dict(state)

        stage_nodes = {"a": MagicMock()}
        targets = [{"name": "a", "inputs": {}}]

        _follow_sequential_targets(
            targets, stage_nodes, {}, {}, "src", DEFAULT_MAX_DYNAMIC_HOPS, negotiate
        )
        assert executed == []


# ---------------------------------------------------------------------------
# _dedup_targets
# ---------------------------------------------------------------------------


class TestDedupTargets:
    """Tests for _dedup_targets."""

    def test_removes_duplicate_target_names(self):
        """When the same target appears twice only the first occurrence is kept."""
        stage_nodes = {"a": MagicMock()}
        targets = [{"name": "a", "inputs": {}}, {"name": "a", "inputs": {}}]
        result = _dedup_targets(targets, stage_nodes)
        assert len(result) == 1
        assert result[0]["name"] == "a"

    def test_filters_targets_not_in_stage_nodes(self):
        """Targets not present in stage_nodes are excluded from the result."""
        stage_nodes = {"known": MagicMock()}
        targets = [{"name": "known", "inputs": {}}, {"name": "unknown", "inputs": {}}]
        result = _dedup_targets(targets, stage_nodes)
        names = [t["name"] for t in result]
        assert "known" in names
        assert "unknown" not in names

    def test_preserves_all_known_unique_targets(self):
        """All known, non-duplicate targets appear in the result."""
        stage_nodes = {"a": MagicMock(), "b": MagicMock(), "c": MagicMock()}
        targets = [
            {"name": "a", "inputs": {}},
            {"name": "b", "inputs": {}},
            {"name": "c", "inputs": {}},
        ]
        result = _dedup_targets(targets, stage_nodes)
        assert [t["name"] for t in result] == ["a", "b", "c"]

    def test_empty_targets_returns_empty(self):
        """An empty targets list produces an empty result."""
        assert _dedup_targets([], {"a": MagicMock()}) == []


# ---------------------------------------------------------------------------
# _execute_convergence
# ---------------------------------------------------------------------------


class TestExecuteConvergence:
    """Tests for _execute_convergence."""

    def test_not_found_in_stage_nodes_skips_and_warns(self, caplog):
        """When convergence stage is not in stage_nodes, state is unchanged."""
        converge = {"name": "missing"}
        negotiate = _make_negotiate_fn()

        with caplog.at_level(logging.WARNING, logger=MODULE):
            state, hops = _execute_convergence(
                converge, ["a", "b"], {}, {"key": "val"}, {}, 0, negotiate
            )

        assert state == {"key": "val"}
        assert hops == 0
        assert any("missing" in r.message for r in caplog.records)

    def test_at_hop_limit_skips_execution(self):
        """When hop_count == DEFAULT_MAX_DYNAMIC_HOPS, convergence is skipped."""
        executed: list[str] = []

        def negotiate(stage, nodes, state, cfg):
            executed.append(stage)
            return dict(state)

        stage_nodes = {"conv": MagicMock()}
        converge = {"name": "conv"}

        state, hops = _execute_convergence(
            converge, ["a"], stage_nodes, {}, {}, DEFAULT_MAX_DYNAMIC_HOPS, negotiate
        )
        assert executed == []
        assert hops == DEFAULT_MAX_DYNAMIC_HOPS

    def test_successful_execution_calls_negotiate(self):
        """When conditions are met, negotiate_fn is called for the convergence stage."""
        executed: list[str] = []

        def negotiate(stage, nodes, state, cfg):
            executed.append(stage)
            return {**state, "converged": True}

        stage_nodes = {"conv": MagicMock()}
        converge = {"name": "conv"}

        state, hops = _execute_convergence(
            converge, ["a", "b"], stage_nodes, {}, {}, 0, negotiate
        )
        assert "conv" in executed
        assert hops == 1
        assert state.get("converged") is True

    def test_records_convergence_predecessors(self):
        """Convergence predecessors are stored in state under _convergence_predecessors."""

        def negotiate(stage, nodes, state, cfg):
            return dict(state)

        stage_nodes = {"conv": MagicMock()}
        converge = {"name": "conv"}
        branch_names = ["branch_a", "branch_b"]

        state, _ = _execute_convergence(
            converge, branch_names, stage_nodes, {}, {}, 0, negotiate
        )
        preds = state.get("_convergence_predecessors", {})
        assert preds.get("conv") == branch_names


# ---------------------------------------------------------------------------
# _follow_sequential_signals_dedup
# ---------------------------------------------------------------------------


class TestFollowSequentialSignalsDedup:
    """Tests for _follow_sequential_signals_dedup."""

    def test_already_followed_targets_skipped(self):
        """Targets already in the followed set are not executed again."""
        executed: list[str] = []

        def negotiate(stage, nodes, state, cfg):
            executed.append(stage)
            return dict(state)

        stage_nodes = {"t": MagicMock()}
        followed: set = {"t"}
        signal = _seq_signal(["t"])

        with patch(f"{MODULE}._extract_next_stage_signal", return_value=signal):
            _follow_sequential_signals_dedup(
                "src", stage_nodes, {}, {}, 0, negotiate, followed
            )

        assert "t" not in executed

    def test_new_targets_are_executed(self):
        """Targets not in the followed set are executed and added to it."""
        executed: list[str] = []

        def negotiate(stage, nodes, state, cfg):
            executed.append(stage)
            return dict(state)

        stage_nodes = {"new_stage": MagicMock()}
        followed: set = set()
        signal = _seq_signal(["new_stage"])

        with patch(f"{MODULE}._extract_next_stage_signal", return_value=signal):
            _follow_sequential_signals_dedup(
                "src", stage_nodes, {}, {}, 0, negotiate, followed
            )

        assert "new_stage" in executed
        assert "new_stage" in followed

    def test_none_signal_returns_early(self):
        """When no signal is present, state and hop_count are returned unchanged."""
        negotiate = _make_negotiate_fn()

        with patch(f"{MODULE}._extract_next_stage_signal", return_value=None):
            state, last, hops = _follow_sequential_signals_dedup(
                "src", {}, {"k": "v"}, {}, 3, negotiate, set()
            )

        assert state == {"k": "v"}
        assert hops == 3

    def test_non_sequential_mode_returns_early(self):
        """A parallel-mode signal from a branch is not followed (prevents fan-out)."""
        executed: list[str] = []

        def negotiate(stage, nodes, state, cfg):
            executed.append(stage)
            return dict(state)

        parallel_signal = {"mode": "parallel", "targets": [{"name": "p", "inputs": {}}]}

        with patch(
            f"{MODULE}._extract_next_stage_signal", return_value=parallel_signal
        ):
            state, _, hops = _follow_sequential_signals_dedup(
                "src", {"p": MagicMock()}, {}, {}, 0, negotiate, set()
            )

        assert executed == []
        assert hops == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
