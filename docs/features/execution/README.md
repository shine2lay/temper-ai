# Execution Features

Documentation for workflow execution and engine abstraction (M2 & M2.5).

## Features

### [Execution Engine Architecture](./execution_engine_architecture.md)
**Purpose:** Design and architecture of the M2.5 execution engine abstraction layer

**Topics Covered:**
- Why abstraction was needed (decoupling from LangGraph)
- ExecutionEngine interface design
- LangGraph adapter implementation
- Engine registry and factory pattern
- Migration strategy and backward compatibility
- Future extensibility (custom engines, distributed execution)

**Key Benefits:**
- **Decoupling**: Framework independent of specific execution backend
- **Flexibility**: Easy to add new engines (Prefect, Airflow, custom)
- **Testing**: Mock engines for fast testing
- **Optimization**: Engine-specific optimizations without changing workflows
- **Future-Proof**: 41× ROI (1.5 days → 61.5 days saved on migrations)

**Architecture Layers:**
```
Workflow Definition (YAML)
       ↓
WorkflowCompiler
       ↓
ExecutionEngine (abstract)
       ↓
LangGraphAdapter | CustomEngine | MockEngine
       ↓
Actual Execution Backend
```

---

### [Custom Engine Guide](./custom_engine_guide.md)
**Purpose:** Step-by-step guide for building custom execution engines

**Topics Covered:**
- ExecutionEngine interface requirements
- State management strategies
- Workflow compilation and optimization
- Error handling and recovery
- Observability integration
- Testing custom engines
- Performance considerations

**When to Build Custom Engine:**
- Specialized execution requirements (distributed, GPU, etc.)
- Integration with existing orchestration systems
- Domain-specific optimizations
- Research and experimentation

**Example Use Cases:**
- **Distributed Engine**: Execute across multiple machines
- **GPU Engine**: Optimize for GPU-heavy workloads
- **Stream Engine**: Real-time event processing
- **Mock Engine**: Fast testing without real LLM calls

---

## Architecture

### Component Structure
```
ExecutionEngine (interface)
  ├─ compile(workflow_config) → CompiledWorkflow
  ├─ execute(compiled_workflow, input) → result
  └─ validate(workflow_config) → errors

LangGraphAdapter (concrete implementation)
  └─ Adapts LangGraph to ExecutionEngine interface

EngineRegistry
  ├─ register(name, engine_class)
  ├─ get(name) → engine_instance
  └─ list_available() → [names]

WorkflowCompiler
  └─ Uses EngineRegistry to get appropriate engine
```

### Workflow Lifecycle
```
1. Load YAML → WorkflowConfig
2. Select Engine (registry lookup)
3. Validate Config (engine.validate)
4. Compile Workflow (engine.compile)
5. Execute (engine.execute)
6. Track Results (observability)
```

### State Management
Engines handle state differently:
- **LangGraph**: Graph-based state with checkpointing
- **Custom**: Can use any state management approach
- **Requirements**: Must support nested state for stages/agents

---

## Configuration

### Basic Engine Selection
```yaml
# configs/system_config.yaml
execution:
  default_engine: langgraph

engines:
  langgraph:
    checkpointing: true
    interrupt_before: []
    interrupt_after: []
```

### Custom Engine Configuration
```yaml
execution:
  default_engine: my_custom_engine

engines:
  my_custom_engine:
    type: distributed
    workers: 4
    redis_url: redis://localhost:6379
    retry_policy:
      max_attempts: 3
      backoff: exponential
```

### Engine-Specific Features
```yaml
# LangGraph-specific
execution:
  engine: langgraph
  langgraph:
    nested_subgraphs: true
    parallel_execution: true
    max_concurrency: 5

# Custom engine-specific
execution:
  engine: gpu_engine
  gpu_engine:
    device: cuda:0
    batch_size: 32
    precision: fp16
```

---

## Performance

### LangGraph Adapter
- **Overhead**: <10ms per stage
- **Parallel Execution**: 2-3x speedup for multi-agent stages
- **Memory**: O(n) where n = number of stages
- **Checkpointing**: <100ms per checkpoint

