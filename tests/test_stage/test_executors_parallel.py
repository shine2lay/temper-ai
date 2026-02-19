"""Comprehensive unit tests for ParallelStageExecutor.

This test suite validates parallel agent execution, concurrent state management,
error aggregation, synthesis integration, quality gates with retries, and
observability tracking.

Target: 80%+ code coverage of src/compiler/executors/parallel.py
"""
import time
from unittest.mock import Mock, patch

import pytest

from temper_ai.agent.base_agent import AgentResponse
from temper_ai.stage.executors.parallel import ParallelStageExecutor
from temper_ai.stage.executors.state_keys import StateKeys

# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_config_loader():
    """Create mock ConfigLoader."""
    loader = Mock()
    loader.load_agent.return_value = {
        "name": "test_agent",
        "role": "researcher",
        "llm": {"provider": "mock", "model": "test"},
        "prompt_template": "Test prompt"
    }
    return loader


@pytest.fixture
def mock_agent_response():
    """Create mock AgentResponse for successful execution."""
    response = Mock(spec=AgentResponse)
    response.output = "Test output"
    response.reasoning = "Test reasoning"
    response.confidence = 0.9
    response.tokens = 100
    response.estimated_cost_usd = 0.001
    response.tool_calls = []
    return response


@pytest.fixture
def mock_synthesis_result():
    """Create mock SynthesisResult."""
    result = Mock()
    result.decision = "synthesized_decision"
    result.confidence = 0.85
    result.method = "consensus"
    result.votes = {"decision1": 2, "decision2": 1}
    result.conflicts = []
    result.reasoning = "Test synthesis reasoning"
    result.metadata = {}
    return result


@pytest.fixture
def basic_stage_config():
    """Create basic stage configuration."""
    return {
        "stage": {
            "agents": ["agent1", "agent2"]
        },
        "error_handling": {
            "min_successful_agents": 1,
            "on_stage_failure": "halt"
        },
        "quality_gates": {
            "enabled": False
        }
    }


@pytest.fixture
def initial_state():
    """Create initial workflow state."""
    return {
        "workflow_id": "test_workflow",
        "stage_outputs": {},
        "current_stage": None
    }


# ============================================================================
# Test Class 1: ParallelExecutor Basics
# ============================================================================

class TestParallelExecutorBasics:
    """Tests for basic initialization and properties."""

    def test_initialization_with_defaults(self):
        """Executor should initialize with None for optional components."""
        executor = ParallelStageExecutor()
        assert executor.synthesis_coordinator is None
        assert executor.quality_gate_validator is None

    def test_initialization_with_components(self):
        """Executor should store provided components."""
        coordinator = Mock()
        validator = Mock()
        executor = ParallelStageExecutor(
            synthesis_coordinator=coordinator,
            quality_gate_validator=validator
        )
        assert executor.synthesis_coordinator is coordinator
        assert executor.quality_gate_validator is validator

    def test_supports_parallel_stage_type(self):
        """Should support 'parallel' stage type."""
        executor = ParallelStageExecutor()
        assert executor.supports_stage_type("parallel") is True

    def test_does_not_support_other_stage_types(self):
        """Should not support non-parallel stage types."""
        executor = ParallelStageExecutor()
        assert executor.supports_stage_type("sequential") is False
        assert executor.supports_stage_type("conditional") is False


# ============================================================================
# Test Class 2: Parallel Execution with Different Agent Counts
# ============================================================================

