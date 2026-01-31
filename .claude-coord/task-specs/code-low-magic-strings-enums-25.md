# Task: Replace magic strings with enums

## Summary

Create enum.Enum subclass. Replace string literals with enum members. Use .value for storage.

**Estimated Effort:** 3.0 hours
**Module:** compiler

---

## Files to Create

_None_

---

## Files to Modify

- src/compiler/executors/parallel.py - Create SynthesisMethod enum

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create SynthesisMethod enum
- [ ] Replace all string literals
- [ ] Update method signatures
- [ ] Type-safe comparisons
### TESTING
- [ ] Test all synthesis methods
- [ ] Verify type safety
- [ ] Check autocomplete works

---

## Implementation Details

Create enum.Enum subclass. Replace string literals with enum members. Use .value for storage.

---

## Test Strategy

Test all enum values. Verify type checking. Check IDE autocomplete.

---

## Success Metrics

- [ ] No magic strings
- [ ] Type-safe
- [ ] Better IDE support

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ParallelStageExecutor

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#20-magic-strings

---

## Notes

No additional notes

