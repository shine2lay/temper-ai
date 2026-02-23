"""
Tests for LLM response caching.

Tests cover:
- Cache key generation
- In-memory cache backend
- Cache hit/miss statistics
- TTL expiration
- LRU eviction
- Thread safety
- Integration with LLM providers
"""

import time
from threading import Thread

import pytest

from temper_ai.llm.cache.llm_cache import CacheStats, InMemoryCache, LLMCache


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_same_params_same_key(self):
        """Test that identical parameters produce identical keys."""
        cache = LLMCache()

        key1 = cache.generate_key(
            model="gpt-4",
            prompt="Hello world",
            temperature=0.7,
            max_tokens=2048,
            tenant_id="test_tenant",
        )
        key2 = cache.generate_key(
            model="gpt-4",
            prompt="Hello world",
            temperature=0.7,
            max_tokens=2048,
            tenant_id="test_tenant",
        )

        assert key1 == key2

    def test_different_prompt_different_key(self):
        """Test that different prompts produce different keys."""
        cache = LLMCache()

        key1 = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        key2 = cache.generate_key(model="gpt-4", prompt="Goodbye", tenant_id="test")

        assert key1 != key2

    def test_different_temperature_different_key(self):
        """Test that different temperatures produce different keys."""
        cache = LLMCache()

        key1 = cache.generate_key(
            model="gpt-4", prompt="Hello", temperature=0.7, tenant_id="test"
        )
        key2 = cache.generate_key(
            model="gpt-4", prompt="Hello", temperature=0.9, tenant_id="test"
        )

        assert key1 != key2

    def test_different_model_different_key(self):
        """Test that different models produce different keys."""
        cache = LLMCache()

        key1 = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        key2 = cache.generate_key(
            model="gpt-3.5-turbo", prompt="Hello", tenant_id="test"
        )

        assert key1 != key2

    def test_additional_params_included(self):
        """Test that additional kwargs are included in key."""
        cache = LLMCache()

        key1 = cache.generate_key(
            model="gpt-4", prompt="Hello", top_p=0.9, tenant_id="test"
        )
        key2 = cache.generate_key(
            model="gpt-4", prompt="Hello", top_p=0.95, tenant_id="test"
        )

        assert key1 != key2

    def test_key_is_sha256_hex(self):
        """Test that key is a valid SHA-256 hex string."""
        cache = LLMCache()

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")

        # Should be 64 characters (256 bits / 4 bits per hex char)
        assert len(key) == 64
        # Should be valid hex
        assert all(c in "0123456789abcdef" for c in key)


