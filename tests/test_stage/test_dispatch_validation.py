"""Tests for stage/dispatch_validation.py — static validation of dispatch: blocks."""

from unittest.mock import MagicMock

from temper_ai.stage.dispatch_validation import validate_dispatch_block


def _store_with(known_agents: set[str] | None = None):
    """Mock config store that recognizes `known_agents` and rejects others."""
    store = MagicMock()
    known = known_agents or set()

    def _get(name, type_):
        if type_ == "agent" and name in known:
            return {"agent": {"name": name}}
        raise KeyError(f"unknown agent: {name}")
    store.get.side_effect = _get
    return store


# ---------------------------------------------------------------------------
# No-dispatch and structural shape
# ---------------------------------------------------------------------------


def test_no_dispatch_key_returns_empty():
    errors = validate_dispatch_block("a", {"name": "a"}, _store_with(), set())
    assert errors == []


def test_dispatch_not_a_list():
    errors = validate_dispatch_block(
        "a", {"dispatch": "bad"}, _store_with(), set(),
    )
    assert any("must be a list" in e for e in errors)


def test_op_not_a_dict():
    errors = validate_dispatch_block(
        "a", {"dispatch": ["bad"]}, _store_with(), set(),
    )
    assert any("must be a dict" in e for e in errors)


def test_unknown_op_name():
    errors = validate_dispatch_block(
        "a", {"dispatch": [{"op": "replace", "target": "x"}]}, _store_with(), set(),
    )
    assert any("'add' or 'remove'" in e for e in errors)


# ---------------------------------------------------------------------------
# op=add structural
# ---------------------------------------------------------------------------


def test_add_missing_node_and_nodes():
    errors = validate_dispatch_block(
        "a", {"dispatch": [{"op": "add"}]}, _store_with(), set(),
    )
    assert any("exactly one of" in e for e in errors)


def test_add_both_node_and_nodes():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {"name": "x", "agent": "y"},
            "nodes": [{"name": "z", "agent": "y"}],
        }]},
        _store_with({"y"}), set(),
    )
    assert any("exactly one of" in e for e in errors)


def test_add_node_not_a_dict():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "node": "not a dict"}]},
        _store_with(), set(),
    )
    assert any("`node:` must be a dict" in e for e in errors)


def test_add_nodes_empty_list():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "nodes": []}]},
        _store_with(), set(),
    )
    assert any("non-empty list" in e for e in errors)


def test_added_node_missing_name():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "node": {"agent": "y"}}]},
        _store_with({"y"}), set(),
    )
    assert any("name" in e.lower() for e in errors)


def test_added_node_missing_agent_and_type():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "node": {"name": "x"}}]},
        _store_with(), set(),
    )
    assert any("agent" in e.lower() and "agents" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Agent ref resolution
# ---------------------------------------------------------------------------


def test_unknown_agent_ref_is_error():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "node": {"name": "x", "agent": "ghost"}}]},
        _store_with({"real_agent"}), set(),
    )
    assert any("ghost" in e and "not found" in e for e in errors)


def test_known_agent_ref_passes():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "node": {"name": "x", "agent": "known"}}]},
        _store_with({"known"}), set(),
    )
    assert errors == []


def test_jinja_agent_ref_skipped():
    """Agent ref with Jinja markers — can't validate statically, skip."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {"name": "x", "agent": "{{ structured.kind }}_agent"},
        }]},
        _store_with(), set(),
    )
    assert errors == []


def test_agents_list_unknown_ref():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {"name": "stage_x", "agents": ["known", "ghost"]},
        }]},
        _store_with({"known"}), set(),
    )
    assert any("ghost" in e and "not found" in e for e in errors)


def test_no_config_store_skips_agent_ref_check():
    """Tests without a store can't check agent refs — skip instead of false-positive."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "add", "node": {"name": "x", "agent": "any"}}]},
        None, set(),
    )
    assert errors == []


# ---------------------------------------------------------------------------
# for_each validation
# ---------------------------------------------------------------------------


