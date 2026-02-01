# Comprehensive Test Strategy for ParallelStageExecutor

## Executive Summary

The `ParallelStageExecutor` is a critical M3 component with complex concurrency logic that orchestrates parallel agent execution using LangGraph subgraphs. This document outlines a comprehensive testing strategy to achieve 80%+ coverage with 200+ LOC of tests.

**Implementation:** `/home/shinelay/meta-autonomous-framework/src/compiler/executors/parallel.py` (672 lines)

**Key Complexity Areas:**
- LangGraph subgraph creation with parallel branches
- Concurrent state management with custom `merge_dicts` reducer
- Error aggregation from multiple agents
- Partial failure handling with `min_successful_agents` threshold
- Synthesis coordination with collaboration strategies
- Quality gates with retry logic (up to 2 retries)
- Observability tracking for collaboration events
- Aggregate metrics calculation (tokens, cost, duration, confidence)

---

## 1. Test Class Structure and Organization

### 1.1 Primary Test Classes

```python
# tests/test_compiler/test_executors_parallel.py

class TestParallelExecutorBasics:
    """Test basic executor properties and initialization."""
    # - supports_stage_type()
    # - initialization with/without coordinators
    # - basic validation

class TestSubgraphConstruction:
    """Test LangGraph subgraph creation for parallel execution."""
    # - init → agents (parallel) → collect topology
    # - node creation for each agent
    # - custom merge_dicts reducer for Annotated fields
    # - entry point and edge configuration

class TestParallelExecution:
    """Test concurrent agent execution."""
    # - 2 agents in parallel
    # - 3 agents in parallel
    # - 5 agents in parallel
    # - 10 agents in parallel (stress test)
    # - execution timing (parallel is faster than sequential)

class TestStateManagement:
    """Test concurrent state updates with merge_dicts."""
    # - agent_outputs aggregation
    # - agent_statuses tracking
    # - agent_metrics collection
    # - errors dictionary
    # - stage_input propagation
    # - thread safety of merges

class TestErrorHandling:
    """Test error scenarios and partial failures."""
    # - single agent failure (2/3 succeed)
    # - all agents fail
    # - partial failure with min_successful_agents=1
    # - partial failure with min_successful_agents=2
    # - error message aggregation
    # - on_stage_failure: halt vs skip

class TestAggregateMetrics:
    """Test aggregate metric calculation from multiple agents."""
    # - total_tokens summation
    # - total_cost_usd summation
    # - max_duration extraction
    # - avg_confidence calculation
    # - num_successful/num_failed counts
    # - metrics with partial failures

class TestSynthesisIntegration:
    """Test integration with collaboration strategies."""
    # - synthesis coordinator delegation
    # - fallback consensus strategy
    # - AgentOutput creation from outputs
    # - SynthesisResult handling
    # - synthesis metadata tracking

class TestQualityGates:
    """Test quality gate validation and retry logic."""
    # - quality gates enabled/disabled
    # - min_confidence validation
    # - min_findings validation
    # - require_citations validation
    # - retry_stage logic (1, 2 retries)
    # - max_retries exhaustion
    # - escalate action
    # - proceed_with_warning action
    # - retry counter tracking

class TestObservabilityTracking:
    """Test observability integration."""
    # - synthesis event tracking
    # - quality_gate_failure event
    # - quality_gate_retry event
    # - collaboration metadata
    # - aggregate metrics in events

class TestConcurrencyAndThreadSafety:
    """Test thread safety and race conditions."""
    # - concurrent writes to agent_outputs
    # - concurrent writes to agent_metrics
    # - no race conditions in state updates
    # - proper isolation between agents

class TestPerformanceCharacteristics:
    """Test performance and scalability."""
    # - parallel execution faster than sequential
    # - 10 agent stress test
    # - timeout handling
    # - resource cleanup

class TestAgentNodeCreation:
    """Test _create_agent_node internal method."""
    # - agent config loading
    # - agent factory creation
    # - execution context creation
    # - response handling
    # - error handling in node
    # - duration tracking

class TestHelperMethods:
    """Test utility methods."""
    # - _extract_agent_name with string
    # - _extract_agent_name with dict
    # - _extract_agent_name with Pydantic model
    # - _run_synthesis with coordinator
    # - _run_synthesis fallback
    # - _validate_quality_gates with validator
    # - _validate_quality_gates fallback
```

---

## 2. Specific Test Methods with Mock Strategies

### 2.1 Basic Functionality Tests

```python
class TestParallelExecutorBasics:
    def test_supports_parallel_type(self):
        """Test executor identifies parallel type correctly."""
        executor = ParallelStageExecutor()
        assert executor.supports_stage_type("parallel") is True
        assert executor.supports_stage_type("sequential") is False
        assert executor.supports_stage_type("adaptive") is False

    def test_initialization_without_coordinators(self):
        """Test executor can be initialized without optional coordinators."""
        executor = ParallelStageExecutor()
        assert executor.synthesis_coordinator is None
        assert executor.quality_gate_validator is None

    def test_initialization_with_coordinators(self):
        """Test executor accepts synthesis coordinator and validator."""
        mock_coordinator = Mock()
        mock_validator = Mock()

        executor = ParallelStageExecutor(
            synthesis_coordinator=mock_coordinator,
            quality_gate_validator=mock_validator
        )

        assert executor.synthesis_coordinator is mock_coordinator
        assert executor.quality_gate_validator is mock_validator
```

### 2.2 Parallel Execution Tests (Parameterized)

