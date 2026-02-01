# Distributed Rate Limiting Security Analysis

**Status**: CRITICAL VULNERABILITIES IDENTIFIED
**Date**: 2026-01-31
**Scope**: Rate limiting bypass scenarios in distributed deployments

---

## Executive Summary

The current rate limiting implementation (`src/safety/rate_limiter.py`, `src/safety/token_bucket.py`, `src/safety/policies/rate_limit_policy.py`) is **NOT SAFE for distributed deployments**. All rate limiting is performed in-memory with **NO shared state mechanism** (Redis, database, etc.), allowing attackers to trivially bypass limits by:

1. Distributing requests across multiple instances
2. Exploiting agent ID case sensitivity
3. Leveraging clock skew between instances
4. Exploiting race conditions in token bucket refills

**Risk Level**: CRITICAL - Complete bypass of rate limiting in production multi-instance deployments

---

## Architecture Analysis

### Current Implementation

**File**: `src/safety/token_bucket.py`
```python
class TokenBucket:
    def __init__(self, rate_limit: RateLimit):
        # IN-MEMORY ONLY - NOT SHARED ACROSS PROCESSES
        self.tokens = float(self.max_tokens)
        self.last_refill = time.time()
        self.lock = threading.Lock()  # ⚠️ Thread-safe BUT NOT process-safe
```

**File**: `src/safety/policies/rate_limit_policy.py`
```python
class RateLimitPolicy(BaseSafetyPolicy):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # IN-MEMORY MANAGERS - NO DISTRIBUTED STATE
        self.per_agent_manager = TokenBucketManager()  # ⚠️ Local only
        self.global_manager = TokenBucketManager()      # ⚠️ Local only
```

**File**: `src/safety/rate_limiter.py`
```python
class RateLimiterPolicy(BaseSafetyPolicy):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # IN-MEMORY HISTORY - NOT SHARED
        self._operation_history: Dict[tuple[str, str], List[float]] = defaultdict(list)
```

### Critical Finding

**NONE of the rate limiting implementations use distributed state.** All state is in-memory, meaning:
- Each process/instance has its own rate limit counters
- Limits are enforced PER INSTANCE, not globally
- An attacker with 10 instances gets 10x the rate limit

---

## Vulnerability Analysis

### 1. CRITICAL: Multi-Instance Rate Limit Bypass

**Severity**: CRITICAL
**CVSS Score**: 9.1 (AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H)

**Attack Vector**:
```python
# Attacker deploys 10 instances of the application
# Each instance has independent in-memory rate limiters

# Instance 1: Makes 100 requests (hits limit)
for i in range(100):
    make_llm_call()  # Allowed

make_llm_call()  # BLOCKED by instance 1

# Instance 2-10: Each makes 100 requests
# Total: 1000 requests instead of 100 limit
# NO ENFORCEMENT across instances
```

**Impact**:
- Complete bypass of rate limits in production
- API quota violations
- Cost overruns
- Resource exhaustion attacks

**Proof of Concept**:
```python
# Start 10 processes of the same application
# Each has rate limit of 50 LLM calls/hour

import multiprocessing

def bypass_rate_limit(process_id):
    """Each process gets its own 50 calls/hour."""
    policy = RateLimitPolicy()  # Fresh in-memory state

    for i in range(50):
        # All 50 allowed per process
        result = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "attacker"}
        )
        assert result.valid  # All pass!

    # Total: 10 * 50 = 500 calls instead of 50 limit

processes = [
    multiprocessing.Process(target=bypass_rate_limit, args=(i,))
    for i in range(10)
]

for p in processes:
    p.start()

# Bypass successful: 500 calls made with 50/hour limit
```

---

### 2. CRITICAL: Agent ID Case Sensitivity Bypass

**Severity**: CRITICAL
**CVSS Score**: 8.6

**Vulnerability**: Agent IDs are treated case-sensitively, allowing bypass via ID manipulation.

**Attack Vector**:
```python
# Each variation gets separate rate limit bucket
contexts = [
    {"agent_id": "attacker"},
    {"agent_id": "Attacker"},
    {"agent_id": "ATTACKER"},
    {"agent_id": "aTtAcKeR"},
]

for context in contexts:
    for i in range(50):
        # Each ID gets fresh 50 calls
        policy.validate(
            action={"operation": "llm_call"},
            context=context
        )

# Total: 200 calls instead of 50 limit
```

