# Distributed Rate Limiting Test Design

## Executive Summary

This document provides a comprehensive test strategy for distributed rate limiting in the Meta Autonomous Framework. The current `RateLimiterPolicy` and `TokenBucket` implementation use in-memory state, which works for single processes but fails to enforce rate limits across multiple processes/instances.

**Goal**: Design and implement a test suite (`tests/test_safety/test_distributed_rate_limiting.py`) that validates distributed rate limiting behavior using Redis as a shared state backend.

---

## Current Implementation Analysis

### Existing Components

1. **`src/safety/rate_limiter.py`**: `RateLimiterPolicy`
   - Uses in-memory `defaultdict` for operation history
   - Per-entity tracking (agent_id, user_id, workflow_id)
   - Supports multiple time windows (per-second, per-minute, per-hour)
   - Thread-safe within a single process

2. **`src/safety/token_bucket.py`**: Token bucket algorithm
   - Thread-safe token bucket using `threading.Lock`
   - `TokenBucketManager` manages multiple buckets
   - In-memory state only

3. **`src/cache/llm_cache.py`**: Redis backend reference
   - Shows how to integrate Redis
   - Provides connection handling patterns

### Key Limitation

**The existing implementation stores rate limit state in-memory, making it impossible to enforce global rate limits across multiple processes or instances.**

---

## Test Architecture

### Test File Structure

```
tests/test_safety/test_distributed_rate_limiting.py
├── Fixtures (Database, Redis, Multi-process helpers)
├── 1. Basic Distributed Rate Limiting (10 tests)
├── 2. Clock Skew and Timing (5 tests)
├── 3. Cache Invalidation (5 tests)
├── 4. Agent ID Normalization (6 tests)
├── 5. Multi-Process Coordination (8 tests)
├── 6. Race Conditions and Edge Cases (8 tests)
├── 7. Failure and Recovery (6 tests)
└── 8. Performance and Scalability (4 tests)
```

**Total: 52+ test scenarios**

---

## Test Categories

### 1. Basic Distributed Rate Limiting (10 tests)

#### Test: `test_redis_backend_basic_operations`
**Purpose**: Verify Redis backend can store/retrieve rate limit data

**Setup**:
- Initialize Redis connection
- Create test key-value pairs

**Actions**:
- Set rate limit counter
- Get rate limit counter
- Delete rate limit counter
- Check expiration/TTL

**Assertions**:
- All Redis operations succeed
- TTL correctly enforced
- Data persists across reads

**Priority**: CRITICAL

---

#### Test: `test_single_process_rate_limit_with_redis`
**Purpose**: Verify rate limiting works with Redis backend in single process

**Setup**:
- Configure RateLimiter with Redis backend
- Set limit: 10 operations/minute

**Actions**:
- Perform 10 operations rapidly
- Attempt 11th operation

**Assertions**:
- First 10 operations succeed
- 11th operation is rate limited
- Wait time is calculated correctly
- Redis state matches expected counters

**Priority**: CRITICAL

---

#### Test: `test_two_processes_shared_rate_limit`
**Purpose**: Verify rate limit is enforced globally across 2 processes

**Setup**:
- Configure Redis backend with shared limit: 10 ops/minute
- Spawn 2 processes

**Actions**:
- Process 1: Perform 6 operations
- Process 2: Perform 6 operations (expecting 4 to succeed, 2 to fail)

**Assertions**:
- Total operations allowed = 10 (across both processes)
- Process 2's 5th and 6th operations are rate limited
- Both processes see consistent state in Redis

**Priority**: CRITICAL

---

#### Test: `test_three_processes_concurrent_requests`
**Purpose**: Test concurrent rate limiting with 3 processes

**Setup**:
- Redis backend, limit: 15 ops/minute
- Spawn 3 processes simultaneously

**Actions**:
- Each process attempts 10 operations concurrently

**Assertions**:
- Exactly 15 operations succeed globally
- 15 operations fail
- No race conditions (total = 30 attempts)
- Redis counters are accurate

**Priority**: CRITICAL

---

#### Test: `test_five_processes_burst_traffic`
**Purpose**: Validate rate limiting under heavy concurrent load

**Setup**:
- Redis backend, limit: 20 ops/minute
- Spawn 5 processes

**Actions**:
- All 5 processes send burst of 10 requests simultaneously

**Assertions**:
- Exactly 20 succeed, 30 fail
- No double-counting or lost operations
- Response times are reasonable (<100ms per check)

**Priority**: HIGH

---

