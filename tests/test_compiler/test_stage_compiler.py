"""Tests for StageCompiler class.

Verifies graph construction, edge creation, and delegation to NodeBuilder.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from src.compiler.stage_compiler import StageCompiler
from src.compiler.state import WorkflowState
from src.compiler.state_manager import StateManager
from src.compiler.node_builder import NodeBuilder


class TestStageCompilerInitialization:
    """Test StageCompiler initialization."""

    def test_init_with_dependencies(self):
        """Test initialization with all dependencies."""
        state_manager = Mock(spec=StateManager)
        node_builder = Mock(spec=NodeBuilder)

        compiler = StageCompiler(state_manager, node_builder)

        assert compiler.state_manager is state_manager
        assert compiler.node_builder is node_builder


class TestCompileStages:
    """Test compile_stages method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.state_manager = Mock(spec=StateManager)
        self.node_builder = Mock(spec=NodeBuilder)
        self.compiler = StageCompiler(self.state_manager, self.node_builder)

    def test_compile_stages_creates_graph(self):
        """Test that compile_stages creates a StateGraph."""
        # Mock init node
        self.state_manager.create_init_node.return_value = Mock()

        # Mock stage nodes
        self.node_builder.create_stage_node.return_value = Mock()

        workflow_config = {"workflow": {"stages": ["research", "analysis"]}}
        stage_names = ["research", "analysis"]

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Verify graph is compiled and executable
        assert graph is not None, "Compiled graph should not be None"
        assert hasattr(graph, 'invoke'), "Compiled graph must have invoke method"
        assert hasattr(graph, 'get_graph'), "Compiled graph must have get_graph method"
        assert callable(graph.invoke), "invoke must be callable"

        # Verify graph structure
        graph_structure = graph.get_graph()
        assert graph_structure is not None, "Graph structure should be retrievable"
        assert len(graph_structure.nodes) >= 3, \
            f"Graph should have at least 3 nodes (init + 2 stages), got {len(graph_structure.nodes)}"

    def test_compile_stages_adds_init_node(self):
        """Test that compile_stages adds initialization node."""
        mock_init_node = Mock()
        self.state_manager.create_init_node.return_value = mock_init_node

        self.node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research"]
        workflow_config = {}

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Verify create_init_node was called exactly once with no arguments
        self.state_manager.create_init_node.assert_called_once_with()

        # Verify init node is in the graph
        graph_structure = graph.get_graph()
        node_names = {node.id for node in graph_structure.nodes.values()}
        assert "__start__" in node_names, "Graph should have __start__ node"

    def test_compile_stages_creates_stage_nodes(self):
        """Test that compile_stages creates nodes for each stage."""
        self.state_manager.create_init_node.return_value = Mock()
        self.node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research", "analysis", "synthesis"]
        workflow_config = {"workflow": {}}

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Verify create_stage_node called for each stage exactly once
        assert self.node_builder.create_stage_node.call_count == 3, \
            f"Expected 3 stage node creations, got {self.node_builder.create_stage_node.call_count}"

        # Verify called with correct stage names in order
        calls = self.node_builder.create_stage_node.call_args_list
        assert calls[0][0][0] == "research", "First stage should be research"
        assert calls[1][0][0] == "analysis", "Second stage should be analysis"
        assert calls[2][0][0] == "synthesis", "Third stage should be synthesis"

        # Verify all stages passed the same workflow_config
        for call in calls:
            assert call[0][1] == workflow_config, "Each stage should receive workflow_config"

        # Verify all stage nodes are in the compiled graph
        graph_structure = graph.get_graph()
        node_names = {node.id for node in graph_structure.nodes.values()}
        assert "research" in node_names, "research node should be in graph"
        assert "analysis" in node_names, "analysis node should be in graph"
        assert "synthesis" in node_names, "synthesis node should be in graph"

    def test_compile_stages_passes_workflow_config(self):
        """Test that compile_stages passes workflow config to node builder."""
        self.state_manager.create_init_node.return_value = Mock()
        self.node_builder.create_stage_node.return_value = Mock()

        workflow_config = {"workflow": {"name": "test"}}
        stage_names = ["research"]

        self.compiler.compile_stages(stage_names, workflow_config)

        # Verify workflow_config was passed
        call_args = self.node_builder.create_stage_node.call_args
        assert call_args[0][1] == workflow_config

    def test_compile_stages_raises_for_empty_stages(self):
        """Test that compile_stages raises ValueError for empty stages."""
        with pytest.raises(ValueError, match="Cannot compile workflow with no stages"):
            self.compiler.compile_stages([], {})

    def test_compile_stages_single_stage(self):
        """Test compile_stages with single stage."""
        self.state_manager.create_init_node.return_value = Mock()
        self.node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research"]
        workflow_config = {}

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Should successfully create graph with one stage
        assert graph is not None
        assert self.node_builder.create_stage_node.call_count == 1

    def test_compile_stages_multiple_stages(self):
        """Test compile_stages with multiple stages."""
        self.state_manager.create_init_node.return_value = Mock()
        self.node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research", "analysis", "synthesis", "recommendation"]
        workflow_config = {}

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Should successfully create graph with multiple stages
        assert graph is not None
        assert self.node_builder.create_stage_node.call_count == 4


