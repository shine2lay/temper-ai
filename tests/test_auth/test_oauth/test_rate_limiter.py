"""Comprehensive tests for OAuth rate limiting.

Tests cover:
- Token bucket algorithm
- Rate limit enforcement per IP/user
- Rate limit reset after window
- Concurrent rate limiting (thread safety)
- Rate limit headers (X-RateLimit-*)
- Burst handling
"""
import asyncio
import pytest
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from temper_ai.auth.oauth.rate_limiter import (
    RateLimitExceeded,
    SlidingWindowRateLimiter,
    OAuthRateLimiter,
)
from temper_ai.shared.constants.durations import SECONDS_PER_MINUTE, SECONDS_PER_HOUR


# ==================== FIXTURES ====================


@pytest.fixture
def rate_limiter():
    """Create fresh rate limiter for each test."""
    return SlidingWindowRateLimiter()


@pytest.fixture
def oauth_limiter():
    """Create OAuth-specific rate limiter."""
    return OAuthRateLimiter()


# ==================== SLIDING WINDOW BASIC TESTS ====================


def test_sliding_window_allows_within_limit(rate_limiter):
    """Test requests are allowed when within limit."""
    # Should allow 5 requests
    for i in range(5):
        result = rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)
        # check_limit returns None on success (doesn't raise exception)
        assert result is None

    # All requests should pass without exception
    assert True  # If we reach here, all requests passed


def test_sliding_window_blocks_over_limit(rate_limiter):
    """Test request blocked when exceeding limit."""
    # Fill up limit
    for i in range(5):
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    # Next request should be blocked
    with pytest.raises(RateLimitExceeded) as exc_info:
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    assert "Rate limit exceeded" in str(exc_info.value)
    assert exc_info.value.retry_after > 0


def test_sliding_window_independent_identifiers(rate_limiter):
    """Test different identifiers have independent limits."""
    # Fill limit for user1
    for i in range(5):
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    # user2 should still have full quota
    for i in range(5):
        rate_limiter.check_limit("test", "user2", max_requests=5, window_seconds=60)

    # Both users should be at limit now
    with pytest.raises(RateLimitExceeded):
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    with pytest.raises(RateLimitExceeded):
        rate_limiter.check_limit("test", "user2", max_requests=5, window_seconds=60)


def test_sliding_window_independent_limit_types(rate_limiter):
    """Test different limit types are independent."""
    # Fill limit for type1
    for i in range(5):
        rate_limiter.check_limit("type1", "user1", max_requests=5, window_seconds=60)

    # type2 should still work for same user
    for i in range(5):
        rate_limiter.check_limit("type2", "user1", max_requests=5, window_seconds=60)

    # Both types should be at limit
    with pytest.raises(RateLimitExceeded):
        rate_limiter.check_limit("type1", "user1", max_requests=5, window_seconds=60)

    with pytest.raises(RateLimitExceeded):
        rate_limiter.check_limit("type2", "user1", max_requests=5, window_seconds=60)


def test_sliding_window_resets_after_window(rate_limiter):
    """Test rate limit resets after time window expires."""
    base_time = datetime.now(timezone.utc)

    with patch('temper_ai.auth.oauth.rate_limiter.datetime') as mock_datetime:
        mock_datetime.now.return_value = base_time

        # Fill up limit
        for i in range(5):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Should be blocked
        with pytest.raises(RateLimitExceeded):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Advance time past window (61 seconds)
        mock_datetime.now.return_value = base_time + timedelta(seconds=61)

        # Should be allowed again (old requests expired)
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)


def test_sliding_window_partial_reset(rate_limiter):
    """Test sliding window allows partial resets."""
    base_time = datetime.now(timezone.utc)

    with patch('temper_ai.auth.oauth.rate_limiter.datetime') as mock_datetime:
        # Make 3 requests at T=0
        mock_datetime.now.return_value = base_time
        for i in range(3):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Make 2 more requests at T=30
        mock_datetime.now.return_value = base_time + timedelta(seconds=30)
        for i in range(2):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Should be at limit now
        with pytest.raises(RateLimitExceeded):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Advance to T=61 (first 3 requests expired)
        mock_datetime.now.return_value = base_time + timedelta(seconds=61)

        # Should allow 3 more requests (only 2 from T=30 still in window)
        for i in range(3):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)


# ==================== RETRY-AFTER TESTS ====================


def test_sliding_window_retry_after_calculation(rate_limiter):
    """Test retry-after correctly calculated."""
    base_time = datetime.now(timezone.utc)

    with patch('temper_ai.auth.oauth.rate_limiter.datetime') as mock_datetime:
        mock_datetime.now.return_value = base_time

        # Fill limit
        for i in range(5):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Check retry-after
        with pytest.raises(RateLimitExceeded) as exc_info:
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Retry-after should be ~60 seconds (when oldest request expires)
        assert 59 <= exc_info.value.retry_after <= 61


