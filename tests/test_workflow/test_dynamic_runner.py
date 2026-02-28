"""Tests for ThreadPoolParallelRunner in the dynamic execution engine.

Tests _merge_dicts (recursive dict merge), ThreadPoolParallelRunner
initialisation, run_parallel (single/multiple nodes, init/collect hooks,
empty-nodes warning), and _run_nodes_parallel (exception capture).

Pure unit tests — real threads, no mocking required.
"""

import logging
from typing import Any

import pytest

from temper_ai.workflow.engines.dynamic_runner import (
    DEFAULT_MAX_WORKERS,
    ThreadPoolParallelRunner,
    _merge_dicts,
)

# ---------------------------------------------------------------------------
# _merge_dicts
# ---------------------------------------------------------------------------


class TestMergeDicts:
    """Tests for the recursive dict-merge helper."""

    def test_flat_merge_combines_keys(self):
        """Non-overlapping keys from both dicts appear in the result."""
        result = _merge_dicts({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_right_wins_on_scalar_conflict(self):
        """Right dict value replaces left for non-dict scalar conflicts."""
        result = _merge_dicts({"x": 1, "y": 2}, {"x": 99, "z": 3})
        assert result == {"x": 99, "y": 2, "z": 3}

    def test_recursive_merge_nested_dicts(self):
        """When both sides have a dict value for the same key, merge recursively."""
        left = {"outputs": {"a": 1, "b": 2}}
        right = {"outputs": {"b": 99, "c": 3}}
        result = _merge_dicts(left, right)
        assert result == {"outputs": {"a": 1, "b": 99, "c": 3}}

    def test_empty_left_returns_right(self):
        """Merging an empty left dict returns a copy of right."""
        result = _merge_dicts({}, {"k": "v"})
        assert result == {"k": "v"}

    def test_empty_right_returns_left(self):
        """Merging an empty right dict returns a copy of left."""
        result = _merge_dicts({"k": "v"}, {})
        assert result == {"k": "v"}

    def test_both_empty(self):
        """Merging two empty dicts produces an empty dict."""
        assert _merge_dicts({}, {}) == {}

    def test_left_not_mutated(self):
        """The original left dict must not be modified."""
        left = {"a": 1}
        _merge_dicts(left, {"b": 2})
        assert left == {"a": 1}

    def test_right_overwrites_non_dict_with_dict(self):
        """When right has a dict value for a key that left has a scalar, right wins."""
        result = _merge_dicts({"key": "scalar"}, {"key": {"nested": True}})
        assert result == {"key": {"nested": True}}


# ---------------------------------------------------------------------------
# ThreadPoolParallelRunner – initialisation
# ---------------------------------------------------------------------------


class TestThreadPoolParallelRunnerInit:
    """Tests for ThreadPoolParallelRunner.__init__."""

    def test_default_max_workers(self):
        """Default max_workers should equal DEFAULT_MAX_WORKERS (8)."""
        runner = ThreadPoolParallelRunner()
        assert runner.max_workers == DEFAULT_MAX_WORKERS
        assert DEFAULT_MAX_WORKERS == 8

    def test_custom_max_workers(self):
        """Custom max_workers value is stored on the instance."""
        runner = ThreadPoolParallelRunner(max_workers=4)
        assert runner.max_workers == 4


# ---------------------------------------------------------------------------
# ThreadPoolParallelRunner.run_parallel
# ---------------------------------------------------------------------------


class TestRunParallel:
    """Tests for ThreadPoolParallelRunner.run_parallel."""

    def test_single_node_result_merged(self):
        """A single node's return dict is merged into the final state."""
        runner = ThreadPoolParallelRunner()

        def node_a(state: dict[str, Any]) -> dict[str, Any]:
            return {"result": "ok"}

        result = runner.run_parallel({"a": node_a}, {"existing": True})
        assert result["result"] == "ok"
        assert result["existing"] is True

    def test_multiple_nodes_all_results_merged(self):
        """All parallel node outputs are merged into a single state dict."""
        runner = ThreadPoolParallelRunner(max_workers=2)

        result = runner.run_parallel(
            {
                "a": lambda s: {"outputs": {"a": "x"}},
                "b": lambda s: {"outputs": {"b": "y"}},
            },
            {"outputs": {}},
        )
        assert result["outputs"]["a"] == "x"
        assert result["outputs"]["b"] == "y"

    def test_with_init_node(self):
        """init_node result is merged into state before parallel nodes run."""
        runner = ThreadPoolParallelRunner()
        init_called: list[bool] = []

        def init(state: dict[str, Any]) -> dict[str, Any]:
            init_called.append(True)
            return {"initialised": True}

        def node(state: dict[str, Any]) -> dict[str, Any]:
            assert state.get("initialised") is True
            return {"done": True}

        result = runner.run_parallel({"n": node}, {}, init_node=init)
        assert init_called, "init_node was never called"
        assert result["initialised"] is True
        assert result["done"] is True

    def test_with_collect_node(self):
        """collect_node runs after all parallel nodes and its updates are merged."""
        runner = ThreadPoolParallelRunner()
        collect_called: list[bool] = []

        def collect(state: dict[str, Any]) -> dict[str, Any]:
            collect_called.append(True)
            return {"collected": True}

        result = runner.run_parallel(
            {"a": lambda s: {"r": 1}},
            {},
            collect_node=collect,
        )
        assert collect_called, "collect_node was never called"
        assert result["collected"] is True
        assert result["r"] == 1

    def test_empty_nodes_logs_warning(self, caplog):
        """Passing an empty nodes dict emits a warning and returns initial state."""
        runner = ThreadPoolParallelRunner()
        state = {"key": "value"}

        with caplog.at_level(
            logging.WARNING, logger="temper_ai.workflow.engines.dynamic_runner"
        ):
            result = runner.run_parallel({}, state)

        assert result["key"] == "value"
        assert any("No nodes to execute" in r.message for r in caplog.records)

    def test_init_and_collect_combined(self):
        """Both init and collect nodes coexist correctly; collect runs last."""
        runner = ThreadPoolParallelRunner()
        order: list[str] = []

        result = runner.run_parallel(
            {"a": lambda s: {"step": "parallel"}},
            {},
            init_node=lambda s: (order.append("init") or {"step": "init"}),
            collect_node=lambda s: (order.append("collect") or {"step": "collect"}),
        )
        assert order == ["init", "collect"]
        assert result["step"] == "collect"

    def test_initial_state_not_mutated(self):
        """The caller's initial_state dict must not be mutated."""
        runner = ThreadPoolParallelRunner()
        initial = {"original": True}

        runner.run_parallel({"a": lambda s: {"extra": True}}, initial)
        assert "extra" not in initial


# ---------------------------------------------------------------------------
# ThreadPoolParallelRunner._run_nodes_parallel
# ---------------------------------------------------------------------------


class TestRunNodesParallel:
    """Tests for _run_nodes_parallel exception handling."""

    def test_exception_captured_in_failed_nodes(self):
        """When a node raises, its name is appended to _failed_nodes."""
        runner = ThreadPoolParallelRunner()

        def failing(state: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

        result = runner._run_nodes_parallel({"bad": failing}, {"x": 1})
        assert "bad" in result.get("_failed_nodes", [])

    def test_good_node_survives_sibling_failure(self):
        """A healthy node still contributes its result even if a sibling fails."""
        runner = ThreadPoolParallelRunner()

        result = runner._run_nodes_parallel(
            {
                "fail": lambda s: (_ for _ in ()).throw(ValueError("oops")),
                "good": lambda s: {"healthy": True},
            },
            {},
        )
        assert result.get("healthy") is True
        assert "fail" in result.get("_failed_nodes", [])

    def test_multiple_failures_all_recorded(self):
        """Multiple failing nodes all appear in _failed_nodes."""
        runner = ThreadPoolParallelRunner()

        nodes = {
            "a": lambda s: (_ for _ in ()).throw(ValueError("a")),
            "b": lambda s: (_ for _ in ()).throw(ValueError("b")),
        }
        result = runner._run_nodes_parallel(nodes, {})
        failed = result.get("_failed_nodes", [])
        assert "a" in failed
        assert "b" in failed


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
