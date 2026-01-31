# Task: Add logging to silent callback failures

## Summary

Replace except Exception: pass with logging. Include callback.__name__. Add exc_info=True.

**Estimated Effort:** 1.0 hours
**Module:** safety

---

## Files to Create

_None_

---

## Files to Modify

- src/safety/rollback.py - Log callback exceptions
- src/safety/approval.py - Log callback exceptions

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Log callback exceptions at ERROR level
- [ ] Include callback name in logs
- [ ] Include exc_info for stack traces
- [ ] Don't re-raise (callbacks are optional)
### TESTING
- [ ] Test with failing callbacks
- [ ] Verify exceptions logged
- [ ] Check processing continues

---

## Implementation Details

Replace except Exception: pass with logging. Include callback.__name__. Add exc_info=True.

---

## Test Strategy

Create callbacks that raise. Verify logged. Check processing continues.

---

## Success Metrics

- [ ] Failures visible
- [ ] Stack traces available
- [ ] Processing continues

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** RollbackManager, ApprovalPolicy

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#11-silent-callback

---

## Notes

No additional notes

