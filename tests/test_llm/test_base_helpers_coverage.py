"""Extended coverage tests for temper_ai/llm/providers/_base_helpers.py.

Covers: HTTP client creation (sync/async), response handling,
cleanup helpers, streaming helpers, context manager mixin, sync backoff,
bind_callable_attributes.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.llm.providers._base_helpers import (
    LLMContextManagerMixin,
    bind_callable_attributes,
    close_async,
    close_sync,
    execute_and_parse,
    execute_streaming_async_impl,
    execute_streaming_impl,
    get_async_lock,
    get_or_create_async_client_safe,
    get_or_create_async_client_sync,
    get_or_create_sync_client,
    make_streaming_call_impl,
    reset_shared_circuit_breakers,
    sync_backoff_sleep,
)
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_instance(**overrides: Any) -> MagicMock:
    """Create a mock BaseLLM instance with common attributes."""
    mock = MagicMock()
    mock.__class__ = type("TestLLM", (), {})
    mock.model = overrides.get("model", "test-model")
    mock.base_url = overrides.get("base_url", "https://example.com")
    mock.api_key = overrides.get("api_key", "sk-test")
    mock.timeout = overrides.get("timeout", 60)
    mock.temperature = overrides.get("temperature", 0.7)
    mock.max_tokens = overrides.get("max_tokens", 2048)
    mock.top_p = overrides.get("top_p", 0.9)
    mock._client = overrides.get("_client", None)
    mock._async_client = overrides.get("_async_client", None)
    mock._sync_cleanup_lock = threading.Lock()
    mock._async_cleanup_lock = None
    mock._closed = overrides.get("_closed", False)
    mock._cache = overrides.get("_cache", None)
    mock._rate_limiter = overrides.get("_rate_limiter", None)
    return mock


# ---------------------------------------------------------------------------
# get_or_create_sync_client
# ---------------------------------------------------------------------------


class TestGetOrCreateSyncClient:
    def test_creates_client_when_none(self) -> None:
        instance = _make_llm_instance()
        instance._client = None
        with patch("temper_ai.llm.providers._base_helpers.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            client = get_or_create_sync_client(instance)
            assert client is mock_client
            mock_cls.assert_called_once()

    def test_reuses_existing_client(self) -> None:
        existing = MagicMock()
        instance = _make_llm_instance(_client=existing)
        client = get_or_create_sync_client(instance)
        assert client is existing

    def test_http2_import_failure(self) -> None:
        instance = _make_llm_instance()
        instance._client = None
        with (
            patch("temper_ai.llm.providers._base_helpers.httpx.Client") as mock_cls,
            patch.dict("sys.modules", {"h2": None}),
        ):
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            client = get_or_create_sync_client(instance)
            assert client is mock_client


# ---------------------------------------------------------------------------
# get_or_create_async_client_safe
# ---------------------------------------------------------------------------


class TestGetOrCreateAsyncClientSafe:
    @pytest.mark.asyncio
    async def test_creates_async_client_when_none(self) -> None:
        instance = _make_llm_instance()
        instance._async_client = None
        with (
            patch(
                "temper_ai.llm.providers._base_helpers.httpx.AsyncClient"
            ) as mock_cls,
            patch("temper_ai.llm.providers.base.BaseLLM._async_client_lock", None),
        ):
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            client = await get_or_create_async_client_safe(instance)
            assert client is mock_client

    @pytest.mark.asyncio
    async def test_reuses_existing_async_client(self) -> None:
        existing = MagicMock()
        instance = _make_llm_instance(_async_client=existing)
        client = await get_or_create_async_client_safe(instance)
        assert client is existing


# ---------------------------------------------------------------------------
# get_or_create_async_client_sync
# ---------------------------------------------------------------------------


class TestGetOrCreateAsyncClientSync:
    def test_creates_async_client_sync(self) -> None:
        instance = _make_llm_instance()
        instance._async_client = None
        with patch(
            "temper_ai.llm.providers._base_helpers.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            client = get_or_create_async_client_sync(instance)
            assert client is mock_client

    def test_reuses_existing_async_client_sync(self) -> None:
        existing = MagicMock()
        instance = _make_llm_instance(_async_client=existing)
        client = get_or_create_async_client_sync(instance)
        assert client is existing


# ---------------------------------------------------------------------------
# execute_and_parse
# ---------------------------------------------------------------------------


class TestExecuteAndParse:
    def test_successful_response(self) -> None:
        from temper_ai.llm.providers.base import LLMResponse

        instance = _make_llm_instance()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
        instance._parse_response.return_value = LLMResponse(
            content="hi", model="m", provider="p"
        )
        result = execute_and_parse(instance, mock_resp, time.time())
        assert result.content == "hi"

    def test_error_response(self) -> None:
        instance = _make_llm_instance()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with pytest.raises(LLMError):
            execute_and_parse(instance, mock_resp, time.time())


# ---------------------------------------------------------------------------
# close_sync
# ---------------------------------------------------------------------------


class TestCloseSync:
    def test_closes_sync_client(self) -> None:
        mock_client = MagicMock()
        instance = _make_llm_instance(_client=mock_client)
        instance._async_client = None
        close_sync(instance)
        mock_client.close.assert_called_once()
        assert instance._closed is True

    def test_already_closed(self) -> None:
        instance = _make_llm_instance(_closed=True)
        close_sync(instance)
        # Should return early

    def test_close_with_async_client_no_loop(self) -> None:
        mock_async = MagicMock()
        instance = _make_llm_instance(_async_client=mock_async)
        instance._client = None
        # No running event loop
        close_sync(instance)
        assert instance._closed is True

    def test_close_with_sync_client_error(self) -> None:
        mock_client = MagicMock()
        mock_client.close.side_effect = OSError("close failed")
        instance = _make_llm_instance(_client=mock_client)
        instance._async_client = None
        close_sync(instance)
        assert instance._closed is True


# ---------------------------------------------------------------------------
# close_async
# ---------------------------------------------------------------------------


class TestCloseAsync:
    @pytest.mark.asyncio
    async def test_closes_async_clients(self) -> None:
        mock_client = MagicMock()
        mock_async_client = AsyncMock()
        instance = _make_llm_instance(
            _client=mock_client, _async_client=mock_async_client
        )
        await close_async(instance)
        mock_client.close.assert_called_once()
        mock_async_client.aclose.assert_called_once()
        assert instance._closed is True

    @pytest.mark.asyncio
    async def test_already_closed_async(self) -> None:
        instance = _make_llm_instance(_closed=True)
        instance._async_cleanup_lock = asyncio.Lock()
        await close_async(instance)

    @pytest.mark.asyncio
    async def test_close_async_with_error(self) -> None:
        mock_client = MagicMock()
        mock_client.close.side_effect = OSError("fail")
        instance = _make_llm_instance(_client=mock_client)
        instance._async_client = None
        await close_async(instance)
        assert instance._closed is True


# ---------------------------------------------------------------------------
# make_streaming_call_impl
# ---------------------------------------------------------------------------


class TestMakeStreamingCallImpl:
    def test_no_rate_limiter(self) -> None:
        instance = _make_llm_instance(_rate_limiter=None)
        # Should not raise
        make_streaming_call_impl(instance, "prompt", None)

    def test_rate_limiter_blocks(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (False, "too fast")
        instance = _make_llm_instance(_rate_limiter=rl)
        with pytest.raises(LLMRateLimitError):
            make_streaming_call_impl(instance, "prompt", None)

    def test_rate_limiter_allows(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (True, None)
        instance = _make_llm_instance(_rate_limiter=rl)
        # Should not raise
        make_streaming_call_impl(instance, "prompt", None)

    def test_rate_limiter_with_context_agent_id(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (True, None)
        instance = _make_llm_instance(_rate_limiter=rl)
        ctx = MagicMock()
        ctx.agent_id = "agent-1"
        make_streaming_call_impl(instance, "prompt", ctx)
        rl.check_and_record_rate_limit.assert_called_with("agent-1")


# ---------------------------------------------------------------------------
# execute_streaming_impl
# ---------------------------------------------------------------------------


class TestExecuteStreamingImpl:
    def test_successful_stream(self) -> None:
        from temper_ai.llm.providers.base import LLMResponse

        instance = _make_llm_instance()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_result = LLMResponse(content="stream result", model="m", provider="p")
        instance._consume_stream.return_value = mock_result
        on_chunk = MagicMock()

        result = execute_streaming_impl(instance, time.time(), mock_response, on_chunk)
        assert result.content == "stream result"
        mock_response.close.assert_called_once()

    def test_error_stream(self) -> None:
        instance = _make_llm_instance()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        on_chunk = MagicMock()

        with pytest.raises(LLMRateLimitError):
            execute_streaming_impl(instance, time.time(), mock_response, on_chunk)
        mock_response.close.assert_called_once()


# ---------------------------------------------------------------------------
# execute_streaming_async_impl
# ---------------------------------------------------------------------------


class TestExecuteStreamingAsyncImpl:
    @pytest.mark.asyncio
    async def test_successful_async_stream(self) -> None:
        from temper_ai.llm.providers.base import LLMResponse

        instance = _make_llm_instance()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_result = LLMResponse(content="async stream", model="m", provider="p")
        instance._aconsume_stream = AsyncMock(return_value=mock_result)
        on_chunk = MagicMock()

        result = await execute_streaming_async_impl(
            instance, time.time(), mock_response, on_chunk
        )
        assert result.content == "async stream"
        mock_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_async_stream(self) -> None:
        instance = _make_llm_instance()
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        on_chunk = MagicMock()

        with pytest.raises(LLMAuthenticationError):
            await execute_streaming_async_impl(
                instance, time.time(), mock_response, on_chunk
            )
        mock_response.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# sync_backoff_sleep
# ---------------------------------------------------------------------------


class TestSyncBackoffSleep:
    def test_sleeps(self) -> None:
        with patch("temper_ai.llm.providers._base_helpers.time.sleep") as mock_sleep:
            sync_backoff_sleep(0.01, 0)
            mock_sleep.assert_called_once()
            assert mock_sleep.call_args[0][0] > 0


# ---------------------------------------------------------------------------
# bind_callable_attributes
# ---------------------------------------------------------------------------


class TestBindCallableAttributes:
    def test_binds_all_attributes(self) -> None:
        instance = _make_llm_instance(_cache=None)
        bind_callable_attributes(instance)
        # After binding, these should be set on the instance
        assert hasattr(instance, "_build_bearer_auth_headers")
        assert hasattr(instance, "_execute_and_parse")
        assert hasattr(instance, "_make_streaming_call_impl")
        assert hasattr(instance, "_execute_streaming_impl")
        assert hasattr(instance, "_execute_streaming_async_impl")


# ---------------------------------------------------------------------------
# reset_shared_circuit_breakers
# ---------------------------------------------------------------------------


class TestResetSharedCircuitBreakers:
    def test_reset_clears(self) -> None:
        import collections

        cb = MagicMock()
        breakers = collections.OrderedDict()
        breakers[("a", "b", "c")] = cb
        lock = threading.Lock()
        reset_shared_circuit_breakers(breakers, lock)
        assert len(breakers) == 0
        cb.reset.assert_called_once()


# ---------------------------------------------------------------------------
# get_async_lock
# ---------------------------------------------------------------------------


class TestGetAsyncLock:
    def test_creates_lock_when_none(self) -> None:
        mock_cls = MagicMock()
        mock_cls._async_client_lock = None
        lock = get_async_lock(mock_cls)
        assert isinstance(lock, asyncio.Lock)

    def test_reuses_existing_lock(self) -> None:
        existing_lock = asyncio.Lock()
        mock_cls = MagicMock()
        mock_cls._async_client_lock = existing_lock
        lock = get_async_lock(mock_cls)
        assert lock is existing_lock


# ---------------------------------------------------------------------------
# LLMContextManagerMixin
# ---------------------------------------------------------------------------


class TestLLMContextManagerMixin:
    def test_sync_context_manager(self) -> None:
        class TestCM(LLMContextManagerMixin):
            closed = False

            def close(self) -> None:
                self.closed = True

            async def aclose(self) -> None:
                self.closed = True

        obj = TestCM()
        with obj as cm:
            assert cm is obj
        assert obj.closed is True

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        class TestCM(LLMContextManagerMixin):
            closed = False

            def close(self) -> None:
                self.closed = True

            async def aclose(self) -> None:
                self.closed = True

        obj = TestCM()
        async with obj as cm:
            assert cm is obj
        assert obj.closed is True

    def test_exit_returns_false(self) -> None:
        class TestCM(LLMContextManagerMixin):
            def close(self) -> None:
                pass

            async def aclose(self) -> None:
                pass

        obj = TestCM()
        result = obj.__exit__(None, None, None)
        assert result is False
