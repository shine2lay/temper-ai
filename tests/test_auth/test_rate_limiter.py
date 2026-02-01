"""Tests for OAuth rate limiting."""
import pytest
import asyncio
import time
from src.auth.oauth.rate_limiter import (
    SlidingWindowRateLimiter,
    OAuthRateLimiter,
    RateLimitExceeded
)


class TestSlidingWindowRateLimiter:
    """Tests for sliding window rate limiter."""

    def test_within_limit(self):
        """Requests within limit should be allowed."""
        limiter = SlidingWindowRateLimiter()

        # 10 requests should all succeed
        for i in range(10):
            limiter.check_limit("test", "identifier_1", max_requests=10, window_seconds=60)

    def test_exceeds_limit(self):
        """Requests exceeding limit should raise RateLimitExceeded."""
        limiter = SlidingWindowRateLimiter()

        # First 5 requests succeed
        for i in range(5):
            limiter.check_limit("test", "identifier_1", max_requests=5, window_seconds=60)

        # 6th request should fail
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_limit("test", "identifier_1", max_requests=5, window_seconds=60)

        assert exc_info.value.retry_after > 0

    def test_sliding_window_expiry(self):
        """Old requests should expire from the sliding window."""
        limiter = SlidingWindowRateLimiter()

        # Make 3 requests
        for i in range(3):
            limiter.check_limit("test", "identifier_1", max_requests=3, window_seconds=2)

        # Should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("test", "identifier_1", max_requests=3, window_seconds=2)

        # Wait for window to expire
        time.sleep(3)

        # Should be able to make requests again (old ones expired)
        limiter.check_limit("test", "identifier_1", max_requests=3, window_seconds=2)

    def test_different_identifiers_independent(self):
        """Different identifiers should have independent limits."""
        limiter = SlidingWindowRateLimiter()

        # Fill limit for identifier_1
        for i in range(5):
            limiter.check_limit("test", "identifier_1", max_requests=5, window_seconds=60)

        # identifier_1 should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("test", "identifier_1", max_requests=5, window_seconds=60)

        # identifier_2 should still be able to make requests
        for i in range(5):
            limiter.check_limit("test", "identifier_2", max_requests=5, window_seconds=60)

    def test_different_limit_types_independent(self):
        """Different limit types should be independent."""
        limiter = SlidingWindowRateLimiter()

        # Fill limit for type_a
        for i in range(5):
            limiter.check_limit("type_a", "identifier_1", max_requests=5, window_seconds=60)

        # type_a should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit("type_a", "identifier_1", max_requests=5, window_seconds=60)

        # type_b should still be available
        for i in range(5):
            limiter.check_limit("type_b", "identifier_1", max_requests=5, window_seconds=60)

    def test_get_remaining(self):
        """Should accurately report remaining requests."""
        limiter = SlidingWindowRateLimiter()

        # No requests yet
        remaining, reset_after = limiter.get_remaining("test", "id_1", 10, 60)
        assert remaining == 10

        # Make 3 requests
        for i in range(3):
            limiter.check_limit("test", "id_1", max_requests=10, window_seconds=60)

        # Should have 7 remaining
        remaining, reset_after = limiter.get_remaining("test", "id_1", 10, 60)
        assert remaining == 7
        assert reset_after > 0

        # Make 7 more requests
        for i in range(7):
            limiter.check_limit("test", "id_1", max_requests=10, window_seconds=60)

        # Should have 0 remaining
        remaining, reset_after = limiter.get_remaining("test", "id_1", 10, 60)
        assert remaining == 0

    def test_cleanup(self):
        """Cleanup should remove old rate limit data."""
        limiter = SlidingWindowRateLimiter()

        # Make requests with short TTL
        for i in range(3):
            limiter.check_limit("test", "id_1", max_requests=10, window_seconds=1)

        # Internal state should have data
        assert "test" in limiter._windows
        assert "id_1" in limiter._windows["test"]

        # Wait for window to expire
        time.sleep(2)

        # Cleanup old data
        limiter.cleanup(older_than_seconds=1)

        # Data should be cleaned up
        assert "id_1" not in limiter._windows.get("test", {})


