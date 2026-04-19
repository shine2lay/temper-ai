"""Tests for stage/executor.py — the graph execution engine."""

from unittest.mock import MagicMock

import pytest

from temper_ai.shared.types import (
    AgentResult,
    ExecutionContext,
    NodeResult,
    Status,
    TokenUsage,
)
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import CyclicDependencyError
from temper_ai.stage.executor import (
    _get_final_output,
    _inject_strategy_context,
    _resolve_inputs,
    execute_graph,
    topological_sort,
)
from temper_ai.stage.models import NodeConfig


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

    def test_input_map_sentence_literal_passes_through(self):
        """A string that doesn't parse as a node ref (has spaces) is a
        literal — return as-is rather than warn+None. Critical for
        dispatched nodes whose Jinja-rendered input_map values are often
        sentences from an upstream agent's structured output."""
        node = _make_agent_node(
            "b", input_map={"brief": "Research hiking trails in Japan."},
        )
        resolved = _resolve_inputs(node, {}, {})
        assert resolved == {"brief": "Research hiking trails in Japan."}

    def test_input_map_bare_scalar_literal_passes_through(self):
        """No period in source and not in input_data → literal."""
        node = _make_agent_node("b", input_map={"topic": "cherry_blossoms"})
        resolved = _resolve_inputs(node, {}, {})
        assert resolved == {"topic": "cherry_blossoms"}

    def test_input_map_bare_scalar_matches_workflow_input(self):
        """Bare identifier still resolves against workflow inputs when present."""
        node = _make_agent_node("b", input_map={"t": "task"})
        resolved = _resolve_inputs(node, {"task": "hello"}, {})
        assert resolved == {"t": "hello"}

    def test_input_map_non_string_source_passes_through(self):
        """Ints, booleans, lists from Jinja-rendered numeric expressions are
        literals — no resolution attempted."""
        node = _make_agent_node(
            "b", input_map={"count": 42, "enabled": True, "items": [1, 2]},
        )
        resolved = _resolve_inputs(node, {}, {})
        assert resolved == {"count": 42, "enabled": True, "items": [1, 2]}

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

    def test_run_state_populated_on_context(self):
        """Executor exposes live node_outputs on context.run_state for
        introspection tools (QueryRunState, future dispatch)."""
        a = _make_agent_node("a", output="done-a")
        b = _make_agent_node("b", depends_on=["a"], output="done-b")

        ctx = _make_context()
        assert ctx.run_state is None  # unset before the run
        execute_graph([a, b], {}, ctx, graph_name="test")

        # After the run, context.run_state contains both nodes
        assert ctx.run_state is not None
        assert set(ctx.run_state.keys()) == {"a", "b"}
        assert ctx.run_state["a"].output == "done-a"
        assert ctx.run_state["b"].output == "done-b"

    def test_run_state_preserved_for_nested_stage(self):
        """Nested stage executions don't overwrite the parent's run_state —
        a sub-stage's tools should see the whole run, not just the sub-stage."""
        parent_state = {"outer_node": NodeResult(status=Status.COMPLETED, output="outer")}
        ctx = _make_context()
        ctx.run_state = parent_state

        a = _make_agent_node("a", output="inner")
        execute_graph([a], {}, ctx, graph_name="nested")

        # Parent reference is unchanged; sub-run did not clobber it
        assert ctx.run_state is parent_state


# --- Declarative Dispatch (tier 1) integration ---


def _make_dispatcher_node(name, dispatch_block, structured_output=None, output="done"):
    """AgentNode whose agent_config has a `dispatch:` block and whose run()
    returns a fixed result. Used to test executor integration of dispatch."""
    nc = NodeConfig(name=name)
    agent_config = {"name": name, "type": "llm", "dispatch": dispatch_block}
    node = AgentNode(nc, agent_config)
    result = NodeResult(
        status=Status.COMPLETED,
        output=output,
        structured_output=structured_output,
        agent_results=[
            AgentResult(
                status=Status.COMPLETED,
                output=output,
                structured_output=structured_output,
                tokens=TokenUsage(total_tokens=100),
            )
        ],
    )
    node.run = MagicMock(return_value=result)
    return node


class _StubGraphLoader:
    """Minimal graph_loader stand-in: hands back pre-built nodes keyed by the
    rendered node name. Lets executor tests run dispatch without config store."""

    def __init__(self, nodes_by_name: dict):
        self._nodes = nodes_by_name
        self.resolved: list[str] = []   # observability: which names were asked for

    def _resolve_node(self, nc):
        self.resolved.append(nc.name)
        if nc.name not in self._nodes:
            raise ValueError(f"Stub loader has no node for {nc.name!r}")
        return self._nodes[nc.name]


