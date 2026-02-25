"""
LLM response caching for cost reduction and faster development.

Provides:
- Content-based hashing for cache keys
- In-memory backend support
- TTL (time-to-live) for cache expiration
- Opt-in via configuration
- Thread-safe operations
- Cache hit/miss statistics
"""

import hashlib
import json
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any

from temper_ai.llm.cache.constants import (
    DEFAULT_CACHE_SIZE,
    DEFAULT_TTL_SECONDS,
)
from temper_ai.shared.constants.durations import TTL_LONG
from temper_ai.shared.constants.limits import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from temper_ai.shared.utils.logging import get_logger

logger = get_logger(__name__)

# Logging constants
CACHE_KEY_LOG_LENGTH = 16  # Number of characters to show in logs for cache keys


@dataclass
class CacheStats:
    """Cache statistics for monitoring."""

    hits: int = 0
    misses: int = 0
    writes: int = 0
    errors: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {**asdict(self), "hit_rate": self.hit_rate}


@dataclass
class CacheKeyParams:
    """Parameters for cache key generation.

    Bundles together the many parameters needed for cache key generation
    to reduce parameter count and improve code maintainability.
    """

    model: str
    prompt: str
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS
    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    system_prompt: str | None = None
    tools: list[dict[str, Any]] | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Get value from cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        """Set value in cache with optional TTL."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        pass

    @abstractmethod
    def clear(self, **kwargs: Any) -> None:
        """Clear entire cache."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        pass


class InMemoryCache(CacheBackend):
    """
    In-memory cache backend using Python dict.

    Features:
    - Thread-safe with locks
    - TTL support with expiration tracking
    - LRU eviction when max_size reached
    - No external dependencies
    """

    def __init__(
        self,
        max_size: int = DEFAULT_CACHE_SIZE,
        on_eviction: Any | None = None,
    ):
        """
        Initialize in-memory cache.

        Args:
            max_size: Maximum number of entries before eviction
            on_eviction: Optional callback invoked on LRU eviction
        """
        self._cache: dict[str, tuple[str, float | None]] = {}
        # PERFORMANCE FIX (code-medi-07): Use OrderedDict for O(1) LRU eviction
        # OrderedDict maintains insertion order, allowing efficient LRU tracking
        self._access_order: OrderedDict = OrderedDict()  # Track access order for LRU
        self._max_size = max_size
        self._lock = Lock()
        self._evictions = 0
        self._on_eviction = on_eviction

        logger.debug(f"InMemoryCache initialized with max_size={max_size}")

    def get(self, key: str) -> str | None:
        """Get value from cache, checking TTL."""
        with self._lock:
            if key not in self._cache:
                return None

            value, expires_at = self._cache[key]

            # Check if expired
            if expires_at is not None and time.time() > expires_at:
                # Expired - delete and return None
                del self._cache[key]
                del self._access_order[key]
                return None

            # PERFORMANCE FIX (code-medi-07): Move to end for O(1) LRU tracking
            # OrderedDict.move_to_end() is O(1), marking this as most recently used
            self._access_order.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        """Set value in cache with optional TTL."""
        with self._lock:
            # Calculate expiration time
            expires_at = time.time() + ttl if ttl else None

            # Evict if at max capacity
            if key not in self._cache and len(self._cache) >= self._max_size:
                self._evict_lru()

            self._cache[key] = (value, expires_at)
            # PERFORMANCE FIX (code-medi-07): Use OrderedDict for O(1) LRU
            # Setting/updating key in OrderedDict places it at the end (most recent)
            self._access_order[key] = True  # Value doesn't matter, only order
            # If key already exists, move it to end (most recently used)
            self._access_order.move_to_end(key)
            return True

    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                del self._access_order[key]
                return True
            return False

    def clear(self, **kwargs: Any) -> None:
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            logger.info("InMemoryCache cleared")

    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None

    def _cleanup_expired(self) -> int:
        """
        Clean up expired entries from cache and access_order.

        RELIABILITY FIX (code-high-07): Prevents memory leak where expired entries
        accumulate in _access_order dict when never accessed again.

        Returns:
            Number of expired entries removed
        """
        if not self._cache:
            return 0

        current_time = time.time()
        expired_keys = []

        # Find all expired keys
        for key, (_, expires_at) in self._cache.items():
            if expires_at is not None and current_time > expires_at:
                expired_keys.append(key)

        # Remove expired entries from both dicts
        for key in expired_keys:
            del self._cache[key]
            # CRITICAL: Also remove from _access_order to prevent memory leak
            if key in self._access_order:
                del self._access_order[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

        return len(expired_keys)

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        # RELIABILITY FIX (code-high-07): Clean up expired entries first
        # to avoid evicting valid entries when expired ones exist
        self._cleanup_expired()

        if not self._access_order:
            return

        # PERFORMANCE FIX (code-medi-07): O(1) LRU eviction with OrderedDict
        # First item in OrderedDict is least recently used (oldest)
        # This is O(1) instead of O(n) min() scan over all keys
        lru_key, _ = self._access_order.popitem(
            last=False
        )  # Remove first (oldest) item

        # Remove from cache
        del self._cache[lru_key]
        self._evictions += 1

        logger.debug(
            f"Evicted LRU entry: {lru_key} (total evictions: {self._evictions})"
        )

        if self._on_eviction is not None:
            try:
                self._on_eviction(lru_key)
            except (TypeError, RuntimeError, ValueError) as exc:
                logger.debug("Eviction callback error: %s", exc)

    def get_stats(self, cleanup_expired: bool = True) -> dict[str, Any]:
        """
        Get cache statistics.

        Args:
            cleanup_expired: If True, clean up expired entries before reporting stats

        Returns:
            Dictionary with cache statistics including size, evictions, and cleanup count
        """
        with self._lock:
            expired_cleaned = 0
            if cleanup_expired:
                # RELIABILITY FIX (code-high-07): Opportunistic cleanup during stats collection
                expired_cleaned = self._cleanup_expired()

            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "evictions": self._evictions,
                "expired_cleaned": expired_cleaned,
            }