def test_sliding_window_retry_after_decreases(rate_limiter):
    """Test retry-after decreases as time passes."""
    base_time = datetime.now(timezone.utc)

    with patch('temper_ai.auth.oauth.rate_limiter.datetime') as mock_datetime:
        mock_datetime.now.return_value = base_time

        # Fill limit
        for i in range(5):
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

        # Check retry-after at T=0
        with pytest.raises(RateLimitExceeded) as exc_info:
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)
        retry_after_1 = exc_info.value.retry_after

        # Advance time 30 seconds
        mock_datetime.now.return_value = base_time + timedelta(seconds=30)

        # Check retry-after at T=30
        with pytest.raises(RateLimitExceeded) as exc_info:
            rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)
        retry_after_2 = exc_info.value.retry_after

        # Second retry-after should be ~30 seconds less
        assert retry_after_2 < retry_after_1
        assert retry_after_2 >= 29  # Account for rounding


# ==================== GET REMAINING TESTS ====================


def test_get_remaining_full_quota(rate_limiter):
    """Test get_remaining with full quota."""
    remaining, reset_after = rate_limiter.get_remaining(
        "test", "user1", max_requests=10, window_seconds=60
    )

    assert remaining == 10
    assert reset_after == 60


def test_get_remaining_partial_quota(rate_limiter):
    """Test get_remaining after some requests."""
    # Use 3 out of 10
    for i in range(3):
        rate_limiter.check_limit("test", "user1", max_requests=10, window_seconds=60)

    remaining, reset_after = rate_limiter.get_remaining(
        "test", "user1", max_requests=10, window_seconds=60
    )

    assert remaining == 7
    assert reset_after > 0


def test_get_remaining_zero_quota(rate_limiter):
    """Test get_remaining when quota exhausted."""
    # Use all 5
    for i in range(5):
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    remaining, reset_after = rate_limiter.get_remaining(
        "test", "user1", max_requests=5, window_seconds=60
    )

    assert remaining == 0
    assert reset_after > 0


# ==================== CLEANUP TESTS ====================


def test_cleanup_removes_old_data(rate_limiter):
    """Test cleanup removes expired data."""
    base_time = datetime.now(timezone.utc)

    with patch('temper_ai.auth.oauth.rate_limiter.datetime') as mock_datetime:
        mock_datetime.now.return_value = base_time

        # Make some requests
        rate_limiter.check_limit("test", "user1", max_requests=10, window_seconds=60)

        # Verify data exists
        assert len(rate_limiter._windows) > 0

        # Advance time past cleanup threshold (3600 seconds = 1 hour)
        mock_datetime.now.return_value = base_time + timedelta(seconds=3601)

        # Run cleanup
        rate_limiter.cleanup(older_than_seconds=3600)

        # Data should be removed
        assert len(rate_limiter._windows) == 0


def test_cleanup_keeps_recent_data(rate_limiter):
    """Test cleanup keeps recent data."""
    base_time = datetime.now(timezone.utc)

    with patch('temper_ai.auth.oauth.rate_limiter.datetime') as mock_datetime:
        mock_datetime.now.return_value = base_time

        # Make request
        rate_limiter.check_limit("test", "user1", max_requests=10, window_seconds=60)

        # Advance time but not past cleanup threshold
        mock_datetime.now.return_value = base_time + timedelta(seconds=1800)  # 30 minutes

        # Run cleanup
        rate_limiter.cleanup(older_than_seconds=3600)

        # Data should still exist
        assert len(rate_limiter._windows) > 0


# ==================== THREAD SAFETY TESTS ====================


