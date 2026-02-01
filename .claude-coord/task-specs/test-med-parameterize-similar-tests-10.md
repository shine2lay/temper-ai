# Task: test-med-parameterize-similar-tests-10 - Use parameterized tests to reduce duplication

**Priority:** NORMAL
**Effort:** 8 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# Before (3 separate tests)
def test_confidence_zero(): assert valid(0.0)
def test_confidence_one(): assert valid(1.0)
def test_confidence_half(): assert valid(0.5)

# After (1 parameterized test)
@pytest.mark.parametrize('confidence', [0.0, 0.5, 1.0])
def test_confidence_values(confidence):
    assert valid(confidence)

**Module:** Testing Infrastructure
**Issues Addressed:** 6

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_validation/test_boundary_values.py` - Parameterize 10 test classes into 1
- `tests/test_strategies/*.py` - Parameterize similar tests

---

## Acceptance Criteria

### Core Functionality

- [ ] Identify duplicate test logic with different inputs
- [ ] Replace with @pytest.mark.parametrize
- [ ] Reduce test LOC by 30%+ in affected files
- [ ] Easier to add new test cases
- [ ] Clear parameter names in parametrize

### Testing

- [ ] All tests still pass
- [ ] Same number of test cases executed
- [ ] Easier to add new test cases
- [ ] Reduced code duplication

---

## Implementation Details

# Before (3 separate tests)
def test_confidence_zero(): assert valid(0.0)
def test_confidence_one(): assert valid(1.0)
def test_confidence_half(): assert valid(0.5)

# After (1 parameterized test)
@pytest.mark.parametrize('confidence', [0.0, 0.5, 1.0])
def test_confidence_values(confidence):
    assert valid(confidence)

---

## Test Strategy

Find duplicate test patterns. Replace with parametrize. Verify same tests run.

---

## Success Metrics

- [ ] 30% reduction in test LOC
- [ ] Same test coverage
- [ ] All tests pass
- [ ] Easier to add cases

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** pytest

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#test-organization

---

## Notes

Reduces duplication and makes adding new test cases trivial.
