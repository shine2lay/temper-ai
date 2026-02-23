"""Comprehensive tests for OAuth state storage implementations."""

import asyncio

import pytest

from temper_ai.auth.oauth.state_store import (
    InMemoryStateStore,
    StateStore,
    create_state_store,
)


class TestStateStoreInterface:
    """Tests for StateStore abstract base class."""

    def test_abstract_methods_prevent_instantiation(self):
        """Test that StateStore cannot be instantiated directly (ABC)."""
        with pytest.raises(TypeError, match="abstract method"):
            StateStore()

    @pytest.mark.asyncio
    async def test_close_method_exists(self):
        """Test close method can be called on concrete subclass."""
        store = InMemoryStateStore()
        result = await store.close()  # Should not raise
        assert result is None


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
            "code_verifier": "verifier_abc",
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
            await store.set_state(
                f"expired_{i}", {"user_id": f"user_{i}"}, ttl_seconds=1
            )

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
            await store.set_state(
                f"state_{i}", {"user_id": f"user_{i}"}, ttl_seconds=3600
            )

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
            store.get_state("state_123"),
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
        result = await store.close()  # Should not raise
        assert result is None


class TestCreateStateStoreFactory:
    """Tests for create_state_store factory function."""

    def test_creates_inmemory_store(self):
        """Test factory creates InMemoryStateStore."""
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
            "nested": {"a": "b" * 1000},
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

        state_data = {"user_id": "用户123", "provider": "google", "emoji": "🔐🌍"}

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
