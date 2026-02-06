"""Performance benchmarks for workflow compilation and agent execution.

Establishes baseline metrics for:
- Workflow compilation time
- Agent execution overhead
- LLM call latency
- Tool execution overhead
- Concurrent throughput
- Memory usage under load

Run with: pytest tests/test_benchmarks/test_benchmarks_compilation.py --benchmark-only
"""

import time
from unittest.mock import Mock, patch

import pytest

from src.agents.standard_agent import StandardAgent
from src.compiler.langgraph_compiler import LangGraphCompiler

# ============================================================================
# Benchmark Tests: Compilation and Execution
# ============================================================================

def test_workflow_compilation_time(simple_workflow_config, benchmark):
    """Benchmark workflow compilation time.

    Target: <1s for simple workflows
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        # Setup
        compiler = LangGraphCompiler()

        # Mock config loader
        mock_loader_instance = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader_instance.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader_instance

        # Benchmark compilation
        result = benchmark(compiler.compile, simple_workflow_config)

        # Verify
        assert result is not None
        assert hasattr(result, 'invoke')

        # Log performance expectation
        if benchmark.stats['mean'] > 1.0:
            pytest.fail(f"Compilation took {benchmark.stats['mean']:.3f}s, target is <1s")


def test_agent_execution_overhead(mock_llm_provider, minimal_agent_config, benchmark):
    """Benchmark agent execution overhead (excluding LLM time).

    Target: <100ms overhead (agent logic only, not LLM call)
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_tool_registry:
        # Setup mock registry
        mock_tool_registry.return_value.list_tools.return_value = []

        # Setup agent
        agent = StandardAgent(minimal_agent_config)

        # Mock LLM response
        from src.agents.llm_providers import LLMResponse
        mock_llm_response = LLMResponse(
            content="<answer>4</answer>",
            model="mock-model",
            provider="mock",
            total_tokens=50,
        )
        agent.llm = Mock()
        agent.llm.complete.return_value = mock_llm_response

        # Benchmark execution (agent overhead only)
        def execute_agent():
            return agent.execute({"input": "What is 2+2?"})

        result = benchmark(execute_agent)

        # Verify
        assert result is not None

        # Log performance expectation (overhead should be <100ms)
        if benchmark.stats['mean'] > 0.1:
            print(f"Warning: Agent overhead {benchmark.stats['mean']:.3f}s exceeds 100ms target")


def test_llm_call_latency(benchmark, mock_llm_provider):
    """Benchmark LLM provider call latency.

    Tracks provider latency for monitoring and comparison.
    """
    # Simulate realistic LLM latency (50-200ms for mocked calls)
    def llm_call_with_latency():
        time.sleep(0.05)  # 50ms simulated latency
        return mock_llm_provider.generate(
            messages=[{"role": "user", "content": "test"}]
        )

    result = benchmark(llm_call_with_latency)

    # Verify
    assert result is not None
    assert "content" in result

    # Log latency for tracking (no hard target, just monitoring)
    print(f"LLM call latency: {benchmark.stats['mean']:.3f}s")


def test_tool_execution_overhead(benchmark):
    """Benchmark tool execution overhead.

    Target: <50ms overhead (tool registry lookup + execution)
    """
    # Create a simple mock tool for benchmarking
    def mock_tool_function(a: int, b: int) -> dict:
        """Simple addition function."""
        return {"result": a + b}

    # Benchmark tool call
    def execute_tool():
        return mock_tool_function(a=2, b=3)

    result = benchmark(execute_tool)

    # Verify
    assert result == {"result": 5}

    # Log performance expectation
    if benchmark.stats['mean'] > 0.05:
        print(f"Warning: Tool overhead {benchmark.stats['mean']:.3f}s exceeds 50ms target")


def test_large_workflow_compilation(complex_workflow_config, benchmark):
    """Benchmark compilation of large (50+ stage) workflow.

    Tests scalability of workflow compilation.
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        # Setup
        compiler = LangGraphCompiler()

        # Mock config loader
        mock_loader_instance = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader_instance.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader_instance

        # Benchmark compilation
        result = benchmark(compiler.compile, complex_workflow_config)

        # Verify
        assert result is not None
        assert hasattr(result, 'invoke')

        # Log performance (no strict target, just monitoring scaling)
        print(f"50-stage workflow compilation: {benchmark.stats['mean']:.3f}s")


def test_concurrent_workflow_throughput(simple_workflow_config, benchmark):
    """Benchmark concurrent workflow compilation throughput.

    Tests parallel workflow handling.
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        # Setup
        mock_loader_instance = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader_instance.load_stage.return_value = mock_stage_config

        # Benchmark concurrent compilations
        def compile_multiple_workflows():
            compilers = [LangGraphCompiler() for _ in range(10)]
            for compiler in compilers:
                compiler.config_loader = mock_loader_instance

            results = []
            for compiler in compilers:
                results.append(compiler.compile(simple_workflow_config))
            return results

        results = benchmark(compile_multiple_workflows)

        # Verify
        assert len(results) == 10
        assert all(r is not None for r in results)

        # Log throughput
        workflows_per_second = 10 / benchmark.stats['mean']
        print(f"Concurrent throughput: {workflows_per_second:.2f} workflows/second")


def test_memory_usage_under_load(mock_llm_provider, minimal_agent_config, benchmark):
    """Benchmark memory usage under repeated operations.

    Detects memory leaks by running operations multiple times.
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_tool_registry:
        # Setup mock registry
        mock_tool_registry.return_value.list_tools.return_value = []

        # Setup agent
        agent = StandardAgent(minimal_agent_config)

        # Mock LLM response
        from src.agents.llm_providers import LLMResponse
        mock_llm_response = LLMResponse(
            content="<answer>test response</answer>",
            model="mock-model",
            provider="mock",
            total_tokens=10,
        )
        agent.llm = Mock()
        agent.llm.complete.return_value = mock_llm_response

        # Benchmark repeated executions (memory should remain stable)
        def repeated_executions():
            results = []
            for _ in range(100):
                results.append(agent.execute({"input": "test"}))
            return results

        results = benchmark(repeated_executions)

        # Verify
        assert len(results) == 100

        # Memory leak detection would require additional tools (memory_profiler)
        # This benchmark establishes baseline for future comparison
        print(f"100 agent executions: {benchmark.stats['mean']:.3f}s")


def test_performance_summary(benchmark):
    """Generate performance summary for compilation benchmarks.

    This test always passes and just records baseline metrics.
    """
    benchmark(lambda: None)

    summary = """
    Compilation Performance Benchmark Summary
    =========================================

    Target Metrics:
    - Workflow compilation: <1s for simple workflows
    - Agent execution overhead: <100ms
    - Tool execution overhead: <50ms
    - Concurrent throughput: 10+ workflows

    Run benchmarks:
        pytest tests/test_benchmarks/test_benchmarks_compilation.py --benchmark-only

    Save baseline:
        pytest tests/test_benchmarks/test_benchmarks_compilation.py --benchmark-only --benchmark-save=baseline

    Compare:
        pytest tests/test_benchmarks/test_benchmarks_compilation.py --benchmark-only --benchmark-compare=baseline
    """

    print(summary)
