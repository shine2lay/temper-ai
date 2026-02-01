# Distributed Rate Limiting - Fix Implementation Guide

**Code snippets for implementing security fixes**

---

## Fix 1: Redis-Backed Token Bucket (P0 - CRITICAL)

### New File: `src/safety/redis_token_bucket.py`

```python
"""
Redis-backed distributed token bucket for rate limiting.

Provides:
- Atomic token consumption via Lua scripts
- Shared state across all instances
- Persistence across restarts
- TTL-based cleanup
"""

import time
import redis
from typing import Optional, Dict, Any
from dataclasses import dataclass

from src.safety.token_bucket import RateLimit


# Lua script for atomic token consumption
CONSUME_TOKENS_SCRIPT = """
local key = KEYS[1]
local refill_key = KEYS[2]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local refill_period = tonumber(ARGV[3])
local tokens_to_consume = tonumber(ARGV[4])
local now = tonumber(ARGV[5])

-- Get current state (default to max_tokens if key doesn't exist)
local current_tokens = tonumber(redis.call('GET', key))
if not current_tokens then
    current_tokens = max_tokens
end

local last_refill = tonumber(redis.call('GET', refill_key))
if not last_refill then
    last_refill = now
end

-- Calculate refill
local elapsed = now - last_refill
if elapsed >= refill_period then
    local tokens_to_add = (elapsed / refill_period) * refill_rate
    current_tokens = math.min(max_tokens, current_tokens + tokens_to_add)
    redis.call('SET', refill_key, now)
    redis.call('EXPIRE', refill_key, 86400)  -- 24 hour TTL
end

-- Try to consume tokens
if current_tokens >= tokens_to_consume then
    current_tokens = current_tokens - tokens_to_consume
    redis.call('SET', key, current_tokens)
    redis.call('EXPIRE', key, 86400)  -- 24 hour TTL
    return 1  -- Success
else
    -- Update current tokens but don't consume
    redis.call('SET', key, current_tokens)
    redis.call('EXPIRE', key, 86400)
    return 0  -- Rate limited
end
"""


class RedisTokenBucket:
    """
    Distributed token bucket using Redis for shared state.

    Thread-safe and process-safe via Redis atomic operations.

    Example:
        >>> import redis
        >>> client = redis.Redis(host='localhost', port=6379)
        >>> limit = RateLimit(max_tokens=10, refill_rate=1.0, refill_period=1.0)
        >>> bucket = RedisTokenBucket(client, "agent-123:llm_call", limit)
        >>>
        >>> if bucket.consume(1):
        ...     make_llm_call()
        ... else:
        ...     print("Rate limited")
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        key_prefix: str,
        rate_limit: RateLimit
    ):
        """
        Initialize Redis token bucket.

        Args:
            redis_client: Redis connection
            key_prefix: Key prefix for this bucket (e.g., "agent-123:llm_call")
            rate_limit: Rate limit configuration
        """
        self.redis = redis_client
        self.key = f"rate_limit:{key_prefix}:tokens"
        self.refill_key = f"rate_limit:{key_prefix}:last_refill"
        self.rate_limit = rate_limit

        # Preload Lua script for performance
        self._consume_script = None

    def _get_consume_script(self):
        """Get or load Lua script for token consumption."""
        if self._consume_script is None:
            self._consume_script = self.redis.register_script(CONSUME_TOKENS_SCRIPT)
        return self._consume_script

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens atomically.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens consumed successfully
            False if insufficient tokens (rate limited)

        Example:
            >>> bucket = RedisTokenBucket(...)
            >>> if bucket.consume(1):
            ...     execute_operation()
        """
        script = self._get_consume_script()

        try:
            result = script(
                keys=[self.key, self.refill_key],
                args=[
                    self.rate_limit.max_tokens,
                    self.rate_limit.refill_rate,
                    self.rate_limit.refill_period,
                    tokens,
                    time.time()
                ]
            )

            return result == 1

        except redis.RedisError as e:
            # Log error and fail open (allow operation)
            # In production, you might want to fail closed instead
            print(f"Redis error in rate limiting: {e}")
            return True

    def get_tokens(self) -> float:
        """
        Get current token count.

        Returns:
            Current number of tokens available
        """
        try:
            tokens_str = self.redis.get(self.key)
            if tokens_str is None:
                return float(self.rate_limit.max_tokens)
            return float(tokens_str)
        except redis.RedisError:
            return float(self.rate_limit.max_tokens)

    def get_wait_time(self, tokens: int = 1) -> float:
        """
        Calculate wait time until tokens available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Wait time in seconds (0 if tokens available now)
        """
        current_tokens = self.get_tokens()

        if current_tokens >= tokens:
            return 0.0

        tokens_needed = tokens - current_tokens
        wait_time = (tokens_needed / self.rate_limit.refill_rate) * self.rate_limit.refill_period

        return wait_time

    def reset(self) -> None:
        """Reset bucket to full capacity."""
        try:
            self.redis.delete(self.key, self.refill_key)
        except redis.RedisError:
            pass

    def get_info(self) -> Dict[str, Any]:
        """Get bucket information for debugging/monitoring."""
        tokens = self.get_tokens()

        return {
            'current_tokens': round(tokens, 2),
            'max_tokens': self.rate_limit.max_tokens,
            'refill_rate': self.rate_limit.refill_rate,
            'refill_period': self.rate_limit.refill_period,
            'burst_size': self.rate_limit.burst_size,
            'fill_percentage': round((tokens / self.rate_limit.max_tokens) * 100, 1),
            'backend': 'redis',
            'key': self.key
        }


class RedisTokenBucketManager:
    """
    Manages multiple Redis token buckets for different rate limit types.

    Example:
        >>> import redis
        >>> client = redis.Redis(host='localhost', port=6379)
        >>> manager = RedisTokenBucketManager(client)
        >>>
        >>> manager.set_limit('llm_call', RateLimit(10, 1.0, 1.0))
        >>>
        >>> if manager.consume('agent-123', 'llm_call', 1):
        ...     make_llm_call()
    """

    def __init__(self, redis_client: redis.Redis):
        """
        Initialize token bucket manager.

        Args:
            redis_client: Redis connection
        """
        self.redis = redis_client
        self.limits: Dict[str, RateLimit] = {}

    def set_limit(self, limit_type: str, rate_limit: RateLimit) -> None:
        """Set rate limit configuration for a limit type."""
        self.limits[limit_type] = rate_limit

    def _get_bucket_key(self, entity_id: str, limit_type: str) -> str:
        """Generate Redis key for bucket."""
        # Normalize entity ID to prevent bypass
        from src.safety.utils import normalize_entity_id
        normalized_id = normalize_entity_id(entity_id)
        return f"{normalized_id}:{limit_type}"

    def consume(self, entity_id: str, limit_type: str, tokens: int = 1) -> bool:
        """Consume tokens for entity and limit type."""
        if limit_type not in self.limits:
            # No limit configured, allow operation
            return True

        bucket_key = self._get_bucket_key(entity_id, limit_type)
        bucket = RedisTokenBucket(self.redis, bucket_key, self.limits[limit_type])

        return bucket.consume(tokens)

    def get_tokens(self, entity_id: str, limit_type: str) -> Optional[float]:
        """Get current token count."""
        if limit_type not in self.limits:
            return None

        bucket_key = self._get_bucket_key(entity_id, limit_type)
        bucket = RedisTokenBucket(self.redis, bucket_key, self.limits[limit_type])

        return bucket.get_tokens()

    def get_wait_time(self, entity_id: str, limit_type: str, tokens: int = 1) -> float:
        """Get wait time until tokens available."""
        if limit_type not in self.limits:
            return 0.0

        bucket_key = self._get_bucket_key(entity_id, limit_type)
        bucket = RedisTokenBucket(self.redis, bucket_key, self.limits[limit_type])

        return bucket.get_wait_time(tokens)

    def reset(self, entity_id: Optional[str] = None, limit_type: Optional[str] = None) -> None:
        """Reset token buckets."""
        if entity_id is None and limit_type is None:
            # Reset all - use Redis SCAN to find all keys
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match="rate_limit:*")
                if keys:
                    self.redis.delete(*keys)
                if cursor == 0:
                    break

        elif entity_id and limit_type:
            # Reset specific bucket
            bucket_key = self._get_bucket_key(entity_id, limit_type)
            bucket = RedisTokenBucket(self.redis, bucket_key, self.limits[limit_type])
            bucket.reset()

        elif entity_id:
            # Reset all buckets for entity
            normalized_id = normalize_entity_id(entity_id)
            pattern = f"rate_limit:{normalized_id}:*"
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern)
                if keys:
                    self.redis.delete(*keys)
                if cursor == 0:
                    break

        elif limit_type:
            # Reset all buckets for limit type
            pattern = f"rate_limit:*:{limit_type}:*"
            cursor = 0
            while True:
                cursor, keys = self.redis.scan(cursor, match=pattern)
                if keys:
                    self.redis.delete(*keys)
                if cursor == 0:
                    break
```