**Code Analysis**:
```python
# src/safety/policies/rate_limit_policy.py:223
entity_id = context.get("agent_id", "unknown")  # ⚠️ Case-sensitive

# Creates separate buckets:
# ("llm_call", "attacker")
# ("llm_call", "Attacker")  # Different bucket!
```

**Fix Required**: Normalize agent IDs to lowercase before rate limiting.

---

### 3. HIGH: Unicode Normalization Bypass

**Severity**: HIGH
**CVSS Score**: 7.8

**Vulnerability**: Unicode homoglyphs and normalization variants create separate rate limit buckets.

**Attack Vector**:
```python
# Visually identical but different Unicode
agent_ids = [
    "admin",           # ASCII
    "аdmin",           # Cyrillic 'а'
    "admin\u200B",     # Zero-width space
    "admin\uFEFF",     # Zero-width no-break space
    "ａｄｍｉｎ",      # Full-width characters
]

# Each creates separate rate limit bucket
for agent_id in agent_ids:
    for i in range(50):
        policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": agent_id}
        )

# Total: 250 calls instead of 50 limit
```

**Fix Required**: Apply Unicode normalization (NFC) and homoglyph detection.

---

### 4. HIGH: Clock Skew Exploitation

**Severity**: HIGH
**CVSS Score**: 7.4

**Vulnerability**: Token bucket refill uses `time.time()` which can be manipulated or skewed.

**Attack Vector 1: System Clock Manipulation**:
```python
# Attacker with container/VM control
import time

# Initial state: 0 tokens remaining
assert bucket.get_tokens() == 0.0

# Manipulate system clock forward 1 hour
os.system("date -s '+1 hour'")

# Bucket refills based on system time!
tokens = bucket.get_tokens()
assert tokens == 50.0  # Full refill instantly
```

**Attack Vector 2: NTP Manipulation**:
```python
# Attacker compromises NTP server
# Sets time forward periodically

while True:
    # Make requests until rate limited
    while policy.validate(action, context).valid:
        make_request()

    # Wait for NTP to push time forward
    time.sleep(60)

    # Refill happens automatically via clock skew
```

**Code Vulnerability**:
```python
# src/safety/token_bucket.py:156
now = time.time()  # ⚠️ Uses system clock
elapsed = now - self.last_refill

# If attacker manipulates clock, elapsed can be arbitrary
```

**Fix Required**: Use monotonic clock (`time.monotonic()`) for elapsed time calculations.

---

### 5. MEDIUM: Race Condition in Refill Calculation

**Severity**: MEDIUM
**CVSS Score**: 6.5

**Vulnerability**: Refill calculation has race condition between `_refill()` and token consumption.

**Attack Vector**:
```python
import threading

bucket = TokenBucket(RateLimit(max_tokens=10, refill_rate=1.0))

# Consume all tokens
bucket.consume(10)

def exploit_refill():
    """Exploit race between refill check and consumption."""
    for _ in range(1000):
        # Rapid-fire consumption attempts during refill
        bucket.consume(1)

# Spawn many threads
threads = [threading.Thread(target=exploit_refill) for _ in range(10)]
for t in threads:
    t.start()

# Some consumptions succeed during refill race window
```

**Code Analysis**:
```python
# src/safety/token_bucket.py:123
def consume(self, tokens: int = 1) -> bool:
    with self.lock:
        self._refill()  # Calculate refill

        if self.tokens >= tokens:
            self.tokens -= tokens  # ⚠️ Race window between refill and consumption
            return True

        return False
```

**Issue**: While thread-safe via lock, the refill calculation can be gamed by precise timing of consumption attempts.

---

### 6. MEDIUM: Cache Collision via Entity Key Manipulation

**Severity**: MEDIUM
**CVSS Score**: 6.3

**Vulnerability**: Entity key generation allows collisions through context manipulation.

**Attack Vector**:
```python
# src/safety/rate_limiter.py:93
def _get_entity_key(self, context: Dict[str, Any]) -> str:
    if not self.per_entity:
        return "global"

    return (
        context.get("agent_id") or
        context.get("user_id") or
        context.get("workflow_id") or
        "global"
    )

# Attacker crafts contexts to collide:
contexts = [
    {"user_id": None, "workflow_id": "admin"},  # Falls through to "admin"
    {"agent_id": None, "user_id": "admin"},     # Falls through to "admin"
    {"agent_id": "admin"},                      # Direct "admin"
]

# All share the same rate limit bucket!
# If legitimate admin uses bucket, attacker gets blocked
```

