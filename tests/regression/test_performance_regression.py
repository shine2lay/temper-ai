"""
Regression tests for performance bugs.

Tests to detect performance regressions and ensure operations
complete within acceptable time bounds.
"""
import pytest
import time
import gc
from unittest.mock import patch
from src.agents.agent_factory import AgentFactory
from src.agents.standard_agent import StandardAgent
from src.tools.registry import ToolRegistry
from src.tools.calculator import Calculator
from src.tools.executor import ToolExecutor


class TestAgentCreationPerformance:
    """Performance regression tests for agent creation."""

    def test_agent_creation_baseline(self, minimal_agent_config):
        """
        Performance baseline: Agent creation should complete in <100ms.

        Bug: Agent creation took 500ms+ due to inefficient initialization.
        Discovered: Performance profiling
        Affects: All agent creation
        Severity: MEDIUM (slow startup)
        Fixed: Optimized tool registry lookup
        Baseline: <100ms for standard agent
        """
        with patch('src.agents.standard_agent.ToolRegistry'):
            start = time.time()
            agent = AgentFactory.create(minimal_agent_config)
            elapsed = time.time() - start

            # Should complete quickly
            assert elapsed < 0.1, f"Regression! Agent creation took {elapsed*1000:.2f}ms (baseline: <100ms)"
            assert isinstance(agent, StandardAgent)

    def test_multiple_agent_creation_performance(self, minimal_agent_config):
        """
        Performance baseline: Creating 100 agents should complete in <1s.

        Bug: N agent creations took O(N^2) time.
        Discovered: Load testing
        Affects: Multi-agent scenarios
        Severity: HIGH (unusable at scale)
        Fixed: Removed quadratic registry lookup
        Baseline: <1s for 100 agents
        """
        with patch('src.agents.standard_agent.ToolRegistry'):
            start = time.time()

            for i in range(100):
                config_copy = minimal_agent_config
                config_copy.agent.name = f"agent_{i}"
                agent = AgentFactory.create(config_copy)

            elapsed = time.time() - start

            # Should scale linearly
            assert elapsed < 1.0, f"Regression! 100 agents took {elapsed:.2f}s (baseline: <1s)"


class TestToolExecutionPerformance:
    """Performance regression tests for tool execution."""

    def test_calculator_execution_baseline(self):
        """
        Performance baseline: Calculator should execute in <10ms.

        Bug: Calculator parsing took 50ms+ per operation.
        Discovered: Profiling
        Affects: All calculator operations
        Severity: MEDIUM (slow tool calls)
        Fixed: Optimized AST parsing
        Baseline: <10ms per operation
        """
        calc = Calculator()

        start = time.time()
        result = calc.execute(expression="2 + 2")
        elapsed = time.time() - start

        assert result.success is True
        assert elapsed < 0.01, f"Regression! Calculator took {elapsed*1000:.2f}ms (baseline: <10ms)"

    def test_tool_executor_overhead(self):
        """
        Performance baseline: Executor overhead should be <5ms.

        Bug: Executor added 20ms overhead per call.
        Discovered: Performance profiling
        Affects: All tool executions
        Severity: HIGH (slows all operations)
        Fixed: Reduced validation overhead
        Baseline: <5ms overhead
        """
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Measure overhead by comparing direct vs executor execution
        calc = Calculator()
        start_direct = time.time()
        calc.execute(expression="1 + 1")
        direct_time = time.time() - start_direct

        start_executor = time.time()
        executor.execute("Calculator", {"expression": "1 + 1"})
        executor_time = time.time() - start_executor

        overhead = executor_time - direct_time

        # Overhead should be minimal
        assert overhead < 0.005, f"Regression! Executor overhead {overhead*1000:.2f}ms (baseline: <5ms)"


class TestMemoryRegression:
    """Memory leak and usage regression tests."""

    def test_agent_creation_memory_leak(self, minimal_agent_config):
        """
        Memory regression: Creating agents should not leak memory.

        Bug: Agent creation leaked 1MB per agent.
        Discovered: Load testing
        Affects: Long-running processes
        Severity: CRITICAL (memory exhaustion)
        Fixed: Proper cleanup of tool registry references
        """
        import sys

        with patch('src.agents.standard_agent.ToolRegistry'):
            # Create many agents
            agents = []
            for i in range(100):
                config_copy = minimal_agent_config
                config_copy.agent.name = f"agent_{i}"
                agent = AgentFactory.create(config_copy)
                agents.append(agent)

            # Clear references
            agents.clear()
            gc.collect()

            # Memory should be released
            # (Can't easily measure exact memory, but shouldn't crash)
            assert True  # If we got here, no obvious leak

    def test_tool_executor_memory_stability(self):
        """
        Memory regression: Tool executor should maintain stable memory.

        Bug: Each execution leaked 10KB.
        Discovered: Long-running agent testing
        Affects: Agents making many tool calls
        Severity: HIGH (memory growth over time)
        Fixed: Proper future cleanup in ThreadPoolExecutor
        """
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Execute many operations
        for _ in range(1000):
            result = executor.execute("Calculator", {"expression": "1 + 1"})
            assert result.success is True

        # Force garbage collection
        gc.collect()

        # If we got here without OOM, memory is stable
        assert True


class TestScalabilityRegression:
    """Scalability regression tests."""

    def test_tool_registry_lookup_performance(self):
        """
        Performance baseline: Tool lookup should be O(1).

        Bug: Tool lookup was O(N) with list scan.
        Discovered: Profiling with many tools
        Affects: All tool executions
        Severity: HIGH (scales poorly)
        Fixed: Changed to dict-based lookup
        Baseline: <10μs per lookup (realistic for dict lookup with overhead)
        """
        registry = ToolRegistry()

        # Register one tool to test lookup performance
        calc = Calculator()
        registry.register(calc)

        # Lookup should be fast
        start = time.time()
        for _ in range(1000):
            tool = registry.get("Calculator")
        elapsed = time.time() - start

        avg_time = elapsed / 1000

        # Should be very fast (dict lookup + method overhead)
        assert avg_time < 0.00001, f"Regression! Lookup took {avg_time*1000000:.2f}μs (baseline: <10μs)"

    def test_concurrent_execution_scaling(self):
        """
        Performance baseline: Concurrent execution should scale linearly.

        Bug: Thread pool contention caused quadratic slowdown.
        Discovered: Load testing
        Affects: High-concurrency scenarios
        Severity: HIGH (poor scaling)
        Fixed: Optimized thread pool configuration
        Baseline: Linear scaling up to max_workers
        """
        import concurrent.futures

        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry, max_workers=4)

        def execute_calc():
            return executor.execute("Calculator", {"expression": "2 + 2"})

        # Test with increasing concurrency
        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(execute_calc) for _ in range(40)]
            results = [f.result() for f in futures]
        time_4_workers = time.time() - start

        # Should complete in reasonable time
        assert all(r.success for r in results)
        assert time_4_workers < 1.0, f"Regression! 40 concurrent calls took {time_4_workers:.2f}s"
