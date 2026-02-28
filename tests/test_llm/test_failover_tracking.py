"""Tests for WI-3: Failover tracking in FailoverProvider.

Tests that FailoverProvider populates failover_sequence on failover
and produces empty sequence on first-try success.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from temper_ai.llm.failover import FailoverConfig, FailoverProvider
from temper_ai.llm.providers import LLMError, LLMResponse
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
)


def _make_provider(model: str, provider_name: str = "test") -> MagicMock:
    """Create a mock LLM provider."""
    mock = MagicMock()
    mock.model = model
    mock.provider = provider_name
    return mock


def _make_response(content: str = "ok") -> LLMResponse:
    """Create a mock LLM response."""
    return LLMResponse(
        content=content,
        model="test-model",
        provider="test-provider",
        prompt_tokens=10,
        completion_tokens=5,
    )


class TestFailoverSequenceTracking:
    """Test _last_failover_sequence tracking."""

    def test_first_try_success_single_entry(self) -> None:
        """First-try success produces single entry in sequence."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.return_value = _make_response()

        fp = FailoverProvider(providers=[p1])
        fp.complete("test")

        seq = fp.last_failover_sequence
        assert len(seq) == 1
        assert "openai:gpt-4:success" == seq[0]

    def test_failover_records_failure_and_success(self) -> None:
        """Failover from p1 to p2 records both in sequence."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.side_effect = LLMError("timeout")

        p2 = _make_provider("claude", "anthropic")
        p2.complete.return_value = _make_response()

        fp = FailoverProvider(providers=[p1, p2])
        fp.complete("test")

        seq = fp.last_failover_sequence
        assert len(seq) == 2
        assert "openai:gpt-4:LLMError" == seq[0]
        assert "anthropic:claude:success" == seq[1]

    def test_all_providers_fail_records_full_sequence(self) -> None:
        """All providers failing records all failures."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.side_effect = LLMError("fail1")

        p2 = _make_provider("claude", "anthropic")
        p2.complete.side_effect = LLMError("fail2")

        fp = FailoverProvider(providers=[p1, p2])

        with pytest.raises(LLMError):
            fp.complete("test")

        seq = fp.last_failover_sequence
        assert len(seq) == 2
        assert "LLMError" in seq[0]
        assert "LLMError" in seq[1]

    def test_sequence_reset_on_new_call(self) -> None:
        """Each call gets a fresh sequence."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.return_value = _make_response()

        fp = FailoverProvider(providers=[p1])

        fp.complete("call1")
        seq1 = fp.last_failover_sequence

        fp.complete("call2")
        seq2 = fp.last_failover_sequence

        # Both should be single-entry success
        assert len(seq1) == 1
        assert len(seq2) == 1

    def test_reset_clears_sequence(self) -> None:
        """reset() clears the failover sequence."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.return_value = _make_response()

        fp = FailoverProvider(providers=[p1])
        fp.complete("test")
        assert len(fp.last_failover_sequence) == 1

        fp.reset()
        assert fp.last_failover_sequence == []

    def test_initial_sequence_empty(self) -> None:
        """Before any call, sequence is empty."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(providers=[p1])
        assert fp.last_failover_sequence == []

    def test_three_provider_failover(self) -> None:
        """Three providers: first two fail, third succeeds."""
        p1 = _make_provider("m1", "provider1")
        p1.complete.side_effect = LLMError("err1")

        p2 = _make_provider("m2", "provider2")
        p2.complete.side_effect = ConnectionError("err2")

        p3 = _make_provider("m3", "provider3")
        p3.complete.return_value = _make_response()

        fp = FailoverProvider(providers=[p1, p2, p3])
        fp.complete("test")

        seq = fp.last_failover_sequence
        assert len(seq) == 3
        assert "provider1:m1:LLMError" == seq[0]
        assert "provider2:m2:ConnectionError" == seq[1]
        assert "provider3:m3:success" == seq[2]


class TestShouldFailover:
    """Tests for FailoverProvider._should_failover error routing logic."""

    def test_timeout_error_failover_enabled(self) -> None:
        """LLMTimeoutError triggers failover when failover_on_timeout=True."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(
            providers=[p1], config=FailoverConfig(failover_on_timeout=True)
        )
        assert fp._should_failover(LLMTimeoutError("timeout")) is True

    def test_timeout_error_failover_disabled(self) -> None:
        """LLMTimeoutError does not trigger failover when failover_on_timeout=False."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(
            providers=[p1], config=FailoverConfig(failover_on_timeout=False)
        )
        assert fp._should_failover(LLMTimeoutError("timeout")) is False

    def test_rate_limit_error_failover_enabled(self) -> None:
        """LLMRateLimitError triggers failover when failover_on_rate_limit=True."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(
            providers=[p1], config=FailoverConfig(failover_on_rate_limit=True)
        )
        assert fp._should_failover(LLMRateLimitError("rate limited")) is True

    def test_rate_limit_error_failover_disabled(self) -> None:
        """LLMRateLimitError does not trigger failover when failover_on_rate_limit=False."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(
            providers=[p1], config=FailoverConfig(failover_on_rate_limit=False)
        )
        assert fp._should_failover(LLMRateLimitError("rate limited")) is False

    def test_connection_error_failover_enabled(self) -> None:
        """ConnectionError triggers failover when failover_on_connection_error=True."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(
            providers=[p1], config=FailoverConfig(failover_on_connection_error=True)
        )
        assert fp._should_failover(ConnectionError("connection refused")) is True

    def test_authentication_error_never_failovers(self) -> None:
        """LLMAuthenticationError always returns False regardless of config."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(providers=[p1], config=FailoverConfig())
        assert fp._should_failover(LLMAuthenticationError("bad key")) is False

    def test_unknown_error_defaults_to_failover(self) -> None:
        """Unknown/generic errors default to failover=True."""
        p1 = _make_provider("gpt-4", "openai")
        fp = FailoverProvider(providers=[p1], config=FailoverConfig())
        assert fp._should_failover(RuntimeError("unexpected")) is True


class TestFailoverAsync:
    """Tests for async failover via acomplete."""

    @pytest.mark.asyncio
    async def test_acomplete_succeeds_on_first_try(self) -> None:
        """acomplete returns response when first provider succeeds."""
        p1 = _make_provider("gpt-4", "openai")
        p1.acomplete = AsyncMock(return_value=_make_response("async_ok"))

        fp = FailoverProvider(providers=[p1])
        result = await fp.acomplete("test")
        assert result.content == "async_ok"

    @pytest.mark.asyncio
    async def test_acomplete_failover_on_error(self) -> None:
        """acomplete fails over to second provider when first raises LLMError."""
        p1 = _make_provider("gpt-4", "openai")
        p1.acomplete = AsyncMock(side_effect=LLMError("primary failed"))

        p2 = _make_provider("claude", "anthropic")
        p2.acomplete = AsyncMock(return_value=_make_response("backup_response"))

        fp = FailoverProvider(providers=[p1, p2])
        result = await fp.acomplete("test")
        assert result.content == "backup_response"


class TestFailoverEdgeCases:
    """Tests for edge cases in FailoverProvider initialization and behavior."""

    def test_empty_providers_raises_value_error(self) -> None:
        """FailoverProvider with empty providers list raises ValueError."""
        with pytest.raises(ValueError, match="At least one provider required"):
            FailoverProvider(providers=[])

    def test_single_provider_all_fail_raises_llm_error(self) -> None:
        """When single provider fails and no failover possible, raises LLMError."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.side_effect = LLMError("always fails")

        fp = FailoverProvider(providers=[p1])
        with pytest.raises(LLMError):
            fp.complete("test")

    def test_sticky_session_disabled_always_starts_at_zero(self) -> None:
        """With sticky_session=False, start index is always 0."""
        p1 = _make_provider("gpt-4", "openai")
        p1.complete.return_value = _make_response()

        fp = FailoverProvider(
            providers=[p1], config=FailoverConfig(sticky_session=False)
        )
        # Manually simulate previous backup usage
        fp.last_successful_index = 1

        fp.complete("test")
        # The call succeeds from provider 0 (only provider, index 0)
        assert fp.last_successful_index == 0