#### Test: `test_per_agent_distributed_limits`
**Purpose**: Verify per-agent limits work across processes

**Setup**:
- Redis backend with per-agent tracking
- 2 agents, each with 10 ops/minute limit
- 2 processes

**Actions**:
- Process 1: 6 ops from agent-1
- Process 2: 6 ops from agent-2
- Process 1: 6 ops from agent-1 (4 should fail)
- Process 2: 6 ops from agent-2 (4 should fail)

**Assertions**:
- Each agent independently gets 10 operations
- Agent limits don't interfere with each other
- Total 20 ops succeed (10 per agent)

**Priority**: HIGH

---

#### Test: `test_global_and_per_agent_limits_combined`
**Purpose**: Test interaction between global and per-agent limits

**Setup**:
- Per-agent limit: 10 ops/minute
- Global limit: 15 ops/minute
- 3 agents, 3 processes

**Actions**:
- Agent 1: 10 ops (all succeed)
- Agent 2: 10 ops (5 succeed, 5 hit global limit)
- Agent 3: 10 ops (all fail - global limit)

**Assertions**:
- Per-agent limits respected
- Global limit enforced across all agents
- Total operations = 15

**Priority**: HIGH

---

#### Test: `test_different_time_windows_distributed`
**Purpose**: Verify different time windows work with Redis

**Setup**:
- Per-second limit: 5
- Per-minute limit: 60
- Per-hour limit: 1000
- 2 processes

**Actions**:
- Process 1: 3 ops rapidly
- Process 2: 3 ops rapidly (1 should fail per-second limit)
- Wait 1.5 seconds
- Process 1: 5 more ops (should succeed)

**Assertions**:
- Per-second limit enforced globally
- Per-minute limit enforced globally
- Window resets work correctly
- TTL cleanup happens

**Priority**: MEDIUM

---

#### Test: `test_operation_type_isolation`
**Purpose**: Ensure different operation types have separate limits

**Setup**:
- Redis backend
- git_commit: 10/minute
- deploy: 2/minute
- tool_call: 100/minute
- 2 processes

**Actions**:
- Process 1: 10 commits (succeed)
- Process 2: 1 deploy (succeed)
- Process 1: 1 commit (fail)
- Process 2: 1 deploy (succeed)

**Assertions**:
- Operation types are isolated
- Each type enforces its own limit
- No cross-contamination

**Priority**: MEDIUM

---

#### Test: `test_redis_connection_pool`
**Purpose**: Verify connection pooling works correctly

**Setup**:
- Configure Redis with connection pool
- 10 concurrent processes

**Actions**:
- All processes perform operations simultaneously
- Monitor connection count

**Assertions**:
- Connections are reused from pool
- No connection leaks
- Performance is acceptable

**Priority**: MEDIUM

---

### 2. Clock Skew and Timing (5 tests)

#### Test: `test_clock_skew_between_processes`
**Purpose**: Handle clock differences between processes

**Setup**:
- 2 processes with simulated clock skew (±2 seconds)
- Redis backend

**Actions**:
- Process 1: Set rate limit with timestamp T1
- Process 2: Check rate limit with timestamp T2 (T2 = T1 + skew)

**Assertions**:
- Rate limits still enforced correctly
- Skew doesn't cause false positives/negatives
- TTL handling is robust

**Priority**: HIGH

---

#### Test: `test_time_window_boundary_conditions`
**Purpose**: Test behavior at window boundaries

**Setup**:
- 1-minute window, 10 ops limit
- 2 processes

**Actions**:
- Process 1: 5 ops at T=0s
- Process 2: 5 ops at T=0.5s
- Process 1: 5 ops at T=59s (should succeed)
- Process 2: 5 ops at T=61s (new window, should succeed)

**Assertions**:
- Window boundaries are respected
- Operations just inside/outside window handled correctly
- No off-by-one errors

**Priority**: HIGH

---

#### Test: `test_ttl_expiration_distributed`
**Purpose**: Verify TTL expiration works across processes

**Setup**:
- 10 ops/minute with 60s TTL
- 2 processes

**Actions**:
- Process 1: 10 ops at T=0
- Wait 30s
- Process 2: Check remaining ops (should be 0)
- Wait 35s more (total 65s)
- Process 1: 10 ops (should succeed - TTL expired)

**Assertions**:
- TTL expires correctly
- Expired data is cleaned up
- New operations after expiration succeed

**Priority**: MEDIUM

---

#### Test: `test_refill_rate_across_processes`
**Purpose**: Verify token refill works distributed