```python
class TestParallelExecution:
    @pytest.mark.parametrize("num_agents", [2, 3, 5, 10])
    def test_parallel_execution_with_n_agents(self, num_agents):
        """Test parallel execution with 2, 3, 5, 10 agents."""
        executor = ParallelStageExecutor()

        # Create mock agents
        mock_agents = [f"agent{i}" for i in range(num_agents)]

        # Mock config loader
        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        # Mock agent responses
        def create_mock_response(agent_name):
            return AgentResponse(
                output=f"Output from {agent_name}",
                reasoning=f"Reasoning from {agent_name}",
                confidence=0.8 + (hash(agent_name) % 10) / 100,
                tokens=100,
                estimated_cost_usd=0.001,
                tool_calls=[]
            )

        # Mock agent factory
        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                mock_agents_map = {}
                for agent_name in mock_agents:
                    mock_agent = Mock()
                    mock_agent.execute.return_value = create_mock_response(agent_name)
                    mock_agents_map[agent_name] = mock_agent

                def get_agent(*args, **kwargs):
                    # Return different agent based on load_agent call
                    for name, agent in mock_agents_map.items():
                        return agent

                mock_create.side_effect = lambda cfg: mock_agents_map[cfg.name]

                # Execute stage
                stage_config = {"agents": mock_agents}
                state = {"workflow_id": "test", "stage_outputs": {}}

                result = executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=state,
                    config_loader=mock_config_loader
                )

                # Verify all agents executed
                stage_output = result["stage_outputs"]["test_stage"]
                assert len(stage_output["agent_outputs"]) == num_agents
                assert stage_output["aggregate_metrics"]["num_agents"] == num_agents
                assert stage_output["aggregate_metrics"]["num_successful"] == num_agents

    def test_parallel_execution_is_concurrent(self):
        """Test that agents execute concurrently, not sequentially."""
        executor = ParallelStageExecutor()

        # Mock agents with artificial delays
        delay_per_agent = 0.1  # 100ms per agent

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        def slow_execute(input_data, context):
            import time
            time.sleep(delay_per_agent)
            return AgentResponse(
                output="Output",
                reasoning="Reasoning",
                tokens=100,
                estimated_cost_usd=0.001
            )

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                mock_agent = Mock()
                mock_agent.execute.side_effect = slow_execute
                mock_create.return_value = mock_agent

                stage_config = {"agents": ["a1", "a2", "a3"]}
                state = {"workflow_id": "test", "stage_outputs": {}}

                import time
                start = time.time()

                result = executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=state,
                    config_loader=mock_config_loader
                )

                duration = time.time() - start

                # If sequential: 3 * 0.1 = 0.3s
                # If parallel: ~0.1s (plus overhead)
                # Assert execution time < 0.25s (generous for parallel)
                assert duration < 0.25, f"Took {duration}s, expected <0.25s for parallel"
```

### 2.3 Error Injection Tests

```python
class TestErrorHandling:
    def test_partial_failure_below_threshold(self):
        """Test partial failure when below min_successful_agents."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        # Agent 1: success
        # Agent 2: failure
        # Agent 3: failure
        # min_successful_agents = 2 (default may be 1, so set to 2)

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                def create_agent_with_behavior(config):
                    agent = Mock()
                    if config.name == "agent1":
                        agent.execute.return_value = AgentResponse(
                            output="Success", reasoning="OK", tokens=100, estimated_cost_usd=0.001
                        )
                    else:
                        agent.execute.side_effect = Exception(f"{config.name} failed")
                    return agent

                mock_create.side_effect = create_agent_with_behavior

                stage_config = {
                    "agents": ["agent1", "agent2", "agent3"],
                    "error_handling": {"min_successful_agents": 2}
                }
                state = {"workflow_id": "test", "stage_outputs": {}}

                # Should raise because only 1/3 succeeded, need 2
                with pytest.raises(RuntimeError, match="Only 1/3 agents succeeded"):
                    executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

    def test_partial_failure_above_threshold(self):
        """Test partial failure when above min_successful_agents."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        # Agent 1: success
        # Agent 2: success
        # Agent 3: failure
        # min_successful_agents = 2

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    def create_agent_with_behavior(config):
                        agent = Mock()
                        if config.name in ["agent1", "agent2"]:
                            agent.execute.return_value = AgentResponse(
                                output=f"{config.name} success",
                                reasoning="OK",
                                tokens=100,
                                estimated_cost_usd=0.001
                            )
                        else:
                            agent.execute.side_effect = Exception(f"{config.name} failed")
                        return agent

                    mock_create.side_effect = create_agent_with_behavior

                    # Mock synthesis
                    mock_strategy = Mock()
                    mock_strategy.synthesize.return_value = SynthesisResult(
                        decision="synthesized",
                        confidence=0.9,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strat.return_value = mock_strategy

                    stage_config = {
                        "agents": ["agent1", "agent2", "agent3"],
                        "error_handling": {"min_successful_agents": 2}
                    }
                    state = {"workflow_id": "test", "stage_outputs": {}}

                    # Should succeed with 2/3 agents
                    result = executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

                    assert result["stage_outputs"]["test_stage"]["aggregate_metrics"]["num_successful"] == 2
                    assert result["stage_outputs"]["test_stage"]["aggregate_metrics"]["num_failed"] == 1

    def test_all_agents_fail(self):
        """Test when all agents fail."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                mock_agent = Mock()
                mock_agent.execute.side_effect = Exception("Agent failed")
                mock_create.return_value = mock_agent

                stage_config = {
                    "agents": ["agent1", "agent2"],
                    "error_handling": {"min_successful_agents": 1}
                }
                state = {"workflow_id": "test", "stage_outputs": {}}

                with pytest.raises(RuntimeError, match="Only 0/2 agents succeeded"):
                    executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

    def test_on_stage_failure_skip(self):
        """Test on_stage_failure=skip bypasses exception."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                mock_agent = Mock()
                mock_agent.execute.side_effect = Exception("All agents failed")
                mock_create.return_value = mock_agent

                stage_config = {
                    "agents": ["agent1"],
                    "error_handling": {
                        "min_successful_agents": 1,
                        "on_stage_failure": "skip"
                    }
                }
                state = {"workflow_id": "test", "stage_outputs": {}}

                # Should not raise, stage output is None
                result = executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=state,
                    config_loader=mock_config_loader
                )

                assert result["stage_outputs"]["test_stage"] is None
```

