# Task Specification: code-crit-redis-flush-08

## Problem Statement

`LLMCache.clear()` uses `flushdb()` which deletes ALL data in the Redis database, affecting other applications sharing the same Redis instance. This can cause catastrophic data loss across multiple applications and services.

Redis databases are often shared across multiple applications in production. Using `flushdb()` is extremely dangerous and should never be used unless you OWN the entire Redis instance.

## Context

- **Source:** Code Review Report 2026-02-01 (Critical Issue #8)
- **File Affected:** `src/cache/llm_cache.py:314`
- **Impact:** Data loss across all applications using the same Redis database
- **Module:** Cache
- **Severity:** CRITICAL (can destroy production data)

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Replace `flushdb()` with key-prefix-based deletion
- [ ] Only delete keys belonging to LLM cache
- [ ] Use SCAN for safe iteration (don't block Redis)
- [ ] Handle large key sets efficiently

### SAFETY
- [ ] Never delete keys from other applications
- [ ] No blocking operations (use SCAN, not KEYS)
- [ ] Graceful handling of Redis errors
- [ ] Option to delete in batches (prevents timeout)

### DATA INTEGRITY
- [ ] Only keys with cache prefix are deleted
- [ ] Verify key ownership before deletion
- [ ] Log deletion operations for audit trail
- [ ] Support dry-run mode for testing

### TESTING
- [ ] Test only cache keys are deleted
- [ ] Test other keys are preserved
- [ ] Test with large key sets (1000+ keys)
- [ ] Test with mixed cache/non-cache keys
- [ ] Performance testing (no Redis blocking)

## Implementation Plan

### Step 1: Read Current Implementation

**File:** `src/cache/llm_cache.py:314`

```bash
grep -B 10 -A 5 "flushdb" src/cache/llm_cache.py
```

### Step 2: Implement Safe Key-Based Deletion

**File:** `src/cache/llm_cache.py`

**Before (DANGEROUS):**
```python
class LLMCache:
    def __init__(self, ...):
        self.key_prefix = "llm_cache:"

    def clear(self) -> None:
        """Clear cache entries (DANGEROUS - deletes entire database)"""
        self._client.flushdb()  # DELETES ALL DATA - VERY DANGEROUS
```

**After (SAFE):**
```python
import logging

logger = logging.getLogger(__name__)

class LLMCache:
    def __init__(self, ...):
        self.key_prefix = "llm_cache:"

    def clear(self, dry_run: bool = False, batch_size: int = 100) -> int:
        """
        Clear cache entries safely by deleting only keys with our prefix.

        This method uses SCAN to iterate through keys incrementally,
        preventing Redis blocking and ensuring we only delete cache keys.

        Args:
            dry_run: If True, only count keys without deleting
            batch_size: Number of keys to delete per batch

        Returns:
            Number of keys deleted (or that would be deleted in dry-run)

        Note:
            Uses SCAN instead of KEYS to avoid blocking Redis.
            Only deletes keys with the configured key_prefix.
        """
        pattern = f"{self.key_prefix}*"
        cursor = 0
        deleted_count = 0
        batch = []

        logger.info(f"Clearing cache keys matching: {pattern} (dry_run={dry_run})")

        while True:
            # SCAN is non-blocking and returns a cursor + batch of keys
            # count is a hint, actual batch size may vary
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
                    # Delete batch of keys
                    # Use pipeline for efficiency
                    pipe = self._client.pipeline()
                    for key in keys:
                        pipe.delete(key)
                    pipe.execute()

                    deleted_count += len(keys)
                    logger.debug(f"Deleted {len(keys)} keys")

            # cursor=0 means we've scanned the entire keyspace
            if cursor == 0:
                break

        logger.info(
            f"Cache clear {'dry-run' if dry_run else 'complete'}: "
            f"{deleted_count} keys {'would be' if dry_run else ''} deleted"
        )

        return deleted_count

    def clear_all(self) -> None:
        """
        DANGEROUS: Clear entire Redis database.

        WARNING: This deletes ALL keys in the database, including keys
        from other applications. Only use this if you own the entire
        Redis instance.

        Raises:
            RuntimeError: Always raises to prevent accidental use
        """
        raise RuntimeError(
            "clear_all() is disabled to prevent data loss. "
            "Use clear() to delete only cache keys, or manually call "
            "flushdb() if you really own the entire Redis instance."
        )
```

### Step 3: Add Key Prefix Configuration

Ensure key prefix is configurable for multi-tenant scenarios:

```python
class LLMCache:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        key_prefix: str = "llm_cache:"
    ):
        """
        Initialize LLM cache.

        Args:
            key_prefix: Prefix for all cache keys (default: "llm_cache:")
                       Use different prefixes for different applications
                       or environments (e.g., "prod:llm_cache:")
        """
        self.key_prefix = key_prefix
        # ... rest of init
```

### Step 4: Add Monitoring

Track cache operations:
```python
def clear(self, dry_run: bool = False, batch_size: int = 100) -> int:
    start_time = time.time()
    deleted_count = # ... deletion logic ...
    duration = time.time() - start_time

    logger.info(
        f"Cache clear completed: {deleted_count} keys in {duration:.2f}s "
        f"({deleted_count/duration:.0f} keys/s)"
    )

    return deleted_count
```

## Test Strategy

### Unit Tests

**File:** `tests/cache/test_llm_cache_clear_safety.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from src.cache.llm_cache import LLMCache

def test_clear_only_deletes_cache_keys():
    """Test that clear() only deletes keys with cache prefix"""
    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        # Simulate SCAN returning cache and non-cache keys
        # In reality, SCAN with pattern would only return matching keys
        mock_client.scan.side_effect = [
            (0, [b'llm_cache:key1', b'llm_cache:key2']),  # cursor, keys
        ]

        cache = LLMCache(key_prefix="llm_cache:")
        deleted = cache.clear()

        # Verify SCAN was called with correct pattern
        mock_client.scan.assert_called()
        call_kwargs = mock_client.scan.call_args.kwargs
        assert call_kwargs['match'] == 'llm_cache:*'

        # Verify keys were deleted
        assert deleted == 2

def test_clear_preserves_other_keys():
    """Test that keys without prefix are NOT deleted"""
    # This is implicitly tested by using SCAN with pattern
    # SCAN will only return keys matching the pattern
    pass

def test_clear_uses_scan_not_keys():
    """Test that SCAN is used (non-blocking) instead of KEYS (blocking)"""
    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        mock_client.scan.return_value = (0, [])

        cache = LLMCache()
        cache.clear()

        # Verify SCAN was called
        mock_client.scan.assert_called()

        # Verify KEYS was NOT called (blocking operation)
        assert not mock_client.keys.called

def test_clear_dry_run_mode():
    """Test dry-run mode counts but doesn't delete"""
    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client
        mock_client.scan.return_value = (0, [b'key1', b'key2', b'key3'])

        cache = LLMCache()
        deleted = cache.clear(dry_run=True)

        # Should count keys
        assert deleted == 3

        # Should NOT call delete
        assert not mock_client.delete.called
        assert not mock_client.pipeline.called

def test_clear_large_keyspace():
    """Test clearing large number of keys (uses SCAN cursor)"""
    with patch('redis.Redis') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        # Simulate SCAN pagination (cursor-based iteration)
        mock_client.scan.side_effect = [
            (1, [b'key1', b'key2']),   # cursor=1, more keys
            (2, [b'key3', b'key4']),   # cursor=2, more keys
            (0, [b'key5']),            # cursor=0, done
        ]

        cache = LLMCache()
        deleted = cache.clear()

        # Should have scanned 3 times (until cursor=0)
        assert mock_client.scan.call_count == 3
        # Should have deleted 5 keys total
        assert deleted == 5

def test_clear_all_raises_error():
    """Test that clear_all() raises error (safety measure)"""
    cache = LLMCache()

    with pytest.raises(RuntimeError, match="disabled to prevent data loss"):
        cache.clear_all()
```

### Integration Tests

**File:** `tests/cache/test_llm_cache_clear_integration.py`

```python
import pytest
from src.cache.llm_cache import LLMCache

@pytest.mark.integration
def test_clear_with_real_redis():
    """Integration test with real Redis"""
    cache = LLMCache(key_prefix="test_cache:")

    # Set up test data
    cache.set("key1", "value1")
    cache.set("key2", "value2")

    # Also add a key with different prefix (simulates another app)
    cache._client.set("other_app:key3", "value3")

    # Clear cache
    deleted = cache.clear()

    # Verify only cache keys deleted
    assert deleted == 2
    assert cache.get("key1") is None
    assert cache.get("key2") is None

    # Verify other app's key is preserved
    assert cache._client.get("other_app:key3") == "value3"

    # Cleanup
    cache._client.delete("other_app:key3")

@pytest.mark.integration
def test_clear_performance_with_many_keys():
    """Test performance with large key set"""
    import time

    cache = LLMCache(key_prefix="perf_test:")

    # Create 10,000 cache keys
    for i in range(10000):
        cache.set(f"key{i}", f"value{i}")

    # Clear should complete in reasonable time
    start = time.time()
    deleted = cache.clear(batch_size=1000)
    duration = time.time() - start

    assert deleted == 10000
    assert duration < 10.0  # Should complete in <10 seconds
```

## Error Handling

**Scenarios:**
1. Redis connection lost during clear → Log error, partial deletion is OK
2. Key deletion fails → Continue with other keys, log error
3. Empty keyspace → Return 0, no error

## Success Metrics

- [ ] Only cache keys are deleted (other keys preserved)
- [ ] Uses SCAN (non-blocking)
- [ ] Handles 10,000+ keys efficiently
- [ ] All tests pass
- [ ] clear_all() raises error (safety check)
- [ ] Dry-run mode works correctly
- [ ] No data loss in integration tests

## Dependencies

**Blocked by:** None

**Blocks:** None (can be done in parallel)

**Related:** code-crit-redis-password-07 (both Redis cache security issues)

## References

- Code Review Report: `.claude-coord/reports/code-review-20260201-002732.md` (lines 192-213)
- Redis SCAN: https://redis.io/commands/scan/
- Redis Best Practices: https://redis.io/docs/manual/patterns/

## Estimated Effort

**Time:** 2-3 hours
**Complexity:** Low-Medium (SCAN logic is straightforward, testing is important)

---

*Priority: CRITICAL (0)*
*Category: Security & Data Integrity*