**Setup**:
- Token bucket: 10 tokens, refill 1/second
- 2 processes

**Actions**:
- Process 1: Consume 10 tokens at T=0
- Wait 5 seconds
- Process 2: Consume 5 tokens (should succeed)
- Process 1: Consume 5 tokens (should fail)

**Assertions**:
- Tokens refill at correct rate
- Both processes see same refill state
- Race-free token consumption

**Priority**: MEDIUM

---

#### Test: `test_timestamp_precision_redis`
**Purpose**: Ensure timestamp precision doesn't cause issues

**Setup**:
- Redis backend
- 2 processes with microsecond-precision timestamps

**Actions**:
- Both processes perform operations with very close timestamps
- Verify ordering

**Assertions**:
- Microsecond precision maintained
- No timestamp collisions
- Ordering is deterministic

**Priority**: LOW

---

### 3. Cache Invalidation (5 tests)

#### Test: `test_manual_cache_clear_distributed`
**Purpose**: Clear rate limit cache across all processes

**Setup**:
- 3 processes, all rate limited
- Redis backend

**Actions**:
- All processes hit rate limit
- Admin triggers cache clear via Redis
- All processes retry operations

**Assertions**:
- Cache clear affects all processes
- All processes can perform operations again
- No stale cache entries

**Priority**: HIGH

---

#### Test: `test_selective_cache_invalidation`
**Purpose**: Clear specific agent or operation type

**Setup**:
- Multiple agents and operation types
- Redis backend

**Actions**:
- Clear cache for agent-1 only
- Verify agent-2 still rate limited
- Clear cache for git_commit only
- Verify deploy still rate limited

**Assertions**:
- Selective invalidation works
- Other entries unaffected

**Priority**: MEDIUM

---

#### Test: `test_cache_invalidation_during_operations`
**Purpose**: Handle cache clear while operations in progress

**Setup**:
- 2 processes actively performing operations
- Redis backend

**Actions**:
- Process 1: Ongoing operations
- Admin clears cache mid-operation
- Process 2: New operations

**Assertions**:
- No race conditions
- Cache clear is atomic
- Operations complete successfully

**Priority**: MEDIUM

---

#### Test: `test_redis_key_expiration_callback`
**Purpose**: Test Redis key expiration events

**Setup**:
- Configure Redis keyspace notifications
- Set short TTL (5 seconds)

**Actions**:
- Set rate limit keys
- Wait for TTL expiration
- Monitor expiration events

**Assertions**:
- Expiration callbacks triggered
- Keys properly cleaned up
- No memory leaks

**Priority**: LOW

---

#### Test: `test_cache_stampede_prevention`
**Purpose**: Prevent cache stampede when limits reset

**Setup**:
- 10 processes waiting for rate limit reset
- All processes retry simultaneously

**Actions**:
- All processes hit limit
- Wait for window reset
- All processes retry at same moment

**Assertions**:
- No thundering herd
- Rate limit still enforced correctly
- Redis handles load

**Priority**: MEDIUM

---

### 4. Agent ID Normalization (6 tests)

#### Test: `test_case_sensitive_agent_ids`
**Purpose**: Verify agent IDs are case-sensitive

**Setup**:
- Redis backend
- Agents: "Agent-1", "agent-1", "AGENT-1"

**Actions**:
- Each agent performs 10 operations

**Assertions**:
- Each treated as separate entity
- Each gets full 10 operations
- Total 30 operations succeed

**Priority**: HIGH

---

#### Test: `test_unicode_agent_ids`
**Purpose**: Handle Unicode in agent IDs

**Setup**:
- Redis backend
- Agents with Unicode: "agent-日本", "agent-🤖", "agent-א"

**Actions**:
- Each agent performs operations

**Assertions**:
- Unicode IDs work correctly
- No encoding errors
- Redis keys are valid

**Priority**: MEDIUM

---

#### Test: `test_special_characters_in_ids`
**Purpose**: Handle special characters safely

**Setup**:
- Agents: "agent:1", "agent/1", "agent@1", "agent#1"

**Actions**:
- All agents perform operations

**Assertions**:
- Special characters don't break Redis keys
- No injection vulnerabilities
- Keys are properly escaped

**Priority**: HIGH (Security)

---

#### Test: `test_very_long_agent_ids`
**Purpose**: Handle long agent IDs

**Setup**:
- Agent IDs up to 1000 characters

**Actions**:
- Perform operations with long IDs

**Assertions**:
- Long IDs work
- Redis key limits respected
- Performance acceptable

