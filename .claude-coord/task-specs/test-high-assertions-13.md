# Task: Improve assertion quality in tests

## Summary

# Weak
assert len(violations) >= 1

# Strong
assert len(violations) == 1
assert violations[0].severity == Severity.CRITICAL
assert 'file_write_redirect' in violations[0].message

**Priority:** HIGH  
**Estimated Effort:** 16.0 hours  
**Module:** Testing Infrastructure  
**Issues Addressed:** 25

---

## Files to Create

_None_

---

## Files to Modify

- `tests/safety/test_forbidden_operations.py` - Replace >= assertions with exact counts
- `tests/test_observability/test_console.py` - Replace string containment with regex
- `tests/test_compiler/test_stage_compiler.py` - Add graph structure validation

---

## Acceptance Criteria


### Core Functionality

- [ ] All weak assertions identified and strengthened
- [ ] Exact counts instead of >= comparisons
- [ ] Specific field checks (severity, message, metadata)
- [ ] Regex patterns for string validation

### Testing

- [ ] Review 100+ tests with weak assertions
- [ ] Fix top 25 most critical weak assertions
- [ ] Add assertion quality linting rule


---

## Implementation Details

# Weak
assert len(violations) >= 1

# Strong
assert len(violations) == 1
assert violations[0].severity == Severity.CRITICAL
assert 'file_write_redirect' in violations[0].message

---

## Test Strategy

Grep for weak assertion patterns. Replace with specific checks. Add pre-commit hook.

---

## Success Metrics

- [ ] 25+ weak assertions strengthened
- [ ] Test failures more informative
- [ ] Assertion quality >90%

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#33-weak-assertion-quality-high---test-effectiveness

---

## Notes

Improves test effectiveness and debugging.