**Fix Required**: Generate deterministic composite key from ALL available IDs.

---

### 7. LOW: Memory Exhaustion via Bucket Proliferation

**Severity**: LOW
**CVSS Score**: 4.3

**Vulnerability**: Unbounded growth of token bucket storage in memory.

**Attack Vector**:
```python
# Generate unique agent IDs to create buckets
import uuid

for i in range(1_000_000):
    unique_id = str(uuid.uuid4())
    policy.validate(
        action={"operation": "llm_call"},
        context={"agent_id": unique_id}
    )

# Creates 1M token buckets in memory
# Each bucket consumes ~200 bytes
# Total: ~200 MB memory exhaustion
```

**Code Issue**:
```python
# src/safety/token_bucket.py:293
self.buckets: Dict[Tuple[str, str], TokenBucket] = {}  # ⚠️ Unbounded growth
```

**Fix Required**: Implement LRU cache with max size or TTL-based eviction.

---

## Attack Scenarios

### Scenario 1: Distributed Denial of Wallet (DoW)

**Attacker Goal**: Exhaust API quotas and incur costs

```python
# Deploy 100 instances of compromised application
# Each instance has 50 LLM calls/hour limit

# Attack coordination:
# - Each instance makes 50 calls/hour
# - Total: 5000 calls/hour instead of 50
# - Monthly cost: $15,000 instead of $150

# No distributed enforcement = complete bypass
```

**Impact**: 100x cost overrun, API quota exhaustion

---

### Scenario 2: Resource Exhaustion Attack

**Attacker Goal**: Overwhelm backend services

```python
# Bypass rate limits via case sensitivity
agent_ids = [f"agent_{i}" for i in range(1000)]
agent_ids += [f"Agent_{i}" for i in range(1000)]  # Case variations

# Each ID gets separate rate limit
# Total: 100,000 requests instead of 100
```

**Impact**: Backend service degradation, legitimate users blocked

---

### Scenario 3: Privilege Escalation via Clock Manipulation

**Attacker Goal**: Bypass deployment rate limits

```python
# Container with CAP_SYS_TIME capability
import subprocess

while True:
    # Make deployments until rate limited
    while can_deploy():
        trigger_deployment()

    # Manipulate clock forward
    subprocess.run(["date", "-s", "+1 hour"])

    # Rate limit resets, continue deploying
```

**Impact**: Unauthorized deployments, production instability

---

## Recommended Security Test Cases

### Test Suite 1: Distributed Bypass Tests

```python
class TestDistributedRateLimitBypass:
    """CRITICAL: Verify rate limits work across instances."""

    def test_multi_instance_rate_limit_enforcement(self):
        """
        CRITICAL: Verify rate limits enforced across multiple processes.

        Attack: Deploy N instances, each makes max_requests
        Expected: Total requests <= global_limit
        Actual: Total requests = N * per_instance_limit (BYPASS)
        """
        num_instances = 10
        per_instance_limit = 50
        global_limit = 50

        # TODO: Implement shared Redis state
        # Currently: VULNERABLE - each instance has separate limit
        pass

    def test_rate_limit_with_redis_backend(self):
        """
        CRITICAL: Verify Redis-backed distributed rate limiting.

        Required:
        - Shared Redis instance for token buckets
        - Atomic increment operations
        - Distributed locks for refill calculations
        """
        # TODO: Implement RedisTokenBucket
        pass

    def test_rate_limit_survives_instance_restart(self):
        """
        HIGH: Verify rate limit state persists across restarts.

        Attack: Restart instance to reset in-memory counters
        Expected: Rate limit state preserved
        """
        pass
```

### Test Suite 2: Agent ID Manipulation Tests

