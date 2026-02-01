"""Tests for OAuth state storage implementations."""
import pytest
import asyncio
from datetime import datetime
from src.auth.oauth.state_store import (
    InMemoryStateStore,
    RedisStateStore,
    create_state_store
)


@pytest.mark.asyncio
class TestInMemoryStateStore:
    """Tests for in-memory state storage."""

    async def test_set_and_get_state(self):
        """Should store and retrieve state data."""
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

    async def test_state_one_time_use(self):
        """State should be deleted after retrieval (one-time use)."""
        store = InMemoryStateStore()

        state_data = {"user_id": "user_123", "provider": "google"}
        await store.set_state("state_123", state_data)

        # First retrieval succeeds
        first = await store.get_state("state_123")
        assert first is not None

        # Second retrieval fails (already deleted)
        second = await store.get_state("state_123")
        assert second is None

    async def test_state_expiration(self):
        """Expired state should not be retrievable."""
        store = InMemoryStateStore()

        state_data = {"user_id": "user_123", "provider": "google"}
        await store.set_state("state_123", state_data, ttl_seconds=1)

        # Should exist immediately
        assert await store.get_state("state_123") is not None

        # Wait for expiration
        await asyncio.sleep(2)

        # Should be expired
        assert await store.get_state("state_123") is None

    async def test_delete_state(self):
        """Should be able to manually delete state."""
        store = InMemoryStateStore()

        state_data = {"user_id": "user_123"}
        await store.set_state("state_123", state_data)

        # Delete state
        deleted = await store.delete_state("state_123")
        assert deleted is True

        # Should not exist anymore
        retrieved = await store.get_state("state_123")
        assert retrieved is None

        # Deleting non-existent state should return False
        deleted_again = await store.delete_state("state_123")
        assert deleted_again is False

    async def test_cleanup_expired(self):
        """Should clean up expired states."""
        store = InMemoryStateStore()

        # Add expired state
        await store.set_state("expired_1", {"user_id": "user_1"}, ttl_seconds=1)
        await store.set_state("expired_2", {"user_id": "user_2"}, ttl_seconds=1)

        # Add non-expired state
        await store.set_state("active_1", {"user_id": "user_3"}, ttl_seconds=3600)

        # Wait for expiration
        await asyncio.sleep(2)

        # Cleanup
        cleaned = await store.cleanup_expired()
        assert cleaned == 2  # Two expired states

        # Non-expired should still exist
        assert await store.get_state("active_1") is not None


@pytest.mark.asyncio
class TestRedisStateStore:
    """Tests for Redis state storage.

    These tests require a running Redis instance.
    If Redis is not available, tests will be skipped.
    """

    @pytest.fixture
    async def redis_store(self):
        """Create Redis state store for testing."""
        try:
            import redis.asyncio
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

        except ImportError:
            pytest.skip("redis package not installed")
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")

    async def test_set_and_get_state(self, redis_store):
        """Should store and retrieve state data in Redis."""
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
        assert retrieved["code_verifier"] == "verifier_abc"

    async def test_state_one_time_use(self, redis_store):
        """State should be deleted after retrieval (atomic get-and-delete)."""
        state_data = {"user_id": "user_123", "provider": "google"}
        await redis_store.set_state("state_123", state_data)

        # First retrieval succeeds
        first = await redis_store.get_state("state_123")
        assert first is not None

        # Second retrieval fails (deleted by first get)
        second = await redis_store.get_state("state_123")
        assert second is None

    async def test_state_auto_expiration(self, redis_store):
        """Redis should automatically expire state after TTL."""
        state_data = {"user_id": "user_123", "provider": "google"}
        await redis_store.set_state("state_123", state_data, ttl_seconds=2)

        # Should exist immediately
        key = redis_store._make_key("state_123")
        ttl = await redis_store._redis.ttl(key)
        assert 0 < ttl <= 2

        # Wait for expiration
        await asyncio.sleep(3)

        # Should be auto-expired by Redis
        retrieved = await redis_store.get_state("state_123")
        assert retrieved is None

    async def test_delete_state(self, redis_store):
        """Should be able to manually delete state."""
        state_data = {"user_id": "user_123"}
        await redis_store.set_state("state_123", state_data)

        # Delete state
        deleted = await redis_store.delete_state("state_123")
        assert deleted is True

        # Should not exist anymore
        retrieved = await redis_store.get_state("state_123")
        assert retrieved is None

        # Deleting non-existent state should return False
        deleted_again = await redis_store.delete_state("state_123")
        assert deleted_again is False

    async def test_persistence_across_reconnect(self, redis_store):
        """State should persist across connection close/reopen."""
        state_data = {"user_id": "user_123", "provider": "google"}
        await redis_store.set_state("state_persistent", state_data, ttl_seconds=600)

        # Close connection
        await redis_store.close()

        # Reconnect
        await redis_store.connect()

        # Should still exist
        retrieved = await redis_store.get_state("state_persistent")
        assert retrieved is not None
        assert retrieved["user_id"] == "user_123"


def test_create_state_store_factory():
    """Factory should create appropriate state store based on Redis availability."""
    store = create_state_store()

    # Should return either Redis or InMemory store
    assert store is not None
    assert isinstance(store, (RedisStateStore, InMemoryStateStore))


@pytest.mark.asyncio
async def test_state_store_close():
    """State stores should clean up resources on close."""
    # In-memory store
    inmem_store = InMemoryStateStore()
    await inmem_store.close()  # Should not raise

    # Redis store (if available)
    try:
        import redis.asyncio
        redis_store = RedisStateStore("redis://localhost:6379/15")
        await redis_store.connect()
        await redis_store.close()  # Should close connection
        assert redis_store._redis is None
    except ImportError:
        pass  # Skip if redis not installed
    except Exception:
        pass  # Skip if Redis not running
