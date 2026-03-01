"""Coverage tests for temper_ai/llm/providers/base.py.

Covers: BaseLLM init (config and kwargs), complete, acomplete, stream, astream,
__del__, LLMConfig, _init_infrastructure, rate limiting, retry/backoff logic.
"""

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from temper_ai.llm.providers.base import (
    BaseLLM,
    LLMConfig,
    LLMResponse,
    LLMStreamChunk,
)
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)


@pytest.fixture(autouse=True)
def reset_circuit_breakers() -> None:
    """Reset shared circuit breakers before each test."""
    BaseLLM.reset_shared_circuit_breakers()
    yield  # type: ignore[misc]
    BaseLLM.reset_shared_circuit_breakers()


# ---------------------------------------------------------------------------
# Concrete test implementation of BaseLLM
# ---------------------------------------------------------------------------


class _TestLLM(BaseLLM):
    """Minimal concrete implementation for testing."""

    def _build_request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return {"prompt": prompt, **kwargs}

    def _parse_response(self, response: dict[str, Any], latency_ms: int) -> LLMResponse:
        return LLMResponse(
            content=response.get("text", ""),
            model=self.model,
            provider="test",
            latency_ms=latency_ms,
        )

    def _get_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _get_endpoint(self) -> str:
        return "/v1/test"


# ---------------------------------------------------------------------------
# BaseLLM.__init__ with config vs kwargs
# ---------------------------------------------------------------------------


class TestBaseLLMInit:
    def test_init_with_config(self) -> None:
        config = LLMConfig(
            model="test-model",
            base_url="http://localhost:8000",
            api_key="test-key",
            temperature=0.5,
            max_tokens=1024,
            top_p=0.8,
            timeout=300,
            max_retries=2,
            retry_delay=1.0,
        )
        llm = _TestLLM(config=config)
        assert llm.model == "test-model"
        assert llm.api_key == "test-key"
        assert llm.temperature == 0.5
        assert llm.max_tokens == 1024
        assert llm.top_p == 0.8
        assert llm.timeout == 300
        assert llm.max_retries == 2
        assert llm.retry_delay == 1.0
        llm.close()

    def test_init_with_kwargs(self) -> None:
        llm = _TestLLM(
            model="test-model",
            base_url="http://localhost:8000",
            api_key="sk-test",
            temperature=0.3,
            max_tokens=512,
        )
        assert llm.model == "test-model"
        assert llm.api_key == "sk-test"
        assert llm.temperature == 0.3
        assert llm.max_tokens == 512
        llm.close()

    def test_init_no_model_no_config_raises(self) -> None:
        with pytest.raises(ValueError, match="model and base_url are required"):
            _TestLLM()

    def test_init_no_base_url_raises(self) -> None:
        with pytest.raises(ValueError, match="model and base_url are required"):
            _TestLLM(model="test")

    def test_init_with_rate_limiter(self) -> None:
        rl = MagicMock()
        llm = _TestLLM(model="test", base_url="http://localhost:8000", rate_limiter=rl)
        assert llm._rate_limiter is rl
        llm.close()

    def test_init_with_config_rate_limiter(self) -> None:
        rl = MagicMock()
        config = LLMConfig(model="m", base_url="http://localhost:8000", rate_limiter=rl)
        llm = _TestLLM(config=config)
        assert llm._rate_limiter is rl
        llm.close()


# ---------------------------------------------------------------------------
# BaseLLM.complete — rate limiting and retry paths
# ---------------------------------------------------------------------------


