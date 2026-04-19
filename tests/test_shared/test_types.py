"""Tests for shared types."""

from temper_ai.shared.types import (
    AgentInterface,
    AgentResult,
    ExecutionContext,
    NodeResult,
    Status,
    TokenUsage,
)


class TestStatus:
    def test_enum_values(self):
        assert Status.PENDING == "pending"
        assert Status.RUNNING == "running"
        assert Status.COMPLETED == "completed"
        assert Status.FAILED == "failed"
        assert Status.SKIPPED == "skipped"

    def test_string_comparison(self):
        assert Status.COMPLETED == "completed"
        assert "running" == Status.RUNNING


class TestTokenUsage:
    def test_defaults(self):
        t = TokenUsage()
        assert t.prompt_tokens == 0
        assert t.completion_tokens == 0
        assert t.total_tokens == 0

    def test_values(self):
        t = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert t.total_tokens == 150


class TestAgentResult:
    def test_completed(self):
        r = AgentResult(status=Status.COMPLETED, output="done")
        assert r.status == Status.COMPLETED
        assert r.output == "done"
        assert r.error is None
        assert r.cost_usd == 0.0
        assert r.memories_formed == []

    def test_failed(self):
        r = AgentResult(status=Status.FAILED, output="", error="boom")
        assert r.error == "boom"


class TestNodeResult:
    def test_defaults(self):
        r = NodeResult(status=Status.COMPLETED)
        assert r.output == ""
        assert r.agent_results == []
        assert r.node_results == {}
        assert r.cost_usd == 0.0

    def test_with_agents(self):
        agent = AgentResult(status=Status.COMPLETED, output="ok")
        r = NodeResult(
            status=Status.COMPLETED,
            output="ok",
            agent_results=[agent],
            cost_usd=0.05,
            total_tokens=500,
        )
        assert len(r.agent_results) == 1
        assert r.cost_usd == 0.05


class TestExecutionContext:
    def test_get_llm(self):
        from unittest.mock import MagicMock
        mock_llm = MagicMock()
        ctx = ExecutionContext(
            run_id="r1", workflow_name="test",
            node_path="", agent_name="",
            event_recorder=MagicMock(),
            tool_executor=MagicMock(),
            llm_providers={"openai": mock_llm},
        )
        assert ctx.get_llm("openai") is mock_llm

    def test_get_llm_missing(self):
        from unittest.mock import MagicMock
        ctx = ExecutionContext(
            run_id="r1", workflow_name="test",
            node_path="", agent_name="",
            event_recorder=MagicMock(),
            tool_executor=MagicMock(),
        )
        import pytest
        with pytest.raises(KeyError, match="not configured"):
            ctx.get_llm("openai")


class TestAgentInterface:
    def test_defaults(self):
        i = AgentInterface()
        assert i.inputs == {}
        assert i.outputs == {}

    def test_with_values(self):
        i = AgentInterface(
            inputs={"task": "string"},
            outputs={"result": "dict"},
        )
        assert i.inputs["task"] == "string"
