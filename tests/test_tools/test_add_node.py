"""Tests for AddNode tool — tier 2 imperative dispatch."""

from unittest.mock import MagicMock

from temper_ai.stage.dispatch import DispatchOp
from temper_ai.stage.dispatch_limits import DispatchRunState
from temper_ai.tools.add_node import AddNode


def _bound_tool(node_path: str = "parent", agent_name: str = "parent") -> AddNode:
    """Make an AddNode bound to a fresh ExecutionContext-like mock."""
    tool = AddNode()
    ctx = MagicMock()
    ctx.node_path = node_path
    ctx.agent_name = agent_name
    ctx.dispatch_state = None
    tool.bind_context(ctx)
    return tool


def test_unbound_returns_error():
    tool = AddNode()
    result = tool.execute(name="x", agent="y")
    assert result.success is False
    assert "not bound" in (result.error or "")


def test_requires_name():
    tool = _bound_tool()
    result = tool.execute(agent="y")
    assert result.success is False
    assert "name" in (result.error or "").lower()


def test_empty_name_rejected():
    tool = _bound_tool()
    result = tool.execute(name="", agent="y")
    assert result.success is False


def test_needs_agent_or_agents():
    tool = _bound_tool()
    result = tool.execute(name="x")
    assert result.success is False
    assert "agent" in (result.error or "").lower()


def test_infers_type_from_agent():
    tool = _bound_tool()
    result = tool.execute(name="x", agent="researcher")
    assert result.success is True
    op = tool._execution_context.dispatch_state.pending_ops["parent"][0]
    assert op.node["type"] == "agent"
    assert op.node["agent"] == "researcher"


def test_infers_type_from_agents_list():
    tool = _bound_tool()
    result = tool.execute(
        name="stage_x",
        agents=["a", "b"],
        strategy="parallel",
    )
    assert result.success is True
    op = tool._execution_context.dispatch_state.pending_ops["parent"][0]
    assert op.node["type"] == "stage"
    assert op.node["agents"] == ["a", "b"]
    assert op.node["strategy"] == "parallel"


def test_explicit_type_honored():
    tool = _bound_tool()
    tool.execute(name="x", type="agent", agent="r")
    op = tool._execution_context.dispatch_state.pending_ops["parent"][0]
    assert op.node["type"] == "agent"


def test_queues_op_with_depends_on_and_input_map():
    tool = _bound_tool()
    tool.execute(
        name="follower",
        agent="post_processor",
        depends_on=["parent"],
        input_map={"data": "parent.output"},
    )
    op = tool._execution_context.dispatch_state.pending_ops["parent"][0]
    assert op.op == "add"
    assert op.node["name"] == "follower"
    assert op.node["depends_on"] == ["parent"]
    assert op.node["input_map"] == {"data": "parent.output"}


def test_keys_buffer_by_node_path():
    """Different node_paths buffer into different dict keys — parallel agents
    don't mix ops."""
    tool_a = _bound_tool(node_path="stage.a", agent_name="a")
    tool_b = _bound_tool(node_path="stage.b", agent_name="b")
    # Share the same dispatch_state so they'd collide if keying were broken
    shared_state = DispatchRunState()
    tool_a._execution_context.dispatch_state = shared_state
    tool_b._execution_context.dispatch_state = shared_state

    tool_a.execute(name="from_a", agent="x")
    tool_b.execute(name="from_b", agent="y")

    assert "stage.a" in shared_state.pending_ops
    assert "stage.b" in shared_state.pending_ops
    assert len(shared_state.pending_ops["stage.a"]) == 1
    assert len(shared_state.pending_ops["stage.b"]) == 1


def test_multiple_calls_append():
    tool = _bound_tool()
    tool.execute(name="n1", agent="x")
    tool.execute(name="n2", agent="y")
    ops = tool._execution_context.dispatch_state.pending_ops["parent"]
    assert [o.node["name"] for o in ops] == ["n1", "n2"]


def test_lazily_seeds_dispatch_state():
    """Context starts with dispatch_state=None — tool creates it on first use."""
    tool = AddNode()
    ctx = MagicMock()
    ctx.node_path = "p"
    ctx.agent_name = "p"
    ctx.dispatch_state = None
    tool.bind_context(ctx)

    tool.execute(name="x", agent="y")
    assert isinstance(ctx.dispatch_state, DispatchRunState)
    assert isinstance(ctx.dispatch_state.pending_ops["p"][0], DispatchOp)


def test_fallback_to_agent_name_when_no_path():
    """Node_path empty → use agent_name as the buffer key (degenerate case)."""
    tool = AddNode()
    ctx = MagicMock()
    ctx.node_path = ""
    ctx.agent_name = "lone_agent"
    ctx.dispatch_state = None
    tool.bind_context(ctx)

    tool.execute(name="x", agent="y")
    assert "lone_agent" in ctx.dispatch_state.pending_ops
