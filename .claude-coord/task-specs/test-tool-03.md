# Task: test-tool-03 - Add Resource Exhaustion Prevention Tests

**Priority:** HIGH
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** Tool Safety (P1)

---

## Summary
Add tests to prevent resource exhaustion from tools consuming excessive CPU, memory, or file handles.

---

## Files to Modify
- `tests/test_tools/test_executor.py` - Add resource limit tests
- `src/tools/executor.py` - Add resource monitoring

---

## Acceptance Criteria

### Concurrent Execution Limits
- [ ] Limit max concurrent tool executions (e.g., max 10 concurrent)
- [ ] Queue additional requests when limit reached
- [ ] FIFO or priority-based queue management

### Memory Limits (optional)
- [ ] Monitor memory usage during tool execution
- [ ] Warn or terminate if memory exceeds threshold
- [ ] Track memory per tool call

### Rate Limiting
- [ ] Limit tool calls per time window (e.g., 100/minute)
- [ ] Per-tool rate limits configurable
- [ ] Graceful degradation when limit hit

---

## Implementation Details

```python
# tests/test_tools/test_executor.py

def test_tool_executor_limits_concurrent_executions():
    """Test executor limits concurrent tool executions."""
    import time
    
    class SlowTool(BaseTool):
        name = "slow"
        
        def execute(self, delay: float = 1.0) -> str:
            time.sleep(delay)
            return "done"
    
    registry = ToolRegistry()
    registry.register(SlowTool())
    
    executor = ToolExecutor(registry, max_concurrent=5)
    
    # Try to execute 20 slow tools concurrently
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = [
            pool.submit(executor.execute, "slow", {"delay": 0.5})
            for _ in range(20)
        ]
        
        # Check concurrent execution count
        time.sleep(0.1)  # Let some start
        concurrent_count = executor.get_concurrent_execution_count()
        
        # Should not exceed max_concurrent
        assert concurrent_count <= 5
        
        # Wait for all to complete
        results = [f.result() for f in futures]
    
    assert len(results) == 20
    assert all(r == "done" for r in results)

def test_tool_executor_rate_limiting():
    """Test tool executor enforces rate limits."""
    class FastTool(BaseTool):
        name = "fast"
        
        def execute(self) -> str:
            return "done"
    
    registry = ToolRegistry()
    registry.register(FastTool())
    
    # 10 calls per second max
    executor = ToolExecutor(registry, rate_limit=10, rate_window=1.0)
    
    # Execute 20 calls rapidly
    import time
    start = time.time()
    
    for i in range(20):
        try:
            executor.execute("fast", {})
        except RateLimitError:
            # Should hit rate limit
            pass
    
    elapsed = time.time() - start
    
    # Should take at least 1 second due to rate limiting
    assert elapsed >= 1.0
```

---

## Test Strategy
- Test with genuinely resource-heavy operations
- Test concurrent execution limits with threading
- Test rate limiting accuracy
- Monitor system resources during test

---

## Success Metrics
- [ ] Concurrent execution limited correctly
- [ ] Rate limiting prevents resource exhaustion
- [ ] No deadlocks or race conditions
- [ ] Coverage of resource limits >85%

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** src/tools/executor.py

---

## Design References
- Rate limiting algorithms: https://en.wikipedia.org/wiki/Rate_limiting
- QA Report: test_executor.py - Resource Exhaustion (P1)
