# API Reference

Complete API documentation for the Meta-Autonomous Agent Framework.

---

## Table of Contents

1. [Overview](#overview)
2. [Agents](#agents)
3. [LLM Providers](#llm-providers)
4. [Tools](#tools)
5. [Configuration](#configuration)
6. [Workflows](#workflows)
7. [Observability](#observability)
8. [Multi-Agent Collaboration](#multi-agent-collaboration)
9. [Safety System](#safety-system)
10. [Caching](#caching)
11. [Data Models](#data-models)
12. [Examples](#examples)

---

## Overview

The Meta-Autonomous Framework is organized into several core modules:

- **agents**: Agent execution and LLM providers
- **tools**: Tool registry, executor, and base classes
- **compiler**: Configuration loading and validation
- **observability**: Execution tracking and monitoring
- **strategies**: Multi-agent collaboration strategies
- **safety**: Policy enforcement and validation
- **cache**: Caching backends for LLM responses
- **core**: Base interfaces and utilities

---

## Agents

### StandardAgent

The primary agent implementation for executing tasks with LLM support.

```python
from src.agents import StandardAgent
from src.compiler.schemas import AgentConfigInner

agent = StandardAgent(config: AgentConfigInner)
response = agent.execute(input_data: Dict[str, Any]) -> AgentResponse
```

**Methods:**

- `execute(input_data)`: Execute the agent with given input
- `stream_execute(input_data)`: Stream agent execution results

**Configuration:**

```yaml
agent:
  name: my_agent
  inference:
    provider: ollama
    model: llama3.2:3b
    temperature: 0.7
    max_tokens: 2048
  tools:
    - Calculator
    - FileWriter
  safety:
    mode: execute
    max_tool_calls_per_execution: 20
```

### BaseAgent

Abstract base class for all agents.

```python
from src.agents import BaseAgent, AgentResponse, ExecutionContext

class CustomAgent(BaseAgent):
    def execute(self, input_data: Dict[str, Any]) -> AgentResponse:
        # Custom implementation
        pass
```

**Abstract Methods:**

- `execute(input_data)`: Must be implemented by subclasses

### AgentFactory

Factory for creating agents from configuration.

```python
from src.agents import AgentFactory

factory = AgentFactory()
agent = factory.create_agent(config: AgentConfigInner)
```

**Methods:**

- `create_agent(config)`: Create an agent from configuration
- `register_agent_type(type_name, agent_class)`: Register custom agent type

---

## LLM Providers

### Base Classes

```python
from src.agents import BaseLLM, LLMProvider, LLMResponse, LLMStreamChunk
```

### OllamaLLM

Local LLM provider using Ollama.

```python
from src.agents import OllamaLLM

llm = OllamaLLM(
    model="llama3.2:3b",
    base_url="http://localhost:11434",
    temperature=0.7,
    max_tokens=2048
)

response = llm.generate(prompt: str, **kwargs) -> LLMResponse
```

**Configuration:**

```yaml
inference:
  provider: ollama
  model: llama3.2:3b
  base_url: http://localhost:11434
```

### OpenAILLM

OpenAI API provider.

```python
from src.agents import OpenAILLM

llm = OpenAILLM(
    model="gpt-4",
    api_key_ref="${env:OPENAI_API_KEY}",
    temperature=0.7,
    max_tokens=2048
)
```

**Configuration:**

```yaml
inference:
  provider: openai
  model: gpt-4
  api_key_ref: ${env:OPENAI_API_KEY}
```

### AnthropicLLM

Anthropic Claude API provider.

```python
from src.agents import AnthropicLLM

llm = AnthropicLLM(
    model="claude-3-sonnet-20240229",
    api_key_ref="${env:ANTHROPIC_API_KEY}",
    temperature=0.7,
    max_tokens=2048
)
```

**Configuration:**

```yaml
inference:
  provider: anthropic
  model: claude-3-sonnet-20240229
  api_key_ref: ${env:ANTHROPIC_API_KEY}
```

### vLLMLLM

vLLM provider for self-hosted models.

```python
from src.agents import vLLMLLM

llm = vLLMLLM(
    model="meta-llama/Llama-2-7b-chat-hf",
    base_url="http://localhost:8000",
    temperature=0.7
)
```

### create_llm_client

Factory function for creating LLM clients.

```python
from src.agents import create_llm_client
from src.compiler.schemas import InferenceConfig

config = InferenceConfig(provider="ollama", model="llama3.2:3b")
llm = create_llm_client(config)
```

### LLM Exceptions

```python
from src.agents import (
    LLMError,              # Base exception
    LLMTimeoutError,       # Timeout errors
    LLMRateLimitError,     # Rate limit errors
    LLMAuthenticationError # Auth errors
)
```

---

## Tools

### BaseTool

Abstract base class for all tools.

```python
from src.tools import BaseTool, ToolParameter, ToolMetadata, ToolResult

class CustomTool(BaseTool):
    @property
    def name(self) -> str:
        return "custom_tool"

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description="Custom tool description",
            version="1.0.0",
            parameters=[
                ToolParameter(
                    name="param1",
                    type="string",
                    description="Parameter description",
                    required=True
                )
            ]
        )

    def execute(self, **kwargs) -> ToolResult:
        # Implementation
        return ToolResult(
            success=True,
            output="Result",
            metadata={}
        )
```

### ToolRegistry

Registry for discovering and managing tools.

```python
from src.tools import ToolRegistry

registry = ToolRegistry(auto_discover=True)

# Register custom tool
registry.register_tool(CustomTool())

# Get tool
tool = registry.get_tool("custom_tool")

# Get all tools
tools = registry.get_all_tools()
```

**Methods:**

- `register_tool(tool)`: Register a tool instance
- `get_tool(name)`: Get tool by name
- `get_all_tools()`: Get all registered tools
- `has_tool(name)`: Check if tool exists
- `list_available_tools()`: Get detailed information about all registered tools (class, description, version, category, etc.)
- `get_registration_report()`: Get formatted report with registration details for debugging

### ToolExecutor

Executor for running tools safely.

```python
from src.tools import ToolExecutor

executor = ToolExecutor(registry)
result = executor.execute(
    tool_name="calculator",
    parameters={"expression": "2 + 2"}
)
```

**Methods:**

- `execute(tool_name, parameters)`: Execute a tool
- `validate_parameters(tool_name, parameters)`: Validate tool parameters

### Tool Exceptions

```python
from src.tools import ToolRegistryError, ToolExecutionError
```

---

## Configuration

### ConfigLoader

Loads and validates YAML/JSON configurations.

```python
from src.compiler import ConfigLoader

loader = ConfigLoader()

# Load agent config
agent_config = loader.load_agent("my_agent")

# Load workflow config
workflow_config = loader.load_workflow("my_workflow")
```

**Methods:**

- `load_agent(name)`: Load agent configuration
- `load_workflow(name)`: Load workflow configuration
- `validate_config(config)`: Validate configuration

### Configuration Exceptions

```python
from src.compiler import ConfigNotFoundError, ConfigValidationError
```

### Configuration Schemas

```python
from src.compiler.schemas import (
    # Agent config
    AgentConfigInner,
    InferenceConfig,
    SafetyConfig,
    MemoryConfig,
    ErrorHandlingConfig,

    # Workflow config
    WorkflowConfig,
    StageConfig,

    # Tool config
    ToolConfig,
)
```

#### InferenceConfig

```python
InferenceConfig(
    provider="ollama",           # ollama, openai, anthropic, vllm, custom
    model="llama3.2:3b",
    base_url=None,
    api_key_ref=None,            # ${env:VAR_NAME}, ${vault:path}
    temperature=0.7,
    max_tokens=2048,
    top_p=0.9,
    timeout_seconds=60,
    max_retries=3,
    retry_delay_seconds=2
)
```

#### SafetyConfig

```python
SafetyConfig(
    mode="execute",              # execute, dry_run, require_approval
    require_approval_for_tools=[],
    max_tool_calls_per_execution=20,
    max_execution_time_seconds=300,
    risk_level="medium"          # low, medium, high
)
```

#### MemoryConfig

```python
MemoryConfig(
    enabled=False,
    type=None,                   # vector, episodic, procedural, semantic
    scope=None,                  # session, project, cross_session, permanent
    retrieval_k=10,
    relevance_threshold=0.7,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    max_episodes=1000,
    decay_factor=0.95
)
```

---

## Workflows

### LangGraphCompiler

Compiles workflow configurations into executable LangGraph graphs.

```python
from src.compiler.langgraph_compiler import LangGraphCompiler

compiler = LangGraphCompiler()
graph = compiler.compile(workflow_config: WorkflowConfig)

# Execute workflow
result = graph.invoke({"query": "...", "context": {}})
```

**Methods:**

- `compile(config)`: Compile workflow to LangGraph
- `validate_workflow(config)`: Validate workflow structure

### WorkflowConfig

```yaml
workflow:
  name: my_workflow
  version: "1.0.0"

  stages:
    - name: research
      type: agent
      agent_ref: researcher
      output_mapping:
        findings: research_output

    - name: synthesis
      type: agent
      agent_ref: synthesizer
      input_mapping:
        research_data: findings
```

### Multi-Agent Workflows

```yaml
workflow:
  name: parallel_research

  stages:
    - name: parallel_research
      type: multi_agent
      strategy: consensus
      agents:
        - researcher_1
        - researcher_2
        - researcher_3
      min_consensus: 0.6
```

---

## Observability

### ExecutionTracker

Track workflow, stage, and agent executions.

```python
from src.observability import ExecutionTracker, ExecutionContext

tracker = ExecutionTracker()

# Track workflow
with tracker.track_workflow("workflow_id", "my_workflow"):
    # Track stage
    with tracker.track_stage("stage_id", "research", "workflow_id"):
        # Track agent
        with tracker.track_agent("agent_id", "researcher", "stage_id"):
            # Execute agent
            result = agent.execute(input_data)
```

### Database Models

```python
from src.observability import (
    WorkflowExecution,
    StageExecution,
    AgentExecution,
    LLMCall,
    ToolExecution,
    CollaborationEvent,
    AgentMeritScore,
    DecisionOutcome,
    SystemMetric,
)
```

### Database Access

```python
from src.observability import (
    DatabaseManager,
    init_database,
    get_database,
    get_session,
)

# Initialize database
init_database(connection_string="sqlite:///workflow.db")

# Get database manager
db = get_database()

# Get session
with get_session() as session:
    executions = session.query(WorkflowExecution).all()
```

### Visualizers

```python
from src.observability import (
    WorkflowVisualizer,
    StreamingVisualizer,
    print_workflow_tree,
)

# Print workflow tree
print_workflow_tree(workflow_execution)

# Stream visualization
visualizer = StreamingVisualizer()
visualizer.on_workflow_start(workflow_id, workflow_name)
visualizer.on_agent_complete(agent_id, result)
```

### Formatters

```python
from src.observability import (
    format_duration,
    format_timestamp,
    format_tokens,
    format_cost,
    status_to_color,
    status_to_icon,
)

# Format duration: "2.5s", "1m 30s"
duration_str = format_duration(seconds)

# Format tokens: "1.2K", "1.5M"
tokens_str = format_tokens(count)

# Format cost: "$0.05", "$1.23"
cost_str = format_cost(amount)
```

### Hooks

```python
from src.observability import (
    get_tracker,
    set_tracker,
    reset_tracker,
    track_workflow,
    track_stage,
    track_agent,
    ExecutionHook,
)

# Custom hook
class CustomHook(ExecutionHook):
    def on_workflow_start(self, workflow_id, name):
        print(f"Workflow {name} started")

    def on_workflow_complete(self, workflow_id, result):
        print(f"Workflow completed: {result}")

# Set custom tracker
tracker = ExecutionTracker(hooks=[CustomHook()])
set_tracker(tracker)
```

---

## Multi-Agent Collaboration

### Collaboration Strategies

```python
from src.strategies import (
    CollaborationStrategy,
    AgentOutput,
    SynthesisResult,
)
```

#### ConsensusStrategy

Simple majority voting strategy.

```python
from src.strategies.consensus import ConsensusStrategy

strategy = ConsensusStrategy(min_consensus=0.6)

outputs = [
    AgentOutput("agent1", "Option A", "reasoning", 0.9, {}),
    AgentOutput("agent2", "Option A", "reasoning", 0.8, {}),
    AgentOutput("agent3", "Option B", "reasoning", 0.7, {}),
]

result = strategy.synthesize(outputs, context={})
# result.decision = "Option A" (majority)
# result.confidence = 0.67
```

#### DebateAndSynthesize

Multi-round argumentation strategy.

```python
from src.strategies.debate import DebateAndSynthesize

strategy = DebateAndSynthesize(
    max_rounds=3,
    convergence_threshold=0.8
)

result = strategy.synthesize(outputs, context={})
```


### Conflict Resolution

```python
from src.strategies import (
    ConflictResolutionStrategy,
    ResolutionResult,
    HighestConfidenceResolver,
    RandomTiebreakerResolver,
    MeritWeightedResolver,
    create_resolver,
)

# Use factory
resolver = create_resolver("highest_confidence")

# Or create directly
resolver = HighestConfidenceResolver()
resolver = MeritWeightedResolver()
resolver = RandomTiebreakerResolver()
```

### Utility Functions

```python
from src.strategies import (
    calculate_consensus_confidence,
    extract_majority_decision,
    calculate_vote_distribution,
)

# Calculate consensus confidence
confidence = calculate_consensus_confidence(outputs)

# Extract majority decision
decision = extract_majority_decision(outputs)

# Calculate vote distribution
distribution = calculate_vote_distribution(outputs)
# Returns: {"Option A": 2, "Option B": 1}
```

---

## Safety System

### Safety Policies

```python
from src.safety import (
    SafetyPolicy,
    BaseSafetyPolicy,
    SafetyViolation,
    ValidationResult,
    ViolationSeverity,
)
```

### BlastRadiusPolicy

Limits scope of file changes to prevent large-scale damage.

```python
from src.safety import BlastRadiusPolicy

policy = BlastRadiusPolicy(
    max_files_per_commit=5,
    max_lines_per_file=200,
    forbidden_paths=[
        "src/safety/",
        "config/",
        ".github/workflows/"
    ]
)

result = policy.validate(
    action={
        "type": "file_change",
        "files": ["src/agents/custom.py"],
        "lines_changed": 150
    },
    context={}
)

if not result.valid:
    for violation in result.violations:
        print(f"{violation.severity}: {violation.message}")
```

### SecretDetectionPolicy

Detects secrets and credentials in code/config.

```python
from src.safety import SecretDetectionPolicy

policy = SecretDetectionPolicy(
    patterns=[
        r"api[_-]?key\s*=\s*['\"]([^'\"]+)['\"]",
        r"password\s*=\s*['\"]([^'\"]+)['\"]",
    ],
    entropy_threshold=4.5,
    confidence_levels={
        "high": 0.9,
        "medium": 0.7,
        "low": 0.5
    }
)

result = policy.validate(
    action={"type": "file_change", "content": code_content},
    context={}
)
```

### RateLimiterPolicy

Rate limiting for operations.

```python
from src.safety import RateLimiterPolicy

policy = RateLimiterPolicy(
    limits={
        "commits": {"max": 10, "window_seconds": 3600},
        "deploys": {"max": 2, "window_seconds": 3600},
        "llm_calls": {"max": 100, "window_seconds": 60}
    }
)

result = policy.validate(
    action={"type": "commit"},
    context={}
)
```

### Custom Safety Policy

```python
from src.safety import BaseSafetyPolicy, ValidationResult, SafetyViolation, ViolationSeverity

class CustomPolicy(BaseSafetyPolicy):
    @property
    def name(self) -> str:
        return "custom_policy"

    @property
    def version(self) -> str:
        return "1.0.0"

    def _validate_impl(self, action, context):
        if action.get("dangerous"):
            return ValidationResult(
                valid=False,
                violations=[
                    SafetyViolation(
                        policy_name=self.name,
                        severity=ViolationSeverity.CRITICAL,
                        message="Dangerous action detected",
                        action=str(action),
                        context=context
                    )
                ],
                policy_name=self.name
            )
        return ValidationResult(valid=True, policy_name=self.name)
```

### Violation Severity

```python
from src.safety import ViolationSeverity

ViolationSeverity.INFO       # Informational
ViolationSeverity.LOW        # Low severity
ViolationSeverity.MEDIUM     # Medium severity
ViolationSeverity.HIGH       # High severity
ViolationSeverity.CRITICAL   # Critical severity
```

---

## Caching

### LLM Cache

```python
from src.cache import LLMCache, InMemoryCache, RedisCache, CacheStats

# In-memory cache
cache = InMemoryCache(max_size=1000, ttl_seconds=3600)

# Redis cache
cache = RedisCache(
    host="localhost",
    port=6379,
    db=0,
    ttl_seconds=3600
)

# Use cache
llm_cache = LLMCache(backend=cache)

# Cache key based on prompt + model + params
key = llm_cache.get_key(prompt, model, temperature, max_tokens)

# Get cached response
response = llm_cache.get(key)
if response is None:
    response = llm.generate(prompt)
    llm_cache.set(key, response)

# Cache stats
stats = llm_cache.get_stats()
print(f"Hits: {stats.hits}, Misses: {stats.misses}")
print(f"Hit rate: {stats.hit_rate:.2%}")
```

### Cache Backends

```python
from src.cache import CacheBackend

class CustomCache(CacheBackend):
    def get(self, key: str):
        # Implementation
        pass

    def set(self, key: str, value: Any, ttl: int = None):
        # Implementation
        pass

    def delete(self, key: str):
        # Implementation
        pass

    def clear(self):
        # Implementation
        pass
```

---

## Data Models

### Agent Response

```python
from src.agents import AgentResponse

response = AgentResponse(
    output="Agent response text",
    metadata={
        "model": "llama3.2:3b",
        "tokens": 150,
        "duration_ms": 1200
    },
    tool_calls=[],
    error=None
)
```

### Tool Result

```python
from src.tools import ToolResult

result = ToolResult(
    success=True,
    output="Tool output",
    metadata={
        "execution_time_ms": 50,
        "tool_version": "1.0.0"
    },
    error=None
)
```

### LLM Response

```python
from src.agents import LLMResponse

response = LLMResponse(
    text="Generated text",
    model="llama3.2:3b",
    tokens_used=150,
    finish_reason="stop",
    metadata={}
)
```

---

## Examples

### Simple Agent

```python
from src.agents import StandardAgent
from src.compiler.schemas import AgentConfigInner, InferenceConfig

config = AgentConfigInner(
    name="simple_agent",
    inference=InferenceConfig(
        provider="ollama",
        model="llama3.2:3b"
    )
)

agent = StandardAgent(config)
response = agent.execute({"query": "What is 2+2?"})
print(response.output)
```

### Agent with Tools

```python
from src.agents import StandardAgent
from src.tools import ToolRegistry, BaseTool, ToolMetadata, ToolResult
from src.compiler.schemas import AgentConfigInner, InferenceConfig

# Custom tool
class Calculator(BaseTool):
    @property
    def name(self):
        return "calculator"

    def get_metadata(self):
        return ToolMetadata(
            name=self.name,
            description="Calculate mathematical expressions",
            version="1.0.0"
        )

    def execute(self, expression: str) -> ToolResult:
        try:
            result = eval(expression)
            return ToolResult(success=True, output=str(result))
        except Exception as e:
            return ToolResult(success=False, error=str(e))

# Create agent with tool
registry = ToolRegistry(auto_discover=False)
registry.register_tool(Calculator())

config = AgentConfigInner(
    name="calculator_agent",
    inference=InferenceConfig(provider="ollama", model="llama3.2:3b"),
    tools=["calculator"]
)

agent = StandardAgent(config)
response = agent.execute({"query": "Calculate 123 * 456"})
```

### Multi-Agent Workflow

```python
from src.compiler import ConfigLoader
from src.compiler.langgraph_compiler import LangGraphCompiler

# Load workflow config
loader = ConfigLoader()
workflow_config = loader.load_workflow("research_workflow")

# Compile to LangGraph
compiler = LangGraphCompiler()
graph = compiler.compile(workflow_config)

# Execute workflow
result = graph.invoke({
    "query": "Research quantum computing applications",
    "context": {}
})

print(result["final_output"])
```

### With Observability

```python
from src.agents import StandardAgent
from src.observability import ExecutionTracker, init_database

# Initialize database
init_database("sqlite:///workflow.db")

# Create tracker
tracker = ExecutionTracker()

# Track execution
with tracker.track_agent("agent_1", "researcher", None):
    agent = StandardAgent(config)
    response = agent.execute(input_data)

# Query execution history
from src.observability import get_session, AgentExecution

with get_session() as session:
    executions = session.query(AgentExecution).all()
    for exe in executions:
        print(f"{exe.agent_name}: {exe.status} ({exe.duration_ms}ms)")
```

### With Safety Policies

```python
from src.agents import StandardAgent
from src.safety import BlastRadiusPolicy, SecretDetectionPolicy

# Create policies
blast_radius = BlastRadiusPolicy(max_files_per_commit=5)
secret_detection = SecretDetectionPolicy()

# Validate actions
action = {
    "type": "file_change",
    "files": ["src/agents/custom.py"],
    "content": "..."
}

# Check blast radius
result = blast_radius.validate(action, {})
if not result.valid:
    print("Blast radius violation!")
    for violation in result.violations:
        print(f"  - {violation.message}")

# Check secrets
result = secret_detection.validate(action, {})
if not result.valid:
    print("Secret detected!")
```

---

## Best Practices

### 1. Configuration Management

- Use `api_key_ref` with environment variables, not hardcoded keys
- Validate configurations with `ConfigLoader` before use
- Version your workflow configurations

### 2. Error Handling

- Always catch `LLMError`, `ToolExecutionError`, and `ConfigValidationError`
- Use appropriate retry strategies for transient failures
- Log errors with context for debugging

### 3. Performance

- Enable caching for LLM responses to reduce latency and cost
- Use connection pooling for database and HTTP clients
- Set appropriate timeouts for LLM and tool calls

### 4. Safety

- Always use safety policies in production
- Validate tool parameters before execution
- Monitor rate limits and resource consumption

### 5. Observability

- Track all workflow and agent executions
- Use custom hooks for application-specific monitoring
- Query execution history for debugging and optimization

---

## API Stability

- **Stable**: `agents`, `tools`, `compiler`, `observability` core APIs
- **Beta**: `strategies`, `safety`, `cache` (may change in minor versions)
- **Experimental**: Custom providers, advanced workflows

---

## See Also

- [Quick Start Guide](./QUICK_START.md)
- [Configuration Reference](./CONFIGURATION.md)
- [Integration Guide](./INTEGRATION.md)
- [Testing Guide](./TESTING.md)
- [Contributing Guide](./CONTRIBUTING.md)

---

For detailed implementation guides and examples, see the `/docs` and `/examples` directories.
