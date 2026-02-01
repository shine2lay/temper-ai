# Distributed Rate Limiting - Quick Reference

## Test Examples with Complete Code

This guide provides copy-paste ready test implementations for distributed rate limiting.

---

## 1. Basic Multi-Process Test Template

```python
"""Test: Rate limits enforced across 2 processes"""
import pytest
import redis
import time
from multiprocessing import Process, Queue
from typing import Dict


def worker_consume_tokens(redis_url: str, agent_id: str, operation: str,
                          count: int, result_queue: Queue):
    """Worker process that attempts to consume tokens."""
    client = redis.Redis.from_url(redis_url, decode_responses=True)

    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend
    backend = RedisRateLimiterBackend(client)

    results = {'allowed': 0, 'denied': 0, 'errors': []}

    for i in range(count):
        try:
            allowed, current = backend.check_and_increment(
                agent_id=agent_id,
                operation=operation,
                limit=10,
                window_seconds=60
            )

            if allowed:
                results['allowed'] += 1
            else:
                results['denied'] += 1

        except Exception as e:
            results['errors'].append(str(e))

    result_queue.put(results)
    client.close()


def test_two_processes_shared_rate_limit(redis_client):
    """
    CRITICAL: Verify rate limit is enforced globally across 2 processes.

    Setup:
        - Redis backend with shared limit: 10 ops/minute
        - Spawn 2 processes

    Expected:
        - Total operations allowed = 10 (across both processes)
        - Process coordination via Redis
        - No race conditions
    """
    redis_url = "redis://localhost:6379/15"

    # Clear Redis
    redis_client.flushdb()

    result_queue = Queue()

    # Process 1: Try to consume 6 tokens
    p1 = Process(target=worker_consume_tokens,
                 args=(redis_url, "agent-global", "test_op", 6, result_queue))

    # Process 2: Try to consume 6 tokens (4 should succeed, 2 should fail)
    p2 = Process(target=worker_consume_tokens,
                 args=(redis_url, "agent-global", "test_op", 6, result_queue))

    # Start processes
    p1.start()
    p2.start()

    # Wait for completion
    p1.join(timeout=10)
    p2.join(timeout=10)

    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    total_allowed = sum(r['allowed'] for r in results)
    total_denied = sum(r['denied'] for r in results)

    # Assertions
    assert total_allowed == 10, f"Expected exactly 10 allowed, got {total_allowed}"
    assert total_denied == 2, f"Expected 2 denied, got {total_denied}"
    assert total_allowed + total_denied == 12, "Lost operations detected"

    # Verify no errors
    for result in results:
        assert len(result['errors']) == 0, f"Errors occurred: {result['errors']}"
```

---

## 2. Clock Skew Test

```python
"""Test: Handle clock skew between processes"""
import pytest
import time
from unittest.mock import patch


def worker_with_clock_skew(redis_url: str, agent_id: str, skew_seconds: float,
                           result_queue: Queue):
    """Worker with simulated clock skew."""
    import redis
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    backend = RedisRateLimiterBackend(client)

    # Mock time to simulate clock skew
    original_time = time.time

    def skewed_time():
        return original_time() + skew_seconds

    results = {'allowed': 0, 'denied': 0}

    with patch('time.time', skewed_time):
        for i in range(5):
            allowed, _ = backend.check_and_increment(
                agent_id=agent_id,
                operation="test_op",
                limit=10,
                window_seconds=60
            )

            if allowed:
                results['allowed'] += 1
            else:
                results['denied'] += 1

    result_queue.put(results)
    client.close()


def test_clock_skew_between_processes(redis_client):
    """
    HIGH: Handle clock differences between processes (±2 seconds).

    Setup:
        - Process 1: Normal clock
        - Process 2: Clock +2 seconds ahead
        - Process 3: Clock -2 seconds behind
        - Shared limit: 10 ops/minute

    Expected:
        - Rate limits still enforced correctly
        - Skew doesn't cause false positives/negatives
        - Window boundaries handled robustly
    """
    redis_url = "redis://localhost:6379/15"
    redis_client.flushdb()

    result_queue = Queue()

    # Process 1: Normal time
    p1 = Process(target=worker_with_clock_skew,
                 args=(redis_url, "agent-1", 0.0, result_queue))

    # Process 2: +2 seconds ahead
    p2 = Process(target=worker_with_clock_skew,
                 args=(redis_url, "agent-1", 2.0, result_queue))

    # Process 3: -2 seconds behind
    p3 = Process(target=worker_with_clock_skew,
                 args=(redis_url, "agent-1", -2.0, result_queue))

    for p in [p1, p2, p3]:
        p.start()

    for p in [p1, p2, p3]:
        p.join(timeout=10)

    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    total_allowed = sum(r['allowed'] for r in results)
    total_denied = sum(r['denied'] for r in results)

    # Despite clock skew, rate limit should still be enforced
    # May not be exactly 10 due to time window differences, but should be close
    assert 8 <= total_allowed <= 12, \
        f"Clock skew caused excessive variation: {total_allowed} allowed"

    assert total_allowed + total_denied == 15, "Lost operations"
```