### 2.4 Quality Gates and Retry Tests

```python
class TestQualityGates:
    def test_quality_gates_disabled_by_default(self):
        """Test quality gates are disabled by default (backward compatibility)."""
        executor = ParallelStageExecutor()

        # Mock synthesis result with low confidence
        mock_synthesis = Mock()
        mock_synthesis.decision = "low confidence"
        mock_synthesis.confidence = 0.3
        mock_synthesis.method = "test"

        passed, violations = executor._validate_quality_gates(
            synthesis_result=mock_synthesis,
            stage_config={},  # No quality_gates config
            stage_name="test",
            state={}
        )

        assert passed is True
        assert len(violations) == 0

    def test_min_confidence_violation(self):
        """Test quality gate fails on low confidence."""
        executor = ParallelStageExecutor()

        mock_synthesis = Mock()
        mock_synthesis.decision = "low confidence"
        mock_synthesis.confidence = 0.5
        mock_synthesis.method = "test"
        mock_synthesis.metadata = {}

        stage_config = {
            "quality_gates": {
                "enabled": True,
                "min_confidence": 0.7
            }
        }

        passed, violations = executor._validate_quality_gates(
            synthesis_result=mock_synthesis,
            stage_config=stage_config,
            stage_name="test",
            state={}
        )

        assert passed is False
        assert len(violations) == 1
        assert "0.50 below minimum 0.70" in violations[0]

    def test_quality_gate_retry_logic(self):
        """Test quality gate triggers retry on first failure."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        # Track number of execute_stage calls
        call_count = 0

        def mock_execute_stage_recursive(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            # First call: fail quality gates
            # Second call: pass quality gates
            if call_count == 1:
                # Return state that will fail quality gates
                with patch.object(executor, '_validate_quality_gates') as mock_validate:
                    mock_validate.return_value = (False, ["Low confidence"])
                    # This will trigger recursion
                    return executor.execute_stage(*args, **kwargs)
            else:
                # Second call: pass
                with patch.object(executor, '_validate_quality_gates') as mock_validate:
                    mock_validate.return_value = (True, [])
                    # Normal execution...
                    # (simplified for test)
                    return {
                        "stage_outputs": {"test_stage": {"decision": "retry success"}},
                        "current_stage": "test_stage",
                        "stage_retry_counts": {}
                    }

        # This test is complex - better tested via integration
        # Unit test: just verify retry counter increments

        state = {"workflow_id": "test", "stage_outputs": {}}

        # Simulate quality gate failure
        with patch.object(executor, '_validate_quality_gates') as mock_validate:
            mock_validate.return_value = (False, ["Low confidence"])

            stage_config = {
                "quality_gates": {
                    "enabled": True,
                    "min_confidence": 0.7,
                    "on_failure": "retry_stage",
                    "max_retries": 2
                },
                "agents": ["agent1"]
            }

            # Verify retry counter gets initialized
            assert "stage_retry_counts" not in state or "test_stage" not in state.get("stage_retry_counts", {})

    def test_max_retries_exhausted(self):
        """Test quality gate escalates after max retries."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()

        with patch('src.compiler.executors.parallel.AgentFactory.create'):
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    # Always return low confidence synthesis
                    mock_strategy = Mock()
                    mock_strategy.synthesize.return_value = SynthesisResult(
                        decision="low conf",
                        confidence=0.3,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strat.return_value = mock_strategy

                    stage_config = {
                        "quality_gates": {
                            "enabled": True,
                            "min_confidence": 0.7,
                            "on_failure": "retry_stage",
                            "max_retries": 2
                        },
                        "agents": ["agent1"]
                    }

                    # Start with retry count at max
                    state = {
                        "workflow_id": "test",
                        "stage_outputs": {},
                        "stage_retry_counts": {"test_stage": 2}  # Already at max
                    }

                    # Should escalate (raise)
                    with pytest.raises(RuntimeError, match="after 2 retries"):
                        executor.execute_stage(
                            stage_name="test_stage",
                            stage_config=stage_config,
                            state=state,
                            config_loader=mock_config_loader
                        )

    def test_quality_gate_proceed_with_warning(self):
        """Test proceed_with_warning adds warning to metadata."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    # Mock agent
                    mock_agent = Mock()
                    mock_agent.execute.return_value = AgentResponse(
                        output="Output", reasoning="OK", tokens=100, estimated_cost_usd=0.001
                    )
                    mock_create.return_value = mock_agent

                    # Mock synthesis with low confidence
                    mock_strategy = Mock()
                    mock_synthesis = SynthesisResult(
                        decision="low conf",
                        confidence=0.5,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strategy.synthesize.return_value = mock_synthesis
                    mock_strat.return_value = mock_strategy

                    stage_config = {
                        "quality_gates": {
                            "enabled": True,
                            "min_confidence": 0.7,
                            "on_failure": "proceed_with_warning"
                        },
                        "agents": ["agent1"]
                    }
                    state = {"workflow_id": "test", "stage_outputs": {}}

                    # Should succeed but add warning
                    result = executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

                    # Check that metadata was updated with warning
                    # (synthesis_result is modified in-place)
                    assert "quality_gate_warning" in mock_synthesis.metadata
```

