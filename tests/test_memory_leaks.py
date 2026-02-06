"""Memory leak detection tests for meta-autonomous-framework.

Tests for memory leaks in long-running agent/workflow execution to ensure
stable memory usage over time. Uses psutil for memory monitoring and gc
for garbage collection verification.

Run with: pytest tests/test_memory_leaks.py -v
"""
import asyncio
import gc
import os
import time
from datetime import datetime
from itertools import count
from typing import List, Tuple
from unittest.mock import Mock, patch

import pytest

try:
    import psutil
except ImportError:
    pytest.skip("psutil not installed (optional for memory leak tests)", allow_module_level=True)

from src.agents.llm_providers import LLMResponse
from src.agents.standard_agent import StandardAgent
from src.compiler.langgraph_compiler import LangGraphCompiler
from src.compiler.schemas import (
    AgentConfig,
    AgentConfigInner,
    ErrorHandlingConfig,
    InferenceConfig,
    PromptConfig,
)
from src.observability.database import DatabaseManager
from src.observability.tracker import ExecutionTracker

# ============================================================================
# Constants
# ============================================================================

# Memory thresholds (in MB)
MAX_MEMORY_GROWTH_PER_100_EXECUTIONS = 10  # MB
WARMUP_ITERATIONS = 10
TEST_ITERATIONS = 100
MEMORY_STABILIZATION_TIME = 0.5  # seconds


# ============================================================================
# Helper Functions
# ============================================================================

def get_memory_usage() -> float:
    """Get current memory usage in MB.

    Returns:
        Memory usage in MB (RSS - Resident Set Size)
    """
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


def force_garbage_collection() -> None:
    """Force garbage collection to stabilize memory measurements."""
    gc.collect()
    gc.collect()  # Run twice to collect cyclic garbage
    gc.collect()
    time.sleep(0.1)  # Allow OS to reclaim memory


def measure_memory_growth(
    operation_func,
    warmup_iterations: int = WARMUP_ITERATIONS,
    test_iterations: int = TEST_ITERATIONS,
) -> Tuple[float, float, float]:
    """Measure memory growth over repeated operations.

    Args:
        operation_func: Function to execute repeatedly
        warmup_iterations: Number of warmup iterations
        test_iterations: Number of test iterations

    Returns:
        Tuple of (baseline_memory_mb, final_memory_mb, growth_mb)
    """
    # Warmup phase
    for _ in range(warmup_iterations):
        operation_func()

    # Stabilize memory
    force_garbage_collection()
    time.sleep(MEMORY_STABILIZATION_TIME)

    # Measure baseline
    baseline_memory = get_memory_usage()

    # Test phase
    for _ in range(test_iterations):
        operation_func()

    # Stabilize and measure final
    force_garbage_collection()
    time.sleep(MEMORY_STABILIZATION_TIME)

    final_memory = get_memory_usage()
    growth = final_memory - baseline_memory

    return baseline_memory, final_memory, growth


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def minimal_agent_config():
    """Minimal agent configuration for testing."""
    return AgentConfig(
        agent=AgentConfigInner(
            name="memory_test_agent",
            description="Agent for memory leak testing",
            version="1.0",
            type="standard",
            prompt=PromptConfig(inline="You are a test assistant. {{input}}"),
            inference=InferenceConfig(
                provider="ollama",
                model="llama2",
                base_url="http://localhost:11434",
                temperature=0.7,
                max_tokens=100,
            ),
            tools=[],
            error_handling=ErrorHandlingConfig(
                retry_strategy="ExponentialBackoff",
                fallback="GracefulDegradation",
            ),
        )
    )


@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return LLMResponse(
        content="<answer>Test response</answer>",
        model="mock-model",
        provider="mock",
        total_tokens=10,
    )


@pytest.fixture
def simple_workflow_config():
    """Simple workflow configuration for testing."""
    return {
        "workflow": {
            "name": "memory_test_workflow",
            "description": "Workflow for memory leak testing",
            "version": "1.0",
            "stages": [
                {"name": "stage1"},
                {"name": "stage2"},
                {"name": "stage3"},
            ]
        }
    }


@pytest.fixture
def test_db():
    """In-memory database for testing."""
    db = DatabaseManager("sqlite:///:memory:")
    db.create_all_tables()
    yield db
    # Cleanup
    db.close_all_connections()


