# Task: Fix thread pool leak in ToolExecutor destructor

## Summary

In __del__, call executor.shutdown(wait=False, cancel_futures=True). Log failures at CRITICAL level.

**Estimated Effort:** 2.0 hours
**Module:** tools

---

## Files to Create

_None_

---

## Files to Modify

- src/tools/executor.py - Force shutdown with cancel_futures in __del__

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Force shutdown in __del__ with cancel_futures=True
- [ ] Log critical warning if cleanup fails
- [ ] Include executor_id and worker_count in logs
### TESTING
- [ ] Test destructor called without explicit shutdown
- [ ] Verify threads cleaned up
- [ ] Check warnings logged

---

## Implementation Details

In __del__, call executor.shutdown(wait=False, cancel_futures=True). Log failures at CRITICAL level.

---

## Test Strategy

Create executor without closing. Trigger GC. Verify threads cleaned. Check logs.

---

## Success Metrics

- [ ] No thread leaks
- [ ] Warnings visible
- [ ] Cleanup forced

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ToolExecutor

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#medium-thread-pool

---

## Notes

No additional notes

