"""Node builder for LangGraph workflow graphs.

Handles creation of execution nodes for stages, with proper configuration
loading and executor delegation.
"""

import logging
from collections.abc import Callable
from typing import Any, cast

from temper_ai.shared.utils.exceptions import WorkflowStageError
from temper_ai.tools.registry import ToolRegistry
from temper_ai.workflow.config_loader import ConfigLoader
from temper_ai.workflow.langgraph_state import LangGraphWorkflowState
from temper_ai.workflow.utils import extract_agent_name

logger = logging.getLogger(__name__)


def _extract_on_stage_failure_policy(workflow_config: Any) -> str:
    """Extract the on_stage_failure policy string from a workflow config.

    Supports both dict-style and object-style workflow configs.
    Defaults to 'halt' when the field is absent.
    """
    if isinstance(workflow_config, dict):
        wf = workflow_config.get("workflow", {})
        eh = wf.get("error_handling", {})
        return eh.get("on_stage_failure", "halt")
    if hasattr(workflow_config, "workflow"):
        wf = workflow_config.workflow
        if hasattr(wf, "error_handling") and wf.error_handling:
            return getattr(wf.error_handling, "on_stage_failure", "halt")
    return "halt"


def _enforce_stage_failure_policy(
    stage_name: str,
    stage_status: str,
    stage_output: dict[str, Any],
    on_stage_failure: str,
) -> None:
    """Enforce on_stage_failure policy for a failed or degraded stage.

    Raises:
        WorkflowStageError: When policy is 'halt'.
    """
    if on_stage_failure == "halt":
        agent_statuses = stage_output.get("agent_statuses", {})
        failed_agents = [
            name
            for name, status in agent_statuses.items()
            if (isinstance(status, dict) and status.get("status") == "failed")
            or status == "failed"
        ]
        label = "all agents failed" if stage_status == "failed" else "degraded"
        raise WorkflowStageError(
            message=(
                f"Stage '{stage_name}' {label} "
                f"({', '.join(failed_agents)}). "
                f"Workflow halted per on_stage_failure='halt' policy."
            ),
            stage_name=stage_name,
        )
    if on_stage_failure == "skip":
        logger.warning(
            "Stage '%s' %s but on_stage_failure='skip'; continuing workflow.",
            stage_name,
            stage_status,
        )


