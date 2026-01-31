# Custom Engine Implementation Guide

## Overview

This guide shows how to implement a custom execution engine for the Meta-Autonomous Framework. Custom engines enable:

- Alternative execution strategies (interpreter, actor model, etc.)
- Advanced features like convergence detection (M5+)
- Domain-specific optimizations
- Experimentation with novel execution models

## Prerequisites

- Understanding of `ExecutionEngine` and `CompiledWorkflow` interfaces
- Python 3.11+
- Familiarity with abstract base classes
- Knowledge of workflow configuration schema

## Step-by-Step Implementation

### Step 1: Implement CompiledWorkflow

Create a class that implements the `CompiledWorkflow` interface:

```python
from src.compiler.execution_engine import CompiledWorkflow
from typing import Dict, Any

class MyCompiledWorkflow(CompiledWorkflow):
    """Custom compiled workflow representation."""

    def __init__(self, stages: List[Dict], workflow_config: Dict):
        """
        Initialize with parsed workflow data.

        Args:
            stages: List of stage configurations
            workflow_config: Original workflow config dict
        """
        self.stages = stages
        self.workflow_config = workflow_config
        self.metadata = {
            "engine": "my_engine",
            "version": "1.0.0",
            "config": workflow_config,
            "stages": [s["name"] for s in stages]
        }

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow synchronously."""
        current_state = state.copy()

        # Execute stages in sequence
        stage_outputs = {}
        for stage in self.stages:
            stage_name = stage["name"]
            stage_output = self._execute_stage(stage, current_state)

            # Accumulate outputs
            stage_outputs[stage_name] = stage_output
            current_state.update(stage_output)

        return {
            **current_state,
            "stage_outputs": stage_outputs
        }

    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow asynchronously."""
        import asyncio

        current_state = state.copy()
        stage_outputs = {}

        for stage in self.stages:
            stage_name = stage["name"]
            # Async stage execution
            stage_output = await self._execute_stage_async(stage, current_state)

            stage_outputs[stage_name] = stage_output
            current_state.update(stage_output)

        return {
            **current_state,
            "stage_outputs": stage_outputs
        }

    def get_metadata(self) -> Dict[str, Any]:
        """Return workflow metadata."""
        return self.metadata

    def visualize(self) -> str:
        """Generate Mermaid diagram."""
        lines = ["graph TD"]

        # Add nodes
        for i, stage in enumerate(self.stages):
            stage_name = stage["name"]
            lines.append(f"    {stage_name}[{stage_name}]")

            # Add edge to next stage
            if i < len(self.stages) - 1:
                next_stage = self.stages[i + 1]["name"]
                lines.append(f"    {stage_name} --> {next_stage}")

        return "\n".join(lines)

    def _execute_stage(self, stage: Dict, state: Dict) -> Dict:
        """Execute a single stage (implement your logic here)."""
        # Your stage execution logic
        return {"result": f"Stage {stage['name']} completed"}

    async def _execute_stage_async(self, stage: Dict, state: Dict) -> Dict:
        """Execute a single stage asynchronously."""
        # Your async stage execution logic
        return {"result": f"Stage {stage['name']} completed"}
```

### Step 2: Implement ExecutionEngine

Create a class that implements the `ExecutionEngine` interface:

