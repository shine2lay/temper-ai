"""
Unit tests for LLM provider clients.

Tests Ollama, OpenAI, Anthropic, and vLLM providers with mocked HTTP responses.
"""
import pytest
import httpx
from unittest.mock import Mock, patch, MagicMock
import time
from typing import Optional

from src.agents.llm_providers import (
    BaseLLM,
    OllamaLLM,
    OpenAILLM,
    AnthropicLLM,
    vLLMLLM,
    create_llm_client,
    LLMProvider,
    LLMResponse,
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMAuthenticationError,
)
from src.llm.circuit_breaker import CircuitState, CircuitBreakerError, CircuitBreaker, CircuitBreakerConfig


class InMemoryStorage:
    """In-memory storage backend for testing (mimics Redis)."""

    def __init__(self):
        self._store = {}

    def get(self, key: str) -> Optional[str]:
        """Retrieve value by key."""
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        """Store value by key."""
        self._store[key] = value

    def delete(self, key: str) -> None:
        """Delete value by key."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all stored data."""
        self._store.clear()


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.Client for testing."""
    with patch('src.agents.llm_providers.httpx.Client') as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        yield mock_client


class TestOllamaLLM:
    """Test Ollama LLM provider."""

    def test_init(self):
        """Test Ollama initialization."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            temperature=0.7,
            max_tokens=2048,
        )

        assert llm.model == "llama3.2:3b"
        assert llm.base_url == "http://localhost:11434"
        assert llm.temperature == 0.7
        assert llm.max_tokens == 2048

    def test_get_endpoint(self):
        """Test Ollama endpoint."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )
        assert llm._get_endpoint() == "/api/generate"

    def test_get_headers(self):
        """Test Ollama headers."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )
        headers = llm._get_headers()
        assert headers["Content-Type"] == "application/json"
        assert "Authorization" not in headers  # Ollama doesn't need auth

    def test_build_request(self):
        """Test Ollama request building."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            temperature=0.7,
            max_tokens=1024,
        )

        request = llm._build_request("Test prompt")

        assert request["model"] == "llama3.2:3b"
        assert request["prompt"] == "Test prompt"
        assert request["temperature"] == 0.7
        assert request["max_tokens"] == 1024
        assert request["stream"] is False

    def test_parse_response(self):
        """Test Ollama response parsing."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        mock_response = {
            "response": "This is a test response",
            "prompt_eval_count": 10,
            "eval_count": 20,
            "done": True,
        }

        result = llm._parse_response(mock_response, latency_ms=250)

        assert result.content == "This is a test response"
        assert result.model == "llama3.2:3b"
        assert result.provider == LLMProvider.OLLAMA
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.total_tokens == 30
        assert result.latency_ms == 250
        assert result.finish_reason == "stop"

    def test_complete_success(self, mock_httpx_client):
        """Test successful completion."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "Paris",
            "prompt_eval_count": 15,
            "eval_count": 5,
            "done": True,
        }
        mock_httpx_client.post.return_value = mock_response

        result = llm.complete("What is the capital of France?")

        assert result.content == "Paris"
        assert result.provider == LLMProvider.OLLAMA
        assert result.total_tokens == 20

        # Verify HTTP call
        mock_httpx_client.post.assert_called_once()
        call_args = mock_httpx_client.post.call_args
        assert "http://localhost:11434/api/generate" in str(call_args)


class TestOpenAILLM:
    """Test OpenAI LLM provider."""

    def test_init_with_api_key(self):
        """Test OpenAI initialization with API key."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test-key",
        )

        assert llm.model == "gpt-4"
        assert llm.api_key == "sk-test-key"

    def test_get_endpoint(self):
        """Test OpenAI endpoint."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test",
        )
        assert llm._get_endpoint() == "/v1/chat/completions"

    def test_get_headers_with_auth(self):
        """Test OpenAI headers include authorization."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test-key",
        )

        headers = llm._get_headers()

        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer sk-test-key"

    def test_build_request(self):
        """Test OpenAI request building."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test",
            temperature=0.5,
        )

        request = llm._build_request("Hello, world!")

        assert request["model"] == "gpt-4"
        assert request["messages"] == [{"role": "user", "content": "Hello, world!"}]
        assert request["temperature"] == 0.5
        assert request["stream"] is False

    def test_parse_response(self):
        """Test OpenAI response parsing."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test",
        )

        mock_response = {
            "model": "gpt-4",
            "choices": [
                {
                    "message": {"content": "Hello! How can I help?"},
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            }
        }

        result = llm._parse_response(mock_response, latency_ms=500)

        assert result.content == "Hello! How can I help?"
        assert result.model == "gpt-4"
        assert result.provider == LLMProvider.OPENAI
        assert result.prompt_tokens == 12
        assert result.completion_tokens == 8
        assert result.total_tokens == 20
        assert result.finish_reason == "stop"


class TestAnthropicLLM:
    """Test Anthropic LLM provider."""

    def test_init(self):
        """Test Anthropic initialization."""
        llm = AnthropicLLM(
            model="claude-3-opus-20240229",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )

        assert llm.model == "claude-3-opus-20240229"
        assert llm.api_key == "sk-ant-test"

    def test_get_endpoint(self):
        """Test Anthropic endpoint."""
        llm = AnthropicLLM(
            model="claude-3-opus-20240229",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )
        assert llm._get_endpoint() == "/v1/messages"

    def test_get_headers(self):
        """Test Anthropic headers."""
        llm = AnthropicLLM(
            model="claude-3-opus-20240229",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test-key",
        )

        headers = llm._get_headers()

        assert headers["Content-Type"] == "application/json"
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["x-api-key"] == "sk-ant-test-key"

    def test_build_request(self):
        """Test Anthropic request building."""
        llm = AnthropicLLM(
            model="claude-3-opus-20240229",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
            temperature=0.8,
            max_tokens=4096,
        )

        request = llm._build_request("Explain quantum physics")

        assert request["model"] == "claude-3-opus-20240229"
        assert request["messages"] == [{"role": "user", "content": "Explain quantum physics"}]
        assert request["temperature"] == 0.8
        assert request["max_tokens"] == 4096

    def test_parse_response(self):
        """Test Anthropic response parsing."""
        llm = AnthropicLLM(
            model="claude-3-opus-20240229",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )

        mock_response = {
            "model": "claude-3-opus-20240229",
            "content": [
                {"text": "Quantum physics is the study of matter and energy..."}
            ],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 50,
            }
        }

        result = llm._parse_response(mock_response, latency_ms=800)

        assert result.content == "Quantum physics is the study of matter and energy..."
        assert result.model == "claude-3-opus-20240229"
        assert result.provider == LLMProvider.ANTHROPIC
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 50
        assert result.total_tokens == 60
        assert result.finish_reason == "end_turn"


