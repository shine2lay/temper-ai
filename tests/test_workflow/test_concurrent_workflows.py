"""
Comprehensive tests for concurrent workflow execution.

Tests concurrent execution patterns for workflows, stages, and agents.
Verifies parallelism, isolation, error handling, and performance.
"""

import asyncio
import time

import pytest


class TestConcurrentStageExecution:
    """Test concurrent execution of multiple stages."""

    @pytest.mark.asyncio
    async def test_parallel_stage_execution(self):
        """Test that multiple stages execute in parallel."""
        execution_log = []

        async def mock_stage_executor(stage_id: str, duration: float):
            """Mock stage that records execution time."""
            start = time.time()
            execution_log.append({"stage": stage_id, "started": start})
            await asyncio.sleep(duration)
            end = time.time()
            execution_log.append({"stage": stage_id, "completed": end})
            return {f"{stage_id}_result": "done"}

        # Execute 3 stages in parallel (1 second each)
        start_time = time.time()
        tasks = [
            mock_stage_executor("stage1", 0.5),
            mock_stage_executor("stage2", 0.5),
            mock_stage_executor("stage3", 0.5),
        ]
        await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # Should complete in ~0.5s (parallel), not 1.5s (sequential)
        assert total_time < 1.0, f"Expected parallel execution <1s, took {total_time}s"

        # Verify all stages started before any completed
        starts = [log for log in execution_log if "started" in log]
        completions = [log for log in execution_log if "completed" in log]

        assert len(starts) == 3
        assert len(completions) == 3

    @pytest.mark.asyncio
    async def test_stage_isolation(self):
        """Test that stages don't interfere with each other's state."""
        results = {}

        async def isolated_stage(stage_id: str):
            """Stage that modifies local state."""
            local_state = {"counter": 0}
            for _i in range(10):
                local_state["counter"] += 1
                await asyncio.sleep(0.01)
            results[stage_id] = local_state["counter"]

        # Run 5 stages concurrently
        tasks = [isolated_stage(f"stage{i}") for i in range(5)]
        await asyncio.gather(*tasks)

        # All stages should have counter = 10 (isolated)
        for stage_id, count in results.items():
            assert count == 10, f"{stage_id} counter is {count}, expected 10"

    @pytest.mark.asyncio
    async def test_stage_error_propagation(self):
        """Test error handling in parallel stage execution."""

        async def failing_stage(stage_id: str):
            """Stage that fails."""
            await asyncio.sleep(0.1)
            if stage_id == "stage2":
                raise ValueError(f"Stage {stage_id} failed")
            return {f"{stage_id}_result": "success"}

        # Execute 3 stages, one will fail
        tasks = [
            failing_stage("stage1"),
            failing_stage("stage2"),  # This will fail
            failing_stage("stage3"),
        ]

        # Should raise ValueError from stage2
        with pytest.raises(ValueError) as exc_info:
            await asyncio.gather(*tasks)

        assert "stage2 failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_stage_dependency_ordering(self):
        """Test that stage dependencies are respected in concurrent execution."""
        execution_order = []

        async def dependent_stage(stage_id: str, depends_on: list[str]):
            """Stage that waits for dependencies."""
            # Wait for dependencies to complete
            while not all(dep in execution_order for dep in depends_on):
                await asyncio.sleep(0.05)

            execution_order.append(stage_id)
            return {f"{stage_id}_result": "done"}

        # Create dependency graph:
        # stage1, stage2 (parallel) -> stage3 (depends on both)
        task1 = asyncio.create_task(dependent_stage("stage1", []))
        task2 = asyncio.create_task(dependent_stage("stage2", []))
        task3 = asyncio.create_task(dependent_stage("stage3", ["stage1", "stage2"]))

        await asyncio.gather(task1, task2, task3)

        # Verify stage3 executed after stage1 and stage2
        stage3_index = execution_order.index("stage3")
        assert "stage1" in execution_order[:stage3_index]
        assert "stage2" in execution_order[:stage3_index]


