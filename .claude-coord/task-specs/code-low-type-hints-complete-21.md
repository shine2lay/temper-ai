# Task: Complete type hints coverage across codebase

## Summary

Use TypeVar for generic types. Add Protocol for interfaces. Import from typing. Run mypy regularly.

**Estimated Effort:** 8.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- src/strategies/consensus.py - Add type hints to _break_tie
- src/strategies/base.py - Add TypeVar for decision_groups
- src/tools/base.py - Complete _check_type hints

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Add missing return type hints
- [ ] Complete parameter type hints
- [ ] Use TypeVar for generics
- [ ] Run mypy with --strict
### TESTING
- [ ] mypy passes with no errors
- [ ] IDE autocomplete works
- [ ] Type errors caught at dev time

---

## Implementation Details

Use TypeVar for generic types. Add Protocol for interfaces. Import from typing. Run mypy regularly.

---

## Test Strategy

Run mypy --strict. Fix all errors. Verify IDE type checking improves.

---

## Success Metrics

- [ ] 100% type hint coverage
- [ ] mypy passes
- [ ] Better IDE support

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** All modules

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#low-missing-type-hints

---

## Notes

No additional notes

