"""Tests for NodeBuilder class.

Verifies node creation, configuration loading, and executor delegation.
"""

import logging
from unittest.mock import Mock

import pytest

from temper_ai.shared.utils.exceptions import WorkflowStageError
from temper_ai.tools.registry import ToolRegistry
from temper_ai.workflow.config_loader import ConfigLoader
from temper_ai.workflow.domain_state import WorkflowDomainState
from temper_ai.workflow.node_builder import (
    STAGE_TIMEOUT_STATUS,
    NodeBuilder,
    _enforce_stage_failure_policy,
    _extract_on_stage_failure_policy,
    create_event_triggered_node,
)


class TestNodeBuilderInitialization:
    """Test NodeBuilder initialization."""

    def test_init_with_dependencies(self):
        """Test initialization with all dependencies."""
        config_loader = Mock(spec=ConfigLoader)
        tool_registry = Mock(spec=ToolRegistry)
        executors = {"sequential": Mock(), "parallel": Mock(), "adaptive": Mock()}

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
        stage_config = {"execution": {"agent_mode": "sequential"}}
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "sequential"

    def test_get_mode_parallel_dict(self):
        """Test detecting parallel mode from dict."""
        stage_config = {"execution": {"agent_mode": "parallel"}}
        mode = self.builder.get_agent_mode(stage_config)
        assert mode == "parallel"

    def test_get_mode_adaptive_dict(self):
        """Test detecting adaptive mode from dict."""
        stage_config = {"execution": {"agent_mode": "adaptive"}}
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
        config_loader = Mock(spec=ConfigLoader)
        config_loader.load_stage.return_value = {
            "agents": ["agent1"],
            "execution": {"agent_mode": "sequential"},
        }

        executor = Mock()
        executor.execute_stage.return_value = {"stage_outputs": {}, "current_stage": ""}

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(spec=ToolRegistry),
            executors={"sequential": executor},
        )

        node = builder.create_stage_node("research", {})

        assert callable(node)

    def test_stage_node_loads_config(self):
        """Test that stage node loads configuration."""
        config_loader = Mock(spec=ConfigLoader)
        stage_config = {"agents": ["agent1"], "execution": {"agent_mode": "sequential"}}
        config_loader.load_stage.return_value = stage_config

        executor = Mock()
        executor.execute_stage.return_value = {"stage_outputs": {}, "current_stage": ""}

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(spec=ToolRegistry),
            executors={"sequential": executor},
        )

        node = builder.create_stage_node("research", {})
        state = WorkflowDomainState()
        node(state)

        config_loader.load_stage.assert_called_once_with("research")

    def test_stage_node_delegates_to_executor(self):
        """Test that stage node delegates to correct executor."""
        config_loader = Mock(spec=ConfigLoader)
        stage_config = {"agents": ["agent1"], "execution": {"agent_mode": "parallel"}}
        config_loader.load_stage.return_value = stage_config

        sequential_executor = Mock()
        parallel_executor = Mock()
        parallel_executor.execute_stage.return_value = {
            "stage_outputs": {},
            "current_stage": "",
        }

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(spec=ToolRegistry),
            executors={
                "sequential": sequential_executor,
                "parallel": parallel_executor,
            },
        )

        node = builder.create_stage_node("research", {})
        state = WorkflowDomainState()
        node(state)

        # Should call parallel executor, not sequential
        parallel_executor.execute_stage.assert_called_once()
        sequential_executor.execute_stage.assert_not_called()

    def test_stage_node_passes_correct_arguments(self):
        """Test that stage node passes correct arguments to executor."""
        config_loader = Mock(spec=ConfigLoader)
        tool_registry = Mock(spec=ToolRegistry)
        stage_config = {"agents": ["agent1"], "execution": {"agent_mode": "sequential"}}
        config_loader.load_stage.return_value = stage_config

        executor = Mock()
        executor.execute_stage.return_value = {"stage_outputs": {}, "current_stage": ""}

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=tool_registry,
            executors={"sequential": executor},
        )

        node = builder.create_stage_node("research", {})
        state = WorkflowDomainState(workflow_id="wf-123")
        node(state)

        # Verify executor.execute_stage was called with correct args
        call_args = executor.execute_stage.call_args
        assert call_args[1]["stage_name"] == "research"
        assert call_args[1]["stage_config"] == stage_config
        # State is converted to dict via to_typed_dict() before passing to executor
        assert isinstance(call_args[1]["state"], dict)
        assert call_args[1]["state"]["workflow_id"] == "wf-123"
        assert call_args[1]["config_loader"] is config_loader
        assert call_args[1]["tool_registry"] is tool_registry

    def test_stage_node_handles_config_load_error(self):
        """Test that stage node raises error if config cannot be loaded."""
        config_loader = Mock(spec=ConfigLoader)
        config_loader.load_stage.side_effect = Exception("Config not found")

        builder = NodeBuilder(
            config_loader=config_loader,
            tool_registry=Mock(spec=ToolRegistry),
            executors={"sequential": Mock()},
        )

        node = builder.create_stage_node("missing_stage", {})
        state = WorkflowDomainState()

        with pytest.raises(ValueError, match="Cannot load stage config"):
            node(state)