class TestBaseLLMComplete:
    def test_rate_limiter_blocks(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (False, "rate limited")
        llm = _TestLLM(model="m", base_url="http://localhost:8000", rate_limiter=rl)
        with pytest.raises(LLMRateLimitError):
            llm.complete("test")
        llm.close()

    def test_rate_limiter_allows(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (True, None)
        llm = _TestLLM(model="m", base_url="http://localhost:8000", rate_limiter=rl)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "ok"}

        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get.return_value = mock_client
            result = llm.complete("test")
            assert result.content == "ok"
        llm.close()

    def test_rate_limiter_with_context(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (True, None)
        llm = _TestLLM(model="m", base_url="http://localhost:8000", rate_limiter=rl)
        ctx = MagicMock()
        ctx.agent_id = "agent-1"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "ok"}

        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get.return_value = mock_client
            llm.complete("test", context=ctx)
            rl.check_and_record_rate_limit.assert_called_with("agent-1")
        llm.close()

    def test_timeout_exhausts_retries(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=1)
        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_get.return_value = mock_client
            with (
                patch("temper_ai.llm.providers.base._sync_backoff_sleep"),
                pytest.raises(LLMTimeoutError),
            ):
                llm.complete("test")
        llm.close()

    def test_rate_limit_error_retries(self) -> None:
        # max_retries=2 means range(2) => attempts 0 and 1
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=2)

        call_count = 0

        def side_effect(*a: Any, **kw: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LLMRateLimitError("rate limited")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"text": "ok"}
            return resp

        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.side_effect = side_effect
            mock_get.return_value = mock_client
            with patch("temper_ai.llm.providers.base._sync_backoff_sleep"):
                result = llm.complete("test")
                assert result.content == "ok"
        llm.close()

    def test_connect_error_exhausts_retries(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=1)
        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectError("connection failed")
            mock_get.return_value = mock_client
            with (
                patch("temper_ai.llm.providers.base._sync_backoff_sleep"),
                pytest.raises(LLMError, match="Connection failed"),
            ):
                llm.complete("test")
        llm.close()

    def test_auth_error_no_retry(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=3)
        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.side_effect = LLMAuthenticationError("auth failed")
            mock_get.return_value = mock_client
            with pytest.raises(LLMAuthenticationError):
                llm.complete("test")
        llm.close()


# ---------------------------------------------------------------------------
# BaseLLM.acomplete — async paths
# ---------------------------------------------------------------------------


class TestBaseLLMAcomplete:
    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_async(self) -> None:
        rl = MagicMock()
        rl.check_and_record_rate_limit.return_value = (False, "blocked")
        llm = _TestLLM(model="m", base_url="http://localhost:8000", rate_limiter=rl)
        with pytest.raises(LLMRateLimitError):
            await llm.acomplete("test")
        llm.close()

    @pytest.mark.asyncio
    async def test_async_timeout_retries(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=1)
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        with (
            patch.object(llm, "_get_async_client_safe", return_value=mock_client),
            patch.object(llm, "_async_backoff_sleep", new_callable=AsyncMock),
            pytest.raises(LLMTimeoutError),
        ):
            await llm.acomplete("test")
        llm.close()

    @pytest.mark.asyncio
    async def test_async_connect_error(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=1)
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("fail")

        with (
            patch.object(llm, "_get_async_client_safe", return_value=mock_client),
            patch.object(llm, "_async_backoff_sleep", new_callable=AsyncMock),
            pytest.raises(LLMError, match="Connection failed"),
        ):
            await llm.acomplete("test")
        llm.close()

    @pytest.mark.asyncio
    async def test_async_auth_error_no_retry(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=3)
        mock_client = AsyncMock()
        mock_client.post.side_effect = LLMAuthenticationError("auth")

        with (
            patch.object(llm, "_get_async_client_safe", return_value=mock_client),
            pytest.raises(LLMAuthenticationError),
        ):
            await llm.acomplete("test")
        llm.close()

    @pytest.mark.asyncio
    async def test_async_rate_limit_retries(self) -> None:
        # max_retries=2 means range(2) => attempts 0 and 1
        llm = _TestLLM(model="m", base_url="http://localhost:8000", max_retries=2)
        call_count = 0

        async def side_effect(*a: Any, **kw: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise LLMRateLimitError("rate limited")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"text": "ok"}
            return resp

        mock_client = AsyncMock()
        mock_client.post.side_effect = side_effect

        with (
            patch.object(llm, "_get_async_client_safe", return_value=mock_client),
            patch.object(llm, "_async_backoff_sleep", new_callable=AsyncMock),
        ):
            result = await llm.acomplete("test")
            assert result.content == "ok"
        llm.close()