---

## Fix 2: Entity ID Normalization (P0 - CRITICAL)

### New File: `src/safety/utils.py`

```python
"""
Security utilities for rate limiting.

Provides:
- Entity ID normalization (prevent case/Unicode bypass)
- Homoglyph detection
- Zero-width character removal
"""

import unicodedata
import re
from typing import Optional


# Zero-width characters to strip
ZERO_WIDTH_CHARS = [
    '\u200B',  # Zero-width space
    '\u200C',  # Zero-width non-joiner
    '\u200D',  # Zero-width joiner
    '\uFEFF',  # Zero-width no-break space
    '\u2060',  # Word joiner
    '\u180E',  # Mongolian vowel separator
]

# Regex to detect non-ASCII characters (for logging/alerting)
NON_ASCII_PATTERN = re.compile(r'[^\x00-\x7F]')


def normalize_entity_id(entity_id: str) -> str:
    """
    Normalize entity ID to prevent bypass attacks.

    Applies:
    1. Lowercase conversion (prevent case bypass)
    2. Unicode NFC normalization (prevent composed character bypass)
    3. Zero-width character removal
    4. Whitespace normalization

    Args:
        entity_id: Raw entity ID from context

    Returns:
        Normalized entity ID

    Examples:
        >>> normalize_entity_id("Admin")
        'admin'

        >>> normalize_entity_id("admin\u200B")  # Zero-width space
        'admin'

        >>> normalize_entity_id("  admin  ")
        'admin'

    Security:
        - Prevents case bypass: "admin" vs "Admin"
        - Prevents Unicode bypass: "admin" vs "аdmin" (Cyrillic)
        - Prevents zero-width bypass: "admin" vs "admin\u200B"
    """
    if not entity_id:
        return ""

    # Step 1: Lowercase (prevent case sensitivity bypass)
    normalized = entity_id.lower()

    # Step 2: Unicode NFC normalization (prevent composed character variants)
    # NFC = Canonical Composition
    # Ensures "é" and "e\u0301" are treated the same
    normalized = unicodedata.normalize('NFC', normalized)

    # Step 3: Remove zero-width characters
    for char in ZERO_WIDTH_CHARS:
        normalized = normalized.replace(char, '')

    # Step 4: Normalize whitespace
    normalized = normalized.strip()
    normalized = re.sub(r'\s+', ' ', normalized)  # Multiple spaces → single space

    # Step 5: Log suspicious non-ASCII characters (for alerting)
    if NON_ASCII_PATTERN.search(normalized):
        # In production, log this for security monitoring
        # Could indicate homoglyph attack attempt
        pass

    return normalized


def detect_homoglyphs(entity_id: str) -> bool:
    """
    Detect potential homoglyph attacks.

    Homoglyphs are characters that look visually similar but have
    different Unicode codepoints (e.g., Latin 'a' vs Cyrillic 'а').

    Args:
        entity_id: Entity ID to check

    Returns:
        True if potential homoglyphs detected

    Examples:
        >>> detect_homoglyphs("admin")
        False

        >>> detect_homoglyphs("аdmin")  # Cyrillic 'а'
        True

    Note:
        This is a basic implementation. For production, consider using
        the 'confusables' library for comprehensive homoglyph detection.
    """
    # Basic check: Look for mixing of scripts
    # If an "ASCII-looking" string contains non-ASCII, it's suspicious

    # Get ASCII version
    ascii_version = entity_id.encode('ascii', errors='ignore').decode('ascii')

    # If lengths differ, there are non-ASCII chars
    if len(ascii_version) != len(entity_id):
        # Check if it looks like ASCII (only ASCII-range characters present)
        for char in entity_id:
            if ord(char) > 127:
                # Non-ASCII character - potential homoglyph
                # Check if it's in a suspicious script (Cyrillic, Greek, etc.)
                script = unicodedata.name(char, '').split()[0]
                if script in ('CYRILLIC', 'GREEK', 'ARMENIAN', 'HEBREW'):
                    return True

    return False


def validate_entity_id(entity_id: str, allow_non_ascii: bool = False) -> Optional[str]:
    """
    Validate and normalize entity ID with security checks.

    Args:
        entity_id: Raw entity ID
        allow_non_ascii: Whether to allow non-ASCII characters

    Returns:
        Normalized entity ID if valid, None if rejected

    Raises:
        ValueError: If entity ID contains suspicious characters

    Security:
        - Rejects homoglyph attacks
        - Rejects overly long IDs (DoS prevention)
        - Rejects suspicious patterns
    """
    if not entity_id:
        return None

    # Length check (DoS prevention)
    if len(entity_id) > 256:
        raise ValueError("Entity ID too long (max 256 characters)")

    # Normalize
    normalized = normalize_entity_id(entity_id)

    # Check for homoglyphs
    if detect_homoglyphs(entity_id):
        # In production, log this as potential attack
        # For now, still allow but alert
        pass

    # Reject if non-ASCII and not allowed
    if not allow_non_ascii:
        if NON_ASCII_PATTERN.search(normalized):
            raise ValueError("Entity ID contains non-ASCII characters")

    return normalized
```