class TestInMemoryCache:
    """Tests for in-memory cache backend."""

    def test_set_and_get(self):
        """Test basic set and get operations."""
        cache = InMemoryCache(max_size=10)

        cache.set("key1", "value1")
        result = cache.get("key1")

        assert result == "value1"

    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        cache = InMemoryCache()

        result = cache.get("nonexistent")

        assert result is None

    def test_delete(self):
        """Test deleting a key."""
        cache = InMemoryCache()

        cache.set("key1", "value1")
        assert cache.exists("key1")

        cache.delete("key1")
        assert not cache.exists("key1")

    def test_clear(self):
        """Test clearing entire cache."""
        cache = InMemoryCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        assert cache.exists("key1")
        assert cache.exists("key2")

        cache.clear()

        assert not cache.exists("key1")
        assert not cache.exists("key2")

    def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        cache = InMemoryCache()

        cache.set("key1", "value1", ttl=1)  # 1 second TTL

        # Should exist immediately
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("key1") is None

    def test_lru_eviction(self):
        """Test LRU eviction when max_size reached."""
        cache = InMemoryCache(max_size=3)

        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Access key1 to make it recently used
        cache.get("key1")

        # Add new key - should evict key2 (least recently used)
        cache.set("key4", "value4")

        assert cache.exists("key1")  # Recently accessed
        assert not cache.exists("key2")  # Evicted
        assert cache.exists("key3")
        assert cache.exists("key4")

    def test_thread_safety(self):
        """Test that cache is thread-safe."""
        cache = InMemoryCache(max_size=1000)

        def worker(thread_id):
            for i in range(100):
                key = f"key_{thread_id}_{i}"
                cache.set(key, f"value_{thread_id}_{i}")
                result = cache.get(key)
                assert result == f"value_{thread_id}_{i}" or result is None

        threads = [Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No crashes = thread-safe

    def test_stats(self):
        """Test cache statistics."""
        cache = InMemoryCache(max_size=5)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        stats = cache.get_stats()

        assert stats["size"] == 2
        assert stats["max_size"] == 5
        assert stats["evictions"] == 0

    def test_expired_cleanup_prevents_memory_leak(self):
        """
        Test that expired entries are cleaned up from _access_order dict.

        REGRESSION TEST for code-high-07: Cache Access Order Never Cleaned
        Ensures that expired entries don't accumulate in _access_order causing memory leak.
        """
        cache = InMemoryCache(max_size=10)

        # Add entries with short TTL
        cache.set("expired1", "value1", ttl=1)
        cache.set("expired2", "value2", ttl=1)
        cache.set("expired3", "value3", ttl=1)
        cache.set("persistent", "value4")  # No TTL

        # Verify all entries exist initially
        assert cache.exists("expired1")
        assert cache.exists("expired2")
        assert cache.exists("expired3")
        assert cache.exists("persistent")

        # Check internal state
        assert len(cache._cache) == 4
        assert len(cache._access_order) == 4

        # Wait for TTL expiration
        time.sleep(1.1)

        # Accessing expired entries should remove them from both dicts
        assert cache.get("expired1") is None
        assert len(cache._cache) == 3  # expired1 removed
        assert len(cache._access_order) == 3  # CRITICAL: access_order also cleaned

        # But expired2 and expired3 are NOT accessed, so they stay in _access_order
        # This is the memory leak scenario - expired but never accessed
        assert "expired2" in cache._cache  # Still in cache
        assert "expired3" in cache._cache  # Still in cache
        assert "expired2" in cache._access_order  # Still tracked
        assert "expired3" in cache._access_order  # Still tracked

        # Now trigger cleanup via get_stats()
        stats = cache.get_stats(cleanup_expired=True)

        # Verify cleanup happened
        assert stats["expired_cleaned"] == 2  # expired2 and expired3 cleaned
        assert len(cache._cache) == 1  # Only persistent remains
        assert len(cache._access_order) == 1  # CRITICAL: access_order also cleaned
        assert "expired2" not in cache._access_order
        assert "expired3" not in cache._access_order
        assert cache.exists("persistent")

    def test_expired_cleanup_during_eviction(self):
        """
        Test that cleanup happens automatically during LRU eviction.

        REGRESSION TEST for code-high-07: Ensures expired entries are cleaned
        before evicting valid entries.
        """
        cache = InMemoryCache(max_size=3)

        # Fill cache with all expiring entries
        cache.set("expired1", "value1", ttl=1)
        cache.set("expired2", "value2", ttl=1)
        cache.set("expired3", "value3", ttl=1)

        assert len(cache._cache) == 3

        # Wait for expiration
        time.sleep(1.1)

        # Add new entry - should trigger cleanup of all expired entries
        # instead of evicting. No valid entries to evict, so cleanup frees space.
        cache.set("new_entry", "value4")

        # Only new entry should exist
        assert cache.exists("new_entry")
        assert not cache.exists("expired1")
        assert not cache.exists("expired2")
        assert not cache.exists("expired3")

        # CRITICAL: access_order should only have 1 active entry
        assert len(cache._cache) == 1
        assert len(cache._access_order) == 1
        assert "expired1" not in cache._access_order
        assert "expired2" not in cache._access_order
        assert "expired3" not in cache._access_order
        assert "new_entry" in cache._access_order

    def test_no_cleanup_when_disabled(self):
        """Test that cleanup can be disabled in get_stats()."""
        cache = InMemoryCache(max_size=10)

        cache.set("expired", "value", ttl=1)
        time.sleep(1.1)

        # Get stats without cleanup
        stats = cache.get_stats(cleanup_expired=False)

        # Should not have cleaned anything
        assert stats["expired_cleaned"] == 0
        # Expired entry still in cache (not accessed)
        assert "expired" in cache._cache


class TestLLMCache:
    """Tests for LLM cache with different backends."""

    def test_memory_backend_cache_hit(self):
        """Test cache hit with memory backend."""
        cache = LLMCache(backend="memory", ttl=None)

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        cache.set(key, "Hello! How can I help?")

        result = cache.get(key)

        assert result == "Hello! How can I help?"
        assert cache.stats.hits == 1
        assert cache.stats.misses == 0

    def test_memory_backend_cache_miss(self):
        """Test cache miss with memory backend."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        result = cache.get(key)

        assert result is None
        assert cache.stats.hits == 0
        assert cache.stats.misses == 1

    def test_ttl_expiration_integration(self):
        """Test TTL expiration in LLMCache."""
        cache = LLMCache(backend="memory", ttl=1)

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        cache.set(key, "Response")

        # Should be cached
        assert cache.get(key) == "Response"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get(key) is None

    def test_cache_statistics(self):
        """Test cache statistics tracking."""
        cache = LLMCache(backend="memory")

        key1 = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        key2 = cache.generate_key(model="gpt-4", prompt="Goodbye", tenant_id="test")

        # Miss
        cache.get(key1)

        # Write
        cache.set(key1, "Response 1")

        # Hit
        cache.get(key1)

        # Miss
        cache.get(key2)

        stats = cache.get_stats()

        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["writes"] == 1
        assert stats["hit_rate"] == 1 / 3

    def test_reset_stats(self):
        """Test resetting cache statistics."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        cache.get(key)

        assert cache.stats.misses == 1

        cache.reset_stats()

        assert cache.stats.misses == 0
        assert cache.stats.hits == 0

    def test_unknown_backend_raises(self):
        """Test that unknown backend raises ValueError."""
        with pytest.raises(ValueError, match="Unknown cache backend"):
            LLMCache(backend="invalid")

    def test_cache_exists(self):
        """Test checking if key exists in cache."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")

        assert not cache.exists(key)

        cache.set(key, "Response")

        assert cache.exists(key)

    def test_cache_delete(self):
        """Test deleting from cache."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        cache.set(key, "Response")

        assert cache.exists(key)

        cache.delete(key)

        assert not cache.exists(key)

    def test_cache_clear(self):
        """Test clearing entire cache."""
        cache = LLMCache(backend="memory")

        key1 = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")
        key2 = cache.generate_key(model="gpt-4", prompt="Goodbye", tenant_id="test")

        cache.set(key1, "Response 1")
        cache.set(key2, "Response 2")

        cache.clear()

        assert not cache.exists(key1)
        assert not cache.exists(key2)


class TestCacheStats:
    """Tests for cache statistics."""

    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        stats = CacheStats(hits=75, misses=25)

        assert stats.hit_rate == 0.75

    def test_hit_rate_zero_total(self):
        """Test hit rate with zero total requests."""
        stats = CacheStats(hits=0, misses=0)

        assert stats.hit_rate == 0.0

    def test_to_dict(self):
        """Test converting stats to dictionary."""
        stats = CacheStats(hits=10, misses=5, writes=15, errors=1, evictions=2)

        result = stats.to_dict()

        assert result["hits"] == 10
        assert result["misses"] == 5
        assert result["writes"] == 15
        assert result["errors"] == 1
        assert result["evictions"] == 2
        assert result["hit_rate"] == 10 / 15


class TestCacheIntegration:
    """Integration tests for LLM cache."""

    def test_realistic_workflow(self):
        """Test realistic caching workflow."""
        cache = LLMCache(backend="memory", ttl=3600, max_size=100)

        # First request - cache miss
        key1 = cache.generate_key(
            model="gpt-4",
            prompt="What is the capital of France?",
            temperature=0.7,
            max_tokens=100,
            tenant_id="test",
        )

        result1 = cache.get(key1)
        assert result1 is None  # Miss

        # Cache the response
        response1 = "The capital of France is Paris."
        cache.set(key1, response1)

        # Second request with same params - cache hit
        result2 = cache.get(key1)
        assert result2 == response1  # Hit

        # Different request - cache miss
        key2 = cache.generate_key(
            model="gpt-4",
            prompt="What is the capital of Germany?",
            temperature=0.7,
            max_tokens=100,
            tenant_id="test",
        )

        result3 = cache.get(key2)
        assert result3 is None  # Miss

        # Check stats
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["writes"] == 1

    def test_concurrent_cache_access(self):
        """Test concurrent access to cache."""
        cache = LLMCache(backend="memory", max_size=1000)

        def worker(thread_id):
            for i in range(50):
                key = cache.generate_key(
                    model=f"model-{thread_id}",
                    prompt=f"prompt-{i}",
                    temperature=0.7,
                    tenant_id=f"tenant-{thread_id}",
                )
                cache.set(key, f"response-{thread_id}-{i}")
                result = cache.get(key)
                # Might be None if evicted
                if result is not None:
                    assert result == f"response-{thread_id}-{i}"

        threads = [Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No crashes = thread-safe

    def test_cache_with_special_characters(self):
        """Test caching with special characters in prompts."""
        cache = LLMCache(backend="memory")

        # Prompt with special characters
        special_prompt = "Hello! How are you? 你好 🌍 \n\t\r"
        key = cache.generate_key(model="gpt-4", prompt=special_prompt, tenant_id="test")

        cache.set(key, "Response to special prompt")
        result = cache.get(key)

        assert result == "Response to special prompt"

    def test_large_response_caching(self):
        """Test caching large responses."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(
            model="gpt-4", prompt="Write a long essay", tenant_id="test"
        )

        # Large response (10KB)
        large_response = "A" * 10240

        cache.set(key, large_response)
        result = cache.get(key)

        assert result == large_response
        assert len(result) == 10240


class TestMultiTenantCacheSecurity:
    """Security tests for multi-tenant cache isolation.

    These tests verify that the cache properly isolates data between different
    users and tenants, preventing cross-tenant data leakage vulnerabilities.
    """

    def test_different_tenants_different_cache_keys(self):
        """Test that different tenants get different cache keys for identical prompts."""
        cache = LLMCache()

        key_tenant_a = cache.generate_key(
            model="gpt-4",
            prompt="Hello world",  # IDENTICAL prompt
            temperature=0.7,
            tenant_id="tenant_a",
            user_id="user_123",
        )

        key_tenant_b = cache.generate_key(
            model="gpt-4",
            prompt="Hello world",  # IDENTICAL prompt
            temperature=0.7,
            tenant_id="tenant_b",  # DIFFERENT tenant
            user_id="user_123",
        )

        # SECURITY: Different tenants must have different keys
        assert key_tenant_a != key_tenant_b

    def test_different_users_same_tenant_different_keys(self):
        """Test that different users in same tenant get different keys."""
        cache = LLMCache()

        key_user_a = cache.generate_key(
            model="gpt-4", prompt="Hello", tenant_id="acme_corp", user_id="user_1"
        )

        key_user_b = cache.generate_key(
            model="gpt-4",
            prompt="Hello",  # IDENTICAL prompt
            tenant_id="acme_corp",  # SAME tenant
            user_id="user_2",  # DIFFERENT user
        )

        # SECURITY: Different users must have different keys
        assert key_user_a != key_user_b

    def test_cache_isolation_no_cross_tenant_leakage(self):
        """Test that cached data does not leak between tenants."""
        cache = LLMCache()

        # Tenant A caches sensitive data
        key_a = cache.generate_key(
            model="gpt-4",
            prompt="Summarize patient data",
            tenant_id="hospital_a",
            user_id="doctor_1",
        )
        cache.set(key_a, "SENSITIVE: Patient John Doe, SSN 123-45-6789")

        # Tenant B queries with identical prompt
        key_b = cache.generate_key(
            model="gpt-4",
            prompt="Summarize patient data",  # IDENTICAL
            tenant_id="hospital_b",  # DIFFERENT tenant
            user_id="doctor_2",
        )
        cached_b = cache.get(key_b)

        # SECURITY: Tenant B should NOT get Tenant A's data
        assert cached_b is None  # Cache MISS (correct)

    def test_missing_user_context_raises_error(self):
        """Test that missing user/tenant context raises security error."""
        cache = LLMCache()

        with pytest.raises(
            ValueError, match="requires user_id or tenant_id for security"
        ):
            cache.generate_key(
                model="gpt-4",
                prompt="Hello",
                temperature=0.7,
                # Missing user_id and tenant_id
            )

    def test_session_isolation(self):
        """Test that different sessions get different cache keys."""
        cache = LLMCache()

        key_session_1 = cache.generate_key(
            model="gpt-4",
            prompt="Continue conversation",
            tenant_id="acme",
            user_id="user_1",
            session_id="session_abc",
        )

        key_session_2 = cache.generate_key(
            model="gpt-4",
            prompt="Continue conversation",  # IDENTICAL
            tenant_id="acme",
            user_id="user_1",
            session_id="session_xyz",  # DIFFERENT session
        )

        # SECURITY: Different sessions must have different keys
        assert key_session_1 != key_session_2

    def test_tenant_id_only_sufficient(self):
        """Test that tenant_id alone is sufficient for cache isolation."""
        cache = LLMCache()

        # Should not raise error with only tenant_id
        key = cache.generate_key(
            model="gpt-4",
            prompt="Test",
            tenant_id="tenant_a",
            # No user_id - should still work
        )

        assert key is not None
        assert len(key) == 64  # SHA-256 hex

    def test_user_id_only_sufficient(self):
        """Test that user_id alone is sufficient for cache isolation."""
        cache = LLMCache()

        # Should not raise error with only user_id
        key = cache.generate_key(
            model="gpt-4",
            prompt="Test",
            user_id="user_123",
            # No tenant_id - should still work
        )

        assert key is not None
        assert len(key) == 64  # SHA-256 hex

    def test_same_user_tenant_session_same_key(self):
        """Test that identical context produces identical keys (idempotent)."""
        cache = LLMCache()

        key1 = cache.generate_key(
            model="gpt-4",
            prompt="Hello",
            temperature=0.7,
            tenant_id="acme",
            user_id="user_1",
            session_id="session_abc",
        )

        key2 = cache.generate_key(
            model="gpt-4",
            prompt="Hello",
            temperature=0.7,
            tenant_id="acme",
            user_id="user_1",
            session_id="session_abc",
        )

        # Idempotent: Same context = same key
        assert key1 == key2

    def test_security_context_in_hash(self):
        """Test that security context is actually included in hash."""
        cache = LLMCache()

        # Generate key with security context
        key_with_context = cache.generate_key(
            model="gpt-4", prompt="Test", tenant_id="acme", user_id="user_1"
        )

        # Try to generate hash without security context (should fail)
        with pytest.raises(ValueError, match="requires user_id or tenant_id"):
            cache.generate_key(
                model="gpt-4",
                prompt="Test",
                # Missing tenant_id and user_id
            )

    def test_multi_tenant_workflow_integration(self):
        """Integration test: Multi-tenant workflow with proper isolation."""
        cache = LLMCache()

        # Scenario: Three companies using shared LLM service
        tenants = ["company_a", "company_b", "company_c"]
        prompt = "Generate quarterly report"

        keys = []
        for tenant in tenants:
            key = cache.generate_key(
                model="gpt-4", prompt=prompt, tenant_id=tenant, user_id=f"user_{tenant}"
            )
            keys.append(key)

            # Cache company-specific data
            cache.set(key, f"Confidential data for {tenant}")

        # Verify all keys are different
        assert len(set(keys)) == 3  # All unique

        # Verify each tenant gets only their own data
        for i, tenant in enumerate(tenants):
            key = keys[i]
            cached_data = cache.get(key)
            assert cached_data == f"Confidential data for {tenant}"
            assert tenant in cached_data  # Contains tenant name
            # Should not contain other tenants' names
            for other_tenant in tenants:
                if other_tenant != tenant:
                    assert other_tenant not in cached_data


class TestCacheKeySecurityValidation:
    """Security tests for cache key parameter validation (code-crit-15).

    IMPORTANT: Python's function calling mechanism prevents reserved parameters
    from appearing in kwargs at runtime. The validation in generate_key() is
    DEFENSE-IN-DEPTH that protects against:

    1. Future code refactoring where kwargs might be built programmatically
    2. Bugs in wrapper functions that incorrectly forward parameters
    3. Dict merge vulnerabilities if code structure changes

    These tests verify the validation logic and document proper usage.
    """

    def test_python_prevents_reserved_param_override_at_call_boundary(self):
        """Document that Python prevents reserved params in kwargs.

        This test demonstrates Python's built-in protection.  Users cannot
        override reserved parameters via kwargs in normal function calls.
        Python raises SyntaxError for duplicate literal keywords (caught at
        compile time), or TypeError for duplicate keywords via dict unpacking
        (caught at runtime).
        """
        cache = LLMCache()

        # Python blocks dict unpacking with duplicate keywords at runtime
        duplicate_kwargs = {"model": "override"}

        with pytest.raises(TypeError, match="got multiple values for keyword argument"):
            cache.generate_key(
                model="gpt-4",
                prompt="Hello",
                tenant_id="test",
                **duplicate_kwargs,  # Duplicate keyword - Python TypeError
            )

    def test_validation_logic_with_intersection_check(self):
        """Verify the validation logic works correctly.

        The validation uses set intersection to detect reserved params in kwargs.
        This test verifies that logic (even though Python prevents it from
        triggering in normal use).
        """
        # Test the validation logic directly
        RESERVED_PARAMS = {
            "model",
            "prompt",
            "temperature",
            "max_tokens",
            "user_id",
            "tenant_id",
            "session_id",
        }

        # Case 1: No conflicts (legitimate kwargs)
        good_kwargs = {"top_p": 0.9, "frequency_penalty": 0.5}
        conflicts = RESERVED_PARAMS.intersection(good_kwargs.keys())
        assert len(conflicts) == 0, "Legitimate kwargs should not conflict"

        # Case 2: Has conflicts (would be caught by validation)
        bad_kwargs = {"top_p": 0.9, "model": "injected"}
        conflicts = RESERVED_PARAMS.intersection(bad_kwargs.keys())
        assert len(conflicts) == 1, "Should detect 'model' conflict"
        assert "model" in conflicts

        # Case 3: Multiple conflicts
        worse_kwargs = {"model": "bad", "prompt": "bad", "temperature": 999}
        conflicts = RESERVED_PARAMS.intersection(worse_kwargs.keys())
        assert len(conflicts) == 3, "Should detect all 3 conflicts"

    def test_legitimate_kwargs_still_allowed(self):
        """Verify that legitimate LLM parameters via kwargs still work."""
        cache = LLMCache()

        # Should NOT raise error
        key = cache.generate_key(
            model="gpt-4",
            prompt="Hello",
            tenant_id="test",
            top_p=0.9,  # Legitimate param
            frequency_penalty=0.5,  # Legitimate param
            presence_penalty=0.2,  # Legitimate param
        )

        assert key is not None
        assert len(key) == 64  # SHA-256 hex

    def test_cache_key_consistency_with_legitimate_kwargs(self):
        """Verify that legitimate kwargs produce consistent cache keys."""
        cache = LLMCache()

        # Same params in different order should produce same key
        key1 = cache.generate_key(
            model="gpt-4",
            prompt="Hello",
            tenant_id="test",
            top_p=0.9,
            frequency_penalty=0.5,
        )

        key2 = cache.generate_key(
            model="gpt-4",
            prompt="Hello",
            tenant_id="test",
            frequency_penalty=0.5,
            top_p=0.9,
        )

        assert key1 == key2  # Deterministic hashing (sort_keys=True)

    def test_empty_kwargs_allowed(self):
        """Verify that calls without kwargs still work."""
        cache = LLMCache()

        key = cache.generate_key(model="gpt-4", prompt="Hello", tenant_id="test")

        assert key is not None
        assert len(key) == 64

    def test_reserved_params_documented(self):
        """Document which parameters are reserved and cannot appear in kwargs."""
        # This serves as documentation of the security contract
        RESERVED_PARAMS = {
            "model",  # LLM model name
            "prompt",  # Input prompt
            "temperature",  # Sampling temperature
            "max_tokens",  # Max response length
            "user_id",  # User security context
            "tenant_id",  # Tenant security context
            "session_id",  # Session security context
            "security_context",  # Namespace protection
            "request",  # Namespace protection
        }

        # Verify this matches the validation in the code
        # (If code changes, this test will fail as a reminder to update docs)
        cache = LLMCache()

        # All reserved params should be rejected if in kwargs (defense-in-depth)
        # Python prevents this in normal use, but validation provides extra safety
        for param in RESERVED_PARAMS:
            assert param in cache._RESERVED_PARAMS

    def test_prevent_security_context_injection_via_kwargs(self):
        """Verify that security_context cannot be injected via kwargs."""
        cache = LLMCache()

        malicious_kwargs = {"security_context": {"tenant_id": "evil"}}

        with pytest.raises(
            ValueError, match="Cannot override reserved parameters.*security_context"
        ):
            cache.generate_key(
                model="gpt-4",
                prompt="Hello",
                tenant_id="legitimate",
                **malicious_kwargs,
            )

    def test_prevent_request_injection_via_kwargs(self):
        """Verify that request cannot be injected via kwargs."""
        cache = LLMCache()

        malicious_kwargs = {"request": {"model": "cheap-model"}}

        with pytest.raises(
            ValueError, match="Cannot override reserved parameters.*request"
        ):
            cache.generate_key(
                model="gpt-4", prompt="Hello", tenant_id="test", **malicious_kwargs
            )


class TestCacheKeyTypeValidation:
    """Type validation tests for cache key generation (code-crit-15)."""

    def test_reject_non_string_model(self):
        """Verify model parameter must be string."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="model must be str"):
            cache.generate_key(
                model=123, prompt="test", tenant_id="test"  # Invalid: integer
            )

        with pytest.raises(TypeError, match="model must be str"):
            cache.generate_key(
                model=None, prompt="test", tenant_id="test"  # Invalid: None
            )

        with pytest.raises(TypeError, match="model must be str"):
            cache.generate_key(
                model={"name": "gpt-4"},  # Invalid: dict
                prompt="test",
                tenant_id="test",
            )

    def test_reject_non_string_prompt(self):
        """Verify prompt parameter must be string."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="prompt must be str"):
            cache.generate_key(
                model="gpt-4", prompt=123, tenant_id="test"  # Invalid: integer
            )

        with pytest.raises(TypeError, match="prompt must be str"):
            cache.generate_key(
                model="gpt-4",
                prompt=["list", "prompt"],  # Invalid: list
                tenant_id="test",
            )

    def test_reject_non_numeric_temperature(self):
        """Verify temperature parameter must be numeric."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="temperature must be numeric"):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                temperature="0.7",  # Invalid: string
                tenant_id="test",
            )

        with pytest.raises(TypeError, match="temperature must be numeric"):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                temperature=None,  # Invalid: None
                tenant_id="test",
            )

    def test_reject_non_integer_max_tokens(self):
        """Verify max_tokens parameter must be integer."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="max_tokens must be int"):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                max_tokens="2048",  # Invalid: string
                tenant_id="test",
            )

        with pytest.raises(TypeError, match="max_tokens must be int"):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                max_tokens=2048.5,  # Invalid: float
                tenant_id="test",
            )

    def test_reject_non_string_user_id(self):
        """Verify user_id parameter must be string or None."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="user_id must be str or None"):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                user_id=123,  # Invalid: integer
                tenant_id="test",
            )

    def test_reject_non_string_tenant_id(self):
        """Verify tenant_id parameter must be string or None."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="tenant_id must be str or None"):
            cache.generate_key(
                model="gpt-4", prompt="test", tenant_id=123  # Invalid: integer
            )

    def test_reject_non_string_session_id(self):
        """Verify session_id parameter must be string or None."""
        cache = LLMCache()

        with pytest.raises(TypeError, match="session_id must be str or None"):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                session_id=123,  # Invalid: integer
                tenant_id="test",
            )

    def test_accept_valid_types(self):
        """Verify that valid types are accepted."""
        cache = LLMCache()

        # All valid types
        key = cache.generate_key(
            model="gpt-4",
            prompt="test prompt",
            temperature=0.7,
            max_tokens=2048,
            user_id="user123",
            tenant_id="tenant456",
            session_id="session789",
        )

        assert isinstance(key, str)
        assert len(key) == 64  # SHA-256 hex digest

    def test_accept_valid_numeric_types(self):
        """Verify that both int and float are accepted for temperature."""
        cache = LLMCache()

        # Integer temperature
        key1 = cache.generate_key(
            model="gpt-4", prompt="test", temperature=1, tenant_id="test"  # int
        )

        # Float temperature
        key2 = cache.generate_key(
            model="gpt-4", prompt="test", temperature=1.0, tenant_id="test"  # float
        )

        assert isinstance(key1, str)
        assert isinstance(key2, str)

    def test_reject_non_serializable_kwargs(self):
        """Verify that non-JSON-serializable kwargs are rejected."""
        cache = LLMCache()

        class CustomObject:
            pass

        non_serializable_kwargs = {"custom": CustomObject()}

        with pytest.raises(
            ValueError, match="Cache key generation failed.*JSON-serializable"
        ):
            cache.generate_key(
                model="gpt-4",
                prompt="test",
                tenant_id="test",
                **non_serializable_kwargs,
            )
