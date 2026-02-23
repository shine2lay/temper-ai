"""Base LLM provider: abstract class, response types, and provider enum."""

import asyncio
import collections
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import httpx

# Optional caching support
try:
    from temper_ai.llm.cache.llm_cache import LLMCache

    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    LLMCache = None  # type: ignore

from temper_ai.llm.constants import (
    DEFAULT_MAX_CIRCUIT_BREAKERS,
    DEFAULT_MAX_HTTP_CLIENTS,
    ERROR_MSG_RATE_LIMIT_EXCEEDED,
)

# Helper functions extracted to reduce class size
from temper_ai.llm.providers._base_helpers import (
    LLMContextManagerMixin,
)
from temper_ai.llm.providers._base_helpers import (
    bind_callable_attributes as _bind_callable_attributes,
)
from temper_ai.llm.providers._base_helpers import (
    close_async as _close_async,
)
from temper_ai.llm.providers._base_helpers import (
    close_sync as _close_sync,
)
from temper_ai.llm.providers._base_helpers import (
    get_or_create_async_client_safe as _get_async_client_safe,
)
from temper_ai.llm.providers._base_helpers import (
    get_or_create_async_client_sync as _get_async_client_sync,
)
from temper_ai.llm.providers._base_helpers import (
    get_or_create_sync_client as _get_sync_client,
)
from temper_ai.llm.providers._base_helpers import (
    get_shared_circuit_breaker as _get_shared_cb,
)
from temper_ai.llm.providers._base_helpers import (
    reset_shared_circuit_breakers as _reset_shared_cbs,
)
from temper_ai.llm.providers._base_helpers import (
    reset_shared_http_clients as _reset_shared_http,
)
from temper_ai.llm.providers._base_helpers import (
    validate_base_url as _validate_base_url,
)
from temper_ai.shared.constants.durations import SLEEP_VERY_SHORT, TIMEOUT_HTTP_DEFAULT
from temper_ai.shared.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
    RETRY_JITTER_MIN,
)
from temper_ai.shared.core.circuit_breaker import CircuitBreaker
from temper_ai.shared.core.context import ExecutionContext
from temper_ai.shared.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)

# Timeout and retry constants
DEFAULT_TIMEOUT_SECONDS = TIMEOUT_HTTP_DEFAULT
DEFAULT_BACKOFF_FACTOR = DEFAULT_BACKOFF_MULTIPLIER
CPU_SAMPLE_INTERVAL_SECONDS = SLEEP_VERY_SHORT

# Default LLM parameter values
DEFAULT_TEMPERATURE = 0.7  # Default temperature for generation
DEFAULT_TOP_P = 0.9  # Default nucleus sampling threshold
DEFAULT_REQUEST_TIMEOUT = 600  # Default timeout for LLM requests (10 minutes)
DEFAULT_CACHE_TTL = 3600  # Default cache time-to-live (1 hour)

# HTTP status codes
HTTP_OK = 200  # Successful response
HTTP_UNAUTHORIZED = 401  # Authentication failed
HTTP_RATE_LIMIT = 429  # Rate limit exceeded
HTTP_SERVER_ERROR = 500  # Server error threshold


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    VLLM = "vllm"


@dataclass
class LLMResponse:
    """Standardized LLM response."""

    content: str
    model: str
    provider: str

    # Token usage
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    # Timing
    latency_ms: int | None = None

    # Metadata
    finish_reason: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class LLMStreamChunk:
    """Chunk from streaming response."""

    content: str
    chunk_type: str = "content"  # "thinking" | "content"
    finish_reason: str | None = None
    done: bool = False
    model: str | None = None
    prompt_tokens: int | None = None  # final chunk only
    completion_tokens: int | None = None  # final chunk only


@dataclass
class LLMConfig:
    """Configuration bundle for LLM initialization.

    Groups the 12 parameters into a single config object to reduce
    parameter count and improve maintainability.
    """

    model: str
    base_url: str
    api_key: str | None = None
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = 2048
    top_p: float = DEFAULT_TOP_P
    timeout: int = DEFAULT_REQUEST_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = 2.0
    enable_cache: bool = False
    cache_ttl: int | None = DEFAULT_CACHE_TTL
    rate_limiter: Any | None = None