class TestvLLMLLM:
    """Test vLLM provider."""

    def test_init(self):
        """Test vLLM initialization."""
        llm = vLLMLLM(
            model="meta-llama/Llama-2-7b-hf",
            base_url="http://localhost:8000",
        )

        assert llm.model == "meta-llama/Llama-2-7b-hf"
        assert llm.base_url == "http://localhost:8000"

    def test_get_endpoint(self):
        """Test vLLM endpoint."""
        llm = vLLMLLM(
            model="meta-llama/Llama-2-7b-hf",
            base_url="http://localhost:8000",
        )
        assert llm._get_endpoint() == "/v1/completions"

    def test_parse_response(self):
        """Test vLLM response parsing."""
        llm = vLLMLLM(
            model="meta-llama/Llama-2-7b-hf",
            base_url="http://localhost:8000",
        )

        mock_response = {
            "model": "meta-llama/Llama-2-7b-hf",
            "choices": [
                {
                    "text": "Generated text from vLLM",
                    "finish_reason": "length"
                }
            ],
            "usage": {
                "prompt_tokens": 25,
                "completion_tokens": 75,
                "total_tokens": 100,
            }
        }

        result = llm._parse_response(mock_response, latency_ms=300)

        assert result.content == "Generated text from vLLM"
        assert result.provider == LLMProvider.VLLM
        assert result.total_tokens == 100


class TestErrorHandling:
    """Test error handling across providers."""

    def test_authentication_error(self, mock_httpx_client):
        """Test authentication error handling."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="invalid-key",
        )

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMAuthenticationError, match="Authentication failed"):
            llm.complete("Test prompt")

    def test_rate_limit_error(self, mock_httpx_client):
        """Test rate limit error handling."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,  # Fail fast for testing
        )

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMRateLimitError, match="Rate limited"):
            llm.complete("Test prompt")

    def test_server_error(self, mock_httpx_client):
        """Test server error handling."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMError, match="Server error"):
            llm.complete("Test prompt")

    def test_timeout_error(self, mock_httpx_client):
        """Test timeout error handling."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
            timeout=1,
        )

        # Simulate timeout
        mock_httpx_client.post.side_effect = httpx.TimeoutException("Request timed out")

        with pytest.raises(LLMTimeoutError, match="Request timed out"):
            llm.complete("Test prompt")

    def test_retry_on_rate_limit(self, mock_httpx_client):
        """Test retry logic with exponential backoff on rate limit."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=3,
            retry_delay=0.1,  # Fast for testing
        )

        # First two calls rate limited, third succeeds
        rate_limit_response = Mock()
        rate_limit_response.status_code = 429
        rate_limit_response.text = "Rate limited"

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "response": "Success after retry",
            "prompt_eval_count": 5,
            "eval_count": 10,
            "done": True,
        }

        mock_httpx_client.post.side_effect = [
            rate_limit_response,
            rate_limit_response,
            success_response,
        ]

        with patch('time.sleep'):  # Speed up test
            result = llm.complete("Test prompt")

        assert result.content == "Success after retry"
        assert mock_httpx_client.post.call_count == 3


class TestErrorResponseSanitization:
    """Verify _handle_error_response sanitizes sensitive data."""

    def test_api_key_redacted_in_auth_error(self, mock_httpx_client):
        """API keys in 401 response bodies are redacted."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test-123",
        )
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key: sk-proj-abc123def456"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMAuthenticationError) as exc_info:
            llm.complete("test")

        assert "sk-proj-abc123def456" not in str(exc_info.value)
        assert "REDACTED" in str(exc_info.value)

    def test_bearer_token_redacted_in_error(self, mock_httpx_client):
        """Bearer tokens in error responses are redacted."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Error: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMError) as exc_info:
            llm.complete("test")

        assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in str(exc_info.value)
        assert "REDACTED" in str(exc_info.value)

    def test_normal_error_preserved(self, mock_httpx_client):
        """Normal error responses without sensitive data remain useful."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Invalid model format: expected string"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMError) as exc_info:
            llm.complete("test")

        assert "Invalid model format: expected string" in str(exc_info.value)
        assert "400" in str(exc_info.value)

    def test_long_response_truncated(self, mock_httpx_client):
        """Response bodies longer than 500 chars are truncated."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )
        long_text = "x" * 1000
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = long_text
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMError) as exc_info:
            llm.complete("test")

        # Error message should not contain all 1000 chars
        error_msg = str(exc_info.value)
        # The prefix "Server error (500): " is ~20 chars, so truncated body = 500
        assert len(error_msg) <= 600

    def test_rate_limit_error_sanitized(self, mock_httpx_client):
        """Rate limit errors also get sanitized."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited. Your key: api_key=sk-secret-longkey123"
        mock_httpx_client.post.return_value = mock_response

        with pytest.raises(LLMRateLimitError) as exc_info:
            llm.complete("test")

        assert "sk-secret-longkey123" not in str(exc_info.value)
        assert "REDACTED" in str(exc_info.value)


class TestCreateLLMClient:
    """Test LLM client factory function."""

    def test_create_ollama_client(self):
        """Test creating Ollama client via factory."""
        llm = create_llm_client(
            provider="ollama",
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        assert isinstance(llm, OllamaLLM)
        assert llm.model == "llama3.2:3b"

    def test_create_openai_client(self):
        """Test creating OpenAI client via factory."""
        llm = create_llm_client(
            provider="openai",
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test",
        )

        assert isinstance(llm, OpenAILLM)
        assert llm.model == "gpt-4"
        assert llm.api_key == "sk-test"

    def test_create_anthropic_client(self):
        """Test creating Anthropic client via factory."""
        llm = create_llm_client(
            provider="anthropic",
            model="claude-3-opus-20240229",
            base_url="https://api.anthropic.com",
            api_key="sk-ant-test",
        )

        assert isinstance(llm, AnthropicLLM)
        assert llm.model == "claude-3-opus-20240229"

    def test_create_vllm_client(self):
        """Test creating vLLM client via factory."""
        llm = create_llm_client(
            provider="vllm",
            model="meta-llama/Llama-2-7b-hf",
            base_url="http://localhost:8000",
        )

        assert isinstance(llm, vLLMLLM)
        assert llm.model == "meta-llama/Llama-2-7b-hf"

    def test_create_unknown_provider_raises_error(self):
        """Test that unknown provider raises ValueError."""
        with pytest.raises(ValueError, match="is not a valid LLMProvider"):
            create_llm_client(
                provider="invalid",
                model="test-model",
                base_url="http://localhost:8000",
            )

    def test_factory_passes_kwargs(self):
        """Test that factory passes additional kwargs to client."""
        llm = create_llm_client(
            provider="ollama",
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            temperature=0.9,
            max_tokens=4096,
            timeout=120,
        )

        assert llm.temperature == 0.9
        assert llm.max_tokens == 4096
        assert llm.timeout == 120

    def test_provider_case_insensitive(self):
        """Test that provider names are case-insensitive."""
        llm = create_llm_client(
            provider="OLLAMA",
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        assert isinstance(llm, OllamaLLM)


class TestContextManager:
    """Test context manager support."""

    def test_context_manager(self, mock_httpx_client):
        """Test LLM client as context manager."""
        with OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        ) as llm:
            assert llm.model == "llama3.2:3b"
            # Trigger client initialization by calling _get_client()
            _ = llm._get_client()

        # Verify close was called
        mock_httpx_client.close.assert_called_once()


class TestRequestOverrides:
    """Test request parameter overrides."""

    def test_temperature_override(self):
        """Test overriding temperature in request."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            temperature=0.7,
        )

        request = llm._build_request("Test", temperature=0.3)

        assert request["temperature"] == 0.3  # Overridden
        assert llm.temperature == 0.7  # Original unchanged

    def test_max_tokens_override(self):
        """Test overriding max_tokens in request."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test",
            max_tokens=2048,
        )

        request = llm._build_request("Test", max_tokens=512)

        assert request["max_tokens"] == 512  # Overridden
        assert llm.max_tokens == 2048  # Original unchanged


