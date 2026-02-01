# Task: test-med-unicode-edge-cases-03 - Add comprehensive Unicode edge case tests

**Priority:** NORMAL
**Effort:** 10 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

@pytest.mark.parametrize('agent_name', [
    'agent-😀',  # Emoji
    'agent-\u200b',  # Zero-width space
    'agent-\ud83d\ude00',  # Surrogate pair
    'café',  # é (single char)
    'cafe\u0301',  # é (e + combining acute)
])
def test_agent_name_unicode(agent_name):
    # Test handling of Unicode edge cases

**Module:** Validation
**Issues Addressed:** 8

---

## Files to Create

- `tests/test_validation/test_unicode_edge_cases.py` - Comprehensive Unicode test suite

---

## Files to Modify

_None_

---

## Acceptance Criteria

### Core Functionality

- [ ] Test emoji in agent names, file paths, configs
- [ ] Test right-to-left (RTL) text in configs
- [ ] Test zero-width characters in strings
- [ ] Test surrogate pairs in file paths
- [ ] Test Unicode normalization attacks (é vs e + ́)
- [ ] Test combining characters
- [ ] Test homograph attacks (Latin 'a' vs Cyrillic 'а')
- [ ] Test bidirectional text override attacks

### Testing

- [ ] 50+ Unicode edge case tests
- [ ] Parameterized tests for different Unicode categories
- [ ] Test both acceptance and rejection scenarios

---

## Implementation Details

@pytest.mark.parametrize('agent_name', [
    'agent-😀',  # Emoji
    'agent-\u200b',  # Zero-width space
    'agent-\ud83d\ude00',  # Surrogate pair
    'café',  # é (single char)
    'cafe\u0301',  # é (e + combining acute)
])
def test_agent_name_unicode(agent_name):
    # Test handling of Unicode edge cases

---

## Test Strategy

Use parameterized tests for Unicode categories. Test both valid and invalid Unicode. Verify proper normalization.

---

## Success Metrics

- [ ] 50+ Unicode edge cases tested
- [ ] All Unicode handled gracefully
- [ ] No crashes on edge cases
- [ ] Clear error messages for invalid Unicode

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Hypothesis

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#52-edge-cases-gaps

---

## Notes

Essential for international users and security (homograph attacks).
