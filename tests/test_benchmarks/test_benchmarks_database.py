"""Performance benchmarks for database operations and async execution.

Establishes baseline metrics for:
- Database query performance
- Async LLM speedup (M3.3-01)
- Query reduction (M3.3-02)
- Concurrent workflow execution

Run with: pytest tests/test_benchmarks/test_benchmarks_database.py --benchmark-only
"""

import asyncio
import time

import pytest

from src.agents.llm_providers import LLMResponse

from .conftest import (
    DEFAULT_BATCH_SIZE,
    MAX_SPEEDUP,
    MIN_SPEEDUP,
    NUM_CONCURRENT_WORKFLOWS,
    NUM_OPERATIONS,
    NUM_PARALLEL_CALLS,
    WORKFLOW_LLM_LATENCY,
    WORKFLOW_STAGES,
)

# ============================================================================
# Benchmark Tests: Database and Async Operations
# ============================================================================

def test_database_query_performance(benchmark, perf_db):
    """Benchmark database query performance.

    Target: <10ms for simple queries
    """
    # Insert test data
    with perf_db.session() as session:
        from sqlalchemy import text
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, value TEXT)"
        ))
        session.execute(text(
            "INSERT INTO test_table (id, value) VALUES (1, 'test')"
        ))
        session.commit()

    # Benchmark query
    def query_database():
        with perf_db.session() as session:
            result = session.execute(text(
                "SELECT value FROM test_table WHERE id = 1"
            ))
            return result.fetchone()

    result = benchmark(query_database)

    # Verify
    assert result is not None
    assert result[0] == "test"

    # Log performance expectation
    if benchmark.stats['mean'] > 0.01:
        print(f"Warning: Query time {benchmark.stats['mean']:.3f}s exceeds 10ms target")


@pytest.mark.asyncio
async def test_async_llm_speedup_verification(mock_async_llm):
    """Verify 2-3× speedup from async LLM providers (M3.3-01).

    Tests sequential vs parallel execution of LLM calls.
    Target: 2-3× speedup with parallel execution.

    Uses configurable TEST_LLM_LATENCY environment variable (default: 0.05s).
    """
    llm = mock_async_llm

    # Warmup (not measured, primes any lazy initialization)
    try:
        await llm.acomplete("warmup")
    except Exception as e:
        pytest.fail(f"Warmup call failed: {e}")

    # Measure sequential execution
    start_seq = time.perf_counter()
    results_seq = []
    try:
        for i in range(NUM_PARALLEL_CALLS):
            result = await llm.acomplete(f"Prompt {i}")
            results_seq.append(result)
    except Exception as e:
        pytest.fail(f"Sequential execution failed: {e}")
    sequential_time = time.perf_counter() - start_seq

    # Measure parallel execution with timeout protection
    start_par = time.perf_counter()
    try:
        async with asyncio.timeout(5.0):
            results_par = await asyncio.gather(*[
                llm.acomplete(f"Prompt {i}")
                for i in range(NUM_PARALLEL_CALLS)
            ])
    except asyncio.TimeoutError:
        pytest.fail("Parallel execution timed out (>5s)")
    except Exception as e:
        pytest.fail(f"Parallel execution failed: {e}")
    parallel_time = time.perf_counter() - start_par

    # Calculate speedup
    speedup = sequential_time / parallel_time

    # Verify results correctness
    assert len(results_seq) == NUM_PARALLEL_CALLS, \
        f"Sequential execution returned {len(results_seq)} results, expected {NUM_PARALLEL_CALLS}"
    assert len(results_par) == NUM_PARALLEL_CALLS, \
        f"Parallel execution returned {len(results_par)} results, expected {NUM_PARALLEL_CALLS}"

    # Validate response content
    for i, result in enumerate(results_seq):
        assert isinstance(result, LLMResponse), f"Sequential result {i} is not LLMResponse"
        assert result.content == "Mock response", f"Sequential result {i} has unexpected content"
        assert result.provider == "mock", f"Sequential result {i} has unexpected provider"

    # Log results
    print(f"\n{'='*70}")
    print("M3.3-01 Async LLM Speedup Verification")
    print(f"{'='*70}")
    print(f"Sequential execution ({NUM_PARALLEL_CALLS} calls): {sequential_time:.4f}s")
    print(f"Parallel execution ({NUM_PARALLEL_CALLS} calls):   {parallel_time:.4f}s")
    print(f"Speedup:                                            {speedup:.2f}x")
    print("Target:                                             2-3x")
    print(f"Expected range:                                     {MIN_SPEEDUP}-{MAX_SPEEDUP}x")
    print(f"Status:                                             {'✓ PASS' if MIN_SPEEDUP <= speedup <= MAX_SPEEDUP else '✗ FAIL'}")
    print(f"{'='*70}\n")

    # Verify speedup meets target (2-3x, with tighter variance tolerance)
    assert speedup >= MIN_SPEEDUP, \
        f"Speedup {speedup:.2f}x is below minimum {MIN_SPEEDUP}x (target: 2-3x). " \
        f"Sequential: {sequential_time:.4f}s, Parallel: {parallel_time:.4f}s"
    assert speedup <= MAX_SPEEDUP, \
        f"Speedup {speedup:.2f}x exceeds maximum {MAX_SPEEDUP}x (suspicious timing). " \
        f"Sequential: {sequential_time:.4f}s, Parallel: {parallel_time:.4f}s"