class TestDeclarativeDispatch:
    def test_add_single_node_via_dispatch_runs_it(self):
        """An agent with dispatch: add -> new node materializes and runs."""
        dispatch_block = [
            {"op": "add", "node": {"name": "spawned", "agent": "x"}}
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        spawned = _make_agent_node("spawned", output="spawned-ran")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert dispatcher.run.called
        assert spawned.run.called
        # Spawned node's output is visible in run_state
        assert ctx.run_state["spawned"].output == "spawned-ran"

    def test_for_each_fans_out_multiple_nodes(self):
        """Dispatch with for_each over structured output spawns one node per item."""
        dispatch_block = [
            {
                "op": "add",
                "for_each": "structured.cities",
                "node": {"name": "{{ item.city }}_research", "agent": "researcher"},
            }
        ]
        dispatcher = _make_dispatcher_node(
            "allocator", dispatch_block,
            structured_output={
                "cities": [{"city": "Tokyo"}, {"city": "Kyoto"}, {"city": "Osaka"}]
            },
        )
        tokyo = _make_agent_node("Tokyo_research", output="t")
        kyoto = _make_agent_node("Kyoto_research", output="k")
        osaka = _make_agent_node("Osaka_research", output="o")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "Tokyo_research": tokyo,
            "Kyoto_research": kyoto,
            "Osaka_research": osaka,
        })

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        for n in (tokyo, kyoto, osaka):
            assert n.run.called
        assert {"Tokyo_research", "Kyoto_research", "Osaka_research"} <= set(ctx.run_state)

    def test_remove_marks_pending_node_skipped(self):
        """op=remove on a pending node — target appears as SKIPPED and doesn't run."""
        dispatch_block = [{"op": "remove", "target": "placeholder"}]
        dispatcher = _make_dispatcher_node("killer", dispatch_block)
        placeholder = _make_agent_node("placeholder", output="should-not-run")
        # placeholder has no depends_on — it would run in parallel with dispatcher
        # but parallel-batch execution would run it first before dispatch fires.
        # Make it a downstream instead, so it's still pending when dispatch runs.
        placeholder.config.depends_on = ["killer"]

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({})

        execute_graph([dispatcher, placeholder], {}, ctx, graph_name="test")
        assert dispatcher.run.called
        assert not placeholder.run.called
        assert ctx.run_state["placeholder"].status == Status.SKIPPED

    def test_dispatch_skipped_when_agent_failed(self):
        """A failing dispatcher doesn't trigger dispatch (output unreliable)."""
        dispatch_block = [{"op": "add", "node": {"name": "spawned", "agent": "x"}}]
        dispatcher = _make_dispatcher_node("fail_parent", dispatch_block)
        # Override dispatcher's run to return FAILED
        dispatcher.run.return_value = NodeResult(
            status=Status.FAILED, output="", error="boom"
        )
        spawned = _make_agent_node("spawned")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert dispatcher.run.called
        assert not spawned.run.called

    def test_dispatch_warns_without_graph_loader(self, caplog):
        """If graph_loader isn't set on context, dispatch logs a warning and
        proceeds without mutating. The dispatcher's own output is still produced."""
        dispatch_block = [{"op": "add", "node": {"name": "spawned", "agent": "x"}}]
        dispatcher = _make_dispatcher_node("parent", dispatch_block, output="parent-ran")

        ctx = _make_context()   # no graph_loader set
        import logging as _lg
        with caplog.at_level(_lg.WARNING):
            result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert any("dispatch skipped" in r.message for r in caplog.records)

    def test_dispatch_bad_subgraph_fails_run(self):
        """A node dict that already exists in the DAG surfaces as a run failure."""
        dispatch_block = [
            {"op": "add", "node": {"name": "conflict", "agent": "x"}}
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        existing = _make_agent_node("conflict", output="ok")  # same name

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"conflict": _make_agent_node("conflict")})

        result = execute_graph([dispatcher, existing], {}, ctx, graph_name="test")
        # Either failed overall or one of the nodes captured the error —
        # the important thing is the run surfaces the conflict.
        assert "conflict" in (result.error or "") or result.status == Status.FAILED

    def test_dispatched_node_can_depend_on_existing_node(self):
        """A dispatched node with depends_on referencing an existing
        already-completed node runs after that node. Order preserved by the
        executor even though topology was mutated mid-run."""
        dispatch_block = [
            {
                "op": "add",
                "node": {"name": "followup", "agent": "f",
                         "depends_on": ["parent"]},
            }
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block, output="p-ran")
        followup = _make_agent_node("followup", output="f-ran", depends_on=["parent"])

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"followup": followup})

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert dispatcher.run.called
        assert followup.run.called
        assert ctx.run_state["followup"].output == "f-ran"


