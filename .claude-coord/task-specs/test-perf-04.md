# Task: test-perf-04 - Add Memory Leak Detection Tests

**Priority:** NORMAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** Performance & Infrastructure (P2)

---

## Summary
Add tests to detect memory leaks in long-running agent/workflow execution.

---

## Files to Create
- `tests/test_memory_leaks.py` - Memory leak detection tests

---

## Acceptance Criteria

### Leak Detection
- [ ] Test agent execution doesn't leak memory
- [ ] Test workflow execution doesn't leak memory
- [ ] Test LLM provider connections don't leak
- [ ] Memory usage stable after initial ramp-up

---

## Implementation Details

```python
def test_agent_execution_no_memory_leak():
    """Test repeated agent execution doesn't leak memory."""
    import psutil
    import os
    import gc
    
    agent = StandardAgent(config)
    process = psutil.Process(os.getpid())
    
    # Warmup
    for _ in range(10):
        agent.execute({"input": "test"})
    
    gc.collect()
    baseline_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    # Execute 100 times
    for _ in range(100):
        agent.execute({"input": "test"})
    
    gc.collect()
    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    memory_growth = final_memory - baseline_memory
    
    # Should grow <10MB
    assert memory_growth < 10
```

---

## Success Metrics
- [ ] No significant memory leaks detected
- [ ] Memory growth <10MB per 100 executions

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None

---

## Design References
- QA Report: Memory Leak Detection (P2)
