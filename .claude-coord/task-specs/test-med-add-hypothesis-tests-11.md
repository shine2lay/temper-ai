# Task: test-med-add-hypothesis-tests-11 - Add property-based tests with Hypothesis

**Priority:** NORMAL
**Effort:** 12 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

from hypothesis import given, strategies as st

@given(st.text())
def test_sanitize_preserves_length_invariant(input_str):
    '''Property: Sanitized string never longer than input'''
    result = sanitize(input_str)
    assert len(result) <= len(input_str)

@given(st.lists(st.integers()))
def test_sort_is_idempotent(lst):
    '''Property: Sorting twice gives same result as once'''
    once = sort(lst)
    twice = sort(sort(lst))
    assert once == twice

**Module:** Property Testing
**Issues Addressed:** 5

---

## Files to Create

- `tests/property/test_config_properties.py` - Config validation properties
- `tests/property/test_state_properties.py` - State machine properties

---

## Files to Modify

- `tests/property/test_consensus_properties.py` - Expand existing properties
- `tests/property/test_validation_properties.py` - Add more validation properties

---

## Acceptance Criteria

### Core Functionality

- [ ] Add property tests for config validation
- [ ] Add property tests for state machine invariants
- [ ] Add property tests for string sanitization
- [ ] Use Hypothesis strategies for complex data generation
- [ ] Test invariants: 'for all X, property Y holds'

### Testing

- [ ] 20+ new property tests
- [ ] Each property runs 100+ examples
- [ ] Properties find edge cases missed by unit tests
- [ ] No property violations found

---

## Implementation Details

from hypothesis import given, strategies as st

@given(st.text())
def test_sanitize_preserves_length_invariant(input_str):
    '''Property: Sanitized string never longer than input'''
    result = sanitize(input_str)
    assert len(result) <= len(input_str)

@given(st.lists(st.integers()))
def test_sort_is_idempotent(lst):
    '''Property: Sorting twice gives same result as once'''
    once = sort(lst)
    twice = sort(sort(lst))
    assert once == twice

---

## Test Strategy

Identify invariants. Express as properties. Use Hypothesis to generate test cases.

---

## Success Metrics

- [ ] 20+ property tests added
- [ ] Properties find edge cases
- [ ] No violations found
- [ ] 100+ examples per property

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Hypothesis

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#property-based-testing

---

## Notes

Property tests find edge cases that unit tests miss. Highly valuable for validation code.
