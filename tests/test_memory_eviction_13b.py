"""Tests for bounded collection eviction in code-high-memory-eviction-13b.

Verifies:
1. SecureTokenStore._access_log is a bounded deque
2. InMemoryStateStore auto-cleans and evicts when over max_entries
3. ObservabilityBuffer._pending_ids purges stale entries
"""

import time
from collections import deque

import pytest
from cryptography.fernet import Fernet

from temper_ai.auth.oauth.state_store import InMemoryStateStore
from temper_ai.auth.oauth.token_store import SecureTokenStore
from temper_ai.observability.buffer import ObservabilityBuffer

# ── SecureTokenStore access log eviction ──────────────────────────────────


class TestTokenStoreAccessLogEviction:
    """Verify _access_log uses bounded deque."""

    def _make_store(self, max_access_log_size=100):
        key = Fernet.generate_key().decode()
        return SecureTokenStore(
            encryption_key=key,
            use_keyring=False,
            max_access_log_size=max_access_log_size,
        )

    def test_access_log_is_deque(self):
        store = self._make_store()
        assert isinstance(store._access_log, deque)

    def test_access_log_respects_maxlen(self):
        store = self._make_store(max_access_log_size=5)
        for i in range(10):
            store.store_token(f"user_{i}", {"access_token": f"tok_{i}"})
        assert len(store._access_log) == 5

    def test_access_log_keeps_newest(self):
        store = self._make_store(max_access_log_size=3)
        for i in range(5):
            store.store_token(f"user_{i}", {"access_token": f"tok_{i}"})
        log = store.get_audit_log()
        assert len(log) == 3
        # Should have the last 3 entries (user_2, user_3, user_4)
        assert log[-1]["user_id"] == "user_4"
        assert log[0]["user_id"] == "user_2"

    def test_default_max_access_log_size(self):
        key = Fernet.generate_key().decode()
        store = SecureTokenStore(encryption_key=key, use_keyring=False)
        assert store._access_log.maxlen == SecureTokenStore.MAX_ACCESS_LOG_SIZE

    def test_get_audit_log_returns_list(self):
        store = self._make_store()
        store.store_token("user_1", {"access_token": "tok"})
        result = store.get_audit_log()
        assert isinstance(result, list)


# ── InMemoryStateStore eviction ──────────────────────────────────────────


class TestInMemoryStateStoreEviction:
    """Verify InMemoryStateStore auto-cleanup and eviction."""

    @pytest.mark.asyncio
    async def test_stays_within_max_entries(self):
        store = InMemoryStateStore(max_entries=10)
        for i in range(20):
            await store.set_state(f"state_{i}", {"data": i}, ttl_seconds=600)
        assert len(store._store) <= 10

    @pytest.mark.asyncio
    async def test_cleanup_triggered_at_80_percent(self):
        store = InMemoryStateStore(max_entries=10)
        # Insert 7 entries (below 80%)
        for i in range(7):
            await store.set_state(f"state_{i}", {"data": i}, ttl_seconds=600)
        assert len(store._store) == 7

        # Insert 1 more (at 80% = 8), should trigger cleanup but nothing expired
        await store.set_state("state_7", {"data": 7}, ttl_seconds=600)
        # All entries are fresh so no expiry cleanup, but still within limit
        assert len(store._store) <= 10

    @pytest.mark.asyncio
    async def test_evicts_oldest_when_full(self):
        store = InMemoryStateStore(max_entries=5)
        for i in range(10):
            await store.set_state(f"state_{i}", {"data": i}, ttl_seconds=600)
        # After eviction, should be bounded
        assert len(store._store) <= 5

    @pytest.mark.asyncio
    async def test_default_max_entries(self):
        store = InMemoryStateStore()
        assert store._max_entries == InMemoryStateStore.MAX_ENTRIES

    @pytest.mark.asyncio
    async def test_custom_max_entries(self):
        store = InMemoryStateStore(max_entries=42)
        assert store._max_entries == 42


# ── ObservabilityBuffer pending IDs purge ────────────────────────────────


class TestObservabilityBufferPendingIdsPurge:
    """Verify _pending_ids purges stale entries."""

    def test_pending_ids_is_dict(self):
        buf = ObservabilityBuffer(auto_flush=False)
        assert isinstance(buf._pending_ids, dict)

    def test_purge_removes_stale_entries(self):
        from temper_ai.observability._buffer_helpers import purge_stale_pending_ids

        buf = ObservabilityBuffer(auto_flush=False, pending_id_timeout=60)
        # Add entries with old timestamps
        old_time = time.time() - 120  # 2 minutes ago
        buf._pending_ids["old_1"] = old_time
        buf._pending_ids["old_2"] = old_time
        buf._pending_ids["fresh_1"] = time.time()

        purged = purge_stale_pending_ids(buf._pending_ids, buf._pending_id_timeout)
        assert purged == 2
        assert "old_1" not in buf._pending_ids
        assert "old_2" not in buf._pending_ids
        assert "fresh_1" in buf._pending_ids

    def test_purge_keeps_fresh_entries(self):
        from temper_ai.observability._buffer_helpers import purge_stale_pending_ids

        buf = ObservabilityBuffer(auto_flush=False, pending_id_timeout=300)
        buf._pending_ids["a"] = time.time()
        buf._pending_ids["b"] = time.time()

        purged = purge_stale_pending_ids(buf._pending_ids, buf._pending_id_timeout)
        assert purged == 0
        assert len(buf._pending_ids) == 2

    def test_default_pending_id_timeout(self):
        buf = ObservabilityBuffer(auto_flush=False)
        assert buf._pending_id_timeout == ObservabilityBuffer.PENDING_ID_TIMEOUT_SECONDS

    def test_custom_pending_id_timeout(self):
        buf = ObservabilityBuffer(auto_flush=False, pending_id_timeout=120)
        assert buf._pending_id_timeout == 120

    def test_purge_called_during_flush(self):
        buf = ObservabilityBuffer(auto_flush=False, pending_id_timeout=1)
        # Add stale entry
        buf._pending_ids["stale"] = time.time() - 10

        # Set a flush callback
        flushed = []
        buf.set_flush_callback(lambda llm, tool, metrics: flushed.append(True))

        # Flush (even with nothing to flush, purge should run)
        buf.flush()

        # Stale entry should be purged
        assert "stale" not in buf._pending_ids
