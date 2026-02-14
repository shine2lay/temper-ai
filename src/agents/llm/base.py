"""Base LLM provider: abstract class, response types, and provider enum."""
import asyncio
import collections
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

# Optional caching support
try:
    from src.cache.llm_cache import LLMCache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    LLMCache = None  # type: ignore

from src.agents.constants import (
    DEFAULT_MAX_CIRCUIT_BREAKERS,
    DEFAULT_MAX_HTTP_CLIENTS,
)

# Helper functions extracted to reduce class size
from src.agents.llm._base_helpers import (
    LLMContextManagerMixin,
    build_bearer_auth_headers,
)
from src.agents.llm._base_helpers import (
    cache_response as _cache_response,
)
from src.agents.llm._base_helpers import (
    check_cache as _check_cache,
)
from src.agents.llm._base_helpers import (
    close_async as _close_async,
)
from src.agents.llm._base_helpers import (
    close_sync as _close_sync,
)
from src.agents.llm._base_helpers import (
    execute_and_parse as _execute_and_parse,
)
from src.agents.llm._base_helpers import (
    get_or_create_async_client_safe as _get_async_client_safe,
)
from src.agents.llm._base_helpers import (
    get_or_create_async_client_sync as _get_async_client_sync,
)
from src.agents.llm._base_helpers import (
    get_or_create_sync_client as _get_sync_client,
)
from src.agents.llm._base_helpers import (
    get_shared_circuit_breaker as _get_shared_cb,
)
from src.agents.llm._base_helpers import (
    reset_shared_circuit_breakers as _reset_shared_cbs,
)
from src.agents.llm._base_helpers import (
    reset_shared_http_clients as _reset_shared_http,
)
from src.agents.llm._base_helpers import (
    validate_base_url as _validate_base_url,
)
from src.constants.durations import SLEEP_VERY_SHORT, TIMEOUT_HTTP_DEFAULT
from src.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
    RETRY_JITTER_MIN,
)
from src.core.circuit_breaker import CircuitBreaker
from src.core.context import ExecutionContext
from src.utils.exceptions import (
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
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    # Timing
    latency_ms: Optional[int] = None

    # Metadata
    finish_reason: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


@dataclass
class LLMStreamChunk:
    """Chunk from streaming response."""
    content: str
    chunk_type: str = "content"  # "thinking" | "content"
    finish_reason: Optional[str] = None
    done: bool = False
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None      # final chunk only
    completion_tokens: Optional[int] = None  # final chunk only


# Callback type for streaming: called with each chunk as it arrives
StreamCallback = Callable[[LLMStreamChunk], None]


class BaseLLM(LLMContextManagerMixin, ABC):
    """Abstract base class for LLM providers.

    See _base_helpers.py for extracted internal logic.
    """

    _MAX_CIRCUIT_BREAKERS = DEFAULT_MAX_CIRCUIT_BREAKERS
    _circuit_breakers: collections.OrderedDict[Tuple[str, str, str], CircuitBreaker] = (
        collections.OrderedDict()
    )
    _circuit_breaker_lock = threading.Lock()

    _MAX_HTTP_CLIENTS = DEFAULT_MAX_HTTP_CLIENTS
    _http_clients: Dict[Tuple[str, str], httpx.Client] = {}
    _http_client_lock = threading.Lock()

    _async_client_lock: Optional[asyncio.Lock] = None

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = 2048,
        top_p: float = DEFAULT_TOP_P,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = 2.0,
        enable_cache: bool = False,
        cache_ttl: Optional[int] = DEFAULT_CACHE_TTL,
        rate_limiter: Optional[Any] = None,
    ):
        self.model = model
        self.base_url = _validate_base_url(base_url.rstrip('/'))
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Lazy initialization - clients created on first use
        self._client: Optional[httpx.Client] = None
        self._async_client: Optional[httpx.AsyncClient] = None

        # Cleanup coordination (prevents race conditions)
        self._closed = False
        self._sync_cleanup_lock = threading.Lock()
        self._async_cleanup_lock: Optional[asyncio.Lock] = None  # Lazy init (needs event loop)

        # Optional caching
        self._cache: Optional[LLMCache] = None
        if enable_cache:
            if CACHE_AVAILABLE and LLMCache is not None:
                self._cache = LLMCache(backend="memory", ttl=cache_ttl)
            else:
                import warnings
                warnings.warn(
                    "LLM caching requested but cache module not available. "
                    "Install with: pip install src/cache",
                    RuntimeWarning
                )

        # Circuit breaker for resilience (shared across instances for same provider+model+endpoint)
        self._circuit_breaker = _get_shared_cb(
            self, BaseLLM._circuit_breakers, BaseLLM._circuit_breaker_lock,
            BaseLLM._MAX_CIRCUIT_BREAKERS,
        )

        self._rate_limiter = rate_limiter

        # Callable attributes (not methods) to reduce class method count
        self._build_bearer_auth_headers = lambda: build_bearer_auth_headers(self)
        self._check_cache = lambda prompt, context, **kw: _check_cache(self, prompt, context, **kw)
        self._cache_response = lambda cache_key, llm_response: _cache_response(self, cache_key, llm_response)
        self._execute_and_parse = lambda response, start_time, cache_key: _execute_and_parse(self, response, start_time, cache_key)

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
        if not hasattr(self, '_closed'):
            return

        if not self._closed and (self._client is not None or self._async_client is not None):
            import warnings
            warnings.warn(
                f"{self.__class__.__name__} was not properly closed. "
                f"Use 'async with' or 'with' context manager to avoid resource leaks. "
                f"Leaked clients will be reclaimed by OS on process exit.",
                ResourceWarning,
                stacklevel=2
            )

    @abstractmethod
    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        """Build provider-specific request payload."""
        pass

    @abstractmethod
    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        """Parse provider-specific response into standardized format."""
        pass

    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """Get provider-specific HTTP headers."""
        pass

    @abstractmethod
    def _get_endpoint(self) -> str:
        """Get provider-specific API endpoint path."""
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    def _make_streaming_call_impl(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        on_chunk: Optional[StreamCallback] = None,
        **kwargs: Any
    ) -> Tuple[Optional[str], Optional[LLMResponse]]:
        """Prepare streaming call with rate limiting and cache check.

        Template method extracting duplicated logic from stream() implementations.

        Args:
            prompt: Input prompt
            context: Execution context
            on_chunk: Streaming callback
            **kwargs: Additional parameters

        Returns:
            Tuple of (cache_key, cached_response_or_none)
        """
        # Rate limiter check
        if self._rate_limiter is not None:
            entity_id = (context.agent_id if context and hasattr(context, 'agent_id') else self.model)
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                raise LLMRateLimitError(reason or "LLM rate limit exceeded")

        # Cache check
        cache_key, cached = self._check_cache(prompt, context, **kwargs)
        return cache_key, cached

    def _execute_streaming_impl(
        self,
        start_time: float,
        response: httpx.Response,
        on_chunk: StreamCallback,
        cache_key: Optional[str],
    ) -> LLMResponse:
        """Execute streaming request and handle response (synchronous).

        Template method extracting duplicated error handling and caching logic.

        Args:
            start_time: Request start timestamp
            response: HTTPx streaming response
            on_chunk: Streaming callback
            cache_key: Cache key for result

        Returns:
            LLMResponse with latency and cached result
        """
        try:
            if response.status_code != HTTP_OK:
                response.read()
                from src.agents.llm._base_helpers import handle_error_response
                handle_error_response(response)

            result = self._consume_stream(response, on_chunk)
        finally:
            response.close()

        latency_ms = int((time.time() - start_time) * 1000)
        result.latency_ms = latency_ms

        # Cache the result
        self._cache_response(cache_key, result)
        return result

    async def _execute_streaming_async_impl(
        self,
        start_time: float,
        response: httpx.Response,
        on_chunk: StreamCallback,
        cache_key: Optional[str],
    ) -> LLMResponse:
        """Execute streaming request and handle response (asynchronous).

        Template method extracting duplicated error handling and caching logic.

        Args:
            start_time: Request start timestamp
            response: HTTPx streaming response
            on_chunk: Streaming callback
            cache_key: Cache key for result

        Returns:
            LLMResponse with latency and cached result
        """
        try:
            if response.status_code != HTTP_OK:
                await response.aread()
                from src.agents.llm._base_helpers import handle_error_response
                handle_error_response(response)

            result = await self._aconsume_stream(response, on_chunk)
        finally:
            await response.aclose()

        latency_ms = int((time.time() - start_time) * 1000)
        result.latency_ms = latency_ms

        # Cache the result
        self._cache_response(cache_key, result)
        return result

    def stream(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        on_chunk: Optional[StreamCallback] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """Generate completion with streaming. Default: fallback to complete().

        Subclasses override this to provide real streaming. The default
        implementation simply calls complete() and ignores on_chunk.
        """
        return self.complete(prompt, context, **kwargs)

    async def astream(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        on_chunk: Optional[StreamCallback] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """Async streaming completion. Default: fallback to acomplete().

        Subclasses override this to provide real streaming. The default
        implementation simply calls acomplete() and ignores on_chunk.
        """
        return await self.acomplete(prompt, context, **kwargs)

    def complete(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """Generate completion for prompt."""
        if self._rate_limiter is not None:
            entity_id = (context.agent_id if context and hasattr(context, 'agent_id') else self.model)
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                raise LLMRateLimitError(reason or "LLM rate limit exceeded")

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
                        endpoint, json=request_data, headers=headers,
                    )

                    return self._execute_and_parse(response, start_time, cache_key)

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        raise LLMTimeoutError(
                            f"Request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                    # Exponential backoff with jitter (R-15) to decorrelate
                    # retries across concurrent callers.
                    delay = self.retry_delay * (DEFAULT_BACKOFF_FACTOR ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    time.sleep(delay)  # Intentional blocking: sync retry uses sleep; use acomplete() for async contexts

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    delay = self.retry_delay * (DEFAULT_BACKOFF_FACTOR ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    time.sleep(delay)  # Intentional blocking: sync rate limit backoff; use acomplete() for async contexts

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        return self._circuit_breaker.call(_make_api_call)

    async def acomplete(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """Async version: Generate completion for prompt."""
        if self._rate_limiter is not None:
            entity_id = (context.agent_id if context and hasattr(context, 'agent_id') else self.model)
            allowed, reason = self._rate_limiter.check_and_record_rate_limit(entity_id)
            if not allowed:
                raise LLMRateLimitError(reason or "LLM rate limit exceeded")

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
                        endpoint, json=request_data, headers=headers,
                    )

                    return self._execute_and_parse(response, start_time, cache_key)

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        raise LLMTimeoutError(
                            f"Request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                    # Exponential backoff with jitter (R-15)
                    delay = self.retry_delay * (DEFAULT_BACKOFF_FACTOR ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    await asyncio.sleep(delay)

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    delay = self.retry_delay * (DEFAULT_BACKOFF_FACTOR ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    await asyncio.sleep(delay)

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        result: LLMResponse = await self._circuit_breaker.async_call(_make_async_api_call)
        return result

