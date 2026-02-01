# Distributed Observability Test Strategy

## Overview

This document describes the comprehensive test strategy for distributed observability tracking with multi-process coordination in the meta-autonomous-framework.

**Test File:** `/home/shinelay/meta-autonomous-framework/tests/test_observability/test_distributed_tracking.py`

**Coverage:** 23 test scenarios across 7 test classes

## Test Architecture

### Multi-Process Testing Framework

```
Test Process (pytest)
├── Spawn Worker Process 1 → SQLite DB (shared)
├── Spawn Worker Process 2 → SQLite DB (shared)
├── Spawn Worker Process 3 → SQLite DB (shared)
├── ...
└── Collect Results via Queue → Verify Consistency
```

**Key Components:**
- **Shared Database:** Temporary SQLite file accessible by all processes
- **Result Queue:** `multiprocessing.Queue` for collecting results
- **Process Isolation:** Each worker process resets and reinitializes database connection
- **Timeout Protection:** All process joins have timeouts to prevent hanging

## Test Classes & Coverage

### 1. Multi-Process Workflow Tracking (5 tests)

**Purpose:** Verify basic multi-process coordination works correctly.

| Test | Processes | What It Tests |
|------|-----------|---------------|
| `test_concurrent_workflow_tracking_2_processes` | 2 | Basic multi-process coordination |
| `test_concurrent_workflow_tracking_5_processes` | 5 | Moderate concurrent load |
| `test_concurrent_workflow_tracking_10_processes` | 10 | High concurrent load (80% success threshold) |
| `test_concurrent_workflow_with_staggered_start` | 5 | Realistic concurrent access patterns |
| `test_concurrent_workflow_with_same_name` | 3 | Workflow name indexing conflicts |

**Verification:**
- All workflows tracked successfully
- Complete hierarchy (workflow → stage → agent → llm/tool)
- No duplicate IDs
- Correct completion status

### 2. Distributed Locking & Concurrency (4 tests)

**Purpose:** Verify concurrent writes handle locking correctly.

| Test | Isolation Level | What It Tests |
|------|----------------|---------------|
| `test_concurrent_updates_same_workflow_read_committed` | READ_COMMITTED | Default isolation behavior |
| `test_concurrent_updates_same_workflow_serializable` | SERIALIZABLE | Strict isolation behavior |
| `test_concurrent_llm_call_tracking` | Default | LLM call tracking race conditions |
| `test_concurrent_agent_metric_updates` | Default | Agent metrics aggregation races |

**Key Patterns:**
- **Read-Modify-Write:** Read record, modify, commit
- **Concurrent Updates:** Multiple processes updating same record
- **Lost Update Detection:** Verify final state consistency
- **Metric Aggregation:** Verify counts don't have race conditions

### 3. Transaction Conflicts & Recovery (3 tests)

**Purpose:** Verify transaction conflict detection and retry mechanisms.

| Test | What It Tests |
|------|---------------|
| `test_detect_concurrent_modification_conflict` | Concurrent modification detection |
| `test_retry_after_transaction_conflict` | Retry with exponential backoff |
| `test_foreign_key_constraint_enforcement` | FK constraints prevent orphaned records |

**Retry Pattern:**
```python
max_retries = 3
for attempt in range(max_retries):
    try:
        with session:
            # Read-modify-write
            ...
        return  # Success
    except Exception:
        if attempt == max_retries - 1:
            raise
        time.sleep(0.05 * (attempt + 1))  # Exponential backoff
```

### 4. Process Crash Recovery (3 tests)

**Purpose:** Verify system handles process crashes gracefully.

| Test | Crash Point | What It Tests |
|------|-------------|---------------|
| `test_workflow_left_running_after_crash` | Mid-workflow | Workflows left in 'running' state |
| `test_stage_left_running_after_crash` | Mid-stage | Stages left in 'running' state |
| `test_detect_orphaned_workflows_by_timeout` | N/A | Timeout-based orphan detection |