def _extract_cache_key_kwargs(kwargs: dict[str, Any]) -> CacheKeyParams:
    """Extract CacheKeyParams from legacy kwargs dict."""
    return CacheKeyParams(
        model=kwargs.pop("model"),
        prompt=kwargs.pop("prompt"),
        temperature=kwargs.pop("temperature", DEFAULT_TEMPERATURE),
        max_tokens=kwargs.pop("max_tokens", DEFAULT_MAX_TOKENS),
        user_id=kwargs.pop("user_id", None),
        tenant_id=kwargs.pop("tenant_id", None),
        session_id=kwargs.pop("session_id", None),
        system_prompt=kwargs.pop("system_prompt", None),
        tools=kwargs.pop("tools", None),
        extra_params=kwargs,
    )


def _validate_cache_key_isolation(
    user_id: str | None,
    tenant_id: str | None,
) -> None:
    """Enforce user/tenant context to prevent cross-tenant data leakage."""
    if not user_id and not tenant_id:
        raise ValueError(
            "Cache key generation requires user_id or tenant_id for security. "
            "Multi-tenant caching without isolation is a privacy violation. "
            "See: HIPAA 164.312(a)(1), GDPR Article 32, SOC 2 CC6.6"
        )


_CACHE_KEY_TYPE_RULES: list[tuple[str, type | tuple[type, ...], bool]] = [
    # (param_name, expected_types, nullable)
    ("model", str, False),
    ("prompt", str, False),
    ("temperature", (int, float), False),
    ("max_tokens", int, False),
    ("user_id", str, True),
    ("tenant_id", str, True),
    ("session_id", str, True),
]


def _validate_cache_key_types(
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    user_id: str | None,
    tenant_id: str | None,
    session_id: str | None,
) -> None:
    """Validate parameter types to prevent type confusion attacks."""
    values = {
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
    }
    for param_name, expected, nullable in _CACHE_KEY_TYPE_RULES:
        value = values[param_name]
        if nullable and value is None:
            continue
        if not isinstance(value, expected):
            label = (
                "str or None"
                if nullable
                else expected.__name__ if isinstance(expected, type) else "numeric"
            )
            raise TypeError(f"{param_name} must be {label}, got {type(value).__name__}")


def _validate_cache_kwargs(reserved: frozenset, kwargs: dict[str, Any]) -> None:
    """Validate kwargs to prevent parameter override attacks (code-crit-15)."""
    conflicting_params = reserved.intersection(kwargs.keys())
    if conflicting_params:
        raise ValueError(
            f"Cannot override reserved parameters via kwargs: {conflicting_params}. "
            f"Reserved parameters: {reserved}. "
            f"Use explicit arguments instead of **kwargs for these parameters."
        )


