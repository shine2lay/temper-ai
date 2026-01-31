# Task: Standardize CLI error handling

## Summary

Create error handler with operation parameter. Switch on exception type. Format consistently.

**Estimated Effort:** 2.0 hours
**Module:** cli

---

## Files to Create

_None_

---

## Files to Modify

- src/cli/rollback.py - Create handle_cli_error function

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create handle_cli_error() utility
- [ ] Consistent error message format
- [ ] Appropriate error types handled
- [ ] Log unexpected errors
### TESTING
- [ ] Test with ValueError
- [ ] Test with PermissionError
- [ ] Test with unexpected errors
- [ ] Verify consistent messages

---

## Implementation Details

Create error handler with operation parameter. Switch on exception type. Format consistently.

---

## Test Strategy

Trigger various errors. Verify messages consistent. Check logging.

---

## Success Metrics

- [ ] Consistent error UX
- [ ] Better debugging
- [ ] Clear messages

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** CLI commands

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#14-error-handling-cli

---

## Notes

No additional notes

