"""Token bucket algorithm for rate limiting.

Implements the classic token bucket algorithm with:
- Configurable capacity and refill rate
- Thread-safe token operations
- Burst support
- Wait time calculation
- Token introspection for monitoring

The token bucket algorithm allows for bursty traffic while maintaining
an average rate limit over time.
"""
import time
import threading
import functools
from typing import Optional, Dict, Any, Tuple, Callable
from dataclasses import dataclass


def requires_lock(method: Callable) -> Callable:
    """Decorator to enforce that a method is called with the instance lock held.

    Raises:
        RuntimeError: If the method is called without holding self.lock

    Example:
        >>> class MyClass:
        ...     def __init__(self):
        ...         self.lock = threading.Lock()
        ...
        ...     @requires_lock
        ...     def _internal_method(self):
        ...         # This method requires lock to be held
        ...         pass
        ...
        ...     def public_method(self):
        ...         with self.lock:
        ...             self._internal_method()  # OK
        ...         self._internal_method()  # RuntimeError!
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        # Check if lock is held by attempting to acquire it with blocking=False
        # If we can acquire it, that means it wasn't held - this is an error!
        if self.lock.acquire(blocking=False):
            # We acquired the lock, which means it wasn't held - bad!
            self.lock.release()
            raise RuntimeError(
                f"{method.__name__}() must be called with self.lock held. "
                f"This is a thread-safety violation."
            )
        # Lock is held (acquire failed), proceed with method call
        return method(self, *args, **kwargs)
    return wrapper


@dataclass
class RateLimit:
    """Rate limit configuration for token bucket.

    Attributes:
        max_tokens: Maximum bucket capacity
        refill_rate: Tokens added per second
        refill_period: How often to check for refills (seconds)
        burst_size: Maximum tokens available for burst (≤ max_tokens)

    Example:
        >>> # 10 requests per hour with burst of 2
        >>> limit = RateLimit(
        ...     max_tokens=10,
        ...     refill_rate=10/3600,  # 10 per hour = 0.00278/sec
        ...     refill_period=1.0,     # Check every second
        ...     burst_size=2           # Allow 2 immediate requests
        ... )
    """
    max_tokens: int
    refill_rate: float
    refill_period: float = 1.0
    burst_size: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate configuration with safety bounds."""
        # SECURITY (code-high-12): Validate max_tokens (must be positive, bounded to prevent DoS)
        if not isinstance(self.max_tokens, int):
            raise ValueError(
                f"max_tokens must be an integer, got {type(self.max_tokens).__name__}"
            )
        if self.max_tokens <= 0:
            raise ValueError(
                f"max_tokens must be positive, got {self.max_tokens}"
            )
        if self.max_tokens > 1_000_000:
            raise ValueError(
                f"max_tokens must be <= 1,000,000 (safety limit), got {self.max_tokens}"
            )

        # SECURITY: Validate refill_rate (must be positive, bounded)
        if not isinstance(self.refill_rate, (int, float)):
            raise ValueError(
                f"refill_rate must be numeric, got {type(self.refill_rate).__name__}"
            )
        if self.refill_rate <= 0:
            raise ValueError(
                f"refill_rate must be positive, got {self.refill_rate}"
            )
        if self.refill_rate > 1_000_000:
            raise ValueError(
                f"refill_rate must be <= 1,000,000 (safety limit), got {self.refill_rate}"
            )

        # SECURITY: Validate refill_period
        if not isinstance(self.refill_period, (int, float)):
            raise ValueError(
                f"refill_period must be numeric, got {type(self.refill_period).__name__}"
            )
        if self.refill_period <= 0:
            raise ValueError(
                f"refill_period must be positive, got {self.refill_period}"
            )
        if self.refill_period > 86400:  # Max 24 hours
            raise ValueError(
                f"refill_period must be <= 86400s (24h), got {self.refill_period}"
            )

        # SECURITY: Validate burst_size
        if self.burst_size is None:
            self.burst_size = self.max_tokens
        else:
            if not isinstance(self.burst_size, int):
                raise ValueError(
                    f"burst_size must be an integer, got {type(self.burst_size).__name__}"
                )
            if self.burst_size <= 0:
                raise ValueError(
                    f"burst_size must be positive, got {self.burst_size}"
                )
            if self.burst_size > self.max_tokens:
                raise ValueError(
                    f"burst_size ({self.burst_size}) cannot exceed max_tokens ({self.max_tokens})"
                )


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    The token bucket algorithm:
    1. Bucket holds tokens up to max capacity
    2. Tokens are added at a constant rate
    3. Operations consume tokens
    4. If tokens available, operation proceeds
    5. If no tokens, operation is rate-limited

    This allows for bursts while maintaining average rate.

    Example:
        >>> limit = RateLimit(max_tokens=10, refill_rate=10/3600, burst_size=2)
        >>> bucket = TokenBucket(limit)
        >>>
        >>> # First request (burst)
        >>> if bucket.consume(1):
        ...     print("Request allowed")
        >>>
        >>> # Check remaining tokens
        >>> print(f"Tokens: {bucket.get_tokens()}")
        >>>
        >>> # Wait time if rate limited
        >>> wait = bucket.get_wait_time(1)
        >>> if wait > 0:
        ...     print(f"Rate limited. Wait {wait}s")
    """

    def __init__(self, rate_limit: RateLimit):
        """Initialize token bucket.

        Args:
            rate_limit: Rate limit configuration
        """
        self.max_tokens = rate_limit.max_tokens
        self.refill_rate = rate_limit.refill_rate
        self.refill_period = rate_limit.refill_period
        self.burst_size = rate_limit.burst_size

        # Start with full bucket
        self.tokens = float(self.max_tokens)
        self.last_refill = time.time()

        # Thread safety
        self.lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume tokens.

        Args:
            tokens: Number of tokens to consume (default: 1)

        Returns:
            True if tokens consumed successfully
            False if insufficient tokens (rate limited)

        Example:
            >>> bucket = TokenBucket(RateLimit(10, 1.0, 1.0, 10))
            >>> if bucket.consume(1):
            ...     execute_operation()
            ... else:
            ...     print("Rate limited")
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    def peek(self, tokens: int = 1) -> bool:
        """Check if tokens available without consuming.

        Args:
            tokens: Number of tokens to check

        Returns:
            True if tokens would be available

        Example:
            >>> bucket = TokenBucket(...)
            >>> if bucket.peek(5):
            ...     print("5 tokens available")
        """
        with self.lock:
            self._refill()
            return self.tokens >= tokens

    @requires_lock
    def _refill(self) -> None:
        """Refill tokens based on elapsed time.

        Called internally before token operations.
        MUST be called with self.lock held (enforced by @requires_lock decorator).

        Raises:
            RuntimeError: If called without holding self.lock
        """
        now = time.time()
        elapsed = now - self.last_refill

        if elapsed >= self.refill_period:
            # Calculate tokens to add based on refill rate
            tokens_to_add = (elapsed / self.refill_period) * self.refill_rate

            # Add tokens up to max capacity
            self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)

            # Update last refill time
            self.last_refill = now

    def get_tokens(self) -> float:
        """Get current token count.

        Useful for monitoring and observability.

        Returns:
            Current number of tokens available

        Example:
            >>> bucket = TokenBucket(...)
            >>> print(f"Available tokens: {bucket.get_tokens():.2f}")
        """
        with self.lock:
            self._refill()
            return self.tokens

    def get_wait_time(self, tokens: int = 1) -> float:
        """Calculate wait time until tokens available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Wait time in seconds (0 if tokens available now)

        Example:
            >>> bucket = TokenBucket(...)
            >>> wait = bucket.get_wait_time(1)
            >>> if wait > 0:
            ...     time.sleep(wait)
            ...     bucket.consume(1)
        """
        with self.lock:
            self._refill()

            if self.tokens >= tokens:
                return 0.0

            # Calculate how many more tokens needed
            tokens_needed = tokens - self.tokens

            # Calculate time to accumulate those tokens
            # time = tokens_needed / (tokens_per_second)
            # tokens_per_second = refill_rate / refill_period
            wait_time = (tokens_needed / self.refill_rate) * self.refill_period

            return wait_time

    def reset(self) -> None:
        """Reset bucket to full capacity.

        Useful for testing or clearing rate limit state.

        Example:
            >>> bucket = TokenBucket(...)
            >>> bucket.consume(5)
            >>> bucket.reset()  # Restore to full
        """
        with self.lock:
            self.tokens = float(self.max_tokens)
            self.last_refill = time.time()

    def get_info(self) -> Dict[str, Any]:
        """Get bucket information for debugging/monitoring.

        Returns:
            Dictionary with bucket state

        Example:
            >>> bucket = TokenBucket(...)
            >>> info = bucket.get_info()
            >>> print(info)
            {
                'current_tokens': 8.5,
                'max_tokens': 10,
                'refill_rate': 0.00278,
                'time_since_last_refill': 2.5,
                'fill_percentage': 85.0
            }
        """
        with self.lock:
            self._refill()

            return {
                'current_tokens': round(self.tokens, 2),
                'max_tokens': self.max_tokens,
                'refill_rate': self.refill_rate,
                'refill_period': self.refill_period,
                'burst_size': self.burst_size,
                'time_since_last_refill': round(time.time() - self.last_refill, 2),
                'fill_percentage': round((self.tokens / self.max_tokens) * 100, 1)
            }


class TokenBucketManager:
    """Manages multiple token buckets for different rate limit types.

    Provides centralized management of token buckets for different
    operations (commits, deploys, tool calls, etc.) and entities
    (agents, users, global).

    Example:
        >>> manager = TokenBucketManager()
        >>>
        >>> # Define rate limits
        >>> manager.set_limit('commit', RateLimit(10, 10/3600, 1.0, 2))
        >>> manager.set_limit('deploy', RateLimit(2, 2/3600, 1.0, 1))
        >>>
        >>> # Check limits
        >>> if manager.consume('agent-123', 'commit', 1):
        ...     git_commit()
        ... else:
        ...     print("Commit rate limited")
        >>>
        >>> # Get wait time
        >>> wait = manager.get_wait_time('agent-123', 'deploy', 1)
    """

    def __init__(self) -> None:
        """Initialize token bucket manager."""
        # Rate limit configurations: {limit_type: RateLimit}
        self.limits: Dict[str, RateLimit] = {}

        # Token buckets: {(entity_id, limit_type): TokenBucket}
        self.buckets: Dict[Tuple[str, str], TokenBucket] = {}

        # Thread safety for bucket creation
        self.lock = threading.Lock()

    def set_limit(self, limit_type: str, rate_limit: RateLimit) -> None:
        """Set rate limit configuration for a limit type.

        Args:
            limit_type: Type of limit (e.g., 'commit', 'deploy')
            rate_limit: Rate limit configuration

        Example:
            >>> manager = TokenBucketManager()
            >>> manager.set_limit('api_call', RateLimit(100, 100/3600, 1.0, 10))
        """
        with self.lock:
            self.limits[limit_type] = rate_limit

    def get_bucket(self, entity_id: str, limit_type: str) -> Optional[TokenBucket]:
        """Get or create token bucket for entity and limit type.

        Args:
            entity_id: Entity identifier (agent ID, user ID, etc.)
            limit_type: Type of limit

        Returns:
            TokenBucket instance or None if limit type not configured

        Example:
            >>> manager = TokenBucketManager()
            >>> manager.set_limit('commit', RateLimit(...))
            >>> bucket = manager.get_bucket('agent-123', 'commit')
        """
        if limit_type not in self.limits:
            return None

        bucket_key = (entity_id, limit_type)

        # Fast path: bucket already exists
        if bucket_key in self.buckets:
            return self.buckets[bucket_key]

        # Slow path: create new bucket (with lock)
        with self.lock:
            # Double-check after acquiring lock
            if bucket_key in self.buckets:
                return self.buckets[bucket_key]

            # Create new bucket
            bucket = TokenBucket(self.limits[limit_type])
            self.buckets[bucket_key] = bucket
            return bucket

    def consume(self, entity_id: str, limit_type: str, tokens: int = 1) -> bool:
        """Consume tokens for entity and limit type.

        Args:
            entity_id: Entity identifier
            limit_type: Type of limit
            tokens: Number of tokens to consume

        Returns:
            True if tokens consumed, False if rate limited

        Example:
            >>> manager = TokenBucketManager()
            >>> if manager.consume('agent-123', 'commit', 1):
            ...     git_commit()
        """
        bucket = self.get_bucket(entity_id, limit_type)
        if bucket is None:
            # No limit configured, allow operation
            return True

        return bucket.consume(tokens)

    def get_tokens(self, entity_id: str, limit_type: str) -> Optional[float]:
        """Get current token count.

        Args:
            entity_id: Entity identifier
            limit_type: Type of limit

        Returns:
            Current token count or None if bucket doesn't exist

        Example:
            >>> manager = TokenBucketManager()
            >>> tokens = manager.get_tokens('agent-123', 'commit')
            >>> print(f"Commits remaining: {tokens}")
        """
        bucket = self.get_bucket(entity_id, limit_type)
        if bucket is None:
            return None

        return bucket.get_tokens()

    def get_wait_time(self, entity_id: str, limit_type: str, tokens: int = 1) -> float:
        """Get wait time until tokens available.

        Args:
            entity_id: Entity identifier
            limit_type: Type of limit
            tokens: Number of tokens needed

        Returns:
            Wait time in seconds (0 if no limit or tokens available)

        Example:
            >>> manager = TokenBucketManager()
            >>> wait = manager.get_wait_time('agent-123', 'deploy', 1)
            >>> if wait > 0:
            ...     print(f"Wait {wait:.1f}s before deploying")
        """
        bucket = self.get_bucket(entity_id, limit_type)
        if bucket is None:
            return 0.0

        return bucket.get_wait_time(tokens)

    def reset(self, entity_id: Optional[str] = None, limit_type: Optional[str] = None) -> None:
        """Reset token buckets.

        Args:
            entity_id: Specific entity to reset (None = all)
            limit_type: Specific limit type to reset (None = all)

        Example:
            >>> manager = TokenBucketManager()
            >>> manager.reset('agent-123', 'commit')  # Reset one bucket
            >>> manager.reset('agent-123')  # Reset all limits for agent
            >>> manager.reset()  # Reset everything
        """
        with self.lock:
            if entity_id is None and limit_type is None:
                # Reset all buckets
                for bucket in self.buckets.values():
                    bucket.reset()
            elif entity_id and limit_type:
                # Reset specific bucket
                bucket_key = (entity_id, limit_type)
                if bucket_key in self.buckets:
                    self.buckets[bucket_key].reset()
            elif entity_id:
                # Reset all buckets for entity
                for (eid, _), bucket in self.buckets.items():
                    if eid == entity_id:
                        bucket.reset()
            elif limit_type:
                # Reset all buckets for limit type
                for (_, ltype), bucket in self.buckets.items():
                    if ltype == limit_type:
                        bucket.reset()

    def get_all_info(self) -> Dict[Tuple[str, str], Dict[str, Any]]:
        """Get information about all token buckets.

        Returns:
            Dictionary mapping (entity_id, limit_type) to bucket info

        Example:
            >>> manager = TokenBucketManager()
            >>> info = manager.get_all_info()
            >>> for (entity, limit_type), bucket_info in info.items():
            ...     print(f"{entity}/{limit_type}: {bucket_info['current_tokens']} tokens")
        """
        with self.lock:
            return {
                (entity_id, limit_type): bucket.get_info()
                for (entity_id, limit_type), bucket in self.buckets.items()
            }
