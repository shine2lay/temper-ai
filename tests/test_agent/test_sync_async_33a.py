"""Tests for code-high-sync-async-33a.

Verifies that the refactored complete/acomplete share logic through
_execute_and_parse helpers.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.llm.providers import BaseLLM, LLMResponse
from temper_ai.shared.utils.exceptions import LLMAuthenticationError


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
    instance = DummyLLM(
        model="test-model", base_url="http://localhost:11434", api_key="test-key"
    )
    return instance


class TestExecuteAndParse:
    """Verify _execute_and_parse handles response correctly."""

    def test_successful_response(self, llm):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "hello world"}

        result = llm._execute_and_parse(mock_response, time.time())
        assert isinstance(result, LLMResponse)
        assert result.content == "hello world"

    def test_error_response_raises(self, llm):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with pytest.raises(LLMAuthenticationError):
            llm._execute_and_parse(mock_response, time.time())


class TestSyncAsyncConsistency:
    """Verify sync and async paths use same helpers and produce consistent results."""

    def test_complete_calls_api(self, llm):
        """complete() makes API call and returns parsed response."""
        with patch.object(llm, "_get_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "result"}
            mock_client.return_value.post.return_value = mock_resp

            result = llm.complete("hello")
            assert result.content == "result"

    @pytest.mark.asyncio
    async def test_acomplete_calls_api(self, llm):
        """acomplete() makes API call and returns parsed response."""
        with patch(
            "temper_ai.llm.providers.base.httpx.AsyncClient"
        ) as mock_client_class:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"text": "result"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_class.return_value = mock_client

            result = await llm.acomplete("hello")
            assert result.content == "result"
