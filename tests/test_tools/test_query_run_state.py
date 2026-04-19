"""Tests for QueryRunState — live workflow-state introspection tool."""

import json
from unittest.mock import MagicMock

from temper_ai.shared.types import NodeResult, Status
from temper_ai.tools.query_run_state import QueryRunState


def _node(output="ok", structured=None, status=Status.COMPLETED, error=None):
    return NodeResult(
        status=status,
        output=output,
        structured_output=structured,
        error=error,
    )


def _tool_with_state(run_state):
    tool = QueryRunState()
    ctx = MagicMock()
    ctx.run_state = run_state
    tool.bind_context(ctx)
    return tool


def test_returns_error_when_not_bound():
    tool = QueryRunState()
    result = tool.execute()
    assert result.success is False
    assert "not bound" in (result.error or "")


def test_returns_empty_list_when_run_state_missing():
    """bind_context was called but executor hasn't populated run_state yet."""
    tool = QueryRunState()
    ctx = MagicMock()
    ctx.run_state = None
    tool.bind_context(ctx)
    result = tool.execute()
    assert result.success is True
    assert json.loads(result.result) == []


def test_returns_all_nodes_by_default():
    tool = _tool_with_state({
        "scout": _node(output="found 3 angles"),
        "planner": _node(output="3 posts planned", structured={"post_count": 3}),
    })
    result = tool.execute()
    assert result.success is True
    data = json.loads(result.result)
    names = {n["node_name"] for n in data}
    assert names == {"scout", "planner"}


def test_node_entry_has_status_output_and_structured():
    tool = _tool_with_state({
        "planner": _node(output="plan text", structured={"posts": ["a", "b"]}),
    })
    data = json.loads(tool.execute().result)
    assert len(data) == 1
    entry = data[0]
    assert entry["node_name"] == "planner"
    assert entry["status"] == "completed"
    assert entry["output"] == "plan text"
    assert entry["structured_output"] == {"posts": ["a", "b"]}


def test_node_names_filter():
    tool = _tool_with_state({
        "scout": _node(output="a"),
        "planner": _node(output="b"),
        "drafter": _node(output="c"),
    })
    data = json.loads(tool.execute(node_names=["scout", "drafter"]).result)
    names = {n["node_name"] for n in data}
    assert names == {"scout", "drafter"}


def test_truncation_flags_long_output():
    long_output = "x" * 5000
    tool = _tool_with_state({"big": _node(output=long_output)})
    data = json.loads(tool.execute(truncate_chars=100).result)
    entry = data[0]
    assert entry["output"] == "x" * 100
    assert entry["output_truncated"] is True
    assert entry["output_full_length"] == 5000


def test_truncate_zero_disables_truncation():
    long_output = "x" * 5000
    tool = _tool_with_state({"big": _node(output=long_output)})
    data = json.loads(tool.execute(truncate_chars=0).result)
    entry = data[0]
    assert entry["output"] == long_output
    assert "output_truncated" not in entry


def test_include_outputs_false_omits_output():
    tool = _tool_with_state({"n1": _node(output="secret", structured={"x": 1})})
    data = json.loads(tool.execute(include_outputs=False).result)
    entry = data[0]
    assert "output" not in entry
    assert entry["structured_output"] == {"x": 1}


def test_include_structured_false_omits_structured():
    tool = _tool_with_state({"n1": _node(output="plain", structured={"x": 1})})
    data = json.loads(tool.execute(include_structured=False).result)
    entry = data[0]
    assert entry["output"] == "plain"
    assert "structured_output" not in entry


def test_error_included_when_node_failed():
    tool = _tool_with_state({
        "broken": _node(status=Status.FAILED, output="", error="timeout after 60s"),
    })
    data = json.loads(tool.execute().result)
    entry = data[0]
    assert entry["status"] == "failed"
    assert entry["error"] == "timeout after 60s"


def test_structured_output_omitted_when_none():
    """None structured_output shouldn't appear as a null field — cleaner JSON."""
    tool = _tool_with_state({"n1": _node(output="x", structured=None)})
    data = json.loads(tool.execute().result)
    entry = data[0]
    assert "structured_output" not in entry


def test_status_coerces_enum_and_string():
    tool = _tool_with_state({
        "a": _node(status=Status.COMPLETED),
        "b": _node(status=Status.RUNNING),
        "c": _node(status=Status.FAILED),
    })
    data = json.loads(tool.execute().result)
    statuses = {n["node_name"]: n["status"] for n in data}
    assert statuses == {"a": "completed", "b": "running", "c": "failed"}
