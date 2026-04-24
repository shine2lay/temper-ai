"""Tests for stage/dispatch.py — declarative dispatch renderer (tier 1)."""

import pytest

from temper_ai.stage.dispatch import (
    DispatchOp,
    DispatchRenderError,
    render_dispatch,
)

# ---------------------------------------------------------------------------
# No dispatch block — trivial case
# ---------------------------------------------------------------------------


def test_no_dispatch_returns_empty():
    assert render_dispatch({"name": "a"}) == []


def test_empty_dispatch_returns_empty():
    assert render_dispatch({"name": "a", "dispatch": []}) == []


def test_dispatch_not_a_list_raises():
    with pytest.raises(DispatchRenderError, match="must be a list"):
        render_dispatch({"dispatch": "not a list"})


# ---------------------------------------------------------------------------
# Single op, no for_each — basic add
# ---------------------------------------------------------------------------


def test_single_add_node():
    cfg = {
        "dispatch": [
            {"op": "add", "node": {"name": "extra", "type": "agent", "agent": "summarizer"}}
        ]
    }
    ops = render_dispatch(cfg)
    assert len(ops) == 1
    assert ops[0].op == "add"
    assert ops[0].node == {"name": "extra", "type": "agent", "agent": "summarizer"}
    assert ops[0].nodes == []


def test_single_add_uses_output_in_jinja():
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "node": {"name": "wrap_{{ output }}", "agent": "summarizer"},
            }
        ]
    }
    ops = render_dispatch(cfg, agent_output="hello")
    assert ops[0].node["name"] == "wrap_hello"


def test_single_add_reads_structured():
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "node": {
                    "name": "n",
                    "agent": "x",
                    "input_map": {"city": "{{ structured.city }}"},
                },
            }
        ]
    }
    ops = render_dispatch(cfg, agent_structured={"city": "Tokyo"})
    assert ops[0].node["input_map"]["city"] == "Tokyo"


def test_single_add_reads_input():
    cfg = {
        "dispatch": [
            {"op": "add", "node": {"name": "use_{{ input.user }}", "agent": "x"}}
        ]
    }
    ops = render_dispatch(cfg, agent_input_data={"user": "alice"})
    assert ops[0].node["name"] == "use_alice"


def test_add_requires_node_or_nodes():
    cfg = {"dispatch": [{"op": "add"}]}
    with pytest.raises(DispatchRenderError, match="exactly one of"):
        render_dispatch(cfg)


def test_add_rejects_both_node_and_nodes():
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "node": {"name": "a"},
                "nodes": [{"name": "b"}],
            }
        ]
    }
    with pytest.raises(DispatchRenderError, match="exactly one of"):
        render_dispatch(cfg)


def test_unknown_op_raises():
    cfg = {"dispatch": [{"op": "replace", "target": "x"}]}
    with pytest.raises(DispatchRenderError, match="must be 'add' or 'remove'"):
        render_dispatch(cfg)


# ---------------------------------------------------------------------------
# Subgraph (op=add with nodes list)
# ---------------------------------------------------------------------------


def test_add_subgraph_with_nodes_list():
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "nodes": [
                    {"name": "fetch", "type": "agent", "agent": "fetcher"},
                    {"name": "collate", "type": "agent", "agent": "collator",
                     "depends_on": ["fetch"]},
                ],
            }
        ]
    }
    ops = render_dispatch(cfg)
    assert len(ops) == 1
    assert ops[0].op == "add"
    assert len(ops[0].nodes) == 2
    assert ops[0].nodes[0]["name"] == "fetch"
    assert ops[0].nodes[1]["depends_on"] == ["fetch"]


def test_empty_nodes_list_raises():
    cfg = {"dispatch": [{"op": "add", "nodes": []}]}
    with pytest.raises(DispatchRenderError, match="non-empty list"):
        render_dispatch(cfg)


# ---------------------------------------------------------------------------
# for_each fan-out
# ---------------------------------------------------------------------------


