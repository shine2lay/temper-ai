"""Native Python execution engine with negotiation support.

Provides NativeExecutionEngine (ExecutionEngine ABC) and NativeCompiledWorkflow
(CompiledWorkflow ABC) — a pure-Python alternative to the LangGraph engine.

Key differences from LangGraph engine:
- No compiled graph — uses WorkflowExecutor to walk DAG as a Python loop
- No barrier nodes for fan-in — explicit depth-group synchronization
- Supports stage-to-stage negotiation via ContextResolutionError re-run
- Supports agent-to-agent negotiation via structured markers in output
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.workflow.condition_evaluator import ConditionEvaluator
from src.workflow.config_loader import ConfigLoader
from src.workflow.engines.workflow_executor import WorkflowExecutor
from src.workflow.execution_engine import (
    CompiledWorkflow,
    ExecutionEngine,
    ExecutionMode,
    WorkflowCancelledError,
)
from src.stage.executors import (
    AdaptiveStageExecutor,
    ParallelStageExecutor,
    SequentialStageExecutor,
)
from src.workflow.node_builder import NodeBuilder
from src.workflow.state_manager import StateManager
from src.safety.factory import create_safety_stack
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class NativeCompiledWorkflow(CompiledWorkflow):
    """Python-native compiled workflow — holds config + executor.

    Unlike LangGraph's compiled Pregel graph, this simply stores the
    WorkflowExecutor and workflow configuration. Execution is a Python loop.
    """

    def __init__(
        self,
        workflow_executor: WorkflowExecutor,
        workflow_config: Dict[str, Any],
        stage_refs: List[Any],
        state_manager: StateManager,
    ) -> None:
        self.workflow_executor = workflow_executor
        self.workflow_config = workflow_config
        self.stage_refs = stage_refs
        self.state_manager = state_manager
        self._cancelled = False

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
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
            self.stage_refs, self.workflow_config, state,
        )

    async def ainvoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
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
            self.stage_refs, self.workflow_config, state,
        )

    def get_metadata(self) -> Dict[str, Any]:
        """Get workflow metadata."""
        workflow = self.workflow_config.get("workflow", self.workflow_config)
        stages = workflow.get("stages", [])
        stage_names = self._extract_stage_names(stages)

        return {
            "engine": "native",
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
    def _extract_stage_names(stages: List[Any]) -> List[str]:
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


class NativeExecutionEngine(ExecutionEngine):
    """Python-native execution engine with negotiation support.

    A pure-Python alternative to the LangGraph engine. Uses WorkflowExecutor
    to walk the DAG as a simple Python loop with ThreadPoolExecutor for
    parallel stages.

    Supports all current features (sequential, parallel, conditional,
    loop) plus:
    - Stage-to-stage negotiation (re-run producer on missing input)
    - Agent-to-agent negotiation (structured markers in output)

    Args:
        tool_registry: ToolRegistry instance for agent tool access
        config_loader: ConfigLoader instance for loading configs
        tool_executor: Optional ToolExecutor with safety stack
        safety_config_path: Path to action_policies.yaml
        safety_environment: Safety environment (dev/staging/production)
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        config_loader: Optional[ConfigLoader] = None,
        tool_executor: Optional[ToolExecutor] = None,
        safety_config_path: Optional[str] = None,
        safety_environment: Optional[str] = None,
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
        self.state_manager = StateManager()

        # Use ThreadPoolParallelRunner instead of LangGraphParallelRunner
        from src.workflow.engines.native_runner import ThreadPoolParallelRunner
        native_runner = ThreadPoolParallelRunner()

        self.executors = {
            "sequential": SequentialStageExecutor(),
            "parallel": ParallelStageExecutor(parallel_runner=native_runner),
            "adaptive": AdaptiveStageExecutor(),
        }

        from src.workflow.context_provider import SourceResolver
        self.context_provider = SourceResolver()

        self.node_builder = NodeBuilder(
            config_loader=self.config_loader,
            tool_registry=self.tool_registry,
            executors=self.executors,
            tool_executor=self.tool_executor,
            context_provider=self.context_provider,
        )

        self.condition_evaluator = ConditionEvaluator()

    def compile(self, workflow_config: Dict[str, Any]) -> CompiledWorkflow:
        """Compile workflow configuration into native executable form.

        Args:
            workflow_config: Workflow configuration dict

        Returns:
            NativeCompiledWorkflow ready for execution

        Raises:
            ValueError: If workflow config is invalid
        """
        # Parse workflow configuration
        workflow = workflow_config.get("workflow", workflow_config)
        stages = workflow.get("stages", [])

        if not stages:
            raise ValueError("Workflow must have at least one stage")

        # Validate all stage and agent configs (fail fast)
        self._validate_all_configs(stages, workflow_config)

        # Set up output extractor
        from src.workflow.output_extractor import get_extractor
        extractor = get_extractor(workflow_config)
        for executor in self.executors.values():
            executor.output_extractor = extractor

        # Extract negotiation config
        negotiation_config = workflow.get("negotiation", {})

        # Create WorkflowExecutor
        workflow_executor = WorkflowExecutor(
            node_builder=self.node_builder,
            condition_evaluator=self.condition_evaluator,
            state_manager=self.state_manager,
            negotiation_config=negotiation_config,
        )

        return NativeCompiledWorkflow(
            workflow_executor=workflow_executor,
            workflow_config=workflow_config,
            stage_refs=stages,
            state_manager=self.state_manager,
        )

    def execute(
        self,
        compiled_workflow: CompiledWorkflow,
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.SYNC,
    ) -> Dict[str, Any]:
        """Execute compiled workflow.

        Args:
            compiled_workflow: NativeCompiledWorkflow from compile()
            input_data: Input data for workflow execution
            mode: Execution mode (SYNC or ASYNC)

        Returns:
            Final workflow state

        Raises:
            TypeError: If compiled_workflow is wrong type
            NotImplementedError: If mode is STREAM
        """
        if not isinstance(compiled_workflow, NativeCompiledWorkflow):
            raise TypeError(
                f"Expected NativeCompiledWorkflow, "
                f"got {type(compiled_workflow).__name__}"
            )

        if mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        # Initialize state
        state = self.state_manager.initialize_state(input_data)

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
        input_data: Dict[str, Any],
        mode: ExecutionMode = ExecutionMode.ASYNC,
    ) -> Dict[str, Any]:
        """Execute compiled workflow asynchronously.

        Args:
            compiled_workflow: NativeCompiledWorkflow from compile()
            input_data: Input data for workflow execution
            mode: Execution mode

        Returns:
            Final workflow state
        """
        if not isinstance(compiled_workflow, NativeCompiledWorkflow):
            raise TypeError(
                f"Expected NativeCompiledWorkflow, "
                f"got {type(compiled_workflow).__name__}"
            )

        if mode == ExecutionMode.STREAM:
            raise NotImplementedError("STREAM mode not yet supported")

        state = self.state_manager.initialize_state(input_data)

        if mode == ExecutionMode.SYNC:
            return await asyncio.to_thread(
                compiled_workflow.invoke, state,  # type: ignore[arg-type]
            )

        return await compiled_workflow.ainvoke(state)  # type: ignore[arg-type]

    def supports_feature(self, feature: str) -> bool:
        """Check if engine supports specific feature.

        The native engine supports all features the LangGraph engine does,
        plus negotiation.

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
        }
        return feature in supported

    def _validate_all_configs(
        self,
        stages: List[Any],
        workflow_config: Dict[str, Any],
    ) -> None:
        """Validate all stage and agent configs against schemas."""
        errors: list[str] = []
        for stage_ref in stages:
            stage_name = self.node_builder.extract_stage_name(stage_ref)
            stage_config = self._validate_stage_config(
                stage_name, workflow_config, errors,
            )
            if stage_config is not None:
                self._validate_agent_configs_for_stage(
                    stage_config, stage_name, errors,
                )

        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(
                f"  - {err}" for err in errors
            )
            raise ValueError(error_msg)

        logger.info("Configuration validation passed for %d stages", len(stages))

    def _validate_stage_config(
        self,
        stage_name: str,
        workflow_config: Dict[str, Any],
        errors: list,
    ) -> Any:
        """Load and validate a single stage config. Returns config or None."""
        from pydantic import ValidationError

        from src.workflow.constants import ERROR_MSG_STAGE_PREFIX
        from src.stage._schemas import StageConfig

        try:
            stage_config = self.node_builder._load_stage_config(
                stage_name, workflow_config,
            )
        except (FileNotFoundError, ValueError, KeyError) as e:
            errors.append(
                f"{ERROR_MSG_STAGE_PREFIX}{stage_name}': "
                f"Failed to load config - {e}"
            )
            return None

        if isinstance(stage_config, dict):
            try:
                StageConfig(**stage_config)
            except ValidationError as e:
                logger.warning(
                    "%s%s': Config schema warnings - %s",
                    ERROR_MSG_STAGE_PREFIX, stage_name, e,
                )

        return stage_config

    def _validate_agent_configs_for_stage(
        self,
        stage_config: Any,
        stage_name: str,
        errors: list,
    ) -> None:
        """Validate agent configs within a stage."""
        from pydantic import ValidationError

        from src.workflow.constants import ERROR_MSG_AGENT_PREFIX
        from src.workflow.langgraph_compiler import _extract_agents_from_stage
        from src.storage.schemas.agent_config import AgentConfig

        agents = _extract_agents_from_stage(stage_config)
        for agent_ref in agents:
            agent_name = self.node_builder.extract_agent_name(agent_ref)
            try:
                agent_config = self.config_loader.load_agent(agent_name)
            except (FileNotFoundError, ValueError, KeyError) as e:
                errors.append(
                    f"{ERROR_MSG_AGENT_PREFIX}{agent_name}' in stage "
                    f"'{stage_name}': Failed to load config - {e}"
                )
                continue

            if isinstance(agent_config, dict):
                try:
                    AgentConfig(**agent_config)
                except ValidationError as e:
                    logger.warning(
                        "%s%s' in stage '%s': Config schema warnings - %s",
                        ERROR_MSG_AGENT_PREFIX, agent_name, stage_name, e,
                    )
