# Task: test-high-strategies-01 - Improve Strategy Consensus Tests with Realistic Data

**Priority:** HIGH
**Effort:** 2 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Replace hardcoded data with property-based testing using Hypothesis to generate realistic varied test data.

---

## Files to Create

- None

---

## Files to Modify

- `tests/test_strategies/test_consensus.py - Add property-based tests`

---

## Acceptance Criteria


### Core Functionality
- [ ] Replace hardcoded identical confidence scores with varied realistic data
- [ ] Add high disagreement escalation tests
- [ ] Add confidence edge cases (0.0, 1.0, NaN)
- [ ] Use property-based testing with Hypothesis

### Testing
- [ ] Property tests: generate random agent votes and verify invariants
- [ ] Disagreement: test with <50% consensus
- [ ] Edge cases: test confidence boundaries
- [ ] Realistic data: use normal distribution for confidence scores

---

## Implementation Details

```python
from hypothesis import given, strategies as st

# Before: Hardcoded unrealistic data
def test_consensus_hardcoded():
    votes = [
        ("A", 0.8),
        ("B", 0.8),
        ("C", 0.8),  # Unrealistic - all same confidence
    ]
    result = consensus_strategy(votes)
    assert result is not None

# After: Property-based with realistic data
@given(
    votes=st.lists(
        st.tuples(
            st.sampled_from(["A", "B", "C"]),
            st.floats(0.0, 1.0)  # Realistic confidence range
        ),
        min_size=3,
        max_size=10
    )
)
def test_consensus_properties(votes):
    """Property: consensus winner has plurality of votes"""
    result = consensus_strategy(votes, threshold=0.5)

    if result.consensus_reached:
        # Property: winner has >=50% of votes
        winner_votes = sum(1 for candidate, _ in votes if candidate == result.winner)
        assert winner_votes / len(votes) >= 0.5
    else:
        # Property: no candidate has >=50%
        for candidate in set(c for c, _ in votes):
            candidate_votes = sum(1 for c, _ in votes if c == candidate)
            assert candidate_votes / len(votes) < 0.5

def test_consensus_high_disagreement_escalation():
    """Test high disagreement triggers escalation"""
    # 5 agents, 5 different votes (100% disagreement)
    votes = [(f"option_{i}", 0.5) for i in range(5)]

    result = consensus_strategy(votes, threshold=0.7)

    assert not result.consensus_reached
    assert result.escalation_required
    assert result.disagreement_level > 0.9

def test_consensus_confidence_edge_cases():
    """Test edge case confidence values"""
    edge_cases = [
        [("A", 0.0), ("B", 1.0)],  # Min/max confidence
        [("A", float('nan'))],      # NaN confidence
        [("A", float('inf'))],      # Infinite confidence
    ]

    for votes in edge_cases:
        # Should handle gracefully, not crash
        result = consensus_strategy(votes)
        assert result is not None
```

---

## Test Strategy

Use Hypothesis for property testing. Generate realistic varied data. Test edge cases.

---

## Success Metrics

- [ ] Property-based tests added
- [ ] Realistic varied test data
- [ ] Edge cases tested

---

## Dependencies

- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** ConsensusStrategy

---

## Design References

- .claude-coord/reports/test-review-20260128-200844.md - Section 2, High Issue #13

---

## Notes

Use Hypothesis for property testing. Test with varied confidence scores.