```python
class TestAgentIDSecurityBypass:
    """CRITICAL: Verify agent ID normalization prevents bypass."""

    def test_case_insensitive_agent_id(self):
        """
        CRITICAL: Verify case variations don't create separate buckets.

        Attack: Use "agent", "Agent", "AGENT" to bypass
        Expected: All treated as same entity
        Actual: Separate buckets (VULNERABLE)
        """
        policy = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": {"max_tokens": 2, "refill_rate": 0.001}
            }
        })

        # Consume limit with lowercase
        r1 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "attacker"}
        )
        assert r1.valid

        r2 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "attacker"}
        )
        assert r2.valid

        # Third request should be blocked
        r3 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "attacker"}
        )
        assert not r3.valid  # Blocked

        # Bypass with uppercase (SHOULD BE BLOCKED)
        r4 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "ATTACKER"}  # Different case
        )

        # VULNERABILITY: r4.valid == True (bypass successful)
        assert not r4.valid, "Case variation should not bypass rate limit"

    def test_unicode_normalization_prevents_bypass(self):
        """
        HIGH: Verify Unicode normalization prevents homoglyph bypass.

        Attack: Use Cyrillic 'а' instead of Latin 'a'
        Expected: Normalized to same entity
        """
        policy = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": {"max_tokens": 1, "refill_rate": 0.001}
            }
        })

        # Consume limit
        r1 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "admin"}  # Latin
        )
        assert r1.valid

        # Try bypass with Cyrillic
        r2 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "аdmin"}  # Cyrillic 'а'
        )

        # VULNERABILITY: r2.valid == True (bypass successful)
        assert not r2.valid, "Unicode homoglyph should not bypass"

    def test_zero_width_character_bypass(self):
        """
        MEDIUM: Verify zero-width characters don't create separate buckets.
        """
        policy = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": {"max_tokens": 1, "refill_rate": 0.001}
            }
        })

        r1 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "admin"}
        )
        assert r1.valid

        # Try bypass with zero-width space
        r2 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "admin\u200B"}  # Zero-width space
        )

        assert not r2.valid, "Zero-width characters should be stripped"
```

### Test Suite 3: Clock Skew & Timing Attacks

```python
class TestClockSkewExploitation:
    """HIGH: Verify clock manipulation doesn't bypass limits."""

    def test_monotonic_clock_for_refill(self):
        """
        HIGH: Verify refill uses monotonic clock (not wall clock).

        Attack: Manipulate system clock to trigger instant refill
        Expected: Refill based on monotonic time
        Actual: Uses time.time() (VULNERABLE)
        """
        from unittest.mock import patch

        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))
        bucket.consume(10)  # Empty bucket

        # Mock system clock jumping forward
        with patch('src.safety.token_bucket.time') as mock_time:
            mock_time.time.return_value = time.time() + 3600  # +1 hour

            # Refill should NOT happen (should use monotonic clock)
            tokens = bucket.get_tokens()

            # VULNERABILITY: tokens == 10.0 (instant refill)
            assert tokens < 1.0, "Clock manipulation should not trigger refill"

    def test_refill_rate_limits_max_tokens_per_refill(self):
        """
        MEDIUM: Verify refill caps at max_tokens even with large time jumps.
        """
        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))
        bucket.consume(10)

        # Simulate massive time jump
        with patch('src.safety.token_bucket.time') as mock_time:
            initial_time = bucket.last_refill
            mock_time.time.return_value = initial_time + 1_000_000  # +11 days

            tokens = bucket.get_tokens()

            # Should cap at max_tokens
            assert tokens == 10.0, "Refill should cap at max_tokens"

    def test_negative_time_delta_handled_safely(self):
        """
        MEDIUM: Verify negative time delta doesn't cause refill.

        Attack: Set clock backwards to cause negative elapsed time
        """
        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))
        bucket.consume(10)

        with patch('src.safety.token_bucket.time') as mock_time:
            initial_time = bucket.last_refill
            mock_time.time.return_value = initial_time - 3600  # -1 hour

            tokens = bucket.get_tokens()

            # Should not refill with negative time
            assert tokens == 0.0, "Negative time delta should not refill"
```

### Test Suite 4: Race Condition Tests

```python
class TestRaceConditionExploits:
    """MEDIUM: Verify no race conditions in token consumption."""

    def test_concurrent_consumption_during_refill(self):
        """
        MEDIUM: Verify concurrent consumption during refill doesn't exceed limit.

        Attack: Precisely time consumption during refill window
        """
        import threading

        bucket = TokenBucket(RateLimit(10, 10.0, 0.1))  # Fast refill
        bucket.consume(10)  # Empty

        consumed_count = {"value": 0}
        lock = threading.Lock()

        def rapid_consume():
            """Try to consume during refill window."""
            for _ in range(100):
                if bucket.consume(1):
                    with lock:
                        consumed_count["value"] += 1

        # Wait for partial refill
        time.sleep(0.05)  # Half refill period

        # Launch concurrent consumers
        threads = [threading.Thread(target=rapid_consume) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify didn't exceed refill amount
        # In 0.05s, should refill ~0.5 tokens
        assert consumed_count["value"] <= 1, \
            f"Race condition allowed {consumed_count['value']} consumptions"

    def test_check_and_consume_atomic(self):
        """
        HIGH: Verify token check and consumption is atomic.
        """
        bucket = TokenBucket(RateLimit(1, 0.001, 1.0))

        results = []

        def try_consume():
            # Simulate check-then-consume pattern (BAD)
            if bucket.peek(1):
                time.sleep(0.001)  # Delay to expose race
                if bucket.consume(1):
                    results.append(True)

        threads = [threading.Thread(target=try_consume) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Only 1 should succeed
        assert len(results) == 1, f"Race allowed {len(results)} consumptions"
```

