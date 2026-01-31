# Task: test-med-tools-01 - Add Tools & Strategies Medium Priority Tests

**Priority:** MEDIUM
**Effort:** 5 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Add medium priority tests for tools and strategies including sequential testing, config validation, reducing mocks, multi-agent coordination, and property-based tests.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_tools/test_sequential_testing.py - Add early stopping validation`
- `tests/test_tools/test_config_validation.py - Add negative tests`
- `tests/test_tools/test_*.py - Reduce over-mocking, use real implementations`
- `tests/test_strategies/test_consensus.py - Add property tests`
- `tests/test_strategies/test_merit_weighted.py - Add property tests`
- `tests/test_strategies/test_debate.py - Add convergence tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Test sequential testing early stopping validation
- [ ] Add negative tests for config validation (test invalid configs)
- [ ] Reduce over-mocking (use real implementations where feasible)
- [ ] Add multi-agent coordination tests
- [ ] Add property tests for merit-weighted resolution
- [ ] Add property tests for debate convergence

### Testing
- [ ] Sequential testing: verify early stopping triggers correctly
- [ ] Config validation: test all invalid config scenarios
- [ ] Mocking: replace 50% of mocks with real implementations
- [ ] Multi-agent: test coordination between 2, 4, 8 agents
- [ ] Property tests: use Hypothesis for strategy invariants
- [ ] Debate: test convergence within N rounds

### Quality Improvements
- [ ] Early stopping prevents wasted computation
- [ ] Negative tests catch validation bugs
- [ ] Real implementations catch integration issues
- [ ] Property tests verify invariants hold

---

## Implementation Details

```python
def test_sequential_testing_early_stopping_validation():
    """Test early stopping triggers when statistical significance reached"""
    tester = SequentialTester(alpha=0.05, power=0.8)

    # Simulate A/B test with clear winner
    for i in range(1000):
        tester.add_sample("A", success=random.random() < 0.6)  # 60% success
        tester.add_sample("B", success=random.random() < 0.4)  # 40% success

        if tester.should_stop():
            assert i < 500  # Should stop before all 1000 samples
            assert tester.winner == "A"
            break
    else:
        pytest.fail("Early stopping didn't trigger")

@pytest.mark.parametrize("invalid_config,expected_error", [
    ({"timeout": -1}, "Timeout must be positive"),
    ({"max_retries": "five"}, "max_retries must be int"),
    ({}, "Missing required field: timeout"),
])
def test_config_validation_negative_cases(invalid_config, expected_error):
    """Test config validation rejects invalid configs"""
    with pytest.raises(ConfigValidationError, match=expected_error):
        validate_config(invalid_config)

# Property-based test with Hypothesis
from hypothesis import given, strategies as st

@given(
    votes=st.lists(st.tuples(st.text(), st.floats(0, 1)), min_size=1, max_size=10)
)
def test_merit_weighted_resolution_properties(votes):
    """Property: winner has highest merit-weighted score"""
    result = merit_weighted_resolution(votes)

    # Property: winner's score >= all other scores
    for candidate, merit in votes:
        if candidate != result.winner:
            assert result.scores[result.winner] >= result.scores[candidate]
```

---

## Test Strategy

Add property-based tests with Hypothesis. Test negative cases. Replace mocks with real implementations. Test coordination.

---

## Success Metrics

- [ ] Early stopping validation tested
- [ ] All invalid config scenarios tested
- [ ] Mocking reduced by 50%
- [ ] Multi-agent coordination tested
- [ ] Property tests added for all strategies
- [ ] Tests run in <8 seconds total

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** SequentialTester, ConfigValidator, StrategyEngine

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 3, Medium Issues (Tools & Strategies)

---

## Notes

Use Hypothesis for property tests. Use real implementations to catch integration bugs. Test with varied agent counts.
