"""Tests for OAuth state storage implementations."""

import asyncio

import pytest

from temper_ai.auth.oauth.state_store import InMemoryStateStore, create_state_store


@pytest.mark.asyncio
class TestInMemoryStateStore:
    """Tests for in-memory state storage."""

    async def test_set_and_get_state(self):
        """Should store and retrieve state data."""
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


def test_create_state_store_factory():
    """Factory should create InMemoryStateStore."""
    store = create_state_store()

    assert store is not None
    assert isinstance(store, InMemoryStateStore)


@pytest.mark.asyncio
async def test_state_store_close():
    """State stores should clean up resources on close."""
    inmem_store = InMemoryStateStore()
    await inmem_store.close()  # Should not raise
    assert True