class NodeBuilder:
    """Builds LangGraph nodes for workflow execution.

    Centralizes node creation logic that was previously in LangGraphCompiler.
    Provides clean interface for creating stage nodes with proper executor
    delegation.

    Example:
        >>> builder = NodeBuilder(config_loader, tool_registry, executors)
        >>> stage_node = builder.create_stage_node("research", workflow_config)
        >>> graph.add_node("research", stage_node)
    """

    def __init__(
        self,
        config_loader: ConfigLoader,
        tool_registry: ToolRegistry,
        executors: dict[str, Any],
        tool_executor: Any | None = None,
        context_provider: Any | None = None,
    ) -> None:
        """Initialize node builder.

        Args:
            config_loader: ConfigLoader for loading stage/agent configs
            tool_registry: ToolRegistry for agent tool access
            executors: Dictionary of stage executors (sequential, parallel, adaptive)
            tool_executor: ToolExecutor with safety stack (optional)
            context_provider: Optional ContextProvider for selective input resolution
        """
        self.config_loader = config_loader
        self.tool_registry = tool_registry
        self.executors = executors
        self.tool_executor = tool_executor

        # Inject context_provider into all executors
        if context_provider is not None:
            for executor in executors.values():
                executor.context_provider = context_provider

    def create_stage_node(
        self, stage_name: str, workflow_config: Any
    ) -> Callable[[LangGraphWorkflowState], dict[str, Any]]:
        """Create execution node for a stage.

        Creates a callable node function that loads stage config,
        determines execution mode, and delegates to the appropriate
        executor.

        Args:
            stage_name: Name of the stage
            workflow_config: Workflow configuration (for embedded stage lookup)

        Returns:
            Callable node function for LangGraph (accepts LangGraphWorkflowState, returns dict update)

        Example:
            >>> node = builder.create_stage_node("research", workflow_config)
            >>> graph.add_node("research", node)
        """

        def stage_node(state: Any) -> dict[str, Any]:
            """Execute stage with configured agent mode.

            Args:
                state: Current workflow state (LangGraphWorkflowState dataclass or dict)

            Returns:
                Dict with updates to apply to state

            Raises:
                ValueError: If stage config cannot be loaded
            """
            # Convert to dict for executor (handle both dataclass and plain dict)
            if isinstance(state, dict):
                state_dict = dict(state)
            else:
                state_dict = state.to_typed_dict()

            # Checkpoint resume (R0.6): skip already-completed stages
            resumed = state_dict.get("resumed_stages")
            if resumed and stage_name in resumed:
                logger.info(
                    "Skipping resumed stage '%s' (checkpoint replay)", stage_name
                )
                return {
                    "stage_outputs": state_dict.get("stage_outputs", {}),
                    "current_stage": stage_name,
                }

            # Load stage config
            stage_config = self._load_stage_config(stage_name, workflow_config)

            # Inject input_map from workflow reference into state
            # so InputMapResolver can read it during resolution.
            input_map = self._find_input_map(stage_name, workflow_config)
            if input_map:
                from temper_ai.workflow.context_provider import (
                    _STAGE_INPUT_MAP_KEY,
                )

                state_dict[_STAGE_INPUT_MAP_KEY] = input_map

            # Get execution mode
            agent_mode = self.get_agent_mode(stage_config)

            # Get appropriate executor
            executor = self.executors.get(agent_mode, self.executors["sequential"])

            # Delegate to executor (pass dict, get dict back)
            result_dict = executor.execute_stage(
                stage_name=stage_name,
                stage_config=stage_config,
                state=state_dict,
                config_loader=self.config_loader,
                tool_registry=self.tool_registry,
            )

            # Clean up input_map from state
            state_dict.pop("_stage_input_map", None)

            # Check stage failure and enforce on_stage_failure policy
            self._check_stage_failure(stage_name, result_dict, workflow_config)

            # Return the updated fields as a dict update for LangGraph
            # Executor returns full state dict, we need to return just the updates
            return {
                "stage_outputs": result_dict.get("stage_outputs", {}),
                "current_stage": result_dict.get("current_stage", ""),
            }

        return stage_node

    def _check_stage_failure(
        self,
        stage_name: str,
        result_dict: dict[str, Any],
        workflow_config: Any,
    ) -> None:
        """Check if stage failed and enforce on_stage_failure policy.

        Args:
            stage_name: Name of the stage
            result_dict: Result from executor containing stage_outputs
            workflow_config: Workflow configuration with error_handling settings

        Raises:
            WorkflowStageError: If stage failed and policy is 'halt'
        """
        stage_outputs = result_dict.get("stage_outputs", {})
        stage_output = stage_outputs.get(stage_name, {})
        if not isinstance(stage_output, dict):
            return

        stage_status = stage_output.get("stage_status")
        on_stage_failure = _extract_on_stage_failure_policy(workflow_config)

        # Only "failed" and "degraded" statuses can trigger a halt
        if stage_status not in ("failed", "degraded"):
            return
        # Degraded stages only halt when policy is "halt"
        if stage_status == "degraded" and on_stage_failure != "halt":
            return

        _enforce_stage_failure_policy(
            stage_name, stage_status, stage_output, on_stage_failure
        )

    def _load_stage_config(
        self, stage_name: str, workflow_config: Any
    ) -> dict[str, Any]:
        """Load stage configuration from file or embedded config.

        Args:
            stage_name: Name of the stage
            workflow_config: Workflow configuration

        Returns:
            Stage configuration dictionary

        Raises:
            ValueError: If stage config cannot be found
        """
        try:
            return self.config_loader.load_stage(stage_name)
        except Exception as first_err:
            # Try loading via stage_ref from the workflow config
            stage_ref_path = self._find_stage_ref(stage_name, workflow_config)
            if stage_ref_path:
                try:
                    return self.config_loader.load_stage(stage_ref_path)
                except Exception:
                    pass

            # Stage might be embedded in workflow config
            stage_config = self.find_embedded_stage(stage_name, workflow_config)
            if not stage_config:
                raise ValueError(
                    f"Cannot load stage config: {stage_name}"
                ) from first_err
            return stage_config

    def _find_input_map(
        self, stage_name: str, workflow_config: Any
    ) -> dict[str, str] | None:
        """Extract input_map from workflow stage reference for decoupled I/O.

        Returns the input_map dict if the workflow reference declares one,
        or None if no input_map is configured.
        """
        wf = workflow_config
        if isinstance(wf, dict):
            wf = wf.get("workflow", wf)
        elif hasattr(wf, "workflow"):
            wf = wf.workflow

        stages = (
            wf.get("stages", []) if isinstance(wf, dict) else getattr(wf, "stages", [])
        )
        for entry in stages:
            if isinstance(entry, dict):
                if entry.get("name") == stage_name:
                    im = entry.get("input_map")
                    return im if im else None
            elif hasattr(entry, "name") and entry.name == stage_name:
                im = getattr(entry, "input_map", None)
                return im if im else None
        return None

    def _find_stage_ref(self, stage_name: str, workflow_config: Any) -> str | None:
        """Extract stage config name from stage_ref in the workflow config.

        Converts a stage_ref path like 'configs/stages/research_stage.yaml'
        to the config name 'research_stage' for the config loader.
        """
        from pathlib import Path as _Path

        wf = workflow_config
        if isinstance(wf, dict):
            wf = wf.get("workflow", wf)
        elif hasattr(wf, "workflow"):
            wf = wf.workflow

        stages = (
            wf.get("stages", []) if isinstance(wf, dict) else getattr(wf, "stages", [])
        )
        for entry in stages:
            if isinstance(entry, dict):
                name = entry.get("name", "")
                ref = entry.get("stage_ref", "")
                if name == stage_name and ref:
                    # Extract filename stem: 'configs/stages/research_stage.yaml' -> 'research_stage'
                    return _Path(ref).stem
        return None

    def get_agent_mode(self, stage_config: Any) -> str:
        """Get agent execution mode from stage config.

        Extracts the agent_mode setting from various config formats
        (dict or Pydantic model).

        Args:
            stage_config: Stage configuration

        Returns:
            Agent execution mode: "parallel", "sequential", or "adaptive"
            (defaults to "sequential" if not specified)

        Example:
            >>> mode = builder.get_agent_mode(stage_config)
            >>> # Returns: "parallel", "sequential", or "adaptive"
        """
        # Handle Pydantic model
        if hasattr(stage_config, "stage"):
            execution = getattr(stage_config.stage, "execution", None)
            if execution:
                return getattr(execution, "agent_mode", "sequential")

        # Handle dict — config may be {"stage": {"execution": ...}} or {"execution": ...}
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        inner = stage_dict.get("stage", stage_dict)
        execution = inner.get("execution", {}) if isinstance(inner, dict) else {}
        if isinstance(execution, dict):
            return cast(str, execution.get("agent_mode", "sequential"))

        return "sequential"

    def find_embedded_stage(
        self, stage_name: str, workflow_config: Any
    ) -> dict[str, Any] | None:
        """Find stage config embedded in workflow config.

        Some workflows embed stage configurations directly rather than
        referencing external files. This searches for embedded configs.

        Args:
            stage_name: Stage name to find
            workflow_config: Workflow configuration

        Returns:
            Stage config dict if found, None otherwise
        """
        # Check if stages are embedded in workflow config
        if hasattr(workflow_config, "workflow"):
            stages = workflow_config.workflow.stages
            for stage_ref in stages:
                if (
                    hasattr(stage_ref, "stage_name")
                    and stage_ref.stage_name == stage_name
                ):
                    # For now, return None (embedded configs not fully supported)
                    # Future enhancement: extract embedded config
                    return None

        return None

    def extract_stage_name(self, stage: Any) -> str:
        """Extract stage name from various stage reference formats.

        Handles different ways stages can be referenced:
        - String: "research"
        - Dict: {"name": "research"}
        - Pydantic: stage.name

        Args:
            stage: Stage reference (dict, str, or Pydantic model)

        Returns:
            Stage name

        Raises:
            ValueError: If stage name cannot be extracted

        Example:
            >>> name = builder.extract_stage_name("research")  # "research"
            >>> name = builder.extract_stage_name({"name": "research"})  # "research"
        """
        if isinstance(stage, str):
            return stage
        elif isinstance(stage, dict):
            # Try common key names
            name = (
                stage.get("name") or stage.get("stage_name") or stage.get("stage_ref")
            )
            if name:
                return cast(str, name)
        else:
            # Pydantic model
            name = getattr(stage, "name", None) or getattr(stage, "stage_name", None)
            if name:
                return cast(str, name)

        raise ValueError(f"Cannot extract stage name from: {stage}")

    def wire_dag_context(self, dag: Any) -> None:
        """Pass the built DAG to PredecessorResolver in each executor.

        Called after DAG construction so the resolver knows predecessor
        relationships at execution time.

        Args:
            dag: StageDAG from ``build_stage_dag()``.
        """
        for executor in self.executors.values():
            ctx = getattr(executor, "context_provider", None)
            if ctx is None:
                continue
            # If the context_provider is a SourceResolver, check its fallback
            predecessor = getattr(ctx, "_predecessor", None)
            if predecessor is not None and hasattr(predecessor, "set_dag"):
                predecessor.set_dag(dag)
            # If it's a PredecessorResolver directly
            if hasattr(ctx, "set_dag"):
                ctx.set_dag(dag)

    def extract_agent_name(self, agent_ref: Any) -> str:
        """Extract agent name from various agent reference formats.

        Delegates to shared utility function to avoid code duplication.

        Args:
            agent_ref: Agent reference (dict, str, or Pydantic model)

        Returns:
            Agent name

        Example:
            >>> name = builder.extract_agent_name("analyzer")  # "analyzer"
            >>> name = builder.extract_agent_name({"agent_name": "analyzer"})  # "analyzer"
        """
        return extract_agent_name(agent_ref)


