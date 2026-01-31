# Task: Improve SQL injection sanitizer precision

## Summary

Use \b for word boundaries. Document parameterized queries as primary defense. Add warning docstring.

**Estimated Effort:** 3.0 hours
**Module:** tools

---

## Files to Create

_None_

---

## Files to Modify

- src/tools/base.py - Use word boundaries and more precise patterns

---

## Acceptance Criteria

### CORE FUNCTIONALITY
- [ ] Use regex word boundaries (\b)
- [ ] More precise pattern matching
- [ ] Reduce false positives
- [ ] Document defense-in-depth approach
- [ ] Emphasize parameterized queries
### TESTING
- [ ] Test with legitimate inputs (SELECTED, --help)
- [ ] Test with actual SQL injection
- [ ] Measure false positive rate

---

## Implementation Details

Use \b for word boundaries. Document parameterized queries as primary defense. Add warning docstring.

---

## Test Strategy

Test legitimate use cases. Verify SQL injection still blocked. Check false positive rate <5%.

---

## Success Metrics

- [ ] False positives reduced
- [ ] SQL injection still blocked
- [ ] Clear documentation

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** ParameterSanitizer

---

## Design References

- .claude-coord/reports/code-review-20260128-224245.md#medium-sql-injection

---

## Notes

No additional notes

