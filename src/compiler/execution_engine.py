"""Abstract execution engine interface for workflow compilation and execution.

This module provides the foundation interface that decouples the framework from
specific graph execution libraries (like LangGraph). It enables:
- Vendor independence and flexibility to switch execution engines
- Experimentation with alternative execution strategies
- Runtime feature detection for engine capabilities

Design Philosophy:
- Adapter pattern (not inheritance) - wrap existing implementations
- Feature detection via supports_feature() - runtime capability checking
- Separate CompiledWorkflow class - allows engine-specific representations
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Iterator
from enum import Enum


class WorkflowCancelledError(Exception):
    """Exception raised when a workflow is cancelled during execution.

    This exception indicates that the workflow was cancelled explicitly
    via the cancel() method, not due to an error or failure.
    """
    pass


class ExecutionMode(Enum):
    """Execution mode for workflows.

    Attributes:
        SYNC: Synchronous execution (blocking)
        ASYNC: Asynchronous execution (non-blocking)
        STREAM: Streaming execution (yields intermediate results)
    """
    SYNC = "sync"
    ASYNC = "async"
    STREAM = "stream"


class CompiledWorkflow(ABC):
    """Abstract compiled workflow representation.

    This allows different engines to have different internal representations
    while presenting a common interface for execution.

    Implementations should store the compiled workflow in their native format
    (e.g., LangGraph StateGraph, custom IR, etc.) and translate between the
    common interface and engine-specific execution.
    """

    @abstractmethod
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow synchronously.

        Args:
            state: Initial workflow state with input data. Should contain
                   all required inputs for the workflow's entry stage.

        Returns:
            Final workflow state with all stage outputs. The returned dict
            includes both input data and outputs from all executed stages.

        Raises:
            ValueError: If state is missing required inputs
            RuntimeError: If workflow execution fails
        """
        pass

    @abstractmethod
    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow asynchronously.

        Args:
            state: Initial workflow state with input data. Should contain
                   all required inputs for the workflow's entry stage.

        Returns:
            Final workflow state with all stage outputs. The returned dict
            includes both input data and outputs from all executed stages.

        Raises:
            ValueError: If state is missing required inputs
            RuntimeError: If workflow execution fails
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """Get workflow metadata.

        Returns:
            Metadata dict with keys:
            - engine: str (engine name, e.g., "langgraph", "custom")
            - version: str (engine version)
            - config: Dict (original workflow configuration)
            - stages: List[str] (stage names in execution order)

        Example:
            {
                "engine": "langgraph",
                "version": "0.2.0",
                "config": {...},
                "stages": ["stage1", "stage2", "stage3"]
            }
        """
        pass

    @abstractmethod
    def visualize(self) -> str:
        """Generate visual representation of workflow.

        Returns:
            String representation of the workflow graph. Format depends on
            the engine implementation (Mermaid, DOT, ASCII art, etc.).

        Example:
            "graph TD\\n  A[stage1] --> B[stage2]\\n  B --> C[stage3]"
        """
        pass

    @abstractmethod
    def cancel(self) -> None:
        """Cancel workflow execution.

        Cancels the currently running workflow execution. The workflow will
        complete the current stage/operation before stopping gracefully.

        This method is idempotent - calling it multiple times has no effect.

        Raises:
            WorkflowCancelledError: During subsequent invoke/ainvoke calls

        Note:
            - Cancellation is cooperative - the running workflow must check
              the cancellation flag periodically
            - Any invoke() or ainvoke() call after cancellation will raise
              WorkflowCancelledError
            - Resources are cleaned up automatically
        """
        pass

    @abstractmethod
    def is_cancelled(self) -> bool:
        """Check if workflow has been cancelled.

        Returns:
            True if cancel() has been called, False otherwise
        """
        pass


class ExecutionEngine(ABC):
    """Abstract execution engine interface.

    This interface decouples workflow execution from specific graph libraries.
    Implementations can use LangGraph, custom interpreters, actor models,
    Temporal workflows, or any other execution strategy.

    The two-phase design (compile then execute) allows:
    1. Validation and optimization during compilation
    2. Reuse of compiled workflows across multiple executions
    3. Serialization of compiled workflows for distributed execution
    """

    @abstractmethod
    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        """Compile workflow configuration into executable form.

        This phase validates the workflow configuration, performs any necessary
        optimizations, and produces an executable representation.

        Args:
            workflow_config: Framework-agnostic workflow configuration dict.
                            Should conform to the meta-autonomous-framework
                            workflow schema (stages, transitions, etc.).

        Returns:
            CompiledWorkflow ready for execution. The compiled form is
            engine-specific but presents a common interface.

        Raises:
            ValueError: If workflow config is invalid or malformed
            TypeError: If workflow config has wrong structure

        Example workflow_config:
            {
                "name": "my_workflow",
                "stages": [...],
                "transitions": [...]
            }
        """
        pass

    @abstractmethod
    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Dict[str, Any]:
        """Execute compiled workflow.

        Args:
            compiled_workflow: Previously compiled workflow from compile()
            input_data: Input data for workflow execution. Should contain
                       all required inputs for the workflow's entry stage.
            mode: Execution mode (SYNC, ASYNC, STREAM). Defaults to SYNC.

        Returns:
            Final workflow state with all stage outputs. For SYNC and ASYNC modes,
            returns the complete final state. For STREAM mode, returns the final
            state after all intermediate states have been processed. Structure
            matches the return value of CompiledWorkflow.invoke().

        Raises:
            TypeError: If compiled_workflow is wrong type for this engine
            ValueError: If input_data is missing required fields
            NotImplementedError: If execution mode not supported by engine
            RuntimeError: If workflow execution fails

        Note:
            STREAM mode behavior is engine-specific. Some engines may provide
            intermediate states through callbacks, separate streaming methods,
            or context managers. This method always returns the final state
            regardless of execution mode. Consult engine documentation for
            streaming-specific APIs.
        """
        pass

    @abstractmethod
    async def async_execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.ASYNC
    ) -> Dict[str, Any]:
        """Execute compiled workflow asynchronously.

        Use this method when calling from an async context (FastAPI, Jupyter,
        pytest-asyncio, etc.) instead of ``execute(mode=ASYNC)``.

        Args:
            compiled_workflow: Previously compiled workflow from compile()
            input_data: Input data for workflow execution
            mode: Execution mode (ASYNC or SYNC). Defaults to ASYNC.
                  When SYNC is requested, runs synchronously via
                  ``run_in_executor``.

        Returns:
            Final workflow state

        Raises:
            TypeError: If compiled_workflow is wrong type for this engine
            NotImplementedError: If execution mode not supported
        """
        pass

    @abstractmethod
    def supports_feature(self, feature: str) -> bool:
        """Check if engine supports specific feature.

        This enables runtime capability checking, allowing the framework to
        adapt behavior based on engine capabilities or provide helpful error
        messages when features aren't available.

        Args:
            feature: Feature name. Standard features include:
                - "sequential_stages": Sequential stage execution
                - "parallel_stages": Parallel stage execution
                - "conditional_routing": Conditional transitions based on state
                - "convergence_detection": Detect and handle stage convergence
                - "dynamic_stage_injection": Add stages at runtime
                - "nested_workflows": Workflows that call other workflows
                - "checkpointing": Save/restore execution state
                - "state_persistence": Persist state to external storage
                - "streaming_execution": Stream intermediate results
                - "distributed_execution": Execute across multiple nodes

        Returns:
            True if feature is supported, False otherwise

        Example:
            if engine.supports_feature("parallel_stages"):
                # Use parallel execution
            else:
                # Fall back to sequential
        """
        pass
