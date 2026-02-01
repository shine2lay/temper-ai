# Task: test-med-session-scoped-fixtures-09 - Optimize fixture scoping for performance

**Priority:** NORMAL
**Effort:** 4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

@pytest.fixture(scope='session')
def test_data_dir():
    '''Path to test data directory (session-scoped for performance)'''
    return Path(__file__).parent / 'fixtures'

@pytest.fixture(scope='module')
def expensive_setup():
    '''Expensive setup that can be shared across module'''
    return initialize_expensive_resource()

**Module:** Testing Infrastructure
**Issues Addressed:** 4

---

## Files to Create

_None_

---

## Files to Modify

- `tests/conftest.py` - Change expensive fixtures to session scope

---

## Acceptance Criteria

### Core Functionality

- [ ] Identify fixtures that don't need per-test setup
- [ ] Change appropriate fixtures to session scope
- [ ] Ensure session-scoped fixtures are immutable
- [ ] Document fixture scopes in docstrings
- [ ] Measure test suite speedup

### Testing

- [ ] All tests pass with new scoping
- [ ] No test interdependencies
- [ ] Test suite runs 10-20% faster
- [ ] No shared state issues

---

## Implementation Details

@pytest.fixture(scope='session')
def test_data_dir():
    '''Path to test data directory (session-scoped for performance)'''
    return Path(__file__).parent / 'fixtures'

@pytest.fixture(scope='module')
def expensive_setup():
    '''Expensive setup that can be shared across module'''
    return initialize_expensive_resource()

---

## Test Strategy

Profile test suite. Identify expensive fixtures. Change scope where safe. Verify no shared state.

---

## Success Metrics

- [ ] Test suite 10-20% faster
- [ ] No shared state issues
- [ ] All tests pass
- [ ] Fixture scopes documented

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** pytest

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#test-performance

---

## Notes

Quick win for test suite performance without changing test logic.
