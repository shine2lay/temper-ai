# Task: Add __all__ exports to __init__ files

## Summary

Add __all__ list. Import public classes. Add module docstring. Document API.

**Estimated Effort:** 2.0 hours
**Module:** Multiple

---

## Files to Create

_None_

---

## Files to Modify

- src/core/__init__.py - Add explicit exports
- src/cli/__init__.py - Add explicit exports

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Define __all__ in each __init__
- [ ] List public API explicitly
- [ ] Add module docstrings
- [ ] Document public vs private
### TESTING
- [ ] Test imports work
- [ ] Verify private not exported
- [ ] Check documentation

---

## Implementation Details

Add __all__ list. Import public classes. Add module docstring. Document API.

---

## Test Strategy

Test from X import *. Verify only intended items exported. Check docs.

---

## Success Metrics

- [ ] Clear public API
- [ ] Private items hidden
- [ ] Better documentation

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** core, cli

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#15-missing-all

---

## Notes

No additional notes