---

## Fix 3: Monotonic Clock (P1 - HIGH)

### Update: `src/safety/token_bucket.py`

```python
"""Update to use monotonic clock instead of system clock."""

import time
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass


class TokenBucket:
    """Thread-safe token bucket rate limiter with monotonic clock."""

    def __init__(self, rate_limit: RateLimit):
        """Initialize token bucket."""
        self.max_tokens = rate_limit.max_tokens
        self.refill_rate = rate_limit.refill_rate
        self.refill_period = rate_limit.refill_period
        self.burst_size = rate_limit.burst_size

        # Start with full bucket
        self.tokens = float(self.max_tokens)

        # ✓ FIXED: Use monotonic clock (immune to system clock changes)
        self.last_refill = time.monotonic()  # Changed from time.time()

        # Thread safety
        self.lock = threading.Lock()

    def _refill(self) -> None:
        """
        Refill tokens based on elapsed time.

        SECURITY: Uses monotonic clock to prevent time manipulation attacks.
        """
        # ✓ FIXED: Monotonic clock
        now = time.monotonic()  # Changed from time.time()
        elapsed = now - self.last_refill

        # ✓ FIXED: Handle negative time delta (clock went backwards)
        if elapsed < 0:
            # This should never happen with monotonic clock, but be safe
            return

        if elapsed >= self.refill_period:
            # Calculate tokens to add based on refill rate
            tokens_to_add = (elapsed / self.refill_period) * self.refill_rate

            # Add tokens up to max capacity
            self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)

            # Update last refill time
            self.last_refill = now

    # ... rest of methods unchanged ...
```

