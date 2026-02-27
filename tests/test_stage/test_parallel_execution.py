"""Tests for parallel stage execution with refactored executors.

This test module verifies:
- Detection of parallel vs sequential mode
- Parallel agent execution with LangGraph subgraph
- Error handling for partial agent failures
- Min successful agents enforcement
- Synthesis integration
- Performance characteristics
"""

from unittest.mock import Mock, patch

import pytest

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.stage.executors import (
    AdaptiveStageExecutor,
    ParallelStageExecutor,
    SequentialStageExecutor,
)
from temper_ai.stage.executors.state_keys import StateKeys
from temper_ai.workflow.domain_state import WorkflowDomainState
from temper_ai.workflow.engines.langgraph_compiler import LangGraphCompiler


class TestAgentModeDetection:
    """Test detection of parallel vs sequential execution mode via NodeBuilder."""

    def test_get_agent_mode_parallel_dict(self):
        """Test detection of parallel mode from dict config."""
        compiler = LangGraphCompiler()

        stage_config = {
            "execution": {"agent_mode": "parallel"},
            "agents": ["agent1", "agent2"],
        }

        assert compiler.node_builder.get_agent_mode(stage_config) == "parallel"

    def test_get_agent_mode_sequential_dict(self):
        """Test detection of sequential mode from dict config."""
        compiler = LangGraphCompiler()

        stage_config = {"execution": {"agent_mode": "sequential"}, "agents": ["agent1"]}

        assert compiler.node_builder.get_agent_mode(stage_config) == "sequential"

    def test_get_agent_mode_default(self):
        """Test default mode is sequential."""
        compiler = LangGraphCompiler()

        # No execution config
        stage_config = {"agents": ["agent1"]}
        assert compiler.node_builder.get_agent_mode(stage_config) == "sequential"

        # Empty execution config
        stage_config = {"execution": {}, "agents": ["agent1"]}
        assert compiler.node_builder.get_agent_mode(stage_config) == "sequential"

    def test_get_agent_mode_pydantic_model(self):
        """Test detection from Pydantic model config."""
        compiler = LangGraphCompiler()

        # Mock Pydantic model
        mock_execution = Mock()
        mock_execution.agent_mode = "parallel"

        mock_stage = Mock()
        mock_stage.execution = mock_execution

        stage_config = Mock()
        stage_config.stage = mock_stage

        assert compiler.node_builder.get_agent_mode(stage_config) == "parallel"


class TestExecutorRegistry:
    """Test that compiler properly initializes and uses executors."""

    def test_compiler_has_executors(self):
        """Test compiler initializes with all executors."""
        compiler = LangGraphCompiler()

        assert "sequential" in compiler.executors
        assert "parallel" in compiler.executors
        assert "adaptive" in compiler.executors
        assert isinstance(compiler.executors["sequential"], SequentialStageExecutor)
        assert isinstance(compiler.executors["parallel"], ParallelStageExecutor)
        assert isinstance(compiler.executors["adaptive"], AdaptiveStageExecutor)

    def test_stage_node_delegates_to_executor(self):
        """Test that stage nodes delegate to executors."""
        compiler = LangGraphCompiler()

        stage_config = {"agents": ["agent1"], "execution": {"agent_mode": "sequential"}}

        with patch.object(compiler.config_loader, "load_stage") as mock_load:
            with patch.object(
                compiler.executors["sequential"], "execute_stage"
            ) as mock_exec:
                mock_load.return_value = stage_config
                mock_exec.return_value = {"stage_outputs": {}, "current_stage": ""}

                stage_node = compiler.node_builder.create_stage_node("research", {})
                state = WorkflowDomainState(stage_outputs={})

                stage_node(state)

                # Verify executor was called
                mock_exec.assert_called_once()


