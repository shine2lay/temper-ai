# Task: test-tool-01 - Add Tool Execution Timeout Tests

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned
**Category:** Tool Safety (P0)

---

## Summary
Add timeout handling for tool execution to prevent agents from hanging on slow or stuck tools.

---

## Files to Modify
- `tests/test_agents/test_standard_agent.py` - Add timeout tests
- `src/tools/executor.py` - Add timeout enforcement
- `src/agents/standard_agent.py` - Configure tool timeout

---

## Acceptance Criteria

### Timeout Enforcement
- [ ] Tool execution limited to configurable timeout (default 30s)
- [ ] Timeout can be configured per-agent
- [ ] Timeout can be overridden per-tool call
- [ ] Hung tools are forcefully terminated after timeout

### Error Handling
- [ ] TimeoutError raised when tool exceeds timeout
- [ ] Agent handles timeout gracefully (doesn't crash)
- [ ] Error message indicates which tool timed out
- [ ] Partial results (if any) are preserved

### Resource Cleanup
- [ ] Tool process/thread cleaned up after timeout
- [ ] No resource leaks from timed-out tools
- [ ] File handles closed, network connections terminated

---

## Implementation Details

```python
# src/tools/executor.py
import signal
from contextlib import contextmanager
import threading

class ToolExecutor:
    def __init__(self, registry, default_timeout: int = 30):
        self.registry = registry
        self.default_timeout = default_timeout
    
    def execute(self, tool_name: str, params: dict, timeout: int = None) -> Any:
        """Execute tool with timeout."""
        timeout = timeout or self.default_timeout
        tool = self.registry.get(tool_name)
        
        if timeout <= 0:
            # No timeout
            return tool.execute(**params)
        
        # Use threading with timeout
        result = {"value": None, "error": None}
        
        def run_tool():
            try:
                result["value"] = tool.execute(**params)
            except Exception as e:
                result["error"] = e
        
        thread = threading.Thread(target=run_tool, daemon=True)
        thread.start()
        thread.join(timeout)
        
        if thread.is_alive():
            # Timeout occurred
            raise ToolExecutionError(
                f"Tool '{tool_name}' exceeded timeout of {timeout}s"
            )
        
        if result["error"]:
            raise result["error"]
        
        return result["value"]

class ToolExecutionError(Exception):
    """Raised when tool execution fails or times out."""
    pass
```

```python
# tests/test_agents/test_standard_agent.py

def test_standard_agent_tool_execution_timeout():
    """Test agent handles slow tool execution gracefully."""
    # Create slow tool
    class SlowTool(BaseTool):
        name = "slow_tool"
        description = "A very slow tool"
        
        def execute(self, delay: int = 60) -> str:
            import time
            time.sleep(delay)
            return "Done"
    
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.get.return_value = SlowTool()
        
        agent = StandardAgent(minimal_agent_config)
        agent.tool_timeout = 2  # 2 second timeout
        
        # Mock LLM to call slow tool
        with patch.object(agent.llm, 'complete', return_value='{"tool": "slow_tool", "parameters": {"delay": 60}}'):
            response = agent.execute({"input": "use slow tool"})
        
        # Should complete with timeout error
        assert response.error is not None
        assert "timeout" in response.error.lower()
        assert "slow_tool" in response.error

def test_tool_executor_enforces_timeout():
    """Test tool executor enforces timeout."""
    import time
    
    class SlowTool(BaseTool):
        name = "slow"
        
        def execute(self) -> str:
            time.sleep(10)
            return "done"
    
    registry = ToolRegistry()
    registry.register(SlowTool())
    
    executor = ToolExecutor(registry, default_timeout=1)
    
    start = time.time()
    with pytest.raises(ToolExecutionError, match="timeout"):
        executor.execute("slow", {})
    elapsed = time.time() - start
    
    # Should timeout in ~1 second, not wait full 10
    assert elapsed < 2

def test_tool_executor_no_resource_leak_on_timeout():
    """Test tool execution cleanup after timeout."""
    import psutil
    import os
    
    class ResourceHeavyTool(BaseTool):
        name = "heavy"
        
        def execute(self) -> str:
            # Open many file handles
            files = [open('/dev/null', 'r') for _ in range(100)]
            time.sleep(60)
            return "done"
    
    registry = ToolRegistry()
    registry.register(ResourceHeavyTool())
    executor = ToolExecutor(registry, default_timeout=1)
    
    process = psutil.Process(os.getpid())
    before_handles = len(process.open_files())
    
    try:
        executor.execute("heavy", {})
    except ToolExecutionError:
        pass
    
    time.sleep(0.5)  # Let cleanup happen
    after_handles = len(process.open_files())
    
    # Should not leak file handles
    assert after_handles - before_handles < 10
```

---

## Test Strategy
- Test with genuinely slow operations (sleep, network)
- Test resource cleanup (files, threads, processes)
- Test timeout accuracy (within 10% of configured value)
- Test nested tool calls with cumulative timeout

---

## Success Metrics
- [ ] Timeouts enforced within ±10% accuracy
- [ ] No resource leaks from timed-out tools
- [ ] Agent continues working after tool timeout
- [ ] Coverage of timeout handling >90%

---

## Dependencies
- **Blocked by:** None
- **Blocks:** None
- **Integrates with:** src/tools/executor.py, src/agents/standard_agent.py

---

## Design References
- Python threading timeout: https://docs.python.org/3/library/threading.html#threading.Thread.join
- Signal-based timeout (Unix): https://docs.python.org/3/library/signal.html
- QA Report: test_standard_agent.py - Tool Timeout (P0)