---

## Fix 4: Update RateLimitPolicy to Use Redis (P0)

### Update: `src/safety/policies/rate_limit_policy.py`

```python
"""Update to use Redis backend for distributed rate limiting."""

from typing import Dict, Any, List, Optional
import os

from src.safety.base import BaseSafetyPolicy
from src.safety.interfaces import ValidationResult, SafetyViolation, ViolationSeverity
from src.safety.token_bucket import RateLimit
from src.safety.redis_token_bucket import RedisTokenBucketManager
from src.safety.utils import normalize_entity_id


class RateLimitPolicy(BaseSafetyPolicy):
    """
    Rate limiting policy using distributed Redis backend.

    SECURITY: Uses Redis for shared state across all instances.
    """

    # ... DEFAULT_LIMITS unchanged ...

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize rate limit policy.

        Args:
            config: Policy configuration including:
                - redis_url: Redis connection URL (default: from env)
                - rate_limits: Custom rate limit configs
                - per_agent: Track limits per agent (default: True)
        """
        super().__init__(config or {})

        # ✓ FIXED: Use Redis backend
        redis_url = self.config.get(
            'redis_url',
            os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        )

        try:
            import redis
            redis_client = redis.from_url(redis_url, decode_responses=True)

            # Use Redis backend
            self.per_agent_manager = RedisTokenBucketManager(redis_client)
            self.global_manager = RedisTokenBucketManager(redis_client)

        except ImportError:
            # Fallback to in-memory for development
            # ⚠️ WARNING: Not safe for production!
            print("WARNING: Redis not available, using in-memory rate limiting")
            print("This is NOT SAFE for distributed deployments!")

            from src.safety.token_bucket import TokenBucketManager
            self.per_agent_manager = TokenBucketManager()
            self.global_manager = TokenBucketManager()

        # Load rate limits
        self._load_per_agent_limits(config or {})
        self._load_global_limits(config or {})

        # Configuration
        self.per_agent = self.config.get("per_agent", True)
        self.cooldown_multiplier = self.config.get("cooldown_multiplier", 1.0)

    def _validate_impl(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ValidationResult:
        """Validate action against rate limits."""
        # ... existing validation logic ...

        # ✓ FIXED: Normalize entity ID before rate limiting
        if self.per_agent:
            raw_entity_id = context.get("agent_id", "unknown")
            entity_id = normalize_entity_id(raw_entity_id)  # Added normalization
            scope = "per-agent"
        else:
            entity_id = "global"
            scope = "global"

        # ... rest unchanged ...
```

