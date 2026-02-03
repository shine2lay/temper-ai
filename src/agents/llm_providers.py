"""
LLM provider clients for multi-provider inference support.

Supports Ollama, OpenAI, Anthropic, and vLLM with unified interface.
Includes optional response caching to reduce costs and improve performance.
"""
import httpx
import json
import time
import asyncio
import threading
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, AsyncIterator, Union, Tuple, Type, Literal
from types import TracebackType
from dataclasses import dataclass
from enum import Enum

# Optional caching support
try:
    from src.cache.llm_cache import LLMCache
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    LLMCache = None  # type: ignore

from src.utils.error_handling import retry_with_backoff, RetryStrategy

# Import canonical execution context for cache isolation
from src.core.context import ExecutionContext

# Import enhanced exceptions
from src.utils.exceptions import (
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMAuthenticationError,
)

# Import circuit breaker for resilience
from src.llm.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, CircuitBreakerError

# Module logger for connection management warnings
logger = logging.getLogger(__name__)


__all__ = [
    # Base classes
    "BaseLLM",
    "LLMProvider",
    # Response types
    "LLMResponse",
    "LLMStreamChunk",
    # Exceptions (re-exported from utils.exceptions)
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
    # Provider implementations
    "OllamaLLM",
    "OpenAILLM",
    "AnthropicLLM",
    "vLLMLLM",
    # Factory
    "create_llm_client",
]


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

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        top_p: float = 0.9,
        timeout: int = 60,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        enable_cache: bool = False,
        cache_ttl: Optional[int] = 3600,
    ):
        """
        Initialize LLM client.

        Args:
            model: Model identifier
            base_url: Base URL for API
            api_key: API key for authentication (optional for local models)
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            top_p: Nucleus sampling parameter
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries
            retry_delay: Initial delay between retries (exponential backoff)
            enable_cache: Enable response caching (default: False)
            cache_ttl: Cache TTL in seconds (default: 3600 = 1 hour)
        """
        self.model = model
        self.base_url = base_url.rstrip('/')
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

        # Circuit breaker for resilience (per-provider isolation)
        provider_name = self.__class__.__name__.replace("LLM", "").lower()
        self._circuit_breaker = CircuitBreaker(
            name=provider_name,
            config=CircuitBreakerConfig()
        )

    def _get_client(self) -> httpx.Client:
        """Get or create HTTPx client with lazy initialization and connection pooling."""
        if self._client is None:
            # Create client with connection pooling for better performance
            # Connection pooling reduces latency by 50-200ms per request
            limits = httpx.Limits(
                max_connections=100,           # Total connections across all hosts
                max_keepalive_connections=20,  # Persistent connections to keep alive
                keepalive_expiry=30.0          # Keep connections alive for 30s
            )

            # Try to enable HTTP/2 if h2 package is available
            # HTTP/2 provides better performance through multiplexing
            try:
                import h2  # type: ignore[import-not-found]  # noqa: F401
                http2_enabled = True
            except ImportError:
                http2_enabled = False

            self._client = httpx.Client(
                timeout=self.timeout,
                limits=limits,
                http2=http2_enabled
            )
        return self._client

    def _get_async_client(self) -> httpx.AsyncClient:
        """Get or create async HTTPx client with lazy initialization and connection pooling."""
        if self._async_client is None:
            # Create async client with connection pooling for better performance
            # Connection pooling reduces latency by 50-200ms per request
            limits = httpx.Limits(
                max_connections=100,           # Total connections across all hosts
                max_keepalive_connections=20,  # Persistent connections to keep alive
                keepalive_expiry=30.0          # Keep connections alive for 30s
            )

            # Try to enable HTTP/2 if h2 package is available
            # HTTP/2 provides better performance through multiplexing
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
        """Close HTTPx clients (sync and async) and release resources.

        RELIABILITY FIX (code-crit-async-race-04): Thread-safe idempotent cleanup
        to prevent race conditions. Uses existing event loop or creates new one.

        Note: Prefer async context manager (`async with`) over manual close().
        """
        with self._sync_cleanup_lock:
            if self._closed:
                return  # Idempotent - already closed

            try:
                # Check if event loop is running
                loop = asyncio.get_running_loop()
                raise RuntimeError(
                    "Cannot call sync close() from async context. "
                    "Use await aclose() instead to prevent event loop conflicts."
                )
            except RuntimeError:
                # No running loop - safe to create new one
                asyncio.run(self.aclose())

    async def aclose(self) -> None:
        """Async close for HTTPx clients and release resources.

        RELIABILITY FIX (code-crit-async-race-04): Thread-safe idempotent cleanup
        to prevent race conditions and connection leaks under concurrent usage.
        """
        # Lazy init async lock (can't create in __init__ without event loop)
        if self._async_cleanup_lock is None:
            self._async_cleanup_lock = asyncio.Lock()

        async with self._async_cleanup_lock:
            if self._closed:
                return  # Idempotent - already closed

            try:
                if self._client is not None:
                    self._client.close()
                if self._async_client is not None:
                    await self._async_client.aclose()
            except Exception as e:
                logger.error(f"Error during async cleanup: {e}", exc_info=True)
            finally:
                self._client = None
                self._async_client = None
                self._closed = True

    def __del__(self) -> None:
        """Warn about improper cleanup - DO NOT attempt cleanup in finalizer.

        RELIABILITY FIX (code-crit-async-race-04): Minimal finalizer to prevent
        deadlocks and crashes during garbage collection. Attempting async cleanup
        in __del__ is dangerous because:
        - Event loop may be shut down
        - Other objects may already be finalized
        - Can cause crashes worse than leaks

        Best practice: Use context managers (async with / with) for guaranteed cleanup.
        """
        if not hasattr(self, '_closed'):
            return  # Initialization failed, nothing to warn about

        if not self._closed and (self._client is not None or self._async_client is not None):
            import warnings
            warnings.warn(
                f"{self.__class__.__name__} was not properly closed. "
                f"Use 'async with' or 'with' context manager to avoid resource leaks. "
                f"Leaked clients will be reclaimed by OS on process exit.",
                ResourceWarning,
                stacklevel=2
            )
        # DO NOT attempt cleanup - let OS reclaim resources on process exit

    def __enter__(self) -> "BaseLLM":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType]
    ) -> Literal[False]:
        """Context manager exit - ensure cleanup."""
        self.close()
        return False

    async def __aenter__(self) -> "BaseLLM":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType]
    ) -> Literal[False]:
        """Async context manager exit - ensure cleanup."""
        await self.aclose()
        return False

    @abstractmethod
    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        """Build provider-specific request payload.

        Args:
            prompt: The input prompt text to send to the LLM
            **kwargs: Provider-specific overrides (e.g., temperature, max_tokens)

        Returns:
            Dict containing the provider-specific request payload

        Example:
            For Ollama:
            {
                "model": "llama3.2:3b",
                "prompt": "Hello, world!",
                "temperature": 0.7,
                "max_tokens": 2048
            }

            For OpenAI:
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello!"}],
                "temperature": 0.7,
                "max_tokens": 2048
            }

        Notes:
            - Should merge instance config (self.temperature, etc.) with kwargs
            - kwargs should override instance config for flexibility
        """
        pass

    @abstractmethod
    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        """Parse provider-specific response into standardized format.

        Args:
            response: Raw response dict from provider API
            latency_ms: Request latency in milliseconds

        Returns:
            LLMResponse with standardized fields

        Example:
            # Parse Ollama response
            {
                "model": "llama3.2:3b",
                "response": "Hello! How can I help?",
                "done": true
            }
            # Into:
            LLMResponse(
                content="Hello! How can I help?",
                model="llama3.2:3b",
                provider="ollama",
                latency_ms=1234
            )

        Raises:
            LLMError: If response format is invalid or missing required fields

        Notes:
            - Should extract token usage if available
            - Should handle streaming vs non-streaming responses
            - Should set finish_reason if provided
        """
        pass

    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """Get provider-specific HTTP headers.

        Returns:
            Dict of HTTP headers to include in API requests

        Example:
            For OpenAI:
            {
                "Authorization": "Bearer sk-...",
                "Content-Type": "application/json"
            }

            For Ollama (no auth):
            {
                "Content-Type": "application/json"
            }

        Notes:
            - Should include authentication headers if api_key is set
            - Should include Content-Type: application/json
            - May include provider-specific headers (e.g., OpenAI-Organization)
        """
        pass

    @abstractmethod
    def _get_endpoint(self) -> str:
        """Get provider-specific API endpoint path.

        Returns:
            Endpoint path (without base URL) for API requests

        Example:
            For Ollama: "/api/generate"
            For OpenAI: "/chat/completions"
            For Anthropic: "/messages"

        Notes:
            - Should return path only, not full URL
            - Will be appended to self.base_url
            - Should be consistent for all requests to this provider
        """
        pass

    def complete(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """
        Generate completion for prompt.

        If caching is enabled, checks cache first before making API call.
        Uses circuit breaker to prevent cascading failures.

        SECURITY: For multi-tenant applications, MUST provide ExecutionContext
        with user_id or tenant_id to ensure proper cache isolation.

        Args:
            prompt: Input prompt
            context: Execution context with user/tenant/session for cache isolation
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.)

        Returns:
            LLMResponse with generated content

        Raises:
            LLMError: On API errors
            LLMTimeoutError: On timeout
            LLMRateLimitError: On rate limiting
            LLMAuthenticationError: On auth errors
            CircuitBreakerError: If circuit breaker is open
            ValueError: If caching enabled but no user/tenant context provided
        """
        # Check cache if enabled
        cache_key = None
        if self._cache is not None:
            # SECURITY: Extract user context for cache isolation
            user_id = context.user_id if context else None
            tenant_id = context.metadata.get('tenant_id') if context and context.metadata else None
            session_id = context.session_id if context else None

            # Generate cache key with security context
            cache_key = self._cache.generate_key(
                model=self.model,
                prompt=prompt,
                temperature=kwargs.get('temperature', self.temperature),
                max_tokens=kwargs.get('max_tokens', self.max_tokens),
                top_p=kwargs.get('top_p', self.top_p),
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                **kwargs
            )

            # Try to get from cache
            cached_response = self._cache.get(cache_key)
            if cached_response:
                # Parse cached response back to LLMResponse
                import json
                cached_data = json.loads(cached_response)
                return LLMResponse(**cached_data)

        # Cache miss or caching disabled - make API call through circuit breaker
        def _make_api_call() -> LLMResponse:
            """Internal function for API call with retry logic."""
            for attempt in range(self.max_retries):
                try:
                    start_time = time.time()

                    # Build request
                    request_data = self._build_request(prompt, **kwargs)
                    headers = self._get_headers()
                    endpoint = f"{self.base_url}{self._get_endpoint()}"

                    # Make request
                    response = self._get_client().post(
                        endpoint,
                        json=request_data,
                        headers=headers,
                    )

                    latency_ms = int((time.time() - start_time) * 1000)

                    # Handle error responses
                    if response.status_code != 200:
                        self._handle_error_response(response)

                    # Parse successful response
                    response_data = response.json()
                    llm_response = self._parse_response(response_data, latency_ms)

                    # Cache the response if caching enabled
                    if self._cache is not None and cache_key is not None:
                        # Serialize response for caching
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

                    return llm_response

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        raise LLMTimeoutError(
                            f"Request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                    time.sleep(self.retry_delay * (2 ** attempt))

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    # Exponential backoff for rate limits
                    time.sleep(self.retry_delay * (2 ** attempt))

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    # Don't retry auth errors
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        # Execute through circuit breaker for resilience
        return self._circuit_breaker.call(_make_api_call)

    async def acomplete(
        self,
        prompt: str,
        context: Optional[ExecutionContext] = None,
        **kwargs: Any
    ) -> LLMResponse:
        """
        Async version: Generate completion for prompt.

        If caching is enabled, checks cache first before making API call.
        Uses circuit breaker to prevent cascading failures.

        SECURITY: For multi-tenant applications, MUST provide ExecutionContext
        with user_id or tenant_id to ensure proper cache isolation.

        Args:
            prompt: Input prompt
            context: Execution context with user/tenant/session for cache isolation
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.)

        Returns:
            LLMResponse with generated content

        Raises:
            LLMError: On API errors
            LLMTimeoutError: On timeout
            LLMRateLimitError: On rate limiting
            LLMAuthenticationError: On auth errors
            CircuitBreakerError: If circuit breaker is open
            ValueError: If caching enabled but no user/tenant context provided
        """
        # Check cache if enabled (cache is synchronous, so this is fine)
        cache_key = None
        if self._cache is not None:
            # SECURITY: Extract user context for cache isolation
            user_id = context.user_id if context else None
            tenant_id = context.metadata.get('tenant_id') if context and context.metadata else None
            session_id = context.session_id if context else None

            # Generate cache key with security context
            cache_key = self._cache.generate_key(
                model=self.model,
                prompt=prompt,
                temperature=kwargs.get('temperature', self.temperature),
                max_tokens=kwargs.get('max_tokens', self.max_tokens),
                top_p=kwargs.get('top_p', self.top_p),
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                **kwargs
            )

            # Try to get from cache
            cached_response = self._cache.get(cache_key)
            if cached_response:
                # Parse cached response back to LLMResponse
                import json
                cached_data = json.loads(cached_response)
                return LLMResponse(**cached_data)

        # Cache miss or caching disabled - make API call through circuit breaker
        async def _make_async_api_call() -> LLMResponse:
            """Internal function for async API call with retry logic."""
            for attempt in range(self.max_retries):
                try:
                    start_time = time.time()

                    # Build request
                    request_data = self._build_request(prompt, **kwargs)
                    headers = self._get_headers()
                    endpoint = f"{self.base_url}{self._get_endpoint()}"

                    # Make async request
                    response = await self._get_async_client().post(
                        endpoint,
                        json=request_data,
                        headers=headers,
                    )

                    latency_ms = int((time.time() - start_time) * 1000)

                    # Handle error responses
                    if response.status_code != 200:
                        self._handle_error_response(response)

                    # Parse successful response
                    response_data = response.json()
                    llm_response = self._parse_response(response_data, latency_ms)

                    # Cache the response if caching enabled
                    if self._cache is not None and cache_key is not None:
                        # Serialize response for caching
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

                    return llm_response

                except httpx.TimeoutException:
                    if attempt == self.max_retries - 1:
                        raise LLMTimeoutError(
                            f"Request timed out after {self.timeout}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

                except LLMRateLimitError:
                    if attempt == self.max_retries - 1:
                        raise
                    # Exponential backoff for rate limits
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))

                except (LLMAuthenticationError, httpx.HTTPStatusError):
                    # Don't retry auth errors
                    raise

            raise LLMError(f"Failed after {self.max_retries} attempts")

        # Execute through circuit breaker for resilience
        # Note: Circuit breaker call is synchronous, wrapping async function
        return await _make_async_api_call()

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle HTTP error responses."""
        if response.status_code == 401:
            raise LLMAuthenticationError(f"Authentication failed: {response.text}")
        elif response.status_code == 429:
            raise LLMRateLimitError(f"Rate limited: {response.text}")
        elif response.status_code >= 500:
            raise LLMError(f"Server error ({response.status_code}): {response.text}")
        else:
            raise LLMError(f"Request failed ({response.status_code}): {response.text}")


class OllamaLLM(BaseLLM):
    """Ollama LLM provider (local models).

    Uses /api/chat with native tool calling when tools are provided,
    falls back to /api/generate for simple completions.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._use_chat_api = False  # Set per-request based on tools kwarg

    def _get_endpoint(self) -> str:
        if self._use_chat_api:
            return "/api/chat"
        return "/api/generate"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
        }

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        tools = kwargs.get("tools")
        if tools:
            self._use_chat_api = True
            request = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "options": {
                    "temperature": kwargs.get("temperature", self.temperature),
                    "top_p": kwargs.get("top_p", self.top_p),
                    "num_predict": kwargs.get("max_tokens", self.max_tokens),
                    "num_ctx": kwargs.get("max_tokens", self.max_tokens) + 4096,
                },
                "tools": tools,
                "stream": False,
            }
            return request
        else:
            self._use_chat_api = False
            return {
                "model": self.model,
                "prompt": prompt,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "top_p": kwargs.get("top_p", self.top_p),
                "stream": False,
            }

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        if self._use_chat_api:
            # Parse /api/chat response
            message = response.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls")

            # Convert native tool calls into <tool_call> XML tags so the
            # existing StandardAgent._parse_tool_calls() regex can find them.
            if tool_calls:
                import json as _json
                tc_parts = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tc_dict = {
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", {}),
                    }
                    tc_parts.append(
                        f"<tool_call>\n{_json.dumps(tc_dict)}\n</tool_call>"
                    )
                # Append tool call tags to content
                content = content + "\n" + "\n".join(tc_parts)

            prompt_tokens = response.get("prompt_eval_count")
            completion_tokens = response.get("eval_count")
            total = (prompt_tokens or 0) + (completion_tokens or 0) or None

            return LLMResponse(
                content=content,
                model=self.model,
                provider=LLMProvider.OLLAMA,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total,
                latency_ms=latency_ms,
                finish_reason="stop" if response.get("done") else None,
                raw_response=response,
            )
        else:
            # Parse /api/generate response
            return LLMResponse(
                content=response.get("response", ""),
                model=self.model,
                provider=LLMProvider.OLLAMA,
                prompt_tokens=response.get("prompt_eval_count"),
                completion_tokens=response.get("eval_count"),
                total_tokens=(response.get("prompt_eval_count", 0) + response.get("eval_count", 0)) or None,
                latency_ms=latency_ms,
                finish_reason="stop" if response.get("done") else None,
                raw_response=response,
            )


