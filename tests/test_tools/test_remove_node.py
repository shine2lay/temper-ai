"""Tests for RemoveNode tool — tier 2 imperative dispatch."""

from unittest.mock import MagicMock

from temper_ai.stage.dispatch_limits import DispatchRunState
from temper_ai.tools.remove_node import RemoveNode


def _bound_tool() -> RemoveNode:
    tool = RemoveNode()
    ctx = MagicMock()
    ctx.node_path = "parent"
    ctx.agent_name = "parent"
    ctx.dispatch_state = None
    tool.bind_context(ctx)
    return tool


def test_unbound_returns_error():
    tool = RemoveNode()
    result = tool.execute(target="x")
    assert result.success is False
    assert "not bound" in (result.error or "")


def test_requires_target():
    tool = _bound_tool()
    result = tool.execute()
    assert result.success is False
    assert "target" in (result.error or "").lower()


def test_empty_target_rejected():
    tool = _bound_tool()
    result = tool.execute(target="")
    assert result.success is False


def test_queues_remove_op():
    tool = _bound_tool()
    result = tool.execute(target="placeholder")
    assert result.success is True

    state = tool._execution_context.dispatch_state
    op = state.pending_ops["parent"][0]
    assert op.op == "remove"
    assert op.target == "placeholder"


def test_add_and_remove_buffer_together():
    """AddNode and RemoveNode ops accumulate in the same per-path list."""
    from temper_ai.tools.add_node import AddNode

    ctx = MagicMock()
    ctx.node_path = "p"
    ctx.agent_name = "p"
    ctx.dispatch_state = None

    add = AddNode()
    rm = RemoveNode()
    add.bind_context(ctx)
    rm.bind_context(ctx)

    add.execute(name="new1", agent="x")
    rm.execute(target="old1")
    add.execute(name="new2", agent="y")

    ops = ctx.dispatch_state.pending_ops["p"]
    assert [o.op for o in ops] == ["add", "remove", "add"]
    assert ops[0].node["name"] == "new1"
    assert ops[1].target == "old1"
    assert ops[2].node["name"] == "new2"


def test_lazily_seeds_dispatch_state():
    tool = RemoveNode()
    ctx = MagicMock()
    ctx.node_path = "p"
    ctx.agent_name = "p"
    ctx.dispatch_state = None
    tool.bind_context(ctx)

    tool.execute(target="x")
    assert isinstance(ctx.dispatch_state, DispatchRunState)
