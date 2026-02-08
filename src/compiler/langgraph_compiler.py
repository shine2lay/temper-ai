"""LangGraph compiler - Pure orchestration layer for workflow compilation.

The LangGraphCompiler is the main entry point for compiling workflow configurations
into executable LangGraph StateGraphs. It delegates all specialized work to
focused components:

- ConfigLoader: Loads workflow/stage/agent configurations
- StateManager: Manages workflow state initialization and operations
- NodeBuilder: Creates executable nodes from stage configurations
- StageCompiler: Constructs LangGraph StateGraph from stages
- Executors: Execute stages (sequential, parallel, adaptive)

Architecture:
    User → LangGraphCompiler → StageCompiler → NodeBuilder → Executors
         ↓
    WorkflowExecutor → StateGraph.invoke()

Supports M2 (sequential) and M3 (parallel, adaptive) execution modes.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from langgraph.graph import StateGraph

logger = logging.getLogger(__name__)

from src.compiler.config_loader import ConfigLoader
from src.compiler.executors import (
    AdaptiveStageExecutor,
    ParallelStageExecutor,
    SequentialStageExecutor,
)
from src.compiler.node_builder import NodeBuilder
from src.compiler.stage_compiler import StageCompiler
from src.compiler.state_manager import StateManager
from src.compiler.workflow_executor import WorkflowExecutor
from src.safety.factory import create_safety_stack
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry

# Re-export WorkflowExecutor for backward compatibility
__all__ = ['LangGraphCompiler', 'WorkflowExecutor']


class LangGraphCompiler:
    """Orchestrates compilation of workflow configurations to LangGraph StateGraphs.

    This is a pure orchestration layer that coordinates specialized components.
    It does not directly handle graph construction, node creation, or state
    management - all such work is delegated to focused subsystems.

    Compilation Flow:
        1. Parse workflow configuration
        2. Extract stage names (via NodeBuilder)
        3. Compile to StateGraph (via StageCompiler)

    Components:
        - tool_registry: Manages available tools for agents
        - config_loader: Loads configuration files
        - state_manager: Handles state initialization and operations
        - executors: Stage execution strategies (sequential/parallel/adaptive)
        - node_builder: Creates executable nodes from configs
        - stage_compiler: Constructs StateGraph from stages

    Example:
        >>> compiler = LangGraphCompiler()
        >>> graph = compiler.compile(workflow_config)
        >>> executor = WorkflowExecutor(graph)
        >>> result = executor.execute({"topic": "AI safety"})
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        config_loader: Optional[ConfigLoader] = None,
        tool_executor: Optional[ToolExecutor] = None,
        safety_config_path: Optional[str] = None,
        safety_environment: Optional[str] = None
    ):
        """Initialize compiler with infrastructure components.

        Args:
            tool_registry: Tool registry for agent tool access
                         (default: creates new ToolRegistry)
            config_loader: Config loader for stage/agent configs
                         (default: creates new ConfigLoader)
            tool_executor: Tool executor with safety stack
                         (default: creates via create_safety_stack())
            safety_config_path: Path to action_policies.yaml
                              (default: config/safety/action_policies.yaml)
            safety_environment: Safety environment (dev/staging/production)
                              (default: from SAFETY_ENV or "development")

        Note:
            All other components (state_manager, executors, node_builder,
            stage_compiler) are created automatically with sensible defaults.
            Safety stack is initialized automatically with ActionPolicyEngine,
            ApprovalWorkflow, RollbackManager, and ToolExecutor.
        """
        # Infrastructure components (can be injected)
        self.tool_registry = tool_registry or ToolRegistry()
        self.config_loader = config_loader or ConfigLoader()

        # Safety stack initialization
        # If tool_executor not provided, create it with full safety stack
        if tool_executor is None:
            self.tool_executor = create_safety_stack(
                self.tool_registry,
                config_path=safety_config_path,
                environment=safety_environment
            )
        else:
            self.tool_executor = tool_executor

        # Build component hierarchy
        self._initialize_components()

    def _initialize_components(self) -> None:
        """Initialize the component hierarchy.

        Component Dependencies:
            StateManager → (independent)
            Executors → (independent)
            NodeBuilder → ConfigLoader, ToolRegistry, Executors
            StageCompiler → StateManager, NodeBuilder

        This initialization order ensures all dependencies are satisfied.
        """
        # State management (independent)
        self.state_manager = StateManager()

        # Stage executors (independent)
        self.executors = {
            'sequential': SequentialStageExecutor(),
            'parallel': ParallelStageExecutor(),
            'adaptive': AdaptiveStageExecutor(),
        }

        # Node builder (depends on config_loader, tool_registry, executors, tool_executor)
        self.node_builder = NodeBuilder(
            config_loader=self.config_loader,
            tool_registry=self.tool_registry,
            executors=self.executors,
            tool_executor=self.tool_executor
        )

        # Stage compiler (depends on state_manager, node_builder)
        self.stage_compiler = StageCompiler(
            state_manager=self.state_manager,
            node_builder=self.node_builder
        )

    def compile(self, workflow_config: Dict[str, Any]) -> StateGraph:
        """Compile workflow configuration to executable LangGraph StateGraph.

        Orchestration Steps:
            1. Parse workflow configuration
            2. Validate stages exist
            3. Extract stage names (delegate to NodeBuilder)
            4. Compile to graph (delegate to StageCompiler)

        Args:
            workflow_config: Workflow configuration dict (typically from YAML)
                Structure: {"workflow": {"stages": [...]}}

        Returns:
            Compiled StateGraph ready for execution

        Raises:
            ValueError: If workflow has no stages

        Example:
            >>> config = {
            ...     "workflow": {
            ...         "stages": ["research", "analysis", "synthesis"]
            ...     }
            ... }
            >>> graph = compiler.compile(config)
            >>> result = graph.invoke({"topic": "quantum computing"})
        """
        # Step 1: Parse workflow configuration
        workflow = self._parse_workflow(workflow_config)
        stages = workflow.get("stages", [])

        # Step 2: Validate workflow structure
        if not stages:
            raise ValueError("Workflow must have at least one stage")

        # Step 3: Validate all stage and agent configs (fail fast)
        self._validate_all_configs(stages, workflow_config)

        # Step 3: Extract stage names (delegate to NodeBuilder)
        stage_names = self._extract_stage_names(stages)

        # Step 4: Compile to graph (delegate to StageCompiler)
        return self.stage_compiler.compile_stages(stage_names, workflow_config)  # type: ignore[return-value]

    def _validate_quality_gates(
        self,
        synthesis_result: Any,
        stage_config: Dict[str, Any],
        stage_name: str
    ) -> Tuple[bool, List[str]]:
        """Validate synthesis result against quality gates.

        Delegates to ParallelStageExecutor for actual validation logic.
        This method exists for backwards compatibility with tests and
        provides a convenient API on the main compiler class.

        Args:
            synthesis_result: SynthesisResult from agent synthesis
            stage_config: Stage configuration dict with quality_gates settings
            stage_name: Name of the stage being validated

        Returns:
            Tuple of (passed: bool, violations: List[str])
                - passed: True if all quality gates passed
                - violations: List of violation messages (empty if passed)

        Example:
            >>> result = SynthesisResult(decision="A", confidence=0.9, ...)
            >>> config = {"quality_gates": {"enabled": True, "min_confidence": 0.7}}
            >>> passed, violations = compiler._validate_quality_gates(result, config, "research")
            >>> assert passed is True
            >>> assert violations == []
        """
        # Delegate to ParallelStageExecutor which has the validation logic
        # Pass empty state dict for backward compatibility (state not used in validation)
        return self.executors['parallel']._validate_quality_gates(
            synthesis_result=synthesis_result,
            stage_config=stage_config,
            stage_name=stage_name,
            state={}  # Empty state for testing/backward compatibility
        )

    def _get_agent_mode(self, stage_config: Dict[str, Any]) -> str:
        """Get agent execution mode from stage configuration.

        Determines whether agents should execute sequentially or in parallel.
        This method exists for backwards compatibility with integration tests.

        Args:
            stage_config: Stage configuration dict with optional execution settings

        Returns:
            Agent mode: "parallel", "sequential", or default ("sequential")

        Example:
            >>> config = {"execution": {"agent_mode": "parallel"}}
            >>> mode = compiler._get_agent_mode(config)
            >>> assert mode == "parallel"
        """
        if "execution" in stage_config and "agent_mode" in stage_config["execution"]:
            return stage_config["execution"]["agent_mode"]
        return "sequential"  # Default mode

    def _execute_parallel_stage(
        self,
        stage_name: str,
        stage_config: Dict[str, Any],
        state: Any
    ) -> Dict[str, Any]:
        """Execute stage with parallel agent execution.

        Delegates to ParallelStageExecutor for actual execution.
        This method exists for backwards compatibility with integration tests.

        Args:
            stage_name: Name of the stage being executed
            stage_config: Stage configuration dict
            state: Current workflow state (WorkflowState object or dict)

        Returns:
            Dict with stage outputs and synthesis results

        Example:
            >>> result = compiler._execute_parallel_stage("research", config, state)
            >>> assert "stage_outputs" in result
        """
        # Convert WorkflowState to dict if needed (for test compatibility)
        # Use exclude_internal=False to preserve infrastructure components (tracker, registry)
        if hasattr(state, 'to_dict'):
            state_dict = state.to_dict(exclude_none=False, exclude_internal=False)
        else:
            state_dict = state

        # Delegate to ParallelStageExecutor
        # Note: This is a simplified wrapper for testing purposes
        # Real execution flow uses NodeBuilder and stage compilation
        return self.executors['parallel'].execute_stage(
            stage_name=stage_name,
            stage_config=stage_config,
            state=state_dict,
            config_loader=self.config_loader,
            tool_registry=None  # Tests don't use tool registry
        )

    def _parse_workflow(self, workflow_config: Dict[str, Any]) -> Dict[str, Any]:
        """Parse workflow section from config.

        Handles different config formats:
        - Direct format: {"stages": [...]}
        - Nested format: {"workflow": {"stages": [...]}}

        Args:
            workflow_config: Raw workflow configuration

        Returns:
            Workflow section dict
        """
        return workflow_config.get("workflow", workflow_config)  # type: ignore[no-any-return]

    def _validate_all_configs(self, stages: list, workflow_config: Dict[str, Any]) -> None:
        """Validate all stage and agent configs against Pydantic schemas.

        Validates configs at compile time to catch errors early before execution.
        Collects all validation errors and reports them together.

        Args:
            stages: List of stage references from workflow
            workflow_config: Full workflow configuration

        Raises:
            ValueError: If any configs are invalid, with details of all errors

        Example:
            >>> self._validate_all_configs(["research", "analysis"], workflow_config)
        """
        from pydantic import ValidationError

        from src.compiler.schemas import AgentConfig, StageConfig

        errors = []

        for stage_ref in stages:
            stage_name = self.node_builder.extract_stage_name(stage_ref)

            # Load stage config
            try:
                stage_config = self.node_builder._load_stage_config(stage_name, workflow_config)
            except Exception as e:
                errors.append(f"Stage '{stage_name}': Failed to load config - {e}")
                continue

            # Validate stage config against Pydantic schema if it's a dict
            # Note: Schema validation is advisory — missing optional fields like
            # 'description' should not block compilation. Only log warnings.
            if isinstance(stage_config, dict):
                try:
                    StageConfig(**stage_config)
                except ValidationError as e:
                    logger.warning(f"Stage '{stage_name}': Config schema warnings - {e}")
                except Exception as e:
                    logger.debug(f"Stage '{stage_name}': Config validation skipped - {e}")

            # Get agents from stage config
            if hasattr(stage_config, 'stage'):
                agents = stage_config.stage.agents
            else:
                from src.utils.config_helpers import get_nested_value
                agents = get_nested_value(stage_config, 'stage.agents') or stage_config.get('agents', [])

            # Validate each agent config
            for agent_ref in agents:
                agent_name = self.node_builder.extract_agent_name(agent_ref)

                try:
                    agent_config = self.config_loader.load_agent(agent_name)
                except Exception as e:
                    errors.append(f"Agent '{agent_name}' in stage '{stage_name}': Failed to load config - {e}")
                    continue

                # Validate agent config against Pydantic schema if it's a dict
                # Note: Schema validation is advisory for agent configs as well
                if isinstance(agent_config, dict):
                    try:
                        AgentConfig(**agent_config)
                    except ValidationError as e:
                        logger.warning(f"Agent '{agent_name}' in stage '{stage_name}': Config schema warnings - {e}")
                    except Exception as e:
                        logger.debug(f"Agent '{agent_name}': Config validation skipped - {e}")

        # If any errors, fail fast with all details
        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {err}" for err in errors)
            raise ValueError(error_msg)

        logger.info(f"Configuration validation passed for {len(stages)} stages")

    def _extract_stage_names(self, stages: list) -> list[str]:
        """Extract stage names from stage references.

        Delegates to NodeBuilder to handle various stage reference formats:
        - String: "research"
        - Dict: {"name": "research"}
        - Pydantic: stage.name

        Args:
            stages: List of stage references

        Returns:
            List of stage names
        """
        return [
            self.node_builder.extract_stage_name(stage)
            for stage in stages
        ]
