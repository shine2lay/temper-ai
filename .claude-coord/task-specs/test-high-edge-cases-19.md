# Task: Add comprehensive edge case tests

## Summary

@pytest.mark.parametrize('confidence', [0.0, 1.0, float('nan'), float('inf'), -float('inf')])
def test_confidence_edge_cases(confidence):
    if math.isnan(confidence) or math.isinf(confidence):
        with pytest.raises(ValueError):
            AgentOutput(agent_id='a1', decision='yes', reasoning='r', confidence=confidence)
    else:
        output = AgentOutput(..., confidence=confidence)
        assert output.confidence == confidence

**Priority:** HIGH  
**Estimated Effort:** 16.0 hours  
**Module:** Testing Infrastructure  
**Issues Addressed:** 15

---

## Files to Create

- `tests/test_validation/test_edge_cases_comprehensive.py` - Comprehensive edge case test suite

---

## Files to Modify

_None_

---

## Acceptance Criteria


### Core Functionality

- [ ] Zero-length workflow/stage/agent hierarchies
- [ ] Extremely long tool names/parameters (>1000 chars, >10MB)
- [ ] Empty decision strings in consensus
- [ ] None/null values in required fields
- [ ] NaN/Infinity in confidence scores
- [ ] Unicode normalization attacks
- [ ] RTL text in configs
- [ ] Zero-width characters in agent names
- [ ] Surrogate pairs in file paths
- [ ] Very large configs (1000+ stages, 100MB)

### Testing

- [ ] 50+ edge case tests
- [ ] Parameterized tests for boundaries
- [ ] Property-based tests for fuzzing
- [ ] All edge cases handled gracefully


---

## Implementation Details

@pytest.mark.parametrize('confidence', [0.0, 1.0, float('nan'), float('inf'), -float('inf')])
def test_confidence_edge_cases(confidence):
    if math.isnan(confidence) or math.isinf(confidence):
        with pytest.raises(ValueError):
            AgentOutput(agent_id='a1', decision='yes', reasoning='r', confidence=confidence)
    else:
        output = AgentOutput(..., confidence=confidence)
        assert output.confidence == confidence

---

## Test Strategy

Use parameterized tests for boundary values. Add property-based tests with Hypothesis. Test all edge cases for graceful handling.

---

## Success Metrics

- [ ] 50+ edge cases tested
- [ ] All handled gracefully
- [ ] No crashes on edge cases
- [ ] Clear error messages

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** Hypothesis, pytest

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#52-edge-cases-gaps

---

## Notes

Essential for robustness. Many edge cases not currently tested.
