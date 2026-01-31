# Task: m3-15-e2e-integration-tests - E2E Integration Tests

**Priority:** CRITICAL (P0)  
**Effort:** 10 hours  
**Status:** pending  
**Owner:** unassigned

## Summary
Create comprehensive E2E integration tests for all M3 features with real Ollama LLM execution.

## Files to Create
- `tests/integration/test_m3_multi_agent.py` - Multi-agent E2E tests

## Test Coverage
- [ ] Test parallel execution (3 agents, Consensus strategy)
- [ ] Test debate strategy (2 rounds, convergence)
- [ ] Test merit-weighted conflict resolution
- [ ] Test adaptive mode switching
- [ ] Test quality gates (pass and fail scenarios)
- [ ] Test partial agent failures (2/3 succeed)
- [ ] Test min_successful_agents enforcement
- [ ] Test synthesis tracked in observability
- [ ] Test all strategy types (Consensus, Debate)
- [ ] Test all resolver types (MeritWeighted, HumanEscalation)

## Test Structure
```python
def test_parallel_consensus_3_agents():
    """Test 3 agents execute in parallel with consensus."""
    config = load_workflow("multi_agent_research")
    result = execute_workflow(config, input_data)
    
    assert "stage_outputs" in result
    assert len(result["stage_outputs"]["research"]["agent_outputs"]) == 3
    assert result["stage_outputs"]["research"]["synthesis"]["method"] == "consensus"

def test_debate_convergence():
    """Test debate converges after 2 rounds."""
    # ...
```

## Acceptance Criteria
- [ ] All tests pass with real Ollama
- [ ] Tests run in CI/CD
- [ ] Coverage >80% of M3 code
- [ ] Performance benchmarks captured
- [ ] Test execution time <5 minutes total

## Dependencies
- Blocked by: All M3 implementation tasks

## Notes
E2E tests are the final validation. Must pass before M3 can be considered complete.
