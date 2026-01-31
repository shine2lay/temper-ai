# Task: test-crit-tools-timeout-01 - Add Tool Executor Timeout Cleanup Tests

**Priority:** CRITICAL
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add tests for tool executor timeout cleanup to prevent resource leaks and hanging threads.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_tools/test_executor.py - Add timeout cleanup tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test timeout cleanup forces thread termination
- [ ] Test timeout prevents resource leaks
- [ ] Test timeout with hanging operations
- [ ] Verify threads are cleaned up after timeout
- [ ] Test timeout doesn't corrupt tool state

### Testing
- [ ] Test tool execution timeout enforcement
- [ ] Test thread cleanup after timeout
- [ ] Test resource cleanup (files, sockets, etc.)
- [ ] Edge case: timeout during cleanup

### Security Controls
- [ ] Prevent resource exhaustion from hanging tools
- [ ] Ensure timeout doesn't leave orphaned processes

---

## Implementation Details

```python
def test_timeout_cleanup_forces_thread_termination():
    """Test timed-out operations release threads properly"""
    executor = ToolExecutor(timeout=1.0)

    def hanging_tool():
        time.sleep(10)  # Hangs for 10s
        return "done"

    with pytest.raises(TimeoutError):
        executor.execute(hanging_tool)

    # Verify thread was terminated
    assert executor.active_threads == 0

def test_timeout_resource_leak_prevention():
    """Test timeout doesn't leak resources"""
    executor = ToolExecutor(timeout=0.5)

    def resource_hungry_tool():
        f = open("/tmp/test.txt", "w")
        time.sleep(10)
        f.close()

    with pytest.raises(TimeoutError):
        executor.execute(resource_hungry_tool)

    # Verify file handle was closed
    assert not executor.has_open_file_handles()
```

---

## Test Strategy

Test timeout enforcement. Verify thread and resource cleanup. Test hanging operations.

---

## Success Metrics

- [ ] Timeout cleanup verified (no orphaned threads)
- [ ] Resource leak prevention tested
- [ ] All tests complete in <3 seconds
- [ ] No flaky tests

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ToolExecutor, ThreadManager

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 1, Critical Issue #12

---

## Notes

Use threading.Event for graceful shutdown. Test file handle cleanup.