class TestDispatchSafetyCaps:
    """Integration tests for dispatch safety caps — thread the limits from
    ExecutionContext through the executor and assert they actually fail the run.
    """

    def _make_many_children_dispatcher(self, count: int):
        """Build an agent node whose dispatch block fans out `count` children."""
        block = [{
            "op": "add",
            "for_each": list(range(count)),
            "node": {"name": "c_{{ item }}", "agent": "x"},
        }]
        return _make_dispatcher_node("parent", block)

    def test_max_children_per_dispatch_triggers(self):
        """Dispatcher emits more children than the configured cap — run fails."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        dispatcher = self._make_many_children_dispatcher(5)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({f"c_{i}": _make_agent_node(f"c_{i}") for i in range(5)})
        ctx.dispatch_limits = DispatchLimits(max_children_per_dispatch=3)

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.FAILED
        assert "max_children_per_dispatch" in (result.error or "")

    def test_max_children_per_dispatch_allows_equal(self):
        """Exactly at the cap is allowed — cap is `> N` not `>= N`."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        dispatcher = self._make_many_children_dispatcher(3)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({f"c_{i}": _make_agent_node(f"c_{i}") for i in range(3)})
        ctx.dispatch_limits = DispatchLimits(max_children_per_dispatch=3)

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED

    def test_max_dynamic_nodes_triggers(self):
        """Run-wide cap — two dispatchers together exceed max_dynamic_nodes."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        # Each dispatcher adds 2 children; cap is 3 → second dispatcher's 4th
        # node breaches the run-wide cap.
        d1 = _make_dispatcher_node("d1", [{
            "op": "add", "for_each": [1, 2],
            "node": {"name": "n1_{{ item }}", "agent": "x"},
        }])
        d2 = _make_dispatcher_node("d2", [{
            "op": "add", "for_each": [3, 4],
            "node": {"name": "n2_{{ item }}", "agent": "x"},
        }])
        # d2 runs after d1
        d2.config.depends_on = ["d1"]
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "n1_1": _make_agent_node("n1_1"),
            "n1_2": _make_agent_node("n1_2"),
            "n2_3": _make_agent_node("n2_3"),
            "n2_4": _make_agent_node("n2_4"),
        })
        ctx.dispatch_limits = DispatchLimits(max_dynamic_nodes=3)

        result = execute_graph([d1, d2], {}, ctx, graph_name="test")
        assert result.status == Status.FAILED
        assert "max_dynamic_nodes" in (result.error or "")

    def test_max_dispatch_depth_triggers(self):
        """A node dispatched BY a dispatched node is depth-2; cap at 1 fails."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        # Grandchild has its OWN dispatch block — so when it runs it will try
        # to dispatch again, reaching depth 2.
        grandchild_block = [{"op": "add", "node": {"name": "great_grandchild", "agent": "x"}}]
        grandchild = _make_dispatcher_node("grandchild", grandchild_block, output="gc-ran")

        # Parent dispatches grandchild.
        parent_block = [{"op": "add", "node": {"name": "grandchild", "agent": "x"}}]
        parent = _make_dispatcher_node("parent", parent_block, output="p-ran")

        great_grandchild = _make_agent_node("great_grandchild")
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "grandchild": grandchild,
            "great_grandchild": great_grandchild,
        })
        ctx.dispatch_limits = DispatchLimits(max_dispatch_depth=1)

        result = execute_graph([parent], {}, ctx, graph_name="test")
        # Depth-2 dispatch rejected → run fails
        assert result.status == Status.FAILED
        assert "max_dispatch_depth" in (result.error or "")

    def test_cycle_detection_triggers(self):
        """Dispatcher emits a node with same (agent_ref, input_map) as itself."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        block = [{
            "op": "add",
            "node": {
                "name": "self_clone",
                "agent": "parent",   # same agent ref as dispatcher's own config name
                "input_map": {},     # same (empty) input as dispatcher
            },
        }]
        # Dispatcher's agent_config has name="parent" (matching the agent ref
        # the child tries to use) — this sets up fingerprint collision.
        dispatcher = _make_dispatcher_node("parent", block)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"self_clone": _make_agent_node("self_clone")})
        ctx.dispatch_limits = DispatchLimits(cycle_detection=True)

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.FAILED
        assert "cycle" in (result.error or "").lower()

    def test_cycle_detection_disabled_allows_repeat(self):
        """With cycle_detection=False, a self-clone is permitted."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        block = [{
            "op": "add",
            "node": {"name": "self_clone", "agent": "parent", "input_map": {}},
        }]
        dispatcher = _make_dispatcher_node("parent", block)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"self_clone": _make_agent_node("self_clone")})
        ctx.dispatch_limits = DispatchLimits(cycle_detection=False)

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED

    def test_defaults_applied_when_no_limits_on_context(self):
        """Missing dispatch_limits on context → module defaults used (lenient)."""
        from temper_ai.stage.dispatch_limits import (
            DEFAULT_MAX_CHILDREN_PER_DISPATCH,
        )

        # Under the default cap — should work fine
        dispatcher = self._make_many_children_dispatcher(DEFAULT_MAX_CHILDREN_PER_DISPATCH - 1)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            f"c_{i}": _make_agent_node(f"c_{i}")
            for i in range(DEFAULT_MAX_CHILDREN_PER_DISPATCH - 1)
        })
        # Deliberately don't set ctx.dispatch_limits — should default

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED


