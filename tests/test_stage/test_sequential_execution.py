"""Tests for sequential stage executor with per-agent output accumulation.

Verifies:
- Multiple agents accumulate outputs (not just last agent)
- Subsequent agents receive prior agents' outputs via current_stage_agents
- Final stage output is a structured dict with per-agent data
- Single-agent stages work correctly
- Agent failures are recorded in agent_statuses
"""

from unittest.mock import Mock, patch

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.stage.executors import SequentialStageExecutor
from temper_ai.stage.executors.state_keys import StateKeys


def _make_agent_response(
    output="test output",
    reasoning="test reasoning",
    confidence=0.85,
    tokens=100,
    cost=0.001,
):
    """Create an AgentResponse with given values."""
    return AgentResponse(
        output=output,
        reasoning=reasoning,
        confidence=confidence,
        tokens=tokens,
        estimated_cost_usd=cost,
        tool_calls=[],
    )


def _mock_config_loader():
    """Create a mock config loader that returns minimal agent configs."""
    loader = Mock()
    loader.load_agent.return_value = {"agent": {"name": "agent"}}
    return loader


def _setup_factory_and_config(mock_agent_config_cls, mock_factory, agents_or_responses):
    """Set up AgentFactory and AgentConfig mocks.

    Args:
        mock_agent_config_cls: The patched AgentConfig class
        mock_factory: The patched AgentFactory class
        agents_or_responses: Either a single AgentResponse (used for all agents),
            a list of AgentResponses (one per agent), or a list of Mock agents.
    """
    # AgentConfig just passes through — we don't need real Pydantic validation
    mock_agent_config_cls.side_effect = lambda **kwargs: Mock()

    if isinstance(agents_or_responses, list) and len(agents_or_responses) > 0:
        if isinstance(agents_or_responses[0], Mock):
            # List of pre-built mock agents
            mock_factory.create.side_effect = agents_or_responses
        else:
            # List of AgentResponses — create mock agents for each
            mock_agents = []
            for resp in agents_or_responses:
                agent = Mock()
                agent.execute.return_value = resp
                mock_agents.append(agent)
            mock_factory.create.side_effect = mock_agents
    else:
        # Single response for all agents
        agent = Mock()
        agent.execute.return_value = agents_or_responses
        mock_factory.create.return_value = agent


# Both AgentFactory (module-level import) and AgentConfig (local import in _run_agent)
# need patching to isolate the executor from Pydantic validation and real agent creation.
FACTORY_PATCH = "temper_ai.stage.executors.sequential.AgentFactory"
CONFIG_PATCH = "temper_ai.storage.schemas.agent_config.AgentConfig"