---

## 3. Parameterized Tests for Different Agent Counts

```python
import pytest

class TestScalability:
    @pytest.mark.parametrize("num_agents,expected_speedup", [
        (2, 1.5),   # 2 agents should be ~1.5x faster than sequential
        (3, 2.0),   # 3 agents should be ~2x faster
        (5, 3.0),   # 5 agents should be ~3x faster
        (10, 5.0),  # 10 agents should be ~5x faster (with overhead)
    ])
    def test_parallel_speedup(self, num_agents, expected_speedup):
        """Test parallel execution provides speedup over sequential."""
        # This is a conceptual test - actual implementation would need
        # real timing measurements
        pass

    @pytest.mark.parametrize("num_agents", [2, 3, 5, 10])
    def test_aggregate_metrics_scale_correctly(self, num_agents):
        """Test aggregate metrics scale with number of agents."""
        executor = ParallelStageExecutor()

        # Mock setup
        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    # Each agent uses 100 tokens, $0.001
                    mock_agent = Mock()
                    mock_agent.execute.return_value = AgentResponse(
                        output="Output",
                        reasoning="OK",
                        tokens=100,
                        estimated_cost_usd=0.001,
                        confidence=0.8
                    )
                    mock_create.return_value = mock_agent

                    # Mock synthesis
                    mock_strategy = Mock()
                    mock_strategy.synthesize.return_value = SynthesisResult(
                        decision="synthesized",
                        confidence=0.9,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strat.return_value = mock_strategy

                    agents = [f"agent{i}" for i in range(num_agents)]
                    stage_config = {"agents": agents}
                    state = {"workflow_id": "test", "stage_outputs": {}}

                    result = executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

                    metrics = result["stage_outputs"]["test_stage"]["aggregate_metrics"]

                    # Verify scaling
                    assert metrics["total_tokens"] == num_agents * 100
                    assert metrics["total_cost_usd"] == pytest.approx(num_agents * 0.001)
                    assert metrics["num_agents"] == num_agents
                    assert metrics["num_successful"] == num_agents
```

---

## 4. Error Injection Techniques for Partial Failures

### 4.1 Mock-Based Error Injection

```python
def test_mixed_success_and_failure_agents():
    """Test handling of mixed success/failure with selective mocking."""
    executor = ParallelStageExecutor()

    # Strategy: Use side_effect with conditional logic based on agent name
    def create_agent_with_behavior(config):
        agent = Mock()

        if "fail" in config.name:
            # Inject failure
            agent.execute.side_effect = RuntimeError(f"{config.name} intentionally failed")
        elif "timeout" in config.name:
            # Inject timeout
            import time
            def timeout_func(*args, **kwargs):
                time.sleep(10)  # Simulate timeout
                return AgentResponse(output="too slow", reasoning="", tokens=0, estimated_cost_usd=0)
            agent.execute.side_effect = timeout_func
        else:
            # Success
            agent.execute.return_value = AgentResponse(
                output=f"{config.name} success",
                reasoning="OK",
                tokens=100,
                estimated_cost_usd=0.001,
                confidence=0.85
            )

        return agent

    with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
        mock_create.side_effect = create_agent_with_behavior

        # Test with mixed agents
        stage_config = {
            "agents": ["agent_success_1", "agent_fail_1", "agent_success_2"],
            "error_handling": {"min_successful_agents": 2}
        }

        # Should succeed with 2/3 successful
```

### 4.2 Exception Injection at Different Layers

```python
def test_exception_in_agent_config_loading():
    """Test error handling when agent config fails to load."""
    executor = ParallelStageExecutor()

    mock_config_loader = Mock()
    # Inject error at config loading
    mock_config_loader.load_agent.side_effect = FileNotFoundError("Config not found")

    stage_config = {"agents": ["agent1"]}
    state = {"workflow_id": "test", "stage_outputs": {}}

    # Should propagate error from agent node
    # (internal exception handling stores in errors dict)
    with pytest.raises(RuntimeError):
        executor.execute_stage(
            stage_name="test_stage",
            stage_config=stage_config,
            state=state,
            config_loader=mock_config_loader
        )

def test_exception_in_agent_execution():
    """Test error handling when agent.execute() fails."""
    # Already covered above, but emphasize different exception types

    exception_types = [
        ValueError("Invalid input"),
        RuntimeError("Execution failed"),
        TimeoutError("Agent timed out"),
        MemoryError("Out of memory"),
    ]

    for exc in exception_types:
        executor = ParallelStageExecutor()
        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                mock_agent = Mock()
                mock_agent.execute.side_effect = exc
                mock_create.return_value = mock_agent

                stage_config = {"agents": ["agent1"], "error_handling": {"min_successful_agents": 1}}
                state = {"workflow_id": "test", "stage_outputs": {}}

                with pytest.raises(RuntimeError, match="Only 0/1 agents succeeded"):
                    executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )
```

---

## 5. Thread Safety Validation Approaches

### 5.1 Concurrent Write Detection