# Callback type for streaming: called with each chunk as it arrives
StreamCallback = Callable[[LLMStreamChunk], None]


class BaseLLM(LLMContextManagerMixin, ABC):
    """Abstract base class for LLM providers.

    See _base_helpers.py for extracted internal logic.
    """

    # Instance attributes set by _init_infrastructure()
    _client: httpx.Client | None
    _async_client: httpx.AsyncClient | None
    _closed: bool
    _sync_cleanup_lock: threading.Lock
    _async_cleanup_lock: asyncio.Lock | None
    _cache: Optional["LLMCache"]
    _circuit_breaker: CircuitBreaker
    _rate_limiter: Any | None

    # Callable attributes bound dynamically by _bind_callable_attributes()
    _build_bearer_auth_headers: Callable[[], dict[str, str]]
    _check_cache: Callable[
        ..., tuple[str | None, Optional["LLMResponse"]]
    ]  # scanner: skip-magic
    _cache_response: Callable[[str | None, "LLMResponse"], None]  # scanner: skip-magic
    _execute_and_parse: Callable[
        [httpx.Response, float, str | None], "LLMResponse"
    ]  # scanner: skip-magic
    _make_streaming_call_impl: Callable[
        ..., tuple[str | None, Optional["LLMResponse"]]
    ]  # scanner: skip-magic
    _execute_streaming_impl: Callable[..., "LLMResponse"]  # scanner: skip-magic
    _execute_streaming_async_impl: Callable[..., Any]

    _MAX_CIRCUIT_BREAKERS = DEFAULT_MAX_CIRCUIT_BREAKERS
    _circuit_breakers: collections.OrderedDict[tuple[str, str, str], CircuitBreaker] = (
        collections.OrderedDict()
    )
    _circuit_breaker_lock = threading.Lock()

    _MAX_HTTP_CLIENTS = DEFAULT_MAX_HTTP_CLIENTS
    _http_clients: dict[tuple[str, str], httpx.Client] = {}
    _http_client_lock = threading.Lock()

    _async_client_lock: asyncio.Lock | None = None

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        config: LLMConfig | None = None,
        **kwargs: Any,
    ):
        """Initialize LLM provider.

        Args:
            model: Model name (required if config not provided)
            base_url: Base URL (required if config not provided)
            config: LLMConfig bundle (recommended for new code)
            **kwargs: Legacy individual parameters (api_key, temperature, etc.)

        The config parameter takes precedence. If not provided, model/base_url
        are required and kwargs are used for other parameters.
        """
        # Extract params from config or kwargs
        if config is not None:
            self.model = config.model
            self.base_url = _validate_base_url(config.base_url.rstrip("/"))
            self.api_key = config.api_key
            self.temperature = config.temperature
            self.max_tokens = config.max_tokens
            self.top_p = config.top_p
            self.timeout = config.timeout
            self.max_retries = config.max_retries
            self.retry_delay = config.retry_delay
            enable_cache = config.enable_cache
            cache_ttl = config.cache_ttl
            rate_limiter = config.rate_limiter
        else:
            if model is None or base_url is None:
                raise ValueError(
                    "model and base_url are required when config is not provided"
                )
            self.model = model
            self.base_url = _validate_base_url(base_url.rstrip("/"))
            self.api_key = kwargs.get("api_key")
            self.temperature = kwargs.get("temperature", DEFAULT_TEMPERATURE)
            self.max_tokens = kwargs.get("max_tokens", 2048)
            self.top_p = kwargs.get("top_p", DEFAULT_TOP_P)
            self.timeout = kwargs.get("timeout", DEFAULT_REQUEST_TIMEOUT)
            self.max_retries = kwargs.get("max_retries", DEFAULT_MAX_RETRIES)
            self.retry_delay = kwargs.get("retry_delay", 2.0)
            enable_cache = kwargs.get("enable_cache", False)
            cache_ttl = kwargs.get("cache_ttl", DEFAULT_CACHE_TTL)
            rate_limiter = kwargs.get("rate_limiter")

        _init_infrastructure(self, enable_cache, cache_ttl, rate_limiter)

    @classmethod
    def reset_shared_circuit_breakers(cls) -> None:
        """Reset all shared circuit breakers."""
        _reset_shared_cbs(cls._circuit_breakers, cls._circuit_breaker_lock)

    @classmethod
    def reset_shared_http_clients(cls) -> None:
        """Close and remove all shared HTTP clients."""
        _reset_shared_http(cls._http_clients, cls._http_client_lock)

    def _get_client(self) -> httpx.Client:
        """Get or create HTTPx client with lazy initialization."""
        return _get_sync_client(self)

    async def _get_async_client_safe(self) -> httpx.AsyncClient:
        """Get or create async HTTPx client with proper async locking (M-19)."""
        return await _get_async_client_safe(self)

    def _get_async_client(self) -> httpx.AsyncClient:
        """Get or create async HTTPx client (sync accessor, backward compat)."""
        return _get_async_client_sync(self)

    def close(self) -> None:
        """Close sync resources and release references (H-06)."""
        _close_sync(self)

    async def aclose(self) -> None:
        """Async close for HTTPx clients and release resources."""
        await _close_async(self)

    def __del__(self) -> None:
        """Warn about improper cleanup - DO NOT attempt cleanup in finalizer."""
        if not hasattr(self, "_closed"):
            return

        if not self._closed and (
            self._client is not None or self._async_client is not None
        ):
            import warnings

            warnings.warn(
                f"{self.__class__.__name__} was not properly closed. "
                f"Use 'async with' or 'with' context manager to avoid resource leaks. "
                f"Leaked clients will be reclaimed by OS on process exit.",
                ResourceWarning,
                stacklevel=2,
            )

    @abstractmethod
    def _build_request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Build provider-specific request payload."""
        pass

    @abstractmethod
    def _parse_response(self, response: dict[str, Any], latency_ms: int) -> LLMResponse:
        """Parse provider-specific response into standardized format."""
        pass

    @abstractmethod
    def _get_headers(self) -> dict[str, str]:
        """Get provider-specific HTTP headers."""
        pass

    @abstractmethod
    def _get_endpoint(self) -> str:
        """Get provider-specific API endpoint path."""
        pass

    def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume streaming response synchronously (provider-specific).

        Args:
            response: HTTPx response object with streaming enabled
            on_chunk: Callback invoked for each chunk

        Returns:
            LLMResponse with aggregated content and metadata
        """
        raise NotImplementedError(
            "Subclass must implement _consume_stream for streaming support"
        )

    async def _aconsume_stream(
        self,
        response: httpx.Response,
        on_chunk: StreamCallback,
    ) -> LLMResponse:
        """Consume streaming response asynchronously (provider-specific).

        Args:
            response: HTTPx response object with streaming enabled
            on_chunk: Callback invoked for each chunk

        Returns:
            LLMResponse with aggregated content and metadata
        """
        raise NotImplementedError(
            "Subclass must implement _aconsume_stream for streaming support"
        )

    def stream(
        self,
        prompt: str,
        context: ExecutionContext | None = None,
        on_chunk: StreamCallback | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion with streaming. Default: fallback to complete().

        Subclasses override this to provide real streaming. The default
        implementation simply calls complete() and ignores on_chunk.
        """
        return self.complete(prompt, context, **kwargs)

    async def astream(
        self,
        prompt: str,
        context: ExecutionContext | None = None,
        on_chunk: StreamCallback | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async streaming completion. Default: fallback to acomplete().

        Subclasses override this to provide real streaming. The default
        implementation simply calls acomplete() and ignores on_chunk.
        """
        return await self.acomplete(prompt, context, **kwargs)

    def complete(
        self, prompt: str, context: ExecutionContext | None = None, **kwargs: Any
    ) -> LLMResponse:
        """Generate completion for prompt."""
        if self._rate_limiter is not None:
            entity_id = (
                context.agent_id
                if context and hasattr(context, "agent_id")
                else self.model
            )
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                raise LLMRateLimitError(reason or ERROR_MSG_RATE_LIMIT_EXCEEDED)

        cache_key, cached = self._check_cache(prompt, context, **kwargs)
        if cached is not None:
            return cached

        def _make_api_call() -> LLMResponse:
            for attempt in range(self.max_retries):
                try:
                    start_time = time.time()
                    request_data = self._build_request(prompt, **kwargs)
                    headers = self._get_headers()
                    endpoint = f"{self.base_url}{self._get_endpoint()}"

                    response = self._get_client().post(
                        endpoint,
                        json=request_data,
                        headers=headers,
                    )

                    return self._execute_and_parse(response, start_time, cache_key)

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        raise LLMTimeoutError(
                            f"Request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                    # Exponential backoff with jitter (R-15) to decorrelate
                    # retries across concurrent callers.
                    delay = (
                        self.retry_delay
                        * (DEFAULT_BACKOFF_FACTOR**attempt)
                        * (RETRY_JITTER_MIN + random.random())
                    )  # noqa: S311 -- jitter/backoff, not crypto
                    time.sleep(
                        delay
                    )  # Intentional blocking: sync retry uses sleep; use acomplete() for async contexts

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    delay = (
                        self.retry_delay
                        * (DEFAULT_BACKOFF_FACTOR**attempt)
                        * (RETRY_JITTER_MIN + random.random())
                    )  # noqa: S311 -- jitter/backoff, not crypto
                    time.sleep(
                        delay
                    )  # Intentional blocking: sync rate limit backoff; use acomplete() for async contexts

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        return self._circuit_breaker.call(_make_api_call)

    async def acomplete(
        self, prompt: str, context: ExecutionContext | None = None, **kwargs: Any
    ) -> LLMResponse:
        """Async version: Generate completion for prompt."""
        if self._rate_limiter is not None:
            entity_id = (
                context.agent_id
                if context and hasattr(context, "agent_id")
                else self.model
            )
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                raise LLMRateLimitError(reason or ERROR_MSG_RATE_LIMIT_EXCEEDED)

        cache_key, cached = self._check_cache(prompt, context, **kwargs)
        if cached is not None:
            return cached

        async def _make_async_api_call() -> LLMResponse:
            for attempt in range(self.max_retries):
                try:
                    start_time = time.time()
                    request_data = self._build_request(prompt, **kwargs)
                    headers = self._get_headers()
                    endpoint = f"{self.base_url}{self._get_endpoint()}"

                    client = await self._get_async_client_safe()
                    response = await client.post(
                        endpoint,
                        json=request_data,
                        headers=headers,
                    )

                    return self._execute_and_parse(response, start_time, cache_key)

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        raise LLMTimeoutError(
                            f"Request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                    # Exponential backoff with jitter (R-15)
                    delay = (
                        self.retry_delay
                        * (DEFAULT_BACKOFF_FACTOR**attempt)
                        * (RETRY_JITTER_MIN + random.random())
                    )  # noqa: S311 -- jitter/backoff, not crypto
                    await asyncio.sleep(delay)

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    delay = (
                        self.retry_delay
                        * (DEFAULT_BACKOFF_FACTOR**attempt)
                        * (RETRY_JITTER_MIN + random.random())
                    )  # noqa: S311 -- jitter/backoff, not crypto
                    await asyncio.sleep(delay)

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        result: LLMResponse = await self._circuit_breaker.async_call(
            _make_async_api_call
        )
        return result


def _init_infrastructure(
    llm: BaseLLM, enable_cache: Any, cache_ttl: Any, rate_limiter: Any
) -> None:
    """Initialize clients, cache, circuit breaker, and rate limiter."""
    llm._client = None
    llm._async_client = None

    llm._closed = False
    llm._sync_cleanup_lock = threading.Lock()
    llm._async_cleanup_lock = None

    llm._cache = None
    if enable_cache:
        if CACHE_AVAILABLE and LLMCache is not None:
            llm._cache = LLMCache(backend="memory", ttl=cache_ttl)
        else:
            import warnings

            warnings.warn(
                "LLM caching requested but cache module not available. "
                "Install with: pip install src/cache",
                RuntimeWarning,
            )

    llm._circuit_breaker = _get_shared_cb(
        llm,
        BaseLLM._circuit_breakers,
        BaseLLM._circuit_breaker_lock,
        BaseLLM._MAX_CIRCUIT_BREAKERS,
    )

    llm._rate_limiter = rate_limiter
    _bind_callable_attributes(llm)
