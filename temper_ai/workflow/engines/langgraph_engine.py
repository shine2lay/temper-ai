"""LangGraph execution engine adapter.

This module provides an adapter that wraps the existing LangGraphCompiler
behind the ExecutionEngine interface. This enables:
- Vendor independence and flexibility to switch execution engines
- Runtime feature detection for engine capabilities
- Consistent interface across different execution strategies

Design:
- Uses Adapter pattern (composition, not inheritance)
- Wraps existing LangGraphCompiler without modifying it
- Preserves all M2 functionality (tracking, tools, config loading)
"""

import asyncio
from typing import Any, Dict, List, Optional, cast

from temper_ai.workflow.execution_engine import (
    CompiledWorkflow,
    ExecutionEngine,
    ExecutionMode,
    WorkflowCancelledError,
)
from temper_ai.workflow.engines.langgraph_compiler import LangGraphCompiler


class LangGraphCompiledWorkflow(CompiledWorkflow):
    """LangGraph-specific compiled workflow wrapper.

    Wraps a LangGraph StateGraph to present the ExecutionEngine interface.
    This allows the compiled graph to be used through the common interface
    while maintaining all LangGraph-specific functionality.
    """

    def __init__(
        self,
        graph: Any,  # Compiled LangGraph StateGraph
        workflow_config: Dict[str, Any],
        tracker: Any = None
    ) -> None:
        """Initialize compiled workflow.

        Args:
            graph: Compiled LangGraph StateGraph from LangGraphCompiler.compile()
            workflow_config: Original workflow configuration dict
            tracker: Optional ExecutionTracker for observability
        """
        self.graph = graph
        self.workflow_config = workflow_config
        self.tracker = tracker
        self._cancelled = False  # Cancellation flag

    def _extract_stage_names(self, stages: List[Any]) -> List[str]:
        """Extract stage names from various stage formats.

        Handles different stage representations:
        - String: "stage1"
        - Dict: {"name": "stage1"} or {"stage_name": "stage1"}
        - Object: stage.name or stage.stage_name attribute

        Args:
            stages: List of stages in various formats

        Returns:
            List of stage names as strings

        Example:
            >>> stages = ["stage1", {"name": "stage2"}, stage_obj]
            >>> self._extract_stage_names(stages)
            ["stage1", "stage2", "stage3"]
        """
        stage_names = []
        for stage in stages:
            if isinstance(stage, str):
                stage_names.append(stage)
            elif isinstance(stage, dict):
                name = stage.get("name") or stage.get("stage_name") or str(stage)
                stage_names.append(name)
            else:
                # Pydantic model or object
                name = getattr(stage, 'name', None) or getattr(stage, 'stage_name', None) or str(stage)
                stage_names.append(name)
        return stage_names

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow synchronously.

        Args:
            state: Initial workflow state with input data

        Returns:
            Final workflow state with all stage outputs

        Raises:
            ValueError: If state is missing required inputs
            RuntimeError: If workflow execution fails
            WorkflowCancelledError: If workflow was cancelled
        """
        # Check cancellation before execution
        if self._cancelled:
            raise WorkflowCancelledError("Workflow execution cancelled")

        # Prepare state dict with tracker if available
        state_dict = dict(state)  # Create a copy
        if self.tracker:
            state_dict["tracker"] = self.tracker

        # Execute graph (pass dict, validated against LangGraphWorkflowState schema)
        result = self.graph.invoke(state_dict)
        return cast(Dict[str, Any], result)

    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute workflow asynchronously.

        Args:
            state: Initial workflow state with input data

        Returns:
            Final workflow state with all stage outputs

        Raises:
            ValueError: If state is missing required inputs
            RuntimeError: If workflow execution fails
            WorkflowCancelledError: If workflow was cancelled
        """
        # Check cancellation before execution
        if self._cancelled:
            raise WorkflowCancelledError("Workflow execution cancelled")

        # Prepare state dict with tracker if available
        state_dict = dict(state)  # Create a copy
        if self.tracker:
            state_dict["tracker"] = self.tracker

        # Execute graph asynchronously (pass dict, validated against LangGraphWorkflowState schema)
        result = await self.graph.ainvoke(state_dict)
        return cast(Dict[str, Any], result)

    def get_metadata(self) -> Dict[str, Any]:
        """Get workflow metadata.

        Returns:
            Metadata dict with engine info, version, config, and stages

        Example:
            {
                "engine": "langgraph",
                "version": "0.2.0",
                "config": {...},
                "stages": ["stage1", "stage2", "stage3"]
            }
        """
        # Extract workflow section
        workflow = self.workflow_config.get("workflow", self.workflow_config)
        stages = workflow.get("stages", [])

        # Extract stage names using helper method
        stage_names = self._extract_stage_names(stages)

        return {
            "engine": "langgraph",
            "version": "0.2.0",  # LangGraph integration version
            "config": self.workflow_config,
            "stages": stage_names
        }

    def visualize(self) -> str:
        """Generate Mermaid diagram of workflow.

        Returns:
            Mermaid flowchart string representing the workflow graph

        Example:
            flowchart TD
                START([Start])
                research[research]
                synthesis[synthesis]
                END([End])
                START --> research
                research --> synthesis
                synthesis --> END
        """
        # Extract workflow section
        workflow = self.workflow_config.get("workflow", self.workflow_config)
        stages = workflow.get("stages", [])

        # Extract stage names using helper method
        stage_names = self._extract_stage_names(stages)

        # Generate Mermaid flowchart
        lines = ["flowchart TD"]
        lines.append("    START([Start])")

        # Add stage nodes
        for stage in stage_names:
            lines.append(f"    {stage}[{stage}]")

        lines.append("    END([End])")

        # Add edges (sequential for visualization)
        if stage_names:
            lines.append(f"    START --> {stage_names[0]}")
            for i in range(len(stage_names) - 1):
                lines.append(f"    {stage_names[i]} --> {stage_names[i+1]}")
            lines.append(f"    {stage_names[-1]} --> END")

        return "\n".join(lines)

    def cancel(self) -> None:
        """Cancel workflow execution.

        Sets the cancellation flag. Subsequent calls to invoke() or ainvoke()
        will raise WorkflowCancelledError.

        This method is idempotent - calling it multiple times has no effect.

        Note:
            - Cancellation is cooperative and happens before the next execution
            - Currently running executions will complete
            - Future enhancement: interrupt running executions mid-flight
        """
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Check if workflow has been cancelled.

        Returns:
            True if cancel() has been called, False otherwise
        """
        return self._cancelled


class LangGraphExecutionEngine(ExecutionEngine):
    """LangGraph execution engine adapter.

    Wraps LangGraphCompiler to implement ExecutionEngine interface.
    Preserves all existing M2 functionality while enabling future
    engine swapping through the common interface.

    This adapter uses composition (not inheritance) to wrap the
    existing LangGraphCompiler, following the Adapter pattern.
    """

    def __init__(
        self,
        tool_registry: Optional[Any] = None,
        config_loader: Optional[Any] = None
    ) -> None:
        """Initialize engine.

        Args:
            tool_registry: ToolRegistry instance for agent tool access
            config_loader: ConfigLoader instance for loading stage/agent configs
        """
        # Wrap existing LangGraphCompiler
        self.compiler = LangGraphCompiler(
            tool_registry=tool_registry,
            config_loader=config_loader
        )
        self.tool_registry = tool_registry
        self.config_loader = config_loader

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        """Compile workflow configuration into executable form.

        Args:
            workflow_config: Framework-agnostic workflow configuration dict

        Returns:
            LangGraphCompiledWorkflow instance ready for execution

        Raises:
            ValueError: If workflow config is invalid or malformed
            TypeError: If workflow config has wrong structure

        Example:
            >>> engine = LangGraphExecutionEngine()
            >>> compiled = engine.compile(workflow_config)
            >>> result = compiled.invoke({"topic": "Python typing"})
        """
        # Use existing LangGraphCompiler to compile
        graph = self.compiler.compile(workflow_config)

        # Wrap in CompiledWorkflow interface
        return LangGraphCompiledWorkflow(
            graph=graph,
            workflow_config=workflow_config,
            tracker=None  # Tracker passed at execution time
        )

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC
    ) -> Dict[str, Any]:
        """Execute compiled workflow.

        Args:
            compiled_workflow: LangGraphCompiledWorkflow instance from compile()
            input_data: Input data for workflow execution
            mode: Execution mode (SYNC, ASYNC, STREAM). Defaults to SYNC.

        Returns:
            Final workflow state with all stage outputs

        Raises:
            TypeError: If compiled_workflow is not LangGraphCompiledWorkflow
            ValueError: If input_data is missing required fields
            NotImplementedError: If mode is STREAM (not supported in M2)
            RuntimeError: If workflow execution fails

        Example:
            >>> engine = LangGraphExecutionEngine()
            >>> compiled = engine.compile(workflow_config)
            >>> result = engine.execute(compiled, {"topic": "AI"}, ExecutionMode.SYNC)
        """
        # Type check
        if not isinstance(compiled_workflow, LangGraphCompiledWorkflow):
            raise TypeError(
                f"Expected LangGraphCompiledWorkflow, got {type(compiled_workflow).__name__}"
            )

        # Mode check
        if mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        if mode == ExecutionMode.ASYNC:
            # CO-01: asyncio.run() is only safe when no event loop is running.
            # If called from an async context (FastAPI, Jupyter, etc.), raise
            # a clear error directing callers to async_execute() instead.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                raise RuntimeError(
                    "Cannot use execute(mode=ASYNC) from an async context. "
                    "Use 'await engine.async_execute(compiled, data)' instead."
                )
            return asyncio.run(compiled_workflow.ainvoke(input_data))

        # SYNC mode (default)
        return compiled_workflow.invoke(input_data)

    async def async_execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.ASYNC
    ) -> Dict[str, Any]:
        """Execute compiled workflow asynchronously.

        Use from async contexts (FastAPI, Jupyter, pytest-asyncio).

        Args:
            compiled_workflow: Compiled workflow from compile()
            input_data: Input data for the workflow
            mode: ASYNC (default) or SYNC (runs invoke in executor)

        Returns:
            Final workflow state
        """
        if not isinstance(compiled_workflow, LangGraphCompiledWorkflow):
            raise TypeError(
                f"Expected LangGraphCompiledWorkflow, got {type(compiled_workflow).__name__}"
            )

        if mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        if mode == ExecutionMode.SYNC:
            return await asyncio.to_thread(
                compiled_workflow.invoke, input_data
            )

        return await compiled_workflow.ainvoke(input_data)

    def supports_feature(self, feature: str) -> bool:
        """Check if engine supports specific feature.

        Args:
            feature: Feature name (see ExecutionEngine docs for standard features)

        Returns:
            True if feature is supported, False otherwise

        LangGraph Capabilities:
        - Supported: sequential_stages, parallel_stages, conditional_routing,
                    checkpointing, state_persistence
        - Not yet supported: convergence_detection, dynamic_stage_injection,
                             nested_workflows

        Example:
            >>> engine = LangGraphExecutionEngine()
            >>> if engine.supports_feature("parallel_stages"):
            ...     print("Can execute stages in parallel")
        """
        # LangGraph capabilities
        supported = {
            "sequential_stages",      # Sequential execution
            "parallel_stages",        # LangGraph supports parallel branches
            "conditional_routing",    # Conditional edges in LangGraph
            "checkpointing",          # LangGraph memory/checkpointing
            "state_persistence",      # State passed between nodes
        }

        return feature in supported