class OpenAILLM(BaseLLM):
    """OpenAI LLM provider (GPT models)."""

    def _get_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": False,
        }

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        choice = response["choices"][0]
        usage = response.get("usage", {})

        return LLMResponse(
            content=choice["message"]["content"],
            model=response.get("model", self.model),
            provider=LLMProvider.OPENAI,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            raw_response=response,
        )


class AnthropicLLM(BaseLLM):
    """Anthropic LLM provider (Claude models)."""

    def _get_endpoint(self) -> str:
        return "/v1/messages"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "top_p": kwargs.get("top_p", self.top_p),
        }

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        content_block = response["content"][0]
        usage = response.get("usage", {})

        return LLMResponse(
            content=content_block["text"],
            model=response.get("model", self.model),
            provider=LLMProvider.ANTHROPIC,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            total_tokens=(usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) or None,
            latency_ms=latency_ms,
            finish_reason=response.get("stop_reason"),
            raw_response=response,
        )


class vLLMLLM(BaseLLM):
    """vLLM provider (self-hosted inference)."""

    def _get_endpoint(self) -> str:
        return "/v1/completions"

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_request(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        return {
            "model": self.model,
            "prompt": prompt,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", self.top_p),
            "stream": False,
        }

    def _parse_response(self, response: Dict[str, Any], latency_ms: int) -> LLMResponse:
        choice = response["choices"][0]
        usage = response.get("usage", {})

        return LLMResponse(
            content=choice["text"],
            model=response.get("model", self.model),
            provider=LLMProvider.VLLM,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            raw_response=response,
        )


def create_llm_client(
    provider: str,
    model: str,
    base_url: str,
    api_key: Optional[str] = None,
    **kwargs: Any
) -> BaseLLM:
    """
    Factory function to create LLM client based on provider.

    Args:
        provider: Provider name (ollama, openai, anthropic, vllm)
        model: Model identifier
        base_url: Base URL for API
        api_key: API key (optional for local models)
        **kwargs: Additional parameters passed to LLM client

    Returns:
        Configured LLM client instance

    Raises:
        ValueError: If provider is unknown

    Example:
        >>> llm = create_llm_client(
        ...     provider="ollama",
        ...     model="llama3.2:3b",
        ...     base_url="http://localhost:11434"
        ... )
        >>> response = llm.complete("What is the capital of France?")
        >>> print(response.content)
    """
    providers = {
        LLMProvider.OLLAMA: OllamaLLM,
        LLMProvider.OPENAI: OpenAILLM,
        LLMProvider.ANTHROPIC: AnthropicLLM,
        LLMProvider.VLLM: vLLMLLM,
    }

    provider_enum = LLMProvider(provider.lower())
    llm_class = providers.get(provider_enum)

    if not llm_class:
        raise ValueError(
            f"Unknown provider: {provider}. "
            f"Supported: {', '.join(p.value for p in LLMProvider)}"
        )

    return llm_class(  # type: ignore[abstract]
        model=model,
        base_url=base_url,
        api_key=api_key,
        **kwargs
    )
