"""Comprehensive tests for OAuth State Store - P0 SECURITY.

Tests cover:
1. State CSRF token generation and validation
2. State storage (InMemory backend)
3. State expiration and automatic cleanup
4. State validation (prevent replay attacks)
5. State storage isolation per provider
6. Concurrent state operations (thread safety)
7. LRU eviction for in-memory store
8. Atomic get-and-delete operations (one-time use)
"""

import asyncio
import secrets
from datetime import UTC, datetime

import pytest

from temper_ai.auth.oauth.state_store import (
    InMemoryStateStore,
    StateStore,
    create_state_store,
)


@pytest.fixture
def sample_state_data():
    """Create sample OAuth state data."""
    return {
        "user_id": "user_123",
        "provider": "google",
        "code_verifier": secrets.token_urlsafe(32),
        "redirect_uri": "http://localhost:8000/auth/callback",
        "nonce": secrets.token_urlsafe(16),
    }


@pytest.fixture
def state_token():
    """Generate random state token."""
    return secrets.token_urlsafe(32)


class TestInMemoryStateStore:
    """Test InMemoryStateStore implementation."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test InMemoryStateStore initialization."""
        store = InMemoryStateStore()

        assert isinstance(store._store, dict)
        assert len(store._store) == 0
        assert store._max_entries == 50000

    @pytest.mark.asyncio
    async def test_initialization_custom_max_entries(self):
        """Test initialization with custom max_entries."""
        store = InMemoryStateStore(max_entries=1000)

        assert store._max_entries == 1000

    @pytest.mark.asyncio
    async def test_set_state_stores_data(self, sample_state_data, state_token):
        """Test set_state stores state data with expiration."""
        store = InMemoryStateStore()

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)

        assert state_token in store._store
        stored_data = store._store[state_token]
        assert stored_data["user_id"] == sample_state_data["user_id"]
        assert stored_data["provider"] == sample_state_data["provider"]
        assert "expires_at" in stored_data

    @pytest.mark.asyncio
    async def test_set_state_default_ttl(self, sample_state_data, state_token):
        """Test set_state uses default TTL (10 minutes)."""
        store = InMemoryStateStore()

        await store.set_state(state_token, sample_state_data)

        stored_data = store._store[state_token]
        expires_at = datetime.fromisoformat(stored_data["expires_at"])
        now = datetime.now(UTC)
        delta = (expires_at - now).total_seconds()

        # Should be approximately 10 minutes (600 seconds)
        assert 595 < delta < 605

    @pytest.mark.asyncio
    async def test_get_state_retrieves_and_deletes(
        self, sample_state_data, state_token
    ):
        """Test get_state retrieves data and deletes it (one-time use)."""
        store = InMemoryStateStore()

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)
        retrieved = await store.get_state(state_token)

        assert retrieved is not None
        assert retrieved["user_id"] == sample_state_data["user_id"]
        assert retrieved["provider"] == sample_state_data["provider"]
        assert "expires_at" not in retrieved  # Metadata removed

        # State should be deleted (one-time use)
        assert state_token not in store._store

    @pytest.mark.asyncio
    async def test_get_state_nonexistent_returns_none(self):
        """Test get_state returns None for nonexistent state."""
        store = InMemoryStateStore()

        result = await store.get_state("nonexistent_state")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_expired_returns_none(self, sample_state_data, state_token):
        """Test get_state returns None for expired state."""
        store = InMemoryStateStore()

        await store.set_state(state_token, sample_state_data, ttl_seconds=1)
        await asyncio.sleep(1.1)  # Wait for expiration

        result = await store.get_state(state_token)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_atomic_operation(self, sample_state_data):
        """Test get_state is atomic (prevents race conditions)."""
        store = InMemoryStateStore()
        state_token = secrets.token_urlsafe(32)

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)

        # Concurrent get_state calls - only one should succeed
        results = await asyncio.gather(
            store.get_state(state_token),
            store.get_state(state_token),
            store.get_state(state_token),
        )

        # Only one should get data, others should get None
        successful = [r for r in results if r is not None]
        assert len(successful) == 1
        assert successful[0]["user_id"] == sample_state_data["user_id"]

    @pytest.mark.asyncio
    async def test_delete_state_removes_data(self, sample_state_data, state_token):
        """Test delete_state removes state data."""
        store = InMemoryStateStore()

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)
        deleted = await store.delete_state(state_token)

        assert deleted is True
        assert state_token not in store._store

    @pytest.mark.asyncio
    async def test_delete_state_nonexistent_returns_false(self):
        """Test delete_state returns False for nonexistent state."""
        store = InMemoryStateStore()

        deleted = await store.delete_state("nonexistent_state")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_old_states(self, sample_state_data):
        """Test cleanup_expired removes expired states."""
        store = InMemoryStateStore()

        # Add expired and valid states
        await store.set_state("expired_1", sample_state_data, ttl_seconds=1)
        await store.set_state("expired_2", sample_state_data, ttl_seconds=1)
        await store.set_state("valid_1", sample_state_data, ttl_seconds=600)

        await asyncio.sleep(1.1)  # Wait for expiration

        cleaned = await store.cleanup_expired()

        assert cleaned == 2
        assert "valid_1" in store._store
        assert "expired_1" not in store._store
        assert "expired_2" not in store._store

    @pytest.mark.asyncio
    async def test_auto_cleanup_at_80_percent(self, sample_state_data):
        """Test automatic cleanup when store reaches 80% capacity."""
        store = InMemoryStateStore(max_entries=10)

        # Fill to 80% with expired states
        for i in range(8):
            await store.set_state(f"state_{i}", sample_state_data, ttl_seconds=1)

        await asyncio.sleep(1.1)  # Expire all

        # Adding one more should trigger cleanup
        await store.set_state("new_state", sample_state_data, ttl_seconds=600)

        # Old expired states should be cleaned
        assert len(store._store) == 1
        assert "new_state" in store._store

    @pytest.mark.asyncio
    async def test_lru_eviction_when_full(self, sample_state_data):
        """Test LRU eviction when store exceeds max_entries."""
        store = InMemoryStateStore(max_entries=5)

        # Fill store to capacity with non-expiring states
        for i in range(5):
            await store.set_state(f"state_{i}", sample_state_data, ttl_seconds=600)

        # Add one more - should trigger eviction of oldest 20%
        await store.set_state("state_new", sample_state_data, ttl_seconds=600)

        # Should have evicted oldest entry (state_0)
        assert len(store._store) <= 5
        assert "state_new" in store._store

    @pytest.mark.asyncio
    async def test_concurrent_set_operations(self, sample_state_data):
        """Test concurrent set_state operations are thread-safe."""
        store = InMemoryStateStore()

        async def set_states(prefix):
            for i in range(10):
                await store.set_state(
                    f"{prefix}_state_{i}", sample_state_data, ttl_seconds=600
                )

        await asyncio.gather(
            set_states("thread1"),
            set_states("thread2"),
            set_states("thread3"),
        )

        # All states should be stored
        assert len(store._store) == 30

    @pytest.mark.asyncio
    async def test_close_noop(self):
        """Test close() is a no-op for in-memory store."""
        store = InMemoryStateStore()
        await store.close()
        # Should not raise any errors
        assert True


