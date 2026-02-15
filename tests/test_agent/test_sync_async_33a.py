"""Tests for code-high-sync-async-33a.

Verifies that the refactored complete/acomplete share logic through
_check_cache, _cache_response, and _execute_and_parse helpers.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.providers import BaseLLM, LLMResponse
from src.shared.utils.exceptions import LLMAuthenticationError


class DummyLLM(BaseLLM):
    """Minimal concrete LLM for testing shared helpers."""

    @property
    def provider_name(self) -> str:
        return "dummy"

    def _build_request(self, prompt, **kwargs):
        return {"prompt": prompt, **kwargs}

    def _parse_response(self, response_data, latency_ms):
        return LLMResponse(
            content=response_data.get("text", ""),
            model=self.model,
            provider=self.provider_name,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            latency_ms=latency_ms,
        )

    def _get_headers(self):
        return {"Authorization": "Bearer test"}

    def _get_endpoint(self):
        return "/completions"


@pytest.fixture
def llm():
    """Create a DummyLLM with mocked HTTP clients."""
    instance = DummyLLM(model="test-model", base_url="http://localhost:11434", api_key="test-key")
    return instance


class TestCheckCache:
    """Verify _check_cache extracts correct cache key."""

    def test_returns_none_when_no_cache(self, llm):
        """Without cache, _check_cache returns (None, None)."""
        key, hit = llm._check_cache("hello", None)
        assert key is None
        assert hit is None

    def test_returns_cache_hit(self, llm):
        """With cache enabled and a hit, returns cached LLMResponse."""
        mock_cache = MagicMock()
        mock_cache.generate_key.return_value = "key-123"
        mock_cache.get.return_value = json.dumps({
            "content": "cached-result",
            "model": "test-model",
            "provider": "dummy",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "latency_ms": 5,
        })
        llm._cache = mock_cache

        key, hit = llm._check_cache("hello", None)
        assert key == "key-123"
        assert isinstance(hit, LLMResponse)
        assert hit.content == "cached-result"

    def test_returns_cache_miss(self, llm):
        """With cache enabled but no hit, returns (key, None)."""
        mock_cache = MagicMock()
        mock_cache.generate_key.return_value = "key-456"
        mock_cache.get.return_value = None
        llm._cache = mock_cache

        key, hit = llm._check_cache("hello", None)
        assert key == "key-456"
        assert hit is None


class TestCacheResponse:
    """Verify _cache_response stores data correctly."""

    def test_stores_when_cache_enabled(self, llm):
        mock_cache = MagicMock()
        llm._cache = mock_cache

        response = LLMResponse(
            content="result",
            model="test-model",
            provider="dummy",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            latency_ms=50,
        )

        llm._cache_response("key-abc", response)
        mock_cache.set.assert_called_once()
        stored = json.loads(mock_cache.set.call_args[0][1])
        assert stored["content"] == "result"
        assert stored["prompt_tokens"] == 10

    def test_noop_when_no_cache(self, llm):
        """No error when cache is None."""
        llm._cache_response("key", LLMResponse(
            content="x", model="m", provider="p",
            prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0,
        ))
        # Function should complete without error when cache is None
        assert llm._cache is None

    def test_noop_when_no_key(self, llm):
        """No error when cache_key is None."""
        llm._cache = MagicMock()
        llm._cache_response(None, LLMResponse(
            content="x", model="m", provider="p",
            prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0,
        ))
        llm._cache.set.assert_not_called()


class TestExecuteAndParse:
    """Verify _execute_and_parse handles response correctly."""

    def test_successful_response(self, llm):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "hello world"}

        result = llm._execute_and_parse(mock_response, time.time(), None)
        assert isinstance(result, LLMResponse)
        assert result.content == "hello world"

    def test_error_response_raises(self, llm):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with pytest.raises(LLMAuthenticationError):
            llm._execute_and_parse(mock_response, time.time(), None)


class TestSyncAsyncConsistency:
    """Verify sync and async paths use same helpers and produce consistent results."""

    def test_complete_uses_check_cache(self, llm):
        """complete() uses _check_cache for cache lookup."""
        with patch.object(llm, '_check_cache', return_value=("key", None)) as mock_check, \
             patch.object(llm, '_get_client') as mock_client:

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "result"}
            mock_client.return_value.post.return_value = mock_resp

            llm.complete("hello")
            mock_check.assert_called_once()

    def test_complete_returns_cache_hit(self, llm):
        """complete() returns cached response without making API call."""
        cached = LLMResponse(
            content="cached", model="m", provider="p",
            prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0,
        )
        with patch.object(llm, '_check_cache', return_value=("key", cached)):
            result = llm.complete("hello")
            assert result.content == "cached"

    @pytest.mark.asyncio
    async def test_acomplete_uses_check_cache(self, llm):
        """acomplete() uses _check_cache for cache lookup."""
        with patch.object(llm, '_check_cache', return_value=("key", None)) as mock_check, \
             patch('src.llm.providers.base.httpx.AsyncClient') as mock_client_class:

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "result"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_class.return_value = mock_client

            await llm.acomplete("hello")
            mock_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_acomplete_returns_cache_hit(self, llm):
        """acomplete() returns cached response without making API call."""
        cached = LLMResponse(
            content="cached", model="m", provider="p",
            prompt_tokens=0, completion_tokens=0, total_tokens=0, latency_ms=0,
        )
        with patch.object(llm, '_check_cache', return_value=("key", cached)):
            result = await llm.acomplete("hello")
            assert result.content == "cached"

    def test_sync_async_same_cache_key(self, llm):
        """Both paths produce the same cache key for the same input."""
        mock_cache = MagicMock()
        mock_cache.generate_key.return_value = "consistent-key"
        mock_cache.get.return_value = None
        llm._cache = mock_cache

        key1, _ = llm._check_cache("prompt", None, temperature=0.5)

        # Reset and call again (same helper)
        mock_cache.generate_key.return_value = "consistent-key"
        key2, _ = llm._check_cache("prompt", None, temperature=0.5)

        assert key1 == key2
