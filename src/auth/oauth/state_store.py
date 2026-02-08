"""Redis-backed OAuth state storage.

Provides distributed state storage for OAuth flows with:
- Automatic TTL expiration
- Horizontal scalability (multi-instance support)
- Persistence across application restarts
- Atomic get-and-delete operations (one-time use)

Security Features:
- State tokens are single-use (deleted after validation)
- Automatic expiration after 10 minutes
- No memory exhaustion risk (Redis TTL handles cleanup)
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.constants.durations import SECONDS_PER_10_MINUTES, TIMEOUT_SHORT
from src.constants.limits import PERCENT_20, PERCENT_80, THRESHOLD_MASSIVE_COUNT

logger = logging.getLogger(__name__)


class StateStore:
    """Abstract base class for state storage implementations."""

    async def set_state(
        self,
        state: str,
        data: Dict[str, Any],
        ttl_seconds: int = SECONDS_PER_10_MINUTES
    ) -> None:
        """Store state data with TTL.

        Args:
            state: State token
            data: State data (user_id, provider, code_verifier, etc.)
            ttl_seconds: Time to live in seconds (default: 10 minutes)
        """
        raise NotImplementedError

    async def get_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Retrieve and delete state data (one-time use).

        Args:
            state: State token

        Returns:
            State data or None if expired/not found
        """
        raise NotImplementedError

    async def delete_state(self, state: str) -> bool:
        """Delete state data.

        Args:
            state: State token

        Returns:
            True if deleted, False if not found
        """
        raise NotImplementedError

    async def close(self):
        """Clean up resources."""
        pass


