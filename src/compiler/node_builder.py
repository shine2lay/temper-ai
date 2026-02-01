"""Node builder for LangGraph workflow graphs.

Handles creation of execution nodes for stages, with proper configuration
loading and executor delegation.
"""
from typing import Dict, Any, Callable, Optional, cast
from src.compiler.langgraph_state import LangGraphWorkflowState
from src.compiler.config_loader import ConfigLoader
from src.compiler.utils import extract_agent_name
from src.tools.registry import ToolRegistry


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
        executors: Dict[str, Any]
    ) -> None:
        """Initialize node builder.

        Args:
            config_loader: ConfigLoader for loading stage/agent configs
            tool_registry: ToolRegistry for agent tool access
            executors: Dictionary of stage executors (sequential, parallel, adaptive)
        """
        self.config_loader = config_loader
        self.tool_registry = tool_registry
        self.executors = executors

    def create_stage_node(
        self,
        stage_name: str,
        workflow_config: Any
    ) -> Callable[[LangGraphWorkflowState], Dict[str, Any]]:
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
        def stage_node(state: LangGraphWorkflowState) -> Dict[str, Any]:
            """Execute stage with configured agent mode.

            Args:
                state: Current workflow state (LangGraphWorkflowState dataclass from LangGraph)

            Returns:
                Dict with updates to apply to state

            Raises:
                ValueError: If stage config cannot be loaded
            """
            # Convert to dict for executor
            state_dict = state.to_typed_dict()

            # Load stage config
            stage_config = self._load_stage_config(stage_name, workflow_config)

            # Get execution mode
            agent_mode = self.get_agent_mode(stage_config)

            # Get appropriate executor
            executor = self.executors.get(agent_mode, self.executors['sequential'])

            # Delegate to executor (pass dict, get dict back)
            result_dict = executor.execute_stage(
                stage_name=stage_name,
                stage_config=stage_config,
                state=state_dict,
                config_loader=self.config_loader,
                tool_registry=self.tool_registry
            )

            # Return the updated fields as a dict update for LangGraph
            # Executor returns full state dict, we need to return just the updates
            return {
                "stage_outputs": result_dict.get("stage_outputs", {}),
                "current_stage": result_dict.get("current_stage", "")
            }

        return stage_node

    def _load_stage_config(
        self,
        stage_name: str,
        workflow_config: Any
    ) -> Dict[str, Any]:
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
        except Exception as e:
            # Stage might be embedded in workflow config
            stage_config = self.find_embedded_stage(stage_name, workflow_config)
            if not stage_config:
                raise ValueError(f"Cannot load stage config: {stage_name}") from e
            return stage_config

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
        if hasattr(stage_config, 'stage'):
            execution = getattr(stage_config.stage, 'execution', None)
            if execution:
                return getattr(execution, 'agent_mode', 'sequential')

        # Handle dict
        stage_dict = stage_config if isinstance(stage_config, dict) else {}
        execution = stage_dict.get("execution", {})
        if isinstance(execution, dict):
            return cast(str, execution.get("agent_mode", "sequential"))

        return "sequential"

    def find_embedded_stage(
        self,
        stage_name: str,
        workflow_config: Any
    ) -> Optional[Dict[str, Any]]:
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
        if hasattr(workflow_config, 'workflow'):
            stages = workflow_config.workflow.stages
            for stage_ref in stages:
                if hasattr(stage_ref, 'stage_name') and stage_ref.stage_name == stage_name:
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
            name = stage.get("name") or stage.get("stage_name") or stage.get("stage_ref")
            if name:
                return cast(str, name)
        else:
            # Pydantic model
            name = getattr(stage, 'name', None) or getattr(stage, 'stage_name', None)
            if name:
                return cast(str, name)

        raise ValueError(f"Cannot extract stage name from: {stage}")

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
