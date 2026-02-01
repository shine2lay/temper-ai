# Distributed Rate Limiting - Visual Architecture & Test Flow

## System Architecture

### Current In-Memory Architecture (Single Process)

```
┌─────────────────────────────────────────────────────────┐
│                  Single Process                         │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │         RateLimiterPolicy                        │  │
│  │                                                   │  │
│  │  _operation_history = defaultdict(list)          │  │
│  │                                                   │  │
│  │  {                                                │  │
│  │    ('commit', 'agent-1'): [t1, t2, t3, ...],    │  │
│  │    ('deploy', 'agent-1'): [t1, t2],             │  │
│  │  }                                                │  │
│  │                                                   │  │
│  │  ✓ Thread-safe (threading.Lock)                  │  │
│  │  ✗ NOT process-safe                              │  │
│  └──────────────────────────────────────────────────┘  │
│                                                          │
└─────────────────────────────────────────────────────────┘

Problem: Multiple processes each have their own state
         → Global limits NOT enforced!
```

### Target Distributed Architecture (Multi-Process)

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Process 1      │    │   Process 2      │    │   Process 3      │
│                  │    │                  │    │                  │
│  RateLimiter ────┼───▶│  RateLimiter ────┼───▶│  RateLimiter ────┼──┐
│  (Redis Backend) │    │  (Redis Backend) │    │  (Redis Backend) │  │
└──────────────────┘    └──────────────────┘    └──────────────────┘  │
         │                       │                       │              │
         │                       │                       │              │
         └───────────────────────┴───────────────────────┴──────────────┘
                                 │
                                 ▼
                    ┌────────────────────────────┐
                    │       Redis Server         │
                    │  (Shared State Backend)    │
                    │                            │
                    │  Keys:                     │
                    │  ratelimit:agent-1:commit  │
                    │  ratelimit:agent-1:deploy  │
                    │  ratelimit:agent-2:commit  │
                    │  ...                       │
                    │                            │
                    │  ✓ Atomic operations       │
                    │  ✓ TTL expiration          │
                    │  ✓ Process-safe            │
                    └────────────────────────────┘

Benefits:
✓ Global rate limits enforced across all processes
✓ Atomic check-and-increment (Lua scripts)
✓ Automatic cleanup via TTL
✓ Horizontal scaling
```

---

## Key Generation Strategy

### Problem: Key Collisions

```
Bad Example (Vulnerable to collision):
─────────────────────────────────────
agent_id = "agent-1"
operation = "commit"
key = f"{agent_id}{operation}"  # ❌ "agent-1commit"

