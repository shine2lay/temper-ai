"""Tests for agent_observer module (src/agents/agent_observer.py).

Tests cover:
- AgentObserver initialization (tracker + context combinations)
- active property (tracker and agent_id checks)
- track_llm_call (success, no-op when inactive, exception handling)
- track_tool_call (success, no-op when inactive, exception handling)
"""
from unittest.mock import MagicMock


from src.agent.utils.agent_observer import AgentObserver


class TestAgentObserverInit:
    """Tests for AgentObserver initialization."""

    def test_with_tracker_and_context(self):
        tracker = MagicMock()
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(tracker, ctx)
        assert observer._tracker is tracker
        assert observer._agent_id == "agent-1"

    def test_with_none_tracker(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(None, ctx)
        assert observer._tracker is None
        assert observer._agent_id == "agent-1"

    def test_with_none_context(self):
        tracker = MagicMock()
        observer = AgentObserver(tracker, None)
        assert observer._tracker is tracker
        assert observer._agent_id is None

    def test_with_context_missing_agent_id(self):
        tracker = MagicMock()
        ctx = object()  # No agent_id attribute
        observer = AgentObserver(tracker, ctx)
        assert observer._agent_id is None


class TestActiveProperty:
    """Tests for the active property."""

    def test_active_when_both_present(self):
        tracker = MagicMock()
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(tracker, ctx)
        assert observer.active is True

    def test_inactive_when_no_tracker(self):
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(None, ctx)
        assert observer.active is False

    def test_inactive_when_no_agent_id(self):
        tracker = MagicMock()
        observer = AgentObserver(tracker, None)
        assert observer.active is False

    def test_inactive_when_both_missing(self):
        observer = AgentObserver(None, None)
        assert observer.active is False


class TestTrackLLMCall:
    """Tests for track_llm_call."""

    def test_delegates_to_tracker(self):
        tracker = MagicMock()
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(tracker, ctx)

        observer.track_llm_call(
            provider="ollama", model="qwen3",
            prompt="test", response="ok",
            prompt_tokens=10, completion_tokens=5,
            latency_ms=100, estimated_cost_usd=0.001,
        )
        tracker.track_llm_call.assert_called_once()
        data = tracker.track_llm_call.call_args[0][0]
        assert data.agent_id == "agent-1"
        assert data.provider == "ollama"
        assert data.model == "qwen3"

    def test_noop_when_inactive(self):
        tracker = MagicMock()
        observer = AgentObserver(tracker, None)

        observer.track_llm_call(provider="ollama", model="qwen3")
        tracker.track_llm_call.assert_not_called()

    def test_exception_logged_not_raised(self, caplog):
        tracker = MagicMock()
        tracker.track_llm_call.side_effect = RuntimeError("tracking error")
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(tracker, ctx)

        # Should not raise — incomplete kwargs cause TypeError, caught internally
        observer.track_llm_call(provider="ollama")
        assert "Failed to track LLM call" in caplog.text


class TestTrackToolCall:
    """Tests for track_tool_call."""

    def test_delegates_to_tracker(self):
        tracker = MagicMock()
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(tracker, ctx)

        observer.track_tool_call(
            tool_name="calculator",
            input_params={"x": 1},
            output_data={"result": 2},
            duration_seconds=0.1,
            status="success",
        )
        tracker.track_tool_call.assert_called_once()
        data = tracker.track_tool_call.call_args[0][0]
        assert data.agent_id == "agent-1"
        assert data.tool_name == "calculator"

    def test_noop_when_inactive(self):
        tracker = MagicMock()
        observer = AgentObserver(tracker, None)

        observer.track_tool_call(tool_name="calculator")
        tracker.track_tool_call.assert_not_called()

    def test_exception_logged_not_raised(self, caplog):
        tracker = MagicMock()
        tracker.track_tool_call.side_effect = RuntimeError("tracking error")
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        observer = AgentObserver(tracker, ctx)

        # Should not raise — incomplete kwargs cause TypeError, caught internally
        observer.track_tool_call(tool_name="calc")
        assert "Failed to track tool call" in caplog.text
