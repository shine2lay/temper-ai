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
from typing import Dict, Any, Optional, Tuple, List
from langgraph.graph import StateGraph

from src.compiler.config_loader import ConfigLoader
from src.compiler.state_manager import StateManager
from src.compiler.node_builder import NodeBuilder
from src.compiler.stage_compiler import StageCompiler
from src.compiler.workflow_executor import WorkflowExecutor
from src.compiler.executors import (
    SequentialStageExecutor,
    ParallelStageExecutor,
    AdaptiveStageExecutor
)
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
        config_loader: Optional[ConfigLoader] = None
    ):
        """Initialize compiler with infrastructure components.

        Args:
            tool_registry: Tool registry for agent tool access
                         (default: creates new ToolRegistry)
            config_loader: Config loader for stage/agent configs
                         (default: creates new ConfigLoader)

        Note:
            All other components (state_manager, executors, node_builder,
            stage_compiler) are created automatically with sensible defaults.
        """
        # Infrastructure components (can be injected)
        self.tool_registry = tool_registry or ToolRegistry()
        self.config_loader = config_loader or ConfigLoader()

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

        # Node builder (depends on config_loader, tool_registry, executors)
        self.node_builder = NodeBuilder(
            config_loader=self.config_loader,
            tool_registry=self.tool_registry,
            executors=self.executors
        )

        # Stage compiler (depends on state_manager, node_builder)
        self.stage_compiler = StageCompiler(
            state_manager=self.state_manager,
            node_builder=self.node_builder
        )

    def compile(self, workflow_config: Dict[str, Any]) -> StateGraph:  # type: ignore[type-arg]
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

        # Step 2: Validate
        if not stages:
            raise ValueError("Workflow must have at least one stage")

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

    def _extract_stage_names(self, stages: list) -> list[str]:  # type: ignore[type-arg]
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