```python
from src.compiler.execution_engine import ExecutionEngine, ExecutionMode
from typing import Dict, Any

class MyExecutionEngine(ExecutionEngine):
    """Custom execution engine implementation."""

    def __init__(self, tool_registry=None, config_loader=None, **kwargs):
        """
        Initialize engine with dependencies.

        Args:
            tool_registry: Optional ToolRegistry instance
            config_loader: Optional ConfigLoader instance
            **kwargs: Additional engine-specific configuration
        """
        self.tool_registry = tool_registry
        self.config_loader = config_loader
        self.engine_config = kwargs

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        """
        Compile workflow configuration into executable form.

        Args:
            workflow_config: Framework workflow config dict

        Returns:
            MyCompiledWorkflow instance

        Raises:
            ValueError: If config is invalid
        """
        # Extract workflow section
        workflow = workflow_config.get("workflow", workflow_config)

        # Validate config
        self._validate_config(workflow)

        # Parse stages
        stages = workflow.get("stages", [])
        if not stages:
            raise ValueError("Workflow must have at least one stage")

        # Transform stages into executable format
        compiled_stages = []
        for stage_config in stages:
            compiled_stage = self._compile_stage(stage_config)
            compiled_stages.append(compiled_stage)

        # Return compiled workflow
        return MyCompiledWorkflow(compiled_stages, workflow_config)

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Dict[str, Any]:
        """
        Execute compiled workflow.

        Args:
            compiled_workflow: Previously compiled workflow
            input_data: Input data for execution
            mode: Execution mode (SYNC, ASYNC, STREAM)

        Returns:
            Final workflow state

        Raises:
            TypeError: If wrong CompiledWorkflow type
            NotImplementedError: If mode not supported
        """
        # Validate workflow type
        if not isinstance(compiled_workflow, MyCompiledWorkflow):
            raise TypeError(
                f"Expected MyCompiledWorkflow, got {type(compiled_workflow)}"
            )

        # Execute based on mode
        if mode == ExecutionMode.SYNC:
            return compiled_workflow.invoke(input_data)

        elif mode == ExecutionMode.ASYNC:
            import asyncio
            return asyncio.run(compiled_workflow.ainvoke(input_data))

        elif mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        else:
            raise ValueError(f"Unknown execution mode: {mode}")

    def supports_feature(self, feature: str) -> bool:
        """
        Check if engine supports specific feature.

        Args:
            feature: Feature name

        Returns:
            True if supported, False otherwise
        """
        # Define supported features
        supported = {
            "sequential_stages",      # Basic sequential execution
            "parallel_stages",        # Parallel stage execution (if implemented)
            "convergence_detection",  # Your custom feature!
        }

        return feature in supported

    def _validate_config(self, workflow: Dict) -> None:
        """Validate workflow configuration."""
        if "name" not in workflow:
            raise ValueError("Workflow must have a name")

        if "stages" not in workflow:
            raise ValueError("Workflow must have stages")

    def _compile_stage(self, stage_config: Dict) -> Dict:
        """
        Compile a single stage.

        Transform stage config into executable format.
        """
        # Your stage compilation logic
        return {
            "name": stage_config.get("name", "unnamed"),
            "config": stage_config,
            # Add your compiled stage data
        }
```

### Step 3: Register Your Engine

Register your engine with the `EngineRegistry`:

```python
from src.compiler.engine_registry import EngineRegistry

# Get registry instance
registry = EngineRegistry()

# Register your engine
registry.register_engine("my_engine", MyExecutionEngine)

# Now it can be used
engine = registry.get_engine("my_engine", tool_registry=my_registry)
```

### Step 4: Use in Workflow YAML

Select your engine in workflow configuration:

```yaml
workflow:
  name: my_workflow
  engine: my_engine  # Select your custom engine
  engine_config:
    custom_option: value
    max_iterations: 10
  stages:
    - name: research
      stage_ref: research_stage
    - name: synthesis
      stage_ref: synthesis_stage
```

### Step 5: Execute Workflow

Use your engine like any other:

```python
from src.compiler.engine_registry import EngineRegistry
from src.compiler.config_loader import ConfigLoader

# Load config
loader = ConfigLoader()
config = loader.load_workflow("my_workflow")

# Get engine (will use your custom engine based on config)
registry = EngineRegistry()
engine = registry.get_engine_from_config(config)

# Compile and execute
compiled = engine.compile(config)
result = engine.execute(compiled, {"input": "test"})

print(result["stage_outputs"])
```

## Advanced: Convergence Detection Engine

Here's a complete example implementing convergence detection for M5:

