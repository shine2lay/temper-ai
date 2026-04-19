"""Tests for stage/agent_node.py — retry-on-empty and exception behavior."""

from unittest.mock import MagicMock, patch

from temper_ai.shared.types import (
    AgentResult,
    ExecutionContext,
    Status,
    TokenUsage,
)
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig


def _make_context():
    recorder = MagicMock()
    recorder.record.return_value = "evt-1"
    return ExecutionContext(
        run_id="run-1",
        workflow_name="test",
        node_path="",
        agent_name="",
        event_recorder=recorder,
        tool_executor=MagicMock(),
    )


def _result(output="ok", status=Status.COMPLETED, tokens=10, cost=0.01):
    return AgentResult(
        status=status,
        output=output,
        tokens=TokenUsage(total_tokens=tokens),
        cost_usd=cost,
    )


def _make_node():
    nc = NodeConfig(name="n1")
    return AgentNode(nc, {"name": "n1", "type": "llm"})


@patch("temper_ai.stage.agent_node.time.sleep", lambda _s: None)
@patch("temper_ai.stage.agent_node.create_agent")
def test_retries_on_empty_then_succeeds(create_agent):
    """Empty output first attempt → retry → success on second attempt."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.side_effect = [_result(output=""), _result(output="final")]
    create_agent.return_value = agent

    node = _make_node()
    result = node.run({}, _make_context())

    assert agent.run.call_count == 2
    assert result.status == Status.COMPLETED
    assert result.output == "final"


@patch("temper_ai.stage.agent_node.time.sleep", lambda _s: None)
@patch("temper_ai.stage.agent_node.create_agent")
def test_returns_last_result_when_all_attempts_empty(create_agent):
    """Every attempt returns empty → node returns the last result (with empty output)."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.side_effect = [_result(output=""), _result(output="")]
    create_agent.return_value = agent

    node = _make_node()
    result = node.run({}, _make_context())

    assert agent.run.call_count == AgentNode.MAX_RETRIES
    # We still return the last result (don't mark FAILED just for empty output)
    assert result.output == ""


@patch("temper_ai.stage.agent_node.time.sleep", lambda _s: None)
@patch("temper_ai.stage.agent_node.create_agent")
def test_retries_on_exception_then_succeeds(create_agent):
    """Exception on first attempt → retry → success on second attempt."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.side_effect = [RuntimeError("transient"), _result(output="ok")]
    create_agent.return_value = agent

    node = _make_node()
    result = node.run({}, _make_context())

    assert agent.run.call_count == 2
    assert result.status == Status.COMPLETED
    assert result.output == "ok"


@patch("temper_ai.stage.agent_node.time.sleep", lambda _s: None)
@patch("temper_ai.stage.agent_node.create_agent")
def test_returns_failed_when_all_attempts_raise(create_agent):
    """All attempts raise → node returns FAILED with the exception message."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.side_effect = [RuntimeError("boom"), RuntimeError("boom again")]
    create_agent.return_value = agent

    node = _make_node()
    result = node.run({}, _make_context())

    assert agent.run.call_count == AgentNode.MAX_RETRIES
    assert result.status == Status.FAILED
    assert "boom again" in (result.error or "")


@patch("temper_ai.stage.agent_node.time.sleep", lambda _s: None)
@patch("temper_ai.stage.agent_node.create_agent")
def test_no_retry_when_first_attempt_succeeds(create_agent):
    """Happy path: non-empty first attempt → single call, no retry."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.return_value = _result(output="done")
    create_agent.return_value = agent

    node = _make_node()
    result = node.run({}, _make_context())

    assert agent.run.call_count == 1
    assert result.output == "done"
