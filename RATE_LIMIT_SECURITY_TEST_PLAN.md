# Distributed Rate Limiting Security Test Plan

**Quick Reference for Test Implementation**

---

## Test File Structure

```
tests/test_security/
├── test_distributed_rate_limiting.py      # Main test suite (NEW)
├── test_rate_limit_agent_id_bypass.py     # Agent ID manipulation (NEW)
├── test_rate_limit_timing_attacks.py      # Clock skew attacks (NEW)
└── test_rate_limit_race_conditions.py     # Concurrency exploits (NEW)
```

---

## Priority Test Matrix

| Test Case | Severity | Est. Time | Priority | Dependencies |
|-----------|----------|-----------|----------|--------------|
| Multi-instance bypass | CRITICAL | 2h | P0 | Redis, multiprocessing |
| Case sensitivity bypass | CRITICAL | 1h | P0 | None |
| Unicode homoglyph bypass | HIGH | 2h | P1 | unicodedata |
| Clock manipulation | HIGH | 1.5h | P1 | time mocking |
| Race condition exploit | MEDIUM | 2h | P2 | threading |
| Entity key collision | MEDIUM | 1h | P2 | None |
| Memory exhaustion | LOW | 1h | P3 | memory profiling |

---

## Test Template 1: Multi-Instance Bypass

**File**: `tests/test_security/test_distributed_rate_limiting.py`