def _build_security_context(
    user_id: str | None,
    tenant_id: str | None,
    session_id: str | None,
) -> dict[str, str]:
    """Build security context dict for cache key isolation."""
    ctx: dict[str, str] = {}
    if tenant_id:
        ctx["tenant_id"] = tenant_id
    if user_id:
        ctx["user_id"] = user_id
    if session_id:
        ctx["session_id"] = session_id
    return ctx


def _hash_cache_key(request: dict[str, Any], security_context: dict[str, str]) -> str:
    """Hash request + security context into a SHA-256 cache key."""
    try:
        canonical = json.dumps(
            {"request": request, "security_context": security_context},
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"Cache key generation failed: parameters must be JSON-serializable. "
            f"Error: {e}"
        ) from e
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _generate_cache_key_hash(params: CacheKeyParams) -> str:
    """Generate cache key hash from parameters.

    Args:
        params: CacheKeyParams with all cache key parameters

    Returns:
        SHA-256 hash cache key
    """
    request = {
        "model": params.model,
        "prompt": params.prompt,
        "temperature": params.temperature,
        "max_tokens": params.max_tokens,
        "system_prompt": params.system_prompt or "",
        "tools": LLMCache._normalize_tools(params.tools) if params.tools else [],
        **params.extra_params,
    }
    security_context = _build_security_context(
        params.user_id, params.tenant_id, params.session_id
    )
    return _hash_cache_key(request, security_context)


def _create_cache_backend(
    backend: str,
    max_size: int,
    eviction_cb: Any | None,
) -> "CacheBackend":
    """Create a cache backend from config."""
    if backend == "memory":
        return InMemoryCache(max_size=max_size, on_eviction=eviction_cb)
    raise ValueError(f"Unknown cache backend: {backend}. Use 'memory'.")


