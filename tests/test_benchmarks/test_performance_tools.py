"""Tool Execution Performance Benchmarks.

This module contains 8 performance benchmarks for tool execution:
- Tool registry lookup
- Calculator tool execution
- Tool executor overhead
- Concurrent tool execution (4 and 10 workers)
- Parameter validation
- Error handling
- Result serialization

Run with: pytest tests/test_benchmarks/test_performance_tools.py --benchmark-only

Save baseline:
    pytest tests/test_benchmarks/test_performance_tools.py --benchmark-only --benchmark-save=tools

Compare with regression detection:
    pytest tests/test_benchmarks/test_performance_tools.py --benchmark-only \
        --benchmark-compare=tools --benchmark-compare-fail=mean:10%
"""

from concurrent.futures import ThreadPoolExecutor, wait

import pytest

from temper_ai.tools.base import ToolResult
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.executor import ToolExecutor

# ============================================================================
# CATEGORY 4: Tool Execution (8 benchmarks)
# ============================================================================


@pytest.mark.benchmark(group="tools")
def test_tool_registry_lookup(benchmark):
    """Benchmark tool registry lookup.

    Target: <5ms
    Measures: Registry search overhead
    """
    from temper_ai.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(Calculator())

    result = benchmark(registry.get, "Calculator")
    assert result is not None


@pytest.mark.benchmark(group="tools")
def test_tool_calculator_execution(benchmark):
    """Benchmark calculator tool execution.

    Target: <50ms
    Measures: Tool execution overhead
    """
    calc = Calculator()

    result = benchmark(calc.execute, expression="2 + 2")

    assert result.success is True
    assert result.result == 4


@pytest.mark.benchmark(group="tools")
def test_tool_executor_overhead(tool_registry, benchmark):
    """Benchmark tool executor overhead.

    Target: <50ms
    Measures: Executor wrapper overhead
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(registry=tool_registry, max_workers=4)

    try:
        result = benchmark(executor.execute, "Calculator", {"expression": "2 + 2"})
        assert result.success is True
    finally:
        executor.shutdown()


@pytest.mark.benchmark(group="tools")
def test_tool_concurrent_execution_4_workers(tool_registry, benchmark):
    """Benchmark concurrent tool execution (4 workers).

    Target: <200ms for 10 tools
    Measures: Thread pool efficiency
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(registry=tool_registry, max_workers=4)

    def execute_concurrent():

        futures = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            for i in range(10):
                future = pool.submit(
                    executor.execute, "Calculator", {"expression": f"{i} + {i}"}
                )
                futures.append(future)

            wait(futures)
            return [f.result() for f in futures]

    try:
        results = benchmark(execute_concurrent)
        assert len(results) == 10
        assert all(r.success for r in results)
    finally:
        executor.shutdown()


@pytest.mark.benchmark(group="tools")
def test_tool_concurrent_execution_10_workers(tool_registry, benchmark):
    """Benchmark concurrent tool execution (10 workers).

    Target: <150ms for 10 tools
    Measures: Thread pool scalability
    """
    tool_registry.register(Calculator())
    executor = ToolExecutor(registry=tool_registry, max_workers=10)

    def execute_concurrent():

        futures = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            for i in range(10):
                future = pool.submit(
                    executor.execute, "Calculator", {"expression": f"{i} + {i}"}
                )
                futures.append(future)

            wait(futures)
            return [f.result() for f in futures]

    try:
        results = benchmark(execute_concurrent)
        assert len(results) == 10
    finally:
        executor.shutdown()


@pytest.mark.benchmark(group="tools")
def test_tool_parameter_validation(benchmark):
    """Benchmark tool parameter validation.

    Target: <10ms
    Measures: Validation overhead
    """
    calc = Calculator()

    def validate_and_execute():
        # Calculator performs internal validation
        return calc.execute(expression="2 + 2")

    result = benchmark(validate_and_execute)
    assert result.success is True


@pytest.mark.benchmark(group="tools")
def test_tool_error_handling(benchmark):
    """Benchmark tool error handling.

    Target: <20ms
    Measures: Error path overhead
    """
    calc = Calculator()

    result = benchmark(calc.execute, expression="1 / 0")

    assert result.success is False
    assert result.error is not None


@pytest.mark.benchmark(group="tools")
def test_tool_result_serialization(benchmark):
    """Benchmark tool result serialization.

    Target: <5ms
    Measures: Result object creation overhead
    """

    def create_result():
        return ToolResult(
            success=True,
            result="test result",
            error=None,
            metadata={"execution_time": 0.1},
        )

    result = benchmark(create_result)
    assert result is not None