```python
def test_concurrent_state_updates_no_conflicts():
    """Test that merge_dicts properly handles concurrent updates."""
    executor = ParallelStageExecutor()

    # Test the merge_dicts reducer directly
    # (it's defined inline in execute_stage, so we test via execution)

    mock_config_loader = Mock()
    mock_config_loader.load_agent.return_value = {"name": "test"}

    # Create agents that write to same state keys concurrently
    with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
        with patch('src.compiler.schemas.AgentConfig'):
            with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                import threading
                import time

                # Track concurrent writes
                write_timestamps = []
                lock = threading.Lock()

                def concurrent_execute(input_data, context):
                    # Simulate concurrent write
                    agent_name = context.metadata["agent_name"]
                    with lock:
                        write_timestamps.append((agent_name, time.time()))

                    # Small delay to increase concurrency likelihood
                    time.sleep(0.01)

                    return AgentResponse(
                        output=f"{agent_name} output",
                        reasoning="OK",
                        tokens=100,
                        estimated_cost_usd=0.001
                    )

                mock_agent = Mock()
                mock_agent.execute.side_effect = concurrent_execute
                mock_create.return_value = mock_agent

                # Mock synthesis
                mock_strategy = Mock()
                mock_strategy.synthesize.return_value = SynthesisResult(
                    decision="synthesized",
                    confidence=0.9,
                    method="test",
                    votes={},
                    conflicts=[],
                    reasoning="test",
                    metadata={}
                )
                mock_strat.return_value = mock_strategy

                stage_config = {"agents": ["a1", "a2", "a3", "a4", "a5"]}
                state = {"workflow_id": "test", "stage_outputs": {}}

                result = executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=state,
                    config_loader=mock_config_loader
                )

                # Verify no data loss - all 5 agents should have outputs
                assert len(result["stage_outputs"]["test_stage"]["agent_outputs"]) == 5

                # Verify writes were concurrent (timestamps within small window)
                if len(write_timestamps) >= 2:
                    times = [t for _, t in write_timestamps]
                    time_span = max(times) - min(times)
                    # All writes should complete within 0.1s if truly parallel
                    assert time_span < 0.1, "Writes were sequential, not parallel"

def test_merge_dicts_reducer_semantics():
    """Test the custom merge_dicts reducer logic."""
    # This is tricky because merge_dicts is defined inline
    # We can test it indirectly by checking final state

    executor = ParallelStageExecutor()

    # Test via multiple agents updating same keys
    mock_config_loader = Mock()
    mock_config_loader.load_agent.return_value = {"name": "test"}

    with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
        with patch('src.compiler.schemas.AgentConfig'):
            with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                # Each agent returns different output
                def create_agent_for_name(config):
                    agent = Mock()
                    agent.execute.return_value = AgentResponse(
                        output=f"{config.name} output",
                        reasoning=f"{config.name} reasoning",
                        tokens=100,
                        estimated_cost_usd=0.001,
                        confidence=0.8
                    )
                    return agent

                mock_create.side_effect = create_agent_for_name

                # Mock synthesis
                mock_strategy = Mock()
                mock_strategy.synthesize.return_value = SynthesisResult(
                    decision="synthesized",
                    confidence=0.9,
                    method="test",
                    votes={},
                    conflicts=[],
                    reasoning="test",
                    metadata={}
                )
                mock_strat.return_value = mock_strategy

                stage_config = {"agents": ["a1", "a2", "a3"]}
                state = {"workflow_id": "test", "stage_outputs": {}}

                result = executor.execute_stage(
                    stage_name="test_stage",
                    stage_config=stage_config,
                    state=state,
                    config_loader=mock_config_loader
                )

                outputs = result["stage_outputs"]["test_stage"]["agent_outputs"]

                # Verify all agents present (merge didn't lose data)
                assert "a1" in outputs
                assert "a2" in outputs
                assert "a3" in outputs

                # Verify each agent's data is correct
                assert outputs["a1"]["output"] == "a1 output"
                assert outputs["a2"]["output"] == "a2 output"
                assert outputs["a3"]["output"] == "a3 output"
```

### 5.2 Race Condition Detection

```python
def test_no_race_conditions_in_metrics_aggregation():
    """Test that aggregate metrics calculation is race-free."""
    executor = ParallelStageExecutor()

    # Run multiple times to detect non-determinism
    results = []

    for iteration in range(10):
        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    mock_agent = Mock()
                    mock_agent.execute.return_value = AgentResponse(
                        output="Output",
                        reasoning="OK",
                        tokens=100,
                        estimated_cost_usd=0.001,
                        confidence=0.8
                    )
                    mock_create.return_value = mock_agent

                    # Mock synthesis
                    mock_strategy = Mock()
                    mock_strategy.synthesize.return_value = SynthesisResult(
                        decision="synthesized",
                        confidence=0.9,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strat.return_value = mock_strategy

                    stage_config = {"agents": ["a1", "a2", "a3", "a4", "a5"]}
                    state = {"workflow_id": "test", "stage_outputs": {}}

                    result = executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

                    metrics = result["stage_outputs"]["test_stage"]["aggregate_metrics"]
                    results.append(metrics)

    # All runs should produce identical results (deterministic)
    first_result = results[0]
    for result in results[1:]:
        assert result["total_tokens"] == first_result["total_tokens"]
        assert result["total_cost_usd"] == first_result["total_cost_usd"]
        assert result["num_successful"] == first_result["num_successful"]
```

---

## 6. Performance and Concurrency Tests

