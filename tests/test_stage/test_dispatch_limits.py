"""Tests for stage/dispatch_limits.py — safety caps on runtime dispatch."""

from temper_ai.stage.dispatch_limits import (
    DEFAULT_CYCLE_DETECTION,
    DEFAULT_MAX_CHILDREN_PER_DISPATCH,
    DEFAULT_MAX_DISPATCH_DEPTH,
    DEFAULT_MAX_DYNAMIC_NODES,
    DispatchLimits,
    DispatchRunState,
    check_cycle,
    fingerprint_node,
)

# ---------------------------------------------------------------------------
# DispatchLimits.from_defaults
# ---------------------------------------------------------------------------


def test_from_defaults_none_returns_full_defaults():
    limits = DispatchLimits.from_defaults(None)
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH
    assert limits.max_dynamic_nodes == DEFAULT_MAX_DYNAMIC_NODES
    assert limits.max_dispatch_depth == DEFAULT_MAX_DISPATCH_DEPTH
    assert limits.cycle_detection is DEFAULT_CYCLE_DETECTION


def test_from_defaults_empty_dict_returns_defaults():
    limits = DispatchLimits.from_defaults({})
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH


def test_from_defaults_no_dispatch_section_returns_defaults():
    """Workflow has defaults but no dispatch subsection."""
    limits = DispatchLimits.from_defaults({"provider": "openai", "model": "gpt-4"})
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH


def test_from_defaults_full_override():
    limits = DispatchLimits.from_defaults({
        "dispatch": {
            "max_children_per_dispatch": 50,
            "max_dynamic_nodes": 500,
            "max_dispatch_depth": 5,
            "cycle_detection": False,
        }
    })
    assert limits.max_children_per_dispatch == 50
    assert limits.max_dynamic_nodes == 500
    assert limits.max_dispatch_depth == 5
    assert limits.cycle_detection is False


def test_from_defaults_partial_override_keeps_other_defaults():
    limits = DispatchLimits.from_defaults({
        "dispatch": {"max_dispatch_depth": 10}
    })
    assert limits.max_dispatch_depth == 10
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH


def test_from_defaults_invalid_int_falls_back_to_default():
    """Non-int value logged and default used — no crash."""
    limits = DispatchLimits.from_defaults({
        "dispatch": {"max_children_per_dispatch": "not a number"}
    })
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH


def test_from_defaults_negative_int_falls_back_to_default():
    limits = DispatchLimits.from_defaults({
        "dispatch": {"max_dynamic_nodes": -5}
    })
    assert limits.max_dynamic_nodes == DEFAULT_MAX_DYNAMIC_NODES


def test_from_defaults_non_dict_dispatch_ignored():
    """dispatch: "string" or list — ignored, defaults used."""
    limits = DispatchLimits.from_defaults({"dispatch": "bad"})
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH


# ---------------------------------------------------------------------------
# fingerprint_node
# ---------------------------------------------------------------------------


def test_fingerprint_is_deterministic():
    fp1 = fingerprint_node("agent_x", {"a": 1, "b": 2})
    fp2 = fingerprint_node("agent_x", {"b": 2, "a": 1})  # key order swapped
    assert fp1 == fp2


def test_fingerprint_differs_by_agent():
    fp_a = fingerprint_node("agent_a", {"x": 1})
    fp_b = fingerprint_node("agent_b", {"x": 1})
    assert fp_a != fp_b


def test_fingerprint_differs_by_input():
    fp1 = fingerprint_node("agent_x", {"x": 1})
    fp2 = fingerprint_node("agent_x", {"x": 2})
    assert fp1 != fp2


def test_fingerprint_handles_none_input():
    fp = fingerprint_node("agent_x", None)
    assert fp[0] == "agent_x"
    assert len(fp[1]) == 40   # SHA1 hex length


def test_fingerprint_handles_unserializable_input():
    """Non-JSON-serializable objects fall back to str() — no crash."""
    class X:
        pass
    fp = fingerprint_node("agent_x", {"obj": X()})
    assert fp[0] == "agent_x"
    assert isinstance(fp[1], str)


# ---------------------------------------------------------------------------
# check_cycle
# ---------------------------------------------------------------------------


def test_no_cycle_when_no_ancestors():
    state = DispatchRunState()
    fp = fingerprint_node("new_agent", {})
    assert check_cycle(state, "some_dispatcher", fp) is None


def test_cycle_detects_dispatcher_self_match():
    """Agent A with input X dispatching agent A with input X = 1-step cycle."""
    state = DispatchRunState()
    fp = fingerprint_node("agent_a", {"x": 1})
    state.fingerprints["A"] = fp
    result = check_cycle(state, "A", fp)
    assert result == "A"


def test_cycle_detects_grandparent_match():
    """A → B → C where C wants to dispatch something matching A's fingerprint."""
    state = DispatchRunState()
    fp_a = fingerprint_node("agent_a", {"x": 1})
    fp_b = fingerprint_node("agent_b", {})
    fp_c = fingerprint_node("agent_c", {})
    state.fingerprints["A"] = fp_a
    state.fingerprints["B"] = fp_b
    state.fingerprints["C"] = fp_c
    state.parents["B"] = "A"
    state.parents["C"] = "B"

    # C is about to dispatch something matching fp_a — caught
    assert check_cycle(state, "C", fp_a) == "A"


def test_no_cycle_when_different_inputs():
    state = DispatchRunState()
    state.fingerprints["A"] = fingerprint_node("agent_a", {"x": 1})
    state.parents["B"] = "A"
    state.fingerprints["B"] = fingerprint_node("agent_b", {})

    # B dispatching agent_a with DIFFERENT input — not a cycle
    assert check_cycle(state, "B", fingerprint_node("agent_a", {"x": 2})) is None


def test_cycle_stops_at_original_node():
    """If dispatcher has no parent entry, walk terminates — no infinite loop."""
    state = DispatchRunState()
    state.fingerprints["original"] = fingerprint_node("orig", {})
    # No entry in parents — walk terminates
    fp_new = fingerprint_node("new", {})
    assert check_cycle(state, "original", fp_new) is None


def test_cycle_detection_guards_against_bad_parent_loop():
    """Even if parent pointers form a cycle (shouldn't happen, defensive),
    the walk terminates without crashing."""
    state = DispatchRunState()
    state.parents["A"] = "B"
    state.parents["B"] = "A"
    fp_new = fingerprint_node("new", {})
    # Should return the first node visited a second time (defensive break)
    # rather than infinite-loop
    result = check_cycle(state, "A", fp_new)
    # Either None (no match) or a node name — what matters is it terminates
    assert result is None or isinstance(result, str)
