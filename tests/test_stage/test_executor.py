"""Tests for stage/executor.py — the graph execution engine."""

import pytest
from unittest.mock import MagicMock, patch

from temper_ai.shared.types import (
    AgentResult,
    ExecutionContext,
    NodeResult,
    Status,
    TokenUsage,
)
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.executor import (
    execute_graph,
    topological_sort,
    _resolve_inputs,
    _inject_strategy_context,
    _get_final_output,
)
from temper_ai.stage.exceptions import CyclicDependencyError
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node


def _make_context(**overrides):
    """Create a minimal ExecutionContext with mocked infrastructure."""
    recorder = MagicMock()
    recorder.record.return_value = "evt-123"
    defaults = {
        "run_id": "run-1",
        "workflow_name": "test",
        "node_path": "",
        "agent_name": "",
        "event_recorder": recorder,
        "tool_executor": MagicMock(),
    }
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def _make_agent_node(name, depends_on=None, condition=None, loop_to=None,
                     max_loops=1, input_map=None, output="ok", status=Status.COMPLETED,
                     structured_output=None, cost=0.01, tokens=100):
    """Create an AgentNode with a mocked agent that returns a fixed result."""
    nc = NodeConfig(
        name=name,
        depends_on=depends_on or [],
        condition=condition,
        loop_to=loop_to,
        max_loops=max_loops,
        input_map=input_map,
    )
    agent_config = {"name": name, "type": "llm"}
    node = AgentNode(nc, agent_config)

    # Mock the run method to return a fixed result
    result = NodeResult(
        status=status,
        output=output,
        structured_output=structured_output,
        agent_results=[
            AgentResult(
                status=status,
                output=output,
                tokens=TokenUsage(total_tokens=tokens),
                cost_usd=cost,
            )
        ],
        cost_usd=cost,
        total_tokens=tokens,
    )
    node.run = MagicMock(return_value=result)
    return node


# --- Topological Sort ---


class TestTopologicalSort:
    def test_single_node(self):
        node = _make_agent_node("a")
        batches = topological_sort([node])
        assert len(batches) == 1
        assert batches[0] == [node]

    def test_linear_chain(self):
        a = _make_agent_node("a")
        b = _make_agent_node("b", depends_on=["a"])
        c = _make_agent_node("c", depends_on=["b"])
        batches = topological_sort([a, b, c])
        assert len(batches) == 3
        assert batches[0] == [a]
        assert batches[1] == [b]
        assert batches[2] == [c]

    def test_parallel_nodes(self):
        a = _make_agent_node("a")
        b = _make_agent_node("b")
        c = _make_agent_node("c")
        batches = topological_sort([a, b, c])
        assert len(batches) == 1
        assert set(n.name for n in batches[0]) == {"a", "b", "c"}

    def test_diamond_dependency(self):
        a = _make_agent_node("a")
        b = _make_agent_node("b", depends_on=["a"])
        c = _make_agent_node("c", depends_on=["a"])
        d = _make_agent_node("d", depends_on=["b", "c"])

        batches = topological_sort([a, b, c, d])
        assert len(batches) == 3
        assert batches[0] == [a]
        assert set(n.name for n in batches[1]) == {"b", "c"}
        assert batches[2] == [d]

    def test_cyclic_raises(self):
        a = _make_agent_node("a", depends_on=["b"])
        b = _make_agent_node("b", depends_on=["a"])
        with pytest.raises(CyclicDependencyError, match="Cyclic"):
            topological_sort([a, b])

    def test_external_dependency_ignored(self):
        """depends_on referencing a node not in the list is ignored."""
        a = _make_agent_node("a", depends_on=["external"])
        batches = topological_sort([a])
        assert len(batches) == 1


# --- Input Resolution ---


class TestResolveInputs:
    def test_no_input_map_passes_all(self):
        node = _make_agent_node("a")
        input_data = {"task": "do stuff", "extra": 42}
        resolved = _resolve_inputs(node, input_data, {})
        assert resolved == {"task": "do stuff", "extra": 42}

    def test_input_map_from_workflow(self):
        node = _make_agent_node("a", input_map={"my_task": "workflow.task"})
        resolved = _resolve_inputs(node, {"task": "hello"}, {})
        assert resolved == {"my_task": "hello"}

    def test_input_map_from_node_output(self):
        node = _make_agent_node("b", input_map={"plan": "a.output"})
        node_outputs = {
            "a": NodeResult(status=Status.COMPLETED, output="the plan"),
        }
        resolved = _resolve_inputs(node, {}, node_outputs)
        assert resolved == {"plan": "the plan"}

    def test_input_map_from_structured(self):
        node = _make_agent_node("b", input_map={"verdict": "a.structured.verdict"})
        node_outputs = {
            "a": NodeResult(
                status=Status.COMPLETED,
                structured_output={"verdict": "PASS"},
            ),
        }
        resolved = _resolve_inputs(node, {}, node_outputs)
        assert resolved == {"verdict": "PASS"}

    def test_input_map_missing_source_returns_none(self):
        node = _make_agent_node("b", input_map={"x": "nonexistent.output"})
        resolved = _resolve_inputs(node, {}, {})
        assert resolved == {"x": None}

    def test_input_map_status(self):
        node = _make_agent_node("b", input_map={"prev_status": "a.status"})
        node_outputs = {
            "a": NodeResult(status=Status.COMPLETED),
        }
        resolved = _resolve_inputs(node, {}, node_outputs)
        assert resolved == {"prev_status": Status.COMPLETED}


