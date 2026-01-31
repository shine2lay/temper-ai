# Task: test-crit-security-rollback-01 - Add Rollback Idempotency and Concurrency Tests

**Priority:** CRITICAL
**Effort:** 2.5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add tests for rollback idempotency (safe to call twice) and concurrent rollback serialization.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_safety/test_rollback.py - Add idempotency and concurrency tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test rollback idempotency (calling rollback twice is safe)
- [ ] Test rollback partial retry after failure
- [ ] Test concurrent rollback attempts are serialized
- [ ] Test double rollback doesn't corrupt state
- [ ] Verify rollback is atomic (all-or-nothing)

### Testing
- [ ] Test calling rollback multiple times on same workflow
- [ ] Test concurrent rollback from multiple threads
- [ ] Test partial rollback failure recovery
- [ ] Edge case: rollback during another rollback

### Security Controls
- [ ] Prevent state corruption from double rollback
- [ ] Ensure rollback serialization with locks

---

## Implementation Details

```python
def test_rollback_idempotency():
    """Test that calling rollback twice is safe"""
    workflow = create_workflow_with_state()
    workflow.rollback()
    initial_state = get_state()
    workflow.rollback()  # Second rollback
    assert get_state() == initial_state  # No state change

def test_concurrent_rollback_attempts_serialization():
    """Test concurrent rollbacks are serialized"""
    workflow = create_workflow_with_state()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(workflow.rollback) for _ in range(5)]
        results = [f.result() for f in futures]
    # All should succeed, but only one does actual work
    assert all(r.success for r in results)
    assert sum(r.performed_rollback for r in results) == 1
```

---

## Test Strategy

Test idempotency with multiple calls. Use threading for concurrency tests. Verify state consistency.

---

## Success Metrics

- [ ] Idempotency verified (no state change on second call)
- [ ] Concurrent rollback serialization working
- [ ] No state corruption in stress tests
- [ ] Tests run in <2 seconds

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** RollbackManager, StateManager, LockManager

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #6

---

## Notes

Use real threading for concurrency tests. Verify lock acquisition order.
