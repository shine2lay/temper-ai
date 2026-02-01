# Task: test-med-split-large-files-01 - Split large test files into focused modules

**Priority:** NORMAL
**Effort:** 8 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# Move tests to new files by logical grouping
# test_experiment_lifecycle.py gets all lifecycle tests
# test_early_stopping.py gets all early stopping tests
# Ensure fixtures are either moved or imported

**Module:** Testing Infrastructure
**Issues Addressed:** 3

---

## Files to Create

- `tests/test_experimentation/test_experiment_lifecycle.py` - Split from test_integration.py
- `tests/test_experimentation/test_early_stopping.py` - Split from test_integration.py
- `tests/test_benchmarks/test_benchmarks_compilation.py` - Split from test_performance.py
- `tests/test_benchmarks/test_benchmarks_database.py` - Split from test_performance.py

---

## Files to Modify

- `tests/test_experimentation/test_integration.py` - Remove moved tests, keep core integration
- `tests/test_benchmarks/test_performance.py` - Remove moved tests, keep general benchmarks

---

## Acceptance Criteria

### Core Functionality

- [ ] test_integration.py reduced from 643 LOC to <300 LOC
- [ ] test_performance.py reduced from 768 LOC to <300 LOC
- [ ] Each new file focuses on single concern (lifecycle, early stopping, etc.)
- [ ] All tests still pass after split
- [ ] No duplicate test logic across files

### Testing

- [ ] Run full test suite to verify no breakage
- [ ] Update imports in all affected tests
- [ ] Verify test discovery finds all split tests

---

## Implementation Details

# Move tests to new files by logical grouping
# test_experiment_lifecycle.py gets all lifecycle tests
# test_early_stopping.py gets all early stopping tests
# Ensure fixtures are either moved or imported

---

## Test Strategy

Run pytest --collect-only to verify all tests discovered. Run full suite to verify all pass.

---

## Success Metrics

- [ ] All test files <400 LOC
- [ ] Clear separation of concerns
- [ ] All tests pass
- [ ] Test discovery finds all tests

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

Improves maintainability and readability. Makes it easier to find specific tests.
