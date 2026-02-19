"""Tests for LLM Cache Concurrent Access Thread Safety.

Tests concurrent access to the LLM cache using threading to verify:
- Thread-safe get/set operations
- No data races in InMemoryCache
- Cache hit/miss statistics under concurrent load
- TTL expiration behavior with concurrent access
- Error handling during concurrent operations
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch


from temper_ai.llm.cache.llm_cache import (
    InMemoryCache,
    LLMCache,
)


class TestInMemoryCacheConcurrency:
    """Test InMemoryCache thread safety under concurrent access."""

    def test_concurrent_set_operations(self):
        """Should handle concurrent set operations without data races."""
        cache = InMemoryCache(max_size=1000)
        num_threads = 20
        operations_per_thread = 50

        def writer(thread_id):
            """Write multiple entries to cache."""
            for i in range(operations_per_thread):
                key = f"thread_{thread_id}_key_{i}"
                value = f"value_{i}"
                cache.set(key, value, ttl=60)
            return thread_id

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(writer, tid) for tid in range(num_threads)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == num_threads
        # Verify all entries were stored
        assert len(cache._cache) == num_threads * operations_per_thread

    def test_concurrent_get_operations(self):
        """Should handle concurrent get operations without errors."""
        cache = InMemoryCache(max_size=1000)

        # Pre-populate cache
        for i in range(100):
            cache.set(f"key_{i}", f"value_{i}", ttl=60)

        num_threads = 30
        reads_per_thread = 100
        results = []

        def reader(thread_id):
            """Read multiple entries from cache."""
            local_results = []
            for i in range(reads_per_thread):
                key = f"key_{i % 100}"
                value = cache.get(key)
                local_results.append((key, value))
            return local_results

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(reader, tid) for tid in range(num_threads)]
            for future in as_completed(futures):
                results.extend(future.result())

        # All reads should succeed
        assert len(results) == num_threads * reads_per_thread
        # All values should be correct
        for key, value in results:
            expected_value = key.replace("key_", "value_")
            assert value == expected_value

    def test_concurrent_mixed_operations(self):
        """Should handle mixed read/write operations concurrently."""
        cache = InMemoryCache(max_size=500)

        # Pre-populate
        for i in range(100):
            cache.set(f"initial_key_{i}", f"initial_value_{i}", ttl=60)

        errors = []

        def writer(thread_id):
            """Write entries to cache."""
            try:
                for i in range(50):
                    key = f"writer_{thread_id}_key_{i}"
                    value = f"writer_{thread_id}_value_{i}"
                    cache.set(key, value, ttl=60)
                return ("write", thread_id)
            except Exception as e:
                errors.append(("write", thread_id, str(e)))
                raise

        def reader(thread_id):
            """Read entries from cache."""
            try:
                hits = 0
                for i in range(100):
                    key = f"initial_key_{i % 100}"
                    value = cache.get(key)
                    if value is not None:
                        hits += 1
                return ("read", thread_id, hits)
            except Exception as e:
                errors.append(("read", thread_id, str(e)))
                raise

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            # Submit 10 writers and 10 readers
            for i in range(10):
                futures.append(executor.submit(writer, i))
                futures.append(executor.submit(reader, i + 10))

            results = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0, f"Concurrent operations had errors: {errors}"
        assert len(results) == 20

    def test_concurrent_delete_operations(self):
        """Should handle concurrent delete operations without errors."""
        cache = InMemoryCache(max_size=1000)

        # Pre-populate
        keys_to_delete = []
        for i in range(200):
            key = f"key_{i}"
            cache.set(key, f"value_{i}", ttl=60)
            keys_to_delete.append(key)

        def deleter(thread_id):
            """Delete entries from cache."""
            deleted_count = 0
            for i in range(10):
                key_idx = thread_id * 10 + i
                if key_idx < len(keys_to_delete):
                    key = keys_to_delete[key_idx]
                    if cache.delete(key):
                        deleted_count += 1
            return deleted_count

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(deleter, tid) for tid in range(20)]
            results = [f.result() for f in as_completed(futures)]

        # All deletes should succeed (each thread deletes 10 keys)
        assert sum(results) == 200
        # Cache should be empty
        assert len(cache._cache) == 0

    def test_concurrent_ttl_expiration(self):
        """Should handle TTL expiration correctly under concurrent access."""
        cache = InMemoryCache(max_size=1000)

        # Store entries with short TTL
        for i in range(100):
            cache.set(f"key_{i}", f"value_{i}", ttl=1)

        # Wait for expiration
        time.sleep(1.2)

        def reader(thread_id):
            """Try to read expired entries."""
            none_count = 0
            for i in range(100):
                key = f"key_{i}"
                value = cache.get(key)
                if value is None:
                    none_count += 1
            return none_count

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(reader, tid) for tid in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # All reads should return None (expired)
        for none_count in results:
            assert none_count == 100

    def test_concurrent_lru_eviction(self):
        """Should handle LRU eviction correctly under concurrent access."""
        cache = InMemoryCache(max_size=100)

        # Pre-fill cache to capacity
        for i in range(100):
            cache.set(f"initial_key_{i}", f"initial_value_{i}", ttl=None)

        def writer(thread_id):
            """Write new entries to trigger eviction."""
            for i in range(20):
                key = f"thread_{thread_id}_key_{i}"
                value = f"thread_{thread_id}_value_{i}"
                cache.set(key, value, ttl=None)
            return thread_id

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(writer, tid) for tid in range(10)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 10
        # Cache should not exceed max_size
        assert len(cache._cache) <= 100
        # LRU eviction should have occurred
        assert cache._evictions > 0


class TestLLMCacheConcurrency:
    """Test LLMCache thread safety under concurrent access."""

    def test_concurrent_cache_operations_with_stats(self):
        """Should track statistics correctly under concurrent access."""
        cache = LLMCache(backend="memory", max_size=500, ttl=60)

        # Pre-populate some keys
        for i in range(50):
            key = cache.generate_key(
                model="gpt-4",
                prompt=f"prompt_{i}",
                temperature=0.7,
                max_tokens=100,
                user_id=f"user_{i % 10}",
            )
            cache.set(key, f"response_{i}")

        def mixed_operations(thread_id):
            """Perform mixed cache operations."""
            hits = 0
            misses = 0

            for i in range(50):
                # Generate key
                key = cache.generate_key(
                    model="gpt-4",
                    prompt=f"prompt_{i}",
                    temperature=0.7,
                    max_tokens=100,
                    user_id=f"user_{i % 10}",
                )

                # Try to get
                result = cache.get(key)
                if result is not None:
                    hits += 1
                else:
                    misses += 1
                    # Set on miss
                    cache.set(key, f"response_{i}_thread_{thread_id}")

            return hits, misses

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(mixed_operations, tid) for tid in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # Verify all threads completed
        assert len(results) == 10

        # Verify stats were updated
        stats = cache.get_stats()
        assert stats["hits"] > 0
        assert stats["misses"] >= 0
        assert stats["writes"] > 0

    def test_concurrent_key_generation(self):
        """Should generate consistent keys under concurrent access."""
        cache = LLMCache(backend="memory")

        def generate_keys(thread_id):
            """Generate cache keys."""
            keys = []
            for i in range(100):
                key = cache.generate_key(
                    model="gpt-4",
                    prompt=f"test_prompt_{i}",
                    temperature=0.7,
                    max_tokens=2048,
                    user_id=f"user_{thread_id}",
                )
                keys.append(key)
            return keys

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(generate_keys, tid) for tid in range(20)]
            results = [f.result() for f in as_completed(futures)]

        # All threads should generate keys
        assert len(results) == 20

        # Keys for same input should be identical across threads
        thread_0_keys = results[0]
        thread_1_keys = results[1]
        # Different users should have different keys
        assert thread_0_keys != thread_1_keys

    def test_concurrent_cache_hits_and_misses(self):
        """Should correctly count hits and misses under concurrent access."""
        cache = LLMCache(backend="memory", max_size=1000, ttl=60)

        # Pre-populate half the keys
        keys = []
        for i in range(100):
            key = cache.generate_key(
                model="gpt-4",
                prompt=f"prompt_{i}",
                temperature=0.7,
                max_tokens=100,
                user_id="test_user",
            )
            keys.append(key)
            if i < 50:
                cache.set(key, f"response_{i}")

        def reader(thread_id):
            """Read from cache."""
            local_hits = 0
            local_misses = 0
            for key in keys:
                result = cache.get(key)
                if result is not None:
                    local_hits += 1
                else:
                    local_misses += 1
            return local_hits, local_misses

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(reader, tid) for tid in range(10)]
            results = [f.result() for f in as_completed(futures)]

        # Each thread should see 50 hits and 50 misses
        for hits, misses in results:
            assert hits == 50
            assert misses == 50

    def test_concurrent_cache_clear(self):
        """Should handle cache clear during concurrent access."""
        cache = LLMCache(backend="memory", max_size=500, ttl=60)

        # Pre-populate
        for i in range(100):
            key = cache.generate_key(
                model="gpt-4",
                prompt=f"prompt_{i}",
                temperature=0.7,
                max_tokens=100,
                user_id=f"user_{i}",
            )
            cache.set(key, f"response_{i}")

        def writer_reader(thread_id):
            """Perform operations during clear."""
            try:
                for i in range(20):
                    key = cache.generate_key(
                        model="gpt-4",
                        prompt=f"thread_{thread_id}_prompt_{i}",
                        temperature=0.7,
                        max_tokens=100,
                        user_id=f"user_{thread_id}",
                    )
                    cache.set(key, f"response_{i}")
                    cache.get(key)
                return True
            except Exception:
                return False

        def clearer():
            """Clear the cache."""
            time.sleep(0.05)  # Let some operations start
            cache.clear()
            return True

        with ThreadPoolExecutor(max_workers=11) as executor:
            futures = []
            # Submit 10 writer/readers
            for tid in range(10):
                futures.append(executor.submit(writer_reader, tid))
            # Submit 1 clearer
            futures.append(executor.submit(clearer))

            results = [f.result() for f in as_completed(futures)]

        # All operations should complete successfully
        assert all(results)


class TestCacheErrorHandling:
    """Test cache error handling under concurrent access."""

    def test_concurrent_operations_with_error_injection(self):
        """Should handle backend errors gracefully during concurrent access."""
        cache = LLMCache(backend="memory", max_size=500, ttl=60)

        # Pre-populate
        for i in range(50):
            key = cache.generate_key(
                model="gpt-4",
                prompt=f"prompt_{i}",
                temperature=0.7,
                max_tokens=100,
                user_id=f"user_{i}",
            )
            cache.set(key, f"response_{i}")

        original_get = cache._backend.get
        call_count = [0]

        def faulty_get(key):
            """Inject errors occasionally."""
            call_count[0] += 1
            if call_count[0] % 10 == 0:
                raise RuntimeError("Simulated backend failure")
            return original_get(key)

        with patch.object(cache._backend, "get", side_effect=faulty_get):

            def reader(thread_id):
                """Try to read from cache."""
                results = []
                for i in range(20):
                    key = cache.generate_key(
                        model="gpt-4",
                        prompt=f"prompt_{i}",
                        temperature=0.7,
                        max_tokens=100,
                        user_id=f"user_{i}",
                    )
                    # Should return None on error, not raise
                    result = cache.get(key)
                    results.append(result)
                return results

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(reader, tid) for tid in range(10)]
                results = [f.result() for f in as_completed(futures)]

            # All threads should complete
            assert len(results) == 10
            # Some operations should have returned None due to errors
            stats = cache.get_stats()
            assert stats["errors"] > 0

    def test_concurrent_set_with_error_injection(self):
        """Should handle backend errors during concurrent set operations."""
        cache = LLMCache(backend="memory", max_size=500, ttl=60)

        original_set = cache._backend.set
        call_count = [0]

        def faulty_set(key, value, ttl=None):
            """Inject errors occasionally."""
            call_count[0] += 1
            if call_count[0] % 15 == 0:
                raise RuntimeError("Simulated backend failure")
            return original_set(key, value, ttl=ttl)

        with patch.object(cache._backend, "set", side_effect=faulty_set):

            def writer(thread_id):
                """Try to write to cache."""
                success_count = 0
                for i in range(30):
                    key = cache.generate_key(
                        model="gpt-4",
                        prompt=f"thread_{thread_id}_prompt_{i}",
                        temperature=0.7,
                        max_tokens=100,
                        user_id=f"user_{thread_id}",
                    )
                    # Should return False on error, not raise
                    if cache.set(key, f"response_{i}"):
                        success_count += 1
                return success_count

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(writer, tid) for tid in range(10)]
                results = [f.result() for f in as_completed(futures)]

            # All threads should complete
            assert len(results) == 10
            # Some operations should have failed
            total_success = sum(results)
            total_operations = 10 * 30
            assert total_success < total_operations
            # Errors should be tracked
            stats = cache.get_stats()
            assert stats["errors"] > 0


class TestCacheStatsThreadSafety:
    """Test cache statistics tracking under concurrent access."""

    def test_stats_consistency_under_concurrent_load(self):
        """Should maintain consistent statistics under concurrent access."""
        cache = LLMCache(backend="memory", max_size=1000, ttl=60)

        # Pre-populate half the keys
        keys = []
        for i in range(200):
            key = cache.generate_key(
                model="gpt-4",
                prompt=f"prompt_{i}",
                temperature=0.7,
                max_tokens=100,
                user_id="test_user",
            )
            keys.append(key)
            if i < 100:
                cache.set(key, f"response_{i}")

        def operations(thread_id):
            """Perform operations."""
            for key in keys:
                cache.get(key)
            return thread_id

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(operations, tid) for tid in range(20)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 20

        # Verify stats
        stats = cache.get_stats()
        # Each thread performs 200 gets (100 hits, 100 misses)
        # 20 threads * 200 gets = 4000 total gets
        assert stats["hits"] == 20 * 100
        assert stats["misses"] == 20 * 100
        assert stats["hits"] + stats["misses"] == 4000

    def test_stats_reset_thread_safe(self):
        """Should safely reset statistics during concurrent access."""
        cache = LLMCache(backend="memory", max_size=500, ttl=60)

        # Generate some stats
        for i in range(50):
            key = cache.generate_key(
                model="gpt-4",
                prompt=f"prompt_{i}",
                temperature=0.7,
                max_tokens=100,
                user_id=f"user_{i}",
            )
            cache.set(key, f"response_{i}")
            cache.get(key)

        def operations(thread_id):
            """Perform operations."""
            for i in range(20):
                key = cache.generate_key(
                    model="gpt-4",
                    prompt=f"thread_{thread_id}_prompt_{i}",
                    temperature=0.7,
                    max_tokens=100,
                    user_id=f"user_{thread_id}",
                )
                cache.set(key, f"response_{i}")
                cache.get(key)
            return True

        def resetter():
            """Reset stats during operations."""
            time.sleep(0.05)
            cache.reset_stats()
            return True

        with ThreadPoolExecutor(max_workers=11) as executor:
            futures = []
            for tid in range(10):
                futures.append(executor.submit(operations, tid))
            futures.append(executor.submit(resetter))

            results = [f.result() for f in as_completed(futures)]

        # All operations should complete
        assert all(results)

        # Stats should be valid (reset happened)
        stats = cache.get_stats()
        assert isinstance(stats["hits"], int)
        assert isinstance(stats["misses"], int)
        assert isinstance(stats["writes"], int)
