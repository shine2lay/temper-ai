# Task: m2-04-agent-runtime - Implement agent executor with LLM and tool integration

**Priority:** CRITICAL
**Effort:** 3-4 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Implement Agent class that orchestrates LLM calls, tool execution, and response generation. This is the core execution engine that takes an agent config and input, calls the LLM, parses tool calls, executes tools, and returns the final response.

---

## Files to Create

- `src/agents/agent.py` - Agent class
- `src/agents/agent_executor.py` - AgentExecutor orchestration
- `tests/test_agents/test_agent.py` - Agent tests

---

## Acceptance Criteria

### Agent Core
- [ ] Initialize agent from AgentConfig
- [ ] Load LLM provider based on config
- [ ] Load tools from registry
- [ ] Render prompt template with input
- [ ] Execute LLM call
- [ ] Parse tool calls from LLM response
- [ ] Execute tools sequentially
- [ ] Generate final response

### Tool Calling Loop
- [ ] LLM generates tool call → parse → execute → inject result → LLM again
- [ ] Support multi-turn tool calling
- [ ] Max tool call limit (safety)
- [ ] Handle tool errors gracefully

### Response Format
- [ ] Structured output (reasoning, tool_calls, final_answer)
- [ ] Token/cost tracking
- [ ] Timing metrics

### Testing
- [ ] Test with mocked LLM and tools
- [ ] Test multi-turn tool calling
- [ ] Test error handling
- [ ] Coverage > 85%

---

## Implementation

```python
class Agent:
    """Agent executor with LLM + tools."""
    
    def __init__(self, config: AgentConfig, llm_provider: BaseLLMProvider, 
                 tool_registry: ToolRegistry):
        self.config = config
        self.llm = llm_provider
        self.tools = tool_registry
        self.prompt_engine = PromptEngine()
    
    def execute(self, input_data: Dict[str, Any]) -> AgentResponse:
        """Execute agent on input."""
        # 1. Render prompt
        prompt = self._render_prompt(input_data)
        
        # 2. Multi-turn tool calling loop
        tool_calls = []
        for turn in range(self.config.agent.safety.max_tool_calls_per_execution):
            # Call LLM
            llm_response = self.llm.generate(prompt)
            
            # Parse tool calls
            parsed_tools = self._parse_tool_calls(llm_response.text)
            if not parsed_tools:
                # No more tools needed
                break
            
            # Execute tools
            for tool_call in parsed_tools:
                result = self.tools.execute(tool_call["name"], tool_call["params"])
                tool_calls.append({
                    "tool": tool_call["name"],
                    "params": tool_call["params"],
                    "result": result
                })
            
            # Inject tool results into next prompt
            prompt = self._inject_tool_results(prompt, tool_calls)
        
        # 3. Final response
        return AgentResponse(
            output=llm_response.text,
            reasoning=self._extract_reasoning(llm_response.text),
            tool_calls=tool_calls,
            tokens=llm_response.total_tokens,
            cost=llm_response.estimated_cost_usd
        )
```

---

## Success Metrics

- [ ] Agent executes with real Ollama LLM
- [ ] Tool calling loop works
- [ ] Multi-turn tool execution works
- [ ] Tests pass > 85%

---

## Dependencies

- **Blocked by:** m2-01-llm-providers, m2-02-tool-registry, m2-03-prompt-engine
- **Blocks:** m2-05-langgraph-basic, m2-06-obs-hooks, m2-07-console-streaming