def test_for_each_from_structured_list():
    """The day_allocator use case — structured output has a list, fan out per item."""
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "for_each": "structured.cities",
                "node": {
                    "name": "{{ item.city }}_research",
                    "type": "stage",
                    "strategy": "parallel",
                    "agents": ["activity_researcher"],
                    "input_map": {
                        "city": "{{ item.city }}",
                        "days": "{{ item.days }}",
                    },
                },
            }
        ]
    }
    ops = render_dispatch(
        cfg,
        agent_structured={
            "cities": [
                {"city": "Tokyo", "days": 3},
                {"city": "Kyoto", "days": 2},
            ]
        },
    )
    assert len(ops) == 2
    assert ops[0].node["name"] == "Tokyo_research"
    assert ops[0].node["input_map"]["days"] == "3"
    assert ops[1].node["name"] == "Kyoto_research"


def test_for_each_with_i_index():
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "for_each": "structured.items",
                "node": {"name": "n_{{ i }}", "agent": "x"},
            }
        ]
    }
    ops = render_dispatch(
        cfg, agent_structured={"items": ["a", "b", "c"]}
    )
    assert [o.node["name"] for o in ops] == ["n_0", "n_1", "n_2"]


def test_for_each_custom_as_var():
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "for_each": "structured.cities",
                "as": "city",
                "node": {"name": "r_{{ city }}", "agent": "x"},
            }
        ]
    }
    ops = render_dispatch(
        cfg, agent_structured={"cities": ["Tokyo", "Kyoto"]}
    )
    assert [o.node["name"] for o in ops] == ["r_Tokyo", "r_Kyoto"]


def test_for_each_invalid_as_raises():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": [1], "as": "not-a-var!",
             "node": {"name": "x", "agent": "y"}}
        ]
    }
    with pytest.raises(DispatchRenderError, match="valid identifier"):
        render_dispatch(cfg)


def test_for_each_literal_list():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": ["a", "b"],
             "node": {"name": "n_{{ item }}", "agent": "x"}}
        ]
    }
    ops = render_dispatch(cfg)
    assert [o.node["name"] for o in ops] == ["n_a", "n_b"]


def test_for_each_int_literal_expands_to_range():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": 3,
             "node": {"name": "n_{{ i }}", "agent": "x"}}
        ]
    }
    ops = render_dispatch(cfg)
    assert [o.node["name"] for o in ops] == ["n_0", "n_1", "n_2"]


def test_for_each_zero_produces_no_ops():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": 0, "node": {"name": "x", "agent": "y"}}
        ]
    }
    assert render_dispatch(cfg) == []


def test_for_each_negative_raises():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": -1, "node": {"name": "x", "agent": "y"}}
        ]
    }
    with pytest.raises(DispatchRenderError, match="non-negative"):
        render_dispatch(cfg)


def test_for_each_path_missing_raises():
    """Missing key on a non-empty structured still raises — that's a real
    config bug (referencing a field that the agent declared but never wrote).
    """
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": "structured.no_such_key",
             "node": {"name": "x", "agent": "y"}}
        ]
    }
    with pytest.raises(DispatchRenderError, match="not found"):
        render_dispatch(cfg, agent_structured={"some_other_key": "x"})


def test_for_each_empty_structured_is_noop():
    """Empty `structured_output` (e.g. upstream LLM API failed with no
    recovered JSON) yields zero iterations rather than crashing the phase.
    Lets the workflow proceed past a transient upstream failure.
    """
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": "structured.no_such_key",
             "node": {"name": "x", "agent": "y"}}
        ]
    }
    ops = render_dispatch(cfg, agent_structured={})
    assert ops == []


def test_for_each_path_wrong_type_raises():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": "structured.name",
             "node": {"name": "x", "agent": "y"}}
        ]
    }
    with pytest.raises(DispatchRenderError, match="expected list or int"):
        render_dispatch(cfg, agent_structured={"name": "Tokyo"})


def test_for_each_path_bad_scope_key_raises():
    cfg = {
        "dispatch": [
            {"op": "add", "for_each": "foo.bar",
             "node": {"name": "x", "agent": "y"}}
        ]
    }
    with pytest.raises(DispatchRenderError, match="valid scope key"):
        render_dispatch(cfg)


