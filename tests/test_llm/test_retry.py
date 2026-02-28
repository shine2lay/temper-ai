"""Tests for temper_ai.llm._retry module.

Tests retry logic for both sync and async LLM calls,
including backoff behavior, error handling, and streaming paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from temper_ai.llm._retry import call_with_retry_async, call_with_retry_sync
from temper_ai.shared.utils.exceptions import LLMError


def _make_config(max_retries: int = 2) -> MagicMock:
    """Create a mock inference config with zero delay to keep tests fast."""
    config = MagicMock()
    config.max_retries = max_retries
    config.retry_delay_seconds = 0.0
    return config


def _make_llm() -> MagicMock:
    """Create a mock LLM provider with sync and async call methods."""
    return MagicMock()


class TestCallWithRetrySync:
    """Tests for call_with_retry_sync."""

    def test_success_on_first_try(self) -> None:
        """Returns (response, None) when the first call succeeds."""
        llm = _make_llm()
        expected = MagicMock()
        llm.complete.return_value = expected
        config = _make_config()
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", None, None, observer, track_failed
        )

        assert response is expected
        assert error is None
        llm.complete.assert_called_once_with("test prompt")
        track_failed.assert_not_called()

    def test_success_after_one_retry(self) -> None:
        """Returns (response, None) when first call fails but second succeeds."""
        llm = _make_llm()
        expected = MagicMock()
        llm.complete.side_effect = [LLMError("transient"), expected]
        config = _make_config(max_retries=2)
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", None, None, observer, track_failed
        )

        assert response is expected
        assert error is None
        assert llm.complete.call_count == 2
        track_failed.assert_called_once()

    def test_max_retries_exhausted_returns_none_and_error(self) -> None:
        """Returns (None, last_error) when all attempts fail."""
        llm = _make_llm()
        err = LLMError("persistent failure")
        llm.complete.side_effect = err
        config = _make_config(max_retries=2)
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", None, None, observer, track_failed
        )

        assert response is None
        assert error is err
        # max_retries=2 means 3 total attempts (0, 1, 2)
        assert llm.complete.call_count == 3

    def test_llm_error_triggers_retry(self) -> None:
        """LLMError on first call causes retry; succeeds on second."""
        llm = _make_llm()
        expected = MagicMock()
        llm.complete.side_effect = [LLMError("fail once"), expected]
        config = _make_config(max_retries=1)
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", None, None, observer, track_failed
        )

        assert response is expected
        assert error is None

    def test_transport_error_triggers_retry(self) -> None:
        """httpx.TransportError on first call causes retry; succeeds on second."""
        llm = _make_llm()
        expected = MagicMock()
        llm.complete.side_effect = [
            httpx.TransportError("connection reset"),
            expected,
        ]
        config = _make_config(max_retries=2)
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", None, None, observer, track_failed
        )

        assert response is expected
        assert error is None

    def test_track_failed_call_invoked_per_failure(self) -> None:
        """track_failed_call is called exactly once per failed attempt."""
        llm = _make_llm()
        llm.complete.side_effect = LLMError("always fails")
        config = _make_config(max_retries=2)
        observer = MagicMock()
        track_failed = MagicMock()

        call_with_retry_sync(
            llm, config, "test prompt", None, None, observer, track_failed
        )

        # 3 total attempts (initial + 2 retries), each triggers track_failed_call
        assert track_failed.call_count == 3

    def test_streaming_path_calls_stream_not_complete(self) -> None:
        """When stream_callback is provided, calls llm.stream instead of llm.complete."""
        llm = _make_llm()
        stream_result = MagicMock()
        llm.stream.return_value = stream_result
        config = _make_config()
        callback = MagicMock()
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", callback, None, observer, track_failed
        )

        assert response is stream_result
        assert error is None
        llm.stream.assert_called_once_with("test prompt", on_chunk=callback)
        llm.complete.assert_not_called()

    def test_native_tool_defs_passed_as_tools_kwarg(self) -> None:
        """native_tool_defs are forwarded as 'tools' kwarg to llm.complete."""
        llm = _make_llm()
        expected = MagicMock()
        llm.complete.return_value = expected
        config = _make_config()
        tools = [{"name": "search", "description": "Web search tool"}]
        observer = MagicMock()
        track_failed = MagicMock()

        response, error = call_with_retry_sync(
            llm, config, "test prompt", None, tools, observer, track_failed
        )

        assert response is expected
        llm.complete.assert_called_once_with("test prompt", tools=tools)


class TestCallWithRetryAsync:
    """Tests for call_with_retry_async."""

    @pytest.mark.asyncio
    async def test_async_success_on_first_try(self) -> None:
        """Returns (response, None) on first successful async call."""
        llm = MagicMock()
        expected = MagicMock()
        llm.acomplete = AsyncMock(return_value=expected)
        config = _make_config()
        observer = MagicMock()
        track_failed = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response, error = await call_with_retry_async(
                llm, config, "test prompt", None, None, observer, track_failed
            )

        assert response is expected
        assert error is None
        llm.acomplete.assert_called_once_with("test prompt")
        track_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_retry_exhaustion(self) -> None:
        """Returns (None, last_error) when all async retries are exhausted."""
        llm = MagicMock()
        err = LLMError("async persistent failure")
        llm.acomplete = AsyncMock(side_effect=err)
        config = _make_config(max_retries=2)
        observer = MagicMock()
        track_failed = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response, error = await call_with_retry_async(
                llm, config, "test prompt", None, None, observer, track_failed
            )

        assert response is None
        assert error is err
        assert llm.acomplete.call_count == 3

    @pytest.mark.asyncio
    async def test_async_streaming_path_calls_astream(self) -> None:
        """When stream_callback provided, calls llm.astream instead of llm.acomplete."""
        llm = MagicMock()
        stream_result = MagicMock()
        llm.astream = AsyncMock(return_value=stream_result)
        config = _make_config()
        callback = MagicMock()
        observer = MagicMock()
        track_failed = MagicMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response, error = await call_with_retry_async(
                llm, config, "test prompt", callback, None, observer, track_failed
            )

        assert response is stream_result
        assert error is None
        llm.astream.assert_called_once_with("test prompt", on_chunk=callback)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