**Priority**: LOW

---

#### Test: `test_whitespace_in_agent_ids`
**Purpose**: Handle whitespace correctly

**Setup**:
- Agents: "agent 1", " agent-1", "agent-1 ", "agent\t1"

**Actions**:
- All agents perform operations

**Assertions**:
- Whitespace preserved or normalized consistently
- No key collisions

**Priority**: MEDIUM

---

#### Test: `test_empty_or_null_agent_ids`
**Purpose**: Handle missing agent IDs gracefully

**Setup**:
- Operations with empty string, None, missing agent_id

**Actions**:
- Attempt operations

**Assertions**:
- Falls back to global tracking
- No exceptions
- Consistent behavior

**Priority**: MEDIUM

---

### 5. Multi-Process Coordination (8 tests)

#### Test: `test_distributed_lock_acquisition`
**Purpose**: Verify Redis locks prevent race conditions

**Setup**:
- 5 processes competing for same operation
- Redis lock with 1-second timeout

**Actions**:
- All processes try to increment counter simultaneously
- Use Redis SETNX for locking

**Assertions**:
- Only one process acquires lock at a time
- Counter increments correctly (no lost updates)
- Lock timeout works

**Priority**: CRITICAL

---

#### Test: `test_atomic_increment_operations`
**Purpose**: Test Redis INCR atomicity

**Setup**:
- 10 processes
- Shared counter in Redis

**Actions**:
- All processes INCR counter 10 times

**Assertions**:
- Final count = 100 (no lost increments)
- All increments atomic
- No race conditions

**Priority**: CRITICAL

---

#### Test: `test_lua_script_atomicity`
**Purpose**: Test complex atomic operations via Lua

**Setup**:
- Redis Lua script for "check-and-decrement"
- 5 processes, 10 tokens total

**Actions**:
- All processes try to consume tokens using Lua script

**Assertions**:
- Exactly 10 operations succeed
- Script execution is atomic
- No race conditions

**Priority**: HIGH

---

#### Test: `test_process_crash_during_operation`
**Purpose**: Handle process crash gracefully

**Setup**:
- 3 processes
- Process 2 will crash mid-operation

**Actions**:
- Process 1: Normal operations
- Process 2: Start operation, then crash (os._exit(1))
- Process 3: Normal operations

**Assertions**:
- Process 2 crash doesn't corrupt Redis state
- Other processes continue normally
- No deadlocks

**Priority**: HIGH

---

#### Test: `test_redis_connection_failure_handling`
**Purpose**: Handle Redis unavailability

**Setup**:
- 2 processes
- Simulate Redis disconnect

**Actions**:
- Process 1: Normal operation
- Disconnect Redis
- Process 2: Attempt operation (should fail gracefully)
- Reconnect Redis
- Process 2: Retry (should succeed)

**Assertions**:
- Connection failures handled gracefully
- Automatic retry logic
- No data loss

**Priority**: HIGH

---

#### Test: `test_redis_timeout_handling`
**Purpose**: Handle slow Redis responses

**Setup**:
- Configure Redis with 100ms timeout
- Simulate slow Redis (network delay)

**Actions**:
- Attempt operations with slow Redis

**Assertions**:
- Timeout exceptions caught
- Fallback behavior (allow or deny)
- No indefinite hangs

**Priority**: MEDIUM

---

#### Test: `test_stale_lock_cleanup`
**Purpose**: Clean up locks from crashed processes

**Setup**:
- Process 1 acquires lock then crashes
- Lock TTL = 5 seconds

**Actions**:
- Process 2 waits for lock
- After TTL expires, Process 2 acquires lock

**Assertions**:
- Stale locks auto-expire
- No permanent deadlocks
- TTL enforced correctly

**Priority**: HIGH

---

#### Test: `test_concurrent_limit_configuration_changes`
**Purpose**: Handle limit changes while processes running

**Setup**:
- 3 processes with limit: 10 ops/minute
- Admin changes limit to 20 ops/minute

**Actions**:
- Processes continue operations
- New limit takes effect

**Assertions**:
- Config change propagates to all processes
- No race conditions
- Existing operations honored

**Priority**: MEDIUM

---

### 6. Race Conditions and Edge Cases (8 tests)

#### Test: `test_simultaneous_first_operation`
**Purpose**: Handle multiple processes' first operation

**Setup**:
- 3 processes
- All start at exactly same time

**Actions**:
- All processes perform first operation simultaneously

