"""Performance benchmarks for Collaboration Strategies and Safety.

This module contains 10 benchmarks covering:
- Collaboration Strategies (6 tests)
- Safety & Security (4 tests)

Run with: pytest tests/test_benchmarks/test_performance_strategies.py --benchmark-only
"""
import pytest
from unittest.mock import Mock

from src.strategies.consensus import ConsensusStrategy
from src.strategies.debate import DebateAndSynthesize
from src.strategies.conflict_resolution import MeritWeightedResolver
from src.strategies.base import AgentOutput
from src.safety.action_policy_engine import ActionPolicyEngine
from src.safety.rollback import RollbackManager
from src.tools.executor import ToolExecutor
from src.tools.calculator import Calculator


# ============================================================================
# CATEGORY 6: Collaboration Strategies (6 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="strategies")
def test_strategy_consensus_3_agents(benchmark):
    """Benchmark consensus strategy with 3 agents.

    Target: <100ms
    Measures: Synthesis overhead
    """
    strategy = ConsensusStrategy(min_agreement=0.5)

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision="result_A",
            reasoning="test reasoning",
            confidence=0.8,
            metadata={}
        )
        for i in range(3)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_consensus_10_agents(benchmark):
    """Benchmark consensus strategy with 10 agents.

    Target: <500ms
    Measures: Synthesis scalability
    """
    strategy = ConsensusStrategy(min_agreement=0.5)

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision="result_A" if i < 7 else "result_B",
            reasoning="test reasoning",
            confidence=0.8,
            metadata={}
        )
        for i in range(10)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_debate(benchmark):
    """Benchmark debate strategy synthesis.

    Target: <200ms
    Measures: Debate coordination overhead
    """
    strategy = DebateAndSynthesize(rounds=2)

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision=f"result_{i}",
            reasoning=f"reasoning {i}",
            confidence=0.7 + (i * 0.1),
            metadata={}
        )
        for i in range(3)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_merit_weighted(benchmark):
    """Benchmark merit-weighted strategy.

    Target: <150ms
    Measures: Weighted voting overhead
    """
    strategy = MeritWeightedResolver()

    outputs = [
        AgentOutput(
            agent_name=f"agent_{i}",
            decision="result_A",
            reasoning="test reasoning",
            confidence=0.5 + (i * 0.1),
            metadata={}
        )
        for i in range(5)
    ]

    result = benchmark(strategy.synthesize, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_conflict_resolution(benchmark):
    """Benchmark conflict resolution.

    Target: <100ms
    Measures: Conflict detection and resolution overhead
    """
    from src.strategies.conflict_resolution import MeritWeightedConflictResolution

    resolver = MeritWeightedConflictResolution()

    outputs = [
        AgentOutput(
            agent_name="agent_0",
            decision="result_A",
            reasoning="reasoning A",
            confidence=0.8,
            metadata={}
        ),
        AgentOutput(
            agent_name="agent_1",
            decision="result_B",
            reasoning="reasoning B",
            confidence=0.7,
            metadata={}
        ),
    ]

    result = benchmark(resolver.resolve, outputs, {})
    assert result.final_decision is not None

@pytest.mark.benchmark(group="strategies")
def test_strategy_quality_gate_validation(benchmark):
    """Benchmark quality gate validation.

    Target: <50ms
    Measures: Quality check overhead
    """
    from src.strategies.base import SynthesisResult

    synthesis_result = SynthesisResult(
        final_decision="test result",
        reasoning="test reasoning",
        confidence=0.9,
        metadata={"agent_count": 3}
    )

    def validate_quality():
        # Simple quality checks
        assert synthesis_result.confidence >= 0.5
        assert synthesis_result.final_decision is not None
        assert len(synthesis_result.reasoning) > 0
        return True

    result = benchmark(validate_quality)
    assert result is True

# ============================================================================
# CATEGORY 7: Safety & Security (4 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="safety")
def test_safety_action_policy_validation(benchmark):
    """Benchmark action policy validation.

    Target: <10ms
    Measures: Policy check overhead
    """
    policy_engine = ActionPolicyEngine()

    from src.safety.action_policy_engine import PolicyExecutionContext
    context = PolicyExecutionContext(
        action_type="tool_execution",
        tool_name="calculator",
        parameters={"expression": "2+2"},
        agent_name="test_agent"
    )

    result = benchmark(policy_engine.validate, context)
    # Validation returns None on success, raises on failure

@pytest.mark.benchmark(group="safety")
def test_safety_rate_limiter_overhead(tool_registry, benchmark):
    """Benchmark rate limiter overhead.

    Target: <5ms
    Measures: Rate limiting check overhead
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(
        registry=tool_registry,
        rate_limit=100,
        rate_window=1.0
    )

    try:
        result = benchmark(
            executor.execute,
            "calculator",
            {"expression": "2 + 2"}
        )
        assert result.success is True
    finally:
        executor.shutdown()

@pytest.mark.benchmark(group="safety")
def test_safety_circuit_breaker_overhead(benchmark):
    """Benchmark circuit breaker overhead.

    Target: <5ms
    Measures: Circuit breaker check overhead
    """
    from src.llm.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

    config = CircuitBreakerConfig(
        failure_threshold=5,
        timeout=60,
        expected_exception=Exception
    )
    circuit_breaker = CircuitBreaker(config)

    def protected_operation():
        with circuit_breaker:
            return "success"

    result = benchmark(protected_operation)
    assert result == "success"

@pytest.mark.benchmark(group="safety")
def test_safety_rollback_snapshot(benchmark):
    """Benchmark rollback snapshot creation.

    Target: <100ms
    Measures: Snapshot overhead
    """
    rollback_manager = RollbackManager()

    test_state = {
        "workflow_id": "test_workflow",
        "stage": "test_stage",
        "data": {"key": "value"}
    }

    result = benchmark(
        rollback_manager.create_snapshot,
        "test_operation",
        test_state
    )
    assert result is not None