class TestSequentialExecutor:
    """Test sequential stage executor."""

    def test_sequential_executor_supports_sequential_type(self):
        """Test executor correctly identifies supported type."""
        executor = SequentialStageExecutor()
        assert executor.supports_stage_type("sequential") is True
        assert executor.supports_stage_type("parallel") is False

    def test_sequential_executor_executes_agents_in_order(self):
        """Test sequential execution of agents."""
        executor = SequentialStageExecutor()

        # Mock config loader
        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "agent1"}

        # Mock agent
        mock_agent = Mock()
        mock_response = AgentResponse(
            output="Sequential output",
            reasoning="Sequential reasoning",
            tokens=100,
            estimated_cost_usd=0.001,
            tool_calls=[],
        )
        mock_agent.execute.return_value = mock_response

        # Mock AgentConfig
        mock_agent_config = Mock()
        mock_agent_config.name = "agent1"

        stage_config = {"agents": ["agent1"]}

        state = {"workflow_id": "wf-123", "stage_outputs": {}}

        with patch(
            "temper_ai.storage.schemas.agent_config.AgentConfig"
        ) as mock_config_class:
            with patch(
                "temper_ai.stage.executors.sequential.AgentFactory.create"
            ) as mock_create:
                mock_config_class.return_value = mock_agent_config
                mock_create.return_value = mock_agent

                result = executor.execute_stage(
                    stage_name="research",
                    stage_config=stage_config,
                    state=state,
                    config_loader=mock_config_loader,
                )

                # Verify execution — sequential now returns structured dict
                assert (
                    result[StateKeys.STAGE_OUTPUTS]["research"]["output"]
                    == "Sequential output"
                )
                assert result[StateKeys.CURRENT_STAGE] == "research"


class TestParallelExecutor:
    """Test parallel stage executor."""

    def test_parallel_executor_supports_parallel_type(self):
        """Test executor correctly identifies supported type."""
        executor = ParallelStageExecutor()
        assert executor.supports_stage_type("parallel") is True
        assert executor.supports_stage_type("sequential") is False


class TestAdaptiveExecutor:
    """Test adaptive stage executor."""

    def test_adaptive_executor_supports_adaptive_type(self):
        """Test executor correctly identifies supported type."""
        executor = AdaptiveStageExecutor()
        assert executor.supports_stage_type("adaptive") is True
        assert executor.supports_stage_type("sequential") is False
        assert executor.supports_stage_type("parallel") is False

    def test_adaptive_executor_has_sequential_and_parallel_executors(self):
        """Test adaptive executor composes sequential and parallel executors."""
        executor = AdaptiveStageExecutor()
        assert hasattr(executor, "sequential_executor")
        assert hasattr(executor, "parallel_executor")
        assert isinstance(executor.sequential_executor, SequentialStageExecutor)
        assert isinstance(executor.parallel_executor, ParallelStageExecutor)


class TestBackwardCompatibility:
    """Test backward compatibility with M2 sequential execution."""

    def test_sequential_execution_through_compiler_still_works(self):
        """Test M2-style sequential execution through compiler."""
        compiler = LangGraphCompiler()

        # Mock agent
        mock_agent = Mock()
        mock_response = AgentResponse(
            output="Sequential output",
            reasoning="Sequential reasoning",
            tokens=100,
            estimated_cost_usd=0.001,
            tool_calls=[],
        )
        mock_agent.execute.return_value = mock_response

        # Mock AgentConfig
        mock_agent_config = Mock()
        mock_agent_config.name = "agent1"

        stage_config = {
            "agents": ["agent1"]
            # No execution mode = sequential by default
        }

        state = {"workflow_id": "wf-123", "stage_outputs": {}}

        with patch.object(compiler.config_loader, "load_agent") as mock_load:
            with patch(
                "temper_ai.storage.schemas.agent_config.AgentConfig"
            ) as mock_config_class:
                with patch(
                    "temper_ai.stage.executors.sequential.AgentFactory.create"
                ) as mock_create:
                    mock_load.return_value = {"name": "agent1"}
                    mock_config_class.return_value = mock_agent_config
                    mock_create.return_value = mock_agent

                    # Execute through executor
                    result = compiler.executors["sequential"].execute_stage(
                        stage_name="research",
                        stage_config=stage_config,
                        state=state,
                        config_loader=compiler.config_loader,
                    )

                    # Verify sequential execution worked — sequential now returns structured dict
                    assert (
                        result[StateKeys.STAGE_OUTPUTS]["research"]["output"]
                        == "Sequential output"
                    )
                    assert result[StateKeys.CURRENT_STAGE] == "research"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
