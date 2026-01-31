# Task: test-agent-02 - Add Context Propagation Tests

**Priority:** HIGH
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** Agent Quality (P1)

---

## Summary
Test that ExecutionContext properly propagates through nested agent calls and tool executions.

---

## Files to Modify
- `tests/test_agents/test_base_agent.py` - Add context propagation tests

---

## Acceptance Criteria

### Context Flow
- [ ] Context passed from parent to child agents
- [ ] Context preserved across tool calls
- [ ] Context includes workflow_id, stage_id, parent_id

### Testing
- [ ] Test nested agent execution
- [ ] Test context in tool calls
- [ ] Test context in LLM calls

---

## Implementation Details

```python
def test_execution_context_propagation():
    """Test context flows through nested calls."""
    agent = MockAgent(minimal_agent_config)
    parent_context = ExecutionContext(
        workflow_id="wf-1",
        stage_id="stage-1"
    )
    
    response = agent.execute({"nested": True}, context=parent_context)
    
    # Verify context was used
    assert response is not None
```

---

## Success Metrics
- [ ] Context propagates correctly
- [ ] Context accessible in all execution points

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Report: test_base_agent.py - Context Propagation (P1)