**Crash Simulation:**
```python
# Simulate crash without cleanup
if simulate_crash:
    os._exit(1)  # Hard exit, no exception handlers
```

**Orphan Detection:**
```sql
SELECT * FROM workflow_executions
WHERE status = 'running'
  AND start_time < (NOW() - INTERVAL '1 hour')
```

### 5. Orphaned Resource Cleanup (2 tests)

**Purpose:** Verify orphaned resources can be cleaned up.

| Test | What It Tests |
|------|---------------|
| `test_cleanup_orphaned_workflows` | Mark orphaned workflows as failed |
| `test_cascade_cleanup_orphaned_hierarchy` | Cascade cleanup to stages/agents |

**Cleanup Pattern:**
```python
# Find orphaned workflows
orphaned = session.exec(
    select(WorkflowExecution).where(
        WorkflowExecution.status == "running",
        WorkflowExecution.start_time < timeout_threshold
    )
).all()

# Mark as failed with error message
for wf in orphaned:
    wf.status = "failed"
    wf.error_message = "Workflow orphaned (process crashed)"
    wf.end_time = datetime.now(timezone.utc)
```

### 6. Clock Skew & Timing Issues (3 tests)

**Purpose:** Verify timestamp handling across processes.

| Test | What It Tests |
|------|---------------|
| `test_workflows_with_different_timestamps` | Timestamp ordering |
| `test_duration_calculation_with_timezone_aware_timestamps` | Duration calculations |
| `test_concurrent_workflows_completion_order` | Completion order preservation |

**Clock Skew Simulation:**
```python
# Create workflows with timestamps spread across 10 seconds
offsets = [-5, -2, 0, 2, 5]
start_time = datetime.now(timezone.utc) + timedelta(seconds=offset)
```

### 7. Data Consistency Verification (3 tests)

**Purpose:** Verify data integrity after concurrent operations.

| Test | What It Tests |
|------|---------------|
| `test_verify_no_duplicate_workflow_ids` | UUID uniqueness |
| `test_verify_foreign_key_relationships_intact` | Referential integrity |
| `test_verify_metric_aggregation_consistency` | Aggregated metrics accuracy |

**Consistency Checks:**
1. **No Duplicates:** `len(ids) == len(set(ids))`
2. **FK Integrity:** All child records reference valid parents
3. **Metric Accuracy:** Aggregates match sum of child records

## Test Patterns & Best Practices

### Pattern 1: Multi-Process Worker Function

```python
def worker_function(db_url: str, process_id: int, result_queue: Queue):
    """Worker process that performs database operations."""
    try:
        # 1. Reset database in child process
        reset_database()

        # 2. Initialize database connection
        init_database(db_url)

        # 3. Perform work
        tracker = ExecutionTracker()
        with tracker.track_workflow(...) as wf_id:
            # Do work
            ...

        # 4. Return success
        result_queue.put({"status": "success", "workflow_id": wf_id})

    except Exception as e:
        # 5. Return error
        result_queue.put({"status": "error", "error": str(e)})
```

**Key Points:**
- Always reset database in child process
- Use `result_queue` for communication (not return values)
- Include error handling to prevent silent failures

### Pattern 2: Process Lifecycle Management

```python
# 1. Create processes
processes = [
    Process(target=worker_function, args=(db_url, i, queue))
    for i in range(num_processes)
]

# 2. Start all processes
for p in processes:
    p.start()

# 3. Wait with timeout
for p in processes:
    p.join(timeout=15)
    if p.is_alive():
        p.terminate()  # Force kill if hanging

# 4. Collect results
results = []
while not result_queue.empty():
    results.append(result_queue.get())
```

**Key Points:**
- Always set timeouts on `join()` to prevent hanging tests
- Terminate processes that don't complete
- Drain result queue completely

### Pattern 3: Shared Database Setup