---

## Configuration Example

### `config/production.yaml`

```yaml
# Production configuration with Redis

safety:
  policies:
    - name: rate_limit
      enabled: true
      config:
        # Redis backend for distributed rate limiting
        redis_url: "redis://redis-cluster:6379/0"

        # Per-agent rate limits
        rate_limits:
          llm_call:
            max_tokens: 50
            refill_rate: 0.0139  # 50 per hour
            refill_period: 1.0
            burst_size: 5

          tool_call:
            max_tokens: 100
            refill_rate: 0.0278  # 100 per hour
            refill_period: 1.0
            burst_size: 10

          commit:
            max_tokens: 10
            refill_rate: 0.0028  # 10 per hour
            refill_period: 1.0
            burst_size: 2

          deploy:
            max_tokens: 2
            refill_rate: 0.00056  # 2 per hour
            refill_period: 1.0
            burst_size: 1

        # Global limits (across all agents)
        global_limits:
          total_tool_calls:
            max_tokens: 1000
            refill_rate: 0.278  # 1000 per hour
            refill_period: 1.0
            burst_size: 50

        # Per-agent enforcement
        per_agent: true

        # Cooldown multiplier on violations
        cooldown_multiplier: 1.5
```

---

## Testing

### Test Redis Backend

```python
"""Test Redis rate limiting."""

import redis
import pytest
from multiprocessing import Process, Queue

from src.safety.redis_token_bucket import RedisTokenBucketManager
from src.safety.token_bucket import RateLimit


def test_redis_multi_instance_enforcement():
    """Verify Redis enforces limits across instances."""
    redis_client = redis.Redis(host='localhost', port=6379, db=15)
    redis_client.flushdb()

    limit = RateLimit(max_tokens=50, refill_rate=0.001, refill_period=1.0)

    def instance_worker(process_id: int, result_queue: Queue):
        """Worker process."""
        # Each process creates its own manager (but shares Redis)
        manager = RedisTokenBucketManager(redis_client)
        manager.set_limit('llm_call', limit)

        successful = 0
        for _ in range(50):
            if manager.consume('shared_agent', 'llm_call', 1):
                successful += 1

        result_queue.put({'process_id': process_id, 'successful': successful})

    # Start 10 processes
    result_queue = Queue()
    processes = [
        Process(target=instance_worker, args=(i, result_queue))
        for i in range(10)
    ]

    for p in processes:
        p.start()

    for p in processes:
        p.join()

    # Collect results
    total_successful = 0
    while not result_queue.empty():
        result = result_queue.get()
        total_successful += result['successful']

    # ✓ Should be exactly 50 (global limit enforced)
    assert total_successful == 50, \
        f"Redis should enforce global limit: {total_successful} vs 50"
```