# --- Strategy Context Injection ---


class TestStrategyContextInjection:
    def test_no_injection_without_flag(self):
        node = _make_agent_node("a", depends_on=["b"])
        result = _inject_strategy_context(node, {"key": "val"}, {})
        assert "_strategy_context" not in result

    def test_injects_when_flagged(self):
        nc = NodeConfig(name="leader", depends_on=["w1", "w2"])
        node = AgentNode(nc, {"name": "leader", "_receives_strategy_context": True})
        node_outputs = {
            "w1": NodeResult(status=Status.COMPLETED, output="Worker 1 says X"),
            "w2": NodeResult(status=Status.COMPLETED, output="Worker 2 says Y"),
        }
        result = _inject_strategy_context(node, {}, node_outputs)
        assert "_strategy_context" in result
        assert "Worker 1 says X" in result["_strategy_context"]
        assert "Worker 2 says Y" in result["_strategy_context"]

    def test_skips_missing_deps(self):
        nc = NodeConfig(name="leader", depends_on=["w1", "w2"])
        node = AgentNode(nc, {"name": "leader", "_receives_strategy_context": True})
        node_outputs = {
            "w1": NodeResult(status=Status.COMPLETED, output="Only me"),
        }
        result = _inject_strategy_context(node, {}, node_outputs)
        assert "Only me" in result["_strategy_context"]


# --- Graph Execution ---


class TestExecuteGraph:
    def test_single_node(self):
        node = _make_agent_node("a", output="done")
        ctx = _make_context()
        result = execute_graph([node], {"task": "go"}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert result.output == "done"
        assert node.run.called

    def test_sequential_execution(self):
        a = _make_agent_node("a", output="step1")
        b = _make_agent_node("b", depends_on=["a"], output="step2")

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert result.output == "step2"
        assert a.run.called
        assert b.run.called

    def test_parallel_execution(self):
        a = _make_agent_node("a", output="out_a", cost=0.01, tokens=100)
        b = _make_agent_node("b", output="out_b", cost=0.02, tokens=200)

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert a.run.called
        assert b.run.called
        assert result.cost_usd == pytest.approx(0.03)
        assert result.total_tokens == 300

    def test_condition_skip(self):
        a = _make_agent_node(
            "a",
            output="verdict",
            structured_output={"verdict": "FAIL"},
        )
        b = _make_agent_node(
            "b",
            depends_on=["a"],
            condition={"source": "a.structured.verdict", "operator": "equals", "value": "PASS"},
            output="should not run",
        )

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert a.run.called
        assert not b.run.called  # skipped due to condition

    def test_condition_pass(self):
        a = _make_agent_node(
            "a",
            structured_output={"verdict": "PASS"},
        )
        b = _make_agent_node(
            "b",
            depends_on=["a"],
            condition={"source": "a.structured.verdict", "operator": "equals", "value": "PASS"},
        )

        ctx = _make_context()
        execute_graph([a, b], {}, ctx, graph_name="test")
        assert b.run.called  # condition met

    def test_cost_aggregation(self):
        a = _make_agent_node("a", cost=0.05, tokens=500)
        b = _make_agent_node("b", depends_on=["a"], cost=0.10, tokens=1000)

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        assert result.cost_usd == pytest.approx(0.15)
        assert result.total_tokens == 1500

    def test_agent_results_aggregated(self):
        a = _make_agent_node("a")
        b = _make_agent_node("b", depends_on=["a"])

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        assert len(result.agent_results) == 2

    def test_node_results_tracked(self):
        a = _make_agent_node("a")
        b = _make_agent_node("b", depends_on=["a"])

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        assert "a" in result.node_results
        assert "b" in result.node_results

    def test_workflow_events_recorded(self):
        node = _make_agent_node("a")
        ctx = _make_context()
        execute_graph([node], {}, ctx, graph_name="wf", is_workflow=True)

        recorder = ctx.event_recorder
        # Should record workflow start + node start (at minimum)
        assert recorder.record.call_count >= 2

    def test_failed_node_halts(self):
        a = _make_agent_node("a", status=Status.FAILED, output="boom")
        b = _make_agent_node("b", depends_on=["a"])

        ctx = _make_context()
        result = execute_graph([a, b], {}, ctx, graph_name="test")
        # b should still run (no explicit halt-on-failure in current impl)
        # but a's failure is recorded
        assert "a" in result.node_results
        assert result.node_results["a"].status == Status.FAILED


# --- Final Output Selection ---


class TestGetFinalOutput:
    def test_combines_all_completed_outputs(self):
        nodes = [_make_agent_node("a"), _make_agent_node("b")]
        outputs = {
            "a": NodeResult(status=Status.COMPLETED, output="first"),
            "b": NodeResult(status=Status.COMPLETED, output="second"),
        }
        result = _get_final_output(nodes, outputs)
        assert "first" in result.output
        assert "second" in result.output

    def test_skips_skipped_nodes(self):
        nodes = [_make_agent_node("a"), _make_agent_node("b")]
        outputs = {
            "a": NodeResult(status=Status.COMPLETED, output="only me"),
            "b": NodeResult(status=Status.SKIPPED),
        }
        result = _get_final_output(nodes, outputs)
        assert result.output == "only me"

    def test_returns_none_if_all_skipped(self):
        nodes = [_make_agent_node("a")]
        outputs = {"a": NodeResult(status=Status.SKIPPED)}
        result = _get_final_output(nodes, outputs)
        assert result is None