class TestSequentialOutputAccumulation:
    """Test that sequential executor accumulates per-agent outputs."""

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_single_agent_returns_structured_dict(self, mock_factory, mock_config_cls):
        """Single agent stage returns dict with agent_outputs, not bare string."""
        _setup_factory_and_config(
            mock_config_cls,
            mock_factory,
            _make_agent_response(output="research result"),
        )

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="research",
            stage_config={"stage": {"agents": ["researcher"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        stage_out = result[StateKeys.STAGE_OUTPUTS]["research"]
        assert isinstance(stage_out, dict)
        assert stage_out["output"] == "research result"
        assert "researcher" in stage_out["agent_outputs"]
        assert stage_out["agent_outputs"]["researcher"]["output"] == "research result"
        assert stage_out["agent_statuses"]["researcher"] == "success"
        assert "researcher" in stage_out["agent_metrics"]

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_multiple_agents_all_accumulated(self, mock_factory, mock_config_cls):
        """All agent outputs are preserved, not just the last one."""
        _setup_factory_and_config(
            mock_config_cls,
            mock_factory,
            [
                _make_agent_response(output="findings from research", tokens=100),
                _make_agent_response(output="analysis of findings", tokens=200),
                _make_agent_response(output="final synthesis", tokens=150),
            ],
        )

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="pipeline",
            stage_config={
                "stage": {"agents": ["researcher", "analyzer", "synthesizer"]}
            },
            state=state,
            config_loader=_mock_config_loader(),
        )

        stage_out = result[StateKeys.STAGE_OUTPUTS]["pipeline"]

        # All three agents are present
        assert len(stage_out["agent_outputs"]) == 3
        assert "researcher" in stage_out["agent_outputs"]
        assert "analyzer" in stage_out["agent_outputs"]
        assert "synthesizer" in stage_out["agent_outputs"]

        # Each has correct output
        assert (
            stage_out["agent_outputs"]["researcher"]["output"]
            == "findings from research"
        )
        assert (
            stage_out["agent_outputs"]["analyzer"]["output"] == "analysis of findings"
        )
        assert stage_out["agent_outputs"]["synthesizer"]["output"] == "final synthesis"

        # "output" key concatenates all non-empty agent outputs
        assert "findings from research" in stage_out["output"]
        assert "analysis of findings" in stage_out["output"]
        assert "final synthesis" in stage_out["output"]

        # All statuses recorded
        assert all(s == "success" for s in stage_out["agent_statuses"].values())

        # All metrics recorded
        assert stage_out["agent_metrics"]["researcher"]["tokens"] == 100
        assert stage_out["agent_metrics"]["analyzer"]["tokens"] == 200
        assert stage_out["agent_metrics"]["synthesizer"]["tokens"] == 150


class TestAgentContextSharing:
    """Test that subsequent agents receive prior agents' outputs."""

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_second_agent_sees_first_agent_output(self, mock_factory, mock_config_cls):
        """Agent 2 receives agent 1's output via current_stage_agents."""
        captured_inputs = []

        def make_agent(config):
            agent = Mock()

            def execute(input_data, context):
                captured_inputs.append(dict(input_data))
                return _make_agent_response(
                    output=f"output from {len(captured_inputs)}"
                )

            agent.execute.side_effect = execute
            return agent

        mock_config_cls.side_effect = lambda **kwargs: Mock()
        mock_factory.create.side_effect = make_agent

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        executor.execute_stage(
            stage_name="collab",
            stage_config={"stage": {"agents": ["agent_a", "agent_b"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        # Agent A should have empty current_stage_agents
        assert captured_inputs[0]["current_stage_agents"] == {}

        # Agent B should see Agent A's output
        assert "agent_a" in captured_inputs[1]["current_stage_agents"]
        assert (
            captured_inputs[1]["current_stage_agents"]["agent_a"]["output"]
            == "output from 1"
        )

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_third_agent_sees_both_prior_agents(self, mock_factory, mock_config_cls):
        """Agent 3 receives both agent 1 and agent 2 outputs."""
        captured_inputs = []

        def make_agent(config):
            agent = Mock()

            def execute(input_data, context):
                captured_inputs.append(dict(input_data))
                return _make_agent_response(output=f"output-{len(captured_inputs)}")

            agent.execute.side_effect = execute
            return agent

        mock_config_cls.side_effect = lambda **kwargs: Mock()
        mock_factory.create.side_effect = make_agent

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        executor.execute_stage(
            stage_name="chain",
            stage_config={"stage": {"agents": ["first", "second", "third"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        # Third agent sees both prior agents
        third_input = captured_inputs[2]["current_stage_agents"]
        assert len(third_input) == 2
        assert "first" in third_input
        assert "second" in third_input


class TestAgentFailureHandling:
    """Test that agent failures are recorded properly with error context."""

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_agent_failure_recorded_in_statuses(self, mock_factory, mock_config_cls):
        """Failed agent is recorded with error details and execution continues with continue_with_remaining policy."""
        failing_agent = Mock()
        failing_agent.execute.side_effect = RuntimeError("LLM timeout")

        succeeding_agent = Mock()
        succeeding_agent.execute.return_value = _make_agent_response(output="recovered")

        mock_config_cls.side_effect = lambda **kwargs: Mock()
        mock_factory.create.side_effect = [failing_agent, succeeding_agent]

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="resilient",
            stage_config={
                "stage": {
                    "agents": ["flaky_agent", "reliable_agent"],
                    "error_handling": {"on_agent_failure": "continue_with_remaining"},
                }
            },
            state=state,
            config_loader=_mock_config_loader(),
        )

        stage_out = result[StateKeys.STAGE_OUTPUTS]["resilient"]

        # Failed agent status includes error details
        assert isinstance(stage_out["agent_statuses"]["flaky_agent"], dict)
        assert stage_out["agent_statuses"]["flaky_agent"]["status"] == "failed"
        assert stage_out["agent_statuses"]["flaky_agent"]["error"] == "LLM timeout"
        assert (
            stage_out["agent_statuses"]["flaky_agent"]["error_type"]
            == "AGENT_EXECUTION_ERROR"
        )

        # Failed agent output_data includes error fields
        failed_output = stage_out["agent_outputs"]["flaky_agent"]
        assert failed_output["error"] == "LLM timeout"
        assert failed_output["error_type"] == "AGENT_EXECUTION_ERROR"
        assert "traceback" in failed_output
        assert failed_output["output"] == ""

        # Succeeding agent continues and completes
        assert stage_out["agent_statuses"]["reliable_agent"] == "success"
        assert stage_out["agent_outputs"]["reliable_agent"]["output"] == "recovered"

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_halt_on_failure_stops_execution(self, mock_factory, mock_config_cls):
        """With halt_stage policy (default), stage stops after first agent failure."""
        failing_agent = Mock()
        failing_agent.execute.side_effect = ValueError("Invalid input")

        succeeding_agent = Mock()
        succeeding_agent.execute.return_value = _make_agent_response(
            output="should not run"
        )

        mock_config_cls.side_effect = lambda **kwargs: Mock()
        mock_factory.create.side_effect = [failing_agent, succeeding_agent]

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="halt_test",
            stage_config={"stage": {"agents": ["failing", "should_not_run"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        stage_out = result[StateKeys.STAGE_OUTPUTS]["halt_test"]

        # First agent failed
        assert stage_out["agent_statuses"]["failing"]["status"] == "failed"
        assert stage_out["agent_statuses"]["failing"]["error"] == "Invalid input"

        # Second agent was not executed
        assert "should_not_run" not in stage_out["agent_statuses"]
        assert "should_not_run" not in stage_out["agent_outputs"]

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_error_type_from_base_error(self, mock_factory, mock_config_cls):
        """Error type is derived from BaseError.error_code when available."""
        from temper_ai.shared.utils.exceptions import BaseError, ErrorCode

        class CustomLLMError(BaseError):
            def __init__(self):
                super().__init__(
                    message="API key invalid",
                    error_code=ErrorCode.LLM_AUTHENTICATION_ERROR,
                )

        failing_agent = Mock()
        failing_agent.execute.side_effect = CustomLLMError()

        mock_config_cls.side_effect = lambda **kwargs: Mock()
        mock_factory.create.return_value = failing_agent

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="error_type_test",
            stage_config={"stage": {"agents": ["failing"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        stage_out = result[StateKeys.STAGE_OUTPUTS]["error_type_test"]
        failed_status = stage_out["agent_statuses"]["failing"]

        # Error type should be the ErrorCode value from BaseError
        assert failed_status["error_type"] == "LLM_AUTHENTICATION_ERROR"

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_error_message_sanitization(self, mock_factory, mock_config_cls):
        """Error messages are sanitized to prevent credential leakage."""
        failing_agent = Mock()
        failing_agent.execute.side_effect = RuntimeError(
            "Connection failed with API key: sk-1234567890abcdef"
        )

        mock_config_cls.side_effect = lambda **kwargs: Mock()
        mock_factory.create.return_value = failing_agent

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="sanitize_test",
            stage_config={"stage": {"agents": ["failing"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        stage_out = result[StateKeys.STAGE_OUTPUTS]["sanitize_test"]
        failed_output = stage_out["agent_outputs"]["failing"]

        # Error message should be sanitized (API key redacted)
        assert "sk-1234567890abcdef" not in failed_output["error"]
        assert "[REDACTED" in failed_output["error"]


class TestMetricsTracking:
    """Test that per-agent metrics are tracked correctly."""

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_metrics_include_duration(self, mock_factory, mock_config_cls):
        """Each agent's metrics include duration_seconds."""
        _setup_factory_and_config(
            mock_config_cls,
            mock_factory,
            _make_agent_response(tokens=500, cost=0.005),
        )

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="timed",
            stage_config={"stage": {"agents": ["agent1"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        metrics = result[StateKeys.STAGE_OUTPUTS]["timed"]["agent_metrics"]["agent1"]
        assert metrics["tokens"] == 500
        assert metrics["cost_usd"] == 0.005
        assert "duration_seconds" in metrics
        assert isinstance(metrics["duration_seconds"], float)

    @patch(CONFIG_PATCH)
    @patch(FACTORY_PATCH)
    def test_output_data_includes_confidence(self, mock_factory, mock_config_cls):
        """Agent output data includes confidence score."""
        _setup_factory_and_config(
            mock_config_cls,
            mock_factory,
            _make_agent_response(confidence=0.92),
        )

        executor = SequentialStageExecutor()
        state = {"stage_outputs": {}, "workflow_id": "wf-test"}

        result = executor.execute_stage(
            stage_name="confident",
            stage_config={"stage": {"agents": ["agent1"]}},
            state=state,
            config_loader=_mock_config_loader(),
        )

        output_data = result[StateKeys.STAGE_OUTPUTS]["confident"]["agent_outputs"][
            "agent1"
        ]
        assert output_data["confidence"] == 0.92
        assert output_data["reasoning"] == "test reasoning"


class TestConvergenceLoop:
    """Test convergence-based re-execution in sequential executor."""

    def test_convergence_stops_after_output_stabilises(self):
        """Convergence loop stops early when _execute_once returns stable output."""
        executor = SequentialStageExecutor()

        # Track how many times _execute_once is called
        call_count = 0
        outputs = ["draft v1", "draft v2", "final answer", "final answer"]

        def mock_execute_once(stage_name, stage_config, state, config_loader):
            nonlocal call_count
            output = outputs[min(call_count, len(outputs) - 1)]
            call_count += 1
            if StateKeys.STAGE_OUTPUTS not in state:
                state[StateKeys.STAGE_OUTPUTS] = {}
            state[StateKeys.STAGE_OUTPUTS][stage_name] = {
                StateKeys.OUTPUT: output,
            }
            return state

        executor._execute_once = mock_execute_once

        from temper_ai.stage._schemas import ConvergenceConfig

        convergence_cfg = ConvergenceConfig(
            enabled=True,
            max_iterations=10,
            method="exact_hash",
        )

        state: dict = {"stage_outputs": {}, "workflow_id": "wf-conv"}
        result = executor._execute_with_convergence(
            "converge_stage",
            {},
            state,
            _mock_config_loader(),
            convergence_cfg,
        )

        # Should stop at iteration 4 (outputs[2]==outputs[3] -> converged)
        assert call_count == 4
        assert (
            result[StateKeys.STAGE_OUTPUTS]["converge_stage"][StateKeys.OUTPUT]
            == "final answer"
        )

    def test_convergence_respects_max_iterations(self):
        """Loop stops at max_iterations when outputs never stabilise."""
        executor = SequentialStageExecutor()

        call_count = 0

        def mock_execute_once(stage_name, stage_config, state, config_loader):
            nonlocal call_count
            call_count += 1
            if StateKeys.STAGE_OUTPUTS not in state:
                state[StateKeys.STAGE_OUTPUTS] = {}
            state[StateKeys.STAGE_OUTPUTS][stage_name] = {
                StateKeys.OUTPUT: f"unique output {call_count}",
            }
            return state

        executor._execute_once = mock_execute_once

        from temper_ai.stage._schemas import ConvergenceConfig

        convergence_cfg = ConvergenceConfig(
            enabled=True,
            max_iterations=3,
            method="exact_hash",
        )

        state: dict = {"stage_outputs": {}, "workflow_id": "wf-conv"}
        executor._execute_with_convergence(
            "no_conv",
            {},
            state,
            _mock_config_loader(),
            convergence_cfg,
        )

        assert call_count == 3

    def test_execute_stage_dispatches_to_convergence(self):
        """execute_stage calls _execute_with_convergence when config is enabled."""
        executor = SequentialStageExecutor()
        convergence_called = False

        def mock_convergence(stage_name, stage_config, state, config_loader, cfg):
            nonlocal convergence_called
            convergence_called = True
            return state

        executor._execute_with_convergence = mock_convergence

        from temper_ai.stage._schemas import (
            ConvergenceConfig,
            StageConfig,
            StageConfigInner,
        )

        inner = StageConfigInner(
            name="conv_stage",
            description="test",
            agents=["agent1"],
            convergence=ConvergenceConfig(enabled=True),
        )
        stage_config = StageConfig(stage=inner)

        state: dict = {"stage_outputs": {}, "workflow_id": "wf-test"}
        executor.execute_stage(
            "conv_stage",
            stage_config,
            state,
            _mock_config_loader(),
        )

        assert convergence_called is True

    def test_convergence_no_false_positive_on_empty_first_output(self):
        """Empty first output should NOT trigger convergence on iteration 0."""
        executor = SequentialStageExecutor()

        call_count = 0
        # First iteration returns empty, second returns empty — converges on iter 2
        outputs = ["", "", "result"]

        def mock_execute_once(stage_name, stage_config, state, config_loader):
            nonlocal call_count
            output = outputs[min(call_count, len(outputs) - 1)]
            call_count += 1
            if StateKeys.STAGE_OUTPUTS not in state:
                state[StateKeys.STAGE_OUTPUTS] = {}
            state[StateKeys.STAGE_OUTPUTS][stage_name] = {
                StateKeys.OUTPUT: output,
            }
            return state

        executor._execute_once = mock_execute_once

        from temper_ai.stage._schemas import ConvergenceConfig

        convergence_cfg = ConvergenceConfig(
            enabled=True,
            max_iterations=5,
            method="exact_hash",
        )

        state: dict = {"stage_outputs": {}, "workflow_id": "wf-empty"}
        executor._execute_with_convergence(
            "empty_stage",
            {},
            state,
            _mock_config_loader(),
            convergence_cfg,
        )

        # Should run twice: iter 0 skips check (no previous), iter 1 compares "" vs "" → converges
        assert call_count == 2
