# Task: test-boundary-values - Boundary Value & Edge Case Tests

**Priority:** HIGH
**Effort:** 2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add parameterized boundary value tests for configuration limits, token counts, confidence scores, and agent counts.

---

## Files to Create
- `tests/test_validation/test_boundary_values.py` - Boundary value tests
- `tests/fixtures/boundary_values.py` - Boundary value constants

---

## Acceptance Criteria

### Boundary Testing
- [ ] Test agent count boundaries (0, 1, 10, 11)
- [ ] Test confidence score boundaries (-0.1, 0.0, 0.5, 1.0, 1.1)
- [ ] Test token count boundaries (0, 1, 2048, 2049, 1000000)
- [ ] Test debate round boundaries (0, 1, 10, 11)
- [ ] Test temperature boundaries (-0.1, 0.0, 1.0, 2.0)
- [ ] Test max_tokens boundaries
- [ ] Test file size boundaries (0, 1MB, 10MB, 10MB+1)

### Testing
- [ ] 30+ parameterized boundary tests
- [ ] Tests verify acceptance at boundaries
- [ ] Tests verify rejection beyond boundaries
- [ ] Clear error messages for violations

---

## Implementation Details

```python
# tests/fixtures/boundary_values.py

BOUNDARY_VALUES = {
    "agent_count": {
        "below_minimum": 0,
        "minimum": 1,
        "typical": 3,
        "maximum": 10,
        "above_maximum": 11,
    },
    "confidence_score": {
        "below_minimum": -0.1,
        "minimum": 0.0,
        "low": 0.3,
        "medium": 0.6,
        "high": 0.9,
        "maximum": 1.0,
        "above_maximum": 1.1,
    },
    "token_count": {
        "below_minimum": 0,
        "minimum": 1,
        "typical": 500,
        "near_limit": 2000,
        "at_limit": 2048,
        "above_limit": 2049,
    },
}
```

```python
# tests/test_validation/test_boundary_values.py

import pytest
from tests.fixtures.boundary_values import BOUNDARY_VALUES

class TestBoundaryValues:
    """Test boundary value validation."""
    
    @pytest.mark.parametrize("agent_count,should_accept", [
        (BOUNDARY_VALUES["agent_count"]["below_minimum"], False),
        (BOUNDARY_VALUES["agent_count"]["minimum"], True),
        (BOUNDARY_VALUES["agent_count"]["typical"], True),
        (BOUNDARY_VALUES["agent_count"]["maximum"], True),
        (BOUNDARY_VALUES["agent_count"]["above_maximum"], False),
    ])
    def test_agent_count_validation(self, agent_count, should_accept):
        """Test agent count boundary validation."""
        if should_accept:
            # Should succeed
            strategy = ConsensusStrategy()
            outputs = create_agent_outputs(count=agent_count)
            result = strategy.synthesize(outputs, {})
            assert result is not None
        else:
            # Should reject
            with pytest.raises(ValueError):
                outputs = create_agent_outputs(count=agent_count)
    
    @pytest.mark.parametrize("confidence,should_accept", [
        (-0.1, False),
        (0.0, True),
        (0.5, True),
        (1.0, True),
        (1.1, False),
    ])
    def test_confidence_score_validation(self, confidence, should_accept):
        """Test confidence score boundaries."""
        from src.strategies.conflict_resolution import ResolutionResult
        
        if should_accept:
            result = ResolutionResult(
                decision="A",
                confidence=confidence,
                method="test",
                votes={},
                conflicts=[],
                reasoning="test"
            )
            assert result.confidence == confidence
        else:
            with pytest.raises(ValueError):
                ResolutionResult(
                    decision="A",
                    confidence=confidence,
                    method="test",
                    votes={},
                    conflicts=[],
                    reasoning="test"
                )
```

---

## Success Metrics
- [ ] 30+ boundary tests implemented
- [ ] All critical boundaries tested
- [ ] Parameterized test suite reduces duplication
- [ ] Coverage >90% for validation code

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- TDD Architect Report: Boundary Value Testing section
- QA Engineer Report: Test Case #19-22, #33, #48-52

