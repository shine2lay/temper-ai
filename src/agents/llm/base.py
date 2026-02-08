"""
Base LLM provider: abstract class, response types, and provider enum.

This module contains the core abstractions shared by all LLM providers.
"""
import asyncio
import collections
import ipaddress
import json
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any, Dict, Literal, Optional, Tuple, Type
from urllib.parse import urlparse

import httpx

# Optional caching support
try:
    from src.cache.llm_cache import LLMCache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    LLMCache = None  # type: ignore

# Import canonical execution context for cache isolation
# Import circuit breaker for resilience
from src.core.circuit_breaker import (  # M-03: Use canonical import
    CircuitBreaker,
    CircuitBreakerConfig,
)
from src.core.context import ExecutionContext

# Import enhanced exceptions
from src.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    sanitize_error_message,
)

# Module logger for connection management warnings
logger = logging.getLogger(__name__)


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
    finish_reason: Optional[str] = None
    done: bool = False


class BaseLLM(ABC):
    """
    Abstract base class for LLM providers.

    Provides unified interface for:
    - Synchronous completion
    - Streaming completion (optional)
    - Retry logic with exponential backoff
    - Error handling and status code mapping
    """

    # Shared circuit breaker instances keyed by (provider_class, model, base_url).
    # This ensures all LLM instances targeting the same endpoint share one
    # circuit breaker, so failures on one instance correctly trip the breaker
    # for all instances pointing at that endpoint.
    # Bounded via OrderedDict with LRU eviction to prevent unbounded memory growth (H-04).
    _MAX_CIRCUIT_BREAKERS = 100
    _circuit_breakers: collections.OrderedDict[Tuple[str, str, str], CircuitBreaker] = (
        collections.OrderedDict()
    )
    _circuit_breaker_lock = threading.Lock()

    # Shared HTTP client pool keyed by (provider, base_url) to reduce
    # connection overhead across instances (M-42).
    _MAX_HTTP_CLIENTS = 50
    _http_clients: Dict[Tuple[str, str], httpx.Client] = {}
    _http_client_lock = threading.Lock()

    # Async lock for async client creation (M-19).
    # Lazily initialized because asyncio.Lock() requires a running event loop
    # in some Python versions.
    _async_client_lock: Optional[asyncio.Lock] = None

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 0.9,
        timeout: int = 600,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        enable_cache: bool = False,
        cache_ttl: Optional[int] = 3600,
        rate_limiter: Optional[Any] = None,
    ):
        self.model = model
        self.base_url = self._validate_base_url(base_url.rstrip('/'))
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

        # Circuit breaker for resilience — shared across instances targeting
        # the same (provider, model, endpoint) combination.
        self._circuit_breaker = self._get_shared_circuit_breaker()

        # Rate limiter (optional, from src.security.llm_security.LLMSecurityRateLimiter)
        self._rate_limiter = rate_limiter

    def _get_shared_circuit_breaker(self) -> CircuitBreaker:
        """Get or create a shared circuit breaker for this provider+model+endpoint.

        Uses LRU eviction: oldest (least-recently-used) circuit breaker is
        removed when the pool reaches _MAX_CIRCUIT_BREAKERS (H-04).
        """
        provider_name = self.__class__.__name__.replace("LLM", "").lower()
        key = (provider_name, self.model, self.base_url)

        with BaseLLM._circuit_breaker_lock:
            if key not in BaseLLM._circuit_breakers:
                # Evict oldest entry if at capacity
                if len(BaseLLM._circuit_breakers) >= BaseLLM._MAX_CIRCUIT_BREAKERS:
                    BaseLLM._circuit_breakers.popitem(last=False)
                BaseLLM._circuit_breakers[key] = CircuitBreaker(
                    name=f"{provider_name}:{self.model}",
                    config=CircuitBreakerConfig()
                )
            else:
                # Mark as recently used
                BaseLLM._circuit_breakers.move_to_end(key)
            return BaseLLM._circuit_breakers[key]

    @classmethod
    def reset_shared_circuit_breakers(cls) -> None:
        """Reset all shared circuit breakers. Primarily useful for testing."""
        with cls._circuit_breaker_lock:
            for cb in cls._circuit_breakers.values():
                cb.reset()
            cls._circuit_breakers.clear()

    @classmethod
    def _get_shared_http_client(
        cls, provider: str, base_url: str, **kwargs: Any
    ) -> httpx.Client:
        """Get or create a shared HTTP client for this provider+base_url (M-42).

        Sharing clients across instances targeting the same endpoint reduces
        connection overhead and improves connection reuse.  Evicts oldest
        client when the pool reaches _MAX_HTTP_CLIENTS.
        """
        key = (provider, base_url)
        with cls._http_client_lock:
            if key not in cls._http_clients:
                if len(cls._http_clients) >= cls._MAX_HTTP_CLIENTS:
                    oldest_key = next(iter(cls._http_clients))
                    cls._http_clients.pop(oldest_key)  # Don't close - safer to let GC handle it
                cls._http_clients[key] = httpx.Client(**kwargs)
            return cls._http_clients[key]

    @classmethod
    def reset_shared_http_clients(cls) -> None:
        """Close and remove all shared HTTP clients. Primarily useful for testing."""
        with cls._http_client_lock:
            for client in cls._http_clients.values():
                try:
                    client.close()
                except Exception:  # noqa: BLE001 -- defensive cleanup
                    pass
            cls._http_clients.clear()

    @classmethod
    def _get_async_lock(cls) -> asyncio.Lock:
        """Get or lazily create the class-level async lock for client creation (M-19).

        asyncio.Lock() is safe to create outside an event loop in Python 3.10+,
        but we use lazy init for broader compatibility.
        """
        if cls._async_client_lock is None:
            cls._async_client_lock = asyncio.Lock()
        return cls._async_client_lock

    @staticmethod
    def _validate_base_url(url: str) -> str:
        """Validate base_url to prevent SSRF attacks (AG-01)."""
        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        allowed_local = {"localhost", "127.0.0.1", "::1"}
        if hostname in allowed_local:
            return url

        metadata_hosts = {"169.254.169.254", "metadata.google.internal"}
        if hostname in metadata_hosts:
            raise ValueError(
                f"SSRF blocked: base_url points to cloud metadata endpoint '{hostname}'"
            )

        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_link_local or addr.is_loopback or addr.is_reserved:
                raise ValueError(
                    f"SSRF blocked: base_url points to private/reserved address '{hostname}'"
                )
        except ValueError as e:
            if "SSRF blocked" in str(e):
                raise

        return url

    def _get_client(self) -> httpx.Client:
        """Get or create HTTPx client with lazy initialization and connection pooling.

        M-49: Uses shared client pool by default for better connection reuse
        across instances targeting the same endpoint.
        """
        if self._client is None:
            with self._sync_cleanup_lock:
                if self._client is None:
                    limits = httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0
                    )

                    try:
                        import h2  # type: ignore[import-not-found]  # noqa: F401
                        http2_enabled = True
                    except ImportError:
                        http2_enabled = False

                    # M-49: Use shared HTTP client by default
                    provider_name = self.__class__.__name__.replace("LLM", "").lower()
                    self._client = self._get_shared_http_client(
                        provider=provider_name,
                        base_url=self.base_url,
                        timeout=self.timeout,
                        limits=limits,
                        http2=http2_enabled
                    )
        return self._client

    async def _get_async_client_safe(self) -> httpx.AsyncClient:
        """Get or create async HTTPx client with proper async locking (M-19).

        Uses asyncio.Lock instead of threading.Lock to avoid blocking the
        event loop during client creation.
        """
        if self._async_client is None:
            async with self._get_async_lock():
                if self._async_client is None:
                    limits = httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0
                    )

                    try:
                        import h2  # noqa: F401
                        http2_enabled = True
                    except ImportError:
                        http2_enabled = False

                    self._async_client = httpx.AsyncClient(
                        timeout=self.timeout,
                        limits=limits,
                        http2=http2_enabled
                    )
        return self._async_client

    def _get_async_client(self) -> httpx.AsyncClient:
        """Get or create async HTTPx client (sync accessor, backward compat).

        For new async code, prefer _get_async_client_safe() which uses
        asyncio.Lock instead of threading.Lock (M-19).
        """
        if self._async_client is None:
            with self._sync_cleanup_lock:
                if self._async_client is None:
                    limits = httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0
                    )

                    try:
                        import h2  # noqa: F401
                        http2_enabled = True
                    except ImportError:
                        http2_enabled = False

                    self._async_client = httpx.AsyncClient(
                        timeout=self.timeout,
                        limits=limits,
                        http2=http2_enabled
                    )
        return self._async_client

    def close(self) -> None:
        """Close sync resources and release references (H-06).

        Closes the sync HTTP client directly.  For the async client, the
        reference is released but callers should use ``await aclose()``
        for proper async cleanup.  This method no longer calls
        ``asyncio.run()`` which would fail when an event loop is already
        running (e.g. inside an async framework).
        """
        with self._sync_cleanup_lock:
            if self._closed:
                return

            try:
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:  # noqa: BLE001 -- defensive cleanup
                        pass
                    self._client = None
                if self._async_client is not None:
                    # H-03: Attempt to schedule async client close on running event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # Schedule the close on the running loop
                        loop.create_task(self._async_client.aclose())
                        logger.debug("Scheduled async client close on running event loop")
                    except RuntimeError:
                        # No running loop - just log warning
                        logger.warning(
                            "close() called with active async client but no running loop; "
                            "async client not closed - use 'await aclose()' for cleanup"
                        )
                    self._async_client = None
            except Exception as e:  # noqa: BLE001 -- defensive cleanup
                logger.warning("Error during sync cleanup: %s", e)
            finally:
                self._closed = True

    async def aclose(self) -> None:
        """Async close for HTTPx clients and release resources."""
        if self._async_cleanup_lock is None:
            self._async_cleanup_lock = asyncio.Lock()

        async with self._async_cleanup_lock:
            if self._closed:
                return

            try:
                if self._client is not None:
                    self._client.close()
                if self._async_client is not None:
                    await self._async_client.aclose()
            except Exception as e:  # noqa: BLE001 -- defensive cleanup
                logger.error(f"Error during async cleanup: {e}", exc_info=True)
            finally:
                self._client = None
                self._async_client = None
                self._closed = True

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

    def __enter__(self) -> "BaseLLM":
        return self

    def __exit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc_val: Optional[BaseException],
        _exc_tb: Optional[TracebackType]
    ) -> Literal[False]:
        self.close()
        return False

    async def __aenter__(self) -> "BaseLLM":
        return self

    async def __aexit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc_val: Optional[BaseException],
        _exc_tb: Optional[TracebackType]
    ) -> Literal[False]:
        await self.aclose()
        return False

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

    def _check_cache(
        self,
        prompt: str,
        context: Optional[ExecutionContext],
        **kwargs: Any,
    ) -> Tuple[Optional[str], Optional[LLMResponse]]:
        """Check cache for a cached response."""
        if self._cache is None:
            return None, None

        user_id = context.user_id if context else None
        tenant_id = context.metadata.get('tenant_id') if context and context.metadata else None
        session_id = context.session_id if context else None

        _extracted_keys = {'temperature', 'max_tokens', 'top_p', 'system_prompt', 'tools'}
        _remaining_kwargs = {k: v for k, v in kwargs.items() if k not in _extracted_keys}
        cache_key = self._cache.generate_key(
            model=self.model,
            prompt=prompt,
            temperature=kwargs.get('temperature', self.temperature),
            max_tokens=kwargs.get('max_tokens', self.max_tokens),
            top_p=kwargs.get('top_p', self.top_p),
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            system_prompt=kwargs.get('system_prompt'),
            tools=kwargs.get('tools'),
            **_remaining_kwargs
        )

        cached_response = self._cache.get(cache_key)
        if cached_response:
            try:
                cached_data = json.loads(cached_response)
                return cache_key, LLMResponse(**cached_data)
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Corrupted cache entry for key {cache_key}: {e}")

        return cache_key, None

    def _cache_response(self, cache_key: Optional[str], llm_response: LLMResponse) -> None:
        """Store a response in cache if caching is enabled."""
        if self._cache is not None and cache_key is not None:
            cache_data = {
                'content': llm_response.content,
                'model': llm_response.model,
                'provider': llm_response.provider,
                'prompt_tokens': llm_response.prompt_tokens,
                'completion_tokens': llm_response.completion_tokens,
                'total_tokens': llm_response.total_tokens,
                'latency_ms': llm_response.latency_ms,
                'finish_reason': llm_response.finish_reason,
            }
            self._cache.set(cache_key, json.dumps(cache_data))

    def _execute_and_parse(
        self,
        response: httpx.Response,
        start_time: float,
        cache_key: Optional[str],
    ) -> LLMResponse:
        """Handle response, parse, and cache. Shared by sync/async paths."""
        latency_ms = int((time.time() - start_time) * 1000)

        if response.status_code != 200:
            self._handle_error_response(response)

        response_data = response.json()
        llm_response = self._parse_response(response_data, latency_ms)
        self._cache_response(cache_key, llm_response)
        return llm_response

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
                    delay = self.retry_delay * (2 ** attempt) * (0.5 + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    time.sleep(delay)

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    delay = self.retry_delay * (2 ** attempt) * (0.5 + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    time.sleep(delay)

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
                    delay = self.retry_delay * (2 ** attempt) * (0.5 + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    await asyncio.sleep(delay)

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    delay = self.retry_delay * (2 ** attempt) * (0.5 + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    await asyncio.sleep(delay)

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        return await self._circuit_breaker.async_call(_make_async_api_call)

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle HTTP error responses."""
        safe_text = sanitize_error_message(response.text[:500])
        if response.status_code == 401:
            raise LLMAuthenticationError(f"Authentication failed: {safe_text}")
        elif response.status_code == 429:
            raise LLMRateLimitError(f"Rate limited: {safe_text}")
        elif response.status_code >= 500:
            raise LLMError(f"Server error ({response.status_code}): {safe_text}")
        else:
            raise LLMError(f"Request failed ({response.status_code}): {safe_text}")
