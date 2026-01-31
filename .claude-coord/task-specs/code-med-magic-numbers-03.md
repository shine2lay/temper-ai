# Task: Extract magic numbers to named constants

## Summary

Create module-level or class-level constants. Add docstrings explaining values. Consider making configurable.

**Estimated Effort:** 3.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- src/compiler/config_loader.py - Create ConfigSecurityLimits class
- src/observability/buffer.py - Create BufferConfig constants
- src/safety/rollback_api.py - Define snapshot limit constants

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create constants for all magic numbers
- [ ] Add documentation explaining rationale
- [ ] Make configurable where appropriate
- [ ] Update all usages
### TESTING
- [ ] Verify behavior unchanged
- [ ] Test with different constant values
- [ ] Document tuning guidance

---

## Implementation Details

Create module-level or class-level constants. Add docstrings explaining values. Consider making configurable.

---

## Test Strategy

Verify all hardcoded values replaced. Test with different values to ensure configurability works.

---

## Success Metrics

- [ ] No magic numbers remain
- [ ] Values documented
- [ ] Easier to tune

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Multiple modules

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#medium-issues

---

## Notes

No additional notes

