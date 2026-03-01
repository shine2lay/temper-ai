"""Simple rate limiting for OAuth endpoints.

Prevents abuse and DoS attacks on OAuth flows with multi-tier rate limiting:
- IP-based limits (prevent single attacker from exhausting resources)
- User-based limits (prevent compromised accounts from abuse)
- Global limits (protect OAuth provider quota)

This is a simplified implementation suitable for moderate traffic.
"""

import logging
import threading
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from temper_ai.shared.constants.durations import (
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
)

DURATION_INSTANT = 1
from temper_ai.shared.utils.exceptions import RateLimitError

logger = logging.getLogger(__name__)

# Rate limit thresholds (requests allowed per time window)
OAUTH_INIT_PER_IP_LIMIT = 10  # OAuth flow initiations per IP per minute
OAUTH_INIT_PER_USER_LIMIT = 5  # OAuth flow initiations per user per minute
OAUTH_INIT_GLOBAL_LIMIT = 1000  # OAuth flow initiations globally per hour
TOKEN_EXCHANGE_PER_IP_LIMIT = 5  # Token exchanges per IP per minute
TOKEN_EXCHANGE_GLOBAL_LIMIT = 500  # Token exchanges globally per hour
USERINFO_PER_USER_LIMIT = 60  # User info retrievals per user per minute
USERINFO_GLOBAL_LIMIT = 5000  # User info retrievals globally per hour

# Rate limit type keys
LIMIT_OAUTH_INIT_IP = "oauth_init_ip"
LIMIT_OAUTH_INIT_USER = "oauth_init_user"
LIMIT_OAUTH_INIT_GLOBAL = "oauth_init_global"
LIMIT_TOKEN_EXCHANGE_IP = (
    "token_exchange_ip"  # noqa: S105 — rate limit key, not password
)
LIMIT_TOKEN_EXCHANGE_GLOBAL = (
    "token_exchange_global"  # noqa: S105 — rate limit key, not password
)
LIMIT_USERINFO_USER = "userinfo_user"
LIMIT_USERINFO_GLOBAL = "userinfo_global"
# Global identifier for rate limiting
GLOBAL_IDENTIFIER = "global"


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

    def __init__(self) -> None:
        """Initialize rate limiter."""
        # Storage: {limit_type: {identifier: deque of timestamps}}
        self._windows: dict[str, dict[str, deque]] = defaultdict(
            lambda: defaultdict(deque)
        )
        self._lock = threading.Lock()

    def check_limit(
        self, limit_type: str, identifier: str, max_requests: int, window_seconds: int
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
            now = datetime.now(UTC)
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
                retry_after = (
                    int(
                        (
                            oldest_timestamp + timedelta(seconds=window_seconds) - now
                        ).total_seconds()
                    )
                    + DURATION_INSTANT
                )

                logger.warning(
                    f"Rate limit exceeded: {limit_type}={identifier}, "
                    f"count={len(timestamps)}/{max_requests} in {window_seconds}s"
                )

                raise RateLimitExceeded(
                    f"Rate limit exceeded for {limit_type}. "
                    f"Maximum {max_requests} requests per {window_seconds} seconds.",
                    retry_after=retry_after,
                )

            # Add current request timestamp
            timestamps.append(now)

            logger.debug(
                f"Rate limit check passed: {limit_type}={identifier}, "
                f"count={len(timestamps)}/{max_requests}"
            )


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

    def __init__(self, limiter: SlidingWindowRateLimiter | None = None):
        """Initialize OAuth rate limiter.

        Args:
            limiter: Underlying rate limiter (default: creates new SlidingWindowRateLimiter)  # noqa
        """
        self.limiter = limiter or SlidingWindowRateLimiter()

        # Define OAuth-specific limits
        self.limits = {
            # OAuth flow initiation  # noqa
            LIMIT_OAUTH_INIT_IP: (OAUTH_INIT_PER_IP_LIMIT, SECONDS_PER_MINUTE),
            LIMIT_OAUTH_INIT_USER: (OAUTH_INIT_PER_USER_LIMIT, SECONDS_PER_MINUTE),
            LIMIT_OAUTH_INIT_GLOBAL: (OAUTH_INIT_GLOBAL_LIMIT, SECONDS_PER_HOUR),
            # Token exchange  # noqa
            LIMIT_TOKEN_EXCHANGE_IP: (TOKEN_EXCHANGE_PER_IP_LIMIT, SECONDS_PER_MINUTE),
            LIMIT_TOKEN_EXCHANGE_GLOBAL: (
                TOKEN_EXCHANGE_GLOBAL_LIMIT,
                SECONDS_PER_HOUR,
            ),
            # User info retrieval
            LIMIT_USERINFO_USER: (USERINFO_PER_USER_LIMIT, SECONDS_PER_MINUTE),
            LIMIT_USERINFO_GLOBAL: (USERINFO_GLOBAL_LIMIT, SECONDS_PER_HOUR),
        }  # noqa

    def check_oauth_init(self, ip_address: str, user_id: str) -> None:
        """Check rate limits for OAuth flow initiation.

        Args:
            ip_address: Client IP address
            user_id: User identifier

        Raises:
            RateLimitExceeded: If any limit exceeded
        """
        # Check IP limit
        max_requests, window = self.limits[LIMIT_OAUTH_INIT_IP]
        self.limiter.check_limit(LIMIT_OAUTH_INIT_IP, ip_address, max_requests, window)

        # Check user limit
        max_requests, window = self.limits[LIMIT_OAUTH_INIT_USER]
        self.limiter.check_limit(LIMIT_OAUTH_INIT_USER, user_id, max_requests, window)

        # Check global limit
        max_requests, window = self.limits[LIMIT_OAUTH_INIT_GLOBAL]
        self.limiter.check_limit(
            LIMIT_OAUTH_INIT_GLOBAL, GLOBAL_IDENTIFIER, max_requests, window
        )

    def check_token_exchange(self, ip_address: str) -> None:
        """Check rate limits for token exchange.

        Args:
            ip_address: Client IP address

        Raises:
            RateLimitExceeded: If any limit exceeded
        """
        # Check IP limit
        max_requests, window = self.limits[LIMIT_TOKEN_EXCHANGE_IP]
        self.limiter.check_limit(
            LIMIT_TOKEN_EXCHANGE_IP, ip_address, max_requests, window
        )

        # Check global limit
        max_requests, window = self.limits[LIMIT_TOKEN_EXCHANGE_GLOBAL]
        self.limiter.check_limit(
            LIMIT_TOKEN_EXCHANGE_GLOBAL, GLOBAL_IDENTIFIER, max_requests, window
        )

    def check_userinfo(self, user_id: str) -> None:
        """Check rate limits for user info retrieval.

        Args:
            user_id: User identifier

        Raises:
            RateLimitExceeded: If any limit exceeded
        """
        # Check user limit
        max_requests, window = self.limits[LIMIT_USERINFO_USER]
        self.limiter.check_limit(LIMIT_USERINFO_USER, user_id, max_requests, window)

        # Check global limit
        max_requests, window = self.limits[LIMIT_USERINFO_GLOBAL]
        self.limiter.check_limit(
            LIMIT_USERINFO_GLOBAL, GLOBAL_IDENTIFIER, max_requests, window
        )
