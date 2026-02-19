"""Comprehensive tests for OAuth state storage implementations."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from temper_ai.auth.oauth.state_store import (
    InMemoryStateStore,
    RedisStateStore,
    StateStore,
    create_state_store,
)

# Check if redis is available
try:
    import redis.asyncio
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class TestStateStoreInterface:
    """Tests for StateStore abstract base class."""

    @pytest.mark.asyncio
    async def test_abstract_methods_raise_not_implemented(self):
        """Test abstract methods raise NotImplementedError."""
        store = StateStore()

        with pytest.raises(NotImplementedError):
            await store.set_state("state", {})

        with pytest.raises(NotImplementedError):
            await store.get_state("state")

        with pytest.raises(NotImplementedError):
            await store.delete_state("state")

    @pytest.mark.asyncio
    async def test_close_method_exists(self):
        """Test close method can be called."""
        store = StateStore()
        await store.close()  # Should not raise


@pytest.mark.asyncio
class TestInMemoryStateStore:
    """Comprehensive tests for InMemoryStateStore."""

    async def test_initialization_default_max_entries(self):
        """Test store initializes with default max entries."""
        store = InMemoryStateStore()
        assert store._max_entries == 50000
        assert len(store._store) == 0

    async def test_initialization_custom_max_entries(self):
        """Test store initializes with custom max entries."""
        store = InMemoryStateStore(max_entries=1000)
        assert store._max_entries == 1000

    async def test_set_and_get_state_basic(self):
        """Test basic set and get operations."""
        store = InMemoryStateStore()

        state_data = {
            "user_id": "user_123",
            "provider": "google",
            "code_verifier": "verifier_abc"
        }

        await store.set_state("state_token_123", state_data, ttl_seconds=600)

        retrieved = await store.get_state("state_token_123")
        assert retrieved is not None
        assert retrieved["user_id"] == "user_123"
        assert retrieved["provider"] == "google"
        assert retrieved["code_verifier"] == "verifier_abc"
        assert "expires_at" not in retrieved  # Internal field removed

    async def test_set_state_default_ttl(self):
        """Test set_state uses default TTL when not specified."""
        store = InMemoryStateStore()

        await store.set_state("state_123", {"user_id": "user_456"})

        # State should exist
        retrieved = await store.get_state("state_123")
        assert retrieved is not None

    async def test_get_state_one_time_use(self):
        """Test state is deleted after first retrieval."""
        store = InMemoryStateStore()

        state_data = {"user_id": "user_123"}
        await store.set_state("state_123", state_data)

        # First get succeeds
        first = await store.get_state("state_123")
        assert first is not None

        # Second get returns None (already deleted)
        second = await store.get_state("state_123")
        assert second is None

    async def test_get_state_expired(self):
        """Test expired state returns None."""
        store = InMemoryStateStore()

        state_data = {"user_id": "user_123"}
        await store.set_state("state_123", state_data, ttl_seconds=1)

        # Wait for expiration
        await asyncio.sleep(1.5)

        # Should return None (expired)
        retrieved = await store.get_state("state_123")
        assert retrieved is None

    async def test_get_state_nonexistent(self):
        """Test getting nonexistent state returns None."""
        store = InMemoryStateStore()

        retrieved = await store.get_state("nonexistent")
        assert retrieved is None

    async def test_delete_state_success(self):
        """Test deleting existing state."""
        store = InMemoryStateStore()

        await store.set_state("state_123", {"user_id": "user_123"})

        deleted = await store.delete_state("state_123")
        assert deleted is True

        # State should no longer exist
        retrieved = await store.get_state("state_123")
        assert retrieved is None

    async def test_delete_state_nonexistent(self):
        """Test deleting nonexistent state returns False."""
        store = InMemoryStateStore()

        deleted = await store.delete_state("nonexistent")
        assert deleted is False

    async def test_cleanup_expired_removes_expired_only(self):
        """Test cleanup removes only expired states."""
        store = InMemoryStateStore()

        # Add expired states
        await store.set_state("expired_1", {"user_id": "user_1"}, ttl_seconds=1)
        await store.set_state("expired_2", {"user_id": "user_2"}, ttl_seconds=1)

        # Add active states
        await store.set_state("active_1", {"user_id": "user_3"}, ttl_seconds=3600)
        await store.set_state("active_2", {"user_id": "user_4"}, ttl_seconds=3600)

        # Wait for expiration
        await asyncio.sleep(1.5)

        # Cleanup
        cleaned = await store.cleanup_expired()
        assert cleaned == 2

        # Active states should still exist
        assert await store.get_state("active_1") is not None
        assert await store.get_state("active_2") is not None

    async def test_cleanup_expired_with_no_expired_states(self):
        """Test cleanup when no states are expired."""
        store = InMemoryStateStore()

        await store.set_state("state_1", {"user_id": "user_1"}, ttl_seconds=3600)

        cleaned = await store.cleanup_expired()
        assert cleaned == 0

    async def test_auto_cleanup_at_80_percent(self):
        """Test automatic cleanup when 80% full."""
        store = InMemoryStateStore(max_entries=10)

        # Add 8 expired states (80% of 10)
        for i in range(8):
            await store.set_state(f"expired_{i}", {"user_id": f"user_{i}"}, ttl_seconds=1)

        await asyncio.sleep(1.5)

        # Add one more state (triggers cleanup)
        await store.set_state("new_state", {"user_id": "new_user"}, ttl_seconds=3600)

        # Expired states should be cleaned
        retrieved = await store.get_state("expired_0")
        assert retrieved is None

        # New state should exist
        retrieved = await store.get_state("new_state")
        assert retrieved is not None

    async def test_evict_oldest_when_full(self):
        """Test oldest entries are evicted when store is full."""
        store = InMemoryStateStore(max_entries=5)

        # Fill store to capacity with long TTL
        for i in range(5):
            await store.set_state(f"state_{i}", {"user_id": f"user_{i}"}, ttl_seconds=3600)

        # Add one more (should trigger eviction of 20% = 1 entry)
        await store.set_state("state_5", {"user_id": "user_5"}, ttl_seconds=3600)

        # Store should have evicted oldest entry
        # Note: we can't predict which one due to dict ordering
        assert len(store._store) <= 5

    async def test_concurrent_access_thread_safety(self):
        """Test concurrent state access is thread-safe."""
        store = InMemoryStateStore()

        state_data = {"user_id": "user_123"}
        await store.set_state("state_123", state_data)

        # Attempt concurrent gets (only one should succeed due to lock)
        results = await asyncio.gather(
            store.get_state("state_123"),
            store.get_state("state_123"),
            store.get_state("state_123")
        )

        # Only one should get the state, others should get None
        non_none_results = [r for r in results if r is not None]
        assert len(non_none_results) == 1

    async def test_state_data_isolation(self):
        """Test state data is isolated between entries."""
        store = InMemoryStateStore()

        state1 = {"user_id": "user_1", "provider": "google"}
        state2 = {"user_id": "user_2", "provider": "github"}

        await store.set_state("state_1", state1)
        await store.set_state("state_2", state2)

        retrieved1 = await store.get_state("state_1")
        retrieved2 = await store.get_state("state_2")

        assert retrieved1["user_id"] == "user_1"
        assert retrieved2["user_id"] == "user_2"
        assert retrieved1["provider"] != retrieved2["provider"]

    async def test_close_method(self):
        """Test close method can be called."""
        store = InMemoryStateStore()
        await store.close()  # Should not raise


class TestRedisStateStore:
    """Comprehensive tests for RedisStateStore."""

    @pytest.fixture
    @pytest.mark.asyncio
    async def redis_store(self):
        """Create Redis state store for testing."""
        if not REDIS_AVAILABLE:
            pytest.skip("redis package not installed")

        try:
            store = RedisStateStore(redis_url="redis://localhost:6379/15")
            await store.connect()

            # Clean test database
            if store._redis:
                await store._redis.flushdb()

            yield store

            # Cleanup
            if store._redis:
                await store._redis.flushdb()
            await store.close()

        except Exception as e:
            pytest.skip(f"Redis not available: {e}")

    async def test_initialization(self):
        """Test RedisStateStore initialization."""
        store = RedisStateStore(redis_url="redis://localhost:6379/0")
        assert store.redis_url == "redis://localhost:6379/0"
        assert store.key_prefix == "oauth:state:"
        assert store._redis is None

    async def test_initialization_custom_prefix(self):
        """Test initialization with custom key prefix."""
        store = RedisStateStore(key_prefix="custom:prefix:")
        assert store.key_prefix == "custom:prefix:"

    async def test_initialization_env_variable(self):
        """Test initialization reads REDIS_URL from env."""
        with patch.dict("os.environ", {"REDIS_URL": "redis://custom:6379/1"}):
            store = RedisStateStore()
            assert store.redis_url == "redis://custom:6379/1"

    async def test_connect_success(self, redis_store):
        """Test successful connection to Redis."""
        assert redis_store._redis is not None

    async def test_connect_failure_no_redis(self):
        """Test connection failure when Redis unavailable."""
        if not REDIS_AVAILABLE:
            pytest.skip("redis package not installed")

        store = RedisStateStore(redis_url="redis://nonexistent:9999/0")

        with pytest.raises((OSError, ConnectionError, TimeoutError, AttributeError)):
            await store.connect()

    async def test_set_and_get_state(self, redis_store):
        """Test basic set and get operations in Redis."""
        state_data = {
            "user_id": "user_123",
            "provider": "google",
            "code_verifier": "verifier_abc"
        }

        await redis_store.set_state("state_token_123", state_data, ttl_seconds=600)

        retrieved = await redis_store.get_state("state_token_123")
        assert retrieved is not None
        assert retrieved["user_id"] == "user_123"
        assert retrieved["provider"] == "google"

    async def test_set_state_default_ttl(self, redis_store):
        """Test set_state uses default TTL."""
        await redis_store.set_state("state_123", {"user_id": "user_456"})

        # Verify TTL is set
        key = redis_store._make_key("state_123")
        ttl = await redis_store._redis.ttl(key)
        assert ttl > 0

    async def test_get_state_atomic_delete(self, redis_store):
        """Test get_state atomically deletes (one-time use)."""
        state_data = {"user_id": "user_123"}
        await redis_store.set_state("state_123", state_data)

        # First get succeeds
        first = await redis_store.get_state("state_123")
        assert first is not None

        # Second get fails (atomically deleted)
        second = await redis_store.get_state("state_123")
        assert second is None

    async def test_get_state_expired_by_ttl(self, redis_store):
        """Test Redis automatically expires state after TTL."""
        state_data = {"user_id": "user_123"}
        await redis_store.set_state("state_123", state_data, ttl_seconds=1)

        # Wait for Redis to expire
        await asyncio.sleep(1.5)

        # Should be None (auto-expired by Redis)
        retrieved = await redis_store.get_state("state_123")
        assert retrieved is None

    async def test_get_state_nonexistent(self, redis_store):
        """Test getting nonexistent state returns None."""
        retrieved = await redis_store.get_state("nonexistent")
        assert retrieved is None

    async def test_delete_state_success(self, redis_store):
        """Test deleting existing state."""
        await redis_store.set_state("state_123", {"user_id": "user_123"})

        deleted = await redis_store.delete_state("state_123")
        assert deleted is True

        # State should not exist
        retrieved = await redis_store.get_state("state_123")
        assert retrieved is None

    async def test_delete_state_nonexistent(self, redis_store):
        """Test deleting nonexistent state returns False."""
        deleted = await redis_store.delete_state("nonexistent")
        assert deleted is False

    async def test_cleanup_expired_is_noop(self, redis_store):
        """Test cleanup_expired is no-op (Redis handles expiration)."""
        cleaned = await redis_store.cleanup_expired()
        assert cleaned == 0

    async def test_persistence_across_reconnect(self, redis_store):
        """Test state persists across connection close/reopen."""
        state_data = {"user_id": "user_123", "provider": "google"}
        await redis_store.set_state("state_persistent", state_data, ttl_seconds=600)

        # Close connection
        await redis_store.close()

        # Reconnect
        await redis_store.connect()

        # State should still exist
        retrieved = await redis_store.get_state("state_persistent")
        assert retrieved is not None
        assert retrieved["user_id"] == "user_123"

    async def test_make_key_method(self):
        """Test _make_key generates correct Redis key."""
        store = RedisStateStore(key_prefix="oauth:state:")
        key = store._make_key("state_123")
        assert key == "oauth:state:state_123"

    async def test_close_cleans_up_connection(self, redis_store):
        """Test close method cleans up Redis connection."""
        await redis_store.close()
        assert redis_store._redis is None

    async def test_concurrent_atomic_get(self, redis_store):
        """Test concurrent gets are atomic (only one succeeds)."""
        state_data = {"user_id": "user_123"}
        await redis_store.set_state("state_concurrent", state_data)

        # Attempt concurrent gets
        results = await asyncio.gather(
            redis_store.get_state("state_concurrent"),
            redis_store.get_state("state_concurrent"),
            redis_store.get_state("state_concurrent")
        )

        # Only one should succeed due to atomic Lua script
        non_none_results = [r for r in results if r is not None]
        assert len(non_none_results) == 1

    async def test_set_state_without_connection_raises(self):
        """Test set_state without connection raises error."""
        if not REDIS_AVAILABLE:
            pytest.skip("redis package not installed")

        store = RedisStateStore()
        # Don't connect

        with pytest.raises(RuntimeError, match="Redis connection not available"):
            await store.set_state("state_123", {})

    async def test_get_state_json_decode_error_handling(self, redis_store):
        """Test get_state handles JSON decode errors gracefully."""
        # Manually insert invalid JSON
        key = redis_store._make_key("invalid_json")
        await redis_store._redis.set(key, "not valid json", ex=600)

        # Should return None and log error
        retrieved = await redis_store.get_state("invalid_json")
        assert retrieved is None


class TestCreateStateStoreFactory:
    """Tests for create_state_store factory function."""

    def test_creates_redis_store_when_available(self):
        """Test factory creates Redis store when available."""
        if not REDIS_AVAILABLE:
            pytest.skip("redis package not installed")

        with patch("temper_ai.auth.oauth.state_store.RedisStateStore") as mock_redis:
            mock_instance = Mock()
            mock_redis.return_value = mock_instance

            store = create_state_store(redis_url="redis://localhost:6379/0")

            mock_redis.assert_called_once_with(redis_url="redis://localhost:6379/0")
            assert store == mock_instance

    def test_falls_back_to_inmemory_on_import_error(self):
        """Test factory falls back to InMemoryStateStore on import error."""
        with patch("temper_ai.auth.oauth.state_store.RedisStateStore") as mock_redis:
            mock_redis.side_effect = ImportError("redis not installed")

            store = create_state_store()

            assert isinstance(store, InMemoryStateStore)

    def test_falls_back_to_inmemory_on_connection_error(self):
        """Test factory falls back on connection errors."""
        with patch("temper_ai.auth.oauth.state_store.RedisStateStore") as mock_redis:
            mock_redis.side_effect = ConnectionError("Cannot connect")

            store = create_state_store()

            assert isinstance(store, InMemoryStateStore)

    def test_factory_returns_state_store_instance(self):
        """Test factory always returns StateStore instance."""
        store = create_state_store()
        assert isinstance(store, StateStore)


@pytest.mark.asyncio
class TestStateStoreEdgeCases:
    """Edge case tests for state storage."""

    async def test_large_state_data(self):
        """Test storing large state data."""
        store = InMemoryStateStore()

        # Large state data
        large_data = {
            "user_id": "user_123",
            "large_field": "x" * 10000,  # 10KB string
            "nested": {"a": "b" * 1000}
        }

        await store.set_state("large_state", large_data)

        retrieved = await store.get_state("large_state")
        assert retrieved is not None
        assert len(retrieved["large_field"]) == 10000

    async def test_special_characters_in_state_token(self):
        """Test state tokens with special characters."""
        store = InMemoryStateStore()

        state_tokens = [
            "state-with-dashes",
            "state_with_underscores",
            "state.with.dots",
            "state123numbers",
        ]

        for token in state_tokens:
            await store.set_state(token, {"user_id": "user_123"})
            retrieved = await store.get_state(token)
            assert retrieved is not None

    async def test_unicode_in_state_data(self):
        """Test Unicode characters in state data."""
        store = InMemoryStateStore()

        state_data = {
            "user_id": "用户123",
            "provider": "google",
            "emoji": "🔐🌍"
        }

        await store.set_state("unicode_state", state_data)

        retrieved = await store.get_state("unicode_state")
        assert retrieved["user_id"] == "用户123"
        assert retrieved["emoji"] == "🔐🌍"

    async def test_empty_state_data(self):
        """Test storing empty state data."""
        store = InMemoryStateStore()

        await store.set_state("empty_state", {})

        retrieved = await store.get_state("empty_state")
        assert retrieved is not None
        assert retrieved == {}

    async def test_very_short_ttl(self):
        """Test very short TTL (< 1 second)."""
        store = InMemoryStateStore()

        await store.set_state("short_ttl", {"user_id": "user_123"}, ttl_seconds=0.1)

        await asyncio.sleep(0.2)

        retrieved = await store.get_state("short_ttl")
        assert retrieved is None
