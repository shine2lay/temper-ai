# Task: Replace Any type hints with specific types

## Summary

Use Protocol for interface types. Use TypeVar for generics. Import from typing.

**Estimated Effort:** 6.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- src/observability/buffer.py - Replace List[Any] with List[Session]
- src/compiler/langgraph_engine.py - Create GraphProtocol and TrackerProtocol
- src/core/service.py - Use specific types for violations

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Identify all Any usages
- [ ] Replace with specific types or protocols
- [ ] Add TypeVar for generics where needed
- [ ] Run mypy to verify
### TESTING
- [ ] mypy passes with no Any warnings
- [ ] IDE autocomplete works
- [ ] No runtime type errors

---

## Implementation Details

Use Protocol for interface types. Use TypeVar for generics. Import from typing.

---

## Test Strategy

Run mypy with --strict. Verify IDE type checking. Test with various types.

---

## Success Metrics

- [ ] Type safety improved
- [ ] Better IDE support
- [ ] Fewer runtime errors

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Multiple modules

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#11-type-hints

---

## Notes

No additional notes