---

## 3. Race Condition Test (Atomic Operations)

```python
"""Test: Prevent race in check-then-increment pattern"""
import pytest
import redis
import time
from multiprocessing import Process, Queue, Barrier


def worker_race_test(redis_url: str, agent_id: str, barrier: Barrier,
                     result_queue: Queue):
    """
    Worker that synchronizes with barrier to create race condition.

    This tests the CRITICAL atomic check-and-increment operation.
    """
    import redis
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    backend = RedisRateLimiterBackend(client)

    results = {'allowed': 0, 'denied': 0, 'timestamps': []}

    # Use 9 tokens, leaving 1 remaining
    for i in range(9):
        backend.check_and_increment(agent_id, "test_op", limit=10, window_seconds=60)

    # Wait for all processes to reach this point
    barrier.wait()

    # All processes simultaneously try to consume the last token
    # Only ONE should succeed due to atomic Lua script
    start = time.time()
    allowed, count = backend.check_and_increment(
        agent_id, "test_op", limit=10, window_seconds=60
    )
    elapsed = time.time() - start

    results['allowed'] = 1 if allowed else 0
    results['denied'] = 0 if allowed else 1
    results['timestamps'].append(elapsed)
    results['final_count'] = count

    result_queue.put(results)
    client.close()


def test_check_then_act_race(redis_client):
    """
    CRITICAL: Prevent race in check-then-increment pattern.

    Setup:
        - 2 processes
        - Limit: 10 operations
        - Both processes consume 9 tokens
        - Both simultaneously try to consume 10th token

    Expected:
        - Only ONE process succeeds (atomic operation)
        - Other process is denied
        - Total operations = 10 (no over-consumption)
    """
    redis_url = "redis://localhost:6379/15"
    redis_client.flushdb()

    from multiprocessing import Manager
    manager = Manager()
    barrier = manager.Barrier(2)  # Synchronize 2 processes
    result_queue = manager.Queue()

    # Spawn 2 processes
    processes = []
    for i in range(2):
        p = Process(
            target=worker_race_test,
            args=(redis_url, "agent-race", barrier, result_queue)
        )
        processes.append(p)
        p.start()

    # Wait for completion
    for p in processes:
        p.join(timeout=10)

    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    total_allowed = sum(r['allowed'] for r in results)
    total_denied = sum(r['denied'] for r in results)

    # CRITICAL: Only one process should have succeeded
    assert total_allowed == 1, \
        f"Race condition! {total_allowed} processes got last token (should be 1)"

    assert total_denied == 1, \
        f"Expected 1 denied, got {total_denied}"

    # Verify final count is exactly 10 (no over-consumption)
    final_counts = [r['final_count'] for r in results]
    assert max(final_counts) == 10, \
        f"Over-consumption detected: max count = {max(final_counts)}"
```

---

## 4. Agent ID Normalization Test

