# Task: test-error-handling-timeouts - Timeout Scenario Tests

**Priority:** HIGH
**Effort:** 2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add timeout tests for LLM calls, tool execution, workflow execution, and agent execution.

---

## Files to Create
- `tests/test_error_handling/test_timeout_scenarios.py` - Timeout tests

---

## Acceptance Criteria

### Timeout Coverage
- [ ] Test LLM response timeout (>30s)
- [ ] Test tool execution timeout (>30s)
- [ ] Test workflow execution timeout (>5min)
- [ ] Test agent execution timeout enforcement
- [ ] Test timeout propagation across stages

### Error Handling
- [ ] Timeout errors include clear context (what timed out)
- [ ] Resources cleaned up on timeout (connections, files)
- [ ] Partial results captured before timeout
- [ ] Retry logic respects timeout budgets

### Testing
- [ ] 8 timeout scenario tests implemented
- [ ] Tests verify timeouts enforced
- [ ] Tests check resource cleanup

---

## Implementation Details

```python
# tests/test_error_handling/test_timeout_scenarios.py

import pytest
import asyncio

class TestTimeoutScenarios:
    """Test timeout enforcement across components."""
    
    @pytest.mark.asyncio
    async def test_llm_response_timeout(self):
        """Test LLM call times out after configured duration."""
        from src.agents.llm_providers import OllamaProvider
        
        # Mock slow LLM response (60s)
        async def slow_generate(*args, **kwargs):
            await asyncio.sleep(60)
            return "response"
        
        provider = OllamaProvider()
        provider._generate = slow_generate
        
        # Verify timeout at 30s
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                provider.generate("prompt"),
                timeout=30.0
            )
    
    @pytest.mark.asyncio
    async def test_tool_execution_timeout(self):
        """Test tool execution timeout."""
        from src.tools.base import BaseTool
        
        class SlowTool(BaseTool):
            name = "slow_tool"
            
            async def aexecute(self, **params):
                await asyncio.sleep(60)
                return {"result": "done"}
        
        tool = SlowTool()
        
        # Should timeout at 30s
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                tool.aexecute(),
                timeout=30.0
            )
    
    @pytest.mark.asyncio
    async def test_workflow_timeout(self):
        """Test full workflow timeout."""
        # Create workflow with 10min estimated time
        # Set timeout to 5min
        # Verify workflow killed at 5min with partial results
        pass
```

---

## Success Metrics
- [ ] 8 timeout tests implemented and passing
- [ ] All components respect timeout configuration
- [ ] Resources cleaned up on timeout
- [ ] Partial results captured when possible

---

## Dependencies
- **Blocked by:** None (can run in parallel)
- **Blocks:** None
- **Integrates with:** All components

---

## Design References
- QA Engineer Report: Test Case #29, #53, #82, #86