### Custom Engine Considerations
- **Compilation Time**: Tradeoff between compilation and execution speed
- **State Overhead**: Choose appropriate state management
- **Observability Cost**: Balance tracking detail vs performance
- **Concurrency**: Consider thread/process pools for parallel execution

---

## Implementation Guide

### 1. Implement Interface
```python
from temper_ai.compiler.execution_engine import ExecutionEngine

class MyCustomEngine(ExecutionEngine):
    def compile(self, workflow_config):
        # Convert workflow config to internal representation
        return CompiledWorkflow(...)

    def execute(self, compiled_workflow, input_data, config=None):
        # Execute the workflow
        return result

    def validate(self, workflow_config):
        # Check for configuration errors
        return []
```

### 2. Register Engine
```python
from temper_ai.compiler.engine_registry import EngineRegistry

EngineRegistry.register("my_custom_engine", MyCustomEngine)
```

### 3. Configure and Use
```yaml
# configs/system_config.yaml
execution:
  default_engine: my_custom_engine
```

### 4. Test Engine
```python
def test_custom_engine():
    engine = MyCustomEngine({})
    workflow_config = load_config("test_workflow.yaml")

    # Validate
    errors = engine.validate(workflow_config)
    assert len(errors) == 0

    # Compile
    compiled = engine.compile(workflow_config)

    # Execute
    result = engine.execute(compiled, {"input": "test"})
    assert result["status"] == "success"
```

---

## Examples

### Using LangGraph Engine (Default)
```python
from temper_ai.compiler import WorkflowCompiler

# Automatically uses LangGraph
workflow = WorkflowCompiler.from_file("workflow.yaml")
result = workflow.execute({"task": "Research TypeScript"})
```

### Switching to Custom Engine
```python
from temper_ai.compiler.engine_registry import EngineRegistry
from my_engines import DistributedEngine

# Register custom engine
EngineRegistry.register("distributed", DistributedEngine)

# Use custom engine
workflow = WorkflowCompiler.from_file(
    "workflow.yaml",
    engine_name="distributed"
)
result = workflow.execute({"task": "Large-scale analysis"})
```

### Mock Engine for Testing
```python
from temper_ai.compiler.engine_registry import EngineRegistry
from tests.mocks import MockEngine

# Use mock engine (no real LLM calls)
EngineRegistry.register("mock", MockEngine)

workflow = WorkflowCompiler.from_file(
    "workflow.yaml",
    engine_name="mock"
)
result = workflow.execute({"task": "test"})  # Fast, deterministic
```

---

## Testing

See execution engine tests:
- `tests/test_compiler/test_execution_engine.py` - Interface tests
- `tests/test_compiler/test_langgraph_adapter.py` - LangGraph adapter tests
- `tests/test_compiler/test_engine_registry.py` - Registry tests
- `tests/integration/test_engine_switching.py` - Engine switching tests

---

## Migration Guide

### From Direct LangGraph Usage
**Before:**
```python
from temper_ai.compiler.langgraph_compiler import LangGraphCompiler

compiler = LangGraphCompiler(workflow_config)
result = compiler.compile_and_run(input_data)
```

**After:**
```python
from temper_ai.compiler import WorkflowCompiler

# Uses LangGraph via abstraction
workflow = WorkflowCompiler.from_config(workflow_config)
result = workflow.execute(input_data)
```

### Adding Deprecation Warnings
Old code continues to work but shows deprecation warning:
```python
# Still works, with warning
from temper_ai.compiler.langgraph_compiler import LangGraphCompiler
# DeprecationWarning: Use WorkflowCompiler instead
```

---

## Related Documentation

- [Collaboration Features](../collaboration/) - Multi-agent collaboration
- [Observability Features](../observability/) - Execution tracking
- [Core Interfaces](../../interfaces/core/) - Agent, Tool, LLM interfaces
- [Milestone 2 Report](../../milestones/milestone2_completion.md) - M2 completion
- [Milestone 2.5 Report](../../milestones/milestone2.5_completion.md) - M2.5 completion
