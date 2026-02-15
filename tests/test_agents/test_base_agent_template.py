"""Tests for BaseAgent template method pattern.

Verifies hook invocation order, error handling, response building,
timeout checking, and setup extraction.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.agents.base_agent import AgentResponse, BaseAgent, ExecutionContext
from src.compiler.schemas import AgentConfig


# ============================================================================
# Fixtures
# ============================================================================


def _make_config(name: str = "test_agent") -> AgentConfig:
    """Build a minimal AgentConfig for testing."""
    return AgentConfig(
        agent={
            "name": name,
            "description": "test",
            "version": "1.0",
            "inference": {"provider": "ollama", "model": "test-model"},
            "prompt": {"inline": "Test prompt"},
            "tools": [],
            "error_handling": {
                "retry_strategy": "ExponentialBackoff",
                "fallback": "GracefulDegradation",
            },
        }
    )


class RecordingAgent(BaseAgent):
    """Agent that records hook invocations for testing."""

    def __init__(self, config: AgentConfig):
        with patch("src.agents.base_agent.create_llm_from_config"):
            super().__init__(config)
        self.call_order: list[str] = []
        self._run_response = AgentResponse(output="run output")

    def _run(self, input_data, context=None, start_time=0.0):
        self.call_order.append("_run")
        return self._run_response

    def _on_setup(self, input_data, context):
        self.call_order.append("_on_setup")

    def _on_before_run(self, input_data, context):
        self.call_order.append("_on_before_run")
        return input_data

    def _on_after_run(self, result):
        self.call_order.append("_on_after_run")
        return result

    def _on_error(self, error, start_time):
        self.call_order.append("_on_error")
        return None  # let default error handling proceed

    def get_capabilities(self):
        return {"type": "recording"}


# ============================================================================
# Hook invocation order
# ============================================================================


class TestHookOrder:
    """Verify hooks are called in the correct order."""

    def test_successful_execution_order(self):
        """Hooks fire: _on_setup → _on_before_run → _run → _on_after_run."""
        agent = RecordingAgent(_make_config())
        agent.execute({"query": "test"})

        assert agent.call_order == [
            "_on_setup",
            "_on_before_run",
            "_run",
            "_on_after_run",
        ]

    def test_error_execution_order(self):
        """On error: _on_setup → _on_before_run → _run → _on_error."""
        agent = RecordingAgent(_make_config())
        agent._run_response = None  # will cause _run to still be called

        # Make _run raise
        def failing_run(input_data, context=None, start_time=0.0):
            agent.call_order.append("_run")
            raise ValueError("test error")

        agent._run = failing_run  # type: ignore[assignment]
        response = agent.execute({"query": "test"})

        assert "_on_setup" in agent.call_order
        assert "_on_before_run" in agent.call_order
        assert "_run" in agent.call_order
        assert "_on_error" in agent.call_order
        assert response.error is not None

    def test_on_before_run_can_modify_input(self):
        """_on_before_run can modify input_data before _run sees it."""
        agent = RecordingAgent(_make_config())
        received_input = {}

        original_run = agent._run

        def capturing_run(input_data, context=None, start_time=0.0):
            received_input.update(input_data)
            return original_run(input_data, context, start_time)

        agent._run = capturing_run  # type: ignore[assignment]

        def inject_key(input_data, context):
            agent.call_order.append("_on_before_run")
            input_data["injected"] = True
            return input_data

        agent._on_before_run = inject_key  # type: ignore[assignment]
        agent.execute({"query": "test"})

        assert received_input.get("injected") is True


# ============================================================================
# Error hook override
# ============================================================================


class TestErrorHookOverride:
    """Verify _on_error can override default error response."""

    def test_on_error_override_returns_custom_response(self):
        """If _on_error returns AgentResponse, that response is used."""
        agent = RecordingAgent(_make_config())
        custom = AgentResponse(output="custom error handled")

        def custom_error_handler(error, start_time):
            return custom

        agent._on_error = custom_error_handler  # type: ignore[assignment]

        def failing_run(input_data, context=None, start_time=0.0):
            raise RuntimeError("boom")

        agent._run = failing_run  # type: ignore[assignment]
        response = agent.execute({"query": "test"})

        assert response is custom
        assert response.output == "custom error handled"
        assert response.error is None

    def test_on_error_returns_none_uses_default(self):
        """If _on_error returns None, default error response is built."""
        agent = RecordingAgent(_make_config())

        def failing_run(input_data, context=None, start_time=0.0):
            raise RuntimeError("default path")

        agent._run = failing_run  # type: ignore[assignment]
        response = agent.execute({"query": "test"})

        assert response.error is not None
        assert "default path" in response.error


# ============================================================================
# Response building
# ============================================================================


class TestBuildResponse:
    """Test _build_response and _build_error_response."""

    def test_build_response_basic(self):
        """_build_response creates AgentResponse with metrics."""
        agent = RecordingAgent(_make_config())
        start = time.time()
        response = agent._build_response(
            output="hello",
            reasoning="thought",
            tool_calls=[],
            tokens=100,
            cost=0.01,
            start_time=start,
        )
        assert response.output == "hello"
        assert response.reasoning == "thought"
        assert response.tokens == 100
        assert response.estimated_cost_usd == 0.01
        assert response.error is None
        assert response.latency_seconds >= 0

    def test_build_error_response(self):
        """_build_error_response creates error AgentResponse."""
        agent = RecordingAgent(_make_config())
        start = time.time()
        response = agent._build_error_response(
            RuntimeError("oops"), start
        )
        assert response.error is not None
        assert "oops" in response.error
        assert response.output == ""


# ============================================================================
# Setup extraction
# ============================================================================


class TestSetup:
    """Test _setup extracts infrastructure from input_data."""

    def test_extracts_tracker(self):
        """_setup extracts tracker from input_data."""
        agent = RecordingAgent(_make_config())
        mock_tracker = MagicMock()
        agent._setup({"tracker": mock_tracker}, None)
        assert agent.tracker is mock_tracker

    def test_extracts_stream_callback(self):
        """_setup extracts stream_callback from input_data."""
        agent = RecordingAgent(_make_config())
        cb = lambda x: None  # noqa: E731
        agent._setup({"stream_callback": cb}, None)
        assert agent._stream_callback is cb

    def test_creates_observer(self):
        """_setup creates AgentObserver."""
        agent = RecordingAgent(_make_config())
        agent._setup({}, None)
        assert agent._observer is not None

    def test_handles_empty_input(self):
        """_setup works with empty input_data."""
        agent = RecordingAgent(_make_config())
        agent._setup({}, None)
        assert agent.tool_executor is None
        assert agent.tracker is None


# ============================================================================
# Validate input
# ============================================================================


class TestValidateInput:
    """Test _validate_input rejects bad inputs."""

    def test_rejects_none(self):
        """_validate_input raises ValueError on None."""
        agent = RecordingAgent(_make_config())
        with pytest.raises(ValueError, match="cannot be None"):
            agent._validate_input(None)

    def test_rejects_non_dict(self):
        """_validate_input raises TypeError on non-dict."""
        agent = RecordingAgent(_make_config())
        with pytest.raises(TypeError, match="must be a dictionary"):
            agent._validate_input("not a dict")

    def test_rejects_bad_context(self):
        """_validate_input raises TypeError on invalid context."""
        agent = RecordingAgent(_make_config())
        with pytest.raises(TypeError, match="must be an ExecutionContext"):
            agent._validate_input({}, context="bad")

    def test_accepts_valid(self):
        """_validate_input accepts valid dict + context."""
        agent = RecordingAgent(_make_config())
        ctx = ExecutionContext(workflow_id="wf-1")
        agent._validate_input({"query": "test"}, ctx)  # should not raise
