# Task: test-security-concurrency - Race Condition & Concurrency Security Tests

**Priority:** CRITICAL
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add tests for race conditions in shared state, concurrent workflow execution, and multi-agent data integrity.

---

## Files to Create
- `tests/test_security/test_race_conditions.py` - Race condition tests
- `tests/test_async/test_concurrent_safety.py` - Concurrent execution safety tests

---

## Acceptance Criteria

### Security Controls
- [ ] Test race condition in shared workflow state (multiple agents modifying)
- [ ] Test agent deadlock detection (A waits for B, B waits for A)
- [ ] Test concurrent database writes (lost update prevention)
- [ ] Test async exception propagation and cleanup
- [ ] Test memory leak in async execution (1000+ workflows)

### Testing
- [ ] All 5 concurrency security tests implemented
- [ ] Tests demonstrate data corruption or verify protection
- [ ] Tests verify proper locking mechanisms
- [ ] Tests check resource cleanup

### Protection
- [ ] Workflow state updates use locks or transactions
- [ ] Deadlock timeout configured
- [ ] Database transactions prevent lost updates
- [ ] Async resources released on exception

---

## Implementation Details

```python
# tests/test_security/test_race_conditions.py

import pytest
import asyncio
from concurrent.futures import ThreadPoolExecutor

class TestRaceConditions:
    """Test race conditions in multi-agent execution."""
    
    @pytest.mark.asyncio
    async def test_shared_state_race_condition(self):
        """Test concurrent modifications to shared workflow state."""
        state = {"counter": 0}
        
        async def increment():
            for _ in range(100):
                current = state["counter"]
                await asyncio.sleep(0.001)  # Yield to other tasks
                state["counter"] = current + 1
        
        # Run 10 concurrent incrementers
        tasks = [increment() for _ in range(10)]
        await asyncio.gather(*tasks)
        
        # Without locking, counter will be < 1000 (race condition)
        # With locking, counter should be exactly 1000
        # This test should FAIL initially to demonstrate the race
        # Then implement locking and verify it passes
        assert state["counter"] == 1000, f"Race condition! Got {state['counter']}"
    
    @pytest.mark.asyncio
    async def test_agent_deadlock_detection(self):
        """Test deadlock detection in multi-agent workflows."""
        lock_a = asyncio.Lock()
        lock_b = asyncio.Lock()
        
        async def agent_1():
            async with lock_a:
                await asyncio.sleep(0.1)
                # Try to acquire lock_b (agent_2 holds it)
                async with lock_b:
                    pass
        
        async def agent_2():
            async with lock_b:
                await asyncio.sleep(0.1)
                # Try to acquire lock_a (agent_1 holds it)
                async with lock_a:
                    pass
        
        # Should timeout rather than deadlock forever
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(agent_1(), agent_2()),
                timeout=2.0
            )
    
    def test_concurrent_database_writes(self):
        """Test database lost update prevention."""
        from src.observability.database import SessionManager
        from src.observability.models import WorkflowExecution
        
        def update_workflow(workflow_id):
            with SessionManager.session() as session:
                workflow = session.query(WorkflowExecution).get(workflow_id)
                current = workflow.metadata.get("counter", 0)
                # Simulate work
                import time
                time.sleep(0.01)
                workflow.metadata["counter"] = current + 1
                session.commit()
        
        # Create test workflow
        workflow_id = "test-race"
        # Initialize with counter=0
        
        # Run 10 concurrent updates
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(update_workflow, workflow_id) for _ in range(10)]
            for future in futures:
                future.result()
        
        # Verify counter is 10 (no lost updates)
        with SessionManager.session() as session:
            workflow = session.query(WorkflowExecution).get(workflow_id)
            assert workflow.metadata["counter"] == 10
```

---

## Success Metrics
- [ ] All 5 concurrency tests implemented
- [ ] Race conditions detected or prevented
- [ ] Deadlock timeout configured
- [ ] No memory leaks in async execution

---

## Dependencies
- **Blocked by:** None (can run in parallel)
- **Blocks:** None
- **Integrates with:** src/compiler/execution_engine.py, src/observability/database.py

---

## Design References
- QA Engineer Report: Test Case #40-43 (Critical concurrency issues)

---

## Notes
- Some tests may need to demonstrate the problem before fixing
- Use asyncio.Lock or threading.Lock as appropriate
- Configure reasonable deadlock timeout (5-10s)