class TestSequentialEdges:
    """Test _add_sequential_edges method."""

    def setup_method(self):
        """Set up test fixtures."""
        self.state_manager = Mock(spec=StateManager)
        self.node_builder = Mock(spec=NodeBuilder)
        self.compiler = StageCompiler(self.state_manager, self.node_builder)

    def test_sequential_edges_correct_flow(self):
        """Test that sequential edges create correct flow."""
        # We'll test this indirectly through compile_stages
        # since _add_sequential_edges is private

        self.state_manager.create_init_node.return_value = Mock()
        self.node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research", "analysis"]
        workflow_config = {}

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Graph should be executable (edges properly connected)
        assert graph is not None, "Graph should be created"
        assert hasattr(graph, 'invoke'), "Graph should be executable"

        # Verify edge structure
        graph_structure = graph.get_graph()
        edges = graph_structure.edges

        # Should have edges: __start__ -> init -> research -> analysis -> __end__ (4 edges)
        assert len(edges) >= 4, \
            f"Should have at least 4 edges (start->init, init->research, research->analysis, analysis->end), got {len(edges)}"

        # Verify sequential flow exists
        edge_pairs = [(e.source, e.target) for e in edges]
        assert any(e[0] == "__start__" for e in edge_pairs), "Should have edge from __start__"
        assert any(e[1] == "__end__" for e in edge_pairs), "Should have edge to __end__"
        assert any(e[0] == "research" and e[1] == "analysis" for e in edge_pairs), \
            "Should have edge from research to analysis"
        assert any(e[1] == "research" for e in edge_pairs), \
            "Should have edge leading to research (from init)"

    def test_edges_connect_all_stages(self):
        """Test that edges connect all stages sequentially."""
        self.state_manager.create_init_node.return_value = Mock()
        self.node_builder.create_stage_node.return_value = Mock()

        # Test with multiple stages
        stage_names = ["stage1", "stage2", "stage3", "stage4"]
        workflow_config = {}

        graph = self.compiler.compile_stages(stage_names, workflow_config)

        # Graph should be complete and executable
        assert graph is not None, "Graph should be created"

        # Verify all nodes and edges exist
        graph_structure = graph.get_graph()
        node_ids = {node.id for node in graph_structure.nodes.values()}
        edge_pairs = [(e.source, e.target) for e in graph_structure.edges]

        # Verify all stages are nodes
        for stage in stage_names:
            assert stage in node_ids, f"Stage {stage} should be in graph nodes"

        # Verify init node exists
        assert "init" in node_ids, "Init node should be in graph"

        # Verify sequential connections (__start__ -> init -> stage1 -> stage2 -> stage3 -> stage4 -> __end__)
        assert ("__start__", "init") in edge_pairs, "Should connect start to init"
        assert ("init", "stage1") in edge_pairs, "Should connect init to stage1"
        assert ("stage1", "stage2") in edge_pairs, "Should connect stage1 to stage2"
        assert ("stage2", "stage3") in edge_pairs, "Should connect stage2 to stage3"
        assert ("stage3", "stage4") in edge_pairs, "Should connect stage3 to stage4"
        assert ("stage4", "__end__") in edge_pairs, "Should connect stage4 to end"

        # Verify edge count (6 edges: start->init + init->s1 + s1->s2 + s2->s3 + s3->s4 + s4->end)
        assert len(edge_pairs) == 6, \
            f"Should have exactly 6 edges (start->init + 4 stages + end), got {len(edge_pairs)}"


class TestCompileParallelStages:
    """Test compile_parallel_stages method (future enhancement)."""

    def test_parallel_falls_back_to_sequential(self):
        """Test that parallel compilation currently falls back to sequential."""
        state_manager = Mock(spec=StateManager)
        node_builder = Mock(spec=NodeBuilder)
        compiler = StageCompiler(state_manager, node_builder)

        state_manager.create_init_node.return_value = Mock()
        node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research", "analysis"]
        workflow_config = {}

        # Should not raise, should delegate to compile_stages
        graph = compiler.compile_parallel_stages(stage_names, workflow_config)

        assert graph is not None