```python
"""
CRITICAL Security Tests: Distributed Rate Limiting Bypass Prevention

Tests verify that rate limits cannot be bypassed by:
1. Distributing requests across multiple instances
2. Restarting instances to reset in-memory state
3. Exploiting lack of shared state

CURRENT STATUS: ALL TESTS EXPECTED TO FAIL - No distributed state implemented
"""

import pytest
import time
import redis
from multiprocessing import Process, Queue
from typing import List, Dict

from src.safety.policies.rate_limit_policy import RateLimitPolicy
from src.safety.token_bucket import RateLimit


# ============================================================================
# CRITICAL: Multi-Instance Bypass Tests
# ============================================================================

class TestMultiInstanceRateLimitBypass:
    """
    CRITICAL: Verify rate limits cannot be bypassed via multiple instances.

    Current Vulnerability:
    - Each instance has in-memory rate limiters
    - 10 instances = 10x the rate limit
    - No shared state = no global enforcement
    """

    @pytest.mark.skip(reason="Redis backend not implemented - test will fail")
    def test_multi_instance_enforces_global_limit(self):
        """
        CRITICAL: Global rate limit must be enforced across all instances.

        Attack Scenario:
        - Deploy 10 instances of application
        - Each instance makes 50 LLM calls
        - Total: 500 calls vs 50 call limit
        - Expected: Only 50 calls succeed globally
        - Actual: All 500 succeed (BYPASS)

        Fix Required: Redis-backed token bucket
        """
        num_instances = 10
        calls_per_instance = 50
        global_limit = 50

        # Shared result queue for all processes
        result_queue = Queue()

        def instance_worker(instance_id: int, result_queue: Queue):
            """Simulates one application instance."""
            # Each instance creates its own policy (in-memory state)
            policy = RateLimitPolicy(config={
                "rate_limits": {
                    "llm_call": RateLimit(
                        max_tokens=global_limit,  # Same limit
                        refill_rate=0.001,
                        refill_period=1.0
                    )
                }
            })

            successful_calls = 0
            for i in range(calls_per_instance):
                result = policy.validate(
                    action={"operation": "llm_call"},
                    context={"agent_id": "shared_agent"}  # Same agent!
                )

                if result.valid:
                    successful_calls += 1

            result_queue.put({
                "instance_id": instance_id,
                "successful_calls": successful_calls
            })

        # Start all instances
        processes: List[Process] = []
        for i in range(num_instances):
            p = Process(target=instance_worker, args=(i, result_queue))
            p.start()
            processes.append(p)

        # Wait for all to complete
        for p in processes:
            p.join(timeout=30)
            if p.is_alive():
                p.terminate()

        # Collect results
        total_successful = 0
        results = []
        while not result_queue.empty():
            result = result_queue.get()
            results.append(result)
            total_successful += result["successful_calls"]

        # VULNERABILITY: total_successful == 500 (should be 50)
        assert total_successful <= global_limit, \
            f"Multi-instance bypass detected: {total_successful} calls succeeded (limit: {global_limit})"

        # Verify each instance was blocked after global limit hit
        instances_fully_succeeded = sum(
            1 for r in results if r["successful_calls"] == calls_per_instance
        )

        # At most 1 instance should fully succeed (global_limit=50, calls_per_instance=50)
        assert instances_fully_succeeded <= 1, \
            f"{instances_fully_succeeded} instances bypassed rate limit"

    @pytest.mark.skip(reason="Redis backend not implemented")
    def test_instance_restart_does_not_reset_rate_limit(self):
        """
        CRITICAL: Restarting instance should not reset rate limit state.

        Attack Scenario:
        - Make 50 calls (hit limit)
        - Restart application instance
        - In-memory state resets
        - Make another 50 calls (bypass!)

        Fix Required: Persistent Redis state
        """
        # Create policy and exhaust limit
        policy1 = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": RateLimit(max_tokens=2, refill_rate=0.001)
            }
        })

        # Exhaust limit
        r1 = policy1.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "agent-1"}
        )
        assert r1.valid

        r2 = policy1.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "agent-1"}
        )
        assert r2.valid

        r3 = policy1.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "agent-1"}
        )
        assert not r3.valid  # Blocked

        # Simulate instance restart (new policy object)
        policy2 = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": RateLimit(max_tokens=2, refill_rate=0.001)
            }
        })

        # Try same agent again after "restart"
        r4 = policy2.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "agent-1"}  # Same agent
        )

        # VULNERABILITY: r4.valid == True (state reset on restart)
        assert not r4.valid, \
            "Instance restart should not reset rate limit state"


# ============================================================================
# CRITICAL: Agent ID Bypass Tests
# ============================================================================

class TestAgentIDBypassPrevention:
    """
    CRITICAL: Verify agent ID normalization prevents bypass.

    Current Vulnerabilities:
    - Case sensitivity: "agent" vs "Agent" vs "AGENT"
    - Unicode variants: Latin vs Cyrillic characters
    - Zero-width characters
    """

    def test_case_insensitive_agent_id_enforcement(self):
        """
        CRITICAL: Case variations should not bypass rate limit.

        Attack: Use different case variations to get multiple limits
        Expected: All variants treated as same entity
        Actual: Each case gets separate bucket (BYPASS)
        """
        policy = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": RateLimit(max_tokens=2, refill_rate=0.001)
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

        # Third call should be blocked
        r3 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "attacker"}
        )
        assert not r3.valid, "Rate limit should be enforced"

        # Try bypass with uppercase
        r4 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "ATTACKER"}  # UPPERCASE
        )

        # VULNERABILITY: r4.valid == True (bypass via case change)
        assert not r4.valid, \
            "CRITICAL: Case variation bypassed rate limit!"

        # Try other case variations
        case_variations = [
            "Attacker",
            "aTtAcKeR",
            "ATTACKER",
            "AtTaCkEr",
        ]

        for variation in case_variations:
            result = policy.validate(
                action={"operation": "llm_call"},
                context={"agent_id": variation}
            )
            assert not result.valid, \
                f"Case variation '{variation}' bypassed rate limit"

    def test_unicode_normalization_prevents_bypass(self):
        """
        HIGH: Unicode homoglyphs should not bypass rate limit.

        Attack: Use Cyrillic/Greek characters that look like Latin
        Examples:
        - Latin 'a' vs Cyrillic 'а' (U+0430)
        - Latin 'e' vs Cyrillic 'е' (U+0435)
        """
        policy = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": RateLimit(max_tokens=1, refill_rate=0.001)
            }
        })

        # Consume limit with Latin characters
        r1 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "admin"}  # Latin
        )
        assert r1.valid

        r2 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "admin"}  # Same, should be blocked
        )
        assert not r2.valid

        # Try bypass with Cyrillic homoglyphs
        cyrillic_variations = [
            "аdmin",   # Cyrillic 'а' (U+0430)
            "аdmіn",   # Cyrillic 'а' and 'і'
            "аdміn",   # Cyrillic 'а', 'м', 'і'
        ]

        for variation in cyrillic_variations:
            result = policy.validate(
                action={"operation": "llm_call"},
                context={"agent_id": variation}
            )
            # VULNERABILITY: result.valid == True for Cyrillic variants
            assert not result.valid, \
                f"Unicode homoglyph '{variation}' bypassed rate limit"

    def test_zero_width_characters_stripped(self):
        """
        MEDIUM: Zero-width characters should not create new buckets.

        Attack: Insert invisible Unicode characters
        """
        policy = RateLimitPolicy(config={
            "rate_limits": {
                "llm_call": RateLimit(max_tokens=1, refill_rate=0.001)
            }
        })

        r1 = policy.validate(
            action={"operation": "llm_call"},
            context={"agent_id": "admin"}
        )
        assert r1.valid

        # Zero-width variations
        zero_width_variations = [
            "admin\u200B",      # Zero-width space
            "admin\u200C",      # Zero-width non-joiner
            "admin\u200D",      # Zero-width joiner
            "admin\uFEFF",      # Zero-width no-break space
            "ad\u200Bmin",      # In the middle
        ]

        for variation in zero_width_variations:
            result = policy.validate(
                action={"operation": "llm_call"},
                context={"agent_id": variation}
            )
            assert not result.valid, \
                f"Zero-width variation '{repr(variation)}' bypassed rate limit"


# ============================================================================
# HIGH: Clock Manipulation Tests
# ============================================================================

class TestClockManipulationPrevention:
    """
    HIGH: Verify clock manipulation doesn't bypass rate limits.

    Vulnerabilities:
    - time.time() can be manipulated via system clock
    - NTP drift can cause unexpected refills
    - Negative time deltas not handled
    """

    def test_uses_monotonic_clock_for_refill(self):
        """
        HIGH: Refill calculations should use monotonic clock.

        Attack: Manipulate system clock to trigger instant refill
        Fix: Use time.monotonic() instead of time.time()
        """
        from unittest.mock import patch
        from src.safety.token_bucket import TokenBucket

        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))

        # Consume all tokens
        bucket.consume(10)
        assert bucket.get_tokens() == 0.0

        # Mock system clock jumping forward 1 hour
        with patch('src.safety.token_bucket.time') as mock_time:
            initial_time = time.time()
            mock_time.time.return_value = initial_time + 3600  # +1 hour

            # Get tokens (triggers refill calculation)
            tokens = bucket.get_tokens()

            # VULNERABILITY: tokens == 10.0 (instant refill via clock jump)
            # Expected: tokens == 0.0 (monotonic clock should be used)
            assert tokens < 1.0, \
                f"Clock manipulation allowed instant refill: {tokens} tokens"

    def test_negative_time_delta_does_not_refill(self):
        """
        MEDIUM: Setting clock backwards should not cause refill.

        Attack: Set system clock backwards to cause negative elapsed time
        """
        from unittest.mock import patch
        from src.safety.token_bucket import TokenBucket

        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))
        bucket.consume(10)

        with patch('src.safety.token_bucket.time') as mock_time:
            initial_time = bucket.last_refill
            mock_time.time.return_value = initial_time - 3600  # -1 hour

            tokens = bucket.get_tokens()

            # Should not refill with negative time
            assert tokens == 0.0, \
                f"Negative time delta caused refill: {tokens} tokens"

    def test_massive_time_jump_caps_at_max_tokens(self):
        """
        LOW: Extreme time jumps should cap at max_tokens.
        """
        from unittest.mock import patch
        from src.safety.token_bucket import TokenBucket

        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))
        bucket.consume(10)

        with patch('src.safety.token_bucket.time') as mock_time:
            initial_time = bucket.last_refill
            mock_time.time.return_value = initial_time + 1_000_000  # +11 days

            tokens = bucket.get_tokens()

            # Should cap at max_tokens
            assert tokens == 10.0, \
                f"Massive time jump exceeded max_tokens: {tokens}"


# ============================================================================
# MEDIUM: Race Condition Tests
# ============================================================================

class TestRaceConditionPrevention:
    """
    MEDIUM: Verify no race conditions in token bucket operations.
    """

    def test_concurrent_consumption_thread_safe(self):
        """
        MEDIUM: Concurrent consumption should not exceed available tokens.
        """
        import threading
        from src.safety.token_bucket import TokenBucket

        bucket = TokenBucket(RateLimit(100, 1.0, 1.0))

        successful_consumptions = []
        lock = threading.Lock()

        def consume_token():
            if bucket.consume(1):
                with lock:
                    successful_consumptions.append(1)

        # Spawn many threads
        threads = [threading.Thread(target=consume_token) for _ in range(150)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Only 100 should succeed (max_tokens)
        assert len(successful_consumptions) == 100, \
            f"Race condition: {len(successful_consumptions)} consumptions (expected 100)"

    def test_refill_during_consumption_no_race(self):
        """
        MEDIUM: Refill during concurrent consumption should not cause over-consumption.
        """
        import threading
        from src.safety.token_bucket import TokenBucket

        bucket = TokenBucket(RateLimit(10, 10.0, 0.1))  # Fast refill
        bucket.consume(10)  # Empty

        consumed = {"count": 0}
        lock = threading.Lock()

        def rapid_consume():
            for _ in range(100):
                if bucket.consume(1):
                    with lock:
                        consumed["count"] += 1
                time.sleep(0.001)

        # Wait for partial refill
        time.sleep(0.05)  # Half refill period

        # Concurrent consumers
        threads = [threading.Thread(target=rapid_consume) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not exceed reasonable refill amount
        # In 0.05s + thread execution time (~0.5s), ~5 tokens refilled
        assert consumed["count"] <= 10, \
            f"Race condition allowed {consumed['count']} consumptions"


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def redis_client():
    """Redis client for distributed tests."""
    try:
        client = redis.Redis(
            host='localhost',
            port=6379,
            db=15,  # Test database
            decode_responses=True
        )
        client.ping()
        yield client
        # Cleanup
        client.flushdb()
    except redis.ConnectionError:
        pytest.skip("Redis not available")


@pytest.fixture
def shared_redis_policy(redis_client):
    """Rate limit policy with Redis backend."""
    # TODO: Implement RedisTokenBucketManager
    pytest.skip("Redis backend not implemented yet")
```