**Assertions**:
- All operations succeed (no false rate limits)
- Redis keys initialized correctly
- No lost operations

**Priority**: HIGH

---

#### Test: `test_race_on_window_reset`
**Purpose**: Handle race at window boundary

**Setup**:
- 2 processes
- Both at limit, window about to reset

**Actions**:
- Both processes check limit at T=59.999s
- Window resets at T=60s
- Both retry

**Assertions**:
- Window reset is atomic
- No double-counting
- Both processes see consistent state

**Priority**: HIGH

---

#### Test: `test_check_then_act_race`
**Purpose**: Prevent race in check-then-increment pattern

**Setup**:
- 2 processes
- Limit: 10 operations

**Actions**:
- Process 1: Check (9 ops so far)
- Process 2: Check (9 ops so far)
- Process 1: Increment (10 ops)
- Process 2: Increment (11 ops - should fail)

**Assertions**:
- Race prevented via atomic operations
- Only 10 operations succeed

**Priority**: CRITICAL

---

#### Test: `test_negative_token_count`
**Purpose**: Prevent negative token buckets

**Setup**:
- 2 processes racing to consume last token

**Actions**:
- Both processes try to consume last token simultaneously

**Assertions**:
- Only one succeeds
- Token count never goes negative
- Atomic decrement used

**Priority**: CRITICAL

---

#### Test: `test_ttl_race_on_expiration`
**Purpose**: Handle TTL expiring during operation

**Setup**:
- 1 process checking limit just as TTL expires

**Actions**:
- Check limit at T=59.99s (before expiration)
- TTL expires at T=60s
- Complete operation at T=60.01s

**Assertions**:
- Consistent handling
- No partial state
- Either fully expired or not

**Priority**: MEDIUM

---

#### Test: `test_burst_concurrency_token_bucket`
**Purpose**: Handle burst traffic with token bucket

**Setup**:
- Token bucket: 100 tokens, 10/second refill
- 10 processes

**Actions**:
- All 10 processes try to consume 20 tokens simultaneously

**Assertions**:
- Exactly 100 tokens consumed total
- Burst handled correctly
- No over-consumption

**Priority**: HIGH

---

#### Test: `test_limit_overflow_protection`
**Purpose**: Prevent integer overflow in counters

**Setup**:
- Very large operation counts
- Long-running processes

**Actions**:
- Simulate millions of operations
- Check counter doesn't overflow

**Assertions**:
- Counters use appropriate data types
- No overflow
- Performance acceptable

**Priority**: LOW

---

#### Test: `test_redis_key_collision`
**Purpose**: Prevent key collisions

**Setup**:
- Similar agent IDs and operation types

**Actions**:
- Create operations that might collide:
  - "agent-1" + "commit" vs "agent" + "1-commit"

**Assertions**:
- Keys use proper delimiters
- No collisions
- Deterministic key generation

**Priority**: HIGH (Security)

---

### 7. Failure and Recovery (6 tests)

#### Test: `test_redis_server_restart`
**Purpose**: Handle Redis restart

**Setup**:
- Processes actively rate limiting
- Redis with persistence disabled

**Actions**:
- Stop Redis
- Restart Redis
- Processes retry operations

**Assertions**:
- Processes reconnect automatically
- Rate limits reset (expected with no persistence)
- No crashes

**Priority**: HIGH

---

#### Test: `test_network_partition`
**Purpose**: Handle network split

**Setup**:
- 2 processes
- Simulate network partition (Redis unreachable)

**Actions**:
- Partition network
- Processes attempt operations
- Restore network

**Assertions**:
- Graceful degradation (allow or deny)
- Recovery after partition heals
- No permanent errors

**Priority**: MEDIUM

---

#### Test: `test_redis_out_of_memory`
**Purpose**: Handle Redis OOM

**Setup**:
- Configure Redis with maxmemory
- Fill Redis to capacity

**Actions**:
- Attempt to set new rate limit keys

**Assertions**:
- OOM errors caught
- Eviction policies work
- No service crash

**Priority**: MEDIUM

---

#### Test: `test_corrupted_redis_data`
**Purpose**: Handle corrupt data gracefully

**Setup**:
- Manually corrupt Redis keys (invalid format)

**Actions**:
- Processes attempt to read corrupted data

**Assertions**:
- Errors caught and logged
- Fallback to safe defaults
- Auto-repair or reset

**Priority**: MEDIUM

---

#### Test: `test_partial_redis_failure`
**Purpose**: Handle intermittent Redis failures