class TestStateStoreFactory:
    """Test create_state_store factory function."""

    def test_create_state_store_returns_inmemory(self):
        """Test factory returns InMemoryStateStore."""
        store = create_state_store()

        assert isinstance(store, InMemoryStateStore)

    def test_create_state_store_is_state_store(self):
        """Test factory returns a StateStore instance."""
        store = create_state_store()

        assert isinstance(store, StateStore)


class TestStateIsolationPerProvider:
    """Test state storage isolation between OAuth providers."""

    @pytest.mark.asyncio
    async def test_different_providers_isolated(self):
        """Test states from different providers are isolated."""
        store = InMemoryStateStore()

        google_state = secrets.token_urlsafe(32)
        github_state = secrets.token_urlsafe(32)

        await store.set_state(
            google_state, {"provider": "google", "user_id": "user_1"}, ttl_seconds=600
        )
        await store.set_state(
            github_state, {"provider": "github", "user_id": "user_1"}, ttl_seconds=600
        )

        google_data = await store.get_state(google_state)
        github_data = await store.get_state(github_state)

        assert google_data["provider"] == "google"
        assert github_data["provider"] == "github"

    @pytest.mark.asyncio
    async def test_state_tokens_globally_unique(self):
        """Test state tokens are globally unique (prevent collision)."""
        store = InMemoryStateStore()

        # Generate many state tokens
        state_tokens = [secrets.token_urlsafe(32) for _ in range(1000)]

        # All should be unique
        assert len(state_tokens) == len(set(state_tokens))

        # Store all
        for i, token in enumerate(state_tokens):
            await store.set_state(token, {"index": i}, ttl_seconds=600)

        # Retrieve all correctly
        for i, token in enumerate(state_tokens):
            data = await store.get_state(token)
            assert data["index"] == i


class TestCSRFProtection:
    """Test CSRF protection via state validation."""

    @pytest.mark.asyncio
    async def test_state_single_use_prevents_replay(self, sample_state_data):
        """Test state is single-use (prevents replay attacks)."""
        store = InMemoryStateStore()
        state_token = secrets.token_urlsafe(32)

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)

        # First use succeeds
        first = await store.get_state(state_token)
        assert first is not None

        # Second use fails (token deleted)
        second = await store.get_state(state_token)
        assert second is None

    @pytest.mark.asyncio
    async def test_expired_state_prevents_delayed_attack(self, sample_state_data):
        """Test expired state prevents delayed CSRF attacks."""
        store = InMemoryStateStore()
        state_token = secrets.token_urlsafe(32)

        await store.set_state(state_token, sample_state_data, ttl_seconds=1)
        await asyncio.sleep(1.1)

        # Expired state cannot be used
        result = await store.get_state(state_token)
        assert result is None

    @pytest.mark.asyncio
    async def test_state_validation_requires_exact_match(self, sample_state_data):
        """Test state validation requires exact token match."""
        store = InMemoryStateStore()
        state_token = secrets.token_urlsafe(32)

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)

        # Slight modification fails validation
        modified_token = state_token[:-1] + ("a" if state_token[-1] != "a" else "b")
        result = await store.get_state(modified_token)

        assert result is None


class TestStateTruncationInLogs:
    """Test state tokens are truncated in logs (prevent exposure)."""

    @pytest.mark.asyncio
    async def test_set_state_truncates_token_in_logs(self, sample_state_data, caplog):
        """Test set_state truncates state token in logs."""
        import logging

        caplog.set_level(logging.DEBUG)

        store = InMemoryStateStore()
        state_token = secrets.token_urlsafe(32)

        await store.set_state(state_token, sample_state_data, ttl_seconds=600)

        # Check logs don't contain full token
        log_messages = [record.message for record in caplog.records]
        for msg in log_messages:
            if "state" in msg.lower():
                # Token should be truncated to 8 chars
                assert state_token not in msg or len(state_token) <= 8
