"""Tests for NodeBuilder class.

Verifies node creation, configuration loading, and executor delegation.
"""
import pytest
from unittest.mock import Mock, MagicMock
from src.compiler.node_builder import NodeBuilder
from src.compiler.state import WorkflowState
from src.compiler.config_loader import ConfigLoader
from src.tools.registry import ToolRegistry


class TestNodeBuilderInitialization:
    """Test NodeBuilder initialization."""

    def test_init_with_dependencies(self):
        """Test initialization with all dependencies."""
        config_loader = Mock(spec=ConfigLoader)
        tool_registry = Mock(spec=ToolRegistry)
        executors = {
            'sequential': Mock(),
            'parallel': Mock(),
            'adaptive': Mock()
        }

        builder = NodeBuilder(config_loader, tool_registry, executors)

        assert builder.config_loader is config_loader
        assert builder.tool_registry is tool_registry
        assert builder.executors is executors


class TestExtractStageName:
    """Test stage name extraction from various formats."""

    def setup_method(self):
        """Set up test fixtures."""
        self.builder = NodeBuilder(Mock(), Mock(), {})

    def test_extract_from_string(self):
        """Test extracting name from string."""
        name = self.builder.extract_stage_name("research")
        assert name == "research"

    def test_extract_from_dict_with_name(self):
        """Test extracting from dict with 'name' key."""
        stage = {"name": "research"}
        name = self.builder.extract_stage_name(stage)
        assert name == "research"

    def test_extract_from_dict_with_stage_name(self):
        """Test extracting from dict with 'stage_name' key."""
        stage = {"stage_name": "analysis"}
        name = self.builder.extract_stage_name(stage)
        assert name == "analysis"

    def test_extract_from_dict_with_stage_ref(self):
        """Test extracting from dict with 'stage_ref' key."""
        stage = {"stage_ref": "synthesis"}
        name = self.builder.extract_stage_name(stage)
        assert name == "synthesis"

    def test_extract_from_pydantic_name(self):
        """Test extracting from Pydantic model with 'name' attribute."""
        stage = Mock()
        stage.name = "research"
        name = self.builder.extract_stage_name(stage)
        assert name == "research"

    def test_extract_from_pydantic_stage_name(self):
        """Test extracting from Pydantic model with 'stage_name' attribute."""
        stage = Mock()
        stage.name = None
        stage.stage_name = "analysis"
        name = self.builder.extract_stage_name(stage)
        assert name == "analysis"

    def test_extract_raises_for_invalid(self):
        """Test that ValueError is raised for invalid stage reference."""
        with pytest.raises(ValueError, match="Cannot extract stage name"):
            self.builder.extract_stage_name({"invalid": "data"})


class TestExtractAgentName:
    """Test agent name extraction from various formats."""

    def setup_method(self):
        """Set up test fixtures."""
        self.builder = NodeBuilder(Mock(), Mock(), {})

    def test_extract_from_string(self):
        """Test extracting name from string."""
        name = self.builder.extract_agent_name("analyzer")
        assert name == "analyzer"

    def test_extract_from_dict_with_name(self):
        """Test extracting from dict with 'name' key."""
        agent = {"name": "analyzer"}
        name = self.builder.extract_agent_name(agent)
        assert name == "analyzer"

    def test_extract_from_dict_with_agent_name(self):
        """Test extracting from dict with 'agent_name' key."""
        agent = {"agent_name": "researcher"}
        name = self.builder.extract_agent_name(agent)
        assert name == "researcher"

    def test_extract_from_pydantic_name(self):
        """Test extracting from Pydantic model with 'name' attribute."""
        agent = Mock()
        agent.name = "analyzer"
        name = self.builder.extract_agent_name(agent)
        assert name == "analyzer"

    def test_extract_from_pydantic_agent_name(self):
        """Test extracting from Pydantic model with 'agent_name' attribute."""
        agent = Mock()
        agent.name = None
        agent.agent_name = "researcher"
        name = self.builder.extract_agent_name(agent)
        assert name == "researcher"