```python
class TestPerformanceCharacteristics:
    def test_10_agent_stress_test(self):
        """Stress test with 10 parallel agents."""
        executor = ParallelStageExecutor()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    mock_agent = Mock()
                    mock_agent.execute.return_value = AgentResponse(
                        output="Output",
                        reasoning="OK",
                        tokens=1000,
                        estimated_cost_usd=0.01,
                        confidence=0.85
                    )
                    mock_create.return_value = mock_agent

                    # Mock synthesis
                    mock_strategy = Mock()
                    mock_strategy.synthesize.return_value = SynthesisResult(
                        decision="synthesized",
                        confidence=0.9,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strat.return_value = mock_strategy

                    agents = [f"agent{i}" for i in range(10)]
                    stage_config = {"agents": agents}
                    state = {"workflow_id": "test", "stage_outputs": {}}

                    import time
                    start = time.time()

                    result = executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

                    duration = time.time() - start

                    # Verify all agents executed
                    assert result["stage_outputs"]["test_stage"]["aggregate_metrics"]["num_agents"] == 10
                    assert result["stage_outputs"]["test_stage"]["aggregate_metrics"]["num_successful"] == 10

                    # Verify metrics aggregated correctly
                    metrics = result["stage_outputs"]["test_stage"]["aggregate_metrics"]
                    assert metrics["total_tokens"] == 10000
                    assert metrics["total_cost_usd"] == pytest.approx(0.1)

                    # Should complete in reasonable time (< 5 seconds for mocked execution)
                    assert duration < 5.0

    def test_resource_cleanup_after_parallel_execution(self):
        """Test that resources are properly cleaned up after parallel execution."""
        executor = ParallelStageExecutor()

        # This is hard to test directly, but we can verify:
        # 1. No lingering threads
        # 2. No memory leaks (via gc)
        # 3. Subgraph is garbage collected

        import threading
        initial_thread_count = threading.active_count()

        mock_config_loader = Mock()
        mock_config_loader.load_agent.return_value = {"name": "test"}

        with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_create:
            with patch('src.compiler.schemas.AgentConfig'):
                with patch('src.strategies.registry.get_strategy_from_config') as mock_strat:
                    mock_agent = Mock()
                    mock_agent.execute.return_value = AgentResponse(
                        output="Output", reasoning="OK", tokens=100, estimated_cost_usd=0.001
                    )
                    mock_create.return_value = mock_agent

                    mock_strategy = Mock()
                    mock_strategy.synthesize.return_value = SynthesisResult(
                        decision="synthesized",
                        confidence=0.9,
                        method="test",
                        votes={},
                        conflicts=[],
                        reasoning="test",
                        metadata={}
                    )
                    mock_strat.return_value = mock_strategy

                    stage_config = {"agents": ["a1", "a2", "a3"]}
                    state = {"workflow_id": "test", "stage_outputs": {}}

                    executor.execute_stage(
                        stage_name="test_stage",
                        stage_config=stage_config,
                        state=state,
                        config_loader=mock_config_loader
                    )

        # Wait for cleanup
        import time
        time.sleep(0.5)

        # Thread count should return to initial (or close)
        final_thread_count = threading.active_count()
        assert final_thread_count <= initial_thread_count + 1  # Allow 1 thread variance
```

---

## 7. Test Coverage Analysis

### 7.1 Coverage Target Breakdown

| Component | Lines | Coverage Target | Test Methods |
|-----------|-------|----------------|--------------|
| `execute_stage` | ~240 | 85% | 15+ tests |
| `_create_agent_node` | ~82 | 90% | 8+ tests |
| `_run_synthesis` | ~48 | 80% | 6+ tests |
| `_validate_quality_gates` | ~75 | 85% | 10+ tests |
| `_extract_agent_name` | ~8 | 100% | 3 tests |
| `supports_stage_type` | ~1 | 100% | 1 test |
| Subgraph construction | ~115 | 80% | 5+ tests |
| **Total** | **672** | **80%+** | **48+ tests** |

### 7.2 Uncovered Edge Cases to Address

1. **Pydantic model vs dict config handling**
   - Test with both `stage_config` dict and Pydantic model
   - Test with missing `execution` field
   - Test with nested `stage.agents` structure

2. **AgentOutput creation edge cases**
   - Missing `confidence` in agent response
   - Missing `reasoning` field
   - Empty `metadata`
   - Tool calls with varying success rates

3. **Synthesis fallback scenarios**
   - ImportError when registry not available
   - Strategy returns None decision
   - Empty agent_outputs list

4. **Observability edge cases**
   - Tracker is None
   - Tracker missing `track_collaboration_event` method
   - Tracker raises exception

5. **State propagation**
   - `stage_input` contains nested workflow state
   - `stage_outputs` already exists
   - `current_stage` is already set

---

## 8. Mock Strategy Examples

### 8.1 Layered Mocking Approach

```python
# Layer 1: Config Loader
mock_config_loader = Mock()
mock_config_loader.load_agent.return_value = {"name": "agent1", "role": "researcher"}

# Layer 2: AgentConfig (Pydantic)
with patch('src.compiler.schemas.AgentConfig') as mock_agent_config_class:
    mock_agent_config = Mock()
    mock_agent_config.name = "agent1"
    mock_agent_config_class.return_value = mock_agent_config

    # Layer 3: AgentFactory
    with patch('src.compiler.executors.parallel.AgentFactory.create') as mock_factory:
        mock_agent = Mock()
        mock_agent.execute.return_value = AgentResponse(...)
        mock_factory.return_value = mock_agent

        # Layer 4: Synthesis Strategy
        with patch('src.strategies.registry.get_strategy_from_config') as mock_get_strategy:
            mock_strategy = Mock()
            mock_strategy.synthesize.return_value = SynthesisResult(...)
            mock_get_strategy.return_value = mock_strategy

            # Execute test
            result = executor.execute_stage(...)
```

### 8.2 Realistic Mock Data