def test_for_each_with_subgraph_nodes():
    """Each iteration produces a subgraph, not a single node."""
    cfg = {
        "dispatch": [
            {
                "op": "add",
                "for_each": "structured.cities",
                "nodes": [
                    {"name": "fetch_{{ item }}", "agent": "fetcher",
                     "input_map": {"city": "{{ item }}"}},
                    {"name": "collate_{{ item }}", "agent": "collator",
                     "depends_on": ["fetch_{{ item }}"]},
                ],
            }
        ]
    }
    ops = render_dispatch(
        cfg, agent_structured={"cities": ["Tokyo", "Kyoto"]}
    )
    assert len(ops) == 2
    assert [n["name"] for n in ops[0].nodes] == ["fetch_Tokyo", "collate_Tokyo"]
    assert ops[0].nodes[1]["depends_on"] == ["fetch_Tokyo"]
    assert [n["name"] for n in ops[1].nodes] == ["fetch_Kyoto", "collate_Kyoto"]


# ---------------------------------------------------------------------------
# op=remove
# ---------------------------------------------------------------------------


def test_remove_op():
    cfg = {"dispatch": [{"op": "remove", "target": "placeholder"}]}
    ops = render_dispatch(cfg)
    assert len(ops) == 1
    assert ops[0].op == "remove"
    assert ops[0].target == "placeholder"


def test_remove_target_can_be_jinja():
    cfg = {"dispatch": [{"op": "remove", "target": "old_{{ structured.key }}"}]}
    ops = render_dispatch(cfg, agent_structured={"key": "X"})
    assert ops[0].target == "old_X"


def test_remove_requires_target():
    cfg = {"dispatch": [{"op": "remove"}]}
    with pytest.raises(DispatchRenderError, match="target"):
        render_dispatch(cfg)


def test_remove_empty_target_raises():
    cfg = {"dispatch": [{"op": "remove", "target": ""}]}
    with pytest.raises(DispatchRenderError, match="non-empty"):
        render_dispatch(cfg)


def test_remove_with_for_each_fans_out():
    cfg = {
        "dispatch": [
            {"op": "remove", "for_each": ["a", "b"],
             "target": "placeholder_{{ item }}"}
        ]
    }
    ops = render_dispatch(cfg)
    assert [o.target for o in ops] == ["placeholder_a", "placeholder_b"]


# ---------------------------------------------------------------------------
# Structural validation (the "agent messed up" cases)
# ---------------------------------------------------------------------------


def test_node_missing_name_raises():
    cfg = {"dispatch": [{"op": "add", "node": {"type": "agent", "agent": "x"}}]}
    with pytest.raises(DispatchRenderError, match="missing `name`"):
        render_dispatch(cfg)


def test_node_missing_type_agent_all_raises():
    cfg = {"dispatch": [{"op": "add", "node": {"name": "x"}}]}
    with pytest.raises(DispatchRenderError, match="no `type`, `agent`"):
        render_dispatch(cfg)


def test_jinja_error_wrapped():
    cfg = {
        "dispatch": [
            {"op": "add", "node": {"name": "x", "agent": "{{ undefined_var }}"}}
        ]
    }
    with pytest.raises(DispatchRenderError, match="Jinja render failed"):
        render_dispatch(cfg)


def test_multiple_ops_in_one_block():
    """Mixed ops in one dispatch block — all rendered in order."""
    cfg = {
        "dispatch": [
            {"op": "add", "node": {"name": "first", "agent": "a"}},
            {"op": "remove", "target": "placeholder"},
            {"op": "add", "for_each": [1, 2], "node": {"name": "n_{{ item }}", "agent": "b"}},
        ]
    }
    ops = render_dispatch(cfg)
    assert [o.op for o in ops] == ["add", "remove", "add", "add"]
    assert ops[0].node["name"] == "first"
    assert ops[1].target == "placeholder"
    assert ops[2].node["name"] == "n_1"
    assert ops[3].node["name"] == "n_2"


def test_dispatch_op_all_added_nodes_helper():
    """DispatchOp.all_added_nodes flattens single + subgraph, returns [] for remove."""
    single = DispatchOp(op="add", node={"name": "a"})
    assert single.all_added_nodes() == [{"name": "a"}]

    subgraph = DispatchOp(op="add", nodes=[{"name": "a"}, {"name": "b"}])
    assert subgraph.all_added_nodes() == [{"name": "a"}, {"name": "b"}]

    remove = DispatchOp(op="remove", target="x")
    assert remove.all_added_nodes() == []