---

## Test Template 2: Timing Attack Tests

**File**: `tests/test_security/test_rate_limit_timing_attacks.py`

```python
"""
Timing Attack Tests for Rate Limiting

Tests verify that timing-based attacks cannot bypass rate limits.
"""

import pytest
import time
from unittest.mock import patch

from src.safety.token_bucket import TokenBucket, RateLimit


class TestTimingAttacks:
    """Test timing-based bypass attempts."""

    def test_precise_consumption_timing_no_bypass(self):
        """
        Verify precise timing of consumption doesn't allow bypass.
        """
        bucket = TokenBucket(RateLimit(10, 1.0, 1.0))

        # Consume at precise refill intervals
        for i in range(20):
            # Wait for exact refill period
            time.sleep(1.0)

            # Try to consume more than refill rate
            result = bucket.consume(2)

            if i < 5:
                # First few should succeed (initial tokens)
                assert result, f"Iteration {i} should succeed"
            else:
                # Later ones should fail (refill rate = 1/sec, consuming 2)
                assert not result, f"Iteration {i} should be rate limited"

    def test_burst_followed_by_trickle_enforced(self):
        """
        Verify burst allowance doesn't persist indefinitely.
        """
        bucket = TokenBucket(RateLimit(
            max_tokens=10,
            refill_rate=1.0,
            burst_size=5
        ))

        # Burst: consume burst_size
        for i in range(5):
            assert bucket.consume(1), f"Burst {i} should succeed"

        # Immediate next request should work (still have tokens)
        assert bucket.consume(1), "Post-burst should work"

        # Continue until exhausted
        while bucket.consume(1):
            pass

        # Now rate limited
        assert not bucket.consume(1), "Should be rate limited after burst"

        # Wait for refill
        time.sleep(1.1)

        # Should have 1 token refilled
        assert bucket.consume(1), "Should have refilled"
        assert not bucket.consume(1), "Only 1 token refilled"
```

