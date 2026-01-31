# Task: test-property-based - Property-Based Testing with Hypothesis

**Priority:** MEDIUM
**Effort:** 3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add property-based testing using Hypothesis library to test invariants and discover edge cases automatically.

---

## Files to Create
- `tests/property/test_consensus_properties.py` - Consensus invariant tests
- `tests/property/test_validation_properties.py` - Validation property tests

---

## Files to Modify
- `pyproject.toml` - Add hypothesis dependency

---

## Acceptance Criteria

### Property Tests
- [ ] Test consensus confidence always in [0, 1]
- [ ] Test agent output validation invariants
- [ ] Test state transition invariants
- [ ] Test configuration validation properties
- [ ] Test conflict resolution properties

### Testing
- [ ] 10 property-based tests implemented
- [ ] Tests discover edge cases automatically
- [ ] Tests run 100+ examples per property
- [ ] Integration with pytest suite

---

## Implementation Details

```python
# tests/property/test_consensus_properties.py

from hypothesis import given, strategies as st
from src.strategies.consensus import ConsensusStrategy

@given(
    num_agents=st.integers(min_value=1, max_value=10),
    num_options=st.integers(min_value=1, max_value=5),
    confidences=st.lists(
        st.floats(min_value=0.0, max_value=1.0),
        min_size=1,
        max_size=10
    )
)
def test_consensus_confidence_bounded(num_agents, num_options, confidences):
    """Property: Consensus confidence always in [0, 1]."""
    strategy = ConsensusStrategy()
    
    outputs = [
        AgentOutput(
            f"agent{i}",
            f"Option{i % num_options}",
            "reason",
            confidences[i % len(confidences)],
            {}
        )
        for i in range(num_agents)
    ]
    
    result = strategy.synthesize(outputs, {})
    
    # Property: confidence must be in valid range
    assert 0.0 <= result.confidence <= 1.0


@given(
    outputs=st.lists(
        st.builds(
            AgentOutput,
            agent_id=st.text(min_size=1, max_size=20),
            decision=st.text(min_size=1, max_size=100),
            reasoning=st.text(max_size=500),
            confidence=st.floats(min_value=0.0, max_value=1.0),
            metadata=st.dictionaries(st.text(), st.text())
        ),
        min_size=1,
        max_size=10
    )
)
def test_consensus_never_raises_exception(outputs):
    """Property: Consensus should never crash on valid inputs."""
    strategy = ConsensusStrategy()
    
    try:
        result = strategy.synthesize(outputs, {})
        # If it returns, verify result is valid
        assert result.decision is not None
        assert 0.0 <= result.confidence <= 1.0
    except ValueError as e:
        # Only acceptable if validation fails
        assert "invalid" in str(e).lower() or "required" in str(e).lower()
```

---

## Success Metrics
- [ ] 10 property-based tests implemented
- [ ] Hypothesis finds edge cases not in manual tests
- [ ] Coverage increase from discovered edge cases
- [ ] Tests run in <60s

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** All test modules

---

## Design References
- TDD Architect Report: Property-Based Testing section

