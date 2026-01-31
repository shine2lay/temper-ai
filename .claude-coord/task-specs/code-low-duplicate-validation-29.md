# Task: Extract duplicate validation logic to decorators

## Summary

Create decorator that wraps methods. Check input_data and context types. Raise TypeError with clear messages.

**Estimated Effort:** 4.0 hours
**Module:** agents

---

## Files to Create

_None_

---

## Files to Modify

- src/agents/standard_agent.py - Create validation decorator, use across methods

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create @validate_inputs decorator
- [ ] Handle input_data validation
- [ ] Handle context validation
- [ ] Apply to all execute methods
- [ ] Consistent error messages
### TESTING
- [ ] Test with invalid inputs
- [ ] Test with missing context
- [ ] Verify consistent behavior
- [ ] Check error messages

---

## Implementation Details

Create decorator that wraps methods. Check input_data and context types. Raise TypeError with clear messages.

---

## Test Strategy

Test all decorated methods. Verify validation consistent. Check error messages clear.

---

## Success Metrics

- [ ] No duplicate validation
- [ ] Consistent behavior
- [ ] DRY principle

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** StandardAgent

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#22-duplicate-validation

---

## Notes

No additional notes

