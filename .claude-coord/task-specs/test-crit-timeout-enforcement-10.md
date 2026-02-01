# Task: Fix timeout test to actually test timeout enforcement

## Summary

class SlowTool(Tool):
    def execute(self, params, context):
        time.sleep(3.0)  # Guaranteed to timeout
        return {'result': 'done'}

def test_tool_timeout_enforced():
    executor = ToolExecutor()
    start = time.time()
    with pytest.raises(TimeoutError):
        executor.execute('SlowTool', {}, timeout=1)
    elapsed = time.time() - start
    assert elapsed < 1.5  # Should timeout at ~1s, not wait for 3s

**Priority:** CRITICAL  
**Estimated Effort:** 2.0 hours  
**Module:** Error Handling  
**Issues Addressed:** 1

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_error_handling/test_timeout_scenarios.py` - Use SlowTool with sleep > timeout to ensure timeout triggers

---

## Acceptance Criteria


### Core Functionality

- [ ] Timeout test uses tool that definitely exceeds timeout
- [ ] Verify TimeoutError raised
- [ ] Verify tool execution stopped
- [ ] Verify resources cleaned up after timeout
- [ ] Test cascading timeouts (tool → agent → stage)

### Testing

- [ ] Test with timeout=1s, tool takes 3s
- [ ] Verify timeout happens at ~1s, not 3s
- [ ] Verify partial results not returned
- [ ] Verify thread/process terminated


---

## Implementation Details

class SlowTool(Tool):
    def execute(self, params, context):
        time.sleep(3.0)  # Guaranteed to timeout
        return {'result': 'done'}

def test_tool_timeout_enforced():
    executor = ToolExecutor()
    start = time.time()
    with pytest.raises(TimeoutError):
        executor.execute('SlowTool', {}, timeout=1)
    elapsed = time.time() - start
    assert elapsed < 1.5  # Should timeout at ~1s, not wait for 3s

---

## Test Strategy

Create SlowTool that sleeps longer than timeout. Verify timeout exception raised. Verify execution stopped early.

---

## Success Metrics

- [ ] Timeout enforced correctly
- [ ] Execution stopped at timeout
- [ ] Resources cleaned up
- [ ] Cascading timeouts tested

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ToolExecutor, TimeoutHandler

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#28-timeout-enforcement-not-validated-high

---

## Notes

Test currently uses fast Calculator that never times out, making it meaningless.