```python
"""Test: Special characters in agent IDs"""
import pytest
import redis


def test_special_characters_in_agent_ids(redis_client):
    """
    HIGH (Security): Handle special characters safely.

    Setup:
        - Agent IDs with special chars: ":", "/", "@", "#", etc.

    Expected:
        - Special characters don't break Redis keys
        - No injection vulnerabilities
        - Keys are properly escaped
    """
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    backend = RedisRateLimiterBackend(redis_client)

    # Test various special characters
    test_agents = [
        "agent:1",       # Colon (Redis key separator)
        "agent/1",       # Slash
        "agent@1",       # At sign
        "agent#1",       # Hash
        "agent[1]",      # Brackets
        "agent{1}",      # Braces
        "agent*1",       # Wildcard
        "agent?1",       # Question mark
        "agent\t1",      # Tab
        "agent\n1",      # Newline (dangerous!)
    ]

    results = {}

    for agent_id in test_agents:
        # Each agent should be able to perform 10 operations
        allowed_count = 0

        for i in range(12):
            allowed, count = backend.check_and_increment(
                agent_id=agent_id,
                operation="test_op",
                limit=10,
                window_seconds=60
            )

            if allowed:
                allowed_count += 1

        results[agent_id] = allowed_count

    # Verify each agent independently got 10 operations
    for agent_id, count in results.items():
        assert count == 10, \
            f"Agent '{agent_id}' got {count} ops (expected 10). " \
            f"Possible key collision or injection!"

    # Verify Redis keys are properly namespaced
    all_keys = redis_client.keys("ratelimit:*")
    assert len(all_keys) >= len(test_agents), \
        f"Expected at least {len(test_agents)} keys, found {len(all_keys)}"

    # Verify no malicious key injection
    dangerous_keys = redis_client.keys("*\n*") + redis_client.keys("*;*")
    assert len(dangerous_keys) == 0, \
        f"Key injection detected! Dangerous keys: {dangerous_keys}"
```

---

## 5. Process Crash Handling Test

```python
"""Test: Process crash during operation"""
import pytest
import os
import signal
import time
from multiprocessing import Process, Queue


def worker_that_crashes(redis_url: str, agent_id: str, result_queue: Queue,
                        crash_after: int = 5):
    """Worker that crashes mid-operation."""
    import redis
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    backend = RedisRateLimiterBackend(client)

    for i in range(crash_after):
        backend.check_and_increment(agent_id, "test_op", limit=10, window_seconds=60)

    # Simulate crash (no cleanup!)
    os._exit(1)


def worker_normal(redis_url: str, agent_id: str, result_queue: Queue):
    """Normal worker."""
    import redis
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    backend = RedisRateLimiterBackend(client)

    results = {'allowed': 0, 'denied': 0}

    for i in range(10):
        allowed, _ = backend.check_and_increment(
            agent_id, "test_op", limit=10, window_seconds=60
        )

        if allowed:
            results['allowed'] += 1
        else:
            results['denied'] += 1

        time.sleep(0.01)  # Small delay

    result_queue.put(results)
    client.close()


def test_process_crash_during_operation(redis_client):
    """
    HIGH: Handle process crash gracefully.

    Setup:
        - 3 processes
        - Process 2 crashes after 5 operations
        - Processes 1 and 3 continue normally

    Expected:
        - Crashed process doesn't corrupt Redis state
        - Other processes continue normally
        - No deadlocks or orphaned locks
    """
    redis_url = "redis://localhost:6379/15"
    redis_client.flushdb()

    from multiprocessing import Manager
    manager = Manager()
    result_queue = manager.Queue()

    # Process 1: Normal
    p1 = Process(target=worker_normal,
                 args=(redis_url, "agent-crash-test", result_queue))

    # Process 2: Will crash after 5 operations
    p2 = Process(target=worker_that_crashes,
                 args=(redis_url, "agent-crash-test", result_queue, 5))

    # Process 3: Normal (starts after crash)
    p3 = Process(target=worker_normal,
                 args=(redis_url, "agent-crash-test", result_queue))

    # Start processes
    p1.start()
    p2.start()

    # Wait for crash
    p2.join(timeout=5)

    # Verify process 2 crashed
    assert p2.exitcode == 1, "Process 2 should have crashed"

    # Start process 3 after crash
    time.sleep(0.1)
    p3.start()

    # Wait for normal processes
    p1.join(timeout=10)
    p3.join(timeout=10)

    # Collect results (process 2 won't return results)
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    total_allowed = sum(r['allowed'] for r in results)
    total_denied = sum(r['denied'] for r in results)

    # Process 2 consumed 5 tokens before crash
    # Process 1 and 3 together should get remaining 5
    # Total attempts = 20 (10 from p1, 10 from p3)
    # Total allowed = 5 (remaining after p2's 5)
    # Total denied = 15

    assert total_allowed <= 5, \
        f"Expected <= 5 allowed after crash, got {total_allowed}"

    assert total_denied >= 10, \
        f"Expected >= 10 denied, got {total_denied}"

    # Verify Redis state is consistent
    final_count_key = redis_client.keys("ratelimit:*crash-test*")
    assert len(final_count_key) > 0, "Redis keys missing after crash"
```