### Test Suite 5: Entity Key Collision Tests

```python
class TestEntityKeyCollisions:
    """MEDIUM: Verify entity key generation is collision-resistant."""

    def test_no_collision_with_missing_fields(self):
        """
        MEDIUM: Verify missing context fields don't cause collisions.
        """
        policy = RateLimiterPolicy(config={
            "limits": {"llm_call": {"max_per_minute": 1}}
        })

        # Context 1: Has agent_id
        context1 = {"agent_id": "user1"}

        # Context 2: No agent_id, has user_id="user1"
        context2 = {"user_id": "user1"}

        # Both resolve to "user1" - COLLISION
        key1 = policy._get_entity_key(context1)
        key2 = policy._get_entity_key(context2)

        # VULNERABILITY: key1 == key2 == "user1"
        assert key1 != key2, "Different context sources should not collide"

    def test_composite_entity_key_generation(self):
        """
        HIGH: Verify entity keys are composite to prevent collisions.

        Recommended format: "{agent_id}:{user_id}:{workflow_id}"
        """
        policy = RateLimiterPolicy()

        contexts = [
            {"agent_id": "a", "user_id": "b"},
            {"agent_id": "ab", "user_id": None},
        ]

        keys = [policy._get_entity_key(ctx) for ctx in contexts]

        # Should generate different keys
        assert len(set(keys)) == len(keys), "Entity keys must be unique"
```

---

## Recommended Fixes (Priority Order)

### P0 (CRITICAL - Implement Immediately)

1. **Implement Redis-backed distributed rate limiting**
   ```python
   class RedisTokenBucket:
       """Distributed token bucket using Redis."""

       def __init__(self, redis_client, key_prefix: str, rate_limit: RateLimit):
           self.redis = redis_client
           self.key = f"{key_prefix}:tokens"
           self.refill_key = f"{key_prefix}:last_refill"
           self.rate_limit = rate_limit

       def consume(self, tokens: int = 1) -> bool:
           """Atomically consume tokens using Redis Lua script."""
           lua_script = """
           local key = KEYS[1]
           local refill_key = KEYS[2]
           local max_tokens = tonumber(ARGV[1])
           local refill_rate = tonumber(ARGV[2])
           local refill_period = tonumber(ARGV[3])
           local tokens_to_consume = tonumber(ARGV[4])
           local now = tonumber(ARGV[5])

           -- Get current state
           local current_tokens = tonumber(redis.call('GET', key) or max_tokens)
           local last_refill = tonumber(redis.call('GET', refill_key) or now)

           -- Calculate refill
           local elapsed = now - last_refill
           if elapsed >= refill_period then
               local tokens_to_add = (elapsed / refill_period) * refill_rate
               current_tokens = math.min(max_tokens, current_tokens + tokens_to_add)
               redis.call('SET', refill_key, now)
           end

           -- Try to consume
           if current_tokens >= tokens_to_consume then
               redis.call('SET', key, current_tokens - tokens_to_consume)
               return 1
           else
               redis.call('SET', key, current_tokens)
               return 0
           end
           """

           result = self.redis.eval(
               lua_script,
               2,  # Number of keys
               self.key,
               self.refill_key,
               self.rate_limit.max_tokens,
               self.rate_limit.refill_rate,
               self.rate_limit.refill_period,
               tokens,
               time.time()
           )

           return result == 1
   ```

