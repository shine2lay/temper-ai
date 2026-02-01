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
from typing import Any, Dict, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from threading import Lock
from src.utils.logging import get_logger

logger = get_logger(__name__)


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

    def __init__(self, max_size: int = 1000):
        """
        Initialize in-memory cache.

        Args:
            max_size: Maximum number of entries before eviction
        """
        self._cache: Dict[str, Tuple[str, Optional[float]]] = {}
        self._access_order: Dict[str, float] = {}  # Track access time for LRU
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

            # Update access time for LRU
            self._access_order[key] = time.time()
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
            self._access_order[key] = time.time()
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

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_order:
            return

        # Find least recently accessed key
        lru_key = min(self._access_order, key=self._access_order.get)  # type: ignore

        # Remove it
        del self._cache[lru_key]
        del self._access_order[lru_key]
        self._evictions += 1

        logger.debug(f"Evicted LRU entry: {lru_key} (total evictions: {self._evictions})")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'evictions': self._evictions
            }


class RedisCache(CacheBackend):
    """
    Redis cache backend.

    Requires: redis package
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, password: Optional[str] = None):
        """
        Initialize Redis cache.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (optional)

        Raises:
            ImportError: If redis package not installed
            ConnectionError: If cannot connect to Redis
        """
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError:
            raise ImportError(
                "Redis backend requires 'redis' package. "
                "Install with: pip install redis"
            )

        self._client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True  # Return strings not bytes
        )

        # Test connection
        try:
            self._client.ping()
            logger.info(f"Connected to Redis at {host}:{port} (db={db})")
        except redis.ConnectionError as e:
            raise ConnectionError(f"Failed to connect to Redis: {e}")

    def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        try:
            value = self._client.get(key)
            return value if value is not None else None
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> bool:
        """Set value in Redis with optional TTL."""
        try:
            if ttl:
                self._client.setex(key, ttl, value)
            else:
                self._client.set(key, value)
            return True
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete key from Redis."""
        try:
            return bool(self._client.delete(key))
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False

    def clear(self) -> None:
        """Clear entire Redis database."""
        try:
            self._client.flushdb()
            logger.info("Redis database cleared")
        except Exception as e:
            logger.error(f"Redis clear error: {e}")

    def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        try:
            return bool(self._client.exists(key))
        except Exception as e:
            logger.error(f"Redis exists error: {e}")
            return False


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

    def __init__(
        self,
        backend: str = "memory",
        ttl: Optional[int] = 3600,
        max_size: int = 1000,
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

        # Build canonical request dict
        request = {
            'model': model,
            'prompt': prompt,
            'temperature': temperature,
            'max_tokens': max_tokens,
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

        # Combine request and security context
        canonical = json.dumps({
            'request': request,
            'security_context': security_context
        }, sort_keys=True)

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