---

## Implementation Checklist

**Before Starting Tests**:

1. **Set up test environment**
   ```bash
   # Install Redis for distributed tests
   docker run -d -p 6379:6379 redis:latest

   # Install test dependencies
   pip install pytest pytest-asyncio redis fakeredis
   ```

2. **Create test directory structure**
   ```bash
   mkdir -p tests/test_security
   touch tests/test_security/__init__.py
   touch tests/test_security/test_distributed_rate_limiting.py
   touch tests/test_security/test_rate_limit_timing_attacks.py
   ```

3. **Run baseline tests (expect failures)**
   ```bash
   # Run and document failures
   pytest tests/test_security/test_distributed_rate_limiting.py -v \
       --tb=short -k "not skip" > baseline_failures.txt
   ```

**Implementation Order**:

1. **Week 1: Critical Tests**
   - [ ] Multi-instance bypass test
   - [ ] Case sensitivity bypass test
   - [ ] Instance restart bypass test

2. **Week 2: High Priority Tests**
   - [ ] Unicode homoglyph bypass test
   - [ ] Monotonic clock test
   - [ ] Zero-width character test

3. **Week 3: Medium Priority Tests**
   - [ ] Race condition tests
   - [ ] Entity key collision tests
   - [ ] Timing attack tests

4. **Week 4: Low Priority Tests**
   - [ ] Memory exhaustion test
   - [ ] Performance benchmarks
   - [ ] Stress tests

---

## Expected Test Results (Current Implementation)

| Test | Expected Result | Reason |
|------|----------------|--------|
| Multi-instance bypass | ❌ FAIL | No distributed state |
| Case sensitivity bypass | ❌ FAIL | No normalization |
| Unicode homoglyph bypass | ❌ FAIL | No normalization |
| Clock manipulation | ❌ FAIL | Uses time.time() |
| Race condition | ✅ PASS | Threading.Lock used |
| Entity key collision | ❌ FAIL | Simple fallback logic |

---

## Success Criteria

Tests should be considered **passing** when:

1. Multi-instance tests succeed with Redis backend
2. All agent ID variations are treated as same entity
3. Clock manipulation has no effect on refills
4. No race conditions under 100+ concurrent threads
5. Memory usage bounded under 10K unique entities
6. Performance: <1ms per rate limit check with Redis

---

## Next Steps

1. Review DISTRIBUTED_RATE_LIMITING_SECURITY_ANALYSIS.md for vulnerability details
2. Implement test suite in priority order
3. Run tests and document failures
4. Implement fixes based on test failures
5. Re-run tests until all pass
6. Perform load testing with 100+ instances
7. Security review before production deployment