# ---------------------------------------------------------------------------
# BaseLLM.stream / astream (default fallback)
# ---------------------------------------------------------------------------


class TestBaseLLMStream:
    def test_stream_defaults_to_complete(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "streamed"}

        with patch.object(llm, "_get_client") as mock_get:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get.return_value = mock_client
            result = llm.stream("test")
            assert result.content == "streamed"
        llm.close()

    @pytest.mark.asyncio
    async def test_astream_defaults_to_acomplete(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "async streamed"}
        mock_client.post.return_value = mock_response

        with patch.object(llm, "_get_async_client_safe", return_value=mock_client):
            result = await llm.astream("test")
            assert result.content == "async streamed"
        llm.close()


# ---------------------------------------------------------------------------
# BaseLLM.__del__
# ---------------------------------------------------------------------------


class TestBaseLLMDel:
    def test_del_warns_when_not_closed(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        llm._closed = False
        llm._client = MagicMock()  # Simulate unclosed client
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            llm.__del__()
            assert len(w) == 1
            assert "not properly closed" in str(w[0].message)
        llm._client = None
        llm.close()

    def test_del_no_warning_when_closed(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        llm.close()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            llm.__del__()
            resource_warnings = [
                x for x in w if issubclass(x.category, ResourceWarning)
            ]
            assert len(resource_warnings) == 0

    def test_del_no_closed_attr(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        # Remove _closed to simulate partially initialized
        if hasattr(llm, "_closed"):
            del llm._closed
        # Should not raise
        llm.__del__()


# ---------------------------------------------------------------------------
# BaseLLM.reset_shared_circuit_breakers
# ---------------------------------------------------------------------------


class TestResetCircuitBreakers:
    def test_reset(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        # Should not raise
        _TestLLM.reset_shared_circuit_breakers()
        llm.close()


# ---------------------------------------------------------------------------
# BaseLLM._async_backoff_sleep
# ---------------------------------------------------------------------------


class TestAsyncBackoffSleep:
    @pytest.mark.asyncio
    async def test_backoff_sleep(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        with patch(
            "temper_ai.llm.providers.base.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            await llm._async_backoff_sleep(0)
            mock_sleep.assert_called_once()
            assert mock_sleep.call_args[0][0] > 0
        llm.close()


# ---------------------------------------------------------------------------
# _consume_stream / _aconsume_stream default raises
# ---------------------------------------------------------------------------


class TestDefaultStreamRaises:
    def test_consume_stream_raises(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        with pytest.raises(NotImplementedError):
            llm._consume_stream(MagicMock(), MagicMock())
        llm.close()

    @pytest.mark.asyncio
    async def test_aconsume_stream_raises(self) -> None:
        llm = _TestLLM(model="m", base_url="http://localhost:8000")
        with pytest.raises(NotImplementedError):
            await llm._aconsume_stream(MagicMock(), MagicMock())
        llm.close()


# ---------------------------------------------------------------------------
# LLMConfig dataclass
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_defaults(self) -> None:
        config = LLMConfig(model="m", base_url="http://localhost:8000")
        assert config.temperature == 0.7
        assert config.max_tokens == 2048
        assert config.top_p == 0.9
        assert config.rate_limiter is None

    def test_custom(self) -> None:
        config = LLMConfig(
            model="m",
            base_url="http://localhost:8000",
            temperature=0.1,
        )
        assert config.temperature == 0.1


# ---------------------------------------------------------------------------
# LLMStreamChunk
# ---------------------------------------------------------------------------


class TestLLMStreamChunk:
    def test_defaults(self) -> None:
        chunk = LLMStreamChunk(content="hello")
        assert chunk.chunk_type == "content"
        assert chunk.done is False
        assert chunk.finish_reason is None

    def test_thinking_chunk(self) -> None:
        chunk = LLMStreamChunk(content="thinking", chunk_type="thinking")
        assert chunk.chunk_type == "thinking"
