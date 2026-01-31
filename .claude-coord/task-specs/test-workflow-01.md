# Task: test-workflow-01 - Add Workflow Cancellation Tests

**Priority:** CRITICAL
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned
**Category:** Workflow Execution (P0)

---

## Summary
Add tests for workflow cancellation capability to stop long-running workflows gracefully.

---

## Files to Modify
- `tests/test_compiler/test_execution_engine.py` - Add cancellation tests
- `src/compiler/execution_engine.py` - Implement cancellation

---

## Acceptance Criteria

### Cancellation API
- [ ] Support cancel() method on CompiledWorkflow
- [ ] Support cancellation via signal/flag
- [ ] Return cancellation status

### Graceful Shutdown
- [ ] Running stage completes before cancellation
- [ ] Resources cleaned up properly
- [ ] Partial results saved if possible

### Testing
- [ ] Test cancellation during workflow execution
- [ ] Test cancellation between stages
- [ ] Test cancellation during tool call
- [ ] Test idempotent cancellation (cancel twice OK)

---

## Implementation Details

```python
def test_workflow_execution_can_be_cancelled():
    """Test that long-running workflows can be cancelled."""
    engine = LangGraphEngine()
    compiled = engine.compile(long_running_workflow_config)
    
    # Start execution in background
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(compiled.invoke, {"input": "test"})
    
    time.sleep(0.5)  # Let it start
    
    # Cancel execution
    compiled.cancel()
    
    # Should raise CancellationError
    with pytest.raises(WorkflowCancelledError):
        future.result(timeout=5)
    
    # Resources should be cleaned up
    assert compiled.is_cancelled is True
```

---

## Success Metrics
- [ ] Workflows can be cancelled
- [ ] Graceful cleanup on cancellation
- [ ] No resource leaks

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Report: test_execution_engine.py - Cancellation (P0)
