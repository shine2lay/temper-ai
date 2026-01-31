# Task: Extract template method for conflict resolution

## Summary

Create template method in ConflictResolutionStrategy. Pass winner_selector as Callable. Extract common code.

**Estimated Effort:** 4.0 hours
**Module:** strategies

---

## Files to Create

_None_

---

## Files to Modify

- src/strategies/conflict_resolution.py - Create base template method

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create _resolve_with_winner_selection() in base
- [ ] Extract common logic (validate, filter, build result)
- [ ] Subclasses implement winner_selector only
- [ ] Reduce code duplication
### TESTING
- [ ] Test each resolver
- [ ] Verify behavior unchanged
- [ ] Check winner selection correct

---

## Implementation Details

Create template method in ConflictResolutionStrategy. Pass winner_selector as Callable. Extract common code.

---

## Test Strategy

Test all resolvers. Verify identical behavior. Check DRY principle satisfied.

---

## Success Metrics

- [ ] No code duplication
- [ ] Single source of truth
- [ ] Easier to extend

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ConflictResolutionStrategy, HighestConfidenceResolver, RandomTiebreakerResolver

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#low-duplicate-code

---

## Notes

No additional notes

