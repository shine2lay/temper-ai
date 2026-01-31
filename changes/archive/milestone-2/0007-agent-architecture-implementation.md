# Change: Agent Architecture Implementation

**Tasks:** m2-04-agent-runtime, m2-04b-agent-interface
**Date:** 2026-01-26
**Type:** Feature Implementation
**Impact:** Milestone 2 - Core Agent System

---

## Summary

Implemented complete interface-based agent architecture with BaseAgent ABC, StandardAgent implementation, and AgentFactory. This provides the foundation for executing workflows with LLM + tool calling capabilities while enabling future agent types (debate, human, custom) through the factory pattern.

Combined both m2-04-agent-runtime (basic agent executor) and m2-04b-agent-interface (refactor to interface-based architecture) into a single cohesive implementation following the "radical modularity" vision principle.

---

## Changes

### New Files

- **`src/agents/base_agent.py`** (BaseAgent ABC + data classes)
  - `BaseAgent` abstract base class with `execute()` and `get_capabilities()` methods
  - `AgentResponse` dataclass for structured execution results
  - `ExecutionContext` dataclass for workflow/stage/agent tracking
  - Config validation method

- **`src/agents/standard_agent.py`** (StandardAgent implementation)
  - Concrete implementation of BaseAgent
  - Multi-turn LLM + tool execution loop
  - Prompt rendering with tool schemas
  - Tool call parsing (XML-style `<tool_call>` tags)
  - LLM provider creation from config
  - Tool registry initialization
  - Token tracking and cost estimation

- **`src/agents/agent_factory.py`** (AgentFactory)
  - Configuration-driven agent creation
  - Maps `type` field to implementation classes
  - Supports custom type registration
  - Extensible for M3+ agent types

- **`tests/test_agents/conftest.py`** (Test fixtures)
  - `minimal_agent_config` fixture
  - `agent_config_with_tools` fixture

- **`tests/test_agents/test_base_agent.py`** (13 tests)
  - Interface contract tests
  - AgentResponse and ExecutionContext tests
  - Abstract class enforcement tests
  - MockAgent implementation tests

- **`tests/test_agents/test_agent_factory.py`** (8 tests)
  - Factory creation tests
  - Type registration tests
  - Unknown type handling tests
  - Custom agent type tests

- **`tests/test_agents/test_standard_agent.py`** (12 tests)
  - Execution tests with mocked LLM
  - Tool calling loop tests
  - Error handling tests
  - Tool call parsing tests
  - Reasoning extraction tests

### Modified Files

- **`src/compiler/schemas.py`**
  - Added `type: str = "standard"` field to `AgentConfigInner`
  - Backward compatible (defaults to "standard")
  - Enables configuration-driven agent selection

- **`src/agents/__init__.py`**
  - Exported BaseAgent, AgentResponse, ExecutionContext
  - Exported StandardAgent
  - Exported AgentFactory

---

## Implementation Details

### BaseAgent Interface

```python
class BaseAgent(ABC):
    """Abstract base class for all agents."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.agent.name
        self.description = config.agent.description
        self.version = config.agent.version

    @abstractmethod
    def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Execute agent with given input."""
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities and metadata."""
        pass

    def validate_config(self) -> bool:
        """Validate agent configuration."""
        pass
```

### StandardAgent Execution Flow

1. **Initialization**
   - Create LLM provider from config (Ollama/OpenAI/Anthropic)
   - Create tool registry and auto-discover tools
   - Initialize prompt engine

2. **Execution Loop**
   - Render prompt with input data + tool schemas
   - Call LLM
   - Parse tool calls from response (XML `<tool_call>` tags)
   - Execute tools and collect results
   - Inject tool results into next prompt
   - Repeat until no more tools or max iterations

3. **Response Generation**
   - Extract final answer (from `<answer>` tags)
   - Extract reasoning (from `<reasoning>` or `<thinking>` tags)
   - Track tokens, cost, latency
   - Return structured AgentResponse

### Tool Calling Format

```xml
<reasoning>I need to calculate 2+2</reasoning>
<tool_call>{"name": "calculator", "parameters": {"expression": "2+2"}}</tool_call>
```

Response includes tool results:
```
Tool Results:
Tool: calculator
Parameters: {"expression": "2+2"}
Result: 4
```

### AgentFactory Usage

```python
# Create agent from configuration
config = AgentConfig(...)
agent = AgentFactory.create(config)

# Execute agent
response = agent.execute({"query": "What is 2+2?"})

# Register custom agent type
class MyCustomAgent(BaseAgent):
    ...

AgentFactory.register_type("my_custom", MyCustomAgent)
```

