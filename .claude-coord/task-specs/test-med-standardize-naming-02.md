# Task: test-med-standardize-naming-02 - Standardize test naming conventions across all files

**Priority:** NORMAL
**Effort:** 6 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# Use grep to find all test name patterns
# Rename systematically: test_feature_behavior_condition
# Update references in conftest and imports

**Module:** Testing Infrastructure
**Issues Addressed:** 5

---

## Files to Create

_None_

---

## Files to Modify

- `tests/test_validation/test_boundary_values.py` - Standardize test method names
- `tests/regression/*.py` - Remove _scenario/_regression suffixes
- `tests/test_strategies/*.py` - Consistent test_<component>_<behavior> pattern

---

## Acceptance Criteria

### Core Functionality

- [ ] All tests follow pattern: test_<component>_<behavior>_<condition>
- [ ] Remove inconsistent suffixes (_scenario, _regression, _validation)
- [ ] Test class names: Test<Feature><Aspect>
- [ ] Fixture names lowercase with underscores

### Testing

- [ ] All tests still pass after rename
- [ ] No duplicate test names
- [ ] Test discovery finds all tests

---

## Implementation Details

# Use grep to find all test name patterns
# Rename systematically: test_feature_behavior_condition
# Update references in conftest and imports

---

## Test Strategy

Run pytest --collect-only before/after to compare. Ensure same number of tests discovered.

---

## Success Metrics

- [ ] 100% of tests follow naming convention
- [ ] All tests pass
- [ ] No naming conflicts

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#test-organization

---

## Notes

Consistency makes tests easier to find and understand.
