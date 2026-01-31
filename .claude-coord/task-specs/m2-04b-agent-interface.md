# Task: m2-04b-agent-interface - Refactor to interface-based agent architecture

**Priority:** CRITICAL
**Effort:** 2-3 hours
**Status:** pending
**Owner:** unassigned

---

## Summary

Refactor the Agent class from m2-04 into an interface-based architecture with BaseAgent ABC, StandardAgent implementation, and AgentFactory. This enables the "radical modularity" vision principle and sets up for multiple agent types in M3+.

---

## Context

m2-04 implements a simple concrete `Agent` class. We need to refactor this to support:
- Multiple agent types (standard, debate, human, custom)
- Configuration-driven agent selection (type field in YAML)
- Easy extensibility for M3+ (multi-agent collaboration)

---

## Files to Create

- `src/agents/base_agent.py` - BaseAgent abstract class + AgentResponse/ExecutionContext
- `src/agents/standard_agent.py` - StandardAgent implementation (refactored from m2-04)
- `src/agents/agent_factory.py` - AgentFactory for creating agents from config
- `tests/test_agents/test_base_agent.py` - Interface tests
- `tests/test_agents/test_agent_factory.py` - Factory tests

---

## Files to Modify

- `src/agents/agent.py` - Move logic to StandardAgent (or deprecate)
- `src/compiler/schemas.py` - Add `type` field to AgentConfig

---

## Acceptance Criteria

### BaseAgent Interface
- [ ] BaseAgent abstract class with execute() method
- [ ] AgentResponse dataclass (output, reasoning, tool_calls, metadata)
- [ ] ExecutionContext dataclass (workflow_id, stage_id, tracker, etc.)
- [ ] get_capabilities() abstract method
- [ ] validate_config() method

### StandardAgent Implementation
- [ ] StandardAgent extends BaseAgent
- [ ] Takes AgentConfig in constructor (not pre-initialized dependencies)
- [ ] Creates LLM provider from config.agent.inference
- [ ] Loads tools from config.agent.tools using ToolRegistry
- [ ] Loads prompt template from config.agent.prompt
- [ ] Implements execute() with LLM + tool loop (from m2-04)
- [ ] All m2-04 functionality preserved

### AgentFactory
- [ ] create(config: AgentConfig) -> BaseAgent
- [ ] Maps config.agent.type to implementation class
- [ ] Supports: "standard" (StandardAgent)
- [ ] Extensible for future types (debate, human, etc.)
- [ ] Clear error for unknown types

### Config Schema Updates
- [ ] Add `type: str = "standard"` to AgentConfigInner
- [ ] Update example configs with type field
- [ ] Backward compatible (defaults to "standard")

### Testing
- [ ] Test BaseAgent interface contract
- [ ] Test StandardAgent creates LLM provider from config
- [ ] Test StandardAgent loads tools from config
- [ ] Test AgentFactory creates correct agent type
- [ ] Test unknown type raises error
- [ ] All m2-04 tests still pass
- [ ] Coverage > 85%

---

## Implementation Details

See full implementation in the detailed spec...

[Detailed BaseAgent, StandardAgent, and AgentFactory code provided]

---

## Success Metrics

- [ ] BaseAgent interface defined with all required methods
- [ ] StandardAgent implements BaseAgent with all m2-04 functionality
- [ ] AgentFactory creates agents from config
- [ ] Config schema includes type field
- [ ] All existing m2-04 tests still pass
- [ ] New interface tests pass
- [ ] Example configs updated with type field
- [ ] Coverage > 85%

---

## Dependencies

- **Blocked by:** m2-04-agent-runtime (must complete first)
- **Blocks:** m2-08-e2e-execution (needs factory pattern)
- **Integrates with:** All M2 agent-related code

---

## Design References

- META_AUTONOMOUS_FRAMEWORK_VISION.md - "Radical Modularity" principle
- TECHNICAL_SPECIFICATION.md Section 3: Agent Configuration

---

## Notes

- This is a refactor, not a rewrite - preserve all m2-04 functionality
- StandardAgent should be a drop-in replacement for Agent class
- Keep backward compatibility where possible
- Focus on extensibility for M3+ (debate agents, human agents)
- Agent type field defaults to "standard" for backward compatibility
- Agent creates all dependencies from config (LLM provider, tools, prompt)
- Use AgentFactory.create(config) instead of Agent(config, llm, tools)