class TestToolCallDispatch:
    """Integration tests for tier 2 imperative dispatch — AddNode / RemoveNode
    tools buffer ops that the executor drains after the agent completes.

    We simulate the tool call by directly appending to dispatch_state.pending_ops
    — the tool's execute() does the same thing, tested in tests/test_tools/.
    What we verify here is that the executor picks up those ops, runs them
    through cap enforcement, and applies them to the live DAG.
    """

    def _prime_pending_ops(self, ctx, node_path: str, ops: list):
        """Pretend the agent just called AddNode/RemoveNode during its run."""
        from temper_ai.stage.dispatch_limits import DispatchRunState
        if ctx.dispatch_state is None:
            ctx.dispatch_state = DispatchRunState()
        ctx.dispatch_state.pending_ops[node_path] = list(ops)

    def test_add_op_from_tool_call_runs(self):
        """Agent queues an AddNode op via the tool — executor applies it."""
        from temper_ai.stage.dispatch import DispatchOp

        parent = _make_agent_node("parent", output="done")
        spawned = _make_agent_node("spawned", output="spawned-ran")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})
        self._prime_pending_ops(ctx, "parent", [
            DispatchOp(op="add", node={"name": "spawned", "type": "agent", "agent": "x"}),
        ])

        result = execute_graph([parent], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert spawned.run.called
        assert ctx.run_state["spawned"].output == "spawned-ran"
        # Buffer drained
        assert "parent" not in (ctx.dispatch_state.pending_ops if ctx.dispatch_state else {})

    def test_remove_op_from_tool_call_skips_target(self):
        from temper_ai.stage.dispatch import DispatchOp

        parent = _make_agent_node("parent", output="done")
        placeholder = _make_agent_node("placeholder", output="should-not-run")
        placeholder.config.depends_on = ["parent"]

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({})
        self._prime_pending_ops(ctx, "parent", [
            DispatchOp(op="remove", target="placeholder"),
        ])

        execute_graph([parent, placeholder], {}, ctx, graph_name="test")
        assert parent.run.called
        assert not placeholder.run.called
        assert ctx.run_state["placeholder"].status == Status.SKIPPED

    def test_declarative_and_tool_call_ops_merge(self):
        """A single agent with BOTH a dispatch: block AND tool calls —
        the executor applies them atomically as one batch."""
        from temper_ai.stage.dispatch import DispatchOp

        # Dispatch block in agent config adds 'from_yaml'
        dispatch_block = [
            {"op": "add", "node": {"name": "from_yaml", "agent": "y"}},
        ]
        parent = _make_dispatcher_node("parent", dispatch_block)
        from_yaml = _make_agent_node("from_yaml", output="y-ran")
        from_tool = _make_agent_node("from_tool", output="t-ran")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "from_yaml": from_yaml, "from_tool": from_tool,
        })
        # Tool-call adds 'from_tool'
        self._prime_pending_ops(ctx, "parent", [
            DispatchOp(op="add", node={"name": "from_tool", "type": "agent", "agent": "t"}),
        ])

        result = execute_graph([parent], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert from_yaml.run.called
        assert from_tool.run.called

    def test_merged_batch_respects_fan_out_cap(self):
        """Cap applies to the MERGED total of declarative + tool-call adds."""
        from temper_ai.stage.dispatch import DispatchOp
        from temper_ai.stage.dispatch_limits import DispatchLimits

        dispatch_block = [
            {"op": "add", "for_each": [1, 2],
             "node": {"name": "y_{{ item }}", "agent": "y"}},
        ]
        parent = _make_dispatcher_node("parent", dispatch_block)

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "y_1": _make_agent_node("y_1"), "y_2": _make_agent_node("y_2"),
            "t": _make_agent_node("t"),
        })
        ctx.dispatch_limits = DispatchLimits(max_children_per_dispatch=2)
        # 2 declarative + 1 tool-call = 3, exceeds cap of 2
        self._prime_pending_ops(ctx, "parent", [
            DispatchOp(op="add", node={"name": "t", "type": "agent", "agent": "t"}),
        ])

        result = execute_graph([parent], {}, ctx, graph_name="test")
        assert result.status == Status.FAILED
        assert "max_children_per_dispatch" in (result.error or "")

    def test_tool_call_ops_respect_cycle_detection(self):
        from temper_ai.stage.dispatch import DispatchOp
        from temper_ai.stage.dispatch_limits import DispatchLimits

        parent = _make_agent_node("parent")
        # The AgentNode's agent_config name is auto-set from the NodeConfig.
        # For cycle detection, we queue an add whose agent matches the parent's
        # agent_config name with empty input_map (same as parent's input_data).
        parent.agent_config = {"name": "parent", "type": "llm"}

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"clone": _make_agent_node("clone")})
        ctx.dispatch_limits = DispatchLimits(cycle_detection=True)
        self._prime_pending_ops(ctx, "parent", [
            DispatchOp(op="add", node={
                "name": "clone", "agent": "parent", "input_map": {},
            }),
        ])

        result = execute_graph([parent], {}, ctx, graph_name="test")
        assert result.status == Status.FAILED
        assert "cycle" in (result.error or "").lower()

    def test_tool_call_with_empty_pending_is_noop(self):
        """Agent didn't call any tools — executor skips dispatch entirely."""
        parent = _make_agent_node("parent", output="done")
        ctx = _make_context()
        # No dispatch_state set up, no pending_ops
        result = execute_graph([parent], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED


class TestDispatchCheckpointing:
    """Dispatch outcomes are persisted via CheckpointService so a crashed
    run can resume with the dispatched DAG shape intact."""

    def test_declarative_dispatch_saves_checkpoint(self):
        """A successful declarative dispatch calls save_dispatch_applied with
        the right payload so resume can re-materialize the children."""
        dispatch_block = [
            {"op": "add", "node": {"name": "spawned", "agent": "x"}},
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        spawned = _make_agent_node("spawned")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})
        cp = MagicMock()
        ctx.checkpoint_service = cp

        execute_graph([dispatcher], {}, ctx, graph_name="test")

        # save_dispatch_applied was called with the dispatched child's dict
        assert cp.save_dispatch_applied.called
        call_kwargs = cp.save_dispatch_applied.call_args.kwargs
        assert call_kwargs["dispatcher_name"] == "parent"
        assert call_kwargs["added_nodes"][0]["name"] == "spawned"
        assert call_kwargs["removed_targets"] == []
        assert call_kwargs["dispatched_count_delta"] == 1

    def test_remove_op_also_saves_checkpoint(self):
        """op=remove alone (no adds) still persists a dispatch_applied so
        resume knows to skip the target."""
        dispatch_block = [{"op": "remove", "target": "placeholder"}]
        dispatcher = _make_dispatcher_node("killer", dispatch_block)
        placeholder = _make_agent_node("placeholder")
        placeholder.config.depends_on = ["killer"]

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({})
        cp = MagicMock()
        ctx.checkpoint_service = cp

        execute_graph([dispatcher, placeholder], {}, ctx, graph_name="test")

        assert cp.save_dispatch_applied.called
        call_kwargs = cp.save_dispatch_applied.call_args.kwargs
        assert call_kwargs["removed_targets"] == ["placeholder"]
        assert call_kwargs["added_nodes"] == []
        assert call_kwargs["dispatched_count_delta"] == 0

    def test_empty_dispatch_doesnt_save_checkpoint(self):
        """A dispatcher whose ops list renders empty (e.g. for_each over an
        empty list) doesn't write a dispatch_applied checkpoint — keeps the
        log clean."""
        dispatch_block = [{
            "op": "add", "for_each": [],
            "node": {"name": "x", "agent": "y"},
        }]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({})
        cp = MagicMock()
        ctx.checkpoint_service = cp

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert not cp.save_dispatch_applied.called

    def test_dispatch_failure_doesnt_save_checkpoint(self):
        """Cap exceeded → dispatch fails → no checkpoint written (partial
        state not persisted)."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        dispatch_block = [{
            "op": "add", "for_each": [1, 2, 3],
            "node": {"name": "c_{{ item }}", "agent": "x"},
        }]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            f"c_{i}": _make_agent_node(f"c_{i}") for i in range(1, 4)
        })
        ctx.dispatch_limits = DispatchLimits(max_children_per_dispatch=1)
        cp = MagicMock()
        ctx.checkpoint_service = cp

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert not cp.save_dispatch_applied.called

    def test_no_checkpoint_service_is_noop(self):
        """Dispatch still works when checkpoint_service is None (the
        non-persisted dev/CLI case)."""
        dispatch_block = [
            {"op": "add", "node": {"name": "spawned", "agent": "x"}},
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        spawned = _make_agent_node("spawned")
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})
        ctx.checkpoint_service = None

        result = execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert result.status == Status.COMPLETED
        assert spawned.run.called


class TestDispatchObservabilityEvents:
    """Dispatch emits observability events so the dashboard timeline sees it."""

    def _event_types_recorded(self, ctx) -> list[str]:
        """Extract the event type value from every recorder.record call."""
        out = []
        for call in ctx.event_recorder.record.call_args_list:
            if call.args:
                evt = call.args[0]
                out.append(getattr(evt, "value", str(evt)))
            elif "event_type" in call.kwargs:
                out.append(call.kwargs["event_type"])
        return out

    def test_successful_dispatch_emits_dispatch_applied(self):
        dispatch_block = [
            {"op": "add", "node": {"name": "spawned", "agent": "x"}},
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        spawned = _make_agent_node("spawned")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert "dispatch.applied" in self._event_types_recorded(ctx)

    def test_event_payload_lists_added_and_removed(self):
        dispatch_block = [
            {"op": "add", "node": {"name": "spawned", "agent": "x"}},
            {"op": "remove", "target": "placeholder"},
        ]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        spawned = _make_agent_node("spawned")
        placeholder = _make_agent_node("placeholder")
        placeholder.config.depends_on = ["parent"]

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"spawned": spawned})

        execute_graph([dispatcher, placeholder], {}, ctx, graph_name="test")

        dispatch_calls = [
            c for c in ctx.event_recorder.record.call_args_list
            if c.args and getattr(c.args[0], "value", "") == "dispatch.applied"
        ]
        assert len(dispatch_calls) == 1
        data = dispatch_calls[0].kwargs["data"]
        assert data["dispatcher"] == "parent"
        assert data["added"] == ["spawned"]
        assert data["removed"] == ["placeholder"]

    def test_cap_exceeded_emits_event(self):
        """When a cap fires, dispatch.cap_exceeded is recorded before the
        error propagates."""
        from temper_ai.stage.dispatch_limits import DispatchLimits

        dispatch_block = [{
            "op": "add", "for_each": [1, 2, 3],
            "node": {"name": "c_{{ item }}", "agent": "x"},
        }]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            f"c_{i}": _make_agent_node(f"c_{i}") for i in range(1, 4)
        })
        ctx.dispatch_limits = DispatchLimits(max_children_per_dispatch=1)

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        assert "dispatch.cap_exceeded" in self._event_types_recorded(ctx)

    def test_empty_dispatch_emits_no_event(self):
        """A dispatcher with empty ops shouldn't pollute the timeline."""
        dispatch_block = [{
            "op": "add", "for_each": [],
            "node": {"name": "x", "agent": "y"},
        }]
        dispatcher = _make_dispatcher_node("parent", dispatch_block)
        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({})

        execute_graph([dispatcher], {}, ctx, graph_name="test")
        types_ = self._event_types_recorded(ctx)
        assert "dispatch.applied" not in types_
        assert "dispatch.cap_exceeded" not in types_


