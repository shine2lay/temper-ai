# Task: test-error-handling-propagation - Error Propagation Tests

**Priority:** HIGH
**Effort:** 2 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add tests for error propagation across agent → stage → workflow chain with proper context preservation.

---

## Files to Create
- `tests/test_error_handling/test_error_propagation.py` - Error propagation tests

---

## Acceptance Criteria

### Error Propagation
- [ ] Test agent error → stage error → workflow error chain
- [ ] Test error context preserved at each level
- [ ] Test partial failure handling (3 of 5 agents succeed)
- [ ] Test error cascading stops when appropriate
- [ ] Test error metadata sanitization (no secrets in errors)

### Testing
- [ ] 10 error propagation tests implemented
- [ ] Tests verify error chain integrity
- [ ] Tests check error messages are helpful
- [ ] Tests verify secrets not leaked in errors

---

## Implementation Details

```python
# tests/test_error_handling/test_error_propagation.py

import pytest

class TestErrorPropagation:
    """Test error propagation across components."""
    
    @pytest.mark.asyncio
    async def test_agent_to_stage_error_propagation(self):
        """Test agent error propagates to stage with context."""
        # Agent raises ToolNotFoundError
        # Stage catches and wraps with stage context
        # Workflow sees StageExecutionError with full chain
        pass
    
    @pytest.mark.asyncio
    async def test_partial_failure_handling(self):
        """Test workflow handles partial agent failures."""
        # 5 agents in parallel stage
        # 2 fail, 3 succeed
        # Verify workflow captures both successes and failures
        pass
    
    def test_error_message_sanitization(self):
        """Test secrets not leaked in error messages."""
        # Error includes API key in original message
        # Verify sanitized before logging/returning
        pass
```

---

## Success Metrics
- [ ] 10 error propagation tests implemented
- [ ] Error context preserved across layers
- [ ] Secrets sanitized from error messages
- [ ] Partial failures handled correctly

---

## Dependencies
- **Blocked by:** test-fix-failures-03
- **Blocks:** None

