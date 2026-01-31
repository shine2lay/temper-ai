# Task: test-collaboration-strategies - Strategy Edge Case Tests

**Priority:** MEDIUM
**Effort:** 2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add edge case tests for collaboration strategies: ties, all-zero merit, empty agents, convergence scenarios.

---

## Files to Create
- `tests/test_strategies/test_strategy_edge_cases.py` - Strategy edge cases

---

## Acceptance Criteria

### Consensus Edge Cases
- [ ] Test unanimous agreement (all same decision)
- [ ] Test perfect tie (50-50 split)
- [ ] Test 3-way split (no majority)
- [ ] Test single agent consensus
- [ ] Test empty agents list

### Merit-Weighted Edge Cases
- [ ] Test all agents have zero merit
- [ ] Test missing merit scores (fallback to 0.5)
- [ ] Test negative merit scores
- [ ] Test extreme merit differences (0.01 vs 0.99)

### Debate Edge Cases
- [ ] Test non-converging debate (max rounds reached)
- [ ] Test convergence threshold boundaries
- [ ] Test oscillating opinions
- [ ] Test all agents start with same opinion

### Testing
- [ ] 20 edge case tests for strategies
- [ ] Tests verify graceful handling
- [ ] Tests document expected behavior

---

## Implementation Details

```python
# tests/test_strategies/test_strategy_edge_cases.py

class TestConsensusEdgeCases:
    """Test consensus strategy edge cases."""
    
    def test_unanimous_agreement(self):
        """Test all agents agree."""
        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {}),
            AgentOutput("a2", "A", "r2", 0.85, {}),
            AgentOutput("a3", "A", "r3", 0.8, {}),
        ]
        
        strategy = ConsensusStrategy()
        result = strategy.synthesize(outputs, {})
        
        assert result.decision == "A"
        assert result.confidence > 0.8
        assert len(result.conflicts) == 0
    
    def test_perfect_tie(self):
        """Test 50-50 tie."""
        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {}),
            AgentOutput("a2", "B", "r2", 0.7, {}),
        ]
        
        strategy = ConsensusStrategy(tie_breaker="confidence")
        result = strategy.synthesize(outputs, {})
        
        # Should pick A (higher confidence)
        assert result.decision == "A"

class TestMeritWeightedEdgeCases:
    """Test merit-weighted resolver edge cases."""
    
    def test_all_zero_merit(self):
        """Test all agents have zero merit."""
        outputs = [
            AgentOutput("a1", "A", "r1", 0.9, {}),
            AgentOutput("a2", "B", "r2", 0.8, {}),
        ]
        
        context = {
            "agent_merits": {"a1": 0.0, "a2": 0.0}
        }
        
        resolver = MeritWeightedResolver()
        result = resolver.resolve(outputs, context)
        
        # Should fall back to equal weighting
        assert result is not None
```

---

## Success Metrics
- [ ] 20 edge case tests implemented
- [ ] All strategy edge cases covered
- [ ] Behavior documented for ambiguous cases

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Engineer Report: Test Case #34-39