**Setup**:
- Redis fails 50% of requests (flaky network)

**Actions**:
- Processes perform operations
- Some succeed, some fail

**Assertions**:
- Retry logic works
- Eventually consistent
- No infinite loops

**Priority**: MEDIUM

---

#### Test: `test_backup_failover`
**Purpose**: Test Redis sentinel/cluster failover

**Setup**:
- Redis cluster with replicas
- Trigger master failover

**Actions**:
- Perform operations during failover

**Assertions**:
- Failover is transparent
- Brief interruption only
- Data consistency maintained

**Priority**: LOW (Infrastructure-dependent)

---

### 8. Performance and Scalability (4 tests)

#### Test: `test_throughput_with_10_processes`
**Purpose**: Measure throughput with moderate concurrency

**Setup**:
- 10 processes
- Each performs 100 operations

**Actions**:
- All processes run simultaneously
- Measure total time and ops/sec

**Assertions**:
- Throughput >= 500 ops/sec
- Redis is not bottleneck
- Latency p99 < 50ms

**Priority**: MEDIUM

---

#### Test: `test_scalability_to_100_processes`
**Purpose**: Test scalability limits

**Setup**:
- 100 processes
- Each performs 10 operations

**Actions**:
- All processes run simultaneously
- Monitor Redis load

**Assertions**:
- System remains stable
- No connection exhaustion
- Linear or sublinear scaling

**Priority**: LOW

---

#### Test: `test_memory_usage_stability`
**Purpose**: Ensure no memory leaks

**Setup**:
- 5 processes running for 5 minutes
- Monitor Redis memory

**Actions**:
- Continuous operations
- Periodic memory snapshots

**Assertions**:
- Memory usage stable
- No unbounded growth
- TTL cleanup working

**Priority**: MEDIUM

---

#### Test: `test_redis_key_count_growth`
**Purpose**: Monitor key count growth

**Setup**:
- 1000 agents, 10 operation types

**Actions**:
- Simulate realistic workload
- Monitor Redis key count

**Assertions**:
- Key count bounded
- Expired keys cleaned up
- No key explosion

**Priority**: LOW

---

## Test Helpers and Fixtures

### Redis Fixtures

```python
@pytest.fixture
def redis_client():
    """Provide Redis client for tests."""
    import redis
    client = redis.Redis(host='localhost', port=6379, db=15, decode_responses=True)

    # Clear test database
    client.flushdb()

    yield client

    # Cleanup
    client.flushdb()
    client.close()


@pytest.fixture
def redis_backend(redis_client):
    """Provide Redis-backed rate limiter."""
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    backend = RedisRateLimiterBackend(redis_client)
    yield backend

    # Cleanup handled by redis_client fixture
```

### Multi-Process Helpers

```python
def worker_process(redis_url: str, agent_id: str, operation: str,
                   count: int, result_queue: Queue, delay_ms: int = 0):
    """Worker process for multi-process tests."""
    import redis
    from src.safety.distributed_rate_limiter import DistributedRateLimiter

    # Delay for staggered start
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

    # Connect to Redis
    client = redis.Redis.from_url(redis_url)
    limiter = DistributedRateLimiter(client)

    results = {'allowed': 0, 'denied': 0}

    for i in range(count):
        allowed = limiter.check_and_increment(agent_id, operation)
        if allowed:
            results['allowed'] += 1
        else:
            results['denied'] += 1

    result_queue.put(results)


def run_multiprocess_test(num_processes: int, ops_per_process: int,
                          expected_total_allowed: int, redis_url: str) -> Dict:
    """
    Run multi-process test and verify results.

    Returns:
        Dictionary with test results and assertions
    """
    from multiprocessing import Process, Queue

    result_queue = Queue()
    processes = []

    # Spawn processes
    for i in range(num_processes):
        p = Process(
            target=worker_process,
            args=(redis_url, f"agent-{i}", "test_op", ops_per_process, result_queue)
        )
        processes.append(p)
        p.start()

    # Wait for completion
    for p in processes:
        p.join()

    # Collect results
    total_allowed = 0
    total_denied = 0

    while not result_queue.empty():
        result = result_queue.get()
        total_allowed += result['allowed']
        total_denied += result['denied']

    # Verify
    assert total_allowed == expected_total_allowed, \
        f"Expected {expected_total_allowed} allowed, got {total_allowed}"

    assert total_allowed + total_denied == num_processes * ops_per_process, \
        f"Lost operations: {num_processes * ops_per_process - (total_allowed + total_denied)}"

    return {'allowed': total_allowed, 'denied': total_denied}
```

