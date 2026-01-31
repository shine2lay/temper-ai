# Task: Sanitize sensitive data in CLI output

## Summary

Create sanitization method. Check for sensitive key names. Replace with ***REDACTED***.

**Estimated Effort:** 2.0 hours
**Module:** cli

---

## Files to Create

_None_

---

## Files to Modify

- src/cli/rollback.py - Add _sanitize_action_for_display method

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Create _sanitize_action_for_display()
- [ ] Redact sensitive keys (api_key, password, token, secret)
- [ ] Apply before displaying
- [ ] Use SecretRedactingFormatter
### TESTING
- [ ] Test with actions containing secrets
- [ ] Verify redaction works
- [ ] Check display safe

---

## Implementation Details

Create sanitization method. Check for sensitive key names. Replace with ***REDACTED***.

---

## Test Strategy

Create actions with api_key. Display and verify redacted. Test various key names.

---

## Success Metrics

- [ ] No secrets in output
- [ ] Consistent redaction
- [ ] Safe for logs

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** CLI rollback commands

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#13-sensitive-logging

---

## Notes

No additional notes