---

## 6. Redis Connection Failure Test

```python
"""Test: Redis connection failure handling"""
import pytest
import redis
from unittest.mock import patch, MagicMock


def test_redis_connection_failure_handling(redis_client):
    """
    HIGH: Handle Redis unavailability gracefully.

    Setup:
        - Normal operation
        - Simulate Redis disconnect
        - Verify graceful failure

    Expected:
        - Connection failures caught
        - Fallback behavior (fail-open or fail-closed)
        - No crashes
    """
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    backend = RedisRateLimiterBackend(redis_client)

    # Normal operation
    allowed, count = backend.check_and_increment(
        "agent-1", "test_op", limit=10, window_seconds=60
    )
    assert allowed is True, "First operation should succeed"

    # Simulate Redis connection failure
    def raise_connection_error(*args, **kwargs):
        raise redis.ConnectionError("Connection refused")

    with patch.object(redis_client, 'evalsha', side_effect=raise_connection_error):
        # Attempt operation during failure
        allowed, count = backend.check_and_increment(
            "agent-1", "test_op", limit=10, window_seconds=60
        )

        # Should fail gracefully (fail-open by default)
        assert allowed is True, "Should fail-open when Redis unavailable"
        assert count == 0, "Count should be 0 on failure"

    # After recovery, should work again
    allowed, count = backend.check_and_increment(
        "agent-1", "test_op", limit=10, window_seconds=60
    )
    assert allowed is True, "Should work after recovery"
```

---

## 7. Performance Benchmark Test