### Clock Skew Simulation

```python
class MockTimeProvider:
    """Simulate clock skew for testing."""

    def __init__(self, skew_seconds: float = 0):
        self.skew = skew_seconds

    def time(self) -> float:
        """Return skewed time."""
        return time.time() + self.skew

    def sleep(self, seconds: float):
        """Sleep with skew adjustment."""
        time.sleep(seconds)
```

### Redis Fault Injection

```python
class FlakyRedis:
    """Redis client that randomly fails requests."""

    def __init__(self, real_client, failure_rate: float = 0.5):
        self.client = real_client
        self.failure_rate = failure_rate

    def __getattr__(self, name):
        """Proxy all calls to real client with random failures."""
        def wrapper(*args, **kwargs):
            if random.random() < self.failure_rate:
                raise redis.ConnectionError("Simulated failure")
            return getattr(self.client, name)(*args, **kwargs)
        return wrapper
```

---

## Implementation Requirements

### Distributed Rate Limiter Backend

**File**: `src/safety/distributed_rate_limiter.py`

```python
class RedisRateLimiterBackend:
    """
    Redis-backed distributed rate limiter.

    Features:
    - Atomic operations via Lua scripts
    - TTL-based window management
    - Connection pooling
    - Fault tolerance
    """

    def __init__(self, redis_client):
        self.redis = redis_client
        self._init_lua_scripts()

    def _init_lua_scripts(self):
        """Pre-load Lua scripts for atomic operations."""
        # Script for check-and-increment
        self.check_and_incr_script = self.redis.register_script("""
            local key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local ttl = tonumber(ARGV[2])

            local current = redis.call('GET', key)
            if current == false then
                current = 0
            else
                current = tonumber(current)
            end

            if current >= limit then
                return {0, current}  -- Denied
            end

            local new_val = redis.call('INCR', key)
            if new_val == 1 then
                redis.call('EXPIRE', key, ttl)
            end

            return {1, new_val}  -- Allowed
        """)

    def check_and_increment(self, agent_id: str, operation: str,
                           limit: int, window_seconds: int) -> Tuple[bool, int]:
        """
        Atomically check limit and increment counter.

        Returns:
            (allowed, current_count)
        """
        key = self._make_key(agent_id, operation, window_seconds)

        try:
            result = self.check_and_incr_script(
                keys=[key],
                args=[limit, window_seconds]
            )
            allowed, count = result
            return bool(allowed), int(count)

        except redis.ConnectionError as e:
            logger.error(f"Redis connection error: {e}")
            # Fail open or closed based on config
            return True, 0  # Fail open (allow operation)

    def _make_key(self, agent_id: str, operation: str, window: int) -> str:
        """
        Generate Redis key for rate limit.

        Format: ratelimit:{agent_id}:{operation}:{window_start}
        """
        # Normalize agent_id (handle special chars)
        safe_agent = agent_id.replace(':', '_').replace('/', '_')

        # Calculate window start time
        now = int(time.time())
        window_start = (now // window) * window

        return f"ratelimit:{safe_agent}:{operation}:{window_start}"

    def reset(self, agent_id: Optional[str] = None,
              operation: Optional[str] = None):
        """Reset rate limits (for testing)."""
        if agent_id is None and operation is None:
            # Delete all rate limit keys
            pattern = "ratelimit:*"
        elif agent_id and operation:
            pattern = f"ratelimit:{agent_id}:{operation}:*"
        elif agent_id:
            pattern = f"ratelimit:{agent_id}:*"
        else:
            pattern = f"ratelimit:*:{operation}:*"

        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
```

### Integration with Existing RateLimiterPolicy

Extend `src/safety/rate_limiter.py`:

```python
class RateLimiterPolicy(BaseSafetyPolicy):
    """Rate limiter with optional Redis backend."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config or {})

        # ... existing initialization ...

        # Optional Redis backend
        self.use_distributed = self.config.get("distributed", False)
        if self.use_distributed:
            redis_config = self.config.get("redis", {})
            self._init_redis_backend(redis_config)

    def _init_redis_backend(self, redis_config):
        """Initialize Redis backend for distributed rate limiting."""
        import redis
        from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

        client = redis.Redis(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6379),
            db=redis_config.get("db", 0),
            password=redis_config.get("password"),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2
        )

        self.redis_backend = RedisRateLimiterBackend(client)
```

---

## Test Execution Strategy

### Test Phases