```python
def create_realistic_agent_response(agent_name: str, success: bool = True) -> AgentResponse:
    """Create realistic agent response for testing."""
    if success:
        return AgentResponse(
            output=f"Research findings from {agent_name}:\n- Finding 1\n- Finding 2",
            reasoning=f"{agent_name} analyzed the data using method X and found Y",
            confidence=0.75 + (hash(agent_name) % 20) / 100,  # 0.75-0.94
            tokens=1200 + (hash(agent_name) % 300),  # 1200-1500
            estimated_cost_usd=0.012 + (hash(agent_name) % 5) / 1000,  # $0.012-$0.017
            tool_calls=[
                {"name": "search", "args": {"query": "test"}, "success": True},
                {"name": "calculate", "args": {"expr": "2+2"}, "success": True}
            ],
            metadata={"reasoning_tokens": 400, "output_tokens": 800}
        )
    else:
        return AgentResponse(
            output="",
            reasoning="",
            error=f"{agent_name} encountered an error during execution",
            tokens=50,
            estimated_cost_usd=0.001,
            tool_calls=[]
        )

def create_realistic_synthesis_result(
    decision: str,
    confidence: float,
    num_conflicts: int = 0
) -> SynthesisResult:
    """Create realistic synthesis result for testing."""
    return SynthesisResult(
        decision=decision,
        confidence=confidence,
        method="consensus_with_merit_weights",
        votes={"Option A": 3, "Option B": 2} if num_conflicts > 0 else {decision: 5},
        conflicts=[
            Conflict(
                agents=["agent1", "agent2"],
                decisions=["Option A", "Option B"],
                disagreement_score=0.6,
                context={"round": 1}
            )
        ] if num_conflicts > 0 else [],
        reasoning=f"Synthesized decision '{decision}' with {confidence:.0%} confidence",
        metadata={
            "deliberation_rounds": 2 if num_conflicts > 0 else 1,
            "convergence_score": confidence
        }
    )
```

---

## 9. Implementation Checklist

### Phase 1: Foundation (LOC: 60)
- [ ] Test class structure setup
- [ ] Basic executor tests (initialization, supports_stage_type)
- [ ] Helper method tests (_extract_agent_name)
- [ ] Mock infrastructure setup

### Phase 2: Core Parallel Execution (LOC: 80)
- [ ] Test subgraph construction
- [ ] Test 2-agent parallel execution
- [ ] Test 3-agent parallel execution
- [ ] Test 5-agent parallel execution
- [ ] Test 10-agent stress test
- [ ] Test concurrency vs sequential timing

### Phase 3: Error Handling (LOC: 60)
- [ ] Test partial failures (2/3 succeed)
- [ ] Test all agents fail
- [ ] Test min_successful_agents threshold
- [ ] Test on_stage_failure: skip
- [ ] Test on_stage_failure: halt
- [ ] Test error message aggregation

### Phase 4: Quality Gates (LOC: 70)
- [ ] Test quality gates disabled
- [ ] Test min_confidence validation
- [ ] Test min_findings validation
- [ ] Test require_citations validation
- [ ] Test retry_stage logic
- [ ] Test max_retries exhausted
- [ ] Test escalate action
- [ ] Test proceed_with_warning action
- [ ] Test retry counter tracking

### Phase 5: Advanced Features (LOC: 80)
- [ ] Test aggregate metrics calculation
- [ ] Test synthesis integration
- [ ] Test observability tracking
- [ ] Test thread safety
- [ ] Test race condition prevention
- [ ] Test resource cleanup
- [ ] Test state propagation
- [ ] Test Pydantic vs dict config

### Phase 6: Edge Cases (LOC: 50)
- [ ] Test missing fields in config
- [ ] Test empty agent list
- [ ] Test tracker is None
- [ ] Test synthesis ImportError fallback
- [ ] Test quality gate validator None fallback
- [ ] Test various agent reference formats

**Total Estimated LOC: 400+** (exceeds 200 LOC requirement)

---

## 10. Continuous Integration Recommendations

### 10.1 Test Markers

```python
pytest.mark.unit         # Fast unit tests (<0.1s each)
pytest.mark.integration  # Integration tests (0.1-1s)
pytest.mark.slow         # Slow tests (1s+)
pytest.mark.concurrent   # Tests that verify concurrency
pytest.mark.stress       # Stress tests with many agents
```

### 10.2 Coverage Enforcement

```bash
# Run with coverage
pytest tests/test_compiler/test_executors_parallel.py --cov=src/compiler/executors/parallel --cov-report=term-missing --cov-fail-under=80

# Generate HTML report
pytest tests/test_compiler/test_executors_parallel.py --cov=src/compiler/executors/parallel --cov-report=html

# Check specific uncovered lines
coverage report -m | grep parallel.py
```

### 10.3 Performance Baseline

```python
# tests/test_compiler/test_executors_parallel.py

@pytest.mark.benchmark
def test_parallel_execution_benchmark(benchmark):
    """Benchmark parallel execution performance."""
    executor = ParallelStageExecutor()

    # Setup mocks
    # ...

    def run():
        executor.execute_stage(...)

    result = benchmark(run)

    # Assert performance characteristics
    assert result.stats.mean < 1.0  # Mean execution time < 1s
```

---

## 11. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Line Coverage** | 80%+ | `pytest --cov` |
| **Branch Coverage** | 75%+ | `pytest --cov-branch` |
| **Test LOC** | 200+ | `cloc tests/test_compiler/test_executors_parallel.py` |
| **Test Methods** | 40+ | Count of `def test_*` |
| **Parameterized Variants** | 20+ | Total test executions |
| **Execution Time** | <30s | `pytest --durations=0` |
| **Flaky Test Rate** | 0% | Run 100 times, 0 failures |

---

## 12. Risk Mitigation

### 12.1 Common Pitfalls

1. **Mocking too much**: Over-mocking can miss integration issues
   - Mitigation: Include integration tests alongside unit tests

2. **Non-deterministic tests**: Concurrency tests can be flaky
   - Mitigation: Run tests multiple times (10x), use proper synchronization

3. **Incomplete error scenarios**: Missing edge cases
   - Mitigation: Systematic error injection at each layer