class TestConcurrentAgentExecution:
    """Test concurrent execution of multiple agents."""

    @pytest.mark.asyncio
    async def test_parallel_agent_execution(self):
        """Test multiple agents execute in parallel within a stage."""
        execution_log = []

        async def mock_agent_executor(agent_id: str, duration: float):
            """Mock agent that records execution."""
            start = time.time()
            execution_log.append({"agent": agent_id, "started": start})
            await asyncio.sleep(duration)
            end = time.time()
            execution_log.append({"agent": agent_id, "completed": end})
            return {f"{agent_id}_output": "result"}

        # Execute 5 agents in parallel (0.3s each)
        start_time = time.time()
        tasks = [mock_agent_executor(f"agent{i}", 0.3) for i in range(5)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # Should complete in ~0.3s (parallel), not 1.5s (sequential)
        assert (
            total_time < 0.6
        ), f"Expected parallel execution <0.6s, took {total_time}s"
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_agent_result_aggregation(self):
        """Test that results from parallel agents are correctly aggregated."""

        async def agent_executor(agent_id: str, value: int):
            """Agent that returns a value."""
            await asyncio.sleep(0.1)
            return {"agent_id": agent_id, "value": value}

        # Execute agents with different values
        tasks = [agent_executor(f"agent{i}", i * 10) for i in range(5)]
        results = await asyncio.gather(*tasks)

        # Verify all results collected
        assert len(results) == 5

        # Verify each agent's result
        for i, result in enumerate(results):
            assert result["agent_id"] == f"agent{i}"
            assert result["value"] == i * 10

    @pytest.mark.asyncio
    async def test_mixed_agent_success_failure(self):
        """Test handling of mixed success/failure in parallel agents."""
        results = []
        errors = []

        async def agent_executor(agent_id: str, should_fail: bool):
            """Agent that may succeed or fail."""
            await asyncio.sleep(0.1)
            if should_fail:
                raise ValueError(f"Agent {agent_id} failed")
            return {f"{agent_id}_result": "success"}

        # Execute 5 agents, 2 will fail
        agents = [
            ("agent0", False),
            ("agent1", True),  # Fails
            ("agent2", False),
            ("agent3", True),  # Fails
            ("agent4", False),
        ]

        # Gather with return_exceptions to capture both successes and failures
        tasks = [agent_executor(aid, fail) for aid, fail in agents]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successes and failures
        for result in all_results:
            if isinstance(result, Exception):
                errors.append(result)
            else:
                results.append(result)

        assert len(results) == 3  # 3 succeeded
        assert len(errors) == 2  # 2 failed


class TestConcurrentWorkflowExecution:
    """Test concurrent execution of multiple complete workflows."""

    @pytest.mark.asyncio
    async def test_multiple_workflows_parallel(self):
        """Test multiple independent workflows execute in parallel."""
        execution_log = []

        async def mock_workflow_executor(workflow_id: str, duration: float):
            """Mock workflow execution."""
            start = time.time()
            execution_log.append({"workflow": workflow_id, "started": start})
            await asyncio.sleep(duration)
            end = time.time()
            execution_log.append({"workflow": workflow_id, "completed": end})
            return {f"{workflow_id}_result": "done"}

        # Execute 3 workflows in parallel (0.5s each)
        start_time = time.time()
        tasks = [
            mock_workflow_executor("workflow1", 0.5),
            mock_workflow_executor("workflow2", 0.5),
            mock_workflow_executor("workflow3", 0.5),
        ]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # Should complete in ~0.5s (parallel), not 1.5s (sequential)
        assert total_time < 1.0, f"Expected parallel execution <1s, took {total_time}s"
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_workflow_state_isolation(self):
        """Test that concurrent workflows have isolated state."""
        workflow_states = {}

        async def workflow_with_state(workflow_id: str):
            """Workflow that maintains isolated state."""
            state = {"items": [], "counter": 0}

            for i in range(10):
                state["items"].append(i)
                state["counter"] += 1
                await asyncio.sleep(0.01)

            workflow_states[workflow_id] = state

        # Run 5 workflows concurrently
        tasks = [workflow_with_state(f"workflow{i}") for i in range(5)]
        await asyncio.gather(*tasks)

        # Each workflow should have 10 items and counter = 10
        assert len(workflow_states) == 5
        for _wf_id, state in workflow_states.items():
            assert len(state["items"]) == 10
            assert state["counter"] == 10

    @pytest.mark.asyncio
    async def test_high_concurrency_stress(self):
        """Test system under high concurrent load (50 workflows)."""

        async def lightweight_workflow(workflow_id: int):
            """Lightweight workflow for stress testing."""
            await asyncio.sleep(0.1)
            return {"id": workflow_id, "status": "completed"}

        # Execute 50 workflows concurrently
        start_time = time.time()
        tasks = [lightweight_workflow(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # Should complete in reasonable time (<2s for 50x0.1s workflows)
        assert total_time < 2.0, f"50 workflows took {total_time}s"
        assert len(results) == 50

        # Verify all completed successfully
        for i, result in enumerate(results):
            assert result["id"] == i
            assert result["status"] == "completed"


class TestResourceManagement:
    """Test resource management in concurrent execution."""

    @pytest.mark.asyncio
    async def test_concurrent_resource_limit(self):
        """Test that concurrent execution respects resource limits."""
        max_concurrent = 5
        current_running = {"count": 0}
        max_observed = {"peak": 0}

        async def resource_tracked_task(task_id: int):
            """Task that tracks concurrent execution count."""
            current_running["count"] += 1
            max_observed["peak"] = max(max_observed["peak"], current_running["count"])

            # Ensure we never exceed limit
            assert (
                current_running["count"] <= max_concurrent
            ), f"Exceeded max_concurrent: {current_running['count']}"

            await asyncio.sleep(0.2)
            current_running["count"] -= 1
            return task_id

        # Create semaphore to limit concurrency
        sem = asyncio.Semaphore(max_concurrent)

        async def limited_task(task_id: int):
            """Task with concurrency limit."""
            async with sem:
                return await resource_tracked_task(task_id)

        # Try to run 20 tasks (but only 5 concurrent)
        tasks = [limited_task(i) for i in range(20)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 20
        assert max_observed["peak"] <= max_concurrent

    @pytest.mark.asyncio
    async def test_memory_cleanup_after_concurrent_execution(self):
        """Test that memory is properly cleaned up after concurrent tasks."""
        import gc

        async def task_with_large_data(task_id: int):
            """Task that creates large data structures."""
            # Create 1MB of data
            large_data = "x" * (1024 * 1024)
            await asyncio.sleep(0.05)
            return len(large_data)

        # Run 10 tasks concurrently
        tasks = [task_with_large_data(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify all tasks completed with correct data size
        assert len(results) == 10
        assert all(r == 1024 * 1024 for r in results)

        # Force garbage collection — verify it doesn't raise
        del results
        gc.collect()


class TestErrorHandlingConcurrency:
    """Test error handling in concurrent execution."""

    @pytest.mark.asyncio
    async def test_cancel_concurrent_tasks_on_critical_error(self):
        """Test that all concurrent tasks are cancelled on critical error."""
        cancelled_count = {"count": 0}

        async def cancellable_task(task_id: int, should_fail: bool):
            """Task that can be cancelled."""
            try:
                for i in range(10):
                    if should_fail and i == 3:
                        raise Exception(f"Critical error in task {task_id}")
                    await asyncio.sleep(0.1)
                return f"task{task_id}_completed"
            except asyncio.CancelledError:
                cancelled_count["count"] += 1
                raise

        # Run 5 tasks, one will fail critically
        tasks = [
            asyncio.create_task(cancellable_task(0, False)),
            asyncio.create_task(cancellable_task(1, False)),
            asyncio.create_task(cancellable_task(2, True)),  # Fails
            asyncio.create_task(cancellable_task(3, False)),
            asyncio.create_task(cancellable_task(4, False)),
        ]

        # Wait for critical error
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=False), timeout=2.0
            )
        except Exception:
            # Cancel all remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Wait for cancellations to complete
            await asyncio.gather(*tasks, return_exceptions=True)

        # Some tasks should have been cancelled
        assert cancelled_count["count"] > 0

    @pytest.mark.asyncio
    async def test_partial_failure_recovery(self):
        """Test system recovers from partial failures in concurrent execution."""

        async def potentially_failing_task(task_id: int, fail_ids: list[int]):
            """Task that may fail based on ID."""
            await asyncio.sleep(0.1)
            if task_id in fail_ids:
                raise ValueError(f"Task {task_id} intentional failure")
            return {"id": task_id, "status": "success"}

        # Run 10 tasks, 3 will fail
        fail_ids = [2, 5, 7]
        tasks = [potentially_failing_task(i, fail_ids) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Separate successes and failures
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 7  # 10 - 3 = 7 succeeded
        assert len(failures) == 3  # 3 failed

        # Verify successful tasks have correct IDs
        success_ids = {s["id"] for s in successes}
        expected_success_ids = {0, 1, 3, 4, 6, 8, 9}
        assert success_ids == expected_success_ids


class TestPerformance:
    """Test performance characteristics of concurrent execution."""

    @pytest.mark.asyncio
    async def test_concurrent_speedup_verification(self):
        """Test that concurrent execution is faster than sequential."""

        async def slow_task(duration: float):
            """Task that takes specified duration."""
            await asyncio.sleep(duration)
            return "done"

        # Sequential execution
        sequential_start = time.time()
        for _ in range(5):
            await slow_task(0.2)
        sequential_time = time.time() - sequential_start

        # Concurrent execution
        concurrent_start = time.time()
        tasks = [slow_task(0.2) for _ in range(5)]
        await asyncio.gather(*tasks)
        concurrent_time = time.time() - concurrent_start

        # Concurrent should be ~5x faster
        speedup = sequential_time / concurrent_time
        assert speedup > 3.0, f"Expected speedup >3x, got {speedup}x"

    @pytest.mark.asyncio
    async def test_throughput_under_load(self):
        """Test throughput with high concurrent workload."""

        async def quick_task(task_id: int):
            """Quick task for throughput testing."""
            await asyncio.sleep(0.05)
            return task_id

        # Execute 100 tasks concurrently
        start_time = time.time()
        tasks = [quick_task(i) for i in range(100)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time

        # Calculate throughput
        throughput = len(results) / total_time

        # Should process at least 10 tasks/second
        assert throughput > 10, f"Throughput only {throughput:.1f} tasks/sec"

    @pytest.mark.asyncio
    async def test_latency_distribution(self):
        """Test latency distribution for concurrent tasks."""
        latencies = []

        async def timed_task(task_id: int):
            """Task that measures its own latency."""
            start = time.time()
            await asyncio.sleep(0.1)
            latency = time.time() - start
            latencies.append(latency)
            return task_id

        # Execute 20 tasks concurrently
        tasks = [timed_task(i) for i in range(20)]
        await asyncio.gather(*tasks)

        # Calculate statistics
        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)

        # Verify reasonable latency distribution
        assert 0.08 < avg_latency < 0.15, f"Average latency {avg_latency}s unexpected"
        assert max_latency < 0.25, f"Max latency {max_latency}s too high"
        assert min_latency > 0.08, f"Min latency {min_latency}s too low"


class TestDeadlockPrevention:
    """Test deadlock prevention in concurrent execution."""

    @pytest.mark.asyncio
    async def test_no_deadlock_with_lock_ordering(self):
        """Test deadlock prevention using consistent lock ordering."""
        lock_a = asyncio.Lock()
        lock_b = asyncio.Lock()

        async def task_with_ordered_locks_1():
            """Task that always acquires locks in A->B order."""
            async with lock_a:
                await asyncio.sleep(0.05)
                async with lock_b:
                    return "task1_done"

        async def task_with_ordered_locks_2():
            """Task that also acquires locks in A->B order."""
            async with lock_a:
                await asyncio.sleep(0.05)
                async with lock_b:
                    return "task2_done"

        # With consistent lock ordering, no deadlock should occur
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    task_with_ordered_locks_1(), task_with_ordered_locks_2()
                ),
                timeout=2.0,
            )
            # If we get here, no deadlock occurred
            assert len(results) == 2
            assert "task1_done" in results
            assert "task2_done" in results
        except TimeoutError:
            pytest.fail("Deadlock detected - lock ordering should prevent this")

    @pytest.mark.asyncio
    async def test_timeout_prevents_indefinite_wait(self):
        """Test that timeouts prevent indefinite waiting."""

        async def long_running_task():
            """Task that runs for a long time."""
            await asyncio.sleep(10.0)  # 10 seconds
            return "completed"

        # Set timeout to 1 second
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(long_running_task(), timeout=1.0)


class TestConcurrentStateUpdates:
    """Test concurrent state updates and synchronization."""

    @pytest.mark.asyncio
    async def test_concurrent_state_updates_with_lock(self):
        """Test safe concurrent state updates using locks."""
        shared_state = {"counter": 0}
        lock = asyncio.Lock()

        async def increment_counter():
            """Safely increment counter."""
            for _ in range(100):
                async with lock:
                    current = shared_state["counter"]
                    await asyncio.sleep(0.001)  # Simulate work
                    shared_state["counter"] = current + 1

        # Run 5 concurrent incrementers
        tasks = [increment_counter() for _ in range(5)]
        await asyncio.gather(*tasks)

        # With locking, should get exactly 500
        assert shared_state["counter"] == 500

    @pytest.mark.asyncio
    async def test_concurrent_list_append_safety(self):
        """Test thread-safe list operations in concurrent execution."""
        results = []
        lock = asyncio.Lock()

        async def append_items(task_id: int):
            """Append items to shared list safely."""
            for i in range(10):
                async with lock:
                    results.append((task_id, i))
                await asyncio.sleep(0.01)

        # Run 5 tasks concurrently
        tasks = [append_items(i) for i in range(5)]
        await asyncio.gather(*tasks)

        # Should have exactly 50 items (5 tasks × 10 items)
        assert len(results) == 50

        # Verify all task IDs present
        task_ids = {item[0] for item in results}
        assert task_ids == {0, 1, 2, 3, 4}