class TestOAuthRateLimiter:
    """Tests for OAuth-specific rate limiter."""

    def test_oauth_init_rate_limiting(self):
        """Should enforce rate limits on OAuth initiation."""
        limiter = OAuthRateLimiter()

        # Make requests up to IP limit (10 per minute)
        for i in range(10):
            limiter.check_oauth_init("192.168.1.1", f"user_{i}")

        # 11th request from same IP should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_oauth_init("192.168.1.1", "user_11")

    def test_oauth_init_user_rate_limiting(self):
        """Should enforce per-user rate limits."""
        limiter = OAuthRateLimiter()

        # Make requests up to user limit (5 per minute)
        for i in range(5):
            limiter.check_oauth_init(f"192.168.1.{i}", "user_same")

        # 6th request from same user (different IP) should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_oauth_init("192.168.1.99", "user_same")

    def test_oauth_init_global_rate_limiting(self):
        """Should enforce global rate limits."""
        limiter = OAuthRateLimiter()

        # Mock lower global limit for testing
        limiter.limits["oauth_init_global"] = (20, 60)  # 20 per minute instead of 1000/hour

        # Make 20 requests from different IPs and users
        for i in range(20):
            limiter.check_oauth_init(f"192.168.1.{i % 256}", f"user_{i}")

        # 21st request should fail (global limit)
        with pytest.raises(RateLimitExceeded):
            limiter.check_oauth_init("10.0.0.1", "unique_user")

    def test_token_exchange_rate_limiting(self):
        """Should enforce rate limits on token exchange."""
        limiter = OAuthRateLimiter()

        # Make requests up to IP limit (5 per minute)
        for i in range(5):
            limiter.check_token_exchange("192.168.1.1")

        # 6th request from same IP should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_token_exchange("192.168.1.1")

    def test_userinfo_rate_limiting(self):
        """Should enforce rate limits on user info retrieval."""
        limiter = OAuthRateLimiter()

        # Make requests up to user limit (60 per minute)
        for i in range(60):
            limiter.check_userinfo("user_123")

        # 61st request should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_userinfo("user_123")

    def test_different_operations_independent(self):
        """Rate limits for different operations should be independent."""
        limiter = OAuthRateLimiter()

        # Fill OAuth init limit for IP
        for i in range(10):
            limiter.check_oauth_init("192.168.1.1", f"user_{i}")

        # OAuth init should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_oauth_init("192.168.1.1", "user_another")

        # But token exchange should still work (different limit)
        for i in range(5):
            limiter.check_token_exchange("192.168.1.1")

    def test_rate_limit_error_message(self):
        """RateLimitExceeded should have helpful error message."""
        limiter = OAuthRateLimiter()

        # Fill limit
        for i in range(10):
            limiter.check_oauth_init("192.168.1.1", f"user_{i}")

        # Should get detailed error
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_oauth_init("192.168.1.1", "user_11")

        error = exc_info.value
        assert "Rate limit exceeded" in str(error)
        assert error.retry_after > 0
        assert error.retry_after <= 60  # Should be within window

    def test_concurrent_requests(self):
        """Rate limiting should be thread-safe."""
        import threading

        limiter = OAuthRateLimiter()
        results = {"success": 0, "failed": 0}
        lock = threading.Lock()

        def make_request(i):
            try:
                limiter.check_oauth_init("192.168.1.1", f"user_{i}")
                with lock:
                    results["success"] += 1
            except RateLimitExceeded:
                with lock:
                    results["failed"] += 1

        # Make 15 concurrent requests (limit is 10)
        threads = []
        for i in range(15):
            t = threading.Thread(target=make_request, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Should have 10 successes and 5 failures
        assert results["success"] == 10
        assert results["failed"] == 5
