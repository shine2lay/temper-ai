# Task: test-med-reduce-over-mocking-05 - Replace over-mocked tests with realistic test data

**Priority:** NORMAL
**Effort:** 12 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

# realistic_data.py
REALISTIC_AGENT = AgentConfig(
    name='research_agent',
    role='researcher',
    model='gpt-4',
    system_prompt='You are...',
    tools=['web_search', 'calculator'],
    max_tokens=2000,
    temperature=0.7
)

REALISTIC_WORKFLOW = WorkflowConfig(
    name='research_workflow',
    stages=[...],  # 3-5 stages
    metadata={...}  # 10+ fields
)

**Module:** Testing Infrastructure
**Issues Addressed:** 12

---

## Files to Create

- `tests/fixtures/realistic_data.py` - Realistic test data fixtures

---

## Files to Modify

- `tests/test_benchmarks/test_performance.py` - Replace empty mocks with real configs
- `tests/test_compiler/test_stage_compiler.py` - Use realistic agent lists
- `tests/test_strategies/test_consensus.py` - Use realistic agent outputs

---

## Acceptance Criteria

### Core Functionality

- [ ] Create realistic_data.py with production-like fixtures
- [ ] Replace empty agent lists with 3-5 realistic agents
- [ ] Replace minimal configs with realistic configs (10+ fields)
- [ ] Add complex nested metadata scenarios
- [ ] Use real agent outputs with realistic reasoning
- [ ] Reduce mocking by 50% in affected tests

### Testing

- [ ] All tests still pass with realistic data
- [ ] Tests catch more edge cases
- [ ] No performance degradation from realistic data

---

## Implementation Details

# realistic_data.py
REALISTIC_AGENT = AgentConfig(
    name='research_agent',
    role='researcher',
    model='gpt-4',
    system_prompt='You are...',
    tools=['web_search', 'calculator'],
    max_tokens=2000,
    temperature=0.7
)

REALISTIC_WORKFLOW = WorkflowConfig(
    name='research_workflow',
    stages=[...],  # 3-5 stages
    metadata={...}  # 10+ fields
)

---

## Test Strategy

Create realistic fixtures. Gradually replace mocks in tests. Verify tests still pass and catch more issues.

---

## Success Metrics

- [ ] Realistic data fixtures created
- [ ] 50% reduction in over-mocking
- [ ] Tests catch more edge cases
- [ ] All tests pass

---

## Dependencies

**Blocked by:** _None_

**Blocks:** _None_

**Integrates with:** _None_

---

## Design References

- .claude-coord/reports/test-review-20260130-223857.md#over-mocking-issues

---

## Notes

More realistic tests catch more real-world bugs.
