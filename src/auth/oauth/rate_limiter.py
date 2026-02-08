"""Simple rate limiting for OAuth endpoints.

Prevents abuse and DoS attacks on OAuth flows with multi-tier rate limiting:
- IP-based limits (prevent single attacker from exhausting resources)
- User-based limits (prevent compromised accounts from abuse)
- Global limits (protect OAuth provider quota)

This is a simplified implementation suitable for moderate traffic.
For high-scale production, consider using redis-based rate limiting
with libraries like slowapi or limits.
"""
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from src.constants.durations import DURATION_INSTANT, SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from src.utils.exceptions import RateLimitError

logger = logging.getLogger(__name__)


class RateLimitExceeded(RateLimitError):  # noqa: N818 — public API name
    """Raised when rate limit is exceeded.

    Inherits from framework-wide RateLimitError for unified isinstance checks
    while preserving the public OAuth API name.
    """

    def __init__(self, message: str, retry_after: int):
        """Initialize rate limit exception.

        Args:
            message: Error message
            retry_after: Seconds until rate limit resets
        """
        super().__init__(message, retry_after=retry_after)


class SlidingWindowRateLimiter:
    """Sliding window rate limiter with multiple limit tiers.

    Uses sliding window algorithm to track request counts over time.
    More accurate than fixed windows and prevents burst at window boundaries.

    Thread-safe implementation using locks.

    Example:
        >>> limiter = SlidingWindowRateLimiter()
        >>>
        >>> # Check if request allowed
        >>> try:
        ...     limiter.check_limit("oauth_init_ip", "192.168.1.1", max_requests=10, window_seconds=60)
        ...     # Request allowed, proceed
        ... except RateLimitExceeded as e:
        ...     # Rate limit hit, return 429 error
        ...     return error_response(429, f"Retry after {e.retry_after}s")
    """

    def __init__(self):
        """Initialize rate limiter."""
        # Storage: {limit_type: {identifier: deque of timestamps}}
        self._windows: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
        self._lock = threading.Lock()

    def check_limit(
        self,
        limit_type: str,
        identifier: str,
        max_requests: int,
        window_seconds: int
    ) -> None:
        """Check if request is within rate limit.

        Args:
            limit_type: Type of limit (e.g., "oauth_init_ip", "token_exchange_user")
            identifier: Unique identifier (IP address, user_id, etc.)
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds

        Raises:
            RateLimitExceeded: If rate limit exceeded
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(seconds=window_seconds)

            # Get timestamp queue for this identifier
            timestamps = self._windows[limit_type][identifier]

            # Remove timestamps outside the window
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()

            # Check if limit exceeded
            if len(timestamps) >= max_requests:
                # Calculate retry-after (time until oldest request expires)
                oldest_timestamp = timestamps[0]
                retry_after = int((oldest_timestamp + timedelta(seconds=window_seconds) - now).total_seconds()) + DURATION_INSTANT

                logger.warning(
                    f"Rate limit exceeded: {limit_type}={identifier}, "
                    f"count={len(timestamps)}/{max_requests} in {window_seconds}s"
                )

                raise RateLimitExceeded(
                    f"Rate limit exceeded for {limit_type}. "
                    f"Maximum {max_requests} requests per {window_seconds} seconds.",
                    retry_after=retry_after
                )

            # Add current request timestamp
            timestamps.append(now)

            logger.debug(
                f"Rate limit check passed: {limit_type}={identifier}, "
                f"count={len(timestamps)}/{max_requests}"
            )

    def get_remaining(
        self,
        limit_type: str,
        identifier: str,
        max_requests: int,
        window_seconds: int
    ) -> Tuple[int, int]:
        """Get remaining requests and reset time.

        Args:
            limit_type: Type of limit
            identifier: Unique identifier
            max_requests: Maximum requests allowed
            window_seconds: Time window in seconds

        Returns:
            (remaining_requests, reset_after_seconds) tuple
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(seconds=window_seconds)

            timestamps = self._windows[limit_type][identifier]

            # Clean up old timestamps
            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()

            remaining = max(0, max_requests - len(timestamps))

            # Calculate reset time (when oldest request expires)
            if timestamps:
                oldest = timestamps[0]
                reset_after = int((oldest + timedelta(seconds=window_seconds) - now).total_seconds())
            else:
                reset_after = window_seconds

            return remaining, reset_after

    def cleanup(self, older_than_seconds: int = SECONDS_PER_HOUR):
        """Clean up old rate limit data.

        Removes limit data for identifiers with no recent requests.

        Args:
            older_than_seconds: Remove data older than this (default: 1 hour)
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(seconds=older_than_seconds)

            for limit_type in list(self._windows.keys()):
                identifiers_to_remove = []

                for identifier, timestamps in self._windows[limit_type].items():
                    # Remove old timestamps
                    while timestamps and timestamps[0] < cutoff:
                        timestamps.popleft()

                    # If no timestamps left, mark for removal
                    if not timestamps:
                        identifiers_to_remove.append(identifier)

                # Remove empty identifiers
                for identifier in identifiers_to_remove:
                    del self._windows[limit_type][identifier]

                # Remove empty limit types
                if not self._windows[limit_type]:
                    del self._windows[limit_type]


class OAuthRateLimiter:
    """OAuth-specific rate limiter with predefined limit tiers.

    Implements multi-tier rate limiting:
    1. IP-based: Prevent single attacker from resource exhaustion
    2. User-based: Prevent compromised accounts from abuse
    3. Global: Protect OAuth provider quota

    Default Limits:
    - OAuth flow initiation:
      - 10 per IP per minute
      - 5 per user per minute
      - 1000 global per hour

    - Token exchange:
      - 5 per IP per minute
      - 500 global per hour

    - User info retrieval:
      - 60 per user per minute
      - 5000 global per hour
    """

    def __init__(self, limiter: Optional[SlidingWindowRateLimiter] = None):
        """Initialize OAuth rate limiter.

        Args:
            limiter: Underlying rate limiter (default: creates new SlidingWindowRateLimiter)
        """
        self.limiter = limiter or SlidingWindowRateLimiter()

        # Define OAuth-specific limits
        self.limits = {
            # OAuth flow initiation
            "oauth_init_ip": (10, SECONDS_PER_MINUTE),      # 10 per IP per minute
            "oauth_init_user": (5, SECONDS_PER_MINUTE),     # 5 per user per minute
            "oauth_init_global": (1000, SECONDS_PER_HOUR),  # 1000 global per hour

            # Token exchange
            "token_exchange_ip": (5, SECONDS_PER_MINUTE),   # 5 per IP per minute
            "token_exchange_global": (500, SECONDS_PER_HOUR),  # 500 global per hour

            # User info retrieval
            "userinfo_user": (60, SECONDS_PER_MINUTE),      # 60 per user per minute
            "userinfo_global": (5000, SECONDS_PER_HOUR),  # 5000 global per hour
        }

    def check_oauth_init(
        self,
        ip_address: str,
        user_id: str
    ) -> None:
        """Check rate limits for OAuth flow initiation.

        Args:
            ip_address: Client IP address
            user_id: User identifier

        Raises:
            RateLimitExceeded: If any limit exceeded
        """
        # Check IP limit
        max_requests, window = self.limits["oauth_init_ip"]
        self.limiter.check_limit("oauth_init_ip", ip_address, max_requests, window)

        # Check user limit
        max_requests, window = self.limits["oauth_init_user"]
        self.limiter.check_limit("oauth_init_user", user_id, max_requests, window)

        # Check global limit
        max_requests, window = self.limits["oauth_init_global"]
        self.limiter.check_limit("oauth_init_global", "global", max_requests, window)

    def check_token_exchange(
        self,
        ip_address: str
    ) -> None:
        """Check rate limits for token exchange.

        Args:
            ip_address: Client IP address

        Raises:
            RateLimitExceeded: If any limit exceeded
        """
        # Check IP limit
        max_requests, window = self.limits["token_exchange_ip"]
        self.limiter.check_limit("token_exchange_ip", ip_address, max_requests, window)

        # Check global limit
        max_requests, window = self.limits["token_exchange_global"]
        self.limiter.check_limit("token_exchange_global", "global", max_requests, window)

    def check_userinfo(
        self,
        user_id: str
    ) -> None:
        """Check rate limits for user info retrieval.

        Args:
            user_id: User identifier

        Raises:
            RateLimitExceeded: If any limit exceeded
        """
        # Check user limit
        max_requests, window = self.limits["userinfo_user"]
        self.limiter.check_limit("userinfo_user", user_id, max_requests, window)

        # Check global limit
        max_requests, window = self.limits["userinfo_global"]
        self.limiter.check_limit("userinfo_global", "global", max_requests, window)
