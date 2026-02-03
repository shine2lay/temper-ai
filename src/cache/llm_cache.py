"""
LLM response caching for cost reduction and faster development.

Provides:
- Content-based hashing for cache keys
- In-memory and Redis backend support
- TTL (time-to-live) for cache expiration
- Opt-in via configuration
- Thread-safe operations
- Cache hit/miss statistics
"""
import hashlib
import json
import time
import os
import warnings
from typing import Any, Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from threading import Lock
from collections import OrderedDict
from src.utils.logging import get_logger
from src.cache.constants import DEFAULT_CACHE_SIZE, DEFAULT_TTL_SECONDS

logger = get_logger(__name__)

# Import redis at module level for exception handling
try:
    import redis  # type: ignore[import-not-found]
    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore
    REDIS_AVAILABLE = False


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            **asdict(self),
            'hit_rate': self.hit_rate
        }


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Get value from cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        pass

    @abstractmethod
    def clear(self) -> None:
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

    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE):
        """
        Initialize in-memory cache.

        Args:
            max_size: Maximum number of entries before eviction
        """
        self._cache: Dict[str, Tuple[str, Optional[float]]] = {}
        # PERFORMANCE FIX (code-medi-07): Use OrderedDict for O(1) LRU eviction
        # OrderedDict maintains insertion order, allowing efficient LRU tracking
        self._access_order: OrderedDict = OrderedDict()  # Track access order for LRU
        self._max_size = max_size
        self._lock = Lock()
        self._evictions = 0

        logger.debug(f"InMemoryCache initialized with max_size={max_size}")

    def get(self, key: str) -> Optional[str]:
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

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
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

    def clear(self) -> None:
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
        lru_key, _ = self._access_order.popitem(last=False)  # Remove first (oldest) item

        # Remove from cache
        del self._cache[lru_key]
        self._evictions += 1

        logger.debug(f"Evicted LRU entry: {lru_key} (total evictions: {self._evictions})")

    def get_stats(self, cleanup_expired: bool = True) -> Dict[str, Any]:
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
                'size': len(self._cache),
                'max_size': self._max_size,
                'evictions': self._evictions,
                'expired_cleaned': expired_cleaned
            }


