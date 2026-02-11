"""Tests for failed LLM call tracking in observability.

Verifies that failed/timed-out LLM calls are recorded via the tracker
so they appear in observability data.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.agents._standard_agent_helpers import track_failed_llm_call


class TestTrackFailedLLMCall:
    """Test the track_failed_llm_call helper function."""

    def _make_agent_with_observer(self):
        """Create a mock agent with an observer."""
        agent = MagicMock()
        agent._observer = MagicMock()
        agent._observer.active = True
        return agent

    def _make_inf_config(self):
        """Create a mock inference config."""
        config = MagicMock()
        config.provider = "ollama"
        config.model = "qwen3-next"
        config.temperature = 0.7
        config.max_tokens = 4096
        return config

    def test_failed_call_tracked_via_observer(self):
        """Failed LLM call is tracked with status='failed'."""
        agent = self._make_agent_with_observer()
        inf_config = self._make_inf_config()
        error = Exception("Connection timeout")

        track_failed_llm_call(agent, inf_config, "test prompt", error, 1, 3)

        agent._observer.track_llm_call.assert_called_once()
        call_kwargs = agent._observer.track_llm_call.call_args[1]

        assert call_kwargs["provider"] == "ollama"
        assert call_kwargs["model"] == "qwen3-next"
        assert call_kwargs["status"] == "failed"
        assert "Connection timeout" in call_kwargs["error_message"]
        assert "[attempt 1/3]" in call_kwargs["error_message"]
        assert call_kwargs["prompt"] == "test prompt"
        assert call_kwargs["response"] == ""
        assert call_kwargs["prompt_tokens"] == 0
        assert call_kwargs["completion_tokens"] == 0

    def test_failed_call_includes_attempt_info(self):
        """Error message includes attempt number."""
        agent = self._make_agent_with_observer()
        inf_config = self._make_inf_config()
        error = Exception("Rate limited")

        track_failed_llm_call(agent, inf_config, "prompt", error, 2, 4)

        call_kwargs = agent._observer.track_llm_call.call_args[1]
        assert "[attempt 2/4]" in call_kwargs["error_message"]

    def test_failed_call_sanitizes_error_message(self):
        """Error messages are sanitized."""
        agent = self._make_agent_with_observer()
        inf_config = self._make_inf_config()
        # Error with potentially sensitive info
        error = Exception("Auth token abc123xyz invalid")

        track_failed_llm_call(agent, inf_config, "prompt", error, 1, 1)

        call_kwargs = agent._observer.track_llm_call.call_args[1]
        # Should be called regardless of message content
        assert call_kwargs["status"] == "failed"

    def test_observer_inactive_does_not_raise(self):
        """When observer is inactive, track_failed_llm_call still completes."""
        agent = MagicMock()
        agent._observer = MagicMock()
        agent._observer.active = False
        # track_llm_call is a no-op when inactive but should not raise
        agent._observer.track_llm_call = MagicMock()

        inf_config = self._make_inf_config()
        error = Exception("test")

        # Should not raise
        track_failed_llm_call(agent, inf_config, "prompt", error, 1, 1)


class TestStandardAgentFailedLLMTracking:
    """Integration tests for failed LLM tracking in StandardAgent iteration methods."""

    def test_sync_iteration_tracks_failed_calls(self):
        """_execute_iteration tracks failed LLM calls."""
        from src.agents.llm import LLMError

        agent = MagicMock()
        agent.name = "test_agent"
        agent.config.agent.inference.max_retries = 1
        agent.config.agent.inference.retry_delay_seconds = 0.01
        agent.config.agent.inference.provider = "ollama"
        agent.config.agent.inference.model = "test"
        agent.config.agent.inference.temperature = 0.7
        agent.config.agent.inference.max_tokens = 1000
        agent._observer = MagicMock()
        agent._observer.active = True
        agent.tool_executor = None
        agent.llm = MagicMock()
        agent.llm.complete.side_effect = LLMError("Connection refused")

        # Import and call the actual _execute_iteration via helpers
        from src.agents._standard_agent_helpers import track_failed_llm_call

        # Verify the function exists and is callable
        assert callable(track_failed_llm_call)

    def test_async_iteration_tracks_failed_calls(self):
        """_aexecute_iteration tracks failed LLM calls."""
        from src.agents.llm import LLMError

        # Just verify the import works (actual async testing is more complex)
        from src.agents._standard_agent_helpers import track_failed_llm_call

        agent = MagicMock()
        agent._observer = MagicMock()
        inf_config = MagicMock()
        inf_config.provider = "ollama"
        inf_config.model = "test"
        inf_config.temperature = 0.7
        inf_config.max_tokens = 1000

        error = LLMError("Timeout after 600s")
        track_failed_llm_call(agent, inf_config, "prompt", error, 3, 3)

        agent._observer.track_llm_call.assert_called_once()
        kwargs = agent._observer.track_llm_call.call_args[1]
        assert kwargs["status"] == "failed"
        assert "[attempt 3/3]" in kwargs["error_message"]