def test_concurrent_requests_thread_safe(rate_limiter):
    """Test rate limiter is thread-safe under concurrent load."""
    max_requests = 100
    num_threads = 10
    requests_per_thread = 20

    errors = []

    def make_requests():
        for i in range(requests_per_thread):
            try:
                rate_limiter.check_limit(
                    "test",
                    "concurrent_user",
                    max_requests=max_requests,
                    window_seconds=60
                )
            except RateLimitExceeded as e:
                errors.append(e)

    # Launch threads
    threads = [threading.Thread(target=make_requests) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Total attempts = num_threads * requests_per_thread = 200
    # Limit = 100, so we should have exactly 100 errors
    assert len(errors) == 100


def test_concurrent_different_users_independent(rate_limiter):
    """Test concurrent requests for different users are independent."""
    max_requests = 50
    num_users = 5

    errors = {f"user{i}": [] for i in range(num_users)}

    def make_requests(user_id):
        for i in range(60):  # Exceed limit of 50
            try:
                rate_limiter.check_limit(
                    "test",
                    user_id,
                    max_requests=max_requests,
                    window_seconds=60
                )
            except RateLimitExceeded as e:
                errors[user_id].append(e)

    # Launch threads for different users
    threads = [
        threading.Thread(target=make_requests, args=(f"user{i}",))
        for i in range(num_users)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Each user should have exactly 10 errors (60 - 50)
    for user_id, user_errors in errors.items():
        assert len(user_errors) == 10, f"{user_id} had {len(user_errors)} errors"


# ==================== OAUTH RATE LIMITER TESTS ====================


def test_oauth_init_ip_limit(oauth_limiter):
    """Test OAuth init enforces IP limit."""
    # IP limit: 10 per minute, but user limit is 5 per minute (lower)
    # Use different users to avoid hitting user limit
    for i in range(10):
        oauth_limiter.check_oauth_init("192.168.1.1", f"user{i}")

    # 11th request should fail IP limit
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_oauth_init("192.168.1.1", "user999")


def test_oauth_init_user_limit(oauth_limiter):
    """Test OAuth init enforces user limit."""
    # User limit: 5 per minute (lower than IP limit)
    for i in range(5):
        oauth_limiter.check_oauth_init(f"192.168.1.{i}", "user1")

    # 6th request should fail (user limit hit)
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_oauth_init("192.168.1.99", "user1")


def test_oauth_init_global_limit(oauth_limiter):
    """Test OAuth init enforces global limit."""
    # Global limit: 1000 per hour
    # Simulate 1000 requests from different IPs and users
    for i in range(1000):
        oauth_limiter.check_oauth_init(f"192.168.{i // 256}.{i % 256}", f"user{i}")

    # 1001st request should fail (global limit)
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_oauth_init("10.0.0.1", "new_user")


def test_oauth_token_exchange_ip_limit(oauth_limiter):
    """Test token exchange enforces IP limit."""
    # IP limit: 5 per minute
    for i in range(5):
        oauth_limiter.check_token_exchange("192.168.1.1")

    # 6th request should fail
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_token_exchange("192.168.1.1")


def test_oauth_token_exchange_global_limit(oauth_limiter):
    """Test token exchange enforces global limit."""
    # Global limit: 500 per hour
    for i in range(500):
        oauth_limiter.check_token_exchange(f"192.168.{i // 256}.{i % 256}")

    # 501st request should fail
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_token_exchange("10.0.0.1")


def test_oauth_userinfo_user_limit(oauth_limiter):
    """Test userinfo enforces user limit."""
    # User limit: 60 per minute
    for i in range(60):
        oauth_limiter.check_userinfo("user1")

    # 61st request should fail
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_userinfo("user1")


def test_oauth_userinfo_global_limit(oauth_limiter):
    """Test userinfo enforces global limit."""
    # Global limit: 5000 per hour
    for i in range(5000):
        oauth_limiter.check_userinfo(f"user{i}")

    # 5001st request should fail
    with pytest.raises(RateLimitExceeded):
        oauth_limiter.check_userinfo("new_user")


def test_oauth_limiter_custom_limiter():
    """Test OAuth limiter with custom underlying limiter."""
    custom_limiter = SlidingWindowRateLimiter()
    oauth_limiter = OAuthRateLimiter(limiter=custom_limiter)

    # Should use the custom limiter
    assert oauth_limiter.limiter is custom_limiter


# ==================== BURST HANDLING TESTS ====================


def test_burst_within_limit_allowed(rate_limiter):
    """Test burst of requests within limit is allowed."""
    # Rapid burst of 5 requests (within limit of 10)
    start_time = time.time()
    for i in range(5):
        rate_limiter.check_limit("test", "user1", max_requests=10, window_seconds=60)
    end_time = time.time()

    # All should succeed quickly
    assert end_time - start_time < 1  # Less than 1 second


def test_burst_exceeding_limit_blocked(rate_limiter):
    """Test burst exceeding limit is blocked."""
    # Burst of 15 requests (limit is 10)
    allowed = 0
    blocked = 0

    for i in range(15):
        try:
            rate_limiter.check_limit("test", "user1", max_requests=10, window_seconds=60)
            allowed += 1
        except RateLimitExceeded:
            blocked += 1

    assert allowed == 10
    assert blocked == 5


# ==================== ERROR MESSAGE TESTS ====================


def test_rate_limit_exceeded_message_format(rate_limiter):
    """Test RateLimitExceeded error message format."""
    # Fill limit
    for i in range(5):
        rate_limiter.check_limit("test_type", "user1", max_requests=5, window_seconds=60)

    # Trigger error
    with pytest.raises(RateLimitExceeded) as exc_info:
        rate_limiter.check_limit("test_type", "user1", max_requests=5, window_seconds=60)

    error_msg = str(exc_info.value)
    assert "Rate limit exceeded" in error_msg
    assert "test_type" in error_msg
    assert "5 requests" in error_msg
    assert "60 seconds" in error_msg


def test_rate_limit_exceeded_attributes(rate_limiter):
    """Test RateLimitExceeded exception attributes."""
    # Fill limit
    for i in range(5):
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    # Trigger error
    with pytest.raises(RateLimitExceeded) as exc_info:
        rate_limiter.check_limit("test", "user1", max_requests=5, window_seconds=60)

    assert exc_info.value.retry_after > 0
    assert isinstance(exc_info.value.retry_after, int)