class LLMCache:
    """
    LLM response cache with content-based hashing.

    Caches LLM responses based on:
    - Model name
    - Prompt content
    - Generation parameters (temperature, max_tokens, etc.)

    Usage:
        >>> cache = LLMCache(backend="memory", ttl=3600)
        >>> key = cache.generate_key(model="gpt-4", prompt="Hello", temperature=0.7)
        >>> cache.set(key, "Hello! How can I help?")
        >>> cached = cache.get(key)
    """

    # SECURITY: Reserved parameter names that cannot be overridden via kwargs
    # Prevents cache poisoning via parameter injection and namespace pollution
    _RESERVED_PARAMS = frozenset(
        {
            "model",
            "prompt",
            "temperature",
            "max_tokens",
            "user_id",
            "tenant_id",
            "session_id",
            "system_prompt",
            "tools",  # Explicit parameters to prevent cache collision
            "security_context",
            "request",  # Prevent namespace pollution
        }
    )

    def __init__(
        self,
        backend: str = "memory",
        ttl: int | None = DEFAULT_TTL_SECONDS,
        max_size: int = DEFAULT_CACHE_SIZE,
        on_event: Any | None = None,
    ):
        """
        Initialize LLM cache.

        Args:
            backend: Cache backend ("memory")
            ttl: Time-to-live in seconds (None = no expiration)
            max_size: Max entries for in-memory cache
            on_event: Optional callback for cache events (hit/miss/write/eviction)

        Raises:
            ValueError: If backend is unknown
        """
        self.ttl = ttl
        self.stats = CacheStats()
        self._stats_lock = Lock()
        self._on_event = on_event

        # Create backend
        eviction_cb = self._make_eviction_callback() if on_event else None
        self._backend = _create_cache_backend(
            backend,
            max_size,
            eviction_cb,
        )

        logger.info(f"LLMCache initialized with backend={backend}, ttl={ttl}s")

    def _fire_cache_event(self, event_type: str, key: str) -> None:
        """Fire a cache event to the on_event callback if set."""
        if self._on_event is None:
            return
        from temper_ai.llm.llm_loop_events import CacheEventData, emit_cache_event

        prefix = key[:CACHE_KEY_LOG_LENGTH] if key else ""
        size = None
        if isinstance(self._backend, InMemoryCache):
            size = len(self._backend._cache)
        emit_cache_event(
            self._on_event,
            CacheEventData(
                event_type=event_type,
                key_prefix=prefix,
                cache_size=size,
            ),
        )

    def _make_eviction_callback(self) -> Any:
        """Create a callback for InMemoryCache eviction events."""

        def _on_eviction(evicted_key: str) -> None:
            self._fire_cache_event("eviction", evicted_key)

        return _on_eviction

    def generate_key(self, params: CacheKeyParams | None = None, **kwargs: Any) -> str:
        """Generate cache key with mandatory user/tenant isolation.

        Args:
            params: CacheKeyParams bundle (recommended)
            **kwargs: Legacy individual parameters (model, prompt, etc.)

        SECURITY: Requires user_id OR tenant_id to prevent cross-tenant
        data leakage (HIPAA, GDPR, SOC 2).

        Raises:
            ValueError: If neither user_id nor tenant_id provided
        """
        # Extract from params or kwargs
        key_params = params if params is not None else _extract_cache_key_kwargs(kwargs)

        # Validation
        _validate_cache_key_isolation(key_params.user_id, key_params.tenant_id)
        _validate_cache_key_types(
            key_params.model,
            key_params.prompt,
            key_params.temperature,
            key_params.max_tokens,
            key_params.user_id,
            key_params.tenant_id,
            key_params.session_id,
        )
        _validate_cache_kwargs(self._RESERVED_PARAMS, key_params.extra_params)

        # Build request dict and hash
        cache_key = _generate_cache_key_hash(key_params)

        logger.debug(
            "Generated cache key with isolation: %s...",
            cache_key[:CACHE_KEY_LOG_LENGTH],
            extra={
                "model": key_params.model,
                "tenant_id": key_params.tenant_id,
                "user_id": key_params.user_id,
                "has_session": bool(key_params.session_id),
            },
        )
        return cache_key

    @staticmethod
    def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize tools list for deterministic hashing (sorted by name)."""
        sorted_tools = sorted(tools, key=lambda t: t.get("name", ""))
        return [dict(sorted(t.items())) for t in sorted_tools]

    def get(self, key: str) -> str | None:
        """
        Get cached response.

        Args:
            key: Cache key

        Returns:
            Cached response or None if not found

        Side effects:
            Updates cache statistics
        """
        try:
            value = self._backend.get(key)

            with self._stats_lock:
                if value is not None:
                    self.stats.hits += 1
                    logger.debug(f"Cache HIT: {key[:CACHE_KEY_LOG_LENGTH]}...")
                else:
                    self.stats.misses += 1
                    logger.debug(f"Cache MISS: {key[:CACHE_KEY_LOG_LENGTH]}...")

            self._fire_cache_event("hit" if value is not None else "miss", key)
            return value

        except (OSError, RuntimeError, ValueError) as e:
            # OSError: network/IO errors from filesystem backends
            # RuntimeError: threading errors (e.g., lock acquisition)
            # ValueError: serialization/deserialization errors
            with self._stats_lock:
                self.stats.errors += 1
            logger.error(
                f"Cache get error for key '{key[:CACHE_KEY_LOG_LENGTH]}...': {e}"
            )
            return None

    def set(self, key: str, value: str) -> bool:
        """
        Cache a response.

        Args:
            key: Cache key
            value: Response to cache

        Returns:
            True if successful, False otherwise

        Side effects:
            Updates cache statistics
        """
        try:
            # M-17: Guard against None TTL
            ttl_value = self.ttl if self.ttl is not None else TTL_LONG  # Default 1 hour
            success = self._backend.set(key, value, ttl=ttl_value)

            if success:
                with self._stats_lock:
                    self.stats.writes += 1
                logger.debug(f"Cached response: {key[:CACHE_KEY_LOG_LENGTH]}...")
                self._fire_cache_event("write", key)
            else:
                with self._stats_lock:
                    self.stats.errors += 1
                logger.warning(
                    f"Failed to cache response: {key[:CACHE_KEY_LOG_LENGTH]}..."
                )

            return success

        except (OSError, RuntimeError, ValueError) as e:
            # OSError: network/IO errors from filesystem backends
            # RuntimeError: threading errors (e.g., lock acquisition)
            # ValueError: serialization/deserialization errors
            with self._stats_lock:
                self.stats.errors += 1
            logger.error(
                f"Cache set error for key '{key[:CACHE_KEY_LOG_LENGTH]}...': {e}"
            )
            return False

    def delete(self, key: str) -> bool:
        """Delete cached response."""
        return self._backend.delete(key)

    def clear(self) -> None:
        """Clear entire cache."""
        self._backend.clear()
        logger.info("Cache cleared")

    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        return self._backend.exists(key)

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with hit rate, counts, etc.
        """
        with self._stats_lock:
            stats = self.stats.to_dict()

        # Add backend-specific stats
        if isinstance(self._backend, InMemoryCache):
            stats.update(self._backend.get_stats())

        return stats

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        with self._stats_lock:
            self.stats = CacheStats()
        logger.debug("Cache statistics reset")
