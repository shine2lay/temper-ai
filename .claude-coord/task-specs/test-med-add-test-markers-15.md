# Task: test-med-add-test-markers-15 - Add comprehensive test markers for organization

**Priority:** NORMAL
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# pytest.ini
[pytest]
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (moderate speed)
    e2e: End-to-end tests (slow, full stack)
    slow: Slow tests (>1s)
    security: Security-focused tests
    regression: Regression tests

# In test
@pytest.mark.unit
@pytest.mark.security
def test_secret_detection():
    ...

**Module:** Testing Infrastructure
**Issues Addressed:** 5

---

## Files to Create

_None_

---

## Files to Modify

- `pytest.ini` - Define all test markers
- `tests/**/test_*.py` - Add markers to tests

---

## Acceptance Criteria

### Core Functionality

- [ ] Define markers: unit, integration, e2e, slow, security, regression
- [ ] Mark all tests with appropriate markers
- [ ] Document markers in pytest.ini
- [ ] CI runs appropriate marker subsets
- [ ] Easy to run specific test categories

### Testing

- [ ] All tests have at least one marker
- [ ] Markers documented in pytest.ini
- [ ] pytest -m 'marker' runs correct subset
- [ ] CI uses markers for test selection

---

## Implementation Details

# pytest.ini
[pytest]
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (moderate speed)
    e2e: End-to-end tests (slow, full stack)
    slow: Slow tests (>1s)
    security: Security-focused tests
    regression: Regression tests

# In test
@pytest.mark.unit
@pytest.mark.security
def test_secret_detection():
    ...

---

## Test Strategy

Define markers. Add to all tests. Verify marker filtering works. Update CI.

---

## Success Metrics

- [ ] All tests have markers
- [ ] Marker filtering works
- [ ] CI uses markers
- [ ] Documentation complete

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

Makes it easy to run specific test categories. Essential for CI optimization.
