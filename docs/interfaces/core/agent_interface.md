# Agent Interface

## Overview

The agent interface defines how all agents execute tasks. It supports multiple agent types through a common interface while allowing specialized implementations.

## Class Hierarchy

```
BaseAgent (ABC)
    │
    ├─ StandardAgent
    │   └─ LLM + Tools agent (M2)
    │
    ├─ DebateAgent (M3+)
    │   └─ Multi-agent collaboration
    │
    ├─ HumanAgent (M3+)
    │   └─ Human-in-the-loop
    │
    └─ CustomAgent
        └─ User-defined implementations
```

## BaseAgent Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List


@dataclass
class AgentResponse:
    """Response from agent execution.

    Attributes:
        output: Final text output from the agent
        reasoning: Extracted reasoning/thought process (optional)
        tool_calls: List of tool calls made during execution
        metadata: Additional execution metadata
        tokens: Total tokens used (prompt + completion)
        estimated_cost_usd: Estimated cost in USD
        latency_seconds: Execution time in seconds
        error: Error message if execution failed (optional)
        confidence: Confidence score (0.0 to 1.0), auto-calculated if not provided
    """
    output: str
    reasoning: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    estimated_cost_usd: float = 0.0
    latency_seconds: float = 0.0
    error: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class ExecutionContext:
    """Context passed to agent during execution."""
    workflow_id: str
    stage_id: str
    agent_execution_id: Optional[str] = None
    previous_stage_output: Optional[Dict[str, Any]] = None
    collaboration_state: Optional[Dict[str, Any]] = None
    tracker: Optional['ExecutionTracker'] = None


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    def __init__(self, config: AgentConfig):
        """Initialize from configuration."""
        self.config = config

    @abstractmethod
    def execute(
        self,
        input_data: Dict[str, Any],
        context: ExecutionContext
    ) -> AgentResponse:
        """Execute agent on input.

        Args:
            input_data: Task-specific input
            context: Execution context (workflow, tracking, etc.)

        Returns:
            AgentResponse with output, reasoning, tool calls
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Return agent capabilities.

        Returns:
            Dict with: tools, max_tokens, supports_streaming, etc.
        """
        pass

    def validate_config(self) -> bool:
        """Validate agent configuration."""
        return True
```

## StandardAgent Implementation

```python
class StandardAgent(BaseAgent):
    """Standard LLM + tools agent."""

    def __init__(self, config: AgentConfig):
        super().__init__(config)

        # Create components from config
        self.llm = self._create_llm_provider()
        self.tools = self._load_tools()
        self.prompt_engine = PromptEngine()
        self.prompt_template = self._load_prompt_template()

    def execute(
        self,
        input_data: Dict[str, Any],
        context: ExecutionContext
    ) -> AgentResponse:
        """Execute with LLM + tool loop."""

        # 1. Render prompt
        prompt = self._render_prompt(input_data)

        # 2. Multi-turn tool calling
        tool_calls = []
        for turn in range(self.max_tool_calls):
            # Call LLM
            llm_response = self.llm.generate(prompt)

            # Track to database
            if context.tracker:
                context.tracker.track_llm_call(
                    context.agent_execution_id,
                    llm_response
                )

            # Parse tool calls
            parsed_tools = self._parse_tool_calls(llm_response.text)
            if not parsed_tools:
                break

            # Execute tools
            for tool_call in parsed_tools:
                result = self._execute_tool(tool_call)
                tool_calls.append(result)

                # Track to database
                if context.tracker:
                    context.tracker.track_tool_call(...)

            # Inject results for next turn
            prompt = self._inject_tool_results(prompt, tool_calls)

        # 3. Return response
        return AgentResponse(
            output=llm_response.text,  # String, not dict!
            reasoning=self._extract_reasoning(llm_response.text),
            tool_calls=tool_calls,
            metadata={
                "llm_calls": turn + 1,
            },
            tokens=total_tokens,
            estimated_cost_usd=total_cost,
            latency_seconds=total_duration
        )

    def get_capabilities(self) -> Dict[str, Any]:
        """Return capabilities."""
        return {
            "agent_type": "standard",
            "tools_available": [t.name for t in self.tools],
            "llm_provider": self.config.agent.inference.provider,
            "llm_model": self.config.agent.inference.model,
            "max_tokens": self.config.agent.inference.max_tokens,
            "supports_streaming": True,
            "supports_tools": True,
        }
