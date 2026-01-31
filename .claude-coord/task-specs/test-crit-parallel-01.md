# Task: test-crit-parallel-01 - Add Parallel Execution Race Condition Tests

**Priority:** CRITICAL
**Effort:** 3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add comprehensive race condition tests for parallel agent execution to prevent state corruption under concurrent access.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_compiler/test_parallel_execution.py - Add race condition tests beyond happy path`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test race conditions between parallel agent executions
- [ ] Test shared resource conflicts in parallel mode
- [ ] Test deadlock scenarios with synthesis aggregation
- [ ] Test partial failure handling (some agents succeed, some fail)
- [ ] Verify thread safety of shared state
- [ ] Ensure proper locking mechanisms

### Testing
- [ ] Use ThreadPoolExecutor for real threading tests
- [ ] Test with 2, 4, 8, 16 concurrent agents
- [ ] Stress test: 100+ concurrent operations
- [ ] Edge case: All agents fail simultaneously
- [ ] Edge case: Agents complete in random order

### Security Controls
- [ ] Prevent data races on shared state
- [ ] Detect deadlock conditions
- [ ] Validate state consistency after parallel execution

---

## Implementation Details

```python
def test_race_conditions_between_parallel_agents():
    """Test concurrent agent execution doesn't corrupt shared state"""
    shared_state = SharedState()
    def agent_task(agent_id):
        for i in range(100):
            shared_state.increment(agent_id)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(agent_task, i) for i in range(10)]
        wait(futures)
    assert shared_state.total == 1000

def test_deadlock_scenarios_with_synthesis_aggregation():
    """Test synthesis aggregation doesn't deadlock"""
    executor = ParallelExecutor()
    results = executor.run_parallel([
        agent_with_dependency(A, depends_on=B),
        agent_with_dependency(B, depends_on=A)
    ])
    with pytest.raises(DeadlockDetectedError, match="Circular dependency"):
        executor.aggregate_results(results, timeout=5)
```

---

## Test Strategy

Use real threading (not async). Stress test with high concurrency. Verify state consistency and deadlock detection.

---

## Success Metrics

- [ ] All race condition scenarios tested with real threads
- [ ] Tests detect state corruption when locks removed
- [ ] Deadlock detection works within 5 seconds
- [ ] Tests run in <2 seconds total

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ParallelExecutor, SharedState, SynthesisAggregator

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #2

---

## Notes

Must use REAL threading, not async. Use thread barrier synchronization for flaky test prevention.
