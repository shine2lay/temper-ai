# Task: test-med-extract-magic-numbers-06 - Extract hard-coded magic numbers to named constants

**Priority:** NORMAL
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# At module level
MAX_SPEEDUP_RATIO = 5.0  # Parallel should be at most 5x faster
STRESS_TEST_ITERATIONS = 1000  # Standard stress test size
PERFORMANCE_THRESHOLD_MS = 10  # Max acceptable latency

# In test
assert speedup < MAX_SPEEDUP_RATIO

**Module:** Testing Infrastructure
**Issues Addressed:** 8

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_benchmarks/test_performance.py` - Extract speedup ranges to constants
- `tests/test_load/test_stress.py` - Extract iteration counts to constants

---

## Acceptance Criteria

### Core Functionality

- [ ] Extract all magic numbers (>5 occurrences) to module constants
- [ ] Use descriptive names: MAX_SPEEDUP_RATIO, STRESS_TEST_ITERATIONS
- [ ] Add docstrings explaining constant purposes
- [ ] Group related constants together
- [ ] No hard-coded numbers in assertions

### Testing

- [ ] All tests pass with constants
- [ ] Easy to adjust test parameters
- [ ] Clear documentation of test expectations

---

## Implementation Details

# At module level
MAX_SPEEDUP_RATIO = 5.0  # Parallel should be at most 5x faster
STRESS_TEST_ITERATIONS = 1000  # Standard stress test size
PERFORMANCE_THRESHOLD_MS = 10  # Max acceptable latency

# In test
assert speedup < MAX_SPEEDUP_RATIO

---

## Test Strategy

Grep for hard-coded numbers. Extract to constants. Verify tests pass.

---

## Success Metrics

- [ ] No magic numbers in assertions
- [ ] All constants documented
- [ ] Easy to adjust test parameters
- [ ] All tests pass

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#hard-coded-values

---

## Notes

Makes tests more maintainable and parameters easier to adjust.
