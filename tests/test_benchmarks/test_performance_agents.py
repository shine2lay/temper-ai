"""Performance benchmarks for Agent Execution.

This module contains 8 benchmarks covering agent execution paths:
- Agent execution overhead (excluding LLM)
- Agent with tool calls
- Agent prompt rendering
- Agent error handling
- Agent factory creation
- Agent memory usage (100 executions)
- Concurrent execution (3 agents)
- Concurrent execution (10 agents)

Run with: pytest tests/test_benchmarks/test_performance_agents.py --benchmark-only
"""
import os
from unittest.mock import Mock, patch

import psutil
import pytest

from src.agents.agent_factory import AgentFactory
from src.agents.llm_providers import LLMResponse
from src.agents.standard_agent import StandardAgent
from src.tools.base import BaseTool, ToolResult

from tests.test_benchmarks.conftest import check_budget

# ============================================================================
# CATEGORY 5: Agent Execution (8 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="agents")
def test_agent_execution_overhead(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark agent execution overhead (excluding LLM).

    Target: <100ms
    Measures: Agent framework overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)
        agent.llm = mock_llm_fast

        result = benchmark(agent.execute, {"input": "test"})

        assert result is not None
        check_budget("agent_execution", benchmark.stats['mean'])

@pytest.mark.benchmark(group="agents")
def test_agent_with_tools(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark agent execution with tool calls.

    Target: <150ms
    Measures: Agent + tool integration overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_tool_instance = Mock(spec=BaseTool)
        mock_tool_instance.execute.return_value = ToolResult(
            success=True,
            result="4",
            error=None
        )

        mock_registry.return_value.list_tools.return_value = ["calculator"]
        mock_registry.return_value.get.return_value = mock_tool_instance

        agent = StandardAgent(minimal_agent_config)
        agent.llm = mock_llm_fast

        # Mock LLM to return tool call
        mock_llm_fast.complete.return_value = LLMResponse(
            content='<tool_call>{"name": "calculator", "args": {"expression": "2+2"}}</tool_call>',
            model="mock",
            provider="mock",
            total_tokens=10
        )

        result = benchmark(agent.execute, {"input": "calculate 2+2"})
        assert result is not None
        check_budget("agent_with_tools", benchmark.stats['mean'])

@pytest.mark.benchmark(group="agents")
def test_agent_prompt_rendering(minimal_agent_config, benchmark):
    """Benchmark agent prompt rendering.

    Target: <20ms
    Measures: Jinja2 template rendering overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        def render_prompt():
            from src.agents.prompt_engine import PromptEngine
            engine = PromptEngine(minimal_agent_config.agent.prompt)
            return engine.render({"input": "test query"})

        result = benchmark(render_prompt)
        assert result is not None
        assert "test query" in result

@pytest.mark.benchmark(group="agents")
def test_agent_error_handling(minimal_agent_config, benchmark):
    """Benchmark agent error handling.

    Target: <50ms
    Measures: Error recovery overhead
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM to raise error
        agent.llm = Mock()
        agent.llm.complete.side_effect = Exception("Test error")

        def execute_with_error():
            try:
                agent.execute({"input": "test"})
            except Exception:
                pass  # Expected error

        benchmark(execute_with_error)
        assert True  # Benchmark completed without crashing

@pytest.mark.benchmark(group="agents")
def test_agent_factory_creation(minimal_agent_config, benchmark):
    """Benchmark agent factory creation.

    Target: <50ms
    Measures: Factory pattern overhead
    """
    def create_via_factory():
        factory = AgentFactory()
        with patch.object(factory, 'tool_registry'):
            return factory.create_agent(minimal_agent_config)

    result = benchmark(create_via_factory)
    assert result is not None

@pytest.mark.benchmark(group="agents")
@pytest.mark.memory
def test_agent_memory_usage_100_executions(minimal_agent_config, mock_llm_fast):
    """Benchmark memory usage for 100 agent executions.

    Target: <200MB growth
    Measures: Memory leak detection
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)
        agent.llm = mock_llm_fast

        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        # Execute 100 times
        for _ in range(100):
            agent.execute({"input": "test"})

        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        growth_mb = mem_after - mem_before

        print(f"Memory growth for 100 executions: {growth_mb:.1f}MB")
        assert growth_mb < 200, f"Memory growth {growth_mb:.1f}MB exceeds 200MB threshold"

@pytest.mark.benchmark(group="agents")
def test_agent_concurrent_execution_3_agents(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark concurrent execution of 3 agents.

    Target: <300ms
    Measures: Multi-agent concurrency
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agents = [StandardAgent(minimal_agent_config) for _ in range(3)]
        for agent in agents:
            agent.llm = mock_llm_fast

        def execute_concurrent():
            from concurrent.futures import ThreadPoolExecutor, wait

            futures = []
            with ThreadPoolExecutor(max_workers=3) as pool:
                for i, agent in enumerate(agents):
                    future = pool.submit(agent.execute, {"input": f"query {i}"})
                    futures.append(future)

                wait(futures)
                return [f.result() for f in futures]

        results = benchmark(execute_concurrent)
        assert len(results) == 3

@pytest.mark.benchmark(group="agents")
def test_agent_concurrent_execution_10_agents(minimal_agent_config, mock_llm_fast, benchmark):
    """Benchmark concurrent execution of 10 agents.

    Target: <500ms
    Measures: Multi-agent scalability
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_registry:
        mock_registry.return_value.list_tools.return_value = []

        agents = [StandardAgent(minimal_agent_config) for _ in range(10)]
        for agent in agents:
            agent.llm = mock_llm_fast

        def execute_concurrent():
            from concurrent.futures import ThreadPoolExecutor, wait

            futures = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                for i, agent in enumerate(agents):
                    future = pool.submit(agent.execute, {"input": f"query {i}"})
                    futures.append(future)

                wait(futures)
                return [f.result() for f in futures]

        results = benchmark(execute_concurrent)
        assert len(results) == 10