```python
@pytest.fixture
def temp_db_path():
    """Create temporary database file."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    yield f"sqlite:///{db_path}"

    # Cleanup
    try:
        if os.path.exists(db_path):
            os.unlink(db_path)
    except Exception:
        pass

@pytest.fixture
def shared_db(temp_db_path):
    """Initialize shared database."""
    reset_database()
    db_manager = init_database(temp_db_path)
    yield db_manager
    reset_database()
```

**Key Points:**
- Use file-based SQLite (not `:memory:`) for multi-process sharing
- Clean up temporary files after tests
- Reset database state between tests

### Pattern 4: Crash Simulation

```python
def track_workflow_with_crash(
    db_url: str,
    simulate_crash: bool,
    crash_at_stage: str,
    result_queue: Queue
):
    """Worker that may crash mid-execution."""
    reset_database()
    init_database(db_url)
    tracker = ExecutionTracker()

    with tracker.track_workflow("workflow", config) as wf_id:
        if crash_at_stage == 'workflow' and simulate_crash:
            os._exit(1)  # Crash without cleanup

        with tracker.track_stage("stage", config, wf_id) as st_id:
            if crash_at_stage == 'stage' and simulate_crash:
                os._exit(1)

            # Continue normal execution...
```

**Key Points:**
- Use `os._exit(1)` for hard crash (bypasses exception handlers)
- Test different crash points (workflow, stage, agent)
- Verify database state after crash

## Edge Cases & Failure Modes

### Edge Case 1: SQLite Write Contention

**Issue:** SQLite allows concurrent reads but serializes writes. Under high write concurrency, some transactions may fail with "database is locked" error.

**Test Strategy:**
- Test with 10+ concurrent processes
- Allow 80% success rate (some failures expected)
- Verify no data corruption on failures

**Mitigation:**
- Implement retry logic with exponential backoff
- Use WAL mode for better concurrency (future improvement)
- Consider PostgreSQL for production deployments

### Edge Case 2: Lost Updates

**Issue:** Two processes read same record, modify it, and commit. Last write wins, first write is lost.

**Test Strategy:**
- Test concurrent updates to same workflow
- Verify final state is one of the valid states
- Test both READ_COMMITTED and SERIALIZABLE isolation

**Mitigation:**
- Use SERIALIZABLE isolation for critical operations
- Implement optimistic locking with version numbers
- Use atomic operations where possible

### Edge Case 3: Orphaned Records

**Issue:** Process crashes mid-transaction, leaving workflow in "running" state forever.

**Test Strategy:**
- Simulate crashes at different points
- Verify orphaned records can be detected
- Test cleanup mechanisms

**Mitigation:**
- Periodic cleanup job to mark old "running" workflows as failed
- Timeout-based detection (workflows running > 1 hour)
- Cascade cleanup to child records

### Edge Case 4: Foreign Key Violations

**Issue:** Concurrent deletion and insertion may cause FK constraint violations.

**Test Strategy:**
- Try to create stage with non-existent workflow
- Verify FK constraints are enforced
- Test cascade deletes

**Mitigation:**
- Database FK constraints prevent orphaned records
- Use transactions to ensure atomicity
- Test cleanup respects FK relationships

### Edge Case 5: Clock Skew

**Issue:** Different processes may have slightly different system clocks.

**Test Strategy:**
- Create workflows with different timestamps
- Verify ordering is preserved
- Test duration calculations

**Mitigation:**
- Always use timezone-aware timestamps
- Use UTC for all timestamps
- Handle both timezone-aware and naive datetimes gracefully

### Edge Case 6: Metric Aggregation Races

**Issue:** Parent workflow metrics are aggregated from child agents. If multiple processes update child agents concurrently, aggregation may be incorrect.

**Test Strategy:**
- Test concurrent agent metric updates
- Verify aggregation is eventually consistent
- Allow some tolerance (80-100% accuracy)

**Mitigation:**
- Perform aggregation on workflow completion (when all agents done)
- Use SQL aggregation queries instead of Python loops
- Implement idempotent aggregation (can be run multiple times)

## Test Execution Recommendations