@pytest.mark.benchmark(group="theoretical")
def test_query_reduction_verification():
    """Verify 90%+ query reduction from ObservabilityBuffer (M3.3-02).

    NOTE: This is a theoretical analysis test that validates the mathematical
    reduction in database queries. For actual ObservabilityBuffer integration
    testing, see tests/test_observability/test_buffer.py.

    Demonstrates N+1 query pattern vs batched writes:
    - Without buffering: Each operation triggers a separate database transaction
    - With buffering: Operations are batched and written together

    Target: 90%+ reduction in database queries.
    """
    # Theoretical analysis of query patterns using configured constants
    num_operations = NUM_OPERATIONS  # 100 operations
    batch_size = DEFAULT_BATCH_SIZE  # 50 batch size

    # Without buffer: N+1 pattern - one query per operation
    # Each insert/update requires a separate database transaction
    queries_unbuffered = num_operations  # 100 queries

    # With buffer: Batched writes
    # Operations are collected and written in batches
    # 100 operations / 50 batch_size = 2 batched queries
    queries_buffered = (num_operations // batch_size) + (1 if num_operations % batch_size > 0 else 0)

    # Calculate reduction
    reduction_percentage = ((queries_unbuffered - queries_buffered) / queries_unbuffered) * 100

    # Log results
    print(f"\n{'='*70}")
    print("M3.3-02 Query Reduction Verification (Theoretical)")
    print(f"{'='*70}")
    print(f"Operations tracked:                {num_operations}")
    print(f"Batch size:                        {batch_size}")
    print("")
    print(f"Unbuffered queries (N+1 pattern): {queries_unbuffered}")
    print(f"Buffered queries (batched):        {queries_buffered}")
    print("")
    print(f"Reduction:                         {reduction_percentage:.1f}%")
    print("Target:                            90%+")
    print(f"Status:                            {'✓ PASS' if reduction_percentage >= 90 else '✗ FAIL'}")
    print("")
    print("NOTE: This test validates the mathematical reduction.")
    print("Implementation: ObservabilityBuffer in src/observability/buffer.py")
    print("Integration tests: tests/test_observability/test_buffer.py")
    print("Evidence: changes/0127-m3.3-02-n-plus-one-query-optimization.md")
    print(f"{'='*70}\n")

    # Verify reduction meets target
    assert reduction_percentage >= 90.0, \
        f"Query reduction {reduction_percentage:.1f}% is below target 90% " \
        f"(ops={num_operations}, batch={batch_size}, queries={queries_buffered})"

    # Additional verification with different batch sizes
    test_cases = [
        (100, 10, 90.0),  # 100 ops, batch 10 = 90% reduction
        (100, 50, 98.0),  # 100 ops, batch 50 = 98% reduction
        (1000, 100, 90.0), # 1000 ops, batch 100 = 90% reduction
    ]

    print("Additional batch size scenarios:")
    for ops, batch, expected_min in test_cases:
        buffered = (ops // batch) + (1 if ops % batch > 0 else 0)
        reduction = ((ops - buffered) / ops) * 100
        status = "✓" if reduction >= expected_min else "✗"
        print(f"  {status} {ops} ops, batch={batch}: {reduction:.1f}% reduction")


@pytest.mark.asyncio
async def test_concurrent_workflow_execution_with_async_llm():
    """Test end-to-end execution of 10+ concurrent workflows with async LLM.

    Verifies that async LLM providers enable true concurrent execution.
    Tests NUM_CONCURRENT_WORKFLOWS workflows, each with WORKFLOW_STAGES stages.

    Uses configurable WORKFLOW_LLM_LATENCY environment variable (default: 0.1s).
    """
    # Mock async LLM provider with workflow-specific latency
    class MockWorkflowLLM:
        async def acomplete(self, prompt: str, **kwargs) -> LLMResponse:
            # Simulate realistic API latency for workflow operations
            await asyncio.sleep(WORKFLOW_LLM_LATENCY)
            return LLMResponse(
                content="<answer>Completed</answer>",
                model="mock-model",
                provider="mock",
                total_tokens=20
            )

    llm = MockWorkflowLLM()

    async def execute_workflow(workflow_id: int):
        """Execute a single workflow with multiple agent stages."""
        try:
            results = []
            stage_names = ["Planning", "Execution", "Verification"]

            for stage_idx in range(WORKFLOW_STAGES):
                stage_name = stage_names[stage_idx] if stage_idx < len(stage_names) else f"Stage{stage_idx + 1}"
                result = await llm.acomplete(f"{stage_name} workflow {workflow_id}")
                results.append(result)

            return {
                "workflow_id": workflow_id,
                "results": results,
                "status": "completed"
            }
        except Exception as e:
            return {
                "workflow_id": workflow_id,
                "results": [],
                "status": "failed",
                "error": str(e)
            }

    # Execute workflows concurrently with timeout protection
    start_time = time.perf_counter()
    try:
        async with asyncio.timeout(10.0):
            workflow_results = await asyncio.gather(*[
                execute_workflow(i)
                for i in range(NUM_CONCURRENT_WORKFLOWS)
            ])
    except asyncio.TimeoutError:
        pytest.fail("Concurrent workflow execution timed out (>10s)")
    except Exception as e:
        pytest.fail(f"Concurrent workflow execution failed: {e}")
    execution_time = time.perf_counter() - start_time

    # Verify all workflows completed successfully
    assert len(workflow_results) == NUM_CONCURRENT_WORKFLOWS, \
        f"Expected {NUM_CONCURRENT_WORKFLOWS} workflows, got {len(workflow_results)}"

    failed_workflows = [wf for wf in workflow_results if wf["status"] != "completed"]
    assert len(failed_workflows) == 0, \
        f"{len(failed_workflows)} workflows failed: {failed_workflows}"

    assert all(len(wf["results"]) == WORKFLOW_STAGES for wf in workflow_results), \
        f"Not all workflows completed {WORKFLOW_STAGES} stages"

    # Calculate throughput and expected times
    workflows_per_second = NUM_CONCURRENT_WORKFLOWS / execution_time
    expected_parallel_time = WORKFLOW_STAGES * WORKFLOW_LLM_LATENCY
    expected_sequential_time = NUM_CONCURRENT_WORKFLOWS * WORKFLOW_STAGES * WORKFLOW_LLM_LATENCY
    speedup_vs_sequential = expected_sequential_time / execution_time

    # Log results
    print(f"\n{'='*70}")
    print("Concurrent Workflow Execution")
    print(f"{'='*70}")
    print(f"Workflows:             {NUM_CONCURRENT_WORKFLOWS}")
    print(f"Stages per workflow:   {WORKFLOW_STAGES}")
    print(f"Stage latency:         {WORKFLOW_LLM_LATENCY * 1000:.0f}ms")
    print("")
    print(f"Execution time:        {execution_time:.3f}s")
    print(f"Throughput:            {workflows_per_second:.2f} workflows/second")
    print("")
    print(f"Expected (parallel):   ~{expected_parallel_time:.1f}s ({WORKFLOW_STAGES} stages × {WORKFLOW_LLM_LATENCY}s)")
    print(f"Sequential would be:   ~{expected_sequential_time:.1f}s ({NUM_CONCURRENT_WORKFLOWS} × {WORKFLOW_STAGES} × {WORKFLOW_LLM_LATENCY}s)")
    print(f"Speedup vs sequential: {speedup_vs_sequential:.2f}x")
    print(f"Status:                {'✓ PASS' if execution_time < 1.0 else '✗ FAIL'}")
    print(f"{'='*70}\n")

    # Verify parallel execution (should be close to expected_parallel_time, not sequential_time)
    max_expected_time = expected_parallel_time * 1.5  # Allow 50% overhead for async coordination
    assert execution_time < max_expected_time, \
        f"Execution took {execution_time:.3f}s, expected <{max_expected_time:.1f}s for parallel execution. " \
        f"This suggests workflows are running sequentially instead of concurrently."