```

## Agent Factory

```python
class AgentFactory:
    """Creates agents from configuration."""

    _agent_types = {
        "standard": StandardAgent,
        # Future: "debate": DebateAgent, etc.
    }

    @classmethod
    def create(cls, config: AgentConfig) -> BaseAgent:
        """Create agent from config.

        Args:
            config: Validated AgentConfig

        Returns:
            Instantiated agent

        Raises:
            ValueError: If type unknown
        """
        agent_type = config.agent.type
        agent_class = cls._agent_types.get(agent_type)

        if not agent_class:
            raise ValueError(f"Unknown agent type: {agent_type}")

        return agent_class(config)

    @classmethod
    def register(cls, agent_type: str, agent_class: Type[BaseAgent]):
        """Register custom agent type."""
        cls._agent_types[agent_type] = agent_class
```

## Configuration Schema

```yaml
agent:
  type: standard              # Agent implementation type
  name: researcher
  description: "Research agent"
  version: "1.0"

  prompt:
    inline: |                 # Or template: "path/to/file.txt"
      You are a researcher.
      Task: {{task}}
      Tools: {{tools}}
    variables:
      expertise: "market analysis"

  inference:
    provider: ollama
    model: llama3.2:3b
    temperature: 0.7
    max_tokens: 2048

  tools:
    - Calculator
    - WebScraper

  safety:
    mode: execute
    max_tool_calls_per_execution: 10
```

## Usage Example

```python
from src.compiler.config_loader import init_config_loader
from src.agents.agent_factory import AgentFactory
from src.observability.tracker import ExecutionTracker

# Load config
loader = init_config_loader("configs")
agent_config = loader.load_agent("researcher")

# Create agent
agent = AgentFactory.create(agent_config)

# Execute
context = ExecutionContext(
    workflow_id="wf-123",
    stage_id="stage-456",
    tracker=ExecutionTracker()
)

response = agent.execute(
    input_data={"task": "Research TypeScript benefits"},
    context=context
)

print(f"Output: {response.output}")
print(f"Reasoning: {response.reasoning}")
print(f"Tools used: {len(response.tool_calls)}")
print(f"Cost: ${response.estimated_cost_usd:.4f}")
print(f"Tokens: {response.tokens}")
print(f"Latency: {response.latency_seconds:.2f}s")
print(f"Confidence: {response.confidence:.2f}")
```

## Execution Flow Diagram

```
agent.execute(input_data, context)
    │
    ├─ 1. Render Prompt
    │      ├─ Load template
    │      ├─ Inject variables (config + input)
    │      ├─ Format tool descriptions
    │      └─> "You are a researcher. Task: ..."
    │
    ├─ 2. LLM Call (Turn 1)
    │      ├─ llm.generate(prompt)
    │      ├─ Track to database
    │      └─> Response: "I'll use Calculator..."
    │
    ├─ 3. Parse Tool Calls
    │      └─> [{"name": "Calculator", "params": {"expr": "2+2"}}]
    │
    ├─ 4. Execute Tools
    │      ├─ tool.execute(expr="2+2")
    │      ├─ Track to database
    │      └─> Result: 4
    │
    ├─ 5. Inject Tool Results
    │      └─> Prompt + "\nTool result: 4"
    │
    ├─ 6. LLM Call (Turn 2)
    │      ├─ llm.generate(updated_prompt)
    │      └─> Response: "Based on calculation, the answer is 4"
    │
    └─ 7. Return AgentResponse
           ├─ output: {"final_answer": "..."}
           ├─ reasoning: "..."
           ├─ tool_calls: [...]
           └─ metadata: {tokens, cost, duration}
```

## Agent Types (Future)

### DebateAgent (M3)
```python
class DebateAgent(BaseAgent):
    """Multi-turn debate with other agents."""

    def execute(self, input_data, context):
        # Participate in debate rounds
        # Vote on proposals
        # Resolve conflicts
        # Reach consensus
        pass
```

### HumanAgent (M3+)
```python
class HumanAgent(BaseAgent):
    """Human-in-the-loop agent."""

    def execute(self, input_data, context):
        # Prompt human for input
        # Wait for response
        # Return human decision
        pass
```

### CustomAgent (Extensible)
```python
class MyCustomAgent(BaseAgent):
    """User-defined custom agent."""

    def execute(self, input_data, context):
        # Custom logic here
        pass

# Register it
AgentFactory.register("custom", MyCustomAgent)
```

## Key Design Points

1. **Interface-based** - All agents implement BaseAgent
2. **Config-driven** - Type field determines implementation
3. **Self-contained** - Agent creates own dependencies from config
4. **Observable** - Context provides tracker for all operations
5. **Extensible** - Users can register custom agent types
6. **Type-safe** - AgentResponse and ExecutionContext are dataclasses

## Related Documentation

- [LLM Provider Interface](./llm_provider_interface.md)
- [Tool Interface](./tool_interface.md)
- [Configuration Schema](./config_schema.md)