### Running Tests

```bash
# Run all distributed tracking tests
pytest tests/test_observability/test_distributed_tracking.py -v

# Run specific test class
pytest tests/test_observability/test_distributed_tracking.py::TestMultiProcessWorkflowTracking -v

# Run with parallel execution (careful with multi-process tests!)
pytest tests/test_observability/test_distributed_tracking.py -n auto

# Run with coverage
pytest tests/test_observability/test_distributed_tracking.py --cov=src.observability --cov-report=html
```

### Test Performance

**Expected Runtime:**
- Full suite: ~60-90 seconds
- Per test: 2-10 seconds
- Process spawn overhead: ~0.5s per process

**Resource Usage:**
- Memory: ~50-100MB per spawned process
- Disk: Temporary SQLite files (~1-5MB each)
- CPU: Depends on number of concurrent processes

### Debugging Tips

1. **Check process exit codes:**
   ```python
   for p in processes:
       p.join()
       if p.exitcode != 0:
           print(f"Process {p.pid} failed with code {p.exitcode}")
   ```

2. **Enable logging in child processes:**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

3. **Inspect database after test:**
   ```python
   with shared_db.session() as session:
       workflows = session.exec(select(WorkflowExecution)).all()
       for wf in workflows:
           print(f"{wf.id}: {wf.status}")
   ```

4. **Add delays to reduce contention:**
   ```python
   time.sleep(0.1 * process_id)  # Stagger process starts
   ```

## Success Criteria

### Test Suite Quality

- [ ] All tests pass on first run (no flaky tests)
- [ ] Coverage >= 85% for multi-process code paths
- [ ] No race conditions detected
- [ ] No data corruption under concurrent load
- [ ] Cleanup mechanisms work correctly
- [ ] Foreign key relationships maintained
- [ ] Metrics aggregation is accurate

### Test Reliability

- [ ] Tests complete within timeout (no hanging)
- [ ] Tests clean up resources (no temp file leaks)
- [ ] Tests are isolated (no cross-test interference)
- [ ] Tests handle failures gracefully
- [ ] Error messages are actionable

### Production Readiness

- [ ] System handles 10+ concurrent processes
- [ ] Crashes are detected and cleaned up
- [ ] Orphaned resources are identified
- [ ] Retry mechanisms work correctly
- [ ] Data consistency is maintained
- [ ] Performance is acceptable (< 100ms overhead per operation)

## Future Enhancements

### Test Coverage Improvements

1. **Add stress tests:** 50-100 concurrent processes
2. **Add long-running tests:** Workflows that run for hours
3. **Add memory leak tests:** Monitor memory usage over time
4. **Add network partition tests:** Simulate network failures (for distributed DB)

### Feature Additions

1. **Distributed locking:** Implement Redis-based distributed locks
2. **Leader election:** One process coordinates cleanup
3. **Heartbeat monitoring:** Processes send heartbeats to detect crashes faster
4. **Automatic retry:** Built-in retry logic for transient failures

### Database Improvements

1. **PostgreSQL support:** Better concurrency than SQLite
2. **WAL mode:** Enable SQLite WAL for better concurrent writes
3. **Connection pooling:** Reuse connections across requests
4. **Optimistic locking:** Version numbers for conflict detection

## Conclusion

This comprehensive test suite verifies that the observability system correctly handles multi-process coordination, concurrent writes, process crashes, and orphaned resource cleanup. The tests use realistic patterns and edge cases to ensure production readiness.

**Key Takeaways:**
- Multi-process testing requires careful setup and cleanup
- SQLite has limitations under high write concurrency (use PostgreSQL for production)
- Retry logic is essential for handling transient failures
- Orphaned resource cleanup is critical for crash recovery
- Metric aggregation requires eventual consistency handling

**Next Steps:**
1. Run full test suite to verify all tests pass
2. Review coverage report to identify gaps
3. Add stress tests for production load scenarios
4. Consider PostgreSQL for production deployments