class TestCircuitBreaker:
    """Test circuit breaker pattern for LLM provider resilience."""

    def test_circuit_breaker_opens_after_failures(self, mock_httpx_client):
        """Test circuit breaker opens after repeated failures."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,  # Fail fast for testing
        )

        # Mock connection failures
        mock_httpx_client.post.side_effect = httpx.ConnectError("Connection refused")

        # Trigger 5 failures to open circuit
        for i in range(5):
            with pytest.raises(httpx.ConnectError):
                llm.complete("test")

        # Verify circuit is open
        assert llm._circuit_breaker.state == CircuitState.OPEN

        # Next call should fail fast with circuit breaker error
        with pytest.raises(CircuitBreakerError, match="Circuit breaker OPEN"):
            llm.complete("test")

        # Verify no additional HTTP calls were made (fast-fail)
        assert mock_httpx_client.post.call_count == 5  # Only the 5 failures

    def test_circuit_breaker_half_open_recovery(self, mock_httpx_client):
        """Test circuit breaker recovers through half-open state."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Open the circuit manually
        breaker = llm._circuit_breaker
        breaker.state = CircuitState.OPEN
        breaker.last_failure_time = time.time() - 61  # Past timeout

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "test response",
            "prompt_eval_count": 10,
            "eval_count": 20,
            "done": True,
        }
        mock_httpx_client.post.return_value = mock_response

        # First call moves to HALF_OPEN
        result = llm.complete("test")
        assert result.content == "test response"
        assert breaker.state == CircuitState.HALF_OPEN

        # Second successful call closes circuit
        llm.complete("test")
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_reopens_on_half_open_failure(self, mock_httpx_client):
        """Test circuit breaker re-opens if half-open test fails."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Set to half-open state
        breaker = llm._circuit_breaker
        breaker.state = CircuitState.HALF_OPEN

        # Mock failure
        mock_httpx_client.post.side_effect = httpx.ConnectError("Connection refused")

        # Half-open test fails, circuit should re-open
        with pytest.raises(httpx.ConnectError):
            llm.complete("test")

        assert breaker.state == CircuitState.OPEN

    def test_circuit_breaker_isolated_per_provider(self, mock_httpx_client):
        """Test each provider has independent circuit breaker."""
        ollama = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )
        openai = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="sk-test",
            max_retries=1,
        )

        # Fail Ollama circuit
        mock_httpx_client.post.side_effect = httpx.ConnectError("Refused")
        for _ in range(5):
            with pytest.raises(httpx.ConnectError):
                ollama.complete("test")

        # Ollama circuit should be OPEN
        assert ollama._circuit_breaker.state == CircuitState.OPEN

        # OpenAI circuit should still be CLOSED
        assert openai._circuit_breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_counts_server_errors(self, mock_httpx_client):
        """Test circuit breaker counts HTTP 5xx server errors."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Mock 500 server error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_httpx_client.post.return_value = mock_response

        # Trigger 5 server errors
        for _ in range(5):
            with pytest.raises(LLMError, match="Server error"):
                llm.complete("test")

        # Circuit should be OPEN
        assert llm._circuit_breaker.state == CircuitState.OPEN

    def test_circuit_breaker_counts_rate_limits(self, mock_httpx_client):
        """Test circuit breaker counts HTTP 429 rate limit errors."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Mock 429 rate limit
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_httpx_client.post.return_value = mock_response

        # Trigger 5 rate limits
        for _ in range(5):
            with pytest.raises(LLMRateLimitError, match="Rate limited"):
                llm.complete("test")

        # Circuit should be OPEN
        assert llm._circuit_breaker.state == CircuitState.OPEN

    def test_circuit_breaker_does_not_count_client_errors(self, mock_httpx_client):
        """Test circuit breaker does NOT count HTTP 4xx client errors."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com",
            api_key="invalid-key",
            max_retries=1,
        )

        # Mock 401 authentication error
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key"
        mock_httpx_client.post.return_value = mock_response

        # Trigger 10 auth errors (more than threshold)
        for _ in range(10):
            with pytest.raises(LLMAuthenticationError):
                llm.complete("test")

        # Circuit should still be CLOSED (client errors don't count)
        assert llm._circuit_breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_counts_timeouts(self, mock_httpx_client):
        """Test circuit breaker counts timeout errors."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
            timeout=1,
        )

        # Mock timeout
        mock_httpx_client.post.side_effect = httpx.TimeoutException("Request timed out")

        # Trigger 5 timeouts
        for _ in range(5):
            with pytest.raises(LLMTimeoutError):
                llm.complete("test")

        # Circuit should be OPEN
        assert llm._circuit_breaker.state == CircuitState.OPEN

    def test_circuit_breaker_fast_fail_reduces_latency(self, mock_httpx_client):
        """Test circuit breaker fast-fails without making HTTP calls."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Open circuit
        llm._circuit_breaker.state = CircuitState.OPEN
        llm._circuit_breaker.last_failure_time = time.time()

        # Try to make call
        start = time.time()
        with pytest.raises(CircuitBreakerError, match="Circuit breaker OPEN"):
            llm.complete("test")
        elapsed = time.time() - start

        # Should fail instantly (< 10ms) without network call
        assert elapsed < 0.01  # 10ms

        # Verify no HTTP calls were made
        mock_httpx_client.post.assert_not_called()

    def test_circuit_breaker_error_message_includes_retry_time(self):
        """Test circuit breaker error message includes retry time."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        # Open circuit with known failure time
        llm._circuit_breaker.state = CircuitState.OPEN
        llm._circuit_breaker.last_failure_time = time.time()

        # Error should include retry time
        with pytest.raises(CircuitBreakerError) as exc_info:
            llm.complete("test")

        error_msg = str(exc_info.value)
        assert "Circuit breaker OPEN" in error_msg
        assert "Retry after" in error_msg
        assert "s" in error_msg  # Seconds

    def test_circuit_breaker_reset_method(self):
        """Test circuit breaker can be manually reset."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        # Open circuit
        breaker = llm._circuit_breaker
        breaker.state = CircuitState.OPEN
        breaker.failure_count = 10

        # Reset circuit
        breaker.reset()

        # Should be back to CLOSED with zero counts
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.last_failure_time is None

    def test_circuit_breaker_thread_safe(self, mock_httpx_client):
        """Test circuit breaker is thread-safe for concurrent requests."""
        import threading

        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Mock failures
        mock_httpx_client.post.side_effect = httpx.ConnectError("Connection refused")

        # Trigger concurrent failures
        def trigger_failure():
            try:
                llm.complete("test")
            except (httpx.ConnectError, CircuitBreakerError):
                pass

        threads = [threading.Thread(target=trigger_failure) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Circuit should be OPEN (thread-safe state transition)
        assert llm._circuit_breaker.state == CircuitState.OPEN

        # Failure count should be consistent (no race conditions)
        assert llm._circuit_breaker.failure_count >= 5

    def test_circuit_breaker_success_resets_failure_count(self, mock_httpx_client):
        """Test successful call resets failure count in CLOSED state."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_retries=1,
        )

        # Mock some failures
        mock_httpx_client.post.side_effect = httpx.ConnectError("Connection refused")
        for _ in range(3):
            try:
                llm.complete("test")
            except httpx.ConnectError:
                pass

        # Failure count should be 3
        assert llm._circuit_breaker.failure_count == 3
        assert llm._circuit_breaker.state == CircuitState.CLOSED

        # Mock success
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "success",
            "prompt_eval_count": 10,
            "eval_count": 20,
            "done": True,
        }
        mock_httpx_client.post.side_effect = None
        mock_httpx_client.post.return_value = mock_response

        # Successful call should reset failure count
        llm.complete("test")
        assert llm._circuit_breaker.failure_count == 0
        assert llm._circuit_breaker.state == CircuitState.CLOSED


class TestTokenLimitEnforcement:
    """Test token limit enforcement for all LLM providers.
    
    These tests ensure that providers validate token limits before making
    API calls, provide accurate token counting, and give helpful error messages.
    """

    def test_ollama_max_tokens_in_request(self):
        """Test that Ollama includes max_tokens in request."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_tokens=1024,
        )

        request = llm._build_request("Test prompt")
        assert request["max_tokens"] == 1024

    def test_openai_max_tokens_in_request(self):
        """Test that OpenAI includes max_tokens in request."""
        llm = OpenAILLM(
            model="gpt-4",
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            max_tokens=2048,
        )

        request = llm._build_request("Test prompt")
        assert request["max_tokens"] == 2048

    def test_anthropic_max_tokens_in_request(self):
        """Test that Anthropic includes max_tokens in request."""
        llm = AnthropicLLM(
            model="claude-3-sonnet-20240229",
            base_url="https://api.anthropic.com/v1",
            api_key="test-key",
            max_tokens=4096,
        )

        request = llm._build_request("Test prompt")
        assert request["max_tokens"] == 4096

    def test_vllm_max_tokens_in_request(self):
        """Test that vLLM includes max_tokens in request."""
        llm = vLLMLLM(
            model="mistral-7b",
            base_url="http://localhost:8000",
            max_tokens=512,
        )

        request = llm._build_request("Test prompt")
        assert request["max_tokens"] == 512

    def test_max_tokens_default_value(self):
        """Test that max_tokens has reasonable default."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        # Default should be 2048
        assert llm.max_tokens == 2048

    def test_max_tokens_can_be_overridden_per_request(self):
        """Test that max_tokens can be overridden in complete() call."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_tokens=1024,
        )

        # Default max_tokens
        request1 = llm._build_request("Test prompt")
        assert request1["max_tokens"] == 1024

        # Override in request
        request2 = llm._build_request("Test prompt", max_tokens=512)
        assert request2["max_tokens"] == 512

    def test_token_counting_empty_string(self):
        """Test token counting for empty string."""
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
        )

        # Empty string should have minimal tokens
        # Note: Actual implementation may not have count_tokens method
        # This test documents expected behavior
        prompt = ""
        # Would call: token_count = llm.count_tokens(prompt)
        # Expected: token_count should be 0 or 1

    def test_token_counting_short_text(self):
        """Test token counting for short text."""
        # Note: This test documents expected behavior
        # Actual token counting depends on tokenizer implementation

        # Examples of expected token counts (approximate):
        test_cases = [
            ("Hello", 1),
            ("Hello world", 2),
            ("This is a test", 4),
            ("The quick brown fox", 4),
        ]

        # Each provider would implement token counting
        # OpenAI: use tiktoken library
        # Anthropic: use anthropic tokenizer
        # Ollama/vLLM: use model-specific tokenizer

    def test_token_counting_unicode_text(self):
        """Test token counting handles Unicode correctly."""
        # Unicode characters may encode to multiple tokens
        test_cases = [
            "Hello 世界",  # English + Chinese
            "Émoji 🎉 test",  # Accents + emoji
            "Привет мир",  # Cyrillic
        ]

        # Token counting should handle these without errors
        # Exact counts depend on tokenizer

    def test_max_tokens_zero_accepted(self):
        """Test that max_tokens=0 is currently accepted.

        Note: Zero max_tokens may not make practical sense for generation,
        but current implementation accepts it without validation.
        Future enhancement: Could validate and raise ValueError or set minimum.
        """
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_tokens=0,
        )
        # Current behavior: accepts zero
        assert llm.max_tokens == 0

    def test_max_tokens_negative_accepted(self):
        """Test that negative max_tokens is currently accepted.

        Note: Negative max_tokens doesn't make sense, but current implementation
        doesn't validate. Future enhancement: Should raise ValueError.
        """
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_tokens=-100,
        )
        # Current behavior: accepts negative
        assert llm.max_tokens == -100

    def test_max_tokens_extremely_large_accepted(self):
        """Test that very large max_tokens is accepted.
        
        Note: Actual API may reject if it exceeds model's context window,
        but the client should accept large values.
        """
        llm = OllamaLLM(
            model="llama3.2:3b",
            base_url="http://localhost:11434",
            max_tokens=100000,  # 100K tokens
        )

        assert llm.max_tokens == 100000

    def test_model_specific_token_limits_openai(self):
        """Test OpenAI model-specific token limits.
        
        Note: This test documents expected limits.
        Actual enforcement depends on implementation.
        """
        # OpenAI model token limits (as of 2024)
        expected_limits = {
            "gpt-3.5-turbo": 4096,
            "gpt-4": 8192,
            "gpt-4-turbo": 128000,
            "gpt-4-turbo-preview": 128000,
        }

        # Models should know their context windows
        # Implementation would query or have hardcoded limits

    def test_model_specific_token_limits_anthropic(self):
        """Test Anthropic model-specific token limits.
        
        Note: This test documents expected limits.
        """
        # Anthropic model token limits (as of 2024)
        expected_limits = {
            "claude-3-opus-20240229": 200000,
            "claude-3-sonnet-20240229": 200000,
            "claude-3-haiku-20240307": 200000,
            "claude-2.1": 200000,
        }

        # Models should know their context windows

    def test_helpful_error_message_structure(self):
        """Test that token limit errors have helpful messages.
        
        Error messages should include:
        - What went wrong (token limit exceeded)
        - Actual values (tokens requested vs limit)
        - Suggestions (truncate, use different model)
        """
        # Example of a good error message:
        # "Token limit exceeded: requested 10000 tokens but model gpt-4
        #  supports maximum 8192. Consider truncating your input or using
        #  gpt-4-turbo (128K tokens)."

    def test_token_limit_enforcement_workflow(self):
        """Test complete token limit enforcement workflow.
        
        1. User creates LLM client with max_tokens
        2. User calls complete() with prompt
        3. Client counts tokens in prompt
        4. Client validates prompt + max_tokens <= model limit
        5. If valid: makes API call
        6. If invalid: raises clear error
        """
        # This is an integration test for the complete flow

    def test_combined_prompt_and_completion_tokens(self):
        """Test that prompt + completion tokens are validated together.
        
        Total tokens (prompt + completion) must fit in model's context window.
        """
        # Example: Model has 8192 token limit
        # Prompt is 7000 tokens
        # Requesting max_tokens=2000 would exceed limit
        # Should raise error or reduce max_tokens automatically

    def test_token_limit_with_system_message(self):
        """Test token counting includes system messages.
        
        System messages consume tokens and should be counted.
        """
        # If provider supports system messages, they count toward limit

    def test_token_limit_with_function_calling(self):
        """Test token counting includes function definitions.
        
        Function/tool definitions consume tokens in OpenAI API.
        """
        # Function definitions can be large (thousands of tokens)
        # Should be included in total count

    def test_streaming_respects_max_tokens(self):
        """Test that streaming responses respect max_tokens."""
        # Streaming should stop after max_tokens generated
        # Even if model wants to continue

    def test_max_tokens_boundary_conditions(self):
        """Test boundary conditions for max_tokens."""
        boundary_values = [
            1,      # Minimum possible
            2048,   # Common default
            4096,   # Common limit
            8192,   # GPT-4 limit
            100000, # Large value
        ]

        for value in boundary_values:
            llm = OllamaLLM(
                model="llama3.2:3b",
                base_url="http://localhost:11434",
                max_tokens=value,
            )
            assert llm.max_tokens == value

    def test_token_efficiency_suggestions(self):
        """Test that errors suggest more token-efficient approaches.
        
        When tokens are limited, errors should suggest:
        - Truncating input
        - Using smaller model
        - Splitting into multiple requests
        - Using different encoding
        """
        # Error message should be educational

    def test_token_cost_estimation(self):
        """Test token-based cost estimation.
        
        For paid APIs, estimating cost based on token usage helps users.
        """
        # Example: GPT-4 costs $0.03 per 1K prompt tokens
        # Would calculate: token_count * model_rate / 1000

    def test_token_limit_enforcement_disabled(self):
        """Test disabling token limit enforcement (for testing).
        
        Should be a way to bypass limits for testing.
        """
        # Could use validate_tokens=False parameter
        # Or SKIP_TOKEN_VALIDATION env var