class TestGetAgentMode:
    """Test agent mode detection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.builder = NodeBuilder(Mock(), Mock(), {})

    def test_get_mode_sequential_dict(self):
        """Test detecting sequential mode from dict."""
        stage_config = {
            "execution": {"agent_mode": "sequential"}
        }
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "sequential"

    def test_get_mode_parallel_dict(self):
        """Test detecting parallel mode from dict."""
        stage_config = {
            "execution": {"agent_mode": "parallel"}
        }
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "parallel"

    def test_get_mode_adaptive_dict(self):
        """Test detecting adaptive mode from dict."""
        stage_config = {
            "execution": {"agent_mode": "adaptive"}
        }
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "adaptive"

    def test_get_mode_default_dict(self):
        """Test default mode when not specified in dict."""
        stage_config = {"execution": {}}
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "sequential"

    def test_get_mode_no_execution_dict(self):
        """Test default mode when execution key missing."""
        stage_config = {"agents": ["agent1"]}
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "sequential"

    def test_get_mode_pydantic_model(self):
        """Test detecting mode from Pydantic model."""
        execution = Mock()
        execution.agent_mode = "parallel"

        stage = Mock()
        stage.execution = execution

        stage_config = Mock()
        stage_config.stage = stage

        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "parallel"


class TestCreateStageNode:
    """Test stage node creation."""

    def test_create_stage_node_returns_callable(self):
        """Test that create_stage_node returns a callable."""
        config_loader = Mock()
        config_loader.load_stage.return_value = {
            "agents": ["agent1"],
            "execution": {"agent_mode": "sequential"}
        }

        executor = Mock()
        executor.execute_stage.return_value = WorkflowState()

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(),
            executors={'sequential': executor}
        )

        node = builder.create_stage_node("research", {})

        assert callable(node)

    def test_stage_node_loads_config(self):
        """Test that stage node loads configuration."""
        config_loader = Mock()
        stage_config = {
            "agents": ["agent1"],
            "execution": {"agent_mode": "sequential"}
        }
        config_loader.load_stage.return_value = stage_config

        executor = Mock()
        executor.execute_stage.return_value = WorkflowState()

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(),
            executors={'sequential': executor}
        )

        node = builder.create_stage_node("research", {})
        state = WorkflowState()
        node(state)

        config_loader.load_stage.assert_called_once_with("research")

    def test_stage_node_delegates_to_executor(self):
        """Test that stage node delegates to correct executor."""
        config_loader = Mock()
        stage_config = {
            "agents": ["agent1"],
            "execution": {"agent_mode": "parallel"}
        }
        config_loader.load_stage.return_value = stage_config

        sequential_executor = Mock()
        parallel_executor = Mock()
        parallel_executor.execute_stage.return_value = WorkflowState()

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(),
            executors={
                'sequential': sequential_executor,
                'parallel': parallel_executor
            }
        )

        node = builder.create_stage_node("research", {})
        state = WorkflowState()
        node(state)

        # Should call parallel executor, not sequential
        parallel_executor.execute_stage.assert_called_once()
        sequential_executor.execute_stage.assert_not_called()

    def test_stage_node_passes_correct_arguments(self):
        """Test that stage node passes correct arguments to executor."""
        config_loader = Mock()
        tool_registry = Mock()
        stage_config = {
            "agents": ["agent1"],
            "execution": {"agent_mode": "sequential"}
        }
        config_loader.load_stage.return_value = stage_config

        executor = Mock()
        executor.execute_stage.return_value = WorkflowState()

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=tool_registry,
            executors={'sequential': executor}
        )

        node = builder.create_stage_node("research", {})
        state = WorkflowState(workflow_id="wf-123")
        node(state)

        # Verify executor.execute_stage was called with correct args
        call_args = executor.execute_stage.call_args
        assert call_args[1]['stage_name'] == "research"
        assert call_args[1]['stage_config'] == stage_config
        assert call_args[1]['state'] is state
        assert call_args[1]['config_loader'] is config_loader
        assert call_args[1]['tool_registry'] is tool_registry

    def test_stage_node_handles_config_load_error(self):
        """Test that stage node raises error if config cannot be loaded."""
        config_loader = Mock()
        config_loader.load_stage.side_effect = Exception("Config not found")

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(),
            executors={'sequential': Mock()}
        )

        node = builder.create_stage_node("missing_stage", {})
        state = WorkflowState()

        with pytest.raises(ValueError, match="Cannot load stage config"):
            node(state)


class TestFindEmbeddedStage:
    """Test finding embedded stage configurations."""

    def test_find_embedded_returns_none_currently(self):
        """Test that find_embedded_stage returns None (not yet implemented)."""
        builder = NodeBuilder(Mock(), Mock(), {})

        # Mock workflow config with embedded stages
        workflow_config = Mock()
        workflow_config.workflow.stages = []

        result = builder.find_embedded_stage("research", workflow_config)

        # Currently returns None (future enhancement)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