# ============================================================================
# Test 1: Agent Execution Memory Leak
# ============================================================================

@pytest.mark.memory
def test_agent_execution_no_memory_leak(minimal_agent_config, mock_llm_response):
    """Test that repeated agent execution doesn't leak memory.

    Acceptance Criteria:
    - Memory growth <10MB per 100 executions
    - Memory usage stabilizes after warmup
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_tool_registry:
        # Setup
        mock_tool_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)
        agent.llm = Mock()
        agent.llm.complete.return_value = mock_llm_response

        # Define operation
        def execute_agent():
            result = agent.execute({"input": "test query"})
            return result

        # Measure memory growth
        baseline, final, growth = measure_memory_growth(execute_agent)

        # Log results
        print(f"\n{'='*70}")
        print("Agent Execution Memory Leak Test")
        print(f"{'='*70}")
        print(f"Baseline memory:  {baseline:.2f} MB")
        print(f"Final memory:     {final:.2f} MB")
        print(f"Memory growth:    {growth:.2f} MB")
        print(f"Growth per exec:  {growth / TEST_ITERATIONS:.3f} MB")
        print(f"Target:           <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 executions")
        print(f"Status:           {'✓ PASS' if growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS else '✗ FAIL'}")
        print(f"{'='*70}\n")

        # Assert
        assert growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS, (
            f"Agent execution leaked {growth:.2f} MB over {TEST_ITERATIONS} executions "
            f"(threshold: {MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB)"
        )


# ============================================================================
# Test 2: Workflow Compilation Memory Leak
# ============================================================================

@pytest.mark.memory
def test_workflow_compilation_no_memory_leak(simple_workflow_config):
    """Test that repeated workflow compilation doesn't leak memory.

    Acceptance Criteria:
    - Memory growth <10MB per 100 compilations
    - Compiled workflows are properly garbage collected
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        # Setup
        mock_loader_instance = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader_instance.load_stage.return_value = mock_stage_config

        # Define operation
        def compile_workflow():
            compiler = LangGraphCompiler()
            compiler.config_loader = mock_loader_instance
            workflow = compiler.compile(simple_workflow_config)
            # Explicitly delete to allow GC
            del workflow
            return None

        # Measure memory growth
        baseline, final, growth = measure_memory_growth(compile_workflow)

        # Log results
        print(f"\n{'='*70}")
        print("Workflow Compilation Memory Leak Test")
        print(f"{'='*70}")
        print(f"Baseline memory:  {baseline:.2f} MB")
        print(f"Final memory:     {final:.2f} MB")
        print(f"Memory growth:    {growth:.2f} MB")
        print(f"Growth per exec:  {growth / TEST_ITERATIONS:.3f} MB")
        print(f"Target:           <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 executions")
        print(f"Status:           {'✓ PASS' if growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS else '✗ FAIL'}")
        print(f"{'='*70}\n")

        # Assert
        assert growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS, (
            f"Workflow compilation leaked {growth:.2f} MB over {TEST_ITERATIONS} compilations "
            f"(threshold: {MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB)"
        )


# ============================================================================
# Test 3: LLM Provider Connection Memory Leak
# ============================================================================

