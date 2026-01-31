# Task: Extract duplicate agent/stage name extraction logic

## Summary

Create utils.py with extract_agent_name() and extract_stage_name(). Handle str, dict, and object types.

**Estimated Effort:** 2.0 hours
**Module:** compiler

---

## Files to Create

_None_

---

## Files to Modify

- src/compiler/utils.py - Create shared extraction utilities
- src/compiler/executors/sequential.py - Use shared utilities
- src/compiler/executors/parallel.py - Use shared utilities
- src/compiler/node_builder.py - Use shared utilities

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create extract_agent_name() utility
- [ ] Create extract_stage_name() utility
- [ ] Update all usages
- [ ] Consistent behavior across modules
### TESTING
- [ ] Test with string refs
- [ ] Test with dict refs
- [ ] Test with object refs
- [ ] Verify all modules work

---

## Implementation Details

Create utils.py with extract_agent_name() and extract_stage_name(). Handle str, dict, and object types.

---

## Test Strategy

Test all input formats. Verify consistent behavior across modules.

---

## Success Metrics

- [ ] No code duplication
- [ ] Single source of truth
- [ ] Easier to maintain

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Compiler executors

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#7-8-duplicate-code

---

## Notes

No additional notes

