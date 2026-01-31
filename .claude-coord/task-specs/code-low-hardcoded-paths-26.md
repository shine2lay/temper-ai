# Task: Make package paths auto-detectable

## Summary

Use inspect.getmodule(). Extract __package__. Provide tools_package parameter for override.

**Estimated Effort:** 2.0 hours
**Module:** tools

---

## Files to Create

_None_

---

## Files to Modify

- src/tools/registry.py - Auto-detect package path in auto_discover

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Auto-detect package from __file__
- [ ] Make tools_package parameter optional
- [ ] Fallback to sensible default
- [ ] Document detection logic
### TESTING
- [ ] Test with default detection
- [ ] Test with explicit package
- [ ] Test from different locations

---

## Implementation Details

Use inspect.getmodule(). Extract __package__. Provide tools_package parameter for override.

---

## Test Strategy

Test discovery from various locations. Verify correct package detected. Test override works.

---

## Success Metrics

- [ ] Auto-detection works
- [ ] Less brittle code
- [ ] Override available

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ToolRegistry

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#low-hardcoded-paths

---

## Notes

No additional notes

