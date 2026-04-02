"""Base LLM provider — abstract HTTP client for LLM APIs.

Subclasses implement provider-specific request building, response parsing,
and stream consumption. Retry with exponential backoff is built in.
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Callable

import httpx

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.observability import EventType, record

logger = logging.getLogger(__name__)

StreamCallback = Callable[[LLMStreamChunk], None]

# Retryable HTTP status codes
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


def _should_retry(exc: httpx.HTTPStatusError) -> bool:
    """Return True if an HTTP status error is retryable."""
    return exc.response.status_code in _RETRYABLE_STATUS_CODES


def _compute_backoff(attempt: int) -> float:
    """Return exponential backoff delay with jitter, capped at 30s."""
    return min(2**attempt + random.random(), 30)  # noqa: B311


class BaseLLM(ABC):
    """Abstract base for LLM providers.

    Provides retry logic and httpx client management. Subclasses implement
    the four abstract methods for provider-specific behavior.
    """

    def __init__(  # noqa: params
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 600,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra_kwargs = kwargs
        self._http_client: httpx.Client | None = None

    # Subclasses should override with a semantic name (e.g., "openai", "vllm")
    PROVIDER_NAME: str = "unknown"

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    def _get_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=float(self.timeout),
                    write=30.0,
                    pool=10.0,
                ),
                headers=self._get_headers(),
            )
        return self._http_client

    def complete(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Send a completion request with retry on transient failures."""
        request = self._build_request(messages, **kwargs)
        return self._execute_with_retry(request, stream=False)

    def stream(
        self,
        messages: list[dict],
        on_chunk: StreamCallback | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a streaming request with retry on transient failures."""
        request = self._build_request(messages, stream=True, **kwargs)
        return self._execute_with_retry(request, stream=True, on_chunk=on_chunk)

    def _execute_with_retry(
        self,
        request: dict,
        stream: bool = False,
        on_chunk: StreamCallback | None = None,
    ) -> LLMResponse:
        last_error: Exception | None = None
        client = self._get_client()
        endpoint = self._get_endpoint()

        for attempt in range(self.max_retries):
            try:
                start = time.monotonic()
                if stream:
                    with client.stream("POST", endpoint, json=request) as response:
                        response.raise_for_status()
                        result = self._consume_stream(response, on_chunk)
                        result.latency_ms = int((time.monotonic() - start) * 1000)
                        return result
                else:
                    response = client.post(endpoint, json=request)
                    response.raise_for_status()
                    latency_ms = int((time.monotonic() - start) * 1000)
                    return self._parse_response(response.json(), latency_ms)

            except httpx.HTTPStatusError as e:
                last_error = e
                if not _should_retry(e):
                    raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e

            if attempt < self.max_retries - 1:
                delay = _compute_backoff(attempt)
                self._record_retry(last_error, attempt, delay)
                time.sleep(delay)

        raise last_error  # type: ignore[misc]

    def _record_retry(self, last_error: Exception | None, attempt: int, delay: float) -> None:
        """Log and record a retry event."""
        logger.warning(
            "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs",
            attempt + 1, self.max_retries, last_error, delay,
        )
        error_code = None
        if isinstance(last_error, httpx.HTTPStatusError):
            error_code = last_error.response.status_code
        record(
            EventType.LLM_RETRY,
            data={
                "model": self.model,
                "provider": self.provider_name,
                "attempt": attempt + 1,
                "max_retries": self.max_retries,
                "error_type": type(last_error).__name__,
                "error": str(last_error)[:500],
                "error_code": error_code,
                "retry_delay_s": round(delay, 1),
            },
        )

    def close(self) -> None:
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self) -> "BaseLLM":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # -- Abstract methods (subclasses implement these) --

    @abstractmethod
    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        """Build the provider-specific request payload."""

    @abstractmethod
    def _parse_response(self, response: dict, latency_ms: int) -> LLMResponse:
        """Parse provider response into LLMResponse."""

    @abstractmethod
    def _get_headers(self) -> dict[str, str]:
        """Return provider-specific headers."""

    @abstractmethod
    def _get_endpoint(self) -> str:
        """Return the API endpoint path (e.g., '/v1/chat/completions')."""

    @abstractmethod
    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback | None,
    ) -> LLMResponse:
        """Consume a streaming response, calling on_chunk for each delta."""