```python
from src.compiler.execution_engine import ExecutionEngine, CompiledWorkflow, ExecutionMode
from typing import Dict, Any, List

class ConvergenceCompiledWorkflow(CompiledWorkflow):
    """Workflow with convergence detection."""

    def __init__(self, stages: List[Dict], workflow_config: Dict, convergence_config: Dict):
        self.stages = stages
        self.workflow_config = workflow_config
        self.convergence_config = convergence_config

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute with convergence detection."""
        max_iterations = self.convergence_config.get("max_iterations", 10)
        convergence_threshold = self.convergence_config.get("threshold", 0.95)

        current_state = state.copy()
        iteration = 0
        converged = False

        # Iterate until convergence
        while iteration < max_iterations and not converged:
            iteration += 1

            # Execute all stages
            iteration_outputs = {}
            for stage in self.stages:
                stage_output = self._execute_stage(stage, current_state)
                iteration_outputs[stage["name"]] = stage_output
                current_state.update(stage_output)

            # Check convergence
            if iteration > 1:
                converged = self._check_convergence(
                    iteration_outputs,
                    convergence_threshold
                )

            current_state["iteration"] = iteration
            current_state["converged"] = converged

        return current_state

    def _check_convergence(self, outputs: Dict, threshold: float) -> bool:
        """Check if workflow has converged."""
        # Your convergence detection logic
        # E.g., compare outputs to previous iteration
        # Return True if similarity > threshold
        return False  # Implement your logic

    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Async execution with convergence."""
        # Similar to invoke but async
        pass

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "engine": "convergence_engine",
            "version": "1.0.0",
            "config": self.workflow_config,
            "stages": [s["name"] for s in self.stages],
            "convergence_config": self.convergence_config
        }

    def visualize(self) -> str:
        """Visualize with loop."""
        lines = ["graph TD"]
        lines.append("    Start[Start]")

        for stage in self.stages:
            name = stage["name"]
            lines.append(f"    {name}[{name}]")

        # Add loop
        lines.append("    Start --> research")
        lines.append("    research --> synthesis")
        lines.append("    synthesis --> |not converged| research")
        lines.append("    synthesis --> |converged| End[End]")

        return "\n".join(lines)


class ConvergenceEngine(ExecutionEngine):
    """Engine with convergence detection for M5."""

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        workflow = workflow_config.get("workflow", workflow_config)

        stages = workflow.get("stages", [])
        convergence_config = workflow.get("convergence", {})

        return ConvergenceCompiledWorkflow(stages, workflow_config, convergence_config)

    def execute(self, compiled_workflow, input_data, mode=ExecutionMode.SYNC):
        if not isinstance(compiled_workflow, ConvergenceCompiledWorkflow):
            raise TypeError("Wrong CompiledWorkflow type")

        if mode == ExecutionMode.SYNC:
            return compiled_workflow.invoke(input_data)
        elif mode == ExecutionMode.ASYNC:
            import asyncio
            return asyncio.run(compiled_workflow.ainvoke(input_data))

    def supports_feature(self, feature: str) -> bool:
        supported = {
            "sequential_stages",
            "convergence_detection",  # Our killer feature!
            "nested_workflows",
        }
        return feature in supported
```

## Testing Your Engine

### Unit Tests

```python
import pytest
from src.compiler.execution_engine import ExecutionMode

def test_custom_engine_compile():
    """Test compilation."""
    engine = MyExecutionEngine()

    config = {
        "workflow": {
            "name": "test",
            "stages": [{"name": "stage1"}]
        }
    }

    compiled = engine.compile(config)

    assert isinstance(compiled, MyCompiledWorkflow)
    assert compiled.get_metadata()["engine"] == "my_engine"

def test_custom_engine_execute():
    """Test execution."""
    engine = MyExecutionEngine()

    config = {
        "workflow": {
            "name": "test",
            "stages": [{"name": "stage1"}]
        }
    }

    compiled = engine.compile(config)
    result = engine.execute(compiled, {"input": "test"})

    assert "stage_outputs" in result
    assert "stage1" in result["stage_outputs"]

def test_feature_support():
    """Test feature detection."""
    engine = MyExecutionEngine()

    assert engine.supports_feature("sequential_stages")
    assert not engine.supports_feature("distributed_execution")

def test_async_execution():
    """Test async mode."""
    engine = MyExecutionEngine()

    config = {"workflow": {"name": "test", "stages": [{"name": "stage1"}]}}
    compiled = engine.compile(config)

    result = engine.execute(compiled, {"input": "test"}, mode=ExecutionMode.ASYNC)

    assert "stage_outputs" in result
```

### Integration Tests

```python
def test_custom_engine_with_registry():
    """Test registration and usage."""
    from src.compiler.engine_registry import EngineRegistry

    # Register engine
    registry = EngineRegistry()
    registry.register_engine("my_engine", MyExecutionEngine)

    # Use via registry
    engine = registry.get_engine("my_engine")

    config = {"workflow": {"name": "test", "stages": [{"name": "stage1"}]}}
    compiled = engine.compile(config)
    result = engine.execute(compiled, {"input": "test"})

    assert result is not None

def test_engine_selection_from_config():
    """Test config-based engine selection."""
    from src.compiler.engine_registry import EngineRegistry

    registry = EngineRegistry()
    registry.register_engine("my_engine", MyExecutionEngine)

    config = {
        "workflow": {
            "name": "test",
            "engine": "my_engine",
            "stages": []
        }
    }

    engine = registry.get_engine_from_config(config)

    assert isinstance(engine, MyExecutionEngine)
```

