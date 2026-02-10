"""Helper functions extracted from BaseLLM to reduce class size.

These are internal implementation details and should not be imported directly.
"""
from __future__ import annotations

import asyncio
import collections
import ipaddress
import json
import logging
import threading
import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Tuple, Type, cast
from urllib.parse import urlparse

import httpx

from src.agents.constants import (
    DEFAULT_KEEPALIVE_EXPIRY_SECONDS,
    DEFAULT_MAX_HTTP_CONNECTIONS,
    DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
    MAX_ERROR_MESSAGE_LENGTH,
)
from src.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from src.utils.exceptions import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    sanitize_error_message,
)

if TYPE_CHECKING:
    from src.agents.llm.base import BaseLLM, LLMResponse
    from src.core.context import ExecutionContext

logger = logging.getLogger(__name__)

# HTTP status codes
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_RATE_LIMIT = 429
HTTP_SERVER_ERROR = 500


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_base_url(url: str) -> str:
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


# ---------------------------------------------------------------------------
# Circuit breaker management
# ---------------------------------------------------------------------------

def get_shared_circuit_breaker(
    instance: BaseLLM,
    circuit_breakers: collections.OrderedDict[Tuple[str, str, str], CircuitBreaker],
    lock: threading.Lock,
    max_breakers: int,
) -> CircuitBreaker:
    """Get or create a shared circuit breaker for this provider+model+endpoint."""
    provider_name = instance.__class__.__name__.replace("LLM", "").lower()
    key = (provider_name, instance.model, instance.base_url)

    with lock:
        if key not in circuit_breakers:
            if len(circuit_breakers) >= max_breakers:
                circuit_breakers.popitem(last=False)
            circuit_breakers[key] = CircuitBreaker(
                name=f"{provider_name}:{instance.model}",
                config=CircuitBreakerConfig()
            )
        else:
            circuit_breakers.move_to_end(key)
        return circuit_breakers[key]


def reset_shared_circuit_breakers(
    circuit_breakers: collections.OrderedDict,
    lock: threading.Lock,
) -> None:
    """Reset all shared circuit breakers."""
    with lock:
        for cb in circuit_breakers.values():
            cb.reset()
        circuit_breakers.clear()


# ---------------------------------------------------------------------------
# HTTP client management
# ---------------------------------------------------------------------------

def get_shared_http_client(
    clients: Dict[Tuple[str, str], httpx.Client],
    lock: threading.Lock,
    max_clients: int,
    provider: str,
    base_url: str,
    **kwargs: Any,
) -> httpx.Client:
    """Get or create a shared HTTP client for this provider+base_url (M-42)."""
    key = (provider, base_url)
    with lock:
        if key not in clients:
            if len(clients) >= max_clients:
                oldest_key = next(iter(clients))
                clients.pop(oldest_key)
            clients[key] = httpx.Client(**kwargs)
        return clients[key]


def reset_shared_http_clients(
    clients: Dict[Tuple[str, str], httpx.Client],
    lock: threading.Lock,
) -> None:
    """Close and remove all shared HTTP clients."""
    with lock:
        for client in clients.values():
            try:
                client.close()
            except (OSError, RuntimeError) as e:
                logger.debug(f"Error closing HTTP client during cleanup: {e}")
        clients.clear()


def get_or_create_sync_client(instance: BaseLLM) -> httpx.Client:
    """Get or create HTTPx client with lazy initialization and connection pooling."""
    if instance._client is None:
        with instance._sync_cleanup_lock:
            if instance._client is None:
                limits = httpx.Limits(
                    max_connections=DEFAULT_MAX_HTTP_CONNECTIONS,
                    max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                    keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY_SECONDS
                )

                try:
                    import h2  # type: ignore[import-not-found]  # noqa: F401
                    http2_enabled = True
                except ImportError:
                    http2_enabled = False

                provider_name = instance.__class__.__name__.replace("LLM", "").lower()
                from src.agents.llm.base import BaseLLM as _BaseLLM
                # Create explicit timeout object to ensure all timeout types are set
                timeout_config = httpx.Timeout(timeout=instance.timeout, connect=30.0)
                instance._client = get_shared_http_client(
                    _BaseLLM._http_clients,
                    _BaseLLM._http_client_lock,
                    _BaseLLM._MAX_HTTP_CLIENTS,
                    provider=provider_name,
                    base_url=instance.base_url,
                    timeout=timeout_config,
                    limits=limits,
                    http2=http2_enabled
                )
    return instance._client


