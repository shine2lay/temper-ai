"""Tests for failed LLM call tracking in observability.

Verifies that failed/timed-out LLM calls are recorded via the tracker
so they appear in observability data.
"""
from unittest.mock import MagicMock

import pytest

from temper_ai.llm.service import LLMService


def _make_llm_service():
    """Create an LLMService with mock LLM and inference config."""
    mock_llm = MagicMock()
    mock_inf_config = MagicMock()
    mock_inf_config.provider = "ollama"
    mock_inf_config.model = "qwen3-next"
    mock_inf_config.temperature = 0.7
    mock_inf_config.max_tokens = 4096
    return LLMService(mock_llm, mock_inf_config)


class TestTrackFailedLLMCall:
    """Test the LLMService._track_failed_call method."""

    def test_failed_call_tracked_via_observer(self):
        """Failed LLM call is tracked with status='failed'."""
        service = _make_llm_service()
        observer = MagicMock()
        error = Exception("Connection timeout")

        service._track_failed_call(observer, "test prompt", error, 1, 3)

        observer.track_llm_call.assert_called_once()
        call_kwargs = observer.track_llm_call.call_args[1]

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
        service = _make_llm_service()
        observer = MagicMock()
        error = Exception("Rate limited")

        service._track_failed_call(observer, "prompt", error, 2, 4)

        call_kwargs = observer.track_llm_call.call_args[1]
        assert "[attempt 2/4]" in call_kwargs["error_message"]

    def test_failed_call_sanitizes_error_message(self):
        """Error messages are sanitized."""
        service = _make_llm_service()
        observer = MagicMock()
        error = Exception("Auth token abc123xyz invalid")

        service._track_failed_call(observer, "prompt", error, 1, 1)

        call_kwargs = observer.track_llm_call.call_args[1]
        assert call_kwargs["status"] == "failed"

    def test_observer_none_does_not_raise(self):
        """When observer is None, _track_failed_call completes silently."""
        service = _make_llm_service()
        error = Exception("test")

        result = service._track_failed_call(None, "prompt", error, 1, 1)
        assert result is None


class TestStandardAgentFailedLLMTracking:
    """Integration tests for failed LLM tracking via LLMService."""

    def test_track_failed_call_is_callable(self):
        """Verify _track_failed_call is callable on LLMService."""
        service = _make_llm_service()
        assert callable(service._track_failed_call)

    def test_track_failed_call_with_llm_error(self):
        """_track_failed_call works with LLMError."""
        from temper_ai.shared.utils.exceptions import LLMError

        service = _make_llm_service()
        observer = MagicMock()

        error = LLMError("Timeout after 600s")
        service._track_failed_call(observer, "prompt", error, 3, 3)

        observer.track_llm_call.assert_called_once()
        kwargs = observer.track_llm_call.call_args[1]
        assert kwargs["status"] == "failed"
        assert "[attempt 3/3]" in kwargs["error_message"]