## Common Pitfalls

### 1. Forgetting Async Support

**Problem:** Only implementing `invoke()`, not `ainvoke()`

**Solution:** Always implement both sync and async methods:
```python
def invoke(self, state):
    # Sync implementation
    pass

async def ainvoke(self, state):
    # Async implementation (can call invoke if needed)
    return self.invoke(state)
```

### 2. Missing Type Checks

**Problem:** Not validating `CompiledWorkflow` type in `execute()`

**Solution:** Always check type:
```python
def execute(self, compiled_workflow, input_data, mode):
    if not isinstance(compiled_workflow, MyCompiledWorkflow):
        raise TypeError(f"Expected MyCompiledWorkflow, got {type(compiled_workflow)}")
```

### 3. Incomplete Feature Detection

**Problem:** Claiming to support features you don't implement

**Solution:** Be honest in `supports_feature()`:
```python
def supports_feature(self, feature: str) -> bool:
    # Only return True for actually implemented features
    supported = {
        "sequential_stages",  # Implemented
        # Don't include "parallel_stages" unless you actually support it
    }
    return feature in supported
```

### 4. Breaking Interface Contract

**Problem:** Returning different output structure than expected

**Solution:** Follow the expected output format:
```python
def invoke(self, state):
    return {
        **state,  # Include input state
        "stage_outputs": {  # Add stage outputs
            "stage1": {...},
            "stage2": {...}
        }
    }
```

### 5. Not Handling Execution Modes

**Problem:** Ignoring `ExecutionMode` parameter

**Solution:** Handle all modes or raise NotImplementedError:
```python
def execute(self, compiled_workflow, input_data, mode):
    if mode == ExecutionMode.SYNC:
        return compiled_workflow.invoke(input_data)
    elif mode == ExecutionMode.ASYNC:
        import asyncio
        return asyncio.run(compiled_workflow.ainvoke(input_data))
    elif mode == ExecutionMode.STREAM:
        raise NotImplementedError("STREAM not supported yet")
```

## Performance Tips

### 1. Lazy Compilation

Only compile when configuration changes:
```python
class CachedEngine(ExecutionEngine):
    def __init__(self):
        self._cache = {}

    def compile(self, workflow_config):
        config_hash = hash(str(workflow_config))

        if config_hash not in self._cache:
            self._cache[config_hash] = self._do_compile(workflow_config)

        return self._cache[config_hash]
```

### 2. Reuse Compiled Workflows

Compile once, execute many times:
```python
# Good: compile once
compiled = engine.compile(config)
for input_data in inputs:
    result = engine.execute(compiled, input_data)

# Bad: compile every time
for input_data in inputs:
    compiled = engine.compile(config)  # Wasteful!
    result = engine.execute(compiled, input_data)
```

### 3. Minimize Metadata Overhead

Cache metadata instead of recalculating:
```python
class MyCompiledWorkflow(CompiledWorkflow):
    def __init__(self, stages, config):
        self.stages = stages
        self._metadata = self._build_metadata(stages, config)  # Cache

    def get_metadata(self):
        return self._metadata  # Return cached
```

## Best Practices

1. **Document your engine:** Add docstrings explaining what makes your engine unique
2. **Provide examples:** Show real-world use cases in your documentation
3. **Test thoroughly:** Cover sync, async, and error cases
4. **Be honest about features:** Only claim support for implemented features
5. **Follow interface contracts:** Match expected input/output structures
6. **Handle errors gracefully:** Provide clear error messages
7. **Optimize for common case:** Most workflows are SYNC mode
8. **Version your engine:** Include version in metadata for debugging

## Examples Reference

See complete reference implementations:
- **LangGraph Engine:** `src/compiler/langgraph_engine.py`
- **Convergence Engine:** (above example)
- **Simple Interpreter:** (coming in M5)

## References

- [Execution Engine Architecture](./execution_engine_architecture.md) - Design overview
- [ExecutionEngine Interface](../src/compiler/execution_engine.py) - Abstract base classes
- [Technical Specification](../TECHNICAL_SPECIFICATION.md) - Framework specification
- [Vision Document](../VISION.md) - Long-term vision

---

**Last Updated:** 2026-01-27
**Status:** M2.5 Documentation
**Related:** Execution Engine Architecture, Technical Specification
