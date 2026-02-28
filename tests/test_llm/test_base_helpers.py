"""Tests for temper_ai/llm/providers/_base_helpers.py.

Tests cover:
- validate_base_url: SSRF prevention for private/cloud-metadata endpoints
- handle_error_response: HTTP error status to exception mapping
- build_bearer_auth_headers: authentication header construction
- get_shared_circuit_breaker: cached circuit breaker management with LRU eviction
"""

from __future__ import annotations

import collections
import threading
from unittest.mock import MagicMock

import pytest

from temper_ai.llm.constants import MAX_ERROR_MESSAGE_LENGTH
from temper_ai.llm.providers._base_helpers import (
    build_bearer_auth_headers,
    get_shared_circuit_breaker,
    handle_error_response,
    validate_base_url,
)
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
)


def _make_response(status_code: int, text: str = "error") -> MagicMock:
    """Create a mock httpx.Response with status_code and text."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    return mock


def _make_llm_instance(
    class_name: str = "OpenAILLM",
    model: str = "gpt-4",
    base_url: str = "https://api.openai.com",
    api_key: str | None = "test-key",
) -> MagicMock:
    """Create a mock BaseLLM instance with the required attributes."""
    mock = MagicMock()
    mock.__class__ = type(class_name, (), {})
    mock.model = model
    mock.base_url = base_url
    mock.api_key = api_key
    return mock


class TestValidateBaseUrl:
    """Tests for validate_base_url SSRF prevention (AG-01)."""

    def test_valid_https_url_passes(self) -> None:
        """Public HTTPS URL is returned unchanged."""
        url = "https://api.openai.com/v1"
        assert validate_base_url(url) == url

    def test_valid_https_url_with_path_passes(self) -> None:
        """Public HTTPS URL with path is returned unchanged."""
        url = "https://api.anthropic.com/v1/messages"
        assert validate_base_url(url) == url

    def test_localhost_allowed(self) -> None:
        """localhost is permitted for local development."""
        url = "http://localhost:8080"
        assert validate_base_url(url) == url

    def test_loopback_127_0_0_1_allowed(self) -> None:
        """127.0.0.1 is permitted for local development."""
        url = "http://127.0.0.1:11434"
        assert validate_base_url(url) == url

    def test_ipv6_loopback_allowed(self) -> None:
        """IPv6 loopback ::1 is permitted for local development."""
        url = "http://[::1]:8080"
        assert validate_base_url(url) == url

    def test_blocks_aws_metadata_endpoint(self) -> None:
        """AWS IMDSv2 endpoint 169.254.169.254 raises ValueError mentioning SSRF."""
        with pytest.raises(ValueError, match="SSRF"):
            validate_base_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_gcp_metadata_endpoint(self) -> None:
        """GCP metadata.google.internal raises ValueError mentioning SSRF."""
        with pytest.raises(ValueError, match="SSRF"):
            validate_base_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_blocks_private_ip_class_a(self) -> None:
        """Private Class A IP (10.x.x.x) is blocked to prevent SSRF."""
        with pytest.raises(ValueError, match="SSRF"):
            validate_base_url("http://10.0.0.1/api")

    def test_blocks_private_ip_class_b(self) -> None:
        """Private Class B IP (172.16.x.x) is blocked to prevent SSRF."""
        with pytest.raises(ValueError, match="SSRF"):
            validate_base_url("http://172.16.0.1/api")

    def test_blocks_private_ip_class_c(self) -> None:
        """Private Class C IP (192.168.x.x) is blocked to prevent SSRF."""
        with pytest.raises(ValueError, match="SSRF"):
            validate_base_url("http://192.168.1.1/api")

    def test_blocks_link_local_address(self) -> None:
        """Link-local address 169.254.1.1 is blocked (link-local range, not metadata)."""
        with pytest.raises(ValueError, match="SSRF"):
            validate_base_url("http://169.254.1.1/api")


class TestHandleErrorResponse:
    """Tests for handle_error_response HTTP status to exception mapping."""

    def test_401_raises_llm_authentication_error(self) -> None:
        """HTTP 401 Unauthorized raises LLMAuthenticationError."""
        response = _make_response(401, "invalid token")
        with pytest.raises(LLMAuthenticationError):
            handle_error_response(response)

    def test_429_raises_llm_rate_limit_error(self) -> None:
        """HTTP 429 Too Many Requests raises LLMRateLimitError."""
        response = _make_response(429, "too many requests")
        with pytest.raises(LLMRateLimitError):
            handle_error_response(response)

    def test_500_raises_llm_error(self) -> None:
        """HTTP 500 Internal Server Error raises LLMError."""
        response = _make_response(500, "internal server error")
        with pytest.raises(LLMError):
            handle_error_response(response)

    def test_503_raises_llm_error(self) -> None:
        """HTTP 503 Service Unavailable raises LLMError."""
        response = _make_response(503, "service unavailable")
        with pytest.raises(LLMError):
            handle_error_response(response)

    def test_400_raises_llm_error(self) -> None:
        """HTTP 400 Bad Request raises LLMError."""
        response = _make_response(400, "bad request")
        with pytest.raises(LLMError):
            handle_error_response(response)

    def test_401_error_message_included(self) -> None:
        """Authentication error message contains response text."""
        response = _make_response(401, "invalid credentials")
        with pytest.raises(LLMAuthenticationError, match="invalid credentials"):
            handle_error_response(response)

    def test_error_message_truncated_to_max_length(self) -> None:
        """Response text longer than MAX_ERROR_MESSAGE_LENGTH is truncated."""
        long_text = "x" * (MAX_ERROR_MESSAGE_LENGTH + 100)
        response = _make_response(400, long_text)

        with pytest.raises(LLMError) as exc_info:
            handle_error_response(response)

        # The error should not contain more x's than MAX_ERROR_MESSAGE_LENGTH
        error_message = str(exc_info.value)
        assert "x" * (MAX_ERROR_MESSAGE_LENGTH + 1) not in error_message

    def test_401_not_raised_as_generic_llm_error(self) -> None:
        """HTTP 401 raises LLMAuthenticationError specifically, not just LLMError."""
        response = _make_response(401)
        with pytest.raises(LLMAuthenticationError):
            handle_error_response(response)

    def test_429_not_raised_as_generic_llm_error(self) -> None:
        """HTTP 429 raises LLMRateLimitError specifically, not just LLMError."""
        response = _make_response(429)
        with pytest.raises(LLMRateLimitError):
            handle_error_response(response)


class TestBuildBearerAuthHeaders:
    """Tests for build_bearer_auth_headers."""

    def test_with_api_key_includes_authorization_header(self) -> None:
        """Instance with api_key includes Authorization Bearer header."""
        instance = _make_llm_instance(api_key="my-secret-key")
        headers = build_bearer_auth_headers(instance)

        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer my-secret-key"
        assert headers["Content-Type"] == "application/json"

    def test_without_api_key_no_authorization_header(self) -> None:
        """Instance with api_key=None returns only Content-Type header."""
        instance = _make_llm_instance(api_key=None)
        headers = build_bearer_auth_headers(instance)

        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_empty_api_key_no_authorization_header(self) -> None:
        """Instance with empty string api_key does not include Authorization header."""
        instance = _make_llm_instance(api_key="")
        headers = build_bearer_auth_headers(instance)

        assert "Authorization" not in headers

    def test_content_type_always_json(self) -> None:
        """Content-Type header is always application/json regardless of api_key."""
        for api_key in ("key123", None, ""):
            instance = _make_llm_instance(api_key=api_key)
            headers = build_bearer_auth_headers(instance)
            assert headers["Content-Type"] == "application/json"


class TestGetSharedCircuitBreaker:
    """Tests for get_shared_circuit_breaker LRU cached management."""

    def test_creates_new_breaker_for_new_key(self) -> None:
        """Creates a new circuit breaker for an unseen provider/model/url."""
        instance = _make_llm_instance()
        circuit_breakers: collections.OrderedDict = collections.OrderedDict()
        lock = threading.Lock()

        cb = get_shared_circuit_breaker(
            instance, circuit_breakers, lock, max_breakers=10
        )

        assert cb is not None
        assert len(circuit_breakers) == 1

    def test_returns_cached_breaker_for_same_key(self) -> None:
        """Returns the same circuit breaker instance for identical key."""
        instance = _make_llm_instance()
        circuit_breakers: collections.OrderedDict = collections.OrderedDict()
        lock = threading.Lock()

        cb1 = get_shared_circuit_breaker(
            instance, circuit_breakers, lock, max_breakers=10
        )
        cb2 = get_shared_circuit_breaker(
            instance, circuit_breakers, lock, max_breakers=10
        )

        assert cb1 is cb2
        assert len(circuit_breakers) == 1

    def test_lru_eviction_at_max_breakers_limit(self) -> None:
        """Evicts the oldest (LRU) entry when max_breakers limit is reached."""
        circuit_breakers: collections.OrderedDict = collections.OrderedDict()
        lock = threading.Lock()
        max_breakers = 2

        inst1 = _make_llm_instance("OpenAILLM", "gpt-4", "https://api.openai.com")
        inst2 = _make_llm_instance(
            "AnthropicLLM", "claude-3", "https://api.anthropic.com"
        )
        get_shared_circuit_breaker(inst1, circuit_breakers, lock, max_breakers)
        get_shared_circuit_breaker(inst2, circuit_breakers, lock, max_breakers)
        assert len(circuit_breakers) == 2

        # Adding a 3rd should evict the first (LRU)
        inst3 = _make_llm_instance("OllamaLLM", "llama2", "http://localhost:11434")
        get_shared_circuit_breaker(inst3, circuit_breakers, lock, max_breakers)

        assert len(circuit_breakers) == 2  # Still at max, one was evicted

    def test_different_keys_create_different_breakers(self) -> None:
        """Different provider/model/url combinations yield distinct breakers."""
        circuit_breakers: collections.OrderedDict = collections.OrderedDict()
        lock = threading.Lock()

        inst1 = _make_llm_instance("OpenAILLM", "gpt-4", "https://api.openai.com")
        inst2 = _make_llm_instance(
            "AnthropicLLM", "claude-3", "https://api.anthropic.com"
        )

        cb1 = get_shared_circuit_breaker(inst1, circuit_breakers, lock, max_breakers=10)
        cb2 = get_shared_circuit_breaker(inst2, circuit_breakers, lock, max_breakers=10)

        assert cb1 is not cb2
        assert len(circuit_breakers) == 2

    def test_circuit_breaker_name_includes_provider_and_model(self) -> None:
        """Circuit breaker name reflects the provider and model."""
        instance = _make_llm_instance("OpenAILLM", "gpt-4", "https://api.openai.com")
        circuit_breakers: collections.OrderedDict = collections.OrderedDict()
        lock = threading.Lock()

        cb = get_shared_circuit_breaker(
            instance, circuit_breakers, lock, max_breakers=10
        )

        assert "openai" in cb.name
        assert "gpt-4" in cb.name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
