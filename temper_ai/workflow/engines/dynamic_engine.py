"""Dynamic Python execution engine with negotiation support.

Provides DynamicExecutionEngine (ExecutionEngine ABC) and DynamicCompiledWorkflow
(CompiledWorkflow ABC) — a pure-Python alternative to the LangGraph engine.

Key capabilities (captures runtime edge routing, negotiation, dynamic parallelism):
- No compiled graph — uses WorkflowExecutor to walk DAG as a Python loop
- No barrier nodes for fan-in — explicit depth-group synchronization
- Supports stage-to-stage negotiation via ContextResolutionError re-run
- Supports agent-to-agent negotiation via structured markers in output
- Dynamic edge routing (_next_stage signals) for runtime-determined flow
"""

import asyncio
import logging
from typing import Any

from temper_ai.safety.factory import create_safety_stack
from temper_ai.stage.executors import (
    AdaptiveStageExecutor,
    ParallelStageExecutor,
    SequentialStageExecutor,
)
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.registry import ToolRegistry
from temper_ai.workflow.condition_evaluator import ConditionEvaluator
from temper_ai.workflow.config_loader import ConfigLoader
from temper_ai.workflow.engines.workflow_executor import WorkflowExecutor
from temper_ai.workflow.execution_engine import (
    CompiledWorkflow,
    ExecutionEngine,
    ExecutionMode,
    WorkflowCancelledError,
)
from temper_ai.workflow.node_builder import NodeBuilder
from temper_ai.workflow.state_manager import initialize_state

logger = logging.getLogger(__name__)


class DynamicCompiledWorkflow(CompiledWorkflow):
    """Python-native compiled workflow — holds config + executor.

    Unlike LangGraph's compiled Pregel graph, this simply stores the
    WorkflowExecutor and workflow configuration. Execution is a Python loop.
    """

    def __init__(
        self,
        workflow_executor: WorkflowExecutor,
        workflow_config: dict[str, Any],
        stage_refs: list[Any],
    ) -> None:
        self.workflow_executor = workflow_executor
        self.workflow_config = workflow_config
        self.stage_refs = stage_refs
        self._cancelled = False

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute workflow synchronously.

        Args:
            state: Initial workflow state with input data

        Returns:
            Final workflow state with all stage outputs

        Raises:
            WorkflowCancelledError: If workflow was cancelled
        """
        if self._cancelled:
            raise WorkflowCancelledError("Workflow execution cancelled")

        # Ensure core state keys exist (CLI may call invoke directly)
        state.setdefault("stage_outputs", {})
        state.setdefault("current_stage", "")

        return self.workflow_executor.run(
            self.stage_refs,
            self.workflow_config,
            state,
        )

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute workflow asynchronously (runs sync in thread).

        Args:
            state: Initial workflow state with input data

        Returns:
            Final workflow state with all stage outputs

        Raises:
            WorkflowCancelledError: If workflow was cancelled
        """
        if self._cancelled:
            raise WorkflowCancelledError("Workflow execution cancelled")

        return await asyncio.to_thread(
            self.workflow_executor.run,
            self.stage_refs,
            self.workflow_config,
            state,
        )

    def get_metadata(self) -> dict[str, Any]:
        """Get workflow metadata."""
        workflow = self.workflow_config.get("workflow", self.workflow_config)
        stages = workflow.get("stages", [])
        stage_names = self._extract_stage_names(stages)

        return {
            "engine": "dynamic",
            "version": "1.0.0",
            "config": self.workflow_config,
            "stages": stage_names,
        }

    def visualize(self) -> str:
        """Generate Mermaid diagram of workflow."""
        workflow = self.workflow_config.get("workflow", self.workflow_config)
        stages = workflow.get("stages", [])
        stage_names = self._extract_stage_names(stages)

        lines = ["flowchart TD"]
        lines.append("    START([Start])")
        for stage in stage_names:
            lines.append(f"    {stage}[{stage}]")
        lines.append("    END([End])")

        if stage_names:
            lines.append(f"    START --> {stage_names[0]}")
            for i in range(len(stage_names) - 1):
                lines.append(f"    {stage_names[i]} --> {stage_names[i + 1]}")
            lines.append(f"    {stage_names[-1]} --> END")

        return "\n".join(lines)

    def cancel(self) -> None:
        """Cancel workflow execution (cooperative)."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Check if workflow has been cancelled."""
        return self._cancelled

    @staticmethod
    def _extract_stage_names(stages: list[Any]) -> list[str]:
        """Extract stage names from various stage formats."""
        names = []
        for stage in stages:
            if isinstance(stage, str):
                names.append(stage)
            elif isinstance(stage, dict):
                name = stage.get("name") or stage.get("stage_name") or str(stage)
                names.append(name)
            else:
                name = (
                    getattr(stage, "name", None)
                    or getattr(stage, "stage_name", None)
                    or str(stage)
                )
                names.append(name)
        return names