async def get_or_create_async_client_safe(instance: BaseLLM) -> httpx.AsyncClient:
    """Get or create async HTTPx client with proper async locking (M-19)."""
    if instance._async_client is None:
        from src.agents.llm.base import BaseLLM as _BaseLLM
        async with get_async_lock(_BaseLLM):
            if instance._async_client is None:
                limits = httpx.Limits(
                    max_connections=DEFAULT_MAX_HTTP_CONNECTIONS,
                    max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                    keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY_SECONDS
                )

                try:
                    import h2  # noqa: F401
                    http2_enabled = True
                except ImportError:
                    http2_enabled = False

                # Create explicit timeout object to ensure all timeout types are set
                timeout_config = httpx.Timeout(timeout=instance.timeout, connect=30.0)
                instance._async_client = httpx.AsyncClient(
                    timeout=timeout_config,
                    limits=limits,
                    http2=http2_enabled
                )
    return instance._async_client


def get_or_create_async_client_sync(instance: BaseLLM) -> httpx.AsyncClient:
    """Get or create async HTTPx client (sync accessor, backward compat)."""
    if instance._async_client is None:
        with instance._sync_cleanup_lock:
            if instance._async_client is None:
                limits = httpx.Limits(
                    max_connections=DEFAULT_MAX_HTTP_CONNECTIONS,
                    max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                    keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY_SECONDS
                )

                try:
                    import h2  # noqa: F401
                    http2_enabled = True
                except ImportError:
                    http2_enabled = False

                # Create explicit timeout object to ensure all timeout types are set
                timeout_config = httpx.Timeout(timeout=instance.timeout, connect=30.0)
                instance._async_client = httpx.AsyncClient(
                    timeout=timeout_config,
                    limits=limits,
                    http2=http2_enabled
                )
    return instance._async_client


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def check_cache(
    instance: BaseLLM,
    prompt: str,
    context: Optional[ExecutionContext],
    **kwargs: Any,
) -> Tuple[Optional[str], Optional[LLMResponse]]:
    """Check cache for a cached response."""
    from src.agents.llm.base import LLMResponse as _LLMResponse

    if instance._cache is None:
        return None, None

    user_id = context.user_id if context else None
    tenant_id = context.metadata.get('tenant_id') if context and context.metadata else None
    session_id = context.session_id if context else None

    _extracted_keys = {'temperature', 'max_tokens', 'top_p', 'system_prompt', 'tools'}
    _remaining_kwargs = {k: v for k, v in kwargs.items() if k not in _extracted_keys}
    cache_key = instance._cache.generate_key(
        model=instance.model,
        prompt=prompt,
        temperature=kwargs.get('temperature', instance.temperature),
        max_tokens=kwargs.get('max_tokens', instance.max_tokens),
        top_p=kwargs.get('top_p', instance.top_p),
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        system_prompt=kwargs.get('system_prompt'),
        tools=kwargs.get('tools'),
        **_remaining_kwargs
    )

    cached_response = instance._cache.get(cache_key)
    if cached_response:
        try:
            cached_data = json.loads(cached_response)
            return cache_key, _LLMResponse(**cached_data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"Corrupted cache entry for key {cache_key}: {e}")

    return cache_key, None


def cache_response(instance: BaseLLM, cache_key: Optional[str], llm_response: LLMResponse) -> None:
    """Store a response in cache if caching is enabled."""
    if instance._cache is not None and cache_key is not None:
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
        instance._cache.set(cache_key, json.dumps(cache_data))


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------

