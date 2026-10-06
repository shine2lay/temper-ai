"""Tests for stage/agent_node.py — retry-on-empty and exception behavior."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.shared.types import (
    AgentResult,
    ExecutionContext,
    Status,
    TokenUsage,
)
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.exceptions import CancellationError, ReplacedByLaterAttempt
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
def test_no_retry_when_the_empty_output_has_a_reason(create_agent):
    """Empty output *with* an error (max iterations, timeout, budget) is a verdict,
    not a glitch: re-running a 40-iteration exploration doubles its cost and ends
    the same way. Seen live: a planner hit its cap at 570k tokens and was run again."""
    agent = MagicMock()
    agent.name = "n1"
    capped = AgentResult(status=Status.FAILED, output="", error="Reached max iterations (40)")
    agent.run.side_effect = [capped, _result(output="would be a second full run")]
    create_agent.return_value = agent

    result = _make_node().run({}, _make_context())

    assert agent.run.call_count == 1
    assert result.output == ""
    assert "max iterations" in (result.error or "")


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


@patch("temper_ai.stage.agent_node.create_agent")
def test_an_attempt_replaced_by_a_later_one_goes_up_at_once(create_agent):
    """SW-84: a later attempt of the run took the step over. A retry would be this stale
    attempt starting the step again under the newer one, so it goes up on the first call:
    no second call, no backoff sleep."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.side_effect = [ReplacedByLaterAttempt("taken over"), _result(output="a retry")]
    create_agent.return_value = agent

    with patch("temper_ai.stage.agent_node.time.sleep") as sleep, \
            pytest.raises(ReplacedByLaterAttempt, match="taken over"):
        _make_node().run({}, _make_context())

    assert agent.run.call_count == 1
    sleep.assert_not_called()


@patch("temper_ai.stage.agent_node.create_agent")
def test_a_plain_stop_keeps_its_retry(create_agent):
    """Only the replaced attempt skips the retry: a plain CancellationError is retried after
    the usual backoff and then ends the step FAILED, as before SW-84."""
    agent = MagicMock()
    agent.name = "n1"
    agent.run.side_effect = [CancellationError("stopped"), CancellationError("stopped again")]
    create_agent.return_value = agent

    with patch("temper_ai.stage.agent_node.time.sleep") as sleep:
        result = _make_node().run({}, _make_context())

    assert agent.run.call_count == AgentNode.MAX_RETRIES
    sleep.assert_called_once_with(2)
    assert result.status == Status.FAILED
    assert "stopped again" in (result.error or "")