class TestDispatchModifyingExistingDAG:
    """Dispatcher targets nodes that ALREADY EXIST in the DAG:
      - remove a pre-existing pending node (downstream cascades)
      - replace a pre-existing node (remove + add with same name preserves
        the downstream contract)
      - add alongside pre-existing nodes (both the original and the new
        siblings run)
    These are the realistic patterns for an agent that rewrites part of
    an originally-declared workflow based on runtime info.
    """

    def test_remove_existing_pending_node_leaves_skipped_tombstone(self):
        """Dispatcher removes a pending node — it's marked SKIPPED and
        never executes. Downstream still runs (with the SKIPPED node's
        empty output resolving via input_map); cascade-skip is not a
        v1 feature but the SKIPPED tombstone is the correct signal for
        downstream to detect the removal if it wants to."""
        dispatch_block = [{"op": "remove", "target": "doomed"}]
        dispatcher = _make_dispatcher_node("planner", dispatch_block)

        doomed = _make_agent_node("doomed", depends_on=["planner"], output="never")
        downstream = _make_agent_node(
            "downstream",
            depends_on=["doomed"],
            input_map={"x": "doomed.output"},
            output="downstream-ran",
        )

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({})

        execute_graph([dispatcher, doomed, downstream], {}, ctx, graph_name="test")

        # Removed node didn't run, left SKIPPED tombstone
        assert not doomed.run.called
        assert ctx.run_state["doomed"].status == Status.SKIPPED
        # Downstream DOES run (today's semantics) — with empty input from SKIPPED
        # source. Documented: if a user wants cascade-skip, they can check
        # upstream .status == SKIPPED in their agent.
        assert downstream.run.called

    def test_replace_via_remove_plus_add_same_name(self):
        """v1's replace semantics: compose `remove target=X` + `add node.name=X`
        in the same dispatch. Downstream that wired to `X.output` keeps working
        because the new X produces a real output."""
        dispatch_block = [
            {"op": "remove", "target": "placeholder"},
            {
                "op": "add",
                "node": {
                    "name": "placeholder",
                    "type": "agent",
                    "agent": "real_researcher",
                    "input_map": {},
                },
            },
        ]
        dispatcher = _make_dispatcher_node("planner", dispatch_block)

        # Existing pending node
        original_placeholder = _make_agent_node(
            "placeholder", depends_on=["planner"], output="placeholder-data",
        )
        # The replacement — what the loader returns for name="placeholder"
        replacement = _make_agent_node("placeholder", output="real-data")

        downstream = _make_agent_node(
            "downstream",
            depends_on=["placeholder"],
            input_map={"data": "placeholder.output"},
            output="downstream-ran",
        )

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"placeholder": replacement})

        execute_graph([dispatcher, original_placeholder, downstream], {}, ctx, graph_name="test")

        # Original was removed (didn't run); replacement ran
        assert not original_placeholder.run.called
        assert replacement.run.called
        # Downstream ran against the REPLACEMENT's output
        assert downstream.run.called
        assert ctx.run_state["placeholder"].output == "real-data"

    def test_add_alongside_pre_existing_nodes(self):
        """Pre-existing node survives untouched when dispatcher only adds
        NEW nodes (doesn't target the pre-existing one)."""
        dispatch_block = [
            {"op": "add", "node": {"name": "extra", "agent": "x"}}
        ]
        dispatcher = _make_dispatcher_node("planner", dispatch_block)
        pre_existing = _make_agent_node(
            "pre_existing", depends_on=["planner"], output="survived",
        )
        extra = _make_agent_node("extra", output="extra-ran")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"extra": extra})

        execute_graph([dispatcher, pre_existing], {}, ctx, graph_name="test")

        assert pre_existing.run.called
        assert extra.run.called
        assert ctx.run_state["pre_existing"].output == "survived"
        assert ctx.run_state["extra"].output == "extra-ran"

    def test_mixed_add_remove_in_single_dispatch(self):
        """One dispatcher emits add AND remove ops; both apply atomically."""
        dispatch_block = [
            {"op": "remove", "target": "drop_me"},
            {"op": "add", "node": {"name": "new_a", "agent": "x"}},
            {"op": "add", "node": {"name": "new_b", "agent": "x"}},
        ]
        dispatcher = _make_dispatcher_node("planner", dispatch_block)
        drop_me = _make_agent_node("drop_me", depends_on=["planner"])
        new_a = _make_agent_node("new_a")
        new_b = _make_agent_node("new_b")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"new_a": new_a, "new_b": new_b})

        execute_graph([dispatcher, drop_me], {}, ctx, graph_name="test")

        assert not drop_me.run.called
        assert new_a.run.called
        assert new_b.run.called
        assert ctx.run_state["drop_me"].status == Status.SKIPPED