class RedisCache(CacheBackend):
    """
    Redis cache backend.

    Requires: redis package
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: Optional[str] = None):
        """
        Initialize Redis cache.

        SECURITY FIX (code-crit-redis-password-07): Redis password is loaded from
        REDIS_PASSWORD environment variable to prevent credential exposure in logs,
        stack traces, and process listings.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: (DEPRECATED) Redis password - use REDIS_PASSWORD env var instead

        Environment Variables:
            REDIS_PASSWORD: Redis authentication password (required for authenticated Redis)

        Raises:
            ImportError: If redis package not installed
            ValueError: If Redis authentication fails
            ConnectionError: If cannot connect to Redis
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "Redis backend requires 'redis' package. "
                "Install with: pip install redis"
            )

        # Handle deprecated password parameter
        if password is not None:
            warnings.warn(
                "Passing password to RedisCache() is deprecated and insecure. "
                "Use REDIS_PASSWORD environment variable instead.",
                DeprecationWarning,
                stacklevel=2
            )
            logger.warning("Redis password passed as parameter (deprecated, use REDIS_PASSWORD env var)")
            redis_password = password
        else:
            # Load from environment (secure approach)
            redis_password = os.getenv('REDIS_PASSWORD')

        # Create Redis connection
        try:
            self._client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=redis_password,  # May be None for local dev
                decode_responses=True,  # Return strings not bytes
                socket_connect_timeout=5,
                socket_timeout=5,
            )

            # Test connection
            self._client.ping()
            logger.info(f"Connected to Redis at {host}:{port} (db={db})")

        except redis.AuthenticationError:
            raise ValueError(
                "Redis authentication failed. Set REDIS_PASSWORD environment variable "
                "or ensure Redis doesn't require authentication."
            )
        except redis.ConnectionError as e:
            raise ConnectionError(f"Failed to connect to Redis at {host}:{port}: {e}")

    def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        try:
            value = self._client.get(key)
            return value if value is not None else None
        except redis.RedisError as e:
            # Specific exception for Redis operations
            logger.error(f"Redis get error: {e}")
            return None
        # KeyboardInterrupt and SystemExit propagate automatically

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in Redis with optional TTL."""
        try:
            if ttl:
                self._client.setex(key, ttl, value)
            else:
                self._client.set(key, value)
            return True
        except redis.RedisError as e:
            # Specific exception for Redis operations
            logger.error(f"Redis set error: {e}")
            return False
        # KeyboardInterrupt and SystemExit propagate automatically

    def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        try:
            return bool(self._client.delete(key))
        except redis.RedisError as e:
            # Specific exception for Redis operations
            logger.error(f"Redis delete error: {e}")
            return False
        # KeyboardInterrupt and SystemExit propagate automatically

    def clear(self, pattern: str = "*", dry_run: bool = False, batch_size: int = 100) -> int:
        """
        Clear cache keys safely using SCAN.

        SECURITY FIX (code-crit-redis-flush-08): Replace dangerous flushdb() with
        SCAN-based deletion to prevent data loss across shared Redis instances.

        WARNING: Currently deletes ALL keys (pattern="*") since RedisCache doesn't
        use key prefixes. Use with caution in shared Redis environments.
        TODO: Add key_prefix support in separate task for proper isolation.

        Args:
            pattern: Redis key pattern to delete (default: "*" = all keys)
                    Example: "llm_cache:*" to delete only cache keys
            dry_run: If True, count keys without deleting
            batch_size: Keys to process per batch (default: 100)

        Returns:
            Number of keys deleted (or would delete in dry-run)

        Note:
            Uses SCAN instead of KEYS to avoid blocking Redis.
            Use pattern parameter to limit scope when sharing Redis.
        """
        try:
            cursor = 0
            deleted_count = 0

            logger.info(f"Clearing Redis keys matching '{pattern}' (dry_run={dry_run})")

            while True:
                # SCAN is non-blocking and returns cursor + batch of keys
                cursor, keys = self._client.scan(
                    cursor=cursor,
                    match=pattern,
                    count=batch_size
                )

                if keys:
                    if dry_run:
                        # Just count, don't delete
                        deleted_count += len(keys)
                        logger.debug(f"Would delete {len(keys)} keys")
                    else:
                        # Delete batch using pipeline for efficiency
                        pipe = self._client.pipeline()
                        for key in keys:
                            pipe.delete(key)
                        pipe.execute()

                        deleted_count += len(keys)
                        logger.debug(f"Deleted {len(keys)} keys")

                # cursor=0 means we've scanned entire keyspace
                if cursor == 0:
                    break

            logger.info(
                f"Redis clear {'dry-run' if dry_run else 'complete'}: "
                f"{deleted_count} keys {'would be' if dry_run else ''} deleted"
            )

            return deleted_count

        except redis.RedisError as e:
            # Specific exception for Redis operations
            logger.error(f"Redis clear error: {e}")
            return 0
        # KeyboardInterrupt and SystemExit propagate automatically

    def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        try:
            return bool(self._client.exists(key))
        except redis.RedisError as e:
            # Specific exception for Redis operations
            logger.error(f"Redis exists error: {e}")
            return False
        # KeyboardInterrupt and SystemExit propagate automatically

    def __repr__(self) -> str:
        """
        Safe repr that doesn't expose credentials.

        SECURITY FIX (code-crit-redis-password-07): Prevent password exposure
        in logs, error messages, and debugging output.
        """
        try:
            connected = self._client.ping() if self._client else False
        except redis.RedisError:
            # Redis connection errors when checking status
            connected = False
        except Exception:
            # Unexpected errors (e.g., attribute errors if _client malformed)
            # Log for debugging but don't crash repr
            logger.debug(f"Unexpected error in RedisCache.__repr__")
            connected = False
        # KeyboardInterrupt and SystemExit propagate automatically
        return f"RedisCache(connected={connected})"

    def __str__(self) -> str:
        """Safe string representation (delegates to __repr__)."""
        return self.__repr__()


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
    _RESERVED_PARAMS = frozenset({
        'model', 'prompt', 'temperature', 'max_tokens',
        'user_id', 'tenant_id', 'session_id',
        'system_prompt', 'tools',  # Explicit parameters to prevent cache collision
        'security_context', 'request'  # Prevent namespace pollution
    })

    def __init__(
        self,
        backend: str = "memory",
        ttl: Optional[int] = DEFAULT_TTL_SECONDS,
        max_size: int = DEFAULT_CACHE_SIZE,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None
    ):
        """
        Initialize LLM cache.

        Args:
            backend: Cache backend ("memory" or "redis")
            ttl: Time-to-live in seconds (None = no expiration)
            max_size: Max entries for in-memory cache
            redis_host: Redis host (if using Redis backend)
            redis_port: Redis port
            redis_db: Redis database number
            redis_password: Redis password

        Raises:
            ValueError: If backend is unknown
        """
        self.ttl = ttl
        self.stats = CacheStats()
        self._stats_lock = Lock()

        # Create backend
        if backend == "memory":
            self._backend: CacheBackend = InMemoryCache(max_size=max_size)
        elif backend == "redis":
            self._backend = RedisCache(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password
            )
        else:
            raise ValueError(f"Unknown cache backend: {backend}. Use 'memory' or 'redis'.")

        logger.info(f"LLMCache initialized with backend={backend}, ttl={ttl}s")

    def generate_key(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> str:
        """
        Generate cache key with mandatory user/tenant isolation.

        SECURITY: This method requires user_id OR tenant_id to prevent
        cross-tenant data leakage. Without isolation, identical prompts
        from different users/tenants would share cache entries, causing
        privacy violations and compliance breaches (HIPAA, GDPR, SOC 2).

        Uses SHA-256 hash of canonicalized request parameters including
        security context to ensure proper isolation.

        Args:
            model: Model name
            prompt: Prompt text
            temperature: Temperature parameter
            max_tokens: Max tokens parameter
            user_id: User identifier (REQUIRED for user-level caching)
            tenant_id: Tenant identifier (REQUIRED for tenant-level caching)
            session_id: Session identifier (optional, for session-level caching)
            **kwargs: Additional parameters to include in key

        Returns:
            Cache key (hex string) with user/tenant isolation

        Raises:
            ValueError: If neither user_id nor tenant_id provided

        Example:
            >>> cache = LLMCache()
            >>> # Different tenants get different keys
            >>> key1 = cache.generate_key("gpt-4", "Hello", tenant_id="tenant_a")
            >>> key2 = cache.generate_key("gpt-4", "Hello", tenant_id="tenant_b")
            >>> key1 != key2  # Different tenants = different keys
            True
        """
        # SECURITY: Enforce user/tenant context to prevent cross-tenant data leakage
        if not user_id and not tenant_id:
            raise ValueError(
                "Cache key generation requires user_id or tenant_id for security. "
                "Multi-tenant caching without isolation is a privacy violation. "
                "See: HIPAA 164.312(a)(1), GDPR Article 32, SOC 2 CC6.6"
            )

        # SECURITY FIX: Validate parameter types to prevent type confusion attacks
        if not isinstance(model, str):
            raise TypeError(f"model must be str, got {type(model).__name__}")
        if not isinstance(prompt, str):
            raise TypeError(f"prompt must be str, got {type(prompt).__name__}")
        if not isinstance(temperature, (int, float)):
            raise TypeError(f"temperature must be numeric, got {type(temperature).__name__}")
        if not isinstance(max_tokens, int):
            raise TypeError(f"max_tokens must be int, got {type(max_tokens).__name__}")
        if user_id is not None and not isinstance(user_id, str):
            raise TypeError(f"user_id must be str or None, got {type(user_id).__name__}")
        if tenant_id is not None and not isinstance(tenant_id, str):
            raise TypeError(f"tenant_id must be str or None, got {type(tenant_id).__name__}")
        if session_id is not None and not isinstance(session_id, str):
            raise TypeError(f"session_id must be str or None, got {type(session_id).__name__}")

        # SECURITY FIX: Validate kwargs to prevent parameter override attacks
        # Prevents cache poisoning via reserved parameter injection (code-crit-15)
        conflicting_params = self._RESERVED_PARAMS.intersection(kwargs.keys())
        if conflicting_params:
            raise ValueError(
                f"Cannot override reserved parameters via kwargs: {conflicting_params}. "
                f"Reserved parameters: {self._RESERVED_PARAMS}. "
                f"Use explicit arguments instead of **kwargs for these parameters."
            )

        # Build canonical request dict
        request = {
            'model': model,
            'prompt': prompt,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'system_prompt': system_prompt or '',
            'tools': self._normalize_tools(tools) if tools else [],
            **kwargs
        }

        # SECURITY: Add user context to separate namespace (prevents collision)
        security_context = {}
        if tenant_id:
            security_context['tenant_id'] = tenant_id
        if user_id:
            security_context['user_id'] = user_id
        if session_id:
            security_context['session_id'] = session_id

        # Combine request and security context with strict JSON serialization
        try:
            canonical = json.dumps(
                {
                    'request': request,
                    'security_context': security_context
                },
                sort_keys=True,
                ensure_ascii=True,  # Consistent Unicode handling
                separators=(',', ':')  # Consistent whitespace
            )
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"Cache key generation failed: parameters must be JSON-serializable. "
                f"Error: {e}"
            )

        # Hash with SHA-256
        hash_obj = hashlib.sha256(canonical.encode('utf-8'))
        cache_key = hash_obj.hexdigest()

        logger.debug(
            f"Generated cache key with isolation: {cache_key[:16]}...",
            extra={
                'model': model,
                'tenant_id': tenant_id,
                'user_id': user_id,
                'has_session': bool(session_id)
            }
        )
        return cache_key

    @staticmethod
    def _normalize_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize tools list for deterministic hashing (sorted by name)."""
        sorted_tools = sorted(tools, key=lambda t: t.get("name", ""))
        return [dict(sorted(t.items())) for t in sorted_tools]

    def get(self, key: str) -> Optional[str]:
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
                    logger.debug(f"Cache HIT: {key[:16]}...")
                else:
                    self.stats.misses += 1
                    logger.debug(f"Cache MISS: {key[:16]}...")

            return value

        except Exception as e:
            # Catches backend-specific exceptions but allows KeyboardInterrupt
            # and SystemExit to propagate
            with self._stats_lock:
                self.stats.errors += 1
            logger.error(f"Cache get error: {e}")
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
            success = self._backend.set(key, value, ttl=self.ttl)

            if success:
                with self._stats_lock:
                    self.stats.writes += 1
                logger.debug(f"Cached response: {key[:16]}...")
            else:
                with self._stats_lock:
                    self.stats.errors += 1
                logger.warning(f"Failed to cache response: {key[:16]}...")

            return success

        except Exception as e:
            # Catches backend-specific exceptions but allows KeyboardInterrupt
            # and SystemExit to propagate
            with self._stats_lock:
                self.stats.errors += 1
            logger.error(f"Cache set error: {e}")
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

    def get_stats(self) -> Dict[str, Any]:
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
