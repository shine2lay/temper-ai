"""Coverage tests for temper_ai/llm/failover.py.

Covers: acomplete async failover, _async_get_start_index, _async_record_success,
_should_failover branches, sticky session retry-primary logic, model/provider_name
properties, reset method.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from temper_ai.llm.failover import FailoverConfig, FailoverProvider
from temper_ai.llm.providers.base import LLMResponse
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)


def _make_provider(model: str = "test", **kwargs: Any) -> MagicMock:
    p = MagicMock()
    p.model = model
    p.provider = kwargs.get("provider", "test-provider")
    return p


def _make_response(content: str = "ok") -> LLMResponse:
    return LLMResponse(content=content, model="test", provider="test")


class TestFailoverProviderAsync:
    @pytest.mark.asyncio
    async def test_acomplete_success_first_provider(self) -> None:
        p1 = _make_provider("primary")
        p1.acomplete = AsyncMock(return_value=_make_response("primary ok"))
        fp = FailoverProvider([p1])
        result = await fp.acomplete("test")
        assert result.content == "primary ok"

    @pytest.mark.asyncio
    async def test_acomplete_failover_to_backup(self) -> None:
        p1 = _make_provider("primary")
        p1.acomplete = AsyncMock(side_effect=LLMError("primary fail"))
        p2 = _make_provider("backup")
        p2.acomplete = AsyncMock(return_value=_make_response("backup ok"))
        fp = FailoverProvider([p1, p2])
        result = await fp.acomplete("test")
        assert result.content == "backup ok"

    @pytest.mark.asyncio
    async def test_acomplete_all_fail(self) -> None:
        p1 = _make_provider("primary")
        p1.acomplete = AsyncMock(side_effect=LLMError("fail1"))
        p2 = _make_provider("backup")
        p2.acomplete = AsyncMock(side_effect=LLMError("fail2"))
        fp = FailoverProvider([p1, p2])
        with pytest.raises(LLMError, match="All.*providers failed"):
            await fp.acomplete("test")

    @pytest.mark.asyncio
    async def test_acomplete_non_failover_error_raises(self) -> None:
        p1 = _make_provider("primary")
        p1.acomplete = AsyncMock(side_effect=LLMAuthenticationError("auth"))
        p2 = _make_provider("backup")
        p2.acomplete = AsyncMock(return_value=_make_response())
        fp = FailoverProvider([p1, p2])
        with pytest.raises(LLMAuthenticationError):
            await fp.acomplete("test")


class TestAsyncStartIndex:
    @pytest.mark.asyncio
    async def test_sticky_session_returns_last_successful(self) -> None:
        p1 = _make_provider("primary")
        p2 = _make_provider("backup")
        fp = FailoverProvider([p1, p2])
        fp.last_successful_index = 1
        fp.backup_success_count = 1
        idx = await fp._async_get_start_index()
        assert idx == 1

    @pytest.mark.asyncio
    async def test_retry_primary_after_threshold(self) -> None:
        p1 = _make_provider("primary")
        p2 = _make_provider("backup")
        config = FailoverConfig(retry_primary_after=2)
        fp = FailoverProvider([p1, p2], config=config)
        fp.backup_success_count = 2
        idx = await fp._async_get_start_index()
        assert idx == 0
        assert fp.backup_success_count == 0


class TestAsyncRecordSuccess:
    @pytest.mark.asyncio
    async def test_record_success_primary(self) -> None:
        p1 = _make_provider("primary")
        fp = FailoverProvider([p1])
        seq: list[str] = []
        await fp._async_record_success(0, p1, seq)
        assert fp.last_successful_index == 0
        assert fp.backup_success_count == 0
        assert "success" in seq[0]

    @pytest.mark.asyncio
    async def test_record_success_backup(self) -> None:
        p1 = _make_provider("primary")
        p2 = _make_provider("backup")
        fp = FailoverProvider([p1, p2])
        seq: list[str] = []
        await fp._async_record_success(1, p2, seq)
        assert fp.last_successful_index == 1
        assert fp.backup_success_count == 1


class TestShouldFailover:
    def test_timeout_failover(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(LLMTimeoutError("t")) is True

    def test_timeout_no_failover(self) -> None:
        config = FailoverConfig(failover_on_timeout=False)
        fp = FailoverProvider([_make_provider()], config=config)
        assert fp._should_failover(LLMTimeoutError("t")) is False

    def test_rate_limit_failover(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(LLMRateLimitError("rl")) is True

    def test_rate_limit_no_failover(self) -> None:
        config = FailoverConfig(failover_on_rate_limit=False)
        fp = FailoverProvider([_make_provider()], config=config)
        assert fp._should_failover(LLMRateLimitError("rl")) is False

    def test_connection_error_failover(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(httpx.ConnectError("c")) is True

    def test_connection_error_no_failover(self) -> None:
        config = FailoverConfig(failover_on_connection_error=False)
        fp = FailoverProvider([_make_provider()], config=config)
        assert fp._should_failover(httpx.ConnectError("c")) is False

    def test_http_status_4xx_no_failover_default(self) -> None:
        fp = FailoverProvider([_make_provider()])
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        err = httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=mock_resp
        )
        assert fp._should_failover(err) is False

    def test_http_status_4xx_failover_enabled(self) -> None:
        config = FailoverConfig(failover_on_client_error=True)
        fp = FailoverProvider([_make_provider()], config=config)
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        err = httpx.HTTPStatusError(
            "bad request", request=MagicMock(), response=mock_resp
        )
        assert fp._should_failover(err) is True

    def test_http_status_5xx_failover(self) -> None:
        fp = FailoverProvider([_make_provider()])
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        err = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=mock_resp
        )
        assert fp._should_failover(err) is True

    def test_http_status_5xx_no_failover(self) -> None:
        config = FailoverConfig(failover_on_server_error=False)
        fp = FailoverProvider([_make_provider()], config=config)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        err = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=mock_resp
        )
        assert fp._should_failover(err) is False

    def test_auth_error_no_failover(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(LLMAuthenticationError("auth")) is False

    def test_unknown_error_failover(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(RuntimeError("unknown")) is True

    def test_httpx_timeout_exception(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(httpx.TimeoutException("t")) is True

    def test_python_timeout_error(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(TimeoutError("t")) is True

    def test_network_error(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(httpx.NetworkError("n")) is True

    def test_connection_error_python(self) -> None:
        fp = FailoverProvider([_make_provider()])
        assert fp._should_failover(ConnectionError("c")) is True


class TestFailoverProperties:
    def test_model_property(self) -> None:
        p1 = _make_provider("model-a")
        p2 = _make_provider("model-b")
        fp = FailoverProvider([p1, p2])
        assert fp.model == "model-a"
        fp.last_successful_index = 1
        assert fp.model == "model-b"

    def test_provider_name_property(self) -> None:
        p1 = _make_provider("m")
        p1.provider = "ollama"
        fp = FailoverProvider([p1])
        assert fp.provider_name == "ollama"

    def test_last_failover_sequence(self) -> None:
        fp = FailoverProvider([_make_provider()])
        fp._last_failover_sequence = ["a", "b"]
        assert fp.last_failover_sequence == ["a", "b"]

    def test_reset(self) -> None:
        p1 = _make_provider("primary")
        p2 = _make_provider("backup")
        fp = FailoverProvider([p1, p2])
        fp.last_successful_index = 1
        fp.backup_success_count = 5
        fp._last_failover_sequence = ["a"]
        fp.reset()
        assert fp.last_successful_index == 0
        assert fp.backup_success_count == 0
        assert fp._last_failover_sequence == []


class TestFailoverInit:
    def test_empty_providers_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one provider"):
            FailoverProvider([])

    def test_custom_config(self) -> None:
        config = FailoverConfig(sticky_session=False)
        fp = FailoverProvider([_make_provider()], config=config)
        assert fp.config.sticky_session is False


class TestSyncStartIndex:
    def test_sticky_returns_last(self) -> None:
        fp = FailoverProvider([_make_provider(), _make_provider()])
        fp.last_successful_index = 1
        fp.backup_success_count = 1
        assert fp._get_start_index() == 1

    def test_retry_primary_after_threshold(self) -> None:
        config = FailoverConfig(retry_primary_after=2)
        fp = FailoverProvider([_make_provider(), _make_provider()], config=config)
        fp.backup_success_count = 2
        assert fp._get_start_index() == 0

    def test_no_sticky(self) -> None:
        config = FailoverConfig(sticky_session=False)
        fp = FailoverProvider([_make_provider(), _make_provider()], config=config)
        fp.last_successful_index = 1
        idx = fp._get_start_index()
        # With sticky=False, condition is False, backup_success_count=0 < retry_primary_after
        # so it falls through to return 0
        assert idx == 0


class TestRecordFailure:
    def test_record_failure(self) -> None:
        fp = FailoverProvider([_make_provider()])
        errors: list[str] = []
        seq: list[str] = []
        p = _make_provider("model-x")
        fp._record_failure(p, LLMError("test error"), errors, seq)
        assert len(errors) == 1
        assert "model-x" in errors[0]
        assert len(seq) == 1


class TestStoreSequence:
    def test_store_sequence(self) -> None:
        fp = FailoverProvider([_make_provider()])
        seq = ["a:b:success"]
        fp._store_sequence(seq)
        assert fp._last_failover_sequence == seq


class TestCompleteSync:
    def test_complete_non_failover_error(self) -> None:
        p1 = _make_provider("primary")
        p1.complete.side_effect = LLMAuthenticationError("auth")
        p2 = _make_provider("backup")
        p2.complete.return_value = _make_response()
        fp = FailoverProvider([p1, p2])
        with pytest.raises(LLMAuthenticationError):
            fp.complete("test")