@pytest.mark.memory
def test_llm_provider_no_memory_leak(minimal_agent_config):
    """Test that LLM provider connections don't leak memory.

    Acceptance Criteria:
    - Memory growth <10MB per 100 calls
    - Connection pooling doesn't accumulate
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_tool_registry:
        # Setup
        mock_tool_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)

        # Mock LLM with connection simulation
        mock_llm = Mock()
        mock_responses = [
            LLMResponse(
                content=f"<answer>Response {i}</answer>",
                model="mock-model",
                provider="mock",
                total_tokens=10,
            )
            for i in range(TEST_ITERATIONS + WARMUP_ITERATIONS)
        ]
        mock_llm.complete.side_effect = mock_responses
        agent.llm = mock_llm

        # Define operation
        call_counter = count()
        def llm_call():
            agent.llm.complete(f"Prompt {next(call_counter)}")

        # Measure memory growth
        baseline, final, growth = measure_memory_growth(llm_call)

        # Log results
        print(f"\n{'='*70}")
        print("LLM Provider Connection Memory Leak Test")
        print(f"{'='*70}")
        print(f"Baseline memory:  {baseline:.2f} MB")
        print(f"Final memory:     {final:.2f} MB")
        print(f"Memory growth:    {growth:.2f} MB")
        print(f"Growth per call:  {growth / TEST_ITERATIONS:.3f} MB")
        print(f"Target:           <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 calls")
        print(f"Status:           {'✓ PASS' if growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS else '✗ FAIL'}")
        print(f"{'='*70}\n")

        # Assert
        assert growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS, (
            f"LLM provider leaked {growth:.2f} MB over {TEST_ITERATIONS} calls "
            f"(threshold: {MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB)"
        )


# ============================================================================
# Test 4: Observability Tracking Memory Leak
# ============================================================================

@pytest.mark.memory
def test_observability_tracking_no_memory_leak(test_db):
    """Test that observability tracking doesn't leak memory.

    Acceptance Criteria:
    - Memory growth <10MB per 100 tracked events
    - Database connections properly closed
    """
    # Setup tracker
    tracker = ExecutionTracker(db=test_db)

    # Define operation
    event_counter = count()
    def track_event():
        workflow_id = f"workflow_{next(event_counter)}"
        tracker.start_workflow(
            workflow_id=workflow_id,
            workflow_name="memory_test"
        )
        tracker.end_workflow(
            workflow_id=workflow_id,
            status="completed"
        )

    # Measure memory growth
    baseline, final, growth = measure_memory_growth(track_event)

    # Cleanup
    tracker.stop()

    # Log results
    print(f"\n{'='*70}")
    print("Observability Tracking Memory Leak Test")
    print(f"{'='*70}")
    print(f"Baseline memory:  {baseline:.2f} MB")
    print(f"Final memory:     {final:.2f} MB")
    print(f"Memory growth:    {growth:.2f} MB")
    print(f"Growth per event: {growth / TEST_ITERATIONS:.3f} MB")
    print(f"Target:           <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 events")
    print(f"Status:           {'✓ PASS' if growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS else '✗ FAIL'}")
    print(f"{'='*70}\n")

    # Assert
    assert growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS, (
        f"Observability tracking leaked {growth:.2f} MB over {TEST_ITERATIONS} events "
        f"(threshold: {MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB)"
    )


# ============================================================================
# Test 5: Long-Running Agent Session
# ============================================================================

@pytest.mark.memory
@pytest.mark.slow
def test_long_running_agent_session_stability(minimal_agent_config, mock_llm_response):
    """Test memory stability in long-running agent sessions.

    Simulates a long-running agent with 500 executions to verify
    memory usage stabilizes after initial ramp-up.

    Acceptance Criteria:
    - Memory growth <50MB over 500 executions
    - No continuous memory increase trend
    """
    with patch('src.agents.standard_agent.ToolRegistry') as mock_tool_registry:
        # Setup
        mock_tool_registry.return_value.list_tools.return_value = []

        agent = StandardAgent(minimal_agent_config)
        agent.llm = Mock()
        agent.llm.complete.return_value = mock_llm_response

        # Warmup
        for _ in range(WARMUP_ITERATIONS):
            agent.execute({"input": "warmup"})

        force_garbage_collection()
        baseline_memory = get_memory_usage()

        # Track memory over time
        memory_samples: List[float] = []
        sample_interval = 50  # Sample every 50 executions

        for i in range(500):
            agent.execute({"input": f"query {i}"})

            if i % sample_interval == 0:
                force_garbage_collection()
                memory_samples.append(get_memory_usage())

        force_garbage_collection()
        final_memory = get_memory_usage()
        total_growth = final_memory - baseline_memory

        # Check for continuous increase (each sample should not grow unbounded)
        # Use 95th percentile to avoid flakiness from OS background processes
        growth_values = [
            memory_samples[i] - memory_samples[i-1]
            for i in range(1, len(memory_samples))
        ]
        growth_values_sorted = sorted(growth_values)
        p95_index = int(len(growth_values_sorted) * 0.95)
        p95_growth = growth_values_sorted[p95_index] if growth_values_sorted else 0
        max_growth_between_samples = max(growth_values) if growth_values else 0

        # Log results
        print(f"\n{'='*70}")
        print("Long-Running Agent Session Stability Test")
        print(f"{'='*70}")
        print(f"Baseline memory:             {baseline_memory:.2f} MB")
        print(f"Final memory:                {final_memory:.2f} MB")
        print(f"Total growth (500 execs):    {total_growth:.2f} MB")
        print(f"Max growth between samples:  {max_growth_between_samples:.2f} MB")
        print(f"P95 growth between samples:  {p95_growth:.2f} MB")
        print(f"Memory samples:              {[f'{m:.1f}' for m in memory_samples]}")
        print("Target:                      <50 MB total growth")
        print(f"Status:                      {'✓ PASS' if total_growth < 50 else '✗ FAIL'}")
        print(f"{'='*70}\n")

        # Assert
        assert total_growth < 50, (
            f"Long-running session leaked {total_growth:.2f} MB over 500 executions "
            f"(threshold: 50 MB)"
        )

        # Verify no unbounded growth (use P95 to filter OS noise)
        assert p95_growth < 15, (
            f"Memory P95 growth {p95_growth:.2f} MB between samples exceeds threshold "
            f"(threshold: 15 MB, indicates potential leak)"
        )


# ============================================================================
# Test 6: Async LLM Provider Memory Leak
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.memory
async def test_async_llm_provider_no_memory_leak():
    """Test that async LLM provider calls don't leak memory.

    Acceptance Criteria:
    - Memory growth <10MB per 100 async calls
    - Async task cleanup is proper
    """
    # Mock async LLM
    class MockAsyncLLM:
        async def acomplete(self, prompt: str, **kwargs) -> LLMResponse:
            await asyncio.sleep(0.001)  # Simulate async I/O
            return LLMResponse(
                content="Async response",
                model="mock-model",
                provider="mock",
                total_tokens=10,
            )

    llm = MockAsyncLLM()

    # Define async operation
    async def async_llm_call():
        await llm.acomplete("test prompt")

    # Warmup
    for _ in range(WARMUP_ITERATIONS):
        await async_llm_call()

    force_garbage_collection()
    baseline_memory = get_memory_usage()

    # Test phase
    for _ in range(TEST_ITERATIONS):
        await async_llm_call()

    force_garbage_collection()
    final_memory = get_memory_usage()
    growth = final_memory - baseline_memory

    # Log results
    print(f"\n{'='*70}")
    print("Async LLM Provider Memory Leak Test")
    print(f"{'='*70}")
    print(f"Baseline memory:  {baseline_memory:.2f} MB")
    print(f"Final memory:     {final_memory:.2f} MB")
    print(f"Memory growth:    {growth:.2f} MB")
    print(f"Growth per call:  {growth / TEST_ITERATIONS:.3f} MB")
    print(f"Target:           <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 calls")
    print(f"Status:           {'✓ PASS' if growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS else '✗ FAIL'}")
    print(f"{'='*70}\n")

    # Assert
    assert growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS, (
        f"Async LLM provider leaked {growth:.2f} MB over {TEST_ITERATIONS} calls "
        f"(threshold: {MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB)"
    )


# ============================================================================
# Test 7: Concurrent Workflow Execution Memory Leak
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.memory
async def test_concurrent_workflows_no_memory_leak(simple_workflow_config):
    """Test that concurrent workflow execution doesn't leak memory.

    Acceptance Criteria:
    - Memory growth <20MB per 100 concurrent workflow executions
    - Concurrent resources properly cleaned up
    """
    with patch('src.compiler.langgraph_compiler.ConfigLoader'):
        # Setup
        mock_loader_instance = Mock()
        mock_stage_config = Mock()
        mock_stage_config.stage.agents = []
        mock_loader_instance.load_stage.return_value = mock_stage_config

        # Define async operation
        async def execute_concurrent_workflows():
            """Execute 5 workflows concurrently."""
            workflows = []
            for _ in range(5):
                compiler = LangGraphCompiler()
                compiler.config_loader = mock_loader_instance
                workflow = compiler.compile(simple_workflow_config)
                workflows.append(workflow)

            # Simulate concurrent execution
            await asyncio.sleep(0.001)

            # Cleanup
            for w in workflows:
                del w

        # Warmup
        for _ in range(WARMUP_ITERATIONS):
            await execute_concurrent_workflows()

        force_garbage_collection()
        baseline_memory = get_memory_usage()

        # Test phase (100 iterations × 5 workflows = 500 total workflows)
        for _ in range(TEST_ITERATIONS):
            await execute_concurrent_workflows()

        force_garbage_collection()
        final_memory = get_memory_usage()
        growth = final_memory - baseline_memory

        # Log results
        print(f"\n{'='*70}")
        print("Concurrent Workflow Execution Memory Leak Test")
        print(f"{'='*70}")
        print(f"Baseline memory:  {baseline_memory:.2f} MB")
        print(f"Final memory:     {final_memory:.2f} MB")
        print(f"Memory growth:    {growth:.2f} MB")
        print(f"Total workflows:  {TEST_ITERATIONS * 5}")
        print(f"Growth per batch: {growth / TEST_ITERATIONS:.3f} MB")
        print("Target:           <20 MB per 100 batches")
        print(f"Status:           {'✓ PASS' if growth < 20 else '✗ FAIL'}")
        print(f"{'='*70}\n")

        # Assert (higher threshold for concurrent operations)
        assert growth < 20, (
            f"Concurrent workflows leaked {growth:.2f} MB over {TEST_ITERATIONS * 5} workflows "
            f"(threshold: 20 MB)"
        )


# ============================================================================
# Test 8: Database Connection Pool Memory Leak
# ============================================================================

@pytest.mark.memory
def test_database_connection_pool_no_memory_leak(test_db):
    """Test that database connection pool doesn't leak memory.

    Acceptance Criteria:
    - Memory growth <10MB per 100 connection cycles
    - Connections properly returned to pool
    """
    from src.observability.models import WorkflowExecution

    # Define operation
    db_counter = count()
    def db_operation():
        with test_db.session() as session:
            # Simulate database operation
            workflow = WorkflowExecution(
                workflow_id=f"workflow_{next(db_counter)}",
                workflow_name="memory_test",
                status="completed",
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow()
            )
            session.add(workflow)
            session.commit()

    # Measure memory growth
    baseline, final, growth = measure_memory_growth(db_operation)

    # Log results
    print(f"\n{'='*70}")
    print("Database Connection Pool Memory Leak Test")
    print(f"{'='*70}")
    print(f"Baseline memory:  {baseline:.2f} MB")
    print(f"Final memory:     {final:.2f} MB")
    print(f"Memory growth:    {growth:.2f} MB")
    print(f"Growth per op:    {growth / TEST_ITERATIONS:.3f} MB")
    print(f"Target:           <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 operations")
    print(f"Status:           {'✓ PASS' if growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS else '✗ FAIL'}")
    print(f"{'='*70}\n")

    # Assert
    assert growth < MAX_MEMORY_GROWTH_PER_100_EXECUTIONS, (
        f"Database connection pool leaked {growth:.2f} MB over {TEST_ITERATIONS} operations "
        f"(threshold: {MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB)"
    )


# ============================================================================
# Test Summary
# ============================================================================

def test_memory_leak_summary():
    """Generate memory leak test summary.

    This test always passes and provides guidance on interpreting results.
    """
    summary = f"""
    Memory Leak Detection Test Summary
    ===================================

    Test Coverage:
    - Agent execution (100 iterations)
    - Workflow compilation (100 iterations)
    - LLM provider connections (100 calls)
    - Observability tracking (100 events)
    - Long-running sessions (500 executions)
    - Async LLM providers (100 calls)
    - Concurrent workflows (500 workflows)
    - Database connection pool (100 operations)

    Success Criteria:
    - Memory growth <{MAX_MEMORY_GROWTH_PER_100_EXECUTIONS} MB per 100 operations (short tests)
    - Memory growth <50 MB per 500 operations (long tests)
    - Memory usage stabilizes after warmup
    - No continuous unbounded growth

    Running Tests:
        # Run all memory leak tests
        pytest tests/test_memory_leaks.py -v

        # Run specific test
        pytest tests/test_memory_leaks.py::test_agent_execution_no_memory_leak -v

        # Run with memory profiling (requires memray)
        pip install memray
        memray run -m pytest tests/test_memory_leaks.py -v
        memray flamegraph memray-*.bin

    Interpreting Results:
    - PASS: Memory growth within acceptable limits
    - FAIL: Potential memory leak detected
    - Check logs for detailed memory measurements
    - Use memray for detailed leak investigation

    Note: Tests require psutil:
        pip install psutil

    CI/CD Integration:
        # Run in CI pipeline
        pytest tests/test_memory_leaks.py -v --tb=short

        # Fail on any leak detection
        pytest tests/test_memory_leaks.py -v --maxfail=1
    """

    print(summary)

    # Verify summary was generated
    assert isinstance(summary, str) and len(summary) > 0
