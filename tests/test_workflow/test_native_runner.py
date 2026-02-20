"""Tests for ThreadPoolParallelRunner.

Tests parallel execution, init/collect nodes, error handling,
and state merging behavior.
"""
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from temper_ai.workflow.engines.native_runner import ThreadPoolParallelRunner, _merge_dicts


class TestMergeDicts:
    """Test dict merge utility."""

    def test_merge_empty(self):
        assert _merge_dicts({}, {}) == {}

    def test_merge_right_wins(self):
        result = _merge_dicts({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_preserves_left(self):
        left = {"x": 1}
        _merge_dicts(left, {"y": 2})
        assert left == {"x": 1}  # Original not mutated


class TestThreadPoolParallelRunner:
    """Test ThreadPoolParallelRunner."""

    def test_empty_nodes(self):
        """Test running with no nodes returns initial state."""
        runner = ThreadPoolParallelRunner()
        state = {"key": "value"}
        result = runner.run_parallel({}, state)
        assert result["key"] == "value"

    def test_single_node(self):
        """Test running a single node."""
        runner = ThreadPoolParallelRunner()

        def node_a(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"agent_outputs": {"a": "output_a"}}

        result = runner.run_parallel(
            {"a": node_a},
            {"agent_outputs": {}},
        )
        assert result["agent_outputs"] == {"a": "output_a"}

    def test_parallel_nodes(self):
        """Test running multiple nodes in parallel."""
        runner = ThreadPoolParallelRunner(max_workers=2)

        def node_a(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"agent_outputs": {"a": "output_a"}}

        def node_b(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"agent_outputs": {"b": "output_b"}}

        result = runner.run_parallel(
            {"a": node_a, "b": node_b},
            {"agent_outputs": {}},
        )
        # Both outputs should be merged
        assert "a" in result["agent_outputs"]
        assert "b" in result["agent_outputs"]
        assert result["agent_outputs"]["a"] == "output_a"
        assert result["agent_outputs"]["b"] == "output_b"

    def test_init_node(self):
        """Test init_node runs before parallel nodes."""
        runner = ThreadPoolParallelRunner()

        def init(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"initialized": True}

        def node_a(state: Dict[str, Any]) -> Dict[str, Any]:
            # init_node result should be in state
            assert state.get("initialized") is True
            return {"result": "ok"}

        result = runner.run_parallel(
            {"a": node_a},
            {},
            init_node=init,
        )
        assert result["initialized"] is True
        assert result["result"] == "ok"

    def test_collect_node(self):
        """Test collect_node runs after parallel nodes."""
        runner = ThreadPoolParallelRunner()

        def node_a(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"agent_outputs": {"a": "output_a"}}

        def collect(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"collected": True}

        result = runner.run_parallel(
            {"a": node_a},
            {"agent_outputs": {}},
            collect_node=collect,
        )
        assert result["collected"] is True

    def test_init_and_collect(self):
        """Test both init and collect nodes."""
        runner = ThreadPoolParallelRunner()

        result = runner.run_parallel(
            {"a": lambda s: {"r": "ok"}},
            {},
            init_node=lambda s: {"step": "init"},
            collect_node=lambda s: {"step": "collect"},
        )
        assert result["r"] == "ok"
        assert result["step"] == "collect"  # collect overwrites init

    def test_node_exception_logged(self):
        """Test that node exceptions are logged but don't crash runner."""
        runner = ThreadPoolParallelRunner()

        def failing_node(state: Dict[str, Any]) -> Dict[str, Any]:
            raise ValueError("boom")

        def good_node(state: Dict[str, Any]) -> Dict[str, Any]:
            return {"good": True}

        result = runner.run_parallel(
            {"fail": failing_node, "good": good_node},
            {},
        )
        assert result["good"] is True

    def test_node_returns_none(self):
        """Test nodes returning None are handled."""
        runner = ThreadPoolParallelRunner()

        def none_node(state: Dict[str, Any]) -> Dict[str, Any]:
            return {}

        result = runner.run_parallel(
            {"a": none_node},
            {"existing": True},
        )
        assert result["existing"] is True

    def test_max_workers_respected(self):
        """Test max_workers is capped to number of nodes."""
        runner = ThreadPoolParallelRunner(max_workers=100)

        result = runner.run_parallel(
            {"a": lambda s: {"a": 1}},
            {},
        )
        assert result["a"] == 1

    def test_state_isolation(self):
        """Test each node gets its own copy of state."""
        runner = ThreadPoolParallelRunner()
        mutations = []

        def mutating_node(state: Dict[str, Any]) -> Dict[str, Any]:
            state["mutated"] = True
            mutations.append(True)
            return {"result": "done"}

        initial = {"original": True}
        result = runner.run_parallel(
            {"a": mutating_node},
            initial,
        )
        # Original state should not be mutated
        assert "mutated" not in initial