STAGE_TIMEOUT_STATUS = "timeout"
_DEFAULT_TRIGGER_TIMEOUT_SECONDS = 300


def create_event_triggered_node(
    stage_name: str,
    inner_node_fn: Callable,
    event_bus: Any,
    trigger_config: Any,
) -> Callable:
    """Wrap a stage node function to wait for an event trigger before executing.

    Args:
        stage_name: Name of the stage
        inner_node_fn: The original stage node function
        event_bus: TemperEventBus instance
        trigger_config: StageTriggerConfig with event_type, timeout_seconds, etc.

    Returns:
        Wrapped node function that waits for event then runs inner_node_fn
    """

    def event_triggered_node(state: dict) -> dict:
        """Wait for a trigger event before executing the inner stage node."""
        _logger = logging.getLogger(__name__)

        if event_bus is None:
            _logger.warning(
                "Stage '%s' has trigger config but no event_bus in state — running immediately",
                stage_name,
            )
            return inner_node_fn(state)

        event_type = trigger_config.event_type
        timeout = getattr(
            trigger_config, "timeout_seconds", _DEFAULT_TRIGGER_TIMEOUT_SECONDS
        )
        source_filter = getattr(trigger_config, "source_workflow", None)

        _logger.info(
            "Stage '%s' waiting for event '%s' (timeout=%ds)",
            stage_name,
            event_type,
            timeout,
        )

        event_data = event_bus.wait_for_event(
            event_type=event_type,
            timeout_seconds=timeout,
            source_workflow_filter=source_filter,
        )

        if event_data is None:
            _logger.warning(
                "Stage '%s' timed out waiting for event '%s'",
                stage_name,
                event_type,
            )
            state_copy = dict(state)
            state_copy["stage_status"] = STAGE_TIMEOUT_STATUS
            return state_copy

        state_copy = dict(state)
        state_copy["trigger_event"] = event_data
        return inner_node_fn(state_copy)

    return event_triggered_node
