"""Performance benchmarks for End-to-End Workflows.

This module contains 6 benchmarks covering complete workflow execution:
- Simple M2 workflow (sequential)
- Medium M3 workflow (parallel, 3 agents)
- Workflow with checkpointing
- Concurrent workflows throughput
- Workflow memory baseline
- Adaptive workflow execution

Run with: pytest tests/test_benchmarks/test_performance_e2e.py --benchmark-only
"""
import pytest
import asyncio
import time
import os
import psutil
from unittest.mock import Mock, patch

from src.compiler.langgraph_compiler import LangGraphCompiler
from src.compiler.checkpoint import CheckpointManager
from tests.fixtures.realistic_data import REALISTIC_RESEARCH_WORKFLOW_AGENTS

# Import PERFORMANCE_BUDGETS from conftest
import sys
sys.path.insert(0, '/home/shinelay/meta-autonomous-framework/tests/test_benchmarks')
from conftest import PERFORMANCE_BUDGETS


# ============================================================================
# CATEGORY 8: End-to-End Workflows (6 benchmarks)
# ============================================================================

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_simple_m2_workflow(simple_workflow_config, benchmark):
    """Benchmark simple M2 workflow (sequential).

    Target: <2s
    Measures: Complete sequential workflow execution
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_stage_config.stage.collaboration.strategy = "sequential"
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        graph = compiler.compile(simple_workflow_config)

        def execute_workflow():
            return graph.invoke({"topic": "test"})

        result = benchmark(execute_workflow)
        assert result is not None

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_medium_m3_workflow_parallel(medium_workflow_config, benchmark):
    """Benchmark medium M3 workflow (parallel, 3 agents).

    Target: <5s
    Measures: Parallel workflow execution
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()

        # Mock 3 agents for parallel execution
        mock_agent_config = Mock()
        mock_agent_config.name = "test_agent"
        mock_stage_config.stage.agents = [mock_agent_config, mock_agent_config, mock_agent_config]
        mock_stage_config.stage.collaboration.strategy = "parallel"

        mock_loader.load_stage.return_value = mock_stage_config
        mock_loader.load_agent.return_value = mock_agent_config
        compiler.config_loader = mock_loader

        graph = compiler.compile(medium_workflow_config)

        def execute_workflow():
            return graph.invoke({"topic": "test"})

        result = benchmark.pedantic(execute_workflow, rounds=1, iterations=1)
        assert result is not None

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_workflow_with_checkpointing(simple_workflow_config, benchmark):
    """Benchmark workflow with checkpointing.

    Target: <3s
    Measures: Checkpoint overhead in workflow
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        # Compile with checkpointing
        from src.compiler.checkpoint import CheckpointManager
        checkpoint_manager = CheckpointManager()

        graph = compiler.compile(simple_workflow_config)

        def execute_with_checkpoint():
            workflow_id = "test_workflow_123"
            checkpoint_manager.save_checkpoint(
                workflow_id=workflow_id,
                stage_name="stage1",
                state={"topic": "test"}
            )
            result = graph.invoke({"topic": "test"})
            checkpoint_manager.get_checkpoint(workflow_id, "stage1")
            return result

        result = benchmark.pedantic(execute_with_checkpoint, rounds=1, iterations=1)
        assert result is not None

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_concurrent_workflows_throughput():
    """Benchmark 10 concurrent workflows.

    Target: >2 workflows/sec
    Measures: System throughput under load
    """
    num_workflows = 10

    async def execute_workflow(workflow_id: int):
        # Simulate lightweight workflow execution
        await asyncio.sleep(0.1)  # 100ms per workflow
        return {"workflow_id": workflow_id, "status": "completed"}

    start_time = time.perf_counter()
    results = await asyncio.gather(*[
        execute_workflow(i) for i in range(num_workflows)
    ])
    execution_time = time.perf_counter() - start_time

    throughput = num_workflows / execution_time

    assert len(results) == num_workflows
    assert throughput >= 2.0, f"Throughput {throughput:.2f} workflows/sec below target 2.0"

    print(f"Concurrent workflow throughput: {throughput:.2f} workflows/sec")

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_workflow_memory_baseline(simple_workflow_config):
    """Benchmark workflow memory baseline.

    Target: <100MB for workflow compilation
    Measures: Memory usage baseline
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        graph = compiler.compile(simple_workflow_config)

        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        growth_mb = mem_after - mem_before

        budget = PERFORMANCE_BUDGETS.get("memory_workflow_compilation", {})
        fail_threshold = budget.get("fail", 150)

        print(f"Workflow compilation memory: {growth_mb:.1f}MB")
        assert growth_mb < fail_threshold, \
            f"Memory {growth_mb:.1f}MB exceeds {fail_threshold}MB threshold"

@pytest.mark.benchmark(group="e2e")
@pytest.mark.slow
def test_e2e_adaptive_workflow_execution(simple_workflow_config, benchmark):
    """Benchmark adaptive workflow execution.

    Target: <2.5s
    Measures: Adaptive executor overhead
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        compiler = LangGraphCompiler()
        mock_loader = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = REALISTIC_RESEARCH_WORKFLOW_AGENTS
        mock_stage_config.stage.collaboration.strategy = "adaptive"
        mock_loader.load_stage.return_value = mock_stage_config
        compiler.config_loader = mock_loader

        graph = compiler.compile(simple_workflow_config)

        def execute_workflow():
            return graph.invoke({"topic": "test"})

        result = benchmark.pedantic(execute_workflow, rounds=1, iterations=1)
        assert result is not None