2. **Normalize agent IDs before rate limiting**
   ```python
   import unicodedata

   def normalize_entity_id(entity_id: str) -> str:
       """Normalize entity ID to prevent bypass via case/Unicode manipulation."""
       if not entity_id:
           return ""

       # Lowercase
       normalized = entity_id.lower()

       # Unicode normalization (NFC)
       normalized = unicodedata.normalize('NFC', normalized)

       # Remove zero-width characters
       zero_width_chars = [
           '\u200B',  # Zero-width space
           '\u200C',  # Zero-width non-joiner
           '\u200D',  # Zero-width joiner
           '\uFEFF',  # Zero-width no-break space
       ]
       for char in zero_width_chars:
           normalized = normalized.replace(char, '')

       # Detect and reject homoglyphs
       # (Consider using confusables library)

       return normalized
   ```

3. **Use monotonic clock for refill calculations**
   ```python
   class TokenBucket:
       def __init__(self, rate_limit: RateLimit):
           # Use monotonic clock (not affected by system time changes)
           self.last_refill = time.monotonic()

       def _refill(self) -> None:
           now = time.monotonic()  # ✓ Monotonic clock
           elapsed = now - self.last_refill

           # Ensure elapsed is non-negative
           if elapsed < 0:
               return  # Clock went backwards - don't refill

           if elapsed >= self.refill_period:
               tokens_to_add = (elapsed / self.refill_period) * self.refill_rate
               self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
               self.last_refill = now
   ```

### P1 (HIGH - Implement This Sprint)

4. **Implement LRU cache for token buckets**
   ```python
   from functools import lru_cache
   from collections import OrderedDict

   class TokenBucketManager:
       def __init__(self, max_buckets: int = 10000):
           self.buckets = OrderedDict()
           self.max_buckets = max_buckets
           self.lock = threading.Lock()

       def get_bucket(self, entity_id: str, limit_type: str):
           bucket_key = (entity_id, limit_type)

           with self.lock:
               # Move to end (most recently used)
               if bucket_key in self.buckets:
                   self.buckets.move_to_end(bucket_key)
                   return self.buckets[bucket_key]

               # Create new bucket
               bucket = TokenBucket(self.limits[limit_type])
               self.buckets[bucket_key] = bucket

               # Evict oldest if over limit
               if len(self.buckets) > self.max_buckets:
                   self.buckets.popitem(last=False)

               return bucket
   ```

5. **Add rate limit metrics and alerting**
   ```python
   class RateLimitPolicy(BaseSafetyPolicy):
       def _validate_impl(self, action, context):
           # ... existing validation ...

           # Track metrics
           self.metrics.increment(
               "rate_limit.checks",
               tags={
                   "limit_type": limit_type,
                   "result": "allowed" if valid else "blocked"
               }
           )

           if not valid:
               # Alert on rate limit violations
               self.alerting.send_alert(
                   severity="warning",
                   message=f"Rate limit exceeded: {action_type}",
                   metadata={
                       "entity_id": entity_id,
                       "limit_type": limit_type,
                       "wait_time": retry_after
                   }
               )
   ```

### P2 (MEDIUM - Implement Next Sprint)

6. **Add distributed circuit breaker for rate-limited endpoints**
7. **Implement rate limit warming for legitimate traffic bursts**
8. **Add per-tenant rate limiting with Redis**

---

## Testing Checklist

**Before deploying to production**:

- [ ] Test multi-instance rate limit enforcement with Redis
- [ ] Verify agent ID normalization prevents case bypass
- [ ] Test Unicode homoglyph detection
- [ ] Verify monotonic clock prevents time manipulation
- [ ] Test race condition handling under load
- [ ] Verify LRU cache eviction works correctly
- [ ] Test rate limit metrics and alerting
- [ ] Load test with 100+ concurrent instances
- [ ] Verify no memory leaks in bucket storage
- [ ] Test failover when Redis is unavailable

---

## References

- OWASP API Security Top 10 - API4:2023 Unrestricted Resource Consumption
- NIST SP 800-95 - Guide to Secure Web Services
- Redis Lua Scripting for Atomic Rate Limiting
- Token Bucket Algorithm Best Practices
- Distributed Systems Security Considerations

---

## Conclusion

The current rate limiting implementation has **CRITICAL vulnerabilities** that allow complete bypass in distributed deployments. The in-memory state design makes it unsuitable for production multi-instance environments.

**Immediate actions required**:
1. Implement Redis-backed distributed rate limiting
2. Normalize all entity IDs (case-insensitive, Unicode-normalized)
3. Switch to monotonic clock for refill calculations
4. Add comprehensive security tests

**Timeline**:
- P0 fixes: Within 1 week
- P1 fixes: Within 2 weeks
- P2 fixes: Within 4 weeks

**Without these fixes, rate limiting provides ZERO protection in production.**
