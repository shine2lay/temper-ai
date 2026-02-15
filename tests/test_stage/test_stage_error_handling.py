"""Tests for stage failure detection and on_stage_failure policy enforcement.

Tests that:
- stage_status is computed correctly (completed/degraded/failed)
- WorkflowStageError is raised when on_stage_failure='halt' and all agents fail
- on_stage_failure='skip' allows workflow to continue
"""
from unittest.mock import MagicMock, patch

import pytest

from src.stage.executors.state_keys import StateKeys
from src.workflow.node_builder import NodeBuilder
from src.shared.utils.exceptions import WorkflowStageError


class TestStageStatusComputation:
    """Test stage_status computation in sequential and parallel executors."""

    def test_sequential_stage_status_completed(self):
        """All agents succeed → stage_status='completed'."""
        from src.stage.executors.sequential import SequentialStageExecutor

        executor = SequentialStageExecutor()

        # Mock a stage with one agent that succeeds
        stage_config = {
            "stage": {
                "agents": [{"name": "agent1"}],
                "error_handling": {
                    "on_agent_failure": "continue_with_remaining",
                },
            }
        }

        mock_response = MagicMock()
        mock_response.output = "success output"
        mock_response.reasoning = None
        mock_response.confidence = 0.9
        mock_response.tokens = 100
        mock_response.estimated_cost_usd = 0.01
        mock_response.tool_calls = []

        mock_agent = MagicMock()
        mock_agent.execute.return_value = mock_response

        mock_config_loader = MagicMock()
        mock_config_loader.load_agent.return_value = {
            "agent": {
                "name": "agent1",
                "type": "standard",
                "description": "test",
                "prompt": {"inline": "test"},
                "inference": {"provider": "ollama", "model": "test"},
                "error_handling": {"on_error": "continue"},
            }
        }

        mock_factory = MagicMock()
        mock_factory.create.return_value = mock_agent

        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        with patch(
            "src.stage.executors.sequential.AgentFactory",
            mock_factory,
        ):
            result = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=state,
                config_loader=mock_config_loader,
            )

        stage_output = result[StateKeys.STAGE_OUTPUTS]["test_stage"]
        assert stage_output["stage_status"] == "completed"

    def test_sequential_stage_status_failed_all_agents(self):
        """All agents fail → stage_status='failed'."""
        from src.stage.executors._sequential_helpers import (
            AgentExecutionContext,
            run_all_agents,
        )
        from src.stage.executors.sequential import SequentialStageExecutor
        from src.stage._schemas import StageErrorHandlingConfig

        executor = SequentialStageExecutor()

        # Mock execute_agent to always return failure
        def mock_execute_agent(ctx, agent_ref, prior_agent_outputs=None):
            agent_name = executor._extract_agent_name(agent_ref)
            return {
                "agent_name": agent_name,
                "output_data": {"output": "", "error": "LLM timeout", "error_type": "llm_timeout"},
                "status": "failed",
                "metrics": {"tokens": 0, "cost_usd": 0.0, "duration_seconds": 1.0, "tool_calls": 0},
            }

        agents = [{"name": "agent1"}, {"name": "agent2"}]
        error_handling = StageErrorHandlingConfig(on_agent_failure="continue_with_remaining")

        ctx = AgentExecutionContext(
            executor=executor,
            stage_id="stage-test",
            stage_name="test_stage",
            workflow_id="wf-test",
            state={"stage_outputs": {}},
            tracker=None,
            config_loader=MagicMock(),
        )

        with patch(
            "src.stage.executors._sequential_helpers.execute_agent",
            side_effect=mock_execute_agent,
        ):
            outputs, statuses, metrics = run_all_agents(
                ctx=ctx,
                agents=agents,
                error_handling=error_handling,
            )

        # All agents should be in failed status
        for name, status in statuses.items():
            assert isinstance(status, dict)
            assert status[StateKeys.STATUS] == "failed"


