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
from typing import Dict, Any, Optional
from datetime import timedelta, datetime
import json
import logging
import os

logger = logging.getLogger(__name__)


class StateStore:
    """Abstract base class for state storage implementations."""

    async def set_state(
        self,
        state: str,
        data: Dict[str, Any],
        ttl_seconds: int = 600
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

    def __init__(self):
        """Initialize in-memory state storage."""
        self._store: Dict[str, Dict[str, Any]] = {}
        logger.warning(
            "Using InMemoryStateStore - NOT suitable for production! "
            "Use RedisStateStore instead."
        )

    async def set_state(
        self,
        state: str,
        data: Dict[str, Any],
        ttl_seconds: int = 600
    ) -> None:
        """Store state data with expiration time."""
        data_with_expiry = {
            **data,
            'expires_at': (
                datetime.utcnow() + timedelta(seconds=ttl_seconds)
            ).isoformat()
        }
        self._store[state] = data_with_expiry
        logger.debug(f"Stored state: {state} (TTL: {ttl_seconds}s)")

    async def get_state(self, state: str) -> Optional[Dict[str, Any]]:
        """Retrieve and delete state data (one-time use)."""
        data = self._store.get(state)

        if data is None:
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(data['expires_at'])
        if datetime.utcnow() > expires_at:
            del self._store[state]
            return None

        # Delete (one-time use)
        del self._store[state]

        # Remove expires_at before returning
        data_copy = data.copy()
        del data_copy['expires_at']

        return data_copy

    async def delete_state(self, state: str) -> bool:
        """Delete state data."""
        if state in self._store:
            del self._store[state]
            return True
        return False

    async def cleanup_expired(self) -> int:
        """Clean up expired states (manual cleanup for in-memory store).

        Returns:
            Number of states cleaned up
        """
        now = datetime.utcnow()
        expired_keys = []

        for state, data in self._store.items():
            expires_at = datetime.fromisoformat(data['expires_at'])
            if now > expires_at:
                expired_keys.append(state)

        for key in expired_keys:
            del self._store[key]

        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired states")

        return len(expired_keys)


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
        ... }, ttl_seconds=600)
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
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                # Test connection
                await self._redis.ping()
                logger.info(f"Connected to Redis: {self.redis_url}")
            except Exception as e:
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
        ttl_seconds: int = 600
    ) -> None:
        """Store state data with automatic TTL.

        Args:
            state: State token
            data: State data (user_id, provider, code_verifier, etc.)
            ttl_seconds: Time to live in seconds (default: 10 minutes)
        """
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

        logger.debug(f"Stored OAuth state: {state} (TTL: {ttl_seconds}s)")

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

        # Atomic get-and-delete using pipeline
        pipeline = self._redis.pipeline()
        pipeline.get(key)
        pipeline.delete(key)
        results = await pipeline.execute()

        value = results[0]

        if value is None:
            logger.debug(f"State not found or expired: {state}")
            return None

        try:
            data = json.loads(value)
            logger.debug(f"Retrieved and deleted state: {state}")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode state data for {state}: {e}")
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
        import redis.asyncio
        # Try to create Redis store
        store = RedisStateStore(redis_url=redis_url)
        return store
    except ImportError:
        logger.warning(
            "Redis not available, using in-memory state storage. "
            "Install redis for production: pip install redis>=5.0.0"
        )
        return InMemoryStateStore()
    except Exception as e:
        logger.error(f"Failed to create Redis state store: {e}, falling back to in-memory")
        return InMemoryStateStore()
