# Task: test-crit-integration-m3m4-01 - Add M3+M4 Integration E2E Test

**Priority:** CRITICAL
**Effort:** 3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add end-to-end integration test for M3 (multi-agent consensus) + M4 (rollback) to verify rollback correctly handles multi-agent stage failures.

---

## Files to Create

- `tests/integration/test_m3_m4_integration.py - New M3+M4 integration test file`

---

## Files to Modify

- None

---

## Acceptance Criteria


### Core Functionality
- [ ] Test multi-agent consensus failure triggers M4 rollback
- [ ] Test M3 parallel stage failure triggers M4 rollback cascade
- [ ] Test M4 rollback with M3 partial consensus
- [ ] Verify rollback handles multi-agent state correctly
- [ ] Test observability tracking for M3+M4 integration

### Testing
- [ ] E2E test: M3 consensus → failure → M4 rollback
- [ ] Test partial consensus scenarios
- [ ] Test rollback cascade through multiple stages
- [ ] Edge case: mixed success/failure in parallel agents

### Integration
- [ ] Verify M3 and M4 components integrate correctly
- [ ] Test database tracking for M3+M4 workflow
- [ ] Ensure state consistency after rollback

---

## Implementation Details

```python
def test_multi_agent_consensus_failure_triggers_rollback():
    """Test M3 multi-agent stage failure triggers M4 rollback"""
    workflow = create_m3_m4_workflow(
        agents=3,
        consensus_threshold=0.7,
        rollback_on_failure=True
    )

    # Simulate 2/3 agents failing (below consensus threshold)
    result = workflow.execute([
        Agent(behavior="success"),
        Agent(behavior="fail"),
        Agent(behavior="fail")
    ])

    # Should trigger rollback
    assert result.status == "rolled_back"
    assert result.consensus_reached == False
    assert workflow.get_state() == initial_state  # State rolled back

def test_m4_rollback_with_m3_partial_consensus():
    """Test rollback handles M3 partial consensus correctly"""
    workflow = create_m3_m4_workflow(agents=5, consensus_threshold=0.6)

    # 3/5 agents succeed (60% - exactly at threshold)
    result = workflow.execute([
        Agent(behavior="success"),
        Agent(behavior="success"),
        Agent(behavior="success"),
        Agent(behavior="fail"),
        Agent(behavior="fail")
    ])

    # At threshold - should succeed
    assert result.consensus_reached == True
    # But if any step fails after consensus, should rollback
    workflow.fail_next_step()
    assert workflow.get_state() == initial_state
```

---

## Test Strategy

Test full M3+M4 integration E2E. Verify rollback handles consensus failures. Test state consistency.

---

## Success Metrics

- [ ] M3+M4 integration fully tested E2E
- [ ] Rollback correctly handles consensus failures
- [ ] State consistency verified after rollback
- [ ] Observability tracking working for M3+M4

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** M3ConsensusEngine, M4RollbackManager, WorkflowOrchestrator

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #16

---

## Notes

Test consensus threshold edge cases. Verify observability database tracking.
