"""
Tests for LLM response caching.

Tests cover:
- Cache key generation
- In-memory cache backend
- Redis cache backend (mocked)
- Cache hit/miss statistics
- TTL expiration
- LRU eviction
- Thread safety
- Integration with LLM providers
"""
import time
import hashlib
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from threading import Thread

from src.cache.llm_cache import (
    LLMCache,
    InMemoryCache,
    RedisCache,
    CacheStats,
    CacheBackend
)

# Check if redis is available
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_same_params_same_key(self):
        """Test that identical parameters produce identical keys."""
        cache = LLMCache()

        key1 = cache.generate_key(
            model="gpt-4",
            prompt="Hello world",
            temperature=0.7,
            max_tokens=2048
        )
        key2 = cache.generate_key(
            model="gpt-4",
            prompt="Hello world",
            temperature=0.7,
            max_tokens=2048
        )

        assert key1 == key2

    def test_different_prompt_different_key(self):
        """Test that different prompts produce different keys."""
        cache = LLMCache()

        key1 = cache.generate_key(model="gpt-4", prompt="Hello")
        key2 = cache.generate_key(model="gpt-4", prompt="Goodbye")

        assert key1 != key2

    def test_different_temperature_different_key(self):
        """Test that different temperatures produce different keys."""
        cache = LLMCache()

        key1 = cache.generate_key(model="gpt-4", prompt="Hello", temperature=0.7)
        key2 = cache.generate_key(model="gpt-4", prompt="Hello", temperature=0.9)

        assert key1 != key2

    def test_different_model_different_key(self):
        """Test that different models produce different keys."""
        cache = LLMCache()

        key1 = cache.generate_key(model="gpt-4", prompt="Hello")
        key2 = cache.generate_key(model="gpt-3.5-turbo", prompt="Hello")

        assert key1 != key2

    def test_additional_params_included(self):
        """Test that additional kwargs are included in key."""
        cache = LLMCache()

        key1 = cache.generate_key(model="gpt-4", prompt="Hello", top_p=0.9)
        key2 = cache.generate_key(model="gpt-4", prompt="Hello", top_p=0.95)

        assert key1 != key2

    def test_key_is_sha256_hex(self):
        """Test that key is a valid SHA-256 hex string."""
        cache = LLMCache()

        key = cache.generate_key(model="gpt-4", prompt="Hello")

        # Should be 64 characters (256 bits / 4 bits per hex char)
        assert len(key) == 64
        # Should be valid hex
        assert all(c in '0123456789abcdef' for c in key)


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

        assert stats['size'] == 2
        assert stats['max_size'] == 5
        assert stats['evictions'] == 0


@pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis package not installed")
class TestRedisCache:
    """Tests for Redis cache backend."""

    @patch('redis.Redis')
    def test_redis_connection(self, mock_redis_class):
        """Test Redis connection initialization."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client
        mock_client.ping.return_value = True

        cache = RedisCache(host="localhost", port=6379)

        mock_redis_class.assert_called_once()
        mock_client.ping.assert_called_once()

    @patch('redis.Redis')
    def test_redis_set_get(self, mock_redis_class):
        """Test Redis set and get operations."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client
        mock_client.ping.return_value = True
        mock_client.get.return_value = "cached_value"

        cache = RedisCache()
        cache.set("key1", "value1")
        result = cache.get("key1")

        mock_client.set.assert_called()
        mock_client.get.assert_called_with("key1")

    @patch('redis.Redis')
    def test_redis_ttl(self, mock_redis_class):
        """Test Redis TTL support."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client
        mock_client.ping.return_value = True

        cache = RedisCache()
        cache.set("key1", "value1", ttl=3600)

        # Should use setex for TTL
        mock_client.setex.assert_called_once_with("key1", 3600, "value1")

    @patch('redis.Redis')
    def test_redis_delete(self, mock_redis_class):
        """Test Redis delete operation."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client
        mock_client.ping.return_value = True
        mock_client.delete.return_value = 1

        cache = RedisCache()
        result = cache.delete("key1")

        assert result is True
        mock_client.delete.assert_called_with("key1")

    @patch('redis.Redis')
    def test_redis_clear(self, mock_redis_class):
        """Test Redis clear operation."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client
        mock_client.ping.return_value = True

        cache = RedisCache()
        cache.clear()

        mock_client.flushdb.assert_called_once()

    @patch('redis.Redis')
    @patch('redis.ConnectionError', Exception)
    def test_redis_connection_error(self, mock_conn_error, mock_redis_class):
        """Test Redis connection error handling."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client

        # Simulate connection error
        mock_client.ping.side_effect = Exception("Connection refused")

        with pytest.raises(ConnectionError, match="Failed to connect"):
            RedisCache()