```python
"""Test: Throughput with 10 processes"""
import pytest
import time
import statistics
from multiprocessing import Process, Queue


def worker_benchmark(redis_url: str, process_id: int, ops_count: int,
                     result_queue: Queue):
    """Worker that measures performance."""
    import redis
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    client = redis.Redis.from_url(redis_url, decode_responses=True)
    backend = RedisRateLimiterBackend(client)

    latencies = []
    allowed = 0
    denied = 0

    start_time = time.time()

    for i in range(ops_count):
        op_start = time.time()

        is_allowed, _ = backend.check_and_increment(
            agent_id=f"agent-{process_id}",
            operation="benchmark",
            limit=1000000,  # Very high limit (no rate limiting)
            window_seconds=60
        )

        op_end = time.time()
        latencies.append((op_end - op_start) * 1000)  # Convert to ms

        if is_allowed:
            allowed += 1
        else:
            denied += 1

    end_time = time.time()
    elapsed = end_time - start_time

    results = {
        'process_id': process_id,
        'ops_count': ops_count,
        'allowed': allowed,
        'denied': denied,
        'elapsed_seconds': elapsed,
        'ops_per_second': ops_count / elapsed if elapsed > 0 else 0,
        'latency_p50': statistics.median(latencies),
        'latency_p95': statistics.quantiles(latencies, n=20)[18],  # 95th percentile
        'latency_p99': statistics.quantiles(latencies, n=100)[98],  # 99th percentile
        'latency_max': max(latencies)
    }

    result_queue.put(results)
    client.close()


def test_throughput_with_10_processes(redis_client):
    """
    MEDIUM: Measure throughput with moderate concurrency.

    Setup:
        - 10 processes
        - Each performs 100 operations

    Expected:
        - Throughput >= 500 ops/sec
        - Latency p99 < 50ms
        - No errors
    """
    redis_url = "redis://localhost:6379/15"
    redis_client.flushdb()

    from multiprocessing import Manager
    manager = Manager()
    result_queue = manager.Queue()

    num_processes = 10
    ops_per_process = 100

    processes = []

    overall_start = time.time()

    # Spawn processes
    for i in range(num_processes):
        p = Process(
            target=worker_benchmark,
            args=(redis_url, i, ops_per_process, result_queue)
        )
        processes.append(p)
        p.start()

    # Wait for all processes
    for p in processes:
        p.join(timeout=30)

    overall_end = time.time()
    overall_elapsed = overall_end - overall_start

    # Collect results
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())

    # Calculate aggregate metrics
    total_ops = sum(r['ops_count'] for r in results)
    total_allowed = sum(r['allowed'] for r in results)
    overall_throughput = total_ops / overall_elapsed

    all_p99_latencies = [r['latency_p99'] for r in results]
    worst_p99 = max(all_p99_latencies)

    # Print results
    print(f"\n{'='*60}")
    print(f"Performance Benchmark Results")
    print(f"{'='*60}")
    print(f"Processes:           {num_processes}")
    print(f"Operations/process:  {ops_per_process}")
    print(f"Total operations:    {total_ops}")
    print(f"Total time:          {overall_elapsed:.2f}s")
    print(f"Overall throughput:  {overall_throughput:.1f} ops/sec")
    print(f"Worst p99 latency:   {worst_p99:.2f}ms")
    print(f"{'='*60}\n")

    # Assertions
    assert overall_throughput >= 500, \
        f"Throughput too low: {overall_throughput:.1f} ops/sec (expected >= 500)"

    assert worst_p99 < 50, \
        f"p99 latency too high: {worst_p99:.2f}ms (expected < 50ms)"

    assert total_allowed == total_ops, \
        f"Operations denied: {total_ops - total_allowed}"

    # Per-process validation
    for result in results:
        assert result['allowed'] == result['ops_count'], \
            f"Process {result['process_id']} had denied operations"
```

---

## Test Fixture Template

```python
"""Common fixtures for distributed rate limiting tests"""
import pytest
import redis
import tempfile
import os


@pytest.fixture
def redis_client():
    """
    Provide Redis client for tests.

    Uses database 15 for isolation from production data.
    Flushes database before and after tests.
    """
    client = redis.Redis(
        host=os.environ.get('REDIS_HOST', 'localhost'),
        port=int(os.environ.get('REDIS_PORT', 6379)),
        db=15,  # Test database
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2
    )

    # Clear test database
    client.flushdb()

    yield client

    # Cleanup
    client.flushdb()
    client.close()


@pytest.fixture
def redis_url():
    """Provide Redis URL for multi-process tests."""
    host = os.environ.get('REDIS_HOST', 'localhost')
    port = os.environ.get('REDIS_PORT', '6379')
    return f"redis://{host}:{port}/15"


@pytest.fixture
def distributed_backend(redis_client):
    """Provide Redis-backed rate limiter."""
    from src.safety.distributed_rate_limiter import RedisRateLimiterBackend

    backend = RedisRateLimiterBackend(redis_client)

    yield backend

    # Cleanup handled by redis_client fixture
```

---

## Lua Script for Atomic Check-and-Increment

```lua
-- check_and_increment.lua
-- Atomically check rate limit and increment counter

local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

-- Get current count
local current = redis.call('GET', key)
if current == false then
    current = 0
else
    current = tonumber(current)
end

-- Check if limit exceeded
if current >= limit then
    -- Return: denied (0), current count
    return {0, current}
end

-- Increment counter
local new_count = redis.call('INCR', key)

-- Set TTL on first increment
if new_count == 1 then
    redis.call('EXPIRE', key, ttl)
end

-- Return: allowed (1), new count
return {1, new_count}
```