class TestWorkflowStageError:
    """Test WorkflowStageError exception."""

    def test_exception_has_stage_name(self):
        """WorkflowStageError carries the stage_name attribute."""
        err = WorkflowStageError(
            message="Stage 'analysis' failed",
            stage_name="analysis",
        )
        assert err.stage_name == "analysis"
        assert "analysis" in str(err)

    def test_is_subclass_of_workflow_error(self):
        """WorkflowStageError is a subclass of WorkflowError."""
        from src.shared.utils.exceptions import WorkflowError

        err = WorkflowStageError(
            message="fail",
            stage_name="test",
        )
        assert isinstance(err, WorkflowError)


class TestNodeBuilderStageFailureCheck:
    """Test NodeBuilder._check_stage_failure() method."""

    def _make_builder(self):
        config_loader = MagicMock()
        tool_registry = MagicMock()
        executors = {"sequential": MagicMock()}
        return NodeBuilder(config_loader, tool_registry, executors)

    def test_check_stage_failure_raises_on_halt(self):
        """_check_stage_failure raises WorkflowStageError when policy=halt."""
        builder = self._make_builder()

        result_dict = {
            "stage_outputs": {
                "analysis": {
                    "stage_status": "failed",
                    "agent_statuses": {
                        "agent1": {"status": "failed"},
                        "agent2": {"status": "failed"},
                    },
                }
            }
        }
        workflow_config = {
            "workflow": {
                "error_handling": {"on_stage_failure": "halt"}
            }
        }

        with pytest.raises(WorkflowStageError) as exc_info:
            builder._check_stage_failure("analysis", result_dict, workflow_config)

        assert exc_info.value.stage_name == "analysis"
        assert "agent1" in str(exc_info.value)
        assert "agent2" in str(exc_info.value)

    def test_check_stage_failure_default_is_halt(self):
        """Default on_stage_failure policy is halt."""
        builder = self._make_builder()

        result_dict = {
            "stage_outputs": {
                "research": {
                    "stage_status": "failed",
                    "agent_statuses": {"agent1": {"status": "failed"}},
                }
            }
        }
        # No error_handling config → default halt
        workflow_config = {"workflow": {}}

        with pytest.raises(WorkflowStageError):
            builder._check_stage_failure("research", result_dict, workflow_config)

    def test_check_stage_failure_skip_does_not_raise(self):
        """_check_stage_failure does not raise when policy=skip."""
        builder = self._make_builder()

        result_dict = {
            "stage_outputs": {
                "analysis": {
                    "stage_status": "failed",
                    "agent_statuses": {"agent1": {"status": "failed"}},
                }
            }
        }
        workflow_config = {
            "workflow": {
                "error_handling": {"on_stage_failure": "skip"}
            }
        }

        # Should not raise
        result = builder._check_stage_failure("analysis", result_dict, workflow_config)
        assert result is None

    def test_check_stage_failure_ignores_non_failed(self):
        """_check_stage_failure does nothing for completed/degraded stages."""
        builder = self._make_builder()

        for status in ("completed", "degraded"):
            result_dict = {
                "stage_outputs": {
                    "analysis": {
                        "stage_status": status,
                        "agent_statuses": {"agent1": "success"},
                    }
                }
            }
            workflow_config = {
                "workflow": {
                    "error_handling": {"on_stage_failure": "halt"}
                }
            }

            # Should not raise
            result = builder._check_stage_failure("analysis", result_dict, workflow_config)
            assert result is None

    def test_check_stage_failure_handles_missing_stage_output(self):
        """_check_stage_failure handles missing stage in results gracefully."""
        builder = self._make_builder()

        result_dict = {"stage_outputs": {}}
        workflow_config = {"workflow": {"error_handling": {"on_stage_failure": "halt"}}}

        # Should not raise - no stage output to check
        result = builder._check_stage_failure("nonexistent", result_dict, workflow_config)
        assert result is None
