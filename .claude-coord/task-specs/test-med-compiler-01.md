# Task: test-med-compiler-01 - Add Compiler & Observability Medium Priority Tests

**Priority:** MEDIUM
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add medium priority test coverage for compiler and observability edge cases including console streaming buffers, state manager assertions, error scenarios, and workflow state transitions.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_compiler/test_console_streaming.py - Add buffer edge case tests`
- `tests/test_compiler/test_state_manager.py - Strengthen assertions`
- `tests/test_compiler/test_error_scenarios.py - Add missing error scenarios`
- `tests/test_compiler/test_workflow_executor.py - Add state transition tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test console streaming buffer edge cases (overflow, wrap-around)
- [ ] Strengthen state manager assertions (verify exact values, not just existence)
- [ ] Add complete error scenario coverage (all error paths tested)
- [ ] Test workflow executor state transitions (all valid/invalid transitions)
- [ ] Fix non-deterministic tests (remove time dependencies)
- [ ] Add realistic test data (not hardcoded constants)

### Testing
- [ ] Console buffer: test overflow, empty buffer, partial writes
- [ ] State manager: assert exact state values, not just truthy checks
- [ ] Error scenarios: test all error types, verify error messages
- [ ] Workflow transitions: test all state machine paths
- [ ] Determinism: use mocks for time/random, not actual values
- [ ] Test data: use factories to generate realistic varied data

### Quality Improvements
- [ ] Remove weak assertions (assert x is not None → assert x == expected)
- [ ] Add edge case coverage for buffer boundaries
- [ ] Test all error code paths
- [ ] Improve test data variety

---

## Implementation Details

```python
def test_console_streaming_buffer_overflow():
    """Test buffer overflow handling"""
    stream = ConsoleStream(max_size=100)
    large_output = "x" * 200
    stream.write(large_output)
    # Should truncate or page, not crash
    assert len(stream.buffer) <= 100
    assert stream.overflow_count == 1

def test_state_manager_strong_assertions():
    """Test exact state values, not just existence"""
    manager = StateManager()
    manager.set_state("workflow_1", {"step": "processing", "progress": 0.5})

    # Bad: assert manager.get_state("workflow_1") is not None
    # Good: assert exact values
    state = manager.get_state("workflow_1")
    assert state["step"] == "processing"
    assert state["progress"] == 0.5

def test_workflow_executor_state_transitions():
    """Test all valid and invalid state transitions"""
    executor = WorkflowExecutor()

    # Valid: PENDING → RUNNING
    executor.transition("PENDING", "RUNNING")
    assert executor.state == "RUNNING"

    # Invalid: COMPLETED → PENDING (should raise)
    executor.state = "COMPLETED"
    with pytest.raises(InvalidStateTransition):
        executor.transition("COMPLETED", "PENDING")
```

---

## Test Strategy

Test edge cases systematically. Strengthen all assertions. Use factories for test data. Remove time dependencies.

---

## Success Metrics

- [ ] All buffer edge cases tested
- [ ] No weak assertions (all verify exact values)
- [ ] All error scenarios covered
- [ ] All state transitions tested
- [ ] Zero non-deterministic test failures
- [ ] Test data variety improved (no hardcoded constants)

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ConsoleStream, StateManager, WorkflowExecutor

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 3, Medium Issues (Compiler & Observability)

---

## Notes

Use pytest-randomly to detect non-deterministic tests. Use factory_boy for realistic test data.