class TestLLMCache:
    """Tests for LLM cache with different backends."""

    def test_memory_backend_cache_hit(self):
        """Test cache hit with memory backend."""
        cache = LLMCache(backend="memory", ttl=None)

        key = cache.generate_key(model="gpt-4", prompt="Hello")
        cache.set(key, "Hello! How can I help?")

        result = cache.get(key)

        assert result == "Hello! How can I help?"
        assert cache.stats.hits == 1
        assert cache.stats.misses == 0

    def test_memory_backend_cache_miss(self):
        """Test cache miss with memory backend."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello")
        result = cache.get(key)

        assert result is None
        assert cache.stats.hits == 0
        assert cache.stats.misses == 1

    def test_ttl_expiration_integration(self):
        """Test TTL expiration in LLMCache."""
        cache = LLMCache(backend="memory", ttl=1)

        key = cache.generate_key(model="gpt-4", prompt="Hello")
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

        key1 = cache.generate_key(model="gpt-4", prompt="Hello")
        key2 = cache.generate_key(model="gpt-4", prompt="Goodbye")

        # Miss
        cache.get(key1)

        # Write
        cache.set(key1, "Response 1")

        # Hit
        cache.get(key1)

        # Miss
        cache.get(key2)

        stats = cache.get_stats()

        assert stats['hits'] == 1
        assert stats['misses'] == 2
        assert stats['writes'] == 1
        assert stats['hit_rate'] == 1/3

    def test_reset_stats(self):
        """Test resetting cache statistics."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello")
        cache.get(key)

        assert cache.stats.misses == 1

        cache.reset_stats()

        assert cache.stats.misses == 0
        assert cache.stats.hits == 0

    def test_unknown_backend_raises(self):
        """Test that unknown backend raises ValueError."""
        with pytest.raises(ValueError, match="Unknown cache backend"):
            LLMCache(backend="invalid")

    @pytest.mark.skipif(not REDIS_AVAILABLE, reason="redis package not installed")
    @patch('redis.Redis')
    def test_redis_backend_initialization(self, mock_redis_class):
        """Test Redis backend initialization."""
        mock_client = MagicMock()
        mock_redis_class.return_value = mock_client
        mock_client.ping.return_value = True

        cache = LLMCache(
            backend="redis",
            redis_host="localhost",
            redis_port=6379,
            redis_db=1,
            redis_password="secret"
        )

        mock_redis_class.assert_called_once()

    def test_cache_exists(self):
        """Test checking if key exists in cache."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello")

        assert not cache.exists(key)

        cache.set(key, "Response")

        assert cache.exists(key)

    def test_cache_delete(self):
        """Test deleting from cache."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Hello")
        cache.set(key, "Response")

        assert cache.exists(key)

        cache.delete(key)

        assert not cache.exists(key)

    def test_cache_clear(self):
        """Test clearing entire cache."""
        cache = LLMCache(backend="memory")

        key1 = cache.generate_key(model="gpt-4", prompt="Hello")
        key2 = cache.generate_key(model="gpt-4", prompt="Goodbye")

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

        assert result['hits'] == 10
        assert result['misses'] == 5
        assert result['writes'] == 15
        assert result['errors'] == 1
        assert result['evictions'] == 2
        assert result['hit_rate'] == 10/15


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
            max_tokens=100
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
            max_tokens=100
        )

        result3 = cache.get(key2)
        assert result3 is None  # Miss

        # Check stats
        stats = cache.get_stats()
        assert stats['hits'] == 1
        assert stats['misses'] == 2
        assert stats['writes'] == 1

    def test_concurrent_cache_access(self):
        """Test concurrent access to cache."""
        cache = LLMCache(backend="memory", max_size=1000)

        def worker(thread_id):
            for i in range(50):
                key = cache.generate_key(
                    model=f"model-{thread_id}",
                    prompt=f"prompt-{i}",
                    temperature=0.7
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
        key = cache.generate_key(model="gpt-4", prompt=special_prompt)

        cache.set(key, "Response to special prompt")
        result = cache.get(key)

        assert result == "Response to special prompt"

    def test_large_response_caching(self):
        """Test caching large responses."""
        cache = LLMCache(backend="memory")

        key = cache.generate_key(model="gpt-4", prompt="Write a long essay")

        # Large response (10KB)
        large_response = "A" * 10240

        cache.set(key, large_response)
        result = cache.get(key)

        assert result == large_response
        assert len(result) == 10240
