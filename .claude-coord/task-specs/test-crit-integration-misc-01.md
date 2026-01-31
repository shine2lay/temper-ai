# Task: test-crit-integration-misc-01 - Add Missing Critical Integration Tests

**Priority:** CRITICAL
**Effort:** 3.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add missing critical integration tests for M2+M3, async race conditions, tool rollback cascading, and network timeouts.

---

## Files to Create

- `tests/integration/test_m2_m3_integration.py - M2+M3 integration tests`

---

## Files to Modify

- `tests/test_async/test_concurrency.py - Fix broken race condition tests`
- `tests/integration/test_tool_rollback.py - Add cascading rollback tests`
- `tests/test_error_handling/test_tool_failure_cascade.py - Add error chain validation`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test M2 StandardAgents executing in M3 parallel stage with consensus
- [ ] Fix async race condition tests (assert == 50, not <= 50)
- [ ] Test cascading rollbacks across multiple stages
- [ ] Test full error chain validation (tool → agent → stage → workflow)
- [ ] Test network timeout integration (LLM API, external tools, retry budget)

### Testing
- [ ] M2+M3: standard agents in parallel consensus
- [ ] Async: actually test race conditions (detect corruption)
- [ ] Rollback: cascade through 3+ stages
- [ ] Error chain: verify propagation at each level
- [ ] Timeouts: LLM, tool, and retry timeout interactions

---

## Implementation Details

```python
def test_m2_standard_agents_in_m3_parallel_consensus():
    """Test M2 agents in M3 parallel stage"""
    workflow = create_m2_m3_workflow(
        m2_agents=[StandardAgent("A"), StandardAgent("B")],
        m3_consensus_threshold=1.0
    )
    result = workflow.execute()
    assert result.consensus_reached == True
    assert result.m2_agents_executed == 2

def test_async_race_condition_actually_detects_races():
    """Test async race condition detection (not just <= check)"""
    state = {"writes": 0}

    async def writer():
        for _ in range(50):
            state["writes"] += 1  # Race condition here

    # Without proper locking, should detect corruption
    await asyncio.gather(*[writer() for _ in range(10)])

    # Should be 500, but race condition causes loss
    assert state["writes"] < 500  # Detects the race

    # With locking:
    async def safe_writer():
        async with lock:
            for _ in range(50):
                state["writes"] += 1

    state = {"writes": 0}
    await asyncio.gather(*[safe_writer() for _ in range(10)])
    assert state["writes"] == 500  # No race with locking
```

---

## Test Strategy

Test M2+M3 integration. Fix async race tests. Test cascading failures. Verify error propagation.

---

## Success Metrics

- [ ] M2+M3 integration working
- [ ] Async race condition tests actually detect races
- [ ] Cascading rollback through 3+ stages verified
- [ ] Error chain propagation validated

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** M2StandardAgents, M3Consensus, RollbackManager, ErrorPropagator

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issues #17-20

---

## Notes

Fix async tests to actually detect races. Test network timeout cascading.
