"""Tests for temper_ai.llm._tracking module.

Tests observer tracking helpers and safety validation:
track_call, track_failed_call, validate_safety.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.llm._tracking import (
    track_call,
    track_failed_call,
    validate_safety,
)
from temper_ai.shared.utils.exceptions import ConfigValidationError


def _make_inference_config() -> MagicMock:
    """Create a mock inference config with required attributes."""
    config = MagicMock()
    config.provider = "openai"
    config.model = "gpt-4"
    config.temperature = 0.7
    config.max_tokens = 1024
    return config


def _make_llm_response(latency_ms: float = 250.0) -> MagicMock:
    """Create a mock LLM response with required attributes."""
    resp = MagicMock()
    resp.content = "Hello, world!"
    resp.prompt_tokens = 100
    resp.completion_tokens = 50
    resp.latency_ms = latency_ms
    return resp


class TestTrackCall:
    """Tests for track_call."""

    def test_observer_none_is_noop(self) -> None:
        """When observer is None, track_call returns without error."""
        config = _make_inference_config()
        resp = _make_llm_response()
        # Should not raise
        track_call(
            observer=None,
            inference_config=config,
            prompt="hi",
            llm_response=resp,
            cost=0.01,
        )

    def test_calls_observer_track_llm_call_with_success_status(self) -> None:
        """Calls observer.track_llm_call with status='success'."""
        observer = MagicMock()
        config = _make_inference_config()
        resp = _make_llm_response()

        track_call(
            observer=observer,
            inference_config=config,
            prompt="test prompt",
            llm_response=resp,
            cost=0.05,
        )

        observer.track_llm_call.assert_called_once()
        call_kwargs = observer.track_llm_call.call_args.kwargs
        assert call_kwargs["status"] == "success"
        assert call_kwargs["provider"] == "openai"
        assert call_kwargs["model"] == "gpt-4"
        assert call_kwargs["prompt"] == "test prompt"

    def test_extracts_latency_ms_from_response(self) -> None:
        """Passes latency_ms from llm_response to observer."""
        observer = MagicMock()
        config = _make_inference_config()
        resp = _make_llm_response(latency_ms=500.0)

        track_call(
            observer=observer,
            inference_config=config,
            prompt="prompt",
            llm_response=resp,
            cost=0.0,
        )

        call_kwargs = observer.track_llm_call.call_args.kwargs
        assert call_kwargs["latency_ms"] == 500


class TestTrackFailedCall:
    """Tests for track_failed_call."""

    def test_observer_none_is_noop(self) -> None:
        """When observer is None, track_failed_call returns without error."""
        config = _make_inference_config()
        err = LookupError("something went wrong")
        # Should not raise
        track_failed_call(
            observer=None,
            inference_config=config,
            prompt="hi",
            error=err,
            attempt=1,
            max_attempts=3,
        )

    def test_calls_observer_track_llm_call_with_failed_status(self) -> None:
        """Calls observer.track_llm_call with status='failed'."""
        observer = MagicMock()
        config = _make_inference_config()
        err = RuntimeError("connection timeout")

        track_failed_call(
            observer=observer,
            inference_config=config,
            prompt="test prompt",
            error=err,
            attempt=2,
            max_attempts=3,
        )

        observer.track_llm_call.assert_called_once()
        call_kwargs = observer.track_llm_call.call_args.kwargs
        assert call_kwargs["status"] == "failed"

    def test_error_message_contains_attempt_format(self) -> None:
        """error_message contains '[attempt N/M]' format string."""
        observer = MagicMock()
        config = _make_inference_config()
        err = RuntimeError("timeout")

        track_failed_call(
            observer=observer,
            inference_config=config,
            prompt="prompt",
            error=err,
            attempt=1,
            max_attempts=3,
        )

        call_kwargs = observer.track_llm_call.call_args.kwargs
        error_msg = call_kwargs["error_message"]
        assert "[attempt 1/3]" in error_msg


class TestValidateSafety:
    """Tests for validate_safety."""

    def test_tool_executor_none_returns_none(self) -> None:
        """Returns None immediately when tool_executor is None."""
        result = validate_safety(
            tool_executor=None,
            inference_config=MagicMock(),
            prompt="prompt",
        )
        assert result is None

    def test_no_policy_engine_returns_none(self) -> None:
        """Returns None when tool_executor.policy_engine is None."""
        tool_executor = MagicMock()
        tool_executor.policy_engine = None

        result = validate_safety(
            tool_executor=tool_executor,
            inference_config=MagicMock(),
            prompt="prompt",
        )
        assert result is None

    def test_policy_violation_returns_error_string(self) -> None:
        """Returns error string containing 'blocked by safety policy' on violation."""
        tool_executor = MagicMock()
        config = _make_inference_config()

        violation = MagicMock()
        violation.message = "model not in allowed list"
        validation_result = MagicMock()
        validation_result.allowed = False
        validation_result.violations = [violation]
        tool_executor.policy_engine.validate_action_sync.return_value = (
            validation_result
        )

        with patch("temper_ai.safety.action_policy_engine.PolicyExecutionContext"):
            result = validate_safety(
                tool_executor=tool_executor,
                inference_config=config,
                prompt="test prompt",
            )

        assert result is not None
        assert "blocked by safety policy" in result
        assert "model not in allowed list" in result

    def test_policy_passes_returns_none(self) -> None:
        """Returns None when policy validation passes."""
        tool_executor = MagicMock()
        config = _make_inference_config()

        validation_result = MagicMock()
        validation_result.allowed = True
        validation_result.violations = []
        tool_executor.policy_engine.validate_action_sync.return_value = (
            validation_result
        )

        with patch("temper_ai.safety.action_policy_engine.PolicyExecutionContext"):
            result = validate_safety(
                tool_executor=tool_executor,
                inference_config=config,
                prompt="test prompt",
            )

        assert result is None

    def test_exception_in_validation_returns_fail_closed_message(self) -> None:
        """Returns fail-closed error message when validation raises an exception."""
        tool_executor = MagicMock()
        config = _make_inference_config()

        with patch("temper_ai.safety.action_policy_engine.PolicyExecutionContext"):
            tool_executor.policy_engine.validate_action_sync.side_effect = (
                ConfigValidationError("policy engine error")
            )
            result = validate_safety(
                tool_executor=tool_executor,
                inference_config=config,
                prompt="test prompt",
            )

        assert result is not None
        assert "Safety validation error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
