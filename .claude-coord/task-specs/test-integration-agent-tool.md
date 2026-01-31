# Task: test-integration-agent-tool - Agent + Tool Integration Tests

**Priority:** HIGH
**Effort:** 2-3 days
**Status:** pending
**Owner:** unassigned

---

## Summary
Add comprehensive integration tests for agent + tool + safety interactions with real tool execution.

---

## Files to Create
- `tests/integration/test_agent_tool_integration.py` - Agent-tool integration tests

---

## Acceptance Criteria

### Core Functionality
- [ ] Test agent successfully calls tool with valid parameters
- [ ] Test agent handles tool execution errors gracefully
- [ ] Test tool timeout enforcement (<30s per tool)
- [ ] Test tool output size limits (100MB max)
- [ ] Test tool parameter validation before execution
- [ ] Test concurrent tool calls from multiple agents

### Integration Points
- [ ] Agent → Tool Registry → Tool Execution → Agent Response
- [ ] Tool errors propagate to agent response metadata
- [ ] Safety policies block dangerous tool calls
- [ ] Observability tracks tool execution metrics

### Testing
- [ ] 10 integration test scenarios covering tool lifecycle
- [ ] Tests use real tool implementations (not mocks)
- [ ] Tests verify end-to-end data flow
- [ ] Coverage >85% for agent-tool integration paths

---

## Implementation Details

```python
# tests/integration/test_agent_tool_integration.py

import pytest
from src.agents.factory import AgentFactory
from src.tools.registry import ToolRegistry
from src.tools.calculator import CalculatorTool
from src.tools.web_scraper import WebScraperTool

class TestAgentToolIntegration:
    """Integration tests for agent + tool execution."""
    
    @pytest.mark.asyncio
    async def test_agent_calculator_tool_success(self):
        """Test agent successfully executes calculator tool."""
        # Setup real agent and tool
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        
        agent = AgentFactory.create_agent(
            "standard",
            name="math_agent",
            model="ollama/llama3.2:3b",
            tools=[registry.get("calculator")]
        )
        
        # Execute with tool call
        response = await agent.aexecute(
            "What is 15 * 23?",
            context={}
        )
        
        # Verify tool was called and result correct
        assert response.tool_calls, "No tool calls made"
        assert "345" in response.output
        assert response.tokens > 0
    
    @pytest.mark.asyncio
    async def test_agent_tool_timeout_enforcement(self):
        """Test tool execution timeout."""
        # Create slow tool that sleeps 60s
        # Verify timeout at 30s
        pass
    
    @pytest.mark.asyncio
    async def test_agent_tool_error_handling(self):
        """Test agent handles tool errors gracefully."""
        # Call tool with invalid params
        # Verify error in response.error, not exception
        pass
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self):
        """Test multiple agents calling tools concurrently."""
        # 5 agents call different tools simultaneously
        # Verify no race conditions or resource conflicts
        pass
```

---

## Success Metrics
- [ ] 10 integration tests implemented and passing
- [ ] Coverage >85% for agent-tool paths
- [ ] All tests use real tools (not mocks)
- [ ] No resource leaks in concurrent execution

---

## Dependencies
- **Blocked by:** test-fix-failures-02
- **Blocks:** None
- **Integrates with:** src/agents/, src/tools/

---

## Design References
- QA Engineer Report: Test Case #28-30, #45

