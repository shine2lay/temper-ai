"""Tests for stage_compiler module.

Covers module-level pure helper functions and StageCompiler methods.
Tests are grouped by function/class with clear docstrings.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langgraph.graph import END

from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.stage_compiler import (
    BARRIER_PREFIX,
    LOOP_GATE_PREFIX,
    StageCompiler,
    _build_loop_path_map,
    _build_loop_path_map_multi,
    _build_path_map,
    _build_ref_lookup,
    _create_loop_gate_node,
    _filter_reachable_targets,
    _get_event_bus_from_workflow,
    _get_on_complete_config,
    _get_trigger_config,
    _maybe_wrap_on_complete_node,
    _maybe_wrap_trigger_node,
    _passthrough_node,
    _remap_barrier_targets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dag(predecessors=None, successors=None):
    """Simple DAG-like namespace for testing."""
    return SimpleNamespace(
        predecessors=predecessors or {},
        successors=successors or {},
    )


def _make_compiler():
    """Create a StageCompiler with a mocked NodeBuilder."""
    node_builder = MagicMock()
    return StageCompiler(node_builder)


# ---------------------------------------------------------------------------
# _build_ref_lookup
# ---------------------------------------------------------------------------


class TestBuildRefLookup:
    """Tests for _build_ref_lookup module-level helper."""

    def test_empty_list_returns_empty_dict(self):
        """Empty input produces empty lookup."""
        result = _build_ref_lookup([])
        assert result == {}

    def test_string_refs_are_skipped(self):
        """Plain string refs are not added to lookup."""
        result = _build_ref_lookup(["stage_a", "stage_b"])
        assert result == {}

    def test_dict_ref_with_name_included(self):
        """Dict refs with 'name' key are indexed by name."""
        refs = [{"name": "stage_a", "other": "value"}]
        result = _build_ref_lookup(refs)
        assert "stage_a" in result
        assert result["stage_a"] == refs[0]

    def test_object_ref_with_name_attribute_included(self):
        """Object refs with .name attribute are indexed by name."""
        ref = SimpleNamespace(name="my_stage", config="cfg")
        result = _build_ref_lookup([ref])
        assert result["my_stage"] is ref

    def test_mixed_refs_only_dicts_included(self):
        """Mix of string and dict refs: only dicts are included."""
        refs = ["skip_me", {"name": "keep_me"}]
        result = _build_ref_lookup(refs)
        assert list(result.keys()) == ["keep_me"]

    def test_dict_without_name_excluded(self):
        """Dict refs without 'name' key are excluded."""
        refs = [{"stage_ref": "some.yaml"}]
        result = _build_ref_lookup(refs)
        assert result == {}


# ---------------------------------------------------------------------------
# _create_loop_gate_node
# ---------------------------------------------------------------------------


class TestCreateLoopGateNode:
    """Tests for _create_loop_gate_node."""

    def test_returns_callable(self):
        """Factory returns a callable gate function."""
        gate = _create_loop_gate_node("my_stage")
        assert callable(gate)

    def test_dict_state_missing_key_starts_at_zero(self):
        """Missing stage key starts at 0, first call sets count to 1."""
        gate = _create_loop_gate_node("stage_a")
        state = {StateKeys.STAGE_LOOP_COUNTS: {}}
        result = gate(state)
        assert result[StateKeys.STAGE_LOOP_COUNTS]["stage_a"] == 1

    def test_dict_state_increments_existing_counter(self):
        """Existing count is incremented by 1."""
        gate = _create_loop_gate_node("stage_a")
        state = {StateKeys.STAGE_LOOP_COUNTS: {"stage_a": 3}}
        result = gate(state)
        assert result[StateKeys.STAGE_LOOP_COUNTS]["stage_a"] == 4

    def test_object_state_reads_via_getattr(self):
        """State object with attribute is read via getattr."""
        gate = _create_loop_gate_node("stage_b")
        state = SimpleNamespace(**{StateKeys.STAGE_LOOP_COUNTS: {"stage_b": 2}})
        result = gate(state)
        assert result[StateKeys.STAGE_LOOP_COUNTS]["stage_b"] == 3

    def test_dict_state_without_loop_counts_key(self):
        """State dict missing the key entirely starts counter at 1."""
        gate = _create_loop_gate_node("new_stage")
        result = gate({})
        assert result[StateKeys.STAGE_LOOP_COUNTS]["new_stage"] == 1

    def test_gate_does_not_mutate_input_state(self):
        """Gate returns new counts dict without mutating input."""
        gate = _create_loop_gate_node("stage_c")
        original_counts = {"stage_c": 1}
        state = {StateKeys.STAGE_LOOP_COUNTS: original_counts}
        gate(state)
        assert original_counts["stage_c"] == 1  # unchanged


# ---------------------------------------------------------------------------
# _build_path_map
# ---------------------------------------------------------------------------


class TestBuildPathMap:
    """Tests for _build_path_map."""

    def test_with_skip_target(self):
        """Path map contains stage name and explicit skip target."""
        result = _build_path_map("stage_a", "stage_c")
        assert result == {"stage_a": "stage_a", "stage_c": "stage_c"}

    def test_without_skip_target_uses_end(self):
        """None skip target maps to END constant."""
        result = _build_path_map("stage_a", None)
        assert result == {"stage_a": "stage_a", END: END}

    def test_stage_name_always_maps_to_itself(self):
        """Stage name entry is always present and self-referential."""
        result = _build_path_map("x", "y")
        assert result["x"] == "x"


# ---------------------------------------------------------------------------
# _build_loop_path_map
# ---------------------------------------------------------------------------


class TestBuildLoopPathMap:
    """Tests for _build_loop_path_map (single exit target)."""

    def test_with_exit_target(self):
        """Loop target and exit target both present."""
        result = _build_loop_path_map("loop_stage", "next_stage")
        assert result == {"loop_stage": "loop_stage", "next_stage": "next_stage"}

    def test_without_exit_target_uses_end(self):
        """None exit target maps to END."""
        result = _build_loop_path_map("loop_stage", None)
        assert result == {"loop_stage": "loop_stage", END: END}

    def test_loop_target_maps_to_itself(self):
        """Loop target entry is always self-referential."""
        result = _build_loop_path_map("back_to_me", "somewhere")
        assert result["back_to_me"] == "back_to_me"


# ---------------------------------------------------------------------------
# _build_loop_path_map_multi
# ---------------------------------------------------------------------------


class TestBuildLoopPathMapMulti:
    """Tests for _build_loop_path_map_multi (multiple exit targets)."""

    def test_multiple_named_exit_targets(self):
        """All exit targets and loop target are in path map."""
        result = _build_loop_path_map_multi("loop_stage", ["next_a", "next_b"])
        assert result["loop_stage"] == "loop_stage"
        assert result["next_a"] == "next_a"
        assert result["next_b"] == "next_b"

    def test_none_target_resolves_to_end(self):
        """None in exit_targets resolves to END."""
        result = _build_loop_path_map_multi("loop_stage", [None])
        assert result["loop_stage"] == "loop_stage"
        assert result[END] == END

    def test_mixed_none_and_named_targets(self):
        """Mix of None and named targets all included."""
        result = _build_loop_path_map_multi("ls", ["stage_x", None])
        assert "stage_x" in result
        assert END in result


# ---------------------------------------------------------------------------
# _filter_reachable_targets
# ---------------------------------------------------------------------------


class TestFilterReachableTargets:
    """Tests for _filter_reachable_targets."""

    def test_empty_successors_returns_none_list(self):
        """Empty successors → [None] (route to END)."""
        dag = _make_dag()
        result = _filter_reachable_targets([], "stage", dag)
        assert result == [None]

    def test_single_successor_returned_as_is(self):
        """Single successor is always returned unchanged."""
        dag = _make_dag(predecessors={"only": []})
        result = _filter_reachable_targets(["only"], "stage", dag)
        assert result == ["only"]

    def test_filters_target_reachable_via_another_target(self):
        """Target reachable through another exit target is filtered out."""
        # stage "A" → successors ["B", "C"]; B is a predecessor of C.
        # After discarding "A" from C's preds, B remains and is in target_set → C filtered.
        dag = _make_dag(predecessors={"B": [], "C": ["A", "B"]})
        result = _filter_reachable_targets(["B", "C"], "A", dag)
        assert result == ["B"]

    def test_independent_targets_not_filtered(self):
        """Targets with no overlap among other preds are all kept."""
        dag = _make_dag(predecessors={"B": ["A"], "C": ["A"]})
        result = _filter_reachable_targets(["B", "C"], "A", dag)
        # Neither B nor C is a predecessor of the other → both kept
        assert set(result) == {"B", "C"}


# ---------------------------------------------------------------------------
# _remap_barrier_targets
# ---------------------------------------------------------------------------


class TestRemapBarrierTargets:
    """Tests for _remap_barrier_targets."""

    def test_no_barrier_edges_returns_unchanged(self):
        """None barrier_edges leaves targets unchanged."""
        result = _remap_barrier_targets(["B", "C"], "A", None)
        assert result == ["B", "C"]

    def test_no_matching_barrier_returns_unchanged(self):
        """Barrier edges dict without matching key leaves target unchanged."""
        result = _remap_barrier_targets(["B"], "A", {("X", "Y"): True})
        assert result == ["B"]

    def test_matching_barrier_remaps_to_barrier_entry_name(self):
        """Matching (stage, target) in barrier_edges remaps to barrier node name."""
        result = _remap_barrier_targets(["B"], "A", {("A", "B"): True})
        assert result == [f"{BARRIER_PREFIX}A_to_B_0"]

    def test_none_target_not_remapped(self):
        """None target is never remapped (requires truthy target)."""
        result = _remap_barrier_targets([None], "A", {("A", None): True})
        assert result == [None]

    def test_partial_remapping_mixed_targets(self):
        """Some targets remapped, others not."""
        barrier_edges = {("A", "B"): True}
        result = _remap_barrier_targets(["B", "C"], "A", barrier_edges)
        assert result[0] == f"{BARRIER_PREFIX}A_to_B_0"
        assert result[1] == "C"


# ---------------------------------------------------------------------------
# _passthrough_node
# ---------------------------------------------------------------------------


class TestPassthroughNode:
    """Tests for _passthrough_node barrier node."""

    def test_returns_empty_dict_regardless_of_state(self):
        """Barrier node returns empty dict for any state input."""
        assert _passthrough_node({}) == {}
        assert _passthrough_node({"x": 1}) == {}
        assert _passthrough_node(SimpleNamespace()) == {}


# ---------------------------------------------------------------------------
# _get_trigger_config
# ---------------------------------------------------------------------------


class TestGetTriggerConfig:
    """Tests for _get_trigger_config."""

    def test_none_returns_none(self):
        """None stage_ref → None."""
        assert _get_trigger_config(None) is None

    def test_dict_with_trigger_key(self):
        """Dict with 'trigger' key returns that value."""
        ref = {"trigger": {"event": "my_event"}, "name": "s"}
        assert _get_trigger_config(ref) == {"event": "my_event"}

    def test_dict_without_trigger_returns_none(self):
        """Dict missing 'trigger' → None."""
        assert _get_trigger_config({"name": "s"}) is None

    def test_object_with_trigger_attribute(self):
        """Object with .trigger attribute returns that value."""
        ref = SimpleNamespace(trigger="some_trigger_cfg")
        assert _get_trigger_config(ref) == "some_trigger_cfg"

    def test_object_without_trigger_attribute(self):
        """Object without .trigger → None."""
        ref = SimpleNamespace(name="s")
        assert _get_trigger_config(ref) is None


# ---------------------------------------------------------------------------
# _get_on_complete_config
# ---------------------------------------------------------------------------


class TestGetOnCompleteConfig:
    """Tests for _get_on_complete_config."""

    def test_none_returns_none(self):
        """None stage_ref → None."""
        assert _get_on_complete_config(None) is None

    def test_dict_with_on_complete_key(self):
        """Dict with 'on_complete' key returns that value."""
        ref = {"on_complete": {"event_type": "done"}}
        assert _get_on_complete_config(ref) == {"event_type": "done"}

    def test_dict_without_on_complete_returns_none(self):
        """Dict missing 'on_complete' → None."""
        assert _get_on_complete_config({"name": "s"}) is None

    def test_object_with_on_complete_attribute(self):
        """Object with .on_complete attribute returns that value."""
        cfg = {"event_type": "finished"}
        ref = SimpleNamespace(on_complete=cfg)
        assert _get_on_complete_config(ref) is cfg

    def test_object_without_on_complete_attribute(self):
        """Object without .on_complete → None."""
        ref = SimpleNamespace(name="s")
        assert _get_on_complete_config(ref) is None


# ---------------------------------------------------------------------------
# _get_event_bus_from_workflow
# ---------------------------------------------------------------------------


class TestGetEventBusFromWorkflow:
    """Tests for _get_event_bus_from_workflow."""

    def test_no_workflow_key_returns_none(self):
        """Config without 'workflow' key → None."""
        result = _get_event_bus_from_workflow({})
        assert result is None

    def test_workflow_without_config_returns_none(self):
        """Workflow section without 'config' → None."""
        result = _get_event_bus_from_workflow({"workflow": {}})
        assert result is None

    def test_event_bus_disabled_returns_none(self):
        """Disabled event_bus config → None."""
        cfg = {"workflow": {"config": {"event_bus": {"enabled": False}}}}
        result = _get_event_bus_from_workflow(cfg)
        assert result is None

    def test_event_bus_enabled_persist_false(self):
        """Enabled event_bus with persist_events=False creates TemperEventBus(persist=False)."""
        cfg = {
            "workflow": {
                "config": {"event_bus": {"enabled": True, "persist_events": False}}
            }
        }
        with patch("temper_ai.events.event_bus.TemperEventBus") as MockBus:
            result = _get_event_bus_from_workflow(cfg)
            MockBus.assert_called_once_with(persist=False)
            assert result is MockBus.return_value

    def test_event_bus_enabled_persist_true(self):
        """Enabled event_bus with persist_events=True creates TemperEventBus(persist=True)."""
        cfg = {
            "workflow": {
                "config": {"event_bus": {"enabled": True, "persist_events": True}}
            }
        }
        with patch("temper_ai.events.event_bus.TemperEventBus") as MockBus:
            _get_event_bus_from_workflow(cfg)
            MockBus.assert_called_once_with(persist=True)


# ---------------------------------------------------------------------------
# StageCompiler._is_conditional
# ---------------------------------------------------------------------------


class TestIsConditional:
    """Tests for StageCompiler._is_conditional static method."""

    def test_dict_with_conditional_key_true(self):
        """Dict with truthy 'conditional' → True."""
        assert StageCompiler._is_conditional({"conditional": True}) is True

    def test_dict_with_condition_key(self):
        """Dict with 'condition' → True."""
        assert StageCompiler._is_conditional({"condition": "some.expr"}) is True

    def test_dict_with_skip_if_key(self):
        """Dict with 'skip_if' → True."""
        assert StageCompiler._is_conditional({"skip_if": "some.field"}) is True

    def test_dict_without_any_conditional_key(self):
        """Dict with none of the conditional keys → False."""
        assert StageCompiler._is_conditional({"name": "s", "stage_ref": "x"}) is False

    def test_dict_all_falsy_values_returns_false(self):
        """Conditional keys present but all falsy → False."""
        ref = {"conditional": False, "condition": None, "skip_if": None}
        assert StageCompiler._is_conditional(ref) is False

    def test_object_with_conditional_attribute_true(self):
        """Object with .conditional = True → True."""
        ref = SimpleNamespace(conditional=True)
        assert StageCompiler._is_conditional(ref) is True

    def test_object_without_conditional_attrs_returns_false(self):
        """Object without any conditional attributes → False."""
        ref = SimpleNamespace(name="s")
        assert StageCompiler._is_conditional(ref) is False


# ---------------------------------------------------------------------------
# StageCompiler._resolve_skip_target
# ---------------------------------------------------------------------------


class TestResolveSkipTarget:
    """Tests for StageCompiler._resolve_skip_target static method."""

    def test_explicit_skip_to_returned_directly(self):
        """Explicit skip_to value is returned as-is."""
        ref = SimpleNamespace(skip_to="target_stage")
        dag = _make_dag(successors={"stage": ["other"]})
        result = StageCompiler._resolve_skip_target("stage", ref, dag)
        assert result == "target_stage"

    def test_skip_to_end_string_returns_none(self):
        """skip_to='end' maps to None (→ END in routing)."""
        ref = SimpleNamespace(skip_to="end")
        dag = _make_dag(successors={"stage": ["other"]})
        result = StageCompiler._resolve_skip_target("stage", ref, dag)
        assert result is None

    def test_no_skip_to_defaults_to_first_successor(self):
        """No skip_to → first DAG successor is the skip target."""
        ref = SimpleNamespace(skip_to=None)
        dag = _make_dag(successors={"stage": ["successor_a", "successor_b"]})
        result = StageCompiler._resolve_skip_target("stage", ref, dag)
        assert result == "successor_a"

    def test_terminal_stage_with_no_successors_returns_none(self):
        """Terminal stage with no successors and no skip_to → None (→ END)."""
        ref = SimpleNamespace(skip_to=None)
        dag = _make_dag(successors={"stage": []})
        result = StageCompiler._resolve_skip_target("stage", ref, dag)
        assert result is None


# ---------------------------------------------------------------------------
# StageCompiler.compile_stages
# ---------------------------------------------------------------------------


class TestCompileStages:
    """Tests for StageCompiler.compile_stages."""

    def test_empty_stage_names_raises_value_error(self):
        """Empty stage list raises ValueError with descriptive message."""
        compiler = _make_compiler()
        with pytest.raises(ValueError, match="no stages"):
            compiler.compile_stages([], {})


# ---------------------------------------------------------------------------
# _maybe_wrap_trigger_node
# ---------------------------------------------------------------------------


class TestMaybeWrapTriggerNode:
    """Tests for _maybe_wrap_trigger_node."""

    def test_no_trigger_config_returns_same_node_fn(self):
        """No trigger config → same node_fn returned unchanged."""
        node_fn = MagicMock()
        result = _maybe_wrap_trigger_node("stage", node_fn, None)
        assert result is node_fn

    def test_with_trigger_config_returns_new_callable(self):
        """Trigger config → returns a different callable."""
        node_fn = MagicMock()
        stage_ref = {"trigger": {"event": "my_event"}}
        result = _maybe_wrap_trigger_node("stage", node_fn, stage_ref)
        assert result is not node_fn
        assert callable(result)

    def test_dict_ref_without_trigger_key_returns_identity(self):
        """Dict ref without 'trigger' key → identity (same node_fn)."""
        node_fn = MagicMock()
        result = _maybe_wrap_trigger_node("stage", node_fn, {"name": "stage"})
        assert result is node_fn


# ---------------------------------------------------------------------------
# _maybe_wrap_on_complete_node
# ---------------------------------------------------------------------------


class TestMaybeWrapOnCompleteNode:
    """Tests for _maybe_wrap_on_complete_node."""

    def test_no_on_complete_config_returns_same_node_fn(self):
        """No on_complete config → same node_fn returned unchanged."""
        node_fn = MagicMock()
        result = _maybe_wrap_on_complete_node("stage", node_fn, None)
        assert result is node_fn

    def test_with_config_returns_new_callable(self):
        """on_complete config → returns a different callable."""
        node_fn = MagicMock(return_value={})
        stage_ref = {"on_complete": {"event_type": "done"}}
        result = _maybe_wrap_on_complete_node("stage", node_fn, stage_ref)
        assert result is not node_fn
        assert callable(result)

    def test_with_config_no_event_bus_returns_result_unchanged(self):
        """With config but no event_bus in state or result → inner result returned."""
        inner_result = {"output": "data"}
        node_fn = MagicMock(return_value=inner_result)
        stage_ref = {"on_complete": {"event_type": "finished"}}
        wrapped = _maybe_wrap_on_complete_node("stage", node_fn, stage_ref)
        result = wrapped({"workflow_id": "wf123"})
        assert result is inner_result

    def test_with_config_and_event_bus_emits_event(self):
        """With on_complete config and event_bus available, emit is called."""
        mock_bus = MagicMock()
        inner_result = {"event_bus": mock_bus}
        node_fn = MagicMock(return_value=inner_result)
        stage_ref = {"on_complete": {"event_type": "my_event", "include_output": False}}
        wrapped = _maybe_wrap_on_complete_node("my_stage", node_fn, stage_ref)
        result = wrapped({"workflow_id": "wf-1"})
        mock_bus.emit.assert_called_once_with(
            event_type="my_event",
            payload={"stage_name": "my_stage"},
            source_workflow_id="wf-1",
            source_stage_name="my_stage",
        )
        assert result is inner_result

    def test_with_config_emit_failure_still_returns_result(self):
        """Event bus emit failure is caught and inner result is still returned."""
        mock_bus = MagicMock()
        mock_bus.emit.side_effect = RuntimeError("bus error")
        inner_result = {"event_bus": mock_bus}
        node_fn = MagicMock(return_value=inner_result)
        stage_ref = {"on_complete": {"event_type": "ev"}}
        wrapped = _maybe_wrap_on_complete_node("stage_x", node_fn, stage_ref)
        # Should not raise despite emit failure
        result = wrapped({})
        assert result is inner_result


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestConstants:
    """Sanity checks for exported constants."""

    def test_loop_gate_prefix_value(self):
        """LOOP_GATE_PREFIX is the expected string."""
        assert LOOP_GATE_PREFIX == "_loop_gate_"

    def test_barrier_prefix_value(self):
        """BARRIER_PREFIX is the expected string."""
        assert BARRIER_PREFIX == "_barrier_"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