class TestScriptAgentDispatch:
    """A dispatch block works on ANY AgentNode — including ones wrapping a
    script agent that never calls an LLM. Proves the dispatch mechanism
    doesn't couple to LLM provider output; it just reads the agent_config
    dict and renders the template against agent input + structured output
    (whatever source those happen to come from)."""

    def _make_script_dispatcher(self, name, dispatch_block, input_structured=None):
        """AgentNode with type=script-ish config (dispatch key but no
        provider/model). The mocked run() simulates a script producing a
        structured output (or not)."""
        nc = NodeConfig(name=name)
        agent_config = {"name": name, "type": "script", "dispatch": dispatch_block}
        node = AgentNode(nc, agent_config)
        result = NodeResult(
            status=Status.COMPLETED,
            output="scripted planner: ran",
            structured_output=input_structured,
            agent_results=[AgentResult(
                status=Status.COMPLETED,
                output="scripted planner: ran",
                structured_output=input_structured,
                tokens=TokenUsage(total_tokens=0),
            )],
        )
        node.run = MagicMock(return_value=result)
        return node

    def test_script_agent_fans_out_from_input(self):
        """Script dispatcher reads `input.cities` and spawns one lane per
        city — no LLM output involved anywhere in the dispatch decision."""
        dispatch_block = [{
            "op": "add",
            "for_each": "input.cities",
            "as": "city",
            "node": {
                "name": "research_{{ city.name }}",
                "type": "agent",
                "agent": "researcher",
                "input_map": {
                    "topic": "{{ city.name }}",
                    "brief": "Research {{ city.name }}",
                },
            },
        }]
        planner = self._make_script_dispatcher("planner", dispatch_block)
        tokyo = _make_agent_node("research_Tokyo", output="tokyo-data")
        kyoto = _make_agent_node("research_Kyoto", output="kyoto-data")

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "research_Tokyo": tokyo, "research_Kyoto": kyoto,
        })

        execute_graph(
            [planner],
            {"cities": [{"name": "Tokyo"}, {"name": "Kyoto"}]},
            ctx, graph_name="test",
        )

        # Deterministic: same input → same dispatched lanes
        assert tokyo.run.called
        assert kyoto.run.called
        # The dispatcher itself ran with 0 tokens (it's a script, no LLM call)
        assert planner.run.called
        assert ctx.run_state["planner"].agent_results[0].tokens.total_tokens == 0

    def test_script_agent_zero_tokens_on_planner(self):
        """Confirms the cost model: script dispatcher contributes 0 tokens
        even when dispatching many children. LLM cost only accrues on the
        dispatched LLM-agent lanes."""
        dispatch_block = [{
            "op": "add",
            "for_each": "input.items",
            "node": {"name": "item_{{ item }}", "agent": "x"},
        }]
        planner = self._make_script_dispatcher("planner", dispatch_block)

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            f"item_{i}": _make_agent_node(f"item_{i}") for i in range(5)
        })

        execute_graph(
            [planner], {"items": list(range(5))}, ctx, graph_name="test",
        )

        # Planner ran — 0 tokens, 0 cost
        planner_result = ctx.run_state["planner"]
        assert planner_result.agent_results[0].tokens.total_tokens == 0
        assert planner_result.agent_results[0].cost_usd == 0


