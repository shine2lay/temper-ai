"""Tests for OAuth rate limiting."""

import time

import pytest

from temper_ai.auth.oauth.rate_limiter import (
    OAuthRateLimiter,
    RateLimitExceeded,
    SlidingWindowRateLimiter,
)


class TestSlidingWindowRateLimiter:
    """Tests for sliding window rate limiter."""

    def test_within_limit(self):
        """Requests within limit should be allowed."""
        limiter = SlidingWindowRateLimiter()

        # 10 requests should all succeed
        for _i in range(10):
            limiter.check_limit(
                "test", "identifier_1", max_requests=10, window_seconds=60
            )

        # All requests succeeded without raising exception
        assert limiter is not None

    def test_exceeds_limit(self):
        """Requests exceeding limit should raise RateLimitExceeded with specific error details."""
        limiter = SlidingWindowRateLimiter()

        # First 5 requests succeed
        for _i in range(5):
            limiter.check_limit(
                "test", "identifier_1", max_requests=5, window_seconds=60
            )

        # 6th request should fail
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_limit(
                "test", "identifier_1", max_requests=5, window_seconds=60
            )

        error = exc_info.value
        # Validate retry_after is present and reasonable
        assert error.retry_after > 0, "Missing retry_after"
        assert error.retry_after <= 60, f"Retry_after too long: {error.retry_after}s"

    def test_sliding_window_expiry(self):
        """Old requests should expire from the sliding window."""
        limiter = SlidingWindowRateLimiter()

        # Make 3 requests
        for _i in range(3):
            limiter.check_limit(
                "test", "identifier_1", max_requests=3, window_seconds=2
            )

        # Should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit(
                "test", "identifier_1", max_requests=3, window_seconds=2
            )

        # Wait for window to expire
        time.sleep(3)

        # Should be able to make requests again (old ones expired)
        limiter.check_limit("test", "identifier_1", max_requests=3, window_seconds=2)

    def test_different_identifiers_independent(self):
        """Different identifiers should have independent limits."""
        limiter = SlidingWindowRateLimiter()

        # Fill limit for identifier_1
        for _i in range(5):
            limiter.check_limit(
                "test", "identifier_1", max_requests=5, window_seconds=60
            )

        # identifier_1 should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit(
                "test", "identifier_1", max_requests=5, window_seconds=60
            )

        # identifier_2 should still be able to make requests
        for _i in range(5):
            limiter.check_limit(
                "test", "identifier_2", max_requests=5, window_seconds=60
            )

    def test_different_limit_types_independent(self):
        """Different limit types should be independent."""
        limiter = SlidingWindowRateLimiter()

        # Fill limit for type_a
        for _i in range(5):
            limiter.check_limit(
                "type_a", "identifier_1", max_requests=5, window_seconds=60
            )

        # type_a should be at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check_limit(
                "type_a", "identifier_1", max_requests=5, window_seconds=60
            )

        # type_b should still be available
        for _i in range(5):
            limiter.check_limit(
                "type_b", "identifier_1", max_requests=5, window_seconds=60
            )


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
        limiter.limits["oauth_init_global"] = (
            20,
            60,
        )  # 20 per minute instead of 1000/hour

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
        for _i in range(5):
            limiter.check_token_exchange("192.168.1.1")

        # 6th request from same IP should fail
        with pytest.raises(RateLimitExceeded):
            limiter.check_token_exchange("192.168.1.1")

    def test_userinfo_rate_limiting(self):
        """Should enforce rate limits on user info retrieval."""
        limiter = OAuthRateLimiter()

        # Make requests up to user limit (60 per minute)
        for _i in range(60):
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
        """RateLimitExceeded should have helpful error message without leaking sensitive info."""
        limiter = OAuthRateLimiter()

        sensitive_ip = "192.168.1.100"  # Use realistic IP that might be sensitive

        # Fill limit
        for i in range(10):
            limiter.check_oauth_init(sensitive_ip, f"user_{i}")

        # Should get detailed error
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_oauth_init(sensitive_ip, "user_11")

        error = exc_info.value
        error_msg = str(error)

        # Validate error message contains rate limit info
        assert "Rate limit exceeded" in error_msg or "rate limit" in error_msg.lower()
        assert error.retry_after > 0
        assert error.retry_after <= 60  # Should be within window

        # SECURITY: Verify error message doesn't leak sensitive information
        assert (
            sensitive_ip not in error_msg
        ), f"Error message leaks IP address: {error_msg}"

        # Verify error message doesn't leak exact counts (prevents enumeration)
        assert not any(
            pattern in error_msg
            for pattern in ["10/10", "11/10", "count=10", "requests=10"]
        ), f"Error message leaks request counts: {error_msg}"

    def test_concurrent_requests(self):
        """Rate limiting should be thread-safe (TOCTOU protection)."""
        import threading

        limiter = OAuthRateLimiter()
        results = {"success": 0, "failed": 0}
        errors = []
        lock = threading.Lock()

        def make_request(i):
            try:
                limiter.check_oauth_init("192.168.1.1", f"user_{i}")
                with lock:
                    results["success"] += 1
            except RateLimitExceeded as e:
                with lock:
                    results["failed"] += 1
                    errors.append((i, e))

        # Make 15 concurrent requests (limit is 10)
        threads = []
        for i in range(15):
            t = threading.Thread(target=make_request, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # SECURITY: Validate TOCTOU protection - exactly 10 should succeed
        assert (
            results["success"] == 10
        ), f"TOCTOU vulnerability: {results['success']} requests succeeded (should be exactly 10)"
        assert results["failed"] == 5, f"Expected 5 failures, got {results['failed']}"

        # Validate all failures have proper error details
        for request_id, error in errors:
            assert (
                error.retry_after > 0
            ), f"Request {request_id} should have valid retry_after value"