---

## Testing

### Test Coverage

- **33 tests** across 3 test files
- **agent_factory.py: 100% coverage**
- **base_agent.py: 91% coverage**
- **standard_agent.py: 86% coverage**

### Test Categories

1. **Interface Tests**: BaseAgent contract, abstract methods, validation
2. **Factory Tests**: Agent creation, type mapping, custom registration
3. **StandardAgent Tests**: Execution, tool calling, error handling, parsing

### Mocking Strategy

- LLM responses mocked with predefined LLMResponse objects
- Tool registry mocked to avoid external dependencies
- Tests cover happy path, error cases, edge cases

---

## Acceptance Criteria

### m2-04-agent-runtime ✓

**Agent Core:**
- ✅ Initialize agent from AgentConfig
- ✅ Load LLM provider based on config
- ✅ Load tools from registry
- ✅ Render prompt template with input
- ✅ Execute LLM call
- ✅ Parse tool calls from LLM response
- ✅ Execute tools sequentially
- ✅ Generate final response

**Tool Calling Loop:**
- ✅ LLM generates tool call → parse → execute → inject result → LLM again
- ✅ Support multi-turn tool calling
- ✅ Max tool call limit (safety)
- ✅ Handle tool errors gracefully

**Response Format:**
- ✅ Structured output (reasoning, tool_calls, final_answer)
- ✅ Token/cost tracking
- ✅ Timing metrics

**Testing:**
- ✅ Test with mocked LLM and tools
- ✅ Test multi-turn tool calling
- ✅ Test error handling
- ✅ Coverage > 85% (achieved 86%)

### m2-04b-agent-interface ✓

**BaseAgent Interface:**
- ✅ BaseAgent abstract class with execute() method
- ✅ AgentResponse dataclass (output, reasoning, tool_calls, metadata)
- ✅ ExecutionContext dataclass (workflow_id, stage_id, tracker, etc.)
- ✅ get_capabilities() abstract method
- ✅ validate_config() method

**StandardAgent Implementation:**
- ✅ StandardAgent extends BaseAgent
- ✅ Takes AgentConfig in constructor
- ✅ Creates LLM provider from config.agent.inference
- ✅ Loads tools from config.agent.tools using ToolRegistry
- ✅ Loads prompt template from config.agent.prompt
- ✅ Implements execute() with LLM + tool loop
- ✅ All m2-04 functionality preserved

**AgentFactory:**
- ✅ create(config: AgentConfig) -> BaseAgent
- ✅ Maps config.agent.type to implementation class
- ✅ Supports: "standard" (StandardAgent)
- ✅ Extensible for future types (debate, human, etc.)
- ✅ Clear error for unknown types

**Config Schema Updates:**
- ✅ Add `type: str = "standard"` to AgentConfigInner
- ✅ Backward compatible (defaults to "standard")

**Testing:**
- ✅ Test BaseAgent interface contract
- ✅ Test StandardAgent creates LLM provider from config
- ✅ Test StandardAgent loads tools from config
- ✅ Test AgentFactory creates correct agent type
- ✅ Test unknown type raises error
- ✅ Coverage > 85% (achieved 86-100%)

---

## Integration

- **Uses**: LLM providers (m2-01), Tool registry (m2-02), Prompt engine (m2-03)
- **Blocks**: m2-05-langgraph-basic (needs agent execution)
- **Blocks**: m2-06-obs-hooks (needs agent execution to track)
- **Blocks**: m2-08-e2e-execution (needs complete agent system)

---

## Future Enhancements (M3+)

- **DebateAgent**: Multi-agent debate with voting and synthesis
- **HumanAgent**: Human-in-the-loop with approval workflows
- **CustomAgent**: User-defined agent types via plugins
- **Streaming**: Real-time streaming of LLM responses
- **Multimodal**: Image/audio input support

---

## Design Decisions

1. **Interface-based architecture**: Enables pluggable agent types
2. **XML-style tool calling**: Simple to parse, readable in prompts
3. **Config-driven initialization**: Agent creates all dependencies from config
4. **Factory pattern**: Centralized agent creation with type mapping
5. **Backward compatibility**: Type field defaults to "standard"

---

## Notes

- Implemented both m2-04 and m2-04b together for efficiency
- StandardAgent is production-ready for basic workflows
- Agent type system prepared for M3 multi-agent collaboration
- Tool calling uses XML tags (not JSON function calling format)
- Cost estimation is simplified (would use provider-specific rates in prod)
- Prompt engine integration handles both inline and file-based templates
