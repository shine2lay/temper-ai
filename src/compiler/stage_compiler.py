"""Stage compiler for LangGraph workflow graphs.

Handles compilation of stage configurations into executable LangGraph StateGraph.
Separated from main compiler to isolate LangGraph-specific graph construction logic.
"""
from typing import Dict, Any, List, Union
from langgraph.graph import StateGraph, START, END
from langgraph.pregel import Pregel

from src.compiler.langgraph_state import LangGraphWorkflowState
from src.compiler.state_manager import StateManager
from src.compiler.node_builder import NodeBuilder


class StageCompiler:
    """Compiles stage configurations into LangGraph StateGraph.

    Handles the LangGraph-specific graph construction logic:
    - Creating StateGraph instances
    - Adding initialization nodes
    - Adding stage execution nodes
    - Connecting nodes with edges
    - Setting entry points
    - Compiling graphs

    Separated from LangGraphCompiler to isolate graph construction concerns.

    Example:
        >>> stage_compiler = StageCompiler(state_manager, node_builder)
        >>> graph = stage_compiler.compile_stages(stage_names, workflow_config)
    """

    def __init__(
        self,
        state_manager: StateManager,
        node_builder: NodeBuilder
    ) -> None:
        """Initialize stage compiler.

        Args:
            state_manager: StateManager for creating initialization nodes
            node_builder: NodeBuilder for creating stage execution nodes
        """
        self.state_manager = state_manager
        self.node_builder = node_builder

    def compile_stages(
        self,
        stage_names: List[str],
        workflow_config: Dict[str, Any]
    ) -> Pregel[Any, Any]:
        """Compile stage names into executable LangGraph StateGraph.

        Creates a sequential workflow graph with:
        1. START -> init node
        2. init -> first stage
        3. stage[i] -> stage[i+1] (sequential)
        4. last stage -> END

        Args:
            stage_names: List of stage names in execution order
            workflow_config: Full workflow configuration for node creation

        Returns:
            Compiled LangGraph StateGraph ready for execution

        Raises:
            ValueError: If stage_names is empty

        Example:
            >>> graph = compiler.compile_stages(
            ...     ["research", "analysis", "synthesis"],
            ...     workflow_config
            ... )
            >>> result = graph.invoke(initial_state)
        """
        if not stage_names:
            raise ValueError("Cannot compile workflow with no stages")

        # Create state graph with LangGraph-compatible dataclass
        graph: StateGraph[Any] = StateGraph(LangGraphWorkflowState)

        # Add initialization node for workflow state
        init_node = self.state_manager.create_init_node()
        graph.add_node("init", init_node)  # type: ignore[call-overload]

        # Add execution node for each stage
        for stage_name in stage_names:
            stage_node = self.node_builder.create_stage_node(
                stage_name,
                workflow_config
            )
            graph.add_node(stage_name, stage_node)  # type: ignore[call-overload]

        # Add edges for sequential execution
        self._add_sequential_edges(graph, stage_names)

        # Set entry point
        graph.set_entry_point("init")

        # Compile and return
        return graph.compile()

    def _add_sequential_edges(
        self,
        graph: StateGraph[Any],
        stage_names: List[str]
    ) -> None:
        """Add sequential edges connecting stages.

        Creates a linear execution flow:
        START -> init -> stage[0] -> stage[1] -> ... -> stage[n] -> END

        Args:
            graph: StateGraph to add edges to
            stage_names: Ordered list of stage names

        Example:
            For stages ["research", "analysis", "synthesis"]:
            START -> init
            init -> research
            research -> analysis
            analysis -> synthesis
            synthesis -> END
        """
        # Connect START to init
        graph.add_edge(START, "init")

        # Connect init to first stage
        graph.add_edge("init", stage_names[0])

        # Connect stages sequentially
        for i in range(len(stage_names) - 1):
            graph.add_edge(stage_names[i], stage_names[i + 1])

        # Connect last stage to END
        graph.add_edge(stage_names[-1], END)

    def compile_parallel_stages(
        self,
        stage_names: List[str],
        workflow_config: Dict[str, Any]
    ) -> Pregel[Any, Any]:
        """Compile stages with parallel execution support (M3+ feature).

        Future enhancement for parallel stage execution.
        Currently delegates to sequential compilation.

        Args:
            stage_names: List of stage names
            workflow_config: Full workflow configuration

        Returns:
            Compiled StateGraph

        Note:
            This is a placeholder for M3+ parallel stage execution.
            Currently falls back to sequential compilation.
        """
        # TODO M3+: Implement parallel stage execution
        # For now, fall back to sequential
        return self.compile_stages(stage_names, workflow_config)

    def compile_conditional_stages(
        self,
        stage_names: List[str],
        workflow_config: Dict[str, Any],
        conditions: Dict[str, Any]
    ) -> Pregel[Any, Any]:
        """Compile stages with conditional branching (M4+ feature).

        Future enhancement for conditional stage execution based on
        state values or quality gates.

        Args:
            stage_names: List of stage names
            workflow_config: Full workflow configuration
            conditions: Conditional branching rules

        Returns:
            Compiled StateGraph

        Note:
            This is a placeholder for M4+ conditional execution.
            Currently falls back to sequential compilation.
        """
        # TODO M4+: Implement conditional branching
        # For now, fall back to sequential
        return self.compile_stages(stage_names, workflow_config)