class TestFindEmbeddedStage:
    """Test finding embedded stage configurations."""

    def test_find_embedded_stage_not_found_returns_none(self):
        """Test that find_embedded_stage returns None when stage is not in config."""
        builder = NodeBuilder(Mock(spec=ConfigLoader), Mock(spec=ToolRegistry), {})

        workflow_config = Mock()
        workflow_config.workflow.stages = []

        result = builder.find_embedded_stage("research", workflow_config)
        assert result is None


class TestExtractOnStageFailurePolicy:
    """Test extraction of on_stage_failure policy from workflow config."""

    def test_dict_config_with_error_handling(self):
        config = {"workflow": {"error_handling": {"on_stage_failure": "skip"}}}
        assert _extract_on_stage_failure_policy(config) == "skip"

    def test_dict_config_without_error_handling(self):
        config = {"workflow": {}}
        assert _extract_on_stage_failure_policy(config) == "halt"

    def test_empty_dict_config(self):
        assert _extract_on_stage_failure_policy({}) == "halt"


class TestEnforceStageFailurePolicy:
    """Test enforcement of on_stage_failure policy."""

    def test_halt_policy_raises(self):
        with pytest.raises(WorkflowStageError):
            _enforce_stage_failure_policy(
                stage_name="my_stage",
                stage_status="failed",
                stage_output={},
                on_stage_failure="halt",
            )

    def test_skip_policy_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="temper_ai.workflow.node_builder"):
            _enforce_stage_failure_policy(
                stage_name="my_stage",
                stage_status="failed",
                stage_output={},
                on_stage_failure="skip",
            )
        assert any("skip" in r.message for r in caplog.records)

    def test_halt_degraded_raises(self):
        with pytest.raises(WorkflowStageError):
            _enforce_stage_failure_policy(
                stage_name="my_stage",
                stage_status="degraded",
                stage_output={},
                on_stage_failure="halt",
            )


class TestCreateEventTriggeredNode:
    """Test create_event_triggered_node factory."""

    def test_no_event_bus_runs_immediately(self):
        inner_node = Mock(return_value={"result": "ok"})
        trigger_config = Mock(event_type="test_event", timeout_seconds=30)
        trigger_config.source_workflow = None

        node = create_event_triggered_node("stage1", inner_node, None, trigger_config)
        state = {"some": "data"}
        result = node(state)

        inner_node.assert_called_once_with(state)
        assert result == {"result": "ok"}

    def test_event_received_runs_inner(self):
        event_data = {"type": "test_event", "payload": "data"}
        event_bus = Mock()
        event_bus.wait_for_event.return_value = event_data
        inner_node = Mock(return_value={"result": "ok"})
        trigger_config = Mock(event_type="test_event", timeout_seconds=30)
        trigger_config.source_workflow = None

        node = create_event_triggered_node(
            "stage1", inner_node, event_bus, trigger_config
        )
        state = {"some": "data"}
        node(state)

        call_state = inner_node.call_args[0][0]
        assert "trigger_event" in call_state
        assert call_state["trigger_event"] == event_data

    def test_event_timeout_sets_status(self):
        event_bus = Mock()
        event_bus.wait_for_event.return_value = None
        inner_node = Mock()
        trigger_config = Mock(event_type="test_event", timeout_seconds=5)
        trigger_config.source_workflow = None

        node = create_event_triggered_node(
            "stage1", inner_node, event_bus, trigger_config
        )
        result = node({"some": "data"})

        assert result["stage_status"] == STAGE_TIMEOUT_STATUS
        inner_node.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