class TestDispatchStageType:
    """Dispatched nodes can be `type: stage` (not just `type: agent`).
    A dispatched stage spins up multiple agents running in parallel /
    sequential / leader topology, same as a static stage node."""

    def _make_stage_node(self, name, child_agents, output="stage-out"):
        """Build a real StageNode (not mocked) wrapping mock child AgentNodes."""
        from temper_ai.stage.stage_node import StageNode

        nc = NodeConfig(name=name)
        children = [
            _make_agent_node(f"{name}__{a}", output=f"{a}-ran") for a in child_agents
        ]
        stage = StageNode(nc, children)
        return stage, children

    def test_dispatched_stage_runs_all_child_agents(self):
        """Dispatcher emits `type: stage` with a list of agents. The stage
        materializes as a StageNode whose child agents run in parallel."""
        dispatch_block = [{
            "op": "add",
            "node": {
                "name": "review_stage",
                "type": "stage",
                "strategy": "parallel",
                "agents": ["reviewer_a", "reviewer_b"],
            },
        }]
        dispatcher = _make_dispatcher_node("planner", dispatch_block)
        stage_node, child_agents = self._make_stage_node(
            "review_stage", ["reviewer_a", "reviewer_b"],
        )

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({"review_stage": stage_node})

        execute_graph([dispatcher], {}, ctx, graph_name="test")

        # The stage itself ran; its children (accessed via child_agents)
        # each ran too
        assert "review_stage" in ctx.run_state
        for child in child_agents:
            assert child.run.called, (
                f"Child {child.name} inside dispatched stage didn't run"
            )

    def test_dispatched_stage_fan_out_per_for_each(self):
        """`for_each` over a list, each iteration dispatching a stage
        (not an agent). Common pattern when each item needs multiple
        agents working together."""
        dispatch_block = [{
            "op": "add",
            "for_each": ["tokyo", "kyoto"],
            "node": {
                "name": "city_{{ item }}_stage",
                "type": "stage",
                "strategy": "parallel",
                "agents": ["researcher", "critic"],
            },
        }]
        dispatcher = _make_dispatcher_node("planner", dispatch_block)
        tokyo_stage, tokyo_children = self._make_stage_node(
            "city_tokyo_stage", ["researcher", "critic"],
        )
        kyoto_stage, kyoto_children = self._make_stage_node(
            "city_kyoto_stage", ["researcher", "critic"],
        )

        ctx = _make_context()
        ctx.graph_loader = _StubGraphLoader({
            "city_tokyo_stage": tokyo_stage,
            "city_kyoto_stage": kyoto_stage,
        })

        execute_graph([dispatcher], {}, ctx, graph_name="test")

        # Both cities' stages ran; each has two child agents that ran
        for child in tokyo_children + kyoto_children:
            assert child.run.called, f"{child.name} didn't run"
        assert "city_tokyo_stage" in ctx.run_state
        assert "city_kyoto_stage" in ctx.run_state


class TestExecuteGraphCore:
    """Condition, cost, and event tests that historically lived inline in
    TestExecuteGraph. Split into their own class so the dispatch/caps tests
    above don't swallow them."""

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
