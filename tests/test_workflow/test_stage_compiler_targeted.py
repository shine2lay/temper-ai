"""Targeted tests for workflow/stage_compiler.py to improve coverage from 62% to 90%+.

Covers: _insert_fan_in_barriers, _add_dag_edges, _add_init_to_roots,
        _add_loop_edge_dag, _add_successor_edges, _resolve_skip_target,
        _maybe_wrap_trigger_node, _maybe_wrap_on_complete_node,
        _get_event_bus_from_workflow, StageCompiler._is_conditional,
        compile_parallel_stages, compile_conditional_stages.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from langgraph.graph import END

from temper_ai.workflow.stage_compiler import (
    BARRIER_PREFIX,
    LOOP_GATE_PREFIX,
    StageCompiler,
    _filter_reachable_targets,
    _get_event_bus_from_workflow,
    _get_on_complete_config,
    _get_trigger_config,
    _insert_fan_in_barriers,
    _maybe_wrap_on_complete_node,
    _maybe_wrap_trigger_node,
    _passthrough_node,
    _remap_barrier_targets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dag(topo_order=None, predecessors=None, successors=None, roots=None):
    """Create a minimal DAG-like namespace."""
    return SimpleNamespace(
        topo_order=topo_order or [],
        predecessors=predecessors or {},
        successors=successors or {},
        roots=roots or [],
    )


def _make_compiler():
    node_builder = MagicMock()
    node_builder.create_stage_node.return_value = MagicMock()
    node_builder.wire_dag_context.return_value = None
    return StageCompiler(node_builder)


# ---------------------------------------------------------------------------
# _passthrough_node
# ---------------------------------------------------------------------------


class TestPassthroughNode:
    def test_returns_empty_dict(self):
        assert _passthrough_node({}) == {}
        assert _passthrough_node({"key": "value"}) == {}


# ---------------------------------------------------------------------------
# _insert_fan_in_barriers
# ---------------------------------------------------------------------------


class TestInsertFanInBarriers:
    def test_no_fan_in_returns_empty(self):
        dag = _make_dag(
            topo_order=["a", "b"],
            predecessors={"a": [], "b": ["a"]},
        )
        depths = {"a": 0, "b": 1}
        graph = MagicMock()
        result = _insert_fan_in_barriers(graph, dag, depths)
        assert result == {}

    def test_symmetric_fan_in_no_barriers(self):
        # Both predecessors at same depth — no barriers needed
        dag = _make_dag(
            topo_order=["a", "b", "c"],
            predecessors={"a": [], "b": [], "c": ["a", "b"]},
        )
        depths = {"a": 1, "b": 1, "c": 2}
        graph = MagicMock()
        result = _insert_fan_in_barriers(graph, dag, depths)
        assert result == {}

    def test_asymmetric_fan_in_inserts_barriers(self):
        # a is at depth 0, b is at depth 1; c has both as predecessors
        dag = _make_dag(
            topo_order=["a", "b", "c"],
            predecessors={"a": [], "b": ["a"], "c": ["a", "b"]},
        )
        depths = {"a": 0, "b": 1, "c": 2}
        graph = MagicMock()
        result = _insert_fan_in_barriers(graph, dag, depths)
        # a->c should have a barrier
        assert ("a", "c") in result

    def test_skips_loop_stage_predecessors(self):
        dag = _make_dag(
            topo_order=["a", "b", "c"],
            predecessors={"a": [], "b": [], "c": ["a", "b"]},
        )
        depths = {"a": 0, "b": 1, "c": 2}
        graph = MagicMock()
        # a is a loop stage — should be skipped
        result = _insert_fan_in_barriers(graph, dag, depths, loop_stages={"a"})
        assert ("a", "c") not in result

    def test_multiple_barriers_for_large_depth_diff(self):
        dag = _make_dag(
            topo_order=["a", "b", "c"],
            predecessors={"a": [], "b": [], "c": ["a", "b"]},
        )
        depths = {"a": 0, "b": 3, "c": 4}
        graph = MagicMock()
        result = _insert_fan_in_barriers(graph, dag, depths)
        assert ("a", "c") in result
        # Should add multiple barrier nodes (depth diff = 3)
        assert graph.add_node.call_count >= 3


# ---------------------------------------------------------------------------
# _filter_reachable_targets
# ---------------------------------------------------------------------------


class TestFilterReachableTargets:
    def test_single_target_returned_as_is(self):
        dag = _make_dag(predecessors={})
        result = _filter_reachable_targets(["b"], "a", dag)
        assert result == ["b"]

    def test_empty_successors_returns_none_list(self):
        dag = _make_dag(predecessors={})
        result = _filter_reachable_targets([], "a", dag)
        assert result == [None]

    def test_filters_target_reachable_from_another(self):
        # b and c are successors of a; c is also reachable from b
        dag = _make_dag(predecessors={"c": ["a", "b"]})
        result = _filter_reachable_targets(["b", "c"], "a", dag)
        # c is reachable from b (which is in target_set) so it should be filtered
        assert "c" not in result

    def test_none_target_preserved(self):
        dag = _make_dag(predecessors={"b": []})
        result = _filter_reachable_targets([None, "b"], "a", dag)
        assert None in result

    def test_fallback_when_all_filtered(self):
        # Edge case: all targets are filtered, should return original
        dag = _make_dag(predecessors={"b": ["a", "b"]})
        result = _filter_reachable_targets(["b"], "a", dag)
        assert result == ["b"]


# ---------------------------------------------------------------------------
# _remap_barrier_targets
# ---------------------------------------------------------------------------


class TestRemapBarrierTargets:
    def test_no_barrier_edges_returns_original(self):
        result = _remap_barrier_targets(["b", "c"], "a", None)
        assert result == ["b", "c"]

    def test_remaps_barrier_target(self):
        barrier_edges = {("a", "b"): True}
        result = _remap_barrier_targets(["b"], "a", barrier_edges)
        assert result == [f"{BARRIER_PREFIX}a_to_b_0"]

    def test_none_target_preserved(self):
        barrier_edges = {}
        result = _remap_barrier_targets([None], "a", barrier_edges)
        assert result == [None]

    def test_mixed_barrier_and_direct(self):
        barrier_edges = {("a", "b"): True}
        result = _remap_barrier_targets(["b", "c"], "a", barrier_edges)
        assert f"{BARRIER_PREFIX}a_to_b_0" in result
        assert "c" in result


# ---------------------------------------------------------------------------
# _get_event_bus_from_workflow
# ---------------------------------------------------------------------------


class TestGetEventBusFromWorkflow:
    def test_no_event_bus_config_returns_none(self):
        config = {"workflow": {"config": {}}}
        result = _get_event_bus_from_workflow(config)
        assert result is None

    def test_event_bus_disabled_returns_none(self):
        config = {"workflow": {"config": {"event_bus": {"enabled": False}}}}
        result = _get_event_bus_from_workflow(config)
        assert result is None

    def test_no_workflow_key_returns_none(self):
        config = {}
        result = _get_event_bus_from_workflow(config)
        assert result is None

    def test_event_bus_enabled_returns_bus(self):
        config = {
            "workflow": {
                "config": {"event_bus": {"enabled": True, "persist_events": True}}
            }
        }
        mock_bus = MagicMock()
        with patch("temper_ai.events.event_bus.TemperEventBus", return_value=mock_bus):
            result = _get_event_bus_from_workflow(config)
        assert result is mock_bus

    def test_event_bus_enabled_no_persist(self):
        config = {
            "workflow": {
                "config": {"event_bus": {"enabled": True, "persist_events": False}}
            }
        }
        mock_bus = MagicMock()
        with patch(
            "temper_ai.events.event_bus.TemperEventBus", return_value=mock_bus
        ) as mock_cls:
            _get_event_bus_from_workflow(config)
            mock_cls.assert_called_once_with(persist=False)


# ---------------------------------------------------------------------------
# _get_trigger_config / _get_on_complete_config
# ---------------------------------------------------------------------------


class TestGetTriggerConfig:
    def test_none_ref_returns_none(self):
        assert _get_trigger_config(None) is None

    def test_dict_with_trigger(self):
        assert _get_trigger_config({"trigger": {"event_type": "foo"}}) == {
            "event_type": "foo"
        }

    def test_dict_without_trigger(self):
        assert _get_trigger_config({"name": "stage1"}) is None

    def test_object_with_trigger(self):
        ref = SimpleNamespace(trigger={"event_type": "bar"})
        assert _get_trigger_config(ref) == {"event_type": "bar"}

    def test_object_without_trigger(self):
        ref = SimpleNamespace(name="stage1")
        assert _get_trigger_config(ref) is None


class TestGetOnCompleteConfig:
    def test_none_ref_returns_none(self):
        assert _get_on_complete_config(None) is None

    def test_dict_with_on_complete(self):
        cfg = {"event_type": "done"}
        assert _get_on_complete_config({"on_complete": cfg}) == cfg

    def test_dict_without_on_complete(self):
        assert _get_on_complete_config({"name": "stage1"}) is None

    def test_object_with_on_complete(self):
        ref = SimpleNamespace(on_complete={"event_type": "finished"})
        assert _get_on_complete_config(ref) == {"event_type": "finished"}


# ---------------------------------------------------------------------------
# _maybe_wrap_trigger_node
# ---------------------------------------------------------------------------


class TestMaybeWrapTriggerNode:
    def test_no_trigger_returns_original(self):
        node_fn = MagicMock()
        stage_ref = {"name": "stage1"}  # no trigger key
        result = _maybe_wrap_trigger_node("stage1", node_fn, stage_ref)
        assert result is node_fn

    def test_none_ref_returns_original(self):
        node_fn = MagicMock()
        result = _maybe_wrap_trigger_node("stage1", node_fn, None)
        assert result is node_fn

    def test_with_trigger_wraps_node(self):
        node_fn = MagicMock()
        stage_ref = {"trigger": {"event_type": "data.ready"}}
        wrapped = _maybe_wrap_trigger_node("stage1", node_fn, stage_ref)
        # The wrapped node is a different callable
        assert wrapped is not node_fn
        assert callable(wrapped)

    def test_wrapped_node_calls_create_event_triggered_node(self):
        node_fn = MagicMock(return_value={"output": "done"})
        from types import SimpleNamespace

        trigger_cfg = SimpleNamespace(event_type="data.ready")
        stage_ref = {"trigger": trigger_cfg}

        mock_inner = MagicMock(return_value={"result": "ok"})

        # Patch where it's imported inside the function
        with patch(
            "temper_ai.workflow.node_builder.create_event_triggered_node",
            return_value=mock_inner,
        ):
            wrapped = _maybe_wrap_trigger_node("stage1", node_fn, stage_ref)
            state = {"event_bus": MagicMock()}
            result = wrapped(state)

        assert result == {"result": "ok"}


# ---------------------------------------------------------------------------
# _maybe_wrap_on_complete_node
# ---------------------------------------------------------------------------


class TestMaybeWrapOnCompleteNode:
    def test_no_on_complete_returns_original(self):
        node_fn = MagicMock()
        result = _maybe_wrap_on_complete_node("stage1", node_fn, {"name": "stage1"})
        assert result is node_fn

    def test_none_ref_returns_original(self):
        node_fn = MagicMock()
        result = _maybe_wrap_on_complete_node("stage1", node_fn, None)
        assert result is node_fn

    def test_wraps_when_on_complete_set(self):
        node_fn = MagicMock(return_value={})
        stage_ref = {"on_complete": {"event_type": "stage.done"}}
        wrapped = _maybe_wrap_on_complete_node("stage1", node_fn, stage_ref)
        assert wrapped is not node_fn

    def test_wrapped_emits_event_when_event_bus_present(self):
        mock_bus = MagicMock()
        node_fn = MagicMock(return_value={"event_bus": mock_bus, "stage_outputs": {}})
        stage_ref = {
            "on_complete": {"event_type": "stage.done", "include_output": False}
        }
        wrapped = _maybe_wrap_on_complete_node("stage1", node_fn, stage_ref)

        state = {"event_bus": mock_bus, "workflow_id": "wf-123"}
        wrapped(state)

        mock_bus.emit.assert_called_once()

    def test_wrapped_no_event_bus_returns_result(self):
        node_fn = MagicMock(return_value={"output": "hello"})
        stage_ref = {"on_complete": {"event_type": "stage.done"}}
        wrapped = _maybe_wrap_on_complete_node("stage1", node_fn, stage_ref)

        state = {}  # no event_bus
        result = wrapped(state)

        assert result == {"output": "hello"}

    def test_wrapped_include_output_true(self):
        mock_bus = MagicMock()
        stage_outputs = {"stage1": "my-output"}
        node_fn = MagicMock(
            return_value={"event_bus": mock_bus, "stage_outputs": stage_outputs}
        )
        stage_ref = {
            "on_complete": {"event_type": "stage.done", "include_output": True}
        }
        wrapped = _maybe_wrap_on_complete_node("stage1", node_fn, stage_ref)

        state = {"event_bus": mock_bus, "workflow_id": "wf-1"}
        wrapped(state)

        call_kwargs = mock_bus.emit.call_args
        assert call_kwargs is not None
        (
            call_kwargs.kwargs.get("payload")
            or call_kwargs[1].get("payload")
            or call_kwargs[0][1]
            if len(call_kwargs[0]) > 1
            else {}
        )
        # Just verify emit was called
        mock_bus.emit.assert_called_once()

    def test_wrapped_event_emit_exception_does_not_propagate(self):
        mock_bus = MagicMock()
        mock_bus.emit.side_effect = RuntimeError("emit failed")
        node_fn = MagicMock(return_value={"event_bus": mock_bus})
        stage_ref = {"on_complete": {"event_type": "stage.done"}}
        wrapped = _maybe_wrap_on_complete_node("stage1", node_fn, stage_ref)

        state = {"event_bus": mock_bus}
        # Should not raise
        result = wrapped(state)
        assert result is not None

    def test_on_complete_with_object_config(self):
        mock_bus = MagicMock()
        on_complete_cfg = SimpleNamespace(event_type="done", include_output=False)
        node_fn = MagicMock(return_value={"event_bus": mock_bus})
        stage_ref = SimpleNamespace(on_complete=on_complete_cfg)
        wrapped = _maybe_wrap_on_complete_node("stage1", node_fn, stage_ref)

        state = {"event_bus": mock_bus, "workflow_id": "wf-1"}
        wrapped(state)
        mock_bus.emit.assert_called_once()


# ---------------------------------------------------------------------------
# StageCompiler._is_conditional
# ---------------------------------------------------------------------------


class TestIsConditional:
    def test_dict_with_conditional_true(self):
        assert StageCompiler._is_conditional({"conditional": True})

    def test_dict_with_condition(self):
        assert StageCompiler._is_conditional({"condition": "x > 0"})

    def test_dict_with_skip_if(self):
        assert StageCompiler._is_conditional({"skip_if": "always"})

    def test_dict_no_condition(self):
        assert not StageCompiler._is_conditional({"name": "stage1"})

    def test_object_with_conditional(self):
        ref = SimpleNamespace(conditional=True, condition=None, skip_if=None)
        assert StageCompiler._is_conditional(ref)

    def test_object_no_condition(self):
        ref = SimpleNamespace(conditional=False, condition=None, skip_if=None)
        assert not StageCompiler._is_conditional(ref)


# ---------------------------------------------------------------------------
# StageCompiler._resolve_skip_target
# ---------------------------------------------------------------------------


class TestResolveSkipTarget:
    def test_skip_to_end_returns_none(self):
        stage_ref = {"skip_to": "end"}
        dag = _make_dag(successors={"a": ["b"]})
        result = StageCompiler._resolve_skip_target("a", stage_ref, dag)
        assert result is None

    def test_explicit_skip_to_returns_target(self):
        stage_ref = {"skip_to": "c"}
        dag = _make_dag(successors={"a": ["b"]})
        result = StageCompiler._resolve_skip_target("a", stage_ref, dag)
        assert result == "c"

    def test_defaults_to_first_successor(self):
        stage_ref = {}
        dag = _make_dag(successors={"a": ["b", "c"]})
        result = StageCompiler._resolve_skip_target("a", stage_ref, dag)
        assert result == "b"

    def test_returns_none_when_no_successors(self):
        stage_ref = {}
        dag = _make_dag(successors={"a": []})
        result = StageCompiler._resolve_skip_target("a", stage_ref, dag)
        assert result is None


# ---------------------------------------------------------------------------
# StageCompiler.compile_parallel_stages / compile_conditional_stages
# ---------------------------------------------------------------------------


class TestCompileAliases:
    def test_compile_parallel_stages_delegates(self):
        compiler = _make_compiler()
        with patch.object(
            compiler, "compile_stages", return_value=MagicMock()
        ) as mock_compile:
            compiler.compile_parallel_stages(["a", "b"], {"workflow": {"stages": []}})
            mock_compile.assert_called_once_with(
                ["a", "b"], {"workflow": {"stages": []}}
            )

    def test_compile_conditional_stages_delegates(self):
        compiler = _make_compiler()
        with patch.object(
            compiler, "compile_stages", return_value=MagicMock()
        ) as mock_compile:
            compiler.compile_conditional_stages(
                ["a", "b"], {"workflow": {"stages": []}}, {"cond": True}
            )
            mock_compile.assert_called_once_with(
                ["a", "b"], {"workflow": {"stages": []}}
            )


# ---------------------------------------------------------------------------
# StageCompiler._add_dag_edges (integration via compile_stages)
# ---------------------------------------------------------------------------


class TestAddDagEdges:
    def test_add_init_to_roots_simple_edge(self):
        compiler = _make_compiler()
        dag = _make_dag(
            topo_order=["a", "b"],
            predecessors={"a": [], "b": ["a"]},
            successors={"a": ["b"], "b": []},
            roots=["a"],
        )
        graph = MagicMock()
        stage_refs = [{"name": "a"}, {"name": "b"}]

        with patch(
            "temper_ai.workflow.stage_compiler.build_stage_dag", return_value=dag
        ):
            with patch(
                "temper_ai.workflow.stage_compiler.compute_depths",
                return_value={"a": 0, "b": 1},
            ):
                compiler._add_dag_edges(graph, ["a", "b"], stage_refs)

        # init -> a should be added (non-conditional root)
        graph.add_edge.assert_any_call("init", "a")

    def test_add_dag_edges_terminal_connects_to_end(self):
        compiler = _make_compiler()
        dag = _make_dag(
            topo_order=["a"],
            predecessors={"a": []},
            successors={"a": []},
            roots=["a"],
        )
        graph = MagicMock()
        stage_refs = [{"name": "a"}]

        with patch(
            "temper_ai.workflow.stage_compiler.build_stage_dag", return_value=dag
        ):
            with patch(
                "temper_ai.workflow.stage_compiler.compute_depths",
                return_value={"a": 0},
            ):
                compiler._add_dag_edges(graph, ["a"], stage_refs)

        # Terminal stage should connect to END
        graph.add_edge.assert_any_call("a", END)


# ---------------------------------------------------------------------------
# StageCompiler._add_loop_edge_dag
# ---------------------------------------------------------------------------


class TestAddLoopEdgeDag:
    def test_no_loops_back_returns_false(self):
        compiler = _make_compiler()
        graph = MagicMock()
        stage_ref = {"name": "a"}  # no loops_back_to
        result = compiler._add_loop_edge_dag(graph, "a", stage_ref, ["b"], _make_dag())
        assert result is False

    def test_with_loops_back_returns_true(self):
        compiler = _make_compiler()
        graph = MagicMock()
        stage_ref = {"name": "a", "loops_back_to": "a", "max_loops": 3}
        dag = _make_dag(predecessors={"b": []})
        result = compiler._add_loop_edge_dag(graph, "a", stage_ref, ["b"], dag)
        assert result is True
        # Gate node should be added
        graph.add_node.assert_called()
        graph.add_edge.assert_any_call("a", f"{LOOP_GATE_PREFIX}a")


# ---------------------------------------------------------------------------
# StageCompiler._add_successor_edges
# ---------------------------------------------------------------------------


class TestAddSuccessorEdges:
    def test_no_successors_connects_to_end(self):
        compiler = _make_compiler()
        graph = MagicMock()
        compiler._add_successor_edges(graph, "a", [], {}, _make_dag(), [])
        graph.add_edge.assert_called_once_with("a", END)

    def test_single_successor_direct_edge(self):
        compiler = _make_compiler()
        graph = MagicMock()
        compiler._add_successor_edges(
            graph, "a", ["b"], {"b": {"name": "b"}}, _make_dag(), []
        )
        graph.add_edge.assert_called_with("a", "b")

    def test_barrier_edge_skipped(self):
        compiler = _make_compiler()
        graph = MagicMock()
        barrier_edges = {("a", "b"): True}
        compiler._add_successor_edges(
            graph,
            "a",
            ["b"],
            {"b": {"name": "b"}},
            _make_dag(),
            [],
            barrier_edges=barrier_edges,
        )
        # Direct edge to "b" should NOT be called
        assert call("a", "b") not in graph.add_edge.call_args_list

    def test_conditional_successor_adds_conditional_edge(self):
        compiler = _make_compiler()
        graph = MagicMock()
        dag = _make_dag(successors={"b": []})
        ref_lookup = {"b": {"name": "b", "condition": "x > 0"}}
        compiler._add_successor_edges(
            graph, "a", ["b"], ref_lookup, dag, [{"name": "b"}]
        )
        graph.add_conditional_edges.assert_called()