1. **Phase 1: Local Unit Tests** (30 minutes)
   - Basic Redis operations
   - Single-process with Redis
   - Agent ID normalization

2. **Phase 2: Multi-Process Tests** (1 hour)
   - 2-3-5 process coordination
   - Race conditions
   - Clock skew

3. **Phase 3: Failure Tests** (45 minutes)
   - Redis failures
   - Network partitions
   - Process crashes

4. **Phase 4: Performance Tests** (30 minutes)
   - Throughput benchmarks
   - Scalability limits

### CI/CD Integration

```yaml
# .github/workflows/distributed-rate-limiting-tests.yml
name: Distributed Rate Limiting Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install redis

      - name: Run distributed rate limiting tests
        run: |
          pytest tests/test_safety/test_distributed_rate_limiting.py -v --tb=short
        env:
          REDIS_URL: redis://localhost:6379/15
```

---

## Acceptance Criteria

### Must Have (Critical)

- [ ] All 52+ tests pass consistently
- [ ] No race conditions detected
- [ ] Global rate limits enforced across 2+ processes
- [ ] Redis atomicity verified (Lua scripts)
- [ ] Process crash handling works
- [ ] Agent ID normalization prevents collisions
- [ ] Performance: >= 500 ops/sec with 10 processes

### Should Have (High Priority)

- [ ] Clock skew handling (±5 seconds)
- [ ] Cache invalidation works
- [ ] TTL cleanup verified
- [ ] Connection pool works correctly
- [ ] Graceful degradation on Redis failure

### Nice to Have (Medium Priority)

- [ ] Performance test: 100+ processes
- [ ] Redis cluster/sentinel support
- [ ] Metrics and observability
- [ ] Auto-recovery from network partitions

---

## Risks and Mitigations

### Risk 1: Test Flakiness
**Mitigation**:
- Use deterministic timing (avoid sleep)
- Retry failed tests (pytest-rerunfailures)
- Increase timeouts in CI

### Risk 2: Redis Dependency
**Mitigation**:
- Use fakeredis for unit tests
- Docker Redis in CI
- Graceful fallback if Redis unavailable

### Risk 3: Performance Bottleneck
**Mitigation**:
- Connection pooling
- Pipeline Redis commands
- Lua scripts for atomicity

### Risk 4: Data Consistency
**Mitigation**:
- Atomic operations (Lua scripts)
- Proper TTL handling
- Validation tests for all edge cases

---

## Success Metrics

1. **Test Coverage**: 100% of distributed scenarios covered
2. **Test Reliability**: <1% flaky test rate
3. **Performance**: Latency p99 < 50ms, throughput >= 500 ops/sec
4. **Failure Handling**: Graceful degradation in all failure modes
5. **Documentation**: Complete test descriptions and examples

---

## Next Steps

1. **Implement Redis Backend** (2-3 hours)
   - Create `src/safety/distributed_rate_limiter.py`
   - Lua scripts for atomic operations
   - Connection pool configuration

2. **Write Test Fixtures** (1 hour)
   - Redis fixtures
   - Multi-process helpers
   - Fault injection utilities

3. **Implement Tests Phase 1** (3-4 hours)
   - Basic distributed rate limiting (10 tests)
   - Clock skew (5 tests)

4. **Implement Tests Phase 2** (3-4 hours)
   - Multi-process coordination (8 tests)
   - Race conditions (8 tests)

5. **Implement Tests Phase 3** (2-3 hours)
   - Agent ID normalization (6 tests)
   - Cache invalidation (5 tests)

6. **Implement Tests Phase 4** (2 hours)
   - Failure and recovery (6 tests)
   - Performance (4 tests)

7. **CI/CD Integration** (1 hour)
   - GitHub Actions workflow
   - Redis service configuration

8. **Documentation** (1 hour)
   - Update TESTING.md
   - Add usage examples
   - Performance tuning guide

**Total Estimated Time: 15-20 hours**

---

## Conclusion

This comprehensive test design provides a robust validation strategy for distributed rate limiting across multiple processes using Redis. The 52+ test scenarios cover all critical aspects:

- ✅ Basic distributed functionality
- ✅ Clock skew and timing edge cases
- ✅ Cache invalidation and TTL
- ✅ Agent ID normalization and security
- ✅ Multi-process coordination
- ✅ Race conditions and atomicity
- ✅ Failure and recovery
- ✅ Performance and scalability

The implementation will ensure the Meta Autonomous Framework can reliably enforce rate limits across distributed deployments, preventing resource exhaustion and ensuring system stability.