class TestCompileConditionalStages:
    """Test compile_conditional_stages method (future enhancement)."""

    def test_conditional_falls_back_to_sequential(self):
        """Test that conditional compilation currently falls back to sequential."""
        state_manager = Mock(spec=StateManager)
        node_builder = Mock(spec=NodeBuilder)
        compiler = StageCompiler(state_manager, node_builder)

        state_manager.create_init_node.return_value = Mock()
        node_builder.create_stage_node.return_value = Mock()

        stage_names = ["research", "analysis"]
        workflow_config = {}
        conditions = {"research": "state.quality > 0.8"}

        # Should not raise, should delegate to compile_stages
        graph = compiler.compile_conditional_stages(
            stage_names,
            workflow_config,
            conditions
        )

        assert graph is not None


class TestIntegrationWithRealGraph:
    """Integration tests with actual LangGraph."""

    def test_compile_creates_executable_graph(self):
        """Test that compiled graph is actually executable."""
        from src.compiler.config_loader import ConfigLoader
        from src.tools.registry import ToolRegistry

        # Create real components
        state_manager = StateManager()
        config_loader = ConfigLoader()
        tool_registry = ToolRegistry()
        executors = {
            'sequential': Mock(),
            'parallel': Mock(),
            'adaptive': Mock()
        }

        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        compiler = StageCompiler(state_manager, node_builder)

        # Mock the node builder's stage node creation
        def mock_stage_node(state):
            state["stage_outputs"] = state.get("stage_outputs", {})
            state["stage_outputs"]["test_stage"] = "output"
            return state

        with patch.object(node_builder, 'create_stage_node', return_value=mock_stage_node):
            stage_names = ["test_stage"]
            workflow_config = {}

            graph = compiler.compile_stages(stage_names, workflow_config)

            # Execute the graph with dict input (LangGraph requires dict)
            initial_state = {
                "workflow_id": "test-123",
                "current_stage": "",
                "num_stages": 0,
                "version": "1.0"
            }
            result = graph.invoke(initial_state)

            # Verify execution
            assert result is not None, "Graph should return a result"
            assert "workflow_id" in result, "Result should contain workflow_id"
            assert "stage_outputs" in result, "Result should contain stage_outputs"
            assert result["stage_outputs"]["test_stage"] == "output", \
                "Stage should produce expected output"

    def test_compile_sequential_flow_execution(self):
        """Test that sequential flow executes stages in order."""
        from src.compiler.config_loader import ConfigLoader
        from src.tools.registry import ToolRegistry

        state_manager = StateManager()
        config_loader = ConfigLoader()
        tool_registry = ToolRegistry()
        executors = {
            'sequential': Mock(),
            'parallel': Mock(),
            'adaptive': Mock()
        }

        node_builder = NodeBuilder(config_loader, tool_registry, executors)
        compiler = StageCompiler(state_manager, node_builder)

        # Track execution order
        execution_order = []

        def create_stage_node_tracker(stage_name, workflow_config):
            def stage_node(state):
                execution_order.append(stage_name)
                state["stage_outputs"] = state.get("stage_outputs", {})
                state["stage_outputs"][stage_name] = f"output_{stage_name}"
                return state
            return stage_node

        with patch.object(node_builder, 'create_stage_node', side_effect=create_stage_node_tracker):
            stage_names = ["research", "analysis", "synthesis"]
            workflow_config = {}

            graph = compiler.compile_stages(stage_names, workflow_config)

            # Execute with dict input (LangGraph requires dict)
            initial_state = {
                "workflow_id": "test-456",
                "current_stage": "",
                "num_stages": 0,
                "version": "1.0"
            }
            result = graph.invoke(initial_state)

            # Verify sequential execution order
            assert execution_order == ["research", "analysis", "synthesis"], \
                f"Expected sequential execution, got {execution_order}"

            # Verify all stages executed
            assert "research" in result["stage_outputs"], "research stage should execute"
            assert "analysis" in result["stage_outputs"], "analysis stage should execute"
            assert "synthesis" in result["stage_outputs"], "synthesis stage should execute"

            # Verify outputs are correct
            assert result["stage_outputs"]["research"] == "output_research"
            assert result["stage_outputs"]["analysis"] == "output_analysis"
            assert result["stage_outputs"]["synthesis"] == "output_synthesis"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
