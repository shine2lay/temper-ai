# Task: test-state-transitions - State Machine Transition Tests

**Priority:** HIGH
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add comprehensive state transition tests for workflow lifecycle, safety modes, and agent execution state machines.

---

## Files to Create
- `tests/test_compiler/test_workflow_state_transitions.py` - Workflow state tests
- `tests/test_safety/test_safety_mode_transitions.py` - Safety mode tests
- `tests/test_agents/test_agent_state_machine.py` - Agent state tests

---

## Acceptance Criteria

### Workflow States
- [ ] Test pending → running transition
- [ ] Test running → completed on success
- [ ] Test running → failed on stage failure
- [ ] Test running → timeout on deadline
- [ ] Test cancellation mid-execution
- [ ] Test pause/resume (if implemented)

### Safety Modes
- [ ] Test execute → dry_run on high risk detection
- [ ] Test dry_run → require_approval on safety violation
- [ ] Test require_approval → execute after approval
- [ ] Test mode transitions preserve context

### Agent States
- [ ] Test init → executing → done path
- [ ] Test executing → tool_call → executing loop
- [ ] Test error → retry → success path
- [ ] Test error → failed path

### Testing
- [ ] 18 state transition tests total
- [ ] All valid transitions tested
- [ ] Invalid transitions rejected
- [ ] State invariants maintained

---

## Implementation Details

```python
# tests/test_compiler/test_workflow_state_transitions.py

import pytest
from src.compiler.execution_engine import WorkflowState

class TestWorkflowStateTransitions:
    """Test workflow lifecycle state transitions."""
    
    @pytest.mark.asyncio
    async def test_pending_to_running_transition(self):
        """Test workflow starts execution."""
        workflow = create_test_workflow()
        assert workflow.state == WorkflowState.PENDING
        
        await workflow.start()
        assert workflow.state == WorkflowState.RUNNING
    
    @pytest.mark.asyncio
    async def test_running_to_completed_on_success(self):
        """Test successful completion."""
        workflow = create_test_workflow()
        await workflow.start()
        
        # All stages complete successfully
        result = await workflow.execute()
        
        assert workflow.state == WorkflowState.COMPLETED
        assert result.success is True
    
    @pytest.mark.asyncio
    async def test_running_to_timeout_on_deadline(self):
        """Test timeout enforcement."""
        workflow = create_slow_workflow(expected_time=600)
        workflow.timeout = 10  # 10 second timeout
        
        await workflow.start()
        
        with pytest.raises(TimeoutError):
            await workflow.execute()
        
        assert workflow.state == WorkflowState.TIMEOUT
    
    @pytest.mark.asyncio
    async def test_cancellation_mid_execution(self):
        """Test workflow cancellation."""
        workflow = create_long_workflow()
        
        execution_task = asyncio.create_task(workflow.execute())
        await asyncio.sleep(1)
        
        await workflow.cancel()
        
        with pytest.raises(asyncio.CancelledError):
            await execution_task
        
        assert workflow.state == WorkflowState.CANCELLED
```

```python
# tests/test_safety/test_safety_mode_transitions.py

class TestSafetyModeTransitions:
    """Test safety mode state transitions."""
    
    def test_execute_to_dry_run_on_risk(self):
        """Test escalation to dry-run."""
        # Start in EXECUTE mode
        # Detect high-risk operation
        # Verify transition to DRY_RUN
        pass
    
    def test_dry_run_to_require_approval(self):
        """Test escalation to require approval."""
        # DRY_RUN mode detects violation
        # Escalate to REQUIRE_APPROVAL
        pass
```

---

## Success Metrics
- [ ] 18 state transition tests implemented
- [ ] All state machines fully covered
- [ ] Invalid transitions tested
- [ ] Coverage >90% for state management code

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- TDD Architect Report: State Transition Testing section
- QA Engineer Report: Test Case #23-24, #33-37

