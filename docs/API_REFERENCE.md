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
7. [Execution Engines](#execution-engines)
8. [Checkpointing](#checkpointing)
9. [Observability](#observability)
10. [Multi-Agent Collaboration](#multi-agent-collaboration)
11. [Safety System](#safety-system)
12. [Caching](#caching)
13. [Data Models](#data-models)
14. [Examples](#examples)

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
registry.register(CustomTool())

# Get tool
tool = registry.get("custom_tool")

# Check if tool exists
if registry.has("custom_tool"):
    print("Tool found")

# Get all tools
tools = registry.get_all_tools()
```

**Methods:**

- `register(tool, allow_override=False)`: Register a tool instance
- `get(name, version=None)`: Get tool by name (optionally specify version)
- `get_all_tools()`: Get all registered tools
- `has(name, version=None)`: Check if tool exists
- `list_available_tools()`: Get detailed information about all registered tools
- `get_registration_report()`: Get formatted debugging report

#### Advanced Methods

**list_available_tools() → Dict[str, Dict[str, Any]]**

Get detailed information about all registered tools (latest version of each):

```python
registry = ToolRegistry(auto_discover=True)

# Get detailed tool information
tools = registry.list_available_tools()

for name, info in tools.items():
    print(f"Tool: {name}")
    print(f"  Class: {info['class']}")
    print(f"  Description: {info['description']}")
    print(f"  Version: {info['version']}")
    print(f"  Category: {info.get('category', 'general')}")
    print(f"  Metadata: {info['metadata']}")
```

**Returns:** Dictionary mapping tool names to detailed information:
- `class`: Tool class name
- `description`: Tool description
- `version`: Tool version
- `category`: Tool category (optional)
- `metadata`: Tool metadata (ToolMetadata object)

**get_registration_report() → str**

Get formatted debugging report with registration statistics:

```python
registry = ToolRegistry(auto_discover=True)

# Print detailed registration report
print(registry.get_registration_report())

# Output:
# Tool Registry Report
# ====================
# Total registered tools: 3 (5 versions)
#
# Registered tools:
#   - calculator (v1.0.0, v2.0.0)
#   - web_scraper (v1.0.0)
#   - file_writer (v1.0.0, v1.1.0)
```

**Returns:** Formatted multi-line report string with:
- Total tool count (unique names and versions)
- List of all registered tools with their versions
- Useful for debugging registration issues

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

## Execution Engines

The execution engine abstraction layer decouples workflow execution from specific graph libraries (like LangGraph), enabling vendor independence, alternative execution strategies, and runtime feature detection.

### ExecutionEngine

Abstract base class for workflow execution engines.

```python
from src.compiler.execution_engine import ExecutionEngine, ExecutionMode

class CustomEngine(ExecutionEngine):
    """Custom execution engine implementation."""

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        """Compile workflow configuration into executable form."""
        # Validate and optimize workflow config
        # Return engine-specific compiled representation
        pass

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Dict[str, Any]:
        """Execute compiled workflow."""
        # Execute workflow and return final state
        pass

    def supports_feature(self, feature: str) -> bool:
        """Check if engine supports specific feature."""
        supported_features = {
            "sequential_stages",
            "parallel_stages",
            "checkpointing"
        }
        return feature in supported_features
```

**Supported Features:**
- `sequential_stages` - Sequential stage execution
- `parallel_stages` - Parallel stage execution
- `conditional_routing` - Conditional transitions
- `convergence_detection` - Convergence detection
- `checkpointing` - Save/restore execution state
- `streaming_execution` - Stream intermediate results
- `nested_workflows` - Nested workflow support
- `distributed_execution` - Distributed execution

### LangGraphExecutionEngine

Default execution engine using LangGraph.

```python
from src.compiler.langgraph_engine import LangGraphExecutionEngine

# Create engine instance
engine = LangGraphExecutionEngine(config_loader=config_loader)

# Compile workflow
workflow_config = {
    "name": "my_workflow",
    "stages": [
        {"name": "analysis", "agents": ["analyzer"], "mode": "sequential"},
        {"name": "synthesis", "agents": ["synthesizer"], "mode": "sequential"}
    ]
}
compiled = engine.compile(workflow_config)

# Execute workflow
result = engine.execute(
    compiled,
    input_data={"task": "Analyze the data"},
    mode=ExecutionMode.SYNC
)
print(result)  # Final workflow state
```

### EngineRegistry

Factory for managing and creating execution engines.

```python
from src.compiler.engine_registry import EngineRegistry
from src.compiler.execution_engine import ExecutionEngine

# Get registry instance (singleton)
registry = EngineRegistry()

# Register custom engine
registry.register_engine("custom", CustomEngine)

# Get engine by name
engine = registry.get_engine("custom", config_loader=config_loader)

# List available engines
engines = registry.list_engines()
print(engines)  # ["langgraph", "custom"]
```

**Usage:**
- Engine selection via workflow configuration (`engine: "langgraph"`)
- Runtime A/B testing of different engines
- Plugin architecture for third-party engines

### Stage Executors

Stage executors control how agents within a stage are executed in multi-agent workflows. Available executors:

#### SequentialStageExecutor

Executes agents one at a time in order (default M2 behavior).

```python
from src.compiler.executors.sequential import SequentialStageExecutor

# Create sequential executor
executor = SequentialStageExecutor()

# Execute stage (used internally by execution engine)
result = executor.execute_stage(
    stage_name="analysis",
    stage_config={
        "agents": ["analyzer1", "analyzer2"],
        "mode": "sequential"
    },
    state={"task": "Analyze data"},
    config_loader=config_loader
)
```

**When to use:**
- Simple workflows with dependent agent outputs
- When agents must run in specific order
- Lower resource usage (one agent at a time)
- Deterministic execution order

**Configuration:**
```yaml
stages:
  - name: analysis
    agents: [analyzer1, analyzer2]
    mode: sequential  # Default
```

#### ParallelStageExecutor

Executes multiple agents concurrently using nested LangGraph subgraphs (M3 feature).

```python
from src.compiler.executors.parallel import ParallelStageExecutor
from src.strategies.registry import StrategyRegistry

# Get collaboration strategy
strategy_registry = StrategyRegistry()
consensus_strategy = strategy_registry.get_strategy("consensus")

# Create parallel executor with synthesis
executor = ParallelStageExecutor(
    synthesis_coordinator=consensus_strategy
)

# Execute stage with parallel agents
result = executor.execute_stage(
    stage_name="analysis",
    stage_config={
        "agents": ["agent1", "agent2", "agent3"],
        "mode": "parallel",
        "collaboration_strategy": "consensus",
        "min_consensus": 0.7
    },
    state={"task": "Analyze data"},
    config_loader=config_loader
)

# Result contains synthesized output
print(result["synthesis_result"])
print(result["agent_outputs"])  # Individual agent outputs
```

**When to use:**
- Independent agent perspectives needed
- Faster execution with concurrent processing
- Multi-agent collaboration (consensus, debate)
- Quality improvement through diversity

**Configuration:**
```yaml
stages:
  - name: analysis
    agents: [researcher1, researcher2, researcher3]
    mode: parallel
    collaboration_strategy: consensus
    min_consensus: 0.7
```

#### AdaptiveStageExecutor

Starts with parallel execution, switches to sequential if disagreement is high (M3 advanced feature).

```python
from src.compiler.executors.adaptive import AdaptiveStageExecutor

# Create adaptive executor
executor = AdaptiveStageExecutor(
    disagreement_threshold=0.3
)

# Execute stage - automatically adapts based on convergence
result = executor.execute_stage(
    stage_name="analysis",
    stage_config={
        "agents": ["agent1", "agent2", "agent3"],
        "mode": "adaptive",
        "disagreement_threshold": 0.3
    },
    state={"task": "Analyze data"},
    config_loader=config_loader
)

# Check if fallback occurred
if result.get("fallback_to_sequential"):
    print("High disagreement detected, switched to sequential mode")
```

**When to use:**
- Uncertain consensus scenarios
- Cost optimization (try parallel first, fallback if needed)
- Automatic convergence detection
- Resource-aware execution

**Configuration:**
```yaml
stages:
  - name: analysis
    agents: [agent1, agent2, agent3]
    mode: adaptive
    disagreement_threshold: 0.3  # 30% disagreement triggers sequential
```

**Executor Selection:**

```yaml
# Workflow configuration with stage executors
name: multi_agent_workflow
engine: langgraph

stages:
  # Sequential stage (default)
  - name: data_collection
    agents: [collector]
    mode: sequential

  # Parallel stage with consensus
  - name: analysis
    agents: [analyst1, analyst2, analyst3]
    mode: parallel
    collaboration_strategy: consensus
    min_consensus: 0.7

  # Adaptive stage with automatic fallback
  - name: recommendation
    agents: [recommender1, recommender2]
    mode: adaptive
    disagreement_threshold: 0.3
```

### CompiledWorkflow

Abstract compiled workflow representation.

```python
from src.compiler.execution_engine import CompiledWorkflow

# Execute compiled workflow
result = compiled_workflow.invoke({"input": "data"})

# Async execution
result = await compiled_workflow.ainvoke({"input": "data"})

# Get metadata
metadata = compiled_workflow.get_metadata()
print(metadata["engine"])   # "langgraph"
print(metadata["stages"])   # ["stage1", "stage2"]

# Visualize workflow
graph_viz = compiled_workflow.visualize()
print(graph_viz)  # Mermaid/DOT graph representation

# Cancel execution
compiled_workflow.cancel()
if compiled_workflow.is_cancelled():
    print("Workflow cancelled")
```

### Execution Modes

```python
from src.compiler.execution_engine import ExecutionMode

# Synchronous execution (blocking)
result = engine.execute(compiled, input_data, mode=ExecutionMode.SYNC)

# Asynchronous execution (non-blocking)
result = engine.execute(compiled, input_data, mode=ExecutionMode.ASYNC)

# Streaming execution (yields intermediate results)
result = engine.execute(compiled, input_data, mode=ExecutionMode.STREAM)
```

### Creating Custom Engines

```python
from src.compiler.execution_engine import (
    ExecutionEngine,
    CompiledWorkflow,
    ExecutionMode,
    WorkflowCancelledError
)
from typing import Dict, Any

class MyCompiledWorkflow(CompiledWorkflow):
    """Custom compiled workflow implementation."""

    def __init__(self, internal_repr):
        self.internal_repr = internal_repr
        self._cancelled = False

    def _execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow logic (user-defined implementation)."""
        # Example: Execute stages sequentially
        current_state = state.copy()
        for stage in self.internal_repr.stages:
            # Execute stage logic here
            current_state[f"{stage}_output"] = f"Result from {stage}"
        return current_state

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if self._cancelled:
            raise WorkflowCancelledError("Workflow cancelled")
        # Execute workflow synchronously
        return self._execute(state)

    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if self._cancelled:
            raise WorkflowCancelledError("Workflow cancelled")
        # Execute workflow asynchronously
        return self._execute(state)

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "engine": "custom",
            "version": "1.0.0",
            "config": self.internal_repr.config,
            "stages": self.internal_repr.stages
        }

    def visualize(self) -> str:
        # Return Mermaid or DOT representation
        return "graph TD\n  A[stage1] --> B[stage2]"

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

class MyCustomEngine(ExecutionEngine):
    """Custom execution engine implementation."""

    def _build_internal_repr(self, workflow_config: Dict[str, Any]):
        """Build internal representation from config (user-defined implementation)."""
        # Simple example: Create a structure with stage names
        from collections import namedtuple
        InternalRepr = namedtuple("InternalRepr", ["config", "stages"])
        stage_names = [stage["name"] for stage in workflow_config.get("stages", [])]
        return InternalRepr(config=workflow_config, stages=stage_names)

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        # Validate workflow config
        if "stages" not in workflow_config:
            raise ValueError("Workflow must have stages")

        # Create internal representation
        internal_repr = self._build_internal_repr(workflow_config)

        # Return compiled workflow
        return MyCompiledWorkflow(internal_repr)

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Dict[str, Any]:
        if not isinstance(compiled_workflow, MyCompiledWorkflow):
            raise TypeError("Wrong compiled workflow type")

        if mode == ExecutionMode.SYNC:
            return compiled_workflow.invoke(input_data)
        elif mode == ExecutionMode.ASYNC:
            import asyncio
            return asyncio.run(compiled_workflow.ainvoke(input_data))
        else:
            raise NotImplementedError(f"Mode {mode} not supported")

    def supports_feature(self, feature: str) -> bool:
        return feature in {"sequential_stages", "checkpointing"}

# Register custom engine
from src.compiler.engine_registry import EngineRegistry
registry = EngineRegistry()
registry.register_engine("my_custom_engine", MyCustomEngine)
```

---

## Checkpointing

Checkpoint and resume support for long-running workflows, enabling recovery from failures and distributed execution.

### CheckpointManager

High-level checkpoint management for workflows.

```python
from src.compiler.checkpoint_manager import (
    CheckpointManager,
    CheckpointStrategy
)
from src.compiler.checkpoint_backends import FileCheckpointBackend
from src.compiler.domain_state import WorkflowDomainState

# Create manager with file backend (default)
manager = CheckpointManager()

# Or specify custom backend
backend = FileCheckpointBackend(checkpoint_dir="./my-checkpoints")
manager = CheckpointManager(
    backend=backend,
    strategy=CheckpointStrategy.EVERY_STAGE,
    max_checkpoints=10
)

# Save checkpoint
domain = WorkflowDomainState(workflow_id="wf-123", input="analyze data")
domain.set_stage_output("research", {"findings": ["data1", "data2"]})
checkpoint_id = manager.save_checkpoint(domain)

# Resume from checkpoint
restored_domain = manager.load_checkpoint("wf-123")
print(restored_domain.stage_outputs)  # {"research": {"findings": [...]}}

# Check if checkpoint exists
if manager.has_checkpoint("wf-123"):
    domain = manager.load_checkpoint("wf-123")

# List all checkpoints for a workflow
checkpoints = manager.list_checkpoints("wf-123")
for cp in checkpoints:
    print(f"{cp['checkpoint_id']}: {cp['stage']} at {cp['created_at']}")

# Delete old checkpoints
manager.delete_checkpoint("wf-123", checkpoint_id)
```

**Checkpoint Strategies:**

```python
from src.compiler.checkpoint_manager import CheckpointStrategy

# Save after every stage (default)
manager = CheckpointManager(strategy=CheckpointStrategy.EVERY_STAGE)

# Save at fixed time intervals (e.g., every 5 minutes)
manager = CheckpointManager(
    strategy=CheckpointStrategy.PERIODIC,
    periodic_interval=300  # seconds
)

# Only save when explicitly requested
manager = CheckpointManager(strategy=CheckpointStrategy.MANUAL)

# Disable automatic checkpointing
manager = CheckpointManager(strategy=CheckpointStrategy.DISABLED)
```

**Lifecycle Hooks:**

```python
# Register callbacks for checkpoint events
def on_saved(workflow_id: str, checkpoint_id: str):
    print(f"Checkpoint saved: {checkpoint_id}")

def on_loaded(workflow_id: str, checkpoint_id: str):
    print(f"Checkpoint loaded: {checkpoint_id}")

def on_failed(workflow_id: str, error: Exception):
    print(f"Checkpoint failed: {error}")

manager.on_checkpoint_saved = on_saved
manager.on_checkpoint_loaded = on_loaded
manager.on_checkpoint_failed = on_failed
```

### CheckpointBackend

Abstract base class for checkpoint storage backends.

**Required Methods for Custom Backends:**
- `save_checkpoint()` - Persist workflow domain state
- `load_checkpoint()` - Restore workflow domain state
- `list_checkpoints()` - List available checkpoints
- `delete_checkpoint()` - Remove a checkpoint
- `get_latest_checkpoint()` - Get most recent checkpoint ID

**Optional Helper Methods:**
- `has_checkpoint()` - Check if checkpoint exists (can use default implementation or override)

**FileCheckpointBackend** - Store checkpoints as JSON files (default, no dependencies):

```python
from src.compiler.checkpoint_backends import FileCheckpointBackend

# Create file backend
backend = FileCheckpointBackend(checkpoint_dir="./checkpoints")

# Save checkpoint
from src.compiler.domain_state import WorkflowDomainState
domain = WorkflowDomainState(workflow_id="wf-123", input="test")
checkpoint_id = backend.save_checkpoint(
    workflow_id="wf-123",
    domain_state=domain,
    metadata={"stage": "research", "user": "alice"}
)

# Load checkpoint
loaded_domain = backend.load_checkpoint("wf-123", checkpoint_id)

# List all checkpoints for a workflow
checkpoints = backend.list_checkpoints("wf-123")

# Get latest checkpoint
latest = backend.get_latest_checkpoint("wf-123")

# Delete checkpoint
backend.delete_checkpoint("wf-123", checkpoint_id)
```

**RedisCheckpointBackend** - Store checkpoints in Redis (for distributed systems):

```python
from src.compiler.checkpoint_backends import RedisCheckpointBackend

# Create Redis backend
backend = RedisCheckpointBackend(
    redis_url="redis://localhost:6379",
    ttl=3600  # Optional TTL in seconds (1 hour)
)

# Usage is same as FileCheckpointBackend
checkpoint_id = backend.save_checkpoint("wf-123", domain)
loaded_domain = backend.load_checkpoint("wf-123", checkpoint_id)
```

**Custom Backend:**

```python
from src.compiler.checkpoint_backends import CheckpointBackend
from src.compiler.domain_state import WorkflowDomainState
from typing import Dict, Any, Optional, List

class S3CheckpointBackend(CheckpointBackend):
    """Store checkpoints in AWS S3."""

    def __init__(self, bucket_name: str):
        import boto3
        self.bucket = bucket_name
        self.s3 = boto3.client('s3')

    def save_checkpoint(
        self,
        workflow_id: str,
        domain_state: WorkflowDomainState,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        import json
        from datetime import datetime, UTC

        # Generate checkpoint ID if not provided
        if not checkpoint_id:
            timestamp = datetime.now(UTC).isoformat()
            checkpoint_id = f"cp-{timestamp}"

        # Serialize checkpoint
        checkpoint_data = {
            "checkpoint_id": checkpoint_id,
            "workflow_id": workflow_id,
            "created_at": datetime.now(UTC).isoformat(),
            "domain_state": domain_state.to_dict(),
            "metadata": metadata or {}
        }

        # Save to S3
        key = f"checkpoints/{workflow_id}/{checkpoint_id}.json"
        self.s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(checkpoint_data)
        )

        return checkpoint_id

    def load_checkpoint(
        self,
        workflow_id: str,
        checkpoint_id: Optional[str] = None
    ) -> WorkflowDomainState:
        import json
        from src.compiler.checkpoint_backends import CheckpointNotFoundError

        # Get latest if checkpoint_id not specified
        if not checkpoint_id:
            checkpoint_id = self.get_latest_checkpoint(workflow_id)

        # Load from S3
        key = f"checkpoints/{workflow_id}/{checkpoint_id}.json"
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            checkpoint_data = json.loads(response['Body'].read())
            return WorkflowDomainState.from_dict(checkpoint_data["domain_state"])
        except self.s3.exceptions.NoSuchKey:
            raise CheckpointNotFoundError(
                f"Checkpoint not found: {workflow_id}/{checkpoint_id}"
            )

    def list_checkpoints(self, workflow_id: str) -> List[Dict[str, Any]]:
        """List all checkpoints for a workflow from S3."""
        # List objects with prefix checkpoints/{workflow_id}/
        response = self.s3.list_objects_v2(
            Bucket=self.bucket,
            Prefix=f"checkpoints/{workflow_id}/"
        )
        checkpoints = []
        for obj in response.get('Contents', []):
            # Parse checkpoint metadata from S3 object
            checkpoints.append({
                'checkpoint_id': obj['Key'].split('/')[-1].replace('.json', ''),
                'created_at': obj['LastModified'].isoformat(),
                'size': obj['Size']
            })
        return sorted(checkpoints, key=lambda x: x['created_at'], reverse=True)

    def delete_checkpoint(self, workflow_id: str, checkpoint_id: str) -> None:
        """Delete a checkpoint from S3."""
        key = f"checkpoints/{workflow_id}/{checkpoint_id}.json"
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def get_latest_checkpoint(self, workflow_id: str) -> str:
        """Get the most recent checkpoint ID from S3."""
        checkpoints = self.list_checkpoints(workflow_id)
        if not checkpoints:
            from src.compiler.checkpoint_backends import CheckpointNotFoundError
            raise CheckpointNotFoundError(f"No checkpoints found for {workflow_id}")
        return checkpoints[0]['checkpoint_id']

    def has_checkpoint(self, workflow_id: str, checkpoint_id: Optional[str] = None) -> bool:
        """Check if a checkpoint exists in S3."""
        if checkpoint_id:
            key = f"checkpoints/{workflow_id}/{checkpoint_id}.json"
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
                return True
            except self.s3.exceptions.ClientError:
                return False
        else:
            # Check if any checkpoint exists for workflow
            return len(self.list_checkpoints(workflow_id)) > 0

# Use custom backend
backend = S3CheckpointBackend(bucket_name="my-checkpoints")
manager = CheckpointManager(backend=backend)
```

### WorkflowDomainState

State container for workflow execution, used with checkpoints.

```python
from src.compiler.domain_state import WorkflowDomainState

# Create domain state
domain = WorkflowDomainState(
    workflow_id="wf-123",
    input="analyze customer data",
    metadata={"user": "alice", "priority": "high"}
)

# Set stage outputs as workflow progresses
domain.set_stage_output("research", {
    "findings": ["trend1", "trend2"],
    "sources": ["db", "api"]
})

domain.set_stage_output("analysis", {
    "insights": ["insight1", "insight2"],
    "confidence": 0.95
})

# Access stage outputs
print(domain.stage_outputs["research"])  # {"findings": [...], "sources": [...]}

# Serialize for checkpointing
state_dict = domain.to_dict()

# Deserialize from checkpoint
restored_domain = WorkflowDomainState.from_dict(state_dict)
```

### Workflow Resume Example

Complete example showing checkpoint and resume:

```python
from src.compiler.checkpoint_manager import CheckpointManager, CheckpointStrategy
from src.compiler.domain_state import WorkflowDomainState

# Initialize checkpoint manager
manager = CheckpointManager(strategy=CheckpointStrategy.EVERY_STAGE)

# Workflow execution with checkpointing
workflow_id = "long-running-workflow-123"

# Try to resume from checkpoint
if manager.has_checkpoint(workflow_id):
    print(f"Resuming workflow {workflow_id}...")
    domain = manager.load_checkpoint(workflow_id)
    print(f"Resuming from stage: {domain.current_stage}")
    print(f"Completed stages: {list(domain.stage_outputs.keys())}")
else:
    print(f"Starting new workflow {workflow_id}...")
    domain = WorkflowDomainState(
        workflow_id=workflow_id,
        input="process large dataset"
    )

# Execute stages (with automatic checkpointing after each)
stages = ["stage1", "stage2", "stage3"]
for stage in stages:
    # Skip already completed stages
    if stage in domain.stage_outputs:
        print(f"Skipping completed stage: {stage}")
        continue

    print(f"Executing stage: {stage}")
    # Execute stage logic here
    stage_output = {"result": f"output from {stage}"}

    # Update domain state
    domain.set_stage_output(stage, stage_output)

    # Checkpoint saves automatically with EVERY_STAGE strategy
    checkpoint_id = manager.save_checkpoint(domain)
    print(f"Checkpoint saved: {checkpoint_id}")

print("Workflow completed!")
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

Response object returned from agent execution.

**Fields:**
- `output: str` - Final text output from the agent (required)
- `reasoning: Optional[str]` - Extracted reasoning/thought process
- `tool_calls: List[Dict[str, Any]]` - List of tool calls made during execution
- `metadata: Dict[str, Any]` - Additional execution metadata
- `tokens: int` - Total tokens used (prompt + completion)
- `estimated_cost_usd: float` - Estimated cost in USD
- `latency_seconds: float` - Execution time in seconds
- `error: Optional[str]` - Error message if execution failed
- `confidence: Optional[float]` - Confidence score (0.0 to 1.0), auto-calculated if not provided

```python
from src.agents import AgentResponse

# Create response with all fields
response = AgentResponse(
    output="Agent response text",
    reasoning="I analyzed the data and found...",
    tool_calls=[
        {"tool": "calculator", "input": "2+2", "output": "4"}
    ],
    metadata={
        "model": "llama3.2:3b",
        "provider": "ollama"
    },
    tokens=150,
    estimated_cost_usd=0.0001,
    latency_seconds=1.2,
    error=None,
    confidence=0.95
)

# Access fields
print(response.output)  # "Agent response text"
print(response.reasoning)  # "I analyzed the data and found..."
print(response.tokens)  # 150
print(response.confidence)  # 0.95

# Confidence is auto-calculated if not provided
response_auto = AgentResponse(
    output="Result",
    tokens=100,
    latency_seconds=0.8
)
print(response_auto.confidence)  # Auto-calculated based on execution metrics
```

**Confidence Auto-Calculation:**

When `confidence` is not explicitly provided, it's automatically calculated based on:
- Error presence (0.0 if error exists)
- Token usage patterns
- Latency indicators
- Tool call success rates

```python
# Confidence auto-calculated
response = AgentResponse(output="Analysis complete", tokens=200)
# confidence field will be automatically set based on execution metrics
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
- [Execution Engine Architecture](./features/execution/execution_engine_architecture.md)
- [Custom Engine Tutorial](./features/execution/custom_engine_guide.md)
- [Integration Guide](./INTEGRATION.md)
- [Testing Guide](./TESTING.md)
- [Contributing Guide](./CONTRIBUTING.md)

---

For detailed implementation guides and examples, see the `/docs` and `/examples` directories.