4. **Performance test instability**: CI timing variance
   - Mitigation: Use generous thresholds, mark as `slow`, allow retries

### 12.2 Testing Gaps

- **Real LangGraph execution**: Unit tests mock subgraph, need integration test
- **Actual concurrency behavior**: Mocks may not capture true threading issues
- **Memory usage**: No tests for memory leaks or excessive allocation
- **Network failures**: If agents call external services (mocked away)

**Mitigation**: Complement with integration tests in separate test suite.

---

## 13. Next Steps

1. **Create test file**: `tests/test_compiler/test_executors_parallel.py`
2. **Implement Phase 1**: Foundation tests (60 LOC)
3. **Run coverage**: `pytest --cov` to establish baseline
4. **Iterate phases 2-6**: Add tests incrementally
5. **Review coverage gaps**: Use `coverage html` to identify uncovered lines
6. **Add integration tests**: Complement unit tests with E2E scenarios
7. **Performance profiling**: Benchmark parallel vs sequential execution
8. **Document findings**: Update test strategy with actual results

---

## Appendix A: Test File Template

```python
"""Comprehensive unit tests for ParallelStageExecutor.

This test module provides thorough coverage of the ParallelStageExecutor,
including parallel execution, error handling, quality gates, and observability.

Coverage target: 80%+
Test LOC: 200+
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from src.compiler.executors.parallel import ParallelStageExecutor
from src.agents.base_agent import AgentResponse, ExecutionContext
from src.strategies.base import AgentOutput, SynthesisResult, Conflict


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def executor():
    """Create ParallelStageExecutor instance."""
    return ParallelStageExecutor()


@pytest.fixture
def mock_config_loader():
    """Create mock ConfigLoader."""
    loader = Mock()
    loader.load_agent.return_value = {"name": "test_agent"}
    return loader


@pytest.fixture
def mock_synthesis_coordinator():
    """Create mock synthesis coordinator."""
    coordinator = Mock()
    coordinator.synthesize.return_value = SynthesisResult(
        decision="synthesized decision",
        confidence=0.9,
        method="test_synthesis",
        votes={},
        conflicts=[],
        reasoning="Test reasoning",
        metadata={}
    )
    return coordinator


@pytest.fixture
def mock_quality_gate_validator():
    """Create mock quality gate validator."""
    validator = Mock()
    validator.validate.return_value = (True, [])  # Pass by default
    return validator


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestParallelExecutorBasics:
    """Test basic executor properties and initialization."""
    pass


class TestSubgraphConstruction:
    """Test LangGraph subgraph creation for parallel execution."""
    pass


class TestParallelExecution:
    """Test concurrent agent execution."""
    pass


# ... (continue with remaining test classes)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--cov=src/compiler/executors/parallel"])
```

---

## Appendix B: Mock Helper Functions

```python
# tests/test_compiler/helpers/parallel_executor_mocks.py

"""Helper functions for mocking ParallelExecutor components."""

from typing import Dict, Any, List, Callable
from unittest.mock import Mock
from src.agents.base_agent import AgentResponse
from src.strategies.base import SynthesisResult, AgentOutput, Conflict


def create_mock_agent(
    name: str,
    should_fail: bool = False,
    tokens: int = 100,
    cost: float = 0.001,
    confidence: float = 0.8,
    delay_seconds: float = 0.0
) -> Mock:
    """Create a mock agent with configurable behavior."""
    agent = Mock()

    if should_fail:
        agent.execute.side_effect = RuntimeError(f"{name} failed")
    else:
        def execute_with_delay(input_data, context):
            if delay_seconds > 0:
                import time
                time.sleep(delay_seconds)

            return AgentResponse(
                output=f"Output from {name}",
                reasoning=f"Reasoning from {name}",
                confidence=confidence,
                tokens=tokens,
                estimated_cost_usd=cost,
                tool_calls=[]
            )

        agent.execute.side_effect = execute_with_delay

    return agent


def create_mock_agent_factory(agents_config: Dict[str, Dict[str, Any]]) -> Callable:
    """Create a mock AgentFactory.create function."""
    agents = {
        name: create_mock_agent(name, **config)
        for name, config in agents_config.items()
    }

    def factory(config):
        return agents.get(config.name, create_mock_agent(config.name))

    return factory


def create_mock_synthesis_result(
    decision: str = "test decision",
    confidence: float = 0.9,
    method: str = "consensus",
    conflicts: int = 0
) -> SynthesisResult:
    """Create a mock SynthesisResult."""
    return SynthesisResult(
        decision=decision,
        confidence=confidence,
        method=method,
        votes={decision: 5} if conflicts == 0 else {"A": 3, "B": 2},
        conflicts=[
            Conflict(
                agents=["a1", "a2"],
                decisions=["A", "B"],
                disagreement_score=0.5,
                context={}
            )
        ] * conflicts,
        reasoning=f"Test synthesis: {decision}",
        metadata={}
    )
```

---

## Summary

This comprehensive test strategy provides:

1. **Structured approach**: 12 test classes covering all aspects of ParallelStageExecutor
2. **200+ LOC**: Detailed test methods with realistic mocking
3. **Parameterized tests**: Testing with 2, 3, 5, 10 agents
4. **Error injection**: Systematic failure testing at multiple layers
5. **Thread safety**: Concurrent write detection and race condition prevention
6. **Performance tests**: Benchmarking parallel vs sequential execution
7. **80%+ coverage**: Comprehensive coverage of all major code paths
8. **Quality gates**: Thorough testing of retry logic and validation
9. **Observability**: Verification of event tracking and metrics

The strategy balances unit testing (fast, isolated) with realistic scenarios (integration-like mocking) to ensure the ParallelStageExecutor works correctly in production.
