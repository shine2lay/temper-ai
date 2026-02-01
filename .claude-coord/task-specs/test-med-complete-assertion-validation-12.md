# Task: test-med-complete-assertion-validation-12 - Complete partial assertions with full state validation

**Priority:** NORMAL
**Effort:** 10 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# Weak (before)
result = strategy.synthesize(outputs)
assert result.decision is not None

# Strong (after)
result = strategy.synthesize(outputs)
assert result.decision == 'Option A'
assert result.confidence > 0.8
assert result.reasoning != ''
assert result.metadata['consensus_type'] == 'unanimous'
assert result.metadata['agent_count'] == len(outputs)
assert all(a.id in result.metadata['participants'] for a in outputs)

**Module:** Testing Infrastructure
**Issues Addressed:** 10

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_strategies/*.py` - Add metadata verification
- `tests/test_compiler/*.py` - Verify complete state
- `tests/test_observability/*.py` - Check all fields

---

## Acceptance Criteria

### Core Functionality

- [ ] Tests verify complete object state, not just key fields
- [ ] Metadata content verified, not just existence
- [ ] Error messages fully validated, not just presence
- [ ] Side effects verified (DB state, logs, events)
- [ ] Test helper functions for common validations

### Testing

- [ ] 100+ assertions strengthened
- [ ] Complete state validation in all integration tests
- [ ] Tests catch more regressions
- [ ] All tests pass

---

## Implementation Details

# Weak (before)
result = strategy.synthesize(outputs)
assert result.decision is not None

# Strong (after)
result = strategy.synthesize(outputs)
assert result.decision == 'Option A'
assert result.confidence > 0.8
assert result.reasoning != ''
assert result.metadata['consensus_type'] == 'unanimous'
assert result.metadata['agent_count'] == len(outputs)
assert all(a.id in result.metadata['participants'] for a in outputs)

---

## Test Strategy

Review all tests. Identify partial validation. Add complete checks. Verify tests catch regressions.

---

## Success Metrics

- [ ] 100+ assertions strengthened
- [ ] Complete state validation
- [ ] Tests catch more bugs
- [ ] All tests pass

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#incomplete-assertions

---

## Notes

Stronger assertions catch more regressions and make debugging easier.