class DynamicExecutionEngine(ExecutionEngine):
    """Dynamic Python execution engine with negotiation support.

    A pure-Python alternative to the LangGraph engine. Uses WorkflowExecutor
    to walk the DAG as a simple Python loop with ThreadPoolExecutor for
    parallel stages.

    Supports all current features (sequential, parallel, conditional,
    loop) plus:
    - Stage-to-stage negotiation (re-run producer on missing input)
    - Agent-to-agent negotiation (structured markers in output)
    - Dynamic edge routing (_next_stage signals)
    - Runtime-determined parallel fan-out

    Args:
        tool_registry: ToolRegistry instance for agent tool access
        config_loader: ConfigLoader instance for loading configs
        tool_executor: Optional ToolExecutor with safety stack
        safety_config_path: Path to action_policies.yaml
        safety_environment: Safety environment (dev/staging/production)
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        config_loader: ConfigLoader | None = None,
        tool_executor: ToolExecutor | None = None,
        safety_config_path: str | None = None,
        safety_environment: str | None = None,
    ) -> None:
        self.tool_registry = tool_registry or ToolRegistry()
        self.config_loader = config_loader or ConfigLoader()

        if tool_executor is None:
            self.tool_executor = create_safety_stack(
                self.tool_registry,
                config_path=safety_config_path,
                environment=safety_environment,
            )
        else:
            self.tool_executor = tool_executor

        self._initialize_components()

    def _initialize_components(self) -> None:
        """Initialize the component hierarchy."""
        from temper_ai.workflow.engines.dynamic_runner import ThreadPoolParallelRunner

        runner = ThreadPoolParallelRunner()

        self.executors = {
            "sequential": SequentialStageExecutor(
                tool_executor=self.tool_executor,
            ),
            "parallel": ParallelStageExecutor(
                parallel_runner=runner,
                tool_executor=self.tool_executor,
            ),
            "adaptive": AdaptiveStageExecutor(
                tool_executor=self.tool_executor,
            ),
        }

        from temper_ai.workflow.context_provider import InputMapResolver

        self.context_provider = InputMapResolver()
        self._predecessor_injection = False

        self.node_builder = NodeBuilder(
            config_loader=self.config_loader,
            tool_registry=self.tool_registry,
            executors=self.executors,
            tool_executor=self.tool_executor,
            context_provider=self.context_provider,
        )

        self.condition_evaluator = ConditionEvaluator()

    def _setup_predecessor_injection(self) -> None:
        """Set up PredecessorResolver as fallback for InputMapResolver.

        Creates a PredecessorResolver and wires it as the fallback in
        InputMapResolver. Stages without explicit inputs will receive
        outputs from DAG predecessors only (not full state).
        """
        from temper_ai.workflow.context_provider import (
            InputMapResolver,
            PredecessorResolver,
        )

        predecessor_resolver = PredecessorResolver()
        self.context_provider = InputMapResolver(fallback=predecessor_resolver)
        self._predecessor_injection = True

        # Re-inject context_provider into all executors
        for executor in self.executors.values():
            executor.context_provider = self.context_provider

    def compile(
        self,
        workflow_config: dict[str, Any],
        on_depth_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> CompiledWorkflow:
        """Compile workflow configuration into dynamic executable form.

        Args:
            workflow_config: Workflow configuration dict
            on_depth_complete: Optional callback invoked after each depth group
                completes. Receives the current workflow state dict.

        Returns:
            DynamicCompiledWorkflow ready for execution

        Raises:
            ValueError: If workflow config is invalid
        """
        # Parse workflow configuration
        workflow = workflow_config.get("workflow", workflow_config)
        stages = workflow.get("stages", [])

        if not stages:
            raise ValueError("Workflow must have at least one stage")

        # Set up predecessor injection if opted in
        if workflow.get("predecessor_injection", False):
            self._setup_predecessor_injection()

        # Set up output extractor
        from temper_ai.workflow.output_extractor import get_extractor

        extractor = get_extractor(workflow_config)
        for executor in self.executors.values():
            executor.output_extractor = extractor

        # Extract negotiation config
        negotiation_config = workflow.get("negotiation", {})

        # Extract max parallel stages from workflow config
        config_section = workflow.get("config", {})
        if isinstance(config_section, dict):
            max_parallel = config_section.get("max_parallel_stages", 4)
        else:
            max_parallel = getattr(config_section, "max_parallel_stages", 4)

        # Create WorkflowExecutor
        workflow_executor = WorkflowExecutor(
            node_builder=self.node_builder,
            condition_evaluator=self.condition_evaluator,
            negotiation_config=negotiation_config,
            on_depth_complete=on_depth_complete,
            max_parallel_workers=max_parallel,
        )

        return DynamicCompiledWorkflow(
            workflow_executor=workflow_executor,
            workflow_config=workflow_config,
            stage_refs=stages,
        )

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC,
    ) -> dict[str, Any]:
        """Execute compiled workflow.

        Args:
            compiled_workflow: DynamicCompiledWorkflow from compile()
            input_data: Input data for workflow execution
            mode: Execution mode (SYNC or ASYNC)

        Returns:
            Final workflow state

        Raises:
            TypeError: If compiled_workflow is wrong type
            NotImplementedError: If mode is STREAM
        """
        if not isinstance(compiled_workflow, DynamicCompiledWorkflow):
            raise TypeError(
                f"Expected DynamicCompiledWorkflow, "
                f"got {type(compiled_workflow).__name__}"
            )

        if mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        # Initialize state
        state = initialize_state(input_data)

        if mode == ExecutionMode.ASYNC:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                raise RuntimeError(
                    "Cannot use execute(mode=ASYNC) from an async context. "
                    "Use 'await engine.async_execute(compiled, data)' instead."
                )
            return asyncio.run(compiled_workflow.ainvoke(state))  # type: ignore[arg-type]

        return compiled_workflow.invoke(state)  # type: ignore[arg-type]

    async def async_execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: dict[str, Any],
        mode: ExecutionMode = ExecutionMode.ASYNC,
    ) -> dict[str, Any]:
        """Execute compiled workflow asynchronously.

        Args:
            compiled_workflow: DynamicCompiledWorkflow from compile()
            input_data: Input data for workflow execution
            mode: Execution mode

        Returns:
            Final workflow state
        """
        if not isinstance(compiled_workflow, DynamicCompiledWorkflow):
            raise TypeError(
                f"Expected DynamicCompiledWorkflow, "
                f"got {type(compiled_workflow).__name__}"
            )

        if mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        state = initialize_state(input_data)

        if mode == ExecutionMode.SYNC:
            return await asyncio.to_thread(
                compiled_workflow.invoke,
                state,  # type: ignore[arg-type]
            )

        return await compiled_workflow.ainvoke(state)  # type: ignore[arg-type]

    def supports_feature(self, feature: str) -> bool:
        """Check if engine supports specific feature.

        The dynamic engine supports all features the LangGraph engine does,
        plus negotiation and dynamic edge routing.

        Args:
            feature: Feature name

        Returns:
            True if feature is supported
        """
        supported = {
            "sequential_stages",
            "parallel_stages",
            "conditional_routing",
            "checkpointing",
            "state_persistence",
            "negotiation",
            "dynamic_routing",
        }
        return feature in supported