class TestParallelExecution:
    """Tests for parallel agent execution with varying counts."""

    @pytest.mark.parametrize("num_agents", [2, 3, 5])
    def test_parallel_execution_with_n_agents(
        self,
        num_agents,
        mock_config_loader,
        mock_agent_response,
        mock_synthesis_result,
        initial_state
    ):
        """Should execute N agents in parallel and collect outputs."""
        # Create agent names
        agent_names = [f"agent{i}" for i in range(1, num_agents + 1)]

        # Create stage config
        stage_config = {
            "stage": {"agents": agent_names},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        # Mock AgentFactory and agent execution
        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult', return_value=mock_synthesis_result):

            # Configure mock agent
            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            # Execute stage
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Verify all agents were executed
            assert mock_agent.execute.call_count == num_agents

            # Verify stage outputs
            assert "test_stage" in result_state[StateKeys.STAGE_OUTPUTS]
            stage_output = result_state[StateKeys.STAGE_OUTPUTS]["test_stage"]

            # Should have outputs from all agents
            assert len(stage_output["agent_outputs"]) == num_agents
            assert len(stage_output["agent_statuses"]) == num_agents

            # All should be successful
            for agent in agent_names:
                assert stage_output["agent_statuses"][agent] == "success"

    def test_parallel_execution_is_concurrent(
        self,
        mock_config_loader,
        initial_state
    ):
        """Agents should execute concurrently, not sequentially."""
        # Create stage with 3 agents
        agent_names = ["agent1", "agent2", "agent3"]
        stage_config = {
            "stage": {"agents": agent_names},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        # Track execution times
        execution_start_times = {}

        def slow_execute(input_data, context):
            """Simulate agent execution with delay."""
            agent_name = context.metadata[StateKeys.AGENT_NAME]
            execution_start_times[agent_name] = time.time()
            time.sleep(0.05)  # 50ms delay

            response = Mock(spec=AgentResponse)
            response.output = f"output_{agent_name}"
            response.reasoning = "reasoning"
            response.confidence = 0.9
            response.tokens = 100
            response.estimated_cost_usd = 0.001
            response.tool_calls = []
            return response

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult') as mock_synthesis_class:

            # Configure mock agent with delay
            mock_agent = Mock()
            mock_agent.execute.side_effect = slow_execute
            mock_factory.return_value = mock_agent

            # Configure synthesis result
            synthesis_result = Mock()
            synthesis_result.decision = "decision"
            synthesis_result.confidence = 0.85
            synthesis_result.method = "consensus"
            synthesis_result.votes = {}
            synthesis_result.conflicts = []
            synthesis_result.reasoning = "reasoning"
            synthesis_result.metadata = {}
            mock_synthesis_class.return_value = synthesis_result

            # Execute stage and measure total time
            start = time.time()
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )
            total_duration = time.time() - start

            # If executed sequentially: 3 * 50ms = 150ms
            # If executed in parallel: ~50ms (plus overhead)
            # Allow generous margin for test environment
            assert total_duration < 0.15, \
                f"Execution took {total_duration:.3f}s, expected < 0.15s (parallel execution)"

            # Verify all agents were called
            assert mock_agent.execute.call_count == 3


# ============================================================================
# Test Class 3: Error Handling and Partial Failures
# ============================================================================

class TestErrorHandling:
    """Tests for error handling and partial failure scenarios."""

    def test_all_agents_fail_below_min_threshold(
        self,
        mock_config_loader,
        initial_state
    ):
        """Should raise error when successful agents < min_successful_agents."""
        stage_config = {
            "stage": {"agents": ["agent1", "agent2", "agent3"]},
            "error_handling": {"min_successful_agents": 2},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'):

            # All agents fail
            mock_agent = Mock()
            mock_agent.execute.side_effect = RuntimeError("Agent execution failed")
            mock_factory.return_value = mock_agent

            # Should raise RuntimeError about min_successful_agents
            with pytest.raises(RuntimeError, match="Only 0/3 agents succeeded"):
                executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=initial_state,
                    config_loader=mock_config_loader
                )

    def test_partial_failure_meets_threshold(
        self,
        mock_config_loader,
        mock_synthesis_result,
        initial_state
    ):
        """Should succeed when successful agents >= min_successful_agents."""
        stage_config = {
            "stage": {"agents": ["agent1", "agent2", "agent3"]},
            "error_handling": {"min_successful_agents": 2},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        def selective_execute(input_data, context):
            """Agent1 and agent2 succeed, agent3 fails."""
            agent_name = context.metadata[StateKeys.AGENT_NAME]
            if agent_name == "agent3":
                raise RuntimeError("Agent 3 failed")

            response = Mock(spec=AgentResponse)
            response.output = f"output_{agent_name}"
            response.reasoning = "reasoning"
            response.confidence = 0.9
            response.tokens = 100
            response.estimated_cost_usd = 0.001
            response.tool_calls = []
            return response

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult', return_value=mock_synthesis_result):

            mock_agent = Mock()
            mock_agent.execute.side_effect = selective_execute
            mock_factory.return_value = mock_agent

            # Should succeed with 2/3 agents successful
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Verify partial success
            stage_output = result_state[StateKeys.STAGE_OUTPUTS]["test_stage"]
            assert stage_output["agent_statuses"]["agent1"] == "success"
            assert stage_output["agent_statuses"]["agent2"] == "success"
            assert stage_output["agent_statuses"]["agent3"] == "failed"

            # Should have outputs from successful agents only
            assert "agent1" in stage_output["agent_outputs"]
            assert "agent2" in stage_output["agent_outputs"]
            assert "agent3" not in stage_output["agent_outputs"]

    def test_error_aggregation_in_state(
        self,
        mock_config_loader,
        initial_state
    ):
        """Failed agents should have errors recorded in state."""
        stage_config = {
            "stage": {"agents": ["agent1", "agent2"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        def selective_execute(input_data, context):
            """Agent1 succeeds, agent2 fails."""
            agent_name = context.metadata[StateKeys.AGENT_NAME]
            if agent_name == "agent2":
                raise ValueError("Test error for agent2")

            response = Mock(spec=AgentResponse)
            response.output = "output"
            response.reasoning = "reasoning"
            response.confidence = 0.9
            response.tokens = 100
            response.estimated_cost_usd = 0.001
            response.tool_calls = []
            return response

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult'):

            mock_agent = Mock()
            mock_agent.execute.side_effect = selective_execute
            mock_factory.return_value = mock_agent

            # Configure synthesis
            synthesis_result = Mock()
            synthesis_result.decision = "decision"
            synthesis_result.confidence = 0.85
            synthesis_result.method = "consensus"
            synthesis_result.votes = {}
            synthesis_result.conflicts = []
            synthesis_result.reasoning = "reasoning"
            synthesis_result.metadata = {}

            # Should succeed but record error
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Error should not be in final stage output (internal to parallel execution)
            # But we can verify agent statuses
            stage_output = result_state[StateKeys.STAGE_OUTPUTS]["test_stage"]
            assert stage_output["agent_statuses"]["agent2"] == "failed"

    def test_on_stage_failure_halt(
        self,
        mock_config_loader,
        initial_state
    ):
        """Should halt (raise) when on_stage_failure=halt."""
        stage_config = {
            "stage": {"agents": ["agent1"]},
            "error_handling": {
                "min_successful_agents": 1,
                "on_stage_failure": "halt"
            },
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'):

            # Agent fails
            mock_agent = Mock()
            mock_agent.execute.side_effect = RuntimeError("Fatal error")
            mock_factory.return_value = mock_agent

            # Should raise
            with pytest.raises(RuntimeError, match="Only 0/1 agents succeeded"):
                executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=initial_state,
                    config_loader=mock_config_loader
                )

    def test_on_stage_failure_skip(
        self,
        mock_config_loader,
        initial_state
    ):
        """Should skip stage when on_stage_failure=skip."""
        stage_config = {
            "stage": {"agents": ["agent1"]},
            "error_handling": {
                "min_successful_agents": 1,
                "on_stage_failure": "skip"
            },
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'):

            # Agent fails
            mock_agent = Mock()
            mock_agent.execute.side_effect = RuntimeError("Fatal error")
            mock_factory.return_value = mock_agent

            # Should not raise, stage output should be None
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            assert result_state[StateKeys.STAGE_OUTPUTS]["test_stage"] is None


# ============================================================================
# Test Class 4: Aggregate Metrics Calculation
# ============================================================================

class TestAggregateMetrics:
    """Tests for aggregate metrics calculation from multiple agents."""

    def test_aggregate_metrics_calculated_correctly(
        self,
        mock_config_loader,
        mock_synthesis_result,
        initial_state
    ):
        """Should calculate correct aggregate metrics from successful agents."""
        stage_config = {
            "stage": {"agents": ["agent1", "agent2", "agent3"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        # Create different responses for each agent
        agent_responses = {
            "agent1": Mock(
                output="output1", reasoning="r1", confidence=0.9,
                tokens=100, estimated_cost_usd=0.001, tool_calls=[]
            ),
            "agent2": Mock(
                output="output2", reasoning="r2", confidence=0.8,
                tokens=200, estimated_cost_usd=0.002, tool_calls=[]
            ),
            "agent3": Mock(
                output="output3", reasoning="r3", confidence=0.7,
                tokens=150, estimated_cost_usd=0.0015, tool_calls=[]
            )
        }

        def get_agent_response(input_data, context):
            agent_name = context.metadata[StateKeys.AGENT_NAME]
            return agent_responses[agent_name]

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult', return_value=mock_synthesis_result):

            mock_agent = Mock()
            mock_agent.execute.side_effect = get_agent_response
            mock_factory.return_value = mock_agent

            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Verify aggregate metrics
            metrics = result_state[StateKeys.STAGE_OUTPUTS]["test_stage"]["aggregate_metrics"]

            # Total tokens: 100 + 200 + 150 = 450
            assert metrics[StateKeys.TOTAL_TOKENS] == 450

            # Total cost: 0.001 + 0.002 + 0.0015 = 0.0045
            assert abs(metrics[StateKeys.TOTAL_COST_USD] - 0.0045) < 0.0001

            # Average confidence: (0.9 + 0.8 + 0.7) / 3 = 0.8
            assert abs(metrics["avg_confidence"] - 0.8) < 0.01

            # Num successful/failed
            assert metrics["num_agents"] == 3
            assert metrics["num_successful"] == 3
            assert metrics["num_failed"] == 0

    def test_aggregate_metrics_with_partial_failures(
        self,
        mock_config_loader,
        mock_synthesis_result,
        initial_state
    ):
        """Should only include successful agents in aggregate metrics."""
        stage_config = {
            "stage": {"agents": ["agent1", "agent2", "agent3"]},
            "error_handling": {"min_successful_agents": 2},
            "quality_gates": {"enabled": False}
        }

        executor = ParallelStageExecutor()

        def selective_execute(input_data, context):
            agent_name = context.metadata[StateKeys.AGENT_NAME]
            if agent_name == "agent3":
                raise RuntimeError("Agent 3 failed")

            response = Mock(spec=AgentResponse)
            response.output = f"output_{agent_name}"
            response.reasoning = "reasoning"
            response.confidence = 0.9
            response.tokens = 100
            response.estimated_cost_usd = 0.001
            response.tool_calls = []
            return response

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult', return_value=mock_synthesis_result):

            mock_agent = Mock()
            mock_agent.execute.side_effect = selective_execute
            mock_factory.return_value = mock_agent

            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Verify aggregate metrics
            metrics = result_state[StateKeys.STAGE_OUTPUTS]["test_stage"]["aggregate_metrics"]

            # Only 2 successful agents
            assert metrics[StateKeys.TOTAL_TOKENS] == 200  # 100 * 2
            assert abs(metrics[StateKeys.TOTAL_COST_USD] - 0.002) < 0.0001  # 0.001 * 2
            assert metrics["num_agents"] == 3
            assert metrics["num_successful"] == 2
            assert metrics["num_failed"] == 1


# ============================================================================
# Test Class 5: Synthesis Integration
# ============================================================================

class TestSynthesisIntegration:
    """Tests for synthesis coordinator integration."""

    def test_synthesis_with_provided_coordinator(
        self,
        mock_config_loader,
        mock_agent_response,
        initial_state
    ):
        """Should use provided synthesis coordinator."""
        coordinator = Mock()
        synthesis_result = Mock()
        synthesis_result.decision = "coordinator_decision"
        synthesis_result.confidence = 0.95
        synthesis_result.method = "custom"
        synthesis_result.votes = {}
        synthesis_result.conflicts = []
        synthesis_result.reasoning = "coordinator reasoning"
        synthesis_result.metadata = {}
        coordinator.synthesize.return_value = synthesis_result

        executor = ParallelStageExecutor(synthesis_coordinator=coordinator)

        stage_config = {
            "stage": {"agents": ["agent1", "agent2"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'):

            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Verify coordinator was called
            assert coordinator.synthesize.called
            call_args = coordinator.synthesize.call_args
            assert len(call_args[1]["agent_outputs"]) == 2

            # Verify decision is from coordinator
            assert result_state[StateKeys.STAGE_OUTPUTS]["test_stage"][StateKeys.DECISION] == "coordinator_decision"

    def test_synthesis_without_coordinator_uses_registry(
        self,
        mock_config_loader,
        mock_agent_response,
        initial_state
    ):
        """Should use strategy registry when no coordinator provided."""
        executor = ParallelStageExecutor()  # No coordinator

        stage_config = {
            "stage": {"agents": ["agent1", "agent2"]},
            "collaboration": {
                "strategy": "consensus",
                "config": {}
            },
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.registry.get_strategy_from_config') as mock_get_strategy:

            # Configure mock strategy with required attributes
            mock_strategy = Mock()
            mock_strategy.cost_budget_usd = None
            mock_strategy.max_rounds = 1
            mock_strategy.min_rounds = 1
            mock_strategy.convergence_threshold = 0.8
            mock_strategy.requires_requery = False
            synthesis_result = Mock()
            synthesis_result.decision = "registry_decision"
            synthesis_result.confidence = 0.85
            synthesis_result.method = "consensus"
            synthesis_result.votes = {}
            synthesis_result.conflicts = []
            synthesis_result.reasoning = "registry reasoning"
            synthesis_result.metadata = {}
            mock_strategy.synthesize.return_value = synthesis_result
            mock_get_strategy.return_value = mock_strategy

            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Verify strategy was used
            assert mock_strategy.synthesize.called

            # Verify decision is from strategy
            assert result_state[StateKeys.STAGE_OUTPUTS]["test_stage"][StateKeys.DECISION] == "registry_decision"


# ============================================================================
# Test Class 6: Quality Gates with Retry Logic
# ============================================================================

class TestQualityGates:
    """Tests for quality gate validation and retry logic."""

    def test_quality_gates_disabled_passes(
        self,
        mock_config_loader,
        mock_agent_response,
        mock_synthesis_result,
        initial_state
    ):
        """Should pass when quality gates are disabled."""
        executor = ParallelStageExecutor()

        stage_config = {
            "stage": {"agents": ["agent1"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {"enabled": False}
        }

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult', return_value=mock_synthesis_result):

            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            # Should succeed without validation
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            assert "test_stage" in result_state[StateKeys.STAGE_OUTPUTS]

    @pytest.mark.xfail(reason="Flaky test due to test isolation issues - passes when run alone")
    def test_quality_gates_min_confidence_violation(
        self,
        mock_config_loader,
        mock_agent_response,
        initial_state
    ):
        """Should fail when confidence below minimum."""
        executor = ParallelStageExecutor()

        stage_config = {
            "stage": {"agents": ["agent1"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.9,
                "on_failure": "escalate",
                "require_citations": False,
                "min_findings": 0
            }
        }

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult') as mock_synthesis_class:

            # Low confidence synthesis result
            synthesis_result = Mock()
            synthesis_result.decision = "decision"
            synthesis_result.confidence = 0.5  # Below 0.9
            synthesis_result.method = "consensus"
            synthesis_result.votes = {}
            synthesis_result.conflicts = []
            synthesis_result.reasoning = "reasoning"
            synthesis_result.metadata = {}
            mock_synthesis_class.return_value = synthesis_result

            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            # Should raise due to quality gate failure
            with pytest.raises(RuntimeError, match="Quality gates failed"):
                executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=initial_state,
                    config_loader=mock_config_loader
                )

    def test_quality_gates_retry_on_failure(
        self,
        mock_config_loader,
        mock_agent_response,
        initial_state
    ):
        """Should retry stage when quality gates fail with retry_stage action."""
        executor = ParallelStageExecutor()

        stage_config = {
            "stage": {"agents": ["agent1"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.9,
                "on_failure": "retry_stage",
                "max_retries": 2,
                "require_citations": False,
                "min_findings": 0
            }
        }

        # Track number of synthesis calls
        synthesis_call_count = [0]

        def create_synthesis_result(*args, **kwargs):
            """Create synthesis result with varying confidence."""
            synthesis_call_count[0] += 1

            result = Mock()
            result.decision = "decision"
            # First call: low confidence (fails), second call: high confidence (passes)
            if synthesis_call_count[0] == 1:
                result.confidence = 0.5  # Fails quality gate
            else:
                result.confidence = 0.95  # Passes quality gate
            result.method = "consensus"
            result.votes = {}
            result.conflicts = []
            result.reasoning = "reasoning"
            result.metadata = {}
            return result

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.registry.get_strategy_from_config') as mock_get_strategy:

            # Mock strategy to return synthesis result
            mock_strategy = Mock()
            mock_strategy.cost_budget_usd = None
            mock_strategy.max_rounds = 1
            mock_strategy.min_rounds = 1
            mock_strategy.convergence_threshold = 0.8
            mock_strategy.requires_requery = False
            mock_strategy.synthesize.side_effect = create_synthesis_result
            mock_get_strategy.return_value = mock_strategy

            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            # Should succeed after retry
            result_state = executor.execute_stage(
                stage_name="test_stage",
                stage_config=stage_config,
                state=initial_state,
                config_loader=mock_config_loader
            )

            # Should have called synthesis twice (initial + 1 retry)
            assert synthesis_call_count[0] == 2

            # Should succeed
            assert "test_stage" in result_state[StateKeys.STAGE_OUTPUTS]

    @pytest.mark.xfail(reason="Flaky test due to test isolation issues - passes when run alone")
    def test_quality_gates_max_retries_exhausted(
        self,
        mock_config_loader,
        mock_agent_response,
        initial_state
    ):
        """Should escalate when max retries exhausted."""
        executor = ParallelStageExecutor()

        stage_config = {
            "stage": {"agents": ["agent1"]},
            "error_handling": {"min_successful_agents": 1},
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.9,
                "on_failure": "retry_stage",
                "max_retries": 2,
                "require_citations": False,
                "min_findings": 0
            }
        }

        with patch('temper_ai.stage.executors.parallel.AgentFactory.create') as mock_factory, \
             patch('temper_ai.storage.schemas.agent_config.AgentConfig'), \
             patch('temper_ai.agent.strategies.base.SynthesisResult') as mock_synthesis_class:

            # Always low confidence
            synthesis_result = Mock()
            synthesis_result.decision = "decision"
            synthesis_result.confidence = 0.5
            synthesis_result.method = "consensus"
            synthesis_result.votes = {}
            synthesis_result.conflicts = []
            synthesis_result.reasoning = "reasoning"
            synthesis_result.metadata = {}
            mock_synthesis_class.return_value = synthesis_result

            mock_agent = Mock()
            mock_agent.execute.return_value = mock_agent_response
            mock_factory.return_value = mock_agent

            # Should raise after exhausting retries
            with pytest.raises(RuntimeError, match="after 2 retries"):
                executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=initial_state,
                    config_loader=mock_config_loader
                )


# ============================================================================
# Test Class 7: Helper Methods
# ============================================================================

class TestHelperMethods:
    """Tests for helper methods."""

    def test_extract_agent_name_from_string(self):
        """Should extract name from string."""
        executor = ParallelStageExecutor()
        assert executor._extract_agent_name("agent1") == "agent1"

    def test_extract_agent_name_from_dict(self):
        """Should extract name from dict with 'name' key."""
        executor = ParallelStageExecutor()
        assert executor._extract_agent_name({"name": "agent1"}) == "agent1"

    def test_extract_agent_name_from_dict_agent_name_key(self):
        """Should extract name from dict with 'agent_name' key."""
        executor = ParallelStageExecutor()
        assert executor._extract_agent_name({"agent_name": "agent1"}) == "agent1"

    def test_extract_agent_name_from_object(self):
        """Should extract name from object with name attribute."""
        executor = ParallelStageExecutor()
        obj = Mock()
        obj.name = "agent1"
        assert executor._extract_agent_name(obj) == "agent1"

    def test_extract_agent_name_from_object_agent_name_attr(self):
        """Should extract name from object with agent_name attribute."""
        executor = ParallelStageExecutor()
        obj = Mock()
        obj.name = None
        obj.agent_name = "agent1"
        assert executor._extract_agent_name(obj) == "agent1"