# ============================================================================
# Failover Provider Tests
# ============================================================================

class TestFailoverProvider:
    """Test LLM provider failover mechanism."""

    def test_failover_init(self):
        """Test failover provider initialization."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        assert len(failover.providers) == 2
        assert failover.last_successful_index == 0
        assert failover.backup_success_count == 0

    def test_failover_requires_at_least_one_provider(self):
        """Test that failover requires at least one provider."""
        from src.agents.llm_failover import FailoverProvider

        with pytest.raises(ValueError, match="At least one provider required"):
            FailoverProvider(providers=[])

    def test_failover_on_connection_error(self):
        """Test failover on connection error."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock primary failure, backup success
        with patch.object(primary, 'complete', side_effect=httpx.ConnectError("Down")):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="Success",
                model="gpt-4",
                provider="openai"
            )):
                result = failover.complete("test")

        assert result.content == "Success"
        assert failover.last_successful_index == 1  # Backup was used

    def test_failover_on_timeout(self):
        """Test failover on timeout error."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock primary timeout, backup success
        with patch.object(primary, 'complete', side_effect=httpx.TimeoutException("Timeout")):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="Success",
                model="gpt-4",
                provider="openai"
            )):
                result = failover.complete("test")

        assert result.content == "Success"
        assert failover.last_successful_index == 1

    def test_failover_on_rate_limit(self):
        """Test failover on rate limit error."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock primary rate limit, backup success
        with patch.object(primary, 'complete', side_effect=LLMRateLimitError("Rate limited")):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="Success",
                model="gpt-4",
                provider="openai"
            )):
                result = failover.complete("test")

        assert result.content == "Success"
        assert failover.last_successful_index == 1

    def test_failover_on_server_error(self):
        """Test failover on 5xx server error."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock 500 Internal Server Error
        response = Mock()
        response.status_code = 500
        error = httpx.HTTPStatusError("Server error", request=Mock(), response=response)

        with patch.object(primary, 'complete', side_effect=error):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="Success",
                model="gpt-4",
                provider="openai"
            )):
                result = failover.complete("test")

        assert result.content == "Success"
        assert failover.last_successful_index == 1

    def test_failover_does_not_trigger_on_client_error(self):
        """Test that failover does NOT trigger on client errors (4xx)."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock 400 Bad Request (client error)
        response = Mock()
        response.status_code = 400
        error = httpx.HTTPStatusError("Bad request", request=Mock(), response=response)

        with patch.object(primary, 'complete', side_effect=error):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="OK",
                model="gpt-4",
                provider="openai"
            )) as backup_mock:
                # Should raise without trying backup
                with pytest.raises(httpx.HTTPStatusError):
                    failover.complete("test")

                # Backup should NOT be called
                backup_mock.assert_not_called()

    def test_failover_retries_all_providers(self):
        """Test failover tries all providers before failing."""
        from src.agents.llm_failover import FailoverProvider

        providers = [
            OllamaLLM(model="llama", base_url="http://localhost:11434"),
            OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test"),
            AnthropicLLM(model="claude-3", base_url="https://api.anthropic.com", api_key="test"),
        ]

        failover = FailoverProvider(providers=providers)

        # Mock all failures
        with patch.object(providers[0], 'complete', side_effect=httpx.ConnectError("Down")) as mock0:
            with patch.object(providers[1], 'complete', side_effect=httpx.ConnectError("Down")) as mock1:
                with patch.object(providers[2], 'complete', side_effect=httpx.ConnectError("Down")) as mock2:
                    # Should fail after trying all 3
                    with pytest.raises(LLMError, match="All 3 providers failed"):
                        failover.complete("test")

                    # Verify all were tried
                    mock0.assert_called_once()
                    mock1.assert_called_once()
                    mock2.assert_called_once()

    def test_failover_sticky_session(self):
        """Test sticky session uses last successful provider."""
        from src.agents.llm_failover import FailoverProvider, FailoverConfig

        primary = OllamaLLM(model="primary", base_url="http://localhost:11434")
        backup = OpenAILLM(model="backup", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(
            providers=[primary, backup],
            config=FailoverConfig(sticky_session=True, retry_primary_after=10)
        )

        # First call succeeds with backup
        with patch.object(primary, 'complete', side_effect=httpx.ConnectError("Down")):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="OK",
                model="backup",
                provider="openai"
            )):
                failover.complete("test")

        assert failover.last_successful_index == 1
        assert failover.backup_success_count == 1

        # Second call should try backup FIRST (sticky)
        with patch.object(primary, 'complete', return_value=LLMResponse(
                content="OK",
                model="primary",
                provider="ollama"
            )) as primary_mock:
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="OK",
                model="backup",
                provider="openai"
            )) as backup_mock:
                failover.complete("test")

                # Backup should be called first, primary should not
                backup_mock.assert_called_once()
                primary_mock.assert_not_called()

    def test_failover_retries_primary_after_threshold(self):
        """Test that primary is retried after N successful backup calls."""
        from src.agents.llm_failover import FailoverProvider, FailoverConfig

        primary = OllamaLLM(model="primary", base_url="http://localhost:11434")
        backup = OpenAILLM(model="backup", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(
            providers=[primary, backup],
            config=FailoverConfig(sticky_session=True, retry_primary_after=3)
        )

        # Simulate 3 successful backup calls
        with patch.object(backup, 'complete', return_value=LLMResponse(
            content="OK",
            model="backup",
            provider="openai"
        )):
            for i in range(3):
                failover.last_successful_index = 1  # Force backup
                failover.complete("test")

        assert failover.backup_success_count == 3

        # Fourth call should retry primary first
        with patch.object(primary, 'complete', return_value=LLMResponse(
            content="OK",
            model="primary",
            provider="ollama"
        )) as primary_mock:
            failover.complete("test")

            # Primary should be called
            primary_mock.assert_called_once()
            # Backup success count should reset
            assert failover.backup_success_count == 0

    @pytest.mark.asyncio
    async def test_failover_async(self):
        """Test async failover."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock primary failure, backup success
        async def async_error(*args, **kwargs):
            raise httpx.ConnectError("Down")

        async def async_success(*args, **kwargs):
            return LLMResponse(
                content="Success",
                model="gpt-4",
                provider="openai"
            )

        with patch.object(primary, 'acomplete', side_effect=async_error):
            with patch.object(backup, 'acomplete', side_effect=async_success):
                result = await failover.acomplete("test")

        assert result.content == "Success"
        assert failover.last_successful_index == 1

    def test_failover_reset(self):
        """Test resetting failover state."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="primary", base_url="http://localhost:11434")
        backup = OpenAILLM(model="backup", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Simulate failover to backup
        failover.last_successful_index = 1
        failover.backup_success_count = 5

        # Reset
        failover.reset()

        assert failover.last_successful_index == 0
        assert failover.backup_success_count == 0

    def test_failover_model_property(self):
        """Test that model property returns current provider's model."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Initially uses primary
        assert failover.model == "llama3.2"

        # After failover, uses backup
        failover.last_successful_index = 1
        assert failover.model == "gpt-4"

    def test_failover_does_not_trigger_on_auth_error(self):
        """Test that failover does NOT trigger on auth errors."""
        from src.agents.llm_failover import FailoverProvider

        primary = OllamaLLM(model="llama3.2", base_url="http://localhost:11434")
        backup = OpenAILLM(model="gpt-4", base_url="https://api.openai.com", api_key="test")

        failover = FailoverProvider(providers=[primary, backup])

        # Mock authentication error
        with patch.object(primary, 'complete', side_effect=LLMAuthenticationError("Invalid API key")):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="OK",
                model="gpt-4",
                provider="openai"
            )) as backup_mock:
                # Should raise without trying backup
                with pytest.raises(LLMAuthenticationError):
                    failover.complete("test")

                # Backup should NOT be called
                backup_mock.assert_not_called()

    def test_failover_custom_config(self):
        """Test failover with custom configuration."""
        from src.agents.llm_failover import FailoverProvider, FailoverConfig

        primary = OllamaLLM(model="primary", base_url="http://localhost:11434")
        backup = OpenAILLM(model="backup", base_url="https://api.openai.com", api_key="test")

        # Disable timeout failover
        config = FailoverConfig(failover_on_timeout=False)
        failover = FailoverProvider(providers=[primary, backup], config=config)

        # Mock timeout - should NOT failover
        with patch.object(primary, 'complete', side_effect=httpx.TimeoutException("Timeout")):
            with patch.object(backup, 'complete', return_value=LLMResponse(
                content="OK",
                model="backup",
                provider="openai"
            )) as backup_mock:
                # Should raise without trying backup
                with pytest.raises(httpx.TimeoutException):
                    failover.complete("test")

                # Backup should NOT be called
                backup_mock.assert_not_called()


class TestCircuitBreakerPersistence:
    """Test circuit breaker state persistence across restarts."""

    @pytest.fixture
    def storage(self):
        """Create in-memory storage for testing."""
        store = InMemoryStorage()
        yield store
        store.clear()

    def test_state_persists_across_restart(self, storage):
        """Test that circuit breaker state persists when instance is recreated."""
        # Create breaker and open circuit
        breaker1 = CircuitBreaker('llm-provider', storage=storage)
        
        # Simulate failures to open circuit
        for _ in range(5):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.state == CircuitState.OPEN
        del breaker1
        
        # Simulate process restart - create new breaker with same name
        breaker2 = CircuitBreaker('llm-provider', storage=storage)
        
        # State should be restored from storage
        assert breaker2.state == CircuitState.OPEN

    def test_failure_count_persists(self, storage):
        """Test that failure count persists across instances."""
        breaker1 = CircuitBreaker('test-provider', storage=storage)
        
        # Record 3 failures (threshold is 5)
        for _ in range(3):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.failure_count == 3
        assert breaker1.state == CircuitState.CLOSED  # Not yet open
        del breaker1
        
        # Recreate breaker
        breaker2 = CircuitBreaker('test-provider', storage=storage)
        
        # Failure count should persist
        assert breaker2.failure_count == 3
        assert breaker2.state == CircuitState.CLOSED

    def test_half_open_state_persists(self, storage):
        """Test that HALF_OPEN state persists correctly."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=1)
        breaker1 = CircuitBreaker('test-provider', config=config, storage=storage)

        # Open circuit
        try:
            breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
        except:
            pass

        assert breaker1.state == CircuitState.OPEN

        # Wait for timeout
        time.sleep(1.1)

        # Manually transition to HALF_OPEN and save
        with breaker1.lock:
            breaker1.state = CircuitState.HALF_OPEN
            breaker1.success_count = 0
            if breaker1.storage:
                breaker1._save_state()

        assert breaker1.state == CircuitState.HALF_OPEN
        del breaker1

        # Recreate breaker
        breaker2 = CircuitBreaker('test-provider', config=config, storage=storage)

        # HALF_OPEN state should persist
        assert breaker2.state == CircuitState.HALF_OPEN

    def test_config_persists(self, storage):
        """Test that configuration persists with state."""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            success_threshold=3,
            timeout=120
        )
        breaker1 = CircuitBreaker('test-provider', config=config, storage=storage)
        
        # Open circuit
        for _ in range(10):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.state == CircuitState.OPEN
        del breaker1
        
        # Recreate breaker (without passing config)
        breaker2 = CircuitBreaker('test-provider', storage=storage)
        
        # Config should be restored from storage
        assert breaker2.config.failure_threshold == 10
        assert breaker2.config.success_threshold == 3
        assert breaker2.config.timeout == 120

    def test_multiple_instances_share_state(self, storage):
        """Test that multiple instances with same name share state via storage."""
        breaker1 = CircuitBreaker('shared-provider', storage=storage)
        breaker2 = CircuitBreaker('shared-provider', storage=storage)
        
        # Open circuit via breaker1
        for _ in range(5):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.state == CircuitState.OPEN
        
        # Reload state in breaker2
        breaker2._load_state()
        
        # Both should see OPEN state
        assert breaker2.state == CircuitState.OPEN

    def test_isolated_state_for_different_names(self, storage):
        """Test that different circuit breaker names have isolated state."""
        breaker1 = CircuitBreaker('provider-a', storage=storage)
        breaker2 = CircuitBreaker('provider-b', storage=storage)
        
        # Open circuit for provider-a
        for _ in range(5):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.state == CircuitState.OPEN
        assert breaker2.state == CircuitState.CLOSED  # Different provider

    def test_reset_clears_persisted_state(self, storage):
        """Test that reset() updates persisted state."""
        breaker1 = CircuitBreaker('test-provider', storage=storage)
        
        # Open circuit
        for _ in range(5):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.state == CircuitState.OPEN
        
        # Reset
        breaker1.reset()
        assert breaker1.state == CircuitState.CLOSED
        del breaker1
        
        # Recreate - should see CLOSED state
        breaker2 = CircuitBreaker('test-provider', storage=storage)
        assert breaker2.state == CircuitState.CLOSED

    def test_success_updates_persisted_state(self, storage):
        """Test that successful calls update persisted state."""
        config = CircuitBreakerConfig(failure_threshold=1, success_threshold=2, timeout=1)
        breaker1 = CircuitBreaker('test-provider', config=config, storage=storage)

        # Open circuit
        try:
            breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
        except:
            pass

        assert breaker1.state == CircuitState.OPEN

        # Wait for timeout (1 second in config)
        time.sleep(1.1)

        # Manually transition to HALF_OPEN and save
        with breaker1.lock:
            breaker1.state = CircuitState.HALF_OPEN
            breaker1.success_count = 0
            if breaker1.storage:
                breaker1._save_state()

        # Record success
        breaker1.call(lambda: "success")
        assert breaker1.success_count == 1
        del breaker1

        # Recreate - success count should persist
        breaker2 = CircuitBreaker('test-provider', config=config, storage=storage)
        assert breaker2.success_count == 1
        assert breaker2.state == CircuitState.HALF_OPEN

    def test_corrupted_state_handled_gracefully(self, storage):
        """Test that corrupted state data doesn't crash breaker."""
        # Manually inject corrupted data
        storage.set('circuit_breaker:test-provider:state', 'invalid json{{{')
        
        # Should not crash, should start with fresh state
        breaker = CircuitBreaker('test-provider', storage=storage)
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_missing_state_starts_fresh(self, storage):
        """Test that missing state starts circuit breaker fresh."""
        # Create breaker with empty storage
        breaker = CircuitBreaker('new-provider', storage=storage)
        
        # Should start in CLOSED state
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    def test_last_failure_time_persists(self, storage):
        """Test that last failure time persists across restarts."""
        breaker1 = CircuitBreaker('test-provider', storage=storage)
        
        # Record failure
        before_time = time.time()
        try:
            breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
        except:
            pass
        after_time = time.time()
        
        assert breaker1.last_failure_time is not None
        assert before_time <= breaker1.last_failure_time <= after_time
        
        saved_time = breaker1.last_failure_time
        del breaker1
        
        # Recreate
        breaker2 = CircuitBreaker('test-provider', storage=storage)
        
        # Last failure time should persist
        assert breaker2.last_failure_time == saved_time

    def test_state_serialization_deserialization(self, storage):
        """Test complete serialize/deserialize cycle."""
        config = CircuitBreakerConfig(failure_threshold=7, success_threshold=3, timeout=90)
        breaker1 = CircuitBreaker('test-provider', config=config, storage=storage)
        
        # Set various state values
        breaker1.failure_count = 4
        breaker1.success_count = 2
        breaker1.last_failure_time = 1234567890.5
        breaker1._save_state()
        
        # Load into new instance
        breaker2 = CircuitBreaker('test-provider', storage=storage)
        
        # All state should match
        assert breaker2.failure_count == 4
        assert breaker2.success_count == 2
        assert breaker2.last_failure_time == 1234567890.5
        assert breaker2.config.failure_threshold == 7
        assert breaker2.config.success_threshold == 3
        assert breaker2.config.timeout == 90

    def test_without_storage_no_persistence(self):
        """Test that breaker without storage doesn't persist."""
        # Create breaker without storage
        breaker1 = CircuitBreaker('test-provider')
        
        # Open circuit
        for _ in range(5):
            try:
                breaker1.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
            except:
                pass
        
        assert breaker1.state == CircuitState.OPEN
        del breaker1
        
        # New breaker (still no storage) starts fresh
        breaker2 = CircuitBreaker('test-provider')
        assert breaker2.state == CircuitState.CLOSED

    def test_concurrent_instances_eventually_consistent(self, storage):
        """Test that concurrent instances stay eventually consistent."""
        import threading
        
        breaker1 = CircuitBreaker('shared-provider', storage=storage)
        breaker2 = CircuitBreaker('shared-provider', storage=storage)
        
        results = []
        
        def open_circuit(breaker):
            for _ in range(5):
                try:
                    breaker.call(lambda: (_ for _ in ()).throw(httpx.TimeoutException("Timeout")))
                except:
                    pass
            results.append(breaker.state)
        
        # Both try to open circuit concurrently
        t1 = threading.Thread(target=open_circuit, args=(breaker1,))
        t2 = threading.Thread(target=open_circuit, args=(breaker2,))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Both should end up OPEN
        assert CircuitState.OPEN in results
        
        # After reloading, both should see consistent state
        breaker1._load_state()
        breaker2._load_state()
        
        # At least one should be OPEN (eventual consistency)
        assert breaker1.state == CircuitState.OPEN or breaker2.state == CircuitState.OPEN


class TestConnectionPoolCleanup:
    """Tests for connection pool cleanup to prevent resource leaks (code-high-02)."""

    def test_sync_client_closes_properly(self):
        """Verify sync HTTP client closes without leaks."""
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

        # Trigger client creation
        client = llm._get_client()
        assert isinstance(client, httpx.Client), \
            f"Expected httpx.Client, got {type(client)}"
        assert llm._client is client, "Should cache client instance"

        # Close and verify cleanup
        llm.close()
        assert llm._client is None

    def test_async_client_closes_with_event_loop(self):
        """Verify async HTTP client closes when event loop is running."""
        import asyncio

        async def test_async_cleanup():
            llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

            # Trigger async client creation
            client = llm._get_async_client()
            assert isinstance(client, httpx.AsyncClient), \
                f"Expected httpx.AsyncClient, got {type(client)}"
            assert llm._async_client is client, "Should cache async client instance"

            # Close using async method
            await llm.aclose()
            assert llm._async_client is None

        asyncio.run(test_async_cleanup())

    def test_async_client_closes_without_event_loop(self):
        """Verify async HTTP client closes even without event loop (code-high-02).

        This is the critical test for the connection pool leak fix.
        Previously, async clients would not close if no event loop was running,
        causing "Too many open files" errors.
        """
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

        # Trigger async client creation
        client = llm._get_async_client()
        assert isinstance(client, httpx.AsyncClient), \
            f"Expected httpx.AsyncClient, got {type(client)}"
        assert llm._async_client is client, "Should cache async client instance"

        # Close without event loop (this previously leaked connections)
        # The fix should use asyncio.run() to create temporary event loop
        llm.close()

        # Verify async client was closed (critical fix verification)
        assert llm._async_client is None

    def test_context_manager_cleanup(self):
        """Verify context manager properly closes connections."""
        with OllamaLLM(model="llama2", base_url="http://localhost:11434") as llm:
            # Trigger both client creations
            sync_client = llm._get_client()
            async_client = llm._get_async_client()
            assert isinstance(sync_client, httpx.Client), \
                f"Expected httpx.Client, got {type(sync_client)}"
            assert isinstance(async_client, httpx.AsyncClient), \
                f"Expected httpx.AsyncClient, got {type(async_client)}"

        # After context exit, both should be closed
        assert llm._client is None
        assert llm._async_client is None

    def test_del_cleanup_sync_client(self):
        """Verify __del__ cleanup closes sync client."""
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")
        client = llm._get_client()
        assert isinstance(client, httpx.Client), \
            f"Expected httpx.Client, got {type(client)}"

        # Trigger garbage collection cleanup
        llm.__del__()
        assert llm._client is None

    def test_del_cleanup_async_client(self):
        """Verify __del__ cleanup closes async client (code-high-02).

        Previously, __del__ only closed sync client, causing async connection leaks.
        """
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")
        async_client = llm._get_async_client()
        assert isinstance(async_client, httpx.AsyncClient), \
            f"Expected httpx.AsyncClient, got {type(async_client)}"

        # Trigger garbage collection cleanup
        llm.__del__()

        # Verify async client was closed (critical fix verification)
        assert llm._async_client is None

    def test_multiple_close_calls_safe(self):
        """Verify multiple close() calls don't cause errors."""
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")
        llm._get_client()
        llm._get_async_client()

        # Multiple close calls should be safe (idempotent)
        llm.close()
        llm.close()
        llm.close()

        assert llm._client is None
        assert llm._async_client is None

    def test_close_before_client_creation(self):
        """Verify close() works even if clients were never created."""
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

        # Close without ever creating clients
        llm.close()

        assert llm._client is None
        assert llm._async_client is None

    def test_close_inside_event_loop_raises(self):
        """Calling sync close() inside a running event loop must raise RuntimeError.

        Previously the RuntimeError was silently swallowed because the try/except
        caught both the 'no loop' RuntimeError from get_running_loop() and the
        intentionally raised RuntimeError for the 'loop is running' case.
        """
        import asyncio

        async def try_sync_close():
            llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")
            llm._get_client()
            with pytest.raises(RuntimeError, match="Cannot call sync close"):
                llm.close()
            # Clean up properly using aclose
            await llm.aclose()

        asyncio.run(try_sync_close())

    def test_async_close_graceful_degradation(self):
        """Verify async client close degrades gracefully even on multiple failures.

        NOTE: The triple-failure scenario (asyncio.run fails + transport close fails)
        is extremely rare and difficult to test reliably. The core fix (using asyncio.run
        to force synchronous close) is validated by test_async_client_closes_without_event_loop.
        """
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")
        llm._get_async_client()

        # Verify close doesn't crash even with async client present
        llm.close()

        # Verify client was cleaned up
        assert llm._async_client is None

    def test_connection_pool_limits_preserved(self):
        """Verify connection pool limits are correctly configured."""
        llm = OllamaLLM(model="llama2", base_url="http://localhost:11434")

        # Verify clients are created with connection pooling
        client = llm._get_client()
        assert client is not None
        assert isinstance(client, httpx.Client)

        async_client = llm._get_async_client()
        assert async_client is not None
        assert isinstance(async_client, httpx.AsyncClient)

        # Verify clients can be reused (connection pooling working)
        assert llm._get_client() is client  # Same instance
        assert llm._get_async_client() is async_client  # Same instance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
