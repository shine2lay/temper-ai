# Task: test-med-improve-error-messages-16 - Improve test failure error messages

**Priority:** NORMAL
**Effort:** 8 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# Weak
assert len(violations) == 1

# Strong
assert len(violations) == 1, (
    f'Expected 1 violation but got {len(violations)}: '
    f'{[v.message for v in violations]}'
)

# Even better
if len(violations) != 1:
    pytest.fail(
        f'Expected exactly 1 violation but got {len(violations)}:\n'
        f'{chr(10).join(f"  - {v.message}" for v in violations)}'
    )

**Module:** Testing Infrastructure
**Issues Addressed:** 7

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_safety/*.py` - Add descriptive error messages
- `tests/test_strategies/*.py` - Add context to assertions

---

## Acceptance Criteria

### Core Functionality

- [ ] All assert statements have descriptive messages
- [ ] Error messages include expected vs actual values
- [ ] Contextual information in error messages
- [ ] Use pytest.fail() with messages for complex failures
- [ ] Error messages help debug failures quickly

### Testing

- [ ] 100+ assertions improved
- [ ] Failure messages are clear and actionable
- [ ] Debugging time reduced
- [ ] All tests pass

---

## Implementation Details

# Weak
assert len(violations) == 1

# Strong
assert len(violations) == 1, (
    f'Expected 1 violation but got {len(violations)}: '
    f'{[v.message for v in violations]}'
)

# Even better
if len(violations) != 1:
    pytest.fail(
        f'Expected exactly 1 violation but got {len(violations)}:\n'
        f'{chr(10).join(f"  - {v.message}" for v in violations)}'
    )

---

## Test Strategy

Review all assertions. Add descriptive messages. Include expected/actual values.

---

## Success Metrics

- [ ] 100+ assertions improved
- [ ] Clear failure messages
- [ ] Faster debugging
- [ ] All tests pass

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#assertion-quality

---

## Notes

Good error messages make debugging 10x faster.