def test_for_each_list_ok():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": [1, 2, 3],
            "node": {"name": "n_{{ item }}", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


def test_for_each_int_ok():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": 5,
            "node": {"name": "n_{{ i }}", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


def test_for_each_scope_path_ok():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": "structured.items",
            "node": {"name": "n_{{ item }}", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


def test_for_each_bad_scope_root():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": "foo.bar",
            "node": {"name": "x", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert any("input.'" in e or "output.'" in e or "structured.'" in e
               for e in errors)


def test_for_each_negative_int():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": -1,
            "node": {"name": "x", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert any("non-negative" in e for e in errors)


def test_for_each_bad_type():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": {"not": "allowed"},
            "node": {"name": "x", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert any("list, int, or string path" in e for e in errors)


def test_for_each_bool_rejected():
    """bool is int subclass — explicitly reject so users don't shoot foot."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add", "for_each": True,
            "node": {"name": "x", "agent": "y"},
        }]},
        _store_with({"y"}), set(),
    )
    assert any("bool" in e for e in errors)


# ---------------------------------------------------------------------------
# input_map source refs
# ---------------------------------------------------------------------------


def test_input_map_known_node_ok():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "input_map": {"data": "known_node.output"},
            },
        }]},
        _store_with({"y"}),
        known_node_names={"known_node"},
    )
    assert errors == []


def test_input_map_unknown_node_flagged():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "input_map": {"data": "ghost.output"},
            },
        }]},
        _store_with({"y"}),
        known_node_names=set(),
    )
    assert any("ghost" in e for e in errors)


def test_input_map_input_and_workflow_always_allowed():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "input_map": {
                    "a": "input.foo",
                    "b": "workflow.bar",
                },
            },
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


def test_input_map_jinja_source_skipped():
    """Source contains Jinja — resolved at render time, skip static check."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "input_map": {"data": "{{ item.producer }}.output"},
            },
        }]},
        _store_with({"y"}),
        known_node_names=set(),
    )
    assert errors == []


def test_input_map_sibling_subgraph_node_allowed():
    """A node can depend on another node in the SAME add-op's nodes list."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "nodes": [
                {"name": "fetch", "agent": "y"},
                {"name": "collate", "agent": "y", "depends_on": ["fetch"]},
            ],
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


def test_input_map_literal_value_no_dot_skipped():
    """Source without a dot is a literal, not a node ref — don't flag."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "input_map": {"city": "Tokyo"},   # literal, not a ref
            },
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


# ---------------------------------------------------------------------------
# depends_on
# ---------------------------------------------------------------------------


def test_depends_on_unknown_node():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "depends_on": ["ghost"],
            },
        }]},
        _store_with({"y"}), set(),
    )
    assert any("depends_on" in e and "ghost" in e for e in errors)


def test_depends_on_jinja_skipped():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {
                "name": "n", "agent": "y",
                "depends_on": ["{{ item.parent }}"],
            },
        }]},
        _store_with({"y"}), set(),
    )
    assert errors == []


# ---------------------------------------------------------------------------
# op=remove
# ---------------------------------------------------------------------------


def test_remove_requires_target():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "remove"}]},
        _store_with(), set(),
    )
    assert any("target" in e for e in errors)


def test_remove_empty_target():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "remove", "target": ""}]},
        _store_with(), set(),
    )
    assert any("target" in e for e in errors)


def test_remove_with_valid_target_passes():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{"op": "remove", "target": "placeholder"}]},
        _store_with(), set(),
    )
    assert errors == []


# ---------------------------------------------------------------------------
# v1-unsupported constructs
# ---------------------------------------------------------------------------


def test_nested_template_flagged():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {"name": "x", "type": "template", "for_each": 3},
        }]},
        _store_with(), set(),
    )
    assert any("template" in e and "not supported" in e for e in errors)


def test_loop_to_inside_dispatched_node_flagged():
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [{
            "op": "add",
            "node": {"name": "x", "agent": "y", "loop_to": "x"},
        }]},
        _store_with({"y"}), set(),
    )
    assert any("loop_to" in e and "not supported" in e for e in errors)


# ---------------------------------------------------------------------------
# Multi-op / full block
# ---------------------------------------------------------------------------


def test_multi_op_collects_all_errors():
    """Errors across multiple ops all surface, not just the first."""
    errors = validate_dispatch_block(
        "a",
        {"dispatch": [
            {"op": "invalid_op"},
            {"op": "add"},   # missing node/nodes
            {"op": "remove"},   # missing target
        ]},
        _store_with(), set(),
    )
    # All three bad ops should be flagged
    assert len(errors) >= 3