def execute_and_parse(
    instance: BaseLLM,
    response: httpx.Response,
    start_time: float,
    cache_key: Optional[str],
) -> LLMResponse:
    """Handle response, parse, and cache. Shared by sync/async paths."""
    latency_ms = int((time.time() - start_time) * 1000)

    if response.status_code != HTTP_OK:
        handle_error_response(response)

    response_data = response.json()
    llm_response = instance._parse_response(response_data, latency_ms)
    cache_response(instance, cache_key, llm_response)
    return llm_response


def handle_error_response(response: httpx.Response) -> None:
    """Handle HTTP error responses."""
    safe_text = sanitize_error_message(response.text[:MAX_ERROR_MESSAGE_LENGTH])
    if response.status_code == HTTP_UNAUTHORIZED:
        raise LLMAuthenticationError(f"Authentication failed: {safe_text}")
    elif response.status_code == HTTP_RATE_LIMIT:
        raise LLMRateLimitError(f"Rate limited: {safe_text}")
    elif response.status_code >= HTTP_SERVER_ERROR:
        raise LLMError(f"Server error ({response.status_code}): {safe_text}")
    else:
        raise LLMError(f"Request failed ({response.status_code}): {safe_text}")


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

def close_sync(instance: BaseLLM) -> None:
    """Close sync resources and release references (H-06)."""
    with instance._sync_cleanup_lock:
        if instance._closed:
            return

        try:
            if instance._client is not None:
                try:
                    instance._client.close()
                except (OSError, RuntimeError) as e:
                    logger.debug(f"Error closing sync client: {e}")
                instance._client = None
            if instance._async_client is not None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(instance._async_client.aclose())
                    logger.debug("Scheduled async client close on running event loop")
                except RuntimeError:
                    logger.warning(
                        "close() called with active async client but no running loop; "
                        "async client not closed - use 'await aclose()' for cleanup"
                    )
                instance._async_client = None
        except (OSError, RuntimeError) as e:
            logger.warning("Error during sync cleanup: %s", e)
        finally:
            instance._closed = True


async def close_async(instance: BaseLLM) -> None:
    """Async close for HTTPx clients and release resources."""
    if instance._async_cleanup_lock is None:
        instance._async_cleanup_lock = asyncio.Lock()

    async with instance._async_cleanup_lock:
        if instance._closed:
            return

        try:
            if instance._client is not None:
                instance._client.close()
            if instance._async_client is not None:
                await instance._async_client.aclose()
        except (OSError, RuntimeError) as e:
            logger.error(f"Error during async cleanup: {e}", exc_info=True)
        finally:
            instance._client = None
            instance._async_client = None
            instance._closed = True


# ---------------------------------------------------------------------------
# Bearer auth helper
# ---------------------------------------------------------------------------

def build_bearer_auth_headers(instance: BaseLLM) -> Dict[str, str]:
    """Build standard headers with Bearer token authentication."""
    headers = {"Content-Type": "application/json"}
    if instance.api_key:
        headers["Authorization"] = f"Bearer {instance.api_key}"
    return headers


# ---------------------------------------------------------------------------
# Async lock helper
# ---------------------------------------------------------------------------

def get_async_lock(cls: Any) -> asyncio.Lock:
    """Get or lazily create the class-level async lock."""
    if cls._async_client_lock is None:
        cls._async_client_lock = asyncio.Lock()
    return cast(asyncio.Lock, cls._async_client_lock)


# ---------------------------------------------------------------------------
# Context manager mixin
# ---------------------------------------------------------------------------

class LLMContextManagerMixin:
    """Mixin providing sync and async context manager support for LLM classes."""

    def __enter__(self) -> "LLMContextManagerMixin":
        return self

    def __exit__(self, _exc_type: Optional[Type[BaseException]], _exc_val: Optional[BaseException], _exc_tb: Optional[TracebackType]) -> Literal[False]:
        self.close()  # type: ignore[attr-defined]
        return False

    async def __aenter__(self) -> "LLMContextManagerMixin":
        return self

    async def __aexit__(self, _exc_type: Optional[Type[BaseException]], _exc_val: Optional[BaseException], _exc_tb: Optional[TracebackType]) -> Literal[False]:
        await self.aclose()  # type: ignore[attr-defined]
        return False