class InMemoryStateStore(StateStore):
    """In-memory state storage (for development/testing only).

    WARNING: Do NOT use in production!
    - No persistence across restarts
    - Not suitable for distributed deployments
    - Manual cleanup required (no automatic TTL)

    Use RedisStateStore for production environments.
    """

    MAX_ENTRIES = THRESHOLD_MASSIVE_COUNT * 5  # 50000

    def __init__(self, max_entries: int = None):
        """Initialize in-memory state storage.

        Args:
            max_entries: Maximum number of entries before auto-cleanup (default: 50000)
        """
        self._store: Dict[str, Dict[str, Any]] = {}
        self._max_entries = max_entries if max_entries is not None else self.MAX_ENTRIES
        self._lock = asyncio.Lock()
        logger.warning(
            "Using InMemoryStateStore - NOT suitable for production! "
            "Use RedisStateStore instead."
        )

    async def set_state(
        self,
        state: str,
        data: Dict[str, Any],
        ttl_seconds: int = None
    ) -> None:
        """Store state data with expiration time."""
        if ttl_seconds is None:
            ttl_seconds = SECONDS_PER_10_MINUTES

        async with self._lock:
            # Auto-cleanup when 80% full to prevent unbounded memory growth
            if len(self._store) >= int(self._max_entries * (PERCENT_80 / 100)):
                await self._cleanup_expired_unlocked()
                # If still over limit after cleanup, remove oldest 20%
                if len(self._store) >= self._max_entries:
                    self._evict_oldest()

            data_with_expiry = {
                **data,
                'expires_at': (
                    datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
                ).isoformat()
            }
            self._store[state] = data_with_expiry
        # SEC-14: Truncate state token in logs to prevent exposure
        logger.debug(f"Stored state: {state[:8]}... (TTL: {ttl_seconds}s)")

    async def get_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Retrieve and delete state data (one-time use).

        Uses asyncio.Lock + dict.pop() for atomic get-and-delete to prevent
        concurrent callbacks from consuming the same state token twice (AU-02).
        """
        async with self._lock:
            data = self._store.pop(state, None)

        if data is None:
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(data['expires_at'])
        if datetime.now(timezone.utc) > expires_at:
            return None

        # Remove expires_at before returning
        data_copy = data.copy()
        del data_copy['expires_at']

        return data_copy

    async def delete_state(self, state: str) -> bool:
        """Delete state data."""
        async with self._lock:
            if state in self._store:
                del self._store[state]
                return True
            return False

    async def _cleanup_expired_unlocked(self) -> int:
        """Clean up expired states (must be called while holding self._lock).

        Returns:
            Number of states cleaned up
        """
        now = datetime.now(timezone.utc)
        expired_keys = [
            state for state, data in self._store.items()
            if now > datetime.fromisoformat(data['expires_at'])
        ]

        for key in expired_keys:
            del self._store[key]

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired states")

        return len(expired_keys)

    async def cleanup_expired(self) -> int:
        """Clean up expired states (manual cleanup for in-memory store).

        Returns:
            Number of states cleaned up
        """
        async with self._lock:
            return await self._cleanup_expired_unlocked()

    def _evict_oldest(self) -> None:
        """Evict oldest 20% of entries when store exceeds max_entries."""
        to_remove = max(1, len(self._store) * PERCENT_20 // 100)
        # Sort by expires_at to remove the oldest entries first
        sorted_keys = sorted(
            self._store.keys(),
            key=lambda k: self._store[k].get('expires_at', ''),
        )
        for key in sorted_keys[:to_remove]:
            del self._store[key]
        logger.info(f"Evicted {to_remove} oldest state entries (size limit)")


class RedisStateStore(StateStore):
    """Redis-backed OAuth state storage (production-ready).

    Features:
    - Automatic TTL expiration (no manual cleanup needed)
    - Horizontal scalability across multiple app instances
    - Persistence across application restarts
    - Atomic get-and-delete operations

    Configuration:
        Set REDIS_URL environment variable:
        export REDIS_URL="redis://localhost:6379/0"

    Usage:
        >>> store = RedisStateStore(redis_url="redis://localhost:6379/0")
        >>> await store.set_state("state_123", {
        ...     "user_id": "user_456",
        ...     "provider": "google",
        ...     "code_verifier": "verifier_abc"
        ... }, ttl_seconds=SECONDS_PER_10_MINUTES)
        >>>
        >>> # Later (in callback):
        >>> state_data = await store.get_state("state_123")  # Atomic get-and-delete
        >>> # state_data is now deleted from Redis (one-time use)
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        key_prefix: str = "oauth:state:"
    ):
        """Initialize Redis state store.

        Args:
            redis_url: Redis connection URL (default: from REDIS_URL env var)
            key_prefix: Key prefix for namespacing (default: "oauth:state:")
        """
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.key_prefix = key_prefix
        self._redis: Optional[Any] = None
        self._redis_available = False

        # Try to import redis (may not be installed in dev)
        try:
            import redis.asyncio as redis_module
            self._redis_module = redis_module
            self._redis_available = True
        except ImportError:
            logger.warning(
                "redis package not installed. Install with: pip install redis>=5.0.0\n"
                "Falling back to in-memory storage (NOT suitable for production)"
            )
            self._redis_available = False

    async def connect(self):
        """Establish Redis connection."""
        if not self._redis_available:
            return

        if self._redis is None:
            try:
                self._redis = await self._redis_module.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=TIMEOUT_SHORT,
                    socket_timeout=TIMEOUT_SHORT
                )
                # Test connection
                await self._redis.ping()
                from src.utils.secrets import mask_url_password
                logger.info(f"Connected to Redis: {mask_url_password(self.redis_url)}")
            except (OSError, ConnectionError, TimeoutError, AttributeError) as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self._redis = None
                raise

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Closed Redis connection")

    def _make_key(self, state: str) -> str:
        """Generate Redis key for state token."""
        return f"{self.key_prefix}{state}"

    async def set_state(
        self,
        state: str,
        data: Dict[str, Any],
        ttl_seconds: int = None
    ) -> None:
        """Store state data with automatic TTL.

        Args:
            state: State token
            data: State data (user_id, provider, code_verifier, etc.)
            ttl_seconds: Time to live in seconds (default: 10 minutes)
        """
        if ttl_seconds is None:
            ttl_seconds = SECONDS_PER_10_MINUTES

        await self.connect()

        if not self._redis:
            raise RuntimeError("Redis connection not available")

        key = self._make_key(state)
        value = json.dumps(data, default=str)

        # Set with TTL (automatic expiration)
        await self._redis.setex(
            key,
            ttl_seconds,
            value
        )

        # SEC-14: Truncate state token in logs to prevent exposure
        logger.debug(f"Stored OAuth state: {state[:8]}... (TTL: {ttl_seconds}s)")

    async def get_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Retrieve and delete state data (atomic one-time use).

        Args:
            state: State token

        Returns:
            State data or None if expired/not found
        """
        await self.connect()

        if not self._redis:
            raise RuntimeError("Redis connection not available")

        key = self._make_key(state)

        # Atomic get-and-delete using Lua script (AU-01)
        # Pipeline GET+DELETE is NOT atomic - another request could GET between them.
        # Lua script executes atomically in Redis, preventing state token reuse.
        lua_script = """
        local value = redis.call('GET', KEYS[1])
        if value then
            redis.call('DEL', KEYS[1])
        end
        return value
        """
        value = await self._redis.eval(lua_script, 1, key)

        if value is None:
            # SEC-14: Truncate state token in logs
            logger.debug(f"State not found or expired: {state[:8]}...")
            return None

        try:
            data = json.loads(value)
            # SEC-14: Truncate state token in logs
            logger.debug(f"Retrieved and deleted state: {state[:8]}...")
            return data
        except json.JSONDecodeError as e:
            # SEC-14: Truncate state token in logs
            logger.error(f"Failed to decode state data for {state[:8]}...: {e}")
            return None

    async def delete_state(self, state: str) -> bool:
        """Delete state data.

        Args:
            state: State token

        Returns:
            True if deleted, False if not found
        """
        await self.connect()

        if not self._redis:
            raise RuntimeError("Redis connection not available")

        key = self._make_key(state)
        deleted = await self._redis.delete(key)

        return deleted > 0

    async def cleanup_expired(self) -> int:
        """Clean up expired states (automatic with Redis TTL).

        Returns:
            0 (Redis handles expiration automatically via TTL)
        """
        # No-op: Redis automatically expires keys with TTL
        # This method exists for interface compatibility
        return 0


def create_state_store(redis_url: Optional[str] = None) -> StateStore:
    """Factory function to create appropriate state store.

    Creates RedisStateStore if Redis is available, otherwise falls back
    to InMemoryStateStore (with warning).

    Args:
        redis_url: Redis connection URL (optional, uses REDIS_URL env var)

    Returns:
        StateStore instance (Redis if available, otherwise in-memory)
    """
    # Check if Redis is available
    try:
        import redis.asyncio  # noqa: F401 — availability check
        # Try to create Redis store
        store = RedisStateStore(redis_url=redis_url)
        return store
    except ImportError:
        logger.warning(
            "Redis not available, using in-memory state storage. "
            "Install redis for production: pip install redis>=5.0.0"
        )
        return InMemoryStateStore()
    except (OSError, ConnectionError, TimeoutError, AttributeError, RuntimeError) as e:
        logger.error(f"Failed to create Redis state store: {e}, falling back to in-memory")
        return InMemoryStateStore()