**Usage in Python:**

```python
# Pre-register script for better performance
check_and_incr_script = redis_client.register_script("""
    -- Lua script here
""")

# Execute atomically
result = check_and_incr_script(
    keys=['ratelimit:agent-1:commit:1706659200'],
    args=[10, 60]  # limit=10, ttl=60 seconds
)

allowed, count = result
```

---

## Running Tests

### Single Test

```bash
pytest tests/test_safety/test_distributed_rate_limiting.py::test_two_processes_shared_rate_limit -v
```

### All Distributed Tests

```bash
pytest tests/test_safety/test_distributed_rate_limiting.py -v
```

### With Coverage

```bash
pytest tests/test_safety/test_distributed_rate_limiting.py --cov=src/safety/distributed_rate_limiter --cov-report=html
```

### Performance Tests Only

```bash
pytest tests/test_safety/test_distributed_rate_limiting.py -v -m performance
```

### Skip Slow Tests

```bash
pytest tests/test_safety/test_distributed_rate_limiting.py -v -m "not slow"
```

---

## Debugging Tips

### 1. Monitor Redis in Real-Time

```bash
# Terminal 1: Monitor all commands
redis-cli MONITOR

# Terminal 2: Run tests
pytest tests/test_safety/test_distributed_rate_limiting.py::test_two_processes_shared_rate_limit -v -s
```

### 2. Inspect Redis Keys

```python
# In test or debugger
import redis
client = redis.Redis(host='localhost', port=6379, db=15, decode_responses=True)

# List all rate limit keys
keys = client.keys('ratelimit:*')
print(f"Found {len(keys)} keys:")
for key in keys:
    value = client.get(key)
    ttl = client.ttl(key)
    print(f"  {key} = {value} (TTL: {ttl}s)")
```

### 3. Check for Stale Processes

```bash
# Find zombie processes
ps aux | grep test_distributed_rate_limiting

# Kill stale processes
pkill -9 -f test_distributed_rate_limiting
```

### 4. Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or set in test
@pytest.fixture(autouse=True)
def setup_logging(caplog):
    caplog.set_level(logging.DEBUG)
```

---

## Common Issues and Solutions

### Issue: Tests Hang

**Cause**: Process deadlock or Redis connection timeout

**Solution**:
```python
# Always set timeouts
p.join(timeout=10)

# Use context managers
with redis.Redis(...) as client:
    # ...
```

### Issue: Flaky Tests

**Cause**: Race conditions, timing dependencies

**Solution**:
```python
# Use barriers for synchronization
from multiprocessing import Barrier
barrier = manager.Barrier(num_processes)

# In worker
barrier.wait()  # All processes reach this point together
```

### Issue: Redis Connection Refused

**Cause**: Redis not running or wrong port

**Solution**:
```bash
# Check Redis is running
redis-cli ping

# Start Redis
redis-server

# Or use Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### Issue: Memory Leaks

**Cause**: Redis keys not expiring

**Solution**:
```python
# Always set TTL
redis_client.setex(key, ttl, value)

# Or use EXPIRE
redis_client.expire(key, ttl)

# Monitor memory
info = redis_client.info('memory')
print(f"Used memory: {info['used_memory_human']}")
```

---

## Best Practices

1. **Always Clean Up**: Use fixtures with cleanup
2. **Isolate Tests**: Use separate Redis database (db=15)
3. **Use Timeouts**: Prevent hanging tests
4. **Mock Time**: For deterministic timing tests
5. **Test Edge Cases**: Empty strings, None, very long values
6. **Verify Atomicity**: Use barriers for race condition tests
7. **Monitor Performance**: Track throughput and latency
8. **Handle Failures**: Test Redis unavailability
9. **Document Tests**: Clear docstrings with setup/expected
10. **Use Markers**: Categorize tests (critical, slow, performance)