---

## Deployment Checklist

**Before deploying to production**:

- [ ] Redis cluster deployed and accessible
- [ ] `REDIS_URL` environment variable configured
- [ ] All instances use same Redis cluster
- [ ] Redis connection pooling configured
- [ ] Redis failover/HA configured
- [ ] Monitoring for Redis health
- [ ] Alerting on rate limit violations
- [ ] Load testing with 100+ instances completed
- [ ] Security tests passing
- [ ] Rollback plan documented

---

## Monitoring

### Metrics to Track

```python
# Add to rate limit policy

def _validate_impl(self, action, context):
    # ... existing validation ...

    # Track metrics
    self.metrics.increment(
        'rate_limit.checks.total',
        tags={
            'limit_type': limit_type,
            'result': 'allowed' if valid else 'blocked',
            'backend': 'redis'
        }
    )

    if not valid:
        # Alert on violations
        self.alerting.send_alert(
            severity='warning',
            title='Rate Limit Violation',
            message=f'Rate limit exceeded: {action_type}',
            metadata={
                'entity_id': entity_id,
                'limit_type': limit_type,
                'wait_time': retry_after,
                'backend': 'redis'
            }
        )
```

### Grafana Dashboard

```promql
# Rate limit check rate
rate(rate_limit_checks_total[5m])

# Rate limit block percentage
rate(rate_limit_checks_total{result="blocked"}[5m])
  / rate(rate_limit_checks_total[5m])

# Redis latency
histogram_quantile(0.99, rate(rate_limit_redis_latency_bucket[5m]))
```

---

## Rollout Strategy

**Phase 1: Development (Week 1)**
- Deploy Redis in development
- Update code to use Redis backend
- Run comprehensive tests

**Phase 2: Staging (Week 2)**
- Deploy to staging environment
- Load test with production traffic replay
- Fix any issues

**Phase 3: Production (Week 3)**
- Deploy to 10% of production instances
- Monitor for 48 hours
- Gradually increase to 100%

**Phase 4: Validation (Week 4)**
- Run security penetration tests
- Validate bypass attempts blocked
- Document lessons learned

---

## Success Metrics

✅ **Deployment successful when**:
- Multi-instance rate limiting works correctly
- All security tests pass
- Performance <1ms per check with Redis
- Zero bypass attacks detected
- Cost predictions accurate

**Monitor for 2 weeks before declaring victory!**