Collision with:
agent_id = "agent"
operation = "1-commit"
key = f"{agent_id}{operation}"  # ❌ "agent1-commit" (SAME!)
```

### Solution: Proper Namespacing

```
Good Example (Safe):
────────────────────
def _make_key(agent_id: str, operation: str, window_seconds: int) -> str:
    # 1. Sanitize agent_id
    safe_agent = agent_id.replace(':', '_').replace('/', '_')

    # 2. Calculate window start (time-based key)
    now = int(time.time())
    window_start = (now // window_seconds) * window_seconds

    # 3. Use consistent delimiter
    return f"ratelimit:{safe_agent}:{operation}:{window_start}"
    #       ^prefix    ^delimiter  ^delimiter  ^timestamp

Example Keys:
┌─────────────────────────────────────────────────────────────────┐
│ ratelimit:agent-1:commit:1706659200                             │
│ ratelimit:agent-2:commit:1706659200                             │
│ ratelimit:agent-1:deploy:1706659200                             │
│ ratelimit:agent_日本:tool_call:1706659200  (Unicode safe)       │
│ ratelimit:agent_1:commit:1706659260  (Next window)              │
└─────────────────────────────────────────────────────────────────┘

Properties:
✓ No collisions
✓ Deterministic
✓ TTL-friendly (time-based)
✓ Unicode-safe
✓ Special character-safe
```

---

## Atomic Check-and-Increment Flow

### Problem: Race Condition (Without Atomicity)

```
Timeline:
────────────────────────────────────────────────────────────
Process 1                     Process 2                     Redis
────────────────────────────────────────────────────────────
GET counter                                                 counter=9
                              GET counter                   counter=9
counter=9, check(9<10) ✓
                              counter=9, check(9<10) ✓
INCR counter                                                counter=10
                              INCR counter                  counter=11 ❌

Result: Both processes succeeded! Limit exceeded (11 > 10)
```

### Solution: Lua Script Atomicity

```
Timeline with Lua Script:
────────────────────────────────────────────────────────────
Process 1                     Process 2                     Redis
────────────────────────────────────────────────────────────
EVALSHA script [args]                                       Executing...
  ├─ GET counter                                            counter=9
  ├─ check (9<10) ✓
  ├─ INCR counter                                           counter=10
  └─ return [1, 10] ✓
                              EVALSHA script [args]         Executing...
                                ├─ GET counter              counter=10
                                ├─ check (10<10) ✗
                                └─ return [0, 10] ✗

Result: Process 1 succeeded, Process 2 denied. Limit enforced! ✓

Lua Script:
───────────
local current = redis.call('GET', KEYS[1])
if current == false then current = 0 else current = tonumber(current) end

if current >= limit then
    return {0, current}  -- Denied
end

local new = redis.call('INCR', KEYS[1])
if new == 1 then redis.call('EXPIRE', KEYS[1], ttl) end

return {1, new}  -- Allowed

Key Property: Entire block executes atomically (Redis single-threaded)
```

---

## Multi-Process Test Flow

### Test: Two Processes, Shared Limit

```
Setup:
──────
Global Limit: 10 operations/minute
Process 1: Attempt 6 operations
Process 2: Attempt 6 operations

Expected: 10 succeed, 2 fail

Timeline:
─────────────────────────────────────────────────────────────────────

Process 1                    Redis State                 Process 2
─────────────────────────────────────────────────────────────────────
Start                        counter=0                   Start
  │
  ├─ Op 1 ──────────────────▶ counter=1 ◀──────────────── Op 1
  ├─ Op 2 ──────────────────▶ counter=2 ◀──────────────── Op 2
  ├─ Op 3 ──────────────────▶ counter=3 ◀──────────────── Op 3
  │                           counter=4
  │                           counter=5
  ├─ Op 4 ──────────────────▶ counter=6
  ├─ Op 5 ──────────────────▶ counter=7
  ├─ Op 6 ──────────────────▶ counter=8 ◀──────────────── Op 4
  │                           counter=9 ◀──────────────── Op 5
  │                           counter=10 ◀─────────────── Op 6 ✓
  │                           counter=10 (DENIED) ◀────── Op 7 ✗
  │
Join/Wait                    counter=10                  Join/Wait

Results:
────────
Process 1: 6 allowed, 0 denied
Process 2: 4 allowed, 2 denied
Total:     10 allowed, 2 denied ✓
```

### Test: Race Condition at Limit

```
Setup:
──────
Limit: 10 operations
Both processes have consumed 9 operations
Both processes simultaneously attempt 10th operation

Timeline:
─────────────────────────────────────────────────────────────────────

Process 1                    Redis (Lua Script)          Process 2
─────────────────────────────────────────────────────────────────────
                             counter=9
  │                                                         │
  ├─ EVALSHA (consume 1) ────────────────────────────────┐ │
  │                          ┌─ Atomic Block Start ───────┤ │
  │                          │  current = GET(key)  → 9   │ │
  │                          │  check (9 < 10) ✓          │ │
  │                          │  INCR(key) → 10            │ │
  │                          │  return [1, 10] ✓          │ │
  │                          └─ Atomic Block End ─────────┘ │
  │                          counter=10                     │
  ◀────────── [1, 10] (ALLOWED)                             │
  │                                                          │
  │                                                          ├─ EVALSHA
  │                          ┌─ Atomic Block Start ─────────┤
  │                          │  current = GET(key) → 10     │
  │                          │  check (10 < 10) ✗           │
  │                          │  return [0, 10] ✗            │
  │                          └─ Atomic Block End ───────────┘
  │                                               [0, 10] ──▶
  │                                               (DENIED)
  │                          counter=10 (unchanged)
  │
Join                         counter=10                  Join

Results:
────────
Process 1: ALLOWED ✓
Process 2: DENIED ✓
Final count: 10 (exact limit) ✓
```

---

## Clock Skew Handling

### Problem: Time Drift Between Processes

```
Scenario:
─────────
Process 1 clock: 2026-01-31 12:00:00 (accurate)
Process 2 clock: 2026-01-31 12:00:02 (+2 seconds ahead)
Process 3 clock: 2026-01-31 11:59:58 (-2 seconds behind)

Window size: 60 seconds

Without normalization:
──────────────────────
Process 1: window_start = 1706707200 (12:00:00)
Process 2: window_start = 1706707200 (12:00:02 → rounds to 12:00:00) ✓
Process 3: window_start = 1706707140 (11:59:58 → rounds to 11:59:00) ✗

Result: Process 3 uses DIFFERENT window → limits not shared! ❌
```

### Solution: Server-Side Timestamps

```
Good Approach:
──────────────
def _make_key(...):
    # Use Redis server time (consistent across all processes)
    server_time = redis.time()[0]  # Redis TIME command
    window_start = (server_time // window_seconds) * window_seconds
    return f"ratelimit:{agent}:{op}:{window_start}"

Alternative (Good Enough):
──────────────────────────
def _make_key(...):
    # Use local time but round to window boundaries
    # Small skew (±2s) won't affect 60s windows much
    now = int(time.time())
    window_start = (now // window_seconds) * window_seconds
    return f"ratelimit:{agent}:{op}:{window_start}"

Trade-off:
├─ Server time: Extra Redis call, but perfect accuracy
└─ Local time: No extra call, but skew-sensitive

Recommendation: Use local time with boundary tolerance in tests
```

---

## Test Execution Flow

### Typical Multi-Process Test

```
┌─────────────────────────────────────────────────────────────────┐
│                        Test Process (pytest)                    │
│                                                                  │
│  1. Setup Phase                                                 │
│     ├─ Initialize Redis client                                  │
│     ├─ Flush test database (db=15)                              │
│     ├─ Create multiprocessing Queue for results                 │
│     └─ Define test parameters (limits, processes, etc.)         │
│                                                                  │
│  2. Spawn Worker Processes                                      │
│     ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐│
│     │   Process 1     │  │   Process 2     │  │  Process N   ││
│     │                 │  │                 │  │              ││
│     │  worker_func()  │  │  worker_func()  │  │ worker_func()││
│     │  ├─ Connect Redis│ │  ├─ Connect Redis│ │ ├─ Connect   ││
│     │  ├─ Perform ops │  │  ├─ Perform ops │  │ ├─ Perform   ││
│     │  └─ Put results │  │  └─ Put results │  │ └─ Put result││
│     └─────────────────┘  └─────────────────┘  └──────────────┘│
│            │                     │                     │        │
│            └─────────────────────┴─────────────────────┘        │
│                               │                                 │
│  3. Wait for Completion                                         │
│     └─ process.join(timeout=10)                                 │
│                                                                  │
│  4. Collect Results                                             │
│     └─ while not queue.empty(): results.append(queue.get())     │
│                                                                  │
│  5. Assertions                                                  │
│     ├─ assert total_allowed == expected_limit                   │
│     ├─ assert total_denied == expected_denied                   │
│     ├─ assert no_errors()                                       │
│     └─ assert redis_state_consistent()                          │
│                                                                  │
│  6. Cleanup                                                     │
│     └─ redis.flushdb()                                          │
└─────────────────────────────────────────────────────────────────┘

Worker Function Template:
─────────────────────────
def worker(redis_url, agent_id, ops_count, result_queue):
    # 1. Initialize
    client = redis.Redis.from_url(redis_url)
    backend = RedisRateLimiterBackend(client)

    results = {'allowed': 0, 'denied': 0}

    # 2. Perform operations
    for i in range(ops_count):
        allowed, count = backend.check_and_increment(...)
        if allowed:
            results['allowed'] += 1
        else:
            results['denied'] += 1

    # 3. Return results
    result_queue.put(results)
    client.close()
```

---

## Test Synchronization Patterns

### Pattern 1: Barrier Synchronization (Race Tests)

```
Purpose: Make all processes reach a point simultaneously
─────────────────────────────────────────────────────────

from multiprocessing import Barrier, Manager

manager = Manager()
barrier = manager.Barrier(num_processes)

def worker(barrier, ...):
    # Do setup work
    setup()

    # Wait for all processes to reach this point
    barrier.wait()  ◀─────────┐
                              │  All processes blocked here
    # Now all processes        │  until last one arrives
    # start simultaneously  ────┘  Then all released together!
    critical_operation()

Timeline:
─────────
Process 1: setup() ────────────┐
Process 2: setup() ──────┐     │
Process 3: setup() ─┐    │     │
                    │    │     │
                    ▼    ▼     ▼
                 barrier.wait() ◀── All blocked
                    │    │     │
                    ▼    ▼     ▼
                 All released at same time!
                    │    │     │
                    ▼    ▼     ▼
             critical_operation() in parallel
```

### Pattern 2: Queue-Based Result Collection

```
Purpose: Collect results from worker processes safely
──────────────────────────────────────────────────────

from multiprocessing import Queue, Manager

manager = Manager()
result_queue = manager.Queue()

def worker(result_queue, ...):
    # Do work
    result = perform_operations()

    # Put result in queue (thread-safe, process-safe)
    result_queue.put(result)

# Main test process
results = []
while not result_queue.empty():
    results.append(result_queue.get())

# Aggregate
total = sum(r['count'] for r in results)
```

### Pattern 3: Delayed Start (Interleaving Test)

```
Purpose: Test interleaved operations
────────────────────────────────────

def worker(delay_ms, ...):
    # Stagger start times
    time.sleep(delay_ms / 1000.0)
    perform_operations()

# Spawn with different delays
Process(target=worker, args=(0, ...))     # Start immediately
Process(target=worker, args=(100, ...))   # Start after 100ms
Process(target=worker, args=(200, ...))   # Start after 200ms

Timeline:
─────────
Process 1: ████████████████████
Process 2:       ████████████████████
Process 3:             ████████████████████
           ├────┼────┼────┼────┼────┼────┤
           0   100  200  300  400  500  600ms

Result: Operations interleaved naturally
```

---

## Redis Key Lifecycle

### Time-Based Window Keys

```
Window Size: 60 seconds
Current Time: 1706707245 (12:00:45)

Key Generation:
───────────────
window_start = (1706707245 // 60) * 60 = 1706707200 (12:00:00)
key = "ratelimit:agent-1:commit:1706707200"
ttl = 120 seconds (2× window for safety)

Timeline:
─────────────────────────────────────────────────────────────────
Time    Event                              Redis State
─────────────────────────────────────────────────────────────────
12:00:00 First operation                   SET key=1, EXPIRE 120
12:00:05 Second operation                  INCR key → 2
12:00:30 Tenth operation                   INCR key → 10
12:00:35 Eleventh operation                GET key=10, check fails
12:00:45 More operations                   All denied (limit=10)
12:00:59 Last operation in window          Still denied
12:01:00 NEW WINDOW STARTS                 New key created!
         key = "ratelimit:agent-1:commit:1706707260"
12:01:01 First op in new window            SET new_key=1, EXPIRE 120
12:02:00 Old key expires                   DEL old_key (TTL=0)
─────────────────────────────────────────────────────────────────

Keys Over Time:
───────────────
11:59:00-12:00:00  ratelimit:agent-1:commit:1706707140
12:00:00-12:01:00  ratelimit:agent-1:commit:1706707200 ◀── Active
12:01:00-12:02:00  ratelimit:agent-1:commit:1706707260 ◀── Next
12:02:00-12:03:00  ratelimit:agent-1:commit:1706707320

TTL ensures old keys auto-expire:
├─ Window 1: Created at 12:00, expires at 12:02 (120s)
├─ Window 2: Created at 12:01, expires at 12:03 (120s)
└─ No manual cleanup needed! ✓
```

---

## Error Handling Flow

### Redis Connection Failure

```
┌────────────────────────────────────────────────────────────┐
│                   Application Process                      │
│                                                             │
│  try:                                                       │
│      allowed, count = backend.check_and_increment(...)     │
│      │                                                      │
│      ├─ EVALSHA script (Redis call) ───X─▶ ConnectionError│
│      │                                                      │
│  except redis.ConnectionError as e:                         │
│      logger.error(f"Redis unavailable: {e}")               │
│      │                                                      │
│      ├─ Mode: "fail_open" ──▶ return (True, 0)   # Allow  │
│      └─ Mode: "fail_closed" ─▶ return (False, 0) # Deny   │
│                                                             │
│  Retry Strategy (exponential backoff):                     │
│  ├─ Attempt 1: Immediate                                   │
│  ├─ Attempt 2: 100ms delay                                 │
│  ├─ Attempt 3: 200ms delay                                 │
│  └─ Attempt 4: 400ms delay → Give up                       │
│                                                             │
│  Circuit Breaker:                                          │
│  ├─ After 10 consecutive failures                          │
│  ├─ Open circuit (stop trying Redis)                       │
│  ├─ Auto-close after 60 seconds                            │
│  └─ Gradual recovery                                       │
└────────────────────────────────────────────────────────────┘

Configuration:
──────────────
failover:
  mode: "fail_open"  # or "fail_closed"
  retry:
    attempts: 3
    initial_delay_ms: 100
    backoff_multiplier: 2.0
  circuit_breaker:
    failure_threshold: 10
    timeout_seconds: 60
```

---

## Performance Benchmarking

### Throughput Test Setup

```
Scenario: 10 processes, 100 ops each = 1000 total operations
───────────────────────────────────────────────────────────────

Measurement Points:
───────────────────
├─ Overall throughput: total_ops / elapsed_time
├─ Per-process throughput: ops_per_process / process_elapsed
├─ Latency distribution: p50, p95, p99, max
└─ Redis metrics: commands/sec, memory usage

Timeline:
─────────
Start ─────────────────────────────────────────────────▶ End
  │                                                        │
  ├─ P1: ████████████████████ (100 ops)                   │
  ├─ P2: ████████████████████                             │
  ├─ P3: ████████████████████                             │
  ├─ P4: ████████████████████                             │
  ├─ P5: ████████████████████                             │
  ├─ P6: ████████████████████                             │
  ├─ P7: ████████████████████                             │
  ├─ P8: ████████████████████                             │
  ├─ P9: ████████████████████                             │
  └─ P10:████████████████████                             │
  │                                                        │
  0s                                                      2s

Results:
────────
Total time: 2.0 seconds
Throughput: 1000 / 2.0 = 500 ops/sec ✓

Per-operation latency:
├─ p50: 5ms
├─ p95: 15ms
├─ p99: 25ms ✓ (target: <50ms)
└─ max: 45ms

Success Criteria:
├─ Throughput >= 500 ops/sec ✓
├─ p99 latency < 50ms ✓
└─ Zero errors ✓
```

---

## Test Markers and Organization

```
# Test file structure with markers

@pytest.mark.critical
@pytest.mark.multiprocess
def test_two_processes_shared_rate_limit(...):
    """CRITICAL: Verify global limit enforcement."""
    ...

@pytest.mark.security
@pytest.mark.high
def test_special_characters_in_ids(...):
    """HIGH (Security): Prevent key injection."""
    ...

@pytest.mark.performance
@pytest.mark.slow
def test_throughput_with_10_processes(...):
    """MEDIUM: Performance benchmarking."""
    ...

Run specific categories:
────────────────────────
pytest -m critical          # Critical tests only
pytest -m "not slow"        # Skip slow tests
pytest -m "security"        # Security tests only
pytest -m "multiprocess"    # Multi-process tests
```

---

## Summary: Test Coverage Matrix

```
┌────────────────────────────────────────────────────────────────┐
│ Test Category          │ Tests │ Priority │ Estimated Time    │
├────────────────────────────────────────────────────────────────┤
│ Basic Distributed      │  10   │ CRITICAL │ 30 min            │
│ Clock Skew & Timing    │   5   │ HIGH     │ 15 min            │
│ Cache Invalidation     │   5   │ MEDIUM   │ 15 min            │
│ Agent ID Normalization │   6   │ HIGH     │ 20 min            │
│ Multi-Process Coord    │   8   │ CRITICAL │ 40 min            │
│ Race Conditions        │   8   │ CRITICAL │ 40 min            │
│ Failure & Recovery     │   6   │ HIGH     │ 30 min            │
│ Performance            │   4   │ MEDIUM   │ 20 min            │
├────────────────────────────────────────────────────────────────┤
│ Total                  │  52   │ Mixed    │ 3.5 hours runtime │
└────────────────────────────────────────────────────────────────┘

Priority Distribution:
──────────────────────
CRITICAL: 15 tests (29%)  ████████████████████████████
HIGH:     18 tests (35%)  ██████████████████████████████████
MEDIUM:   15 tests (29%)  ████████████████████████████
LOW:       4 tests (7%)   ███████

Implementation Order:
─────────────────────
Week 1: CRITICAL tests (15) → Core functionality validated
Week 2: HIGH tests (18)     → Edge cases covered
Week 3: MEDIUM tests (15)   → Full coverage achieved
Week 4: LOW tests (4)       → Nice-to-have scenarios
```

---

**Document Version**: 1.0
**Last Updated**: 2026-01-31
**Purpose**: Visual guide for distributed rate limiting architecture and test flow
