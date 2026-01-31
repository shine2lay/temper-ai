# Task: Add resource limits to Calculator tool

## Summary

Define constants. Check lengths before parsing. Implement _get_ast_depth(). Handle OverflowError.

**Estimated Effort:** 4.0 hours
**Module:** tools

---

## Files to Create

_None_

---

## Files to Modify

- src/tools/calculator.py - Add value limits, expression length, AST depth checks

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] MAX_NUMBER_VALUE = 10**100
- [ ] MAX_EXPRESSION_LENGTH = 1000
- [ ] MAX_COMPUTATION_DEPTH = 100
- [ ] Validate before evaluation
- [ ] Handle OverflowError
### TESTING
- [ ] Test with 9**9**9
- [ ] Test with long expressions
- [ ] Test with deeply nested operations
- [ ] Verify limits enforced

---

## Implementation Details

Define constants. Check lengths before parsing. Implement _get_ast_depth(). Handle OverflowError.

---

## Test Strategy

Test DoS vectors (9**9**9, nested operations). Verify graceful errors. Check performance.

---

## Success Metrics

- [ ] No DoS possible
- [ ] Resource limits enforced
- [ ] Graceful error handling

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Calculator

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#low-calculator-limits

---

## Notes

No additional notes

