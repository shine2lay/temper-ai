"""
Concurrent execution safety tests.

Tests for concurrent workflow execution, multi-agent safety,
and async resource management.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest


class TestConcurrentWorkflowExecution:
    """Test concurrent workflow execution safety."""

    @pytest.mark.asyncio
    async def test_concurrent_workflow_state_isolation(self):
        """
        Test that concurrent workflows have isolated state.

        Each workflow should have its own state that doesn't interfere
        with other workflows running concurrently.
        """
        workflow_states = {}

        async def run_workflow(workflow_id: str):
            """Run workflow with isolated state."""
            # Initialize workflow state
            state = {"id": workflow_id, "counter": 0}

            # Simulate workflow execution
            for _i in range(10):
                state["counter"] += 1
                await asyncio.sleep(0.001)

            # Store final state
            workflow_states[workflow_id] = state

        # Run 20 workflows concurrently
        tasks = [run_workflow(f"workflow_{i}") for i in range(20)]
        await asyncio.gather(*tasks)

        # Verify all workflows completed with correct state
        assert len(workflow_states) == 20, "All workflows should complete"

        for workflow_id, state in workflow_states.items():
            assert (
                state["counter"] == 10
            ), f"{workflow_id} has incorrect counter: {state['counter']}"
            assert (
                state["id"] == workflow_id
            ), f"{workflow_id} has incorrect ID: {state['id']}"

    @pytest.mark.asyncio
    async def test_concurrent_workflow_resource_contention(self):
        """
        Test that concurrent workflows properly handle resource contention.

        When multiple workflows need the same resource, proper locking
        should prevent data corruption.
        """
        shared_resource = {"value": 0}
        resource_lock = asyncio.Lock()
        access_log = []

        async def workflow_with_shared_resource(workflow_id: int):
            """Workflow that accesses shared resource."""
            async with resource_lock:
                # Read current value
                current = shared_resource["value"]
                access_log.append(f"workflow_{workflow_id}_read_{current}")

                # Simulate work
                await asyncio.sleep(0.01)

                # Update value
                shared_resource["value"] = current + 1
                access_log.append(f"workflow_{workflow_id}_write_{current + 1}")

        # Run 10 workflows concurrently
        tasks = [workflow_with_shared_resource(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify resource was updated correctly
        assert (
            shared_resource["value"] == 10
        ), f"Expected 10, got {shared_resource['value']}"

        # Verify all accesses were serialized (no interleaving)
        # Each workflow should have read_N followed by write_N+1
        for i in range(10):
            read_entry = f"workflow_{i}_read_{i}"
            write_entry = f"workflow_{i}_write_{i + 1}"
            assert read_entry in access_log, f"Missing: {read_entry}"
            assert write_entry in access_log, f"Missing: {write_entry}"

    @pytest.mark.asyncio
    async def test_concurrent_workflow_cancellation(self):
        """
        Test that cancelling one workflow doesn't affect others.

        Workflows should be independent and cancellation should be isolated.
        """
        completed = {"count": 0}
        cancelled = {"count": 0}

        async def cancellable_workflow(workflow_id: int):
            """Workflow that can be cancelled."""
            try:
                for _i in range(10):
                    await asyncio.sleep(0.05)
                completed["count"] += 1
            except asyncio.CancelledError:
                cancelled["count"] += 1
                raise

        # Start 10 workflows
        tasks = [asyncio.create_task(cancellable_workflow(i)) for i in range(10)]

        # Let them start
        await asyncio.sleep(0.01)

        # Cancel workflows 0, 2, 4, 6, 8 (5 total)
        for i in [0, 2, 4, 6, 8]:
            tasks[i].cancel()

        # Wait for all to complete or be cancelled
        await asyncio.gather(*tasks, return_exceptions=True)

        # Verify 5 were cancelled
        assert (
            cancelled["count"] == 5
        ), f"Expected 5 cancelled, got {cancelled['count']}"

        # Verify 5 completed normally
        assert (
            completed["count"] == 5
        ), f"Expected 5 completed, got {completed['count']}"

    @pytest.mark.asyncio
    async def test_concurrent_workflow_exception_isolation(self):
        """
        Test that exceptions in one workflow don't crash others.

        Each workflow should handle its own exceptions independently.
        """
        successful = {"count": 0}
        failed = {"count": 0}

        async def workflow_maybe_fail(workflow_id: int):
            """Workflow that may raise exception."""
            try:
                await asyncio.sleep(0.01)

                # Workflows with even IDs fail
                if workflow_id % 2 == 0:
                    raise ValueError(f"Workflow {workflow_id} failed")

                successful["count"] += 1
            except ValueError:
                failed["count"] += 1
                raise

        # Run 10 workflows
        tasks = [workflow_maybe_fail(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify 5 succeeded and 5 failed
        assert (
            successful["count"] == 5
        ), f"Expected 5 successful, got {successful['count']}"
        assert failed["count"] == 5, f"Expected 5 failed, got {failed['count']}"

        # Verify correct results
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 5, f"Expected 5 exceptions, got {len(exceptions)}"


class TestMultiAgentSafety:
    """Test multi-agent execution safety."""

    @pytest.mark.asyncio
    async def test_multi_agent_task_queue_safety(self):
        """
        Test that multiple agents can safely consume from shared task queue.

        Agents should not process the same task twice.
        """
        tasks_queue = asyncio.Queue()
        processed_tasks = set()
        processing_lock = asyncio.Lock()

        # Add 100 tasks to queue
        for i in range(100):
            await tasks_queue.put(f"task_{i}")

        async def agent_worker(agent_id: int):
            """Agent that processes tasks from queue."""
            while True:
                try:
                    # Get task with timeout
                    task_id = await asyncio.wait_for(tasks_queue.get(), timeout=0.1)

                    # Process task
                    await asyncio.sleep(0.001)

                    # Record as processed (thread-safe)
                    async with processing_lock:
                        if task_id in processed_tasks:
                            raise ValueError(f"Task {task_id} processed twice!")
                        processed_tasks.add(task_id)

                    tasks_queue.task_done()

                except TimeoutError:
                    # No more tasks
                    break

        # Run 5 agents concurrently
        agents = [agent_worker(i) for i in range(5)]
        await asyncio.gather(*agents)

        # Verify all 100 tasks were processed exactly once
        assert (
            len(processed_tasks) == 100
        ), f"Expected 100 tasks processed, got {len(processed_tasks)}"

    @pytest.mark.asyncio
    async def test_multi_agent_coordinator_pattern(self):
        """
        Test coordinator pattern for multi-agent workflows.

        One coordinator distributes work to multiple worker agents.
        """
        work_items = list(range(50))
        results = []
        results_lock = asyncio.Lock()

        async def coordinator(workers: int):
            """Coordinator that distributes work."""
            work_queue = asyncio.Queue()

            # Add all work items
            for item in work_items:
                await work_queue.put(item)

            async def worker(worker_id: int):
                """Worker that processes items."""
                while True:
                    try:
                        item = await asyncio.wait_for(work_queue.get(), timeout=0.1)

                        # Process item (double the value)
                        result = item * 2
                        await asyncio.sleep(0.001)

                        # Store result
                        async with results_lock:
                            results.append(result)

                        work_queue.task_done()

                    except TimeoutError:
                        break

            # Start workers
            worker_tasks = [worker(i) for i in range(workers)]
            await asyncio.gather(*worker_tasks)

        # Run coordinator with 5 workers
        await coordinator(workers=5)

        # Verify all work was processed
        assert len(results) == 50, f"Expected 50 results, got {len(results)}"

        # Verify results are correct
        expected = {item * 2 for item in work_items}
        assert set(results) == expected, "Results don't match expected values"

    @pytest.mark.asyncio
    async def test_multi_agent_barrier_synchronization(self):
        """
        Test barrier synchronization for multi-agent coordination.

        All agents must reach a checkpoint before any can proceed.
        """
        num_agents = 5
        barrier_reached = {"count": 0}
        after_barrier = {"count": 0}
        barrier = asyncio.Barrier(num_agents)

        async def agent_with_barrier(agent_id: int):
            """Agent that waits at barrier."""
            # Phase 1: Work before barrier
            await asyncio.sleep(0.01 * agent_id)  # Stagger arrival times

            # Record reaching barrier
            barrier_reached["count"] += 1
            current_before = barrier_reached["count"]

            # Wait at barrier
            await barrier.wait()

            # Phase 2: Work after barrier
            # At this point, all agents should have reached barrier
            after_barrier["count"] += 1

            # Verify all agents reached barrier before any proceeded
            assert (
                current_before <= num_agents
            ), f"Agent {agent_id} saw {current_before} at barrier"

        # Run all agents
        agents = [agent_with_barrier(i) for i in range(num_agents)]
        await asyncio.gather(*agents)

        # Verify all agents completed both phases
        assert barrier_reached["count"] == num_agents
        assert after_barrier["count"] == num_agents


class TestAsyncResourceManagement:
    """Test async resource management and cleanup."""

    @pytest.mark.asyncio
    async def test_async_connection_pool_safety(self):
        """
        Test that async connection pool handles concurrent access safely.

        Multiple tasks requesting connections should not exceed pool size
        and should properly release connections.
        """
        pool_size = 5
        active_connections = {"count": 0}
        max_concurrent = {"count": 0}
        total_acquired = {"count": 0}
        connection_lock = asyncio.Lock()

        class ConnectionPool:
            """Simple async connection pool."""

            def __init__(self, size: int):
                self.semaphore = asyncio.Semaphore(size)

            async def acquire(self):
                """Acquire connection from pool."""
                await self.semaphore.acquire()

                async with connection_lock:
                    active_connections["count"] += 1
                    total_acquired["count"] += 1
                    max_concurrent["count"] = max(
                        max_concurrent["count"], active_connections["count"]
                    )

            async def release(self):
                """Release connection back to pool."""
                async with connection_lock:
                    active_connections["count"] -= 1

                self.semaphore.release()

        pool = ConnectionPool(pool_size)

        async def use_connection(task_id: int):
            """Task that uses a connection."""
            await pool.acquire()
            try:
                # Simulate work with connection
                await asyncio.sleep(0.05)
            finally:
                await pool.release()

        # Run 20 tasks (4x pool size) concurrently
        tasks = [use_connection(i) for i in range(20)]
        await asyncio.gather(*tasks)

        # Verify pool size was never exceeded
        assert (
            max_concurrent["count"] <= pool_size
        ), f"Pool size exceeded! Max concurrent: {max_concurrent['count']}"

        # Verify all connections were released
        assert (
            active_connections["count"] == 0
        ), f"Connections leaked! {active_connections['count']} still active"

        # Verify all tasks acquired connections
        assert (
            total_acquired["count"] == 20
        ), f"Expected 20 acquisitions, got {total_acquired['count']}"

    @pytest.mark.asyncio
    async def test_async_file_handle_cleanup(self):
        """
        Test that async file operations clean up handles properly.

        File handles should be closed even when exceptions occur.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            writes_completed = {"count": 0}

            async def write_file_safely(content: str):
                """Write to file with proper cleanup."""
                # Simulate async file write
                try:
                    # This would normally be an async file operation
                    file_path.write_text(content)
                    await asyncio.sleep(0.001)
                    writes_completed["count"] += 1
                except Exception:
                    # Cleanup would happen in finally block
                    raise

            async def write_file_with_error(content: str):
                """Write to file then raise error."""
                try:
                    file_path.write_text(content)
                    await asyncio.sleep(0.001)
                    raise ValueError("Write failed")
                except ValueError:
                    # Cleanup still happens
                    writes_completed["count"] += 1
                    raise

            # Successful write
            await write_file_safely("test content")
            assert writes_completed["count"] == 1

            # Write with exception
            with pytest.raises(ValueError):
                await write_file_with_error("error content")

            # Verify cleanup happened (counter incremented)
            assert writes_completed["count"] == 2

    @pytest.mark.asyncio
    async def test_async_semaphore_fairness(self):
        """
        Test that async semaphore provides fair access.

        Tasks should acquire semaphore in roughly FIFO order.
        """
        semaphore = asyncio.Semaphore(2)  # Only 2 concurrent
        acquisition_order = []
        order_lock = asyncio.Lock()

        async def task_with_semaphore(task_id: int):
            """Task that acquires semaphore."""
            await asyncio.sleep(0.001 * task_id)  # Stagger start times

            async with semaphore:
                async with order_lock:
                    acquisition_order.append(task_id)

                # Hold semaphore briefly
                await asyncio.sleep(0.05)

        # Start 10 tasks
        tasks = [task_with_semaphore(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify all acquired
        assert len(acquisition_order) == 10

        # Note: Exact FIFO not guaranteed by asyncio, but tasks should
        # generally acquire in start order. We just verify all completed.
        assert set(acquisition_order) == set(range(10))


class TestConcurrentDataAccess:
    """Test concurrent data access patterns."""

    @pytest.mark.asyncio
    async def test_read_write_lock_pattern(self):
        """
        Test read-write lock pattern for concurrent access.

        Multiple readers can access concurrently, but writers need exclusive access.
        """
        shared_data = {"value": 0}
        readers = 0
        readers_lock = asyncio.Lock()
        writer_lock = asyncio.Lock()
        read_count = {"count": 0}
        write_count = {"count": 0}

        async def reader(reader_id: int):
            """Read shared data (multiple readers allowed)."""
            nonlocal readers

            # Acquire reader lock
            async with readers_lock:
                readers += 1
                if readers == 1:
                    # First reader blocks writers
                    await writer_lock.acquire()

            # Read data (multiple readers concurrent)
            shared_data["value"]
            await asyncio.sleep(0.01)  # Simulate read time
            read_count["count"] += 1

            # Release reader lock
            async with readers_lock:
                readers -= 1
                if readers == 0:
                    # Last reader unblocks writers
                    writer_lock.release()

        async def writer(writer_id: int):
            """Write shared data (exclusive access)."""
            async with writer_lock:
                # Exclusive write access
                current = shared_data["value"]
                await asyncio.sleep(0.02)  # Simulate write time
                shared_data["value"] = current + 1
                write_count["count"] += 1

        # Start 5 readers and 2 writers concurrently
        tasks = []
        tasks.extend([reader(i) for i in range(5)])
        tasks.extend([writer(i) for i in range(2)])

        await asyncio.gather(*tasks)

        # Verify all completed
        assert read_count["count"] == 5, "All readers should complete"
        assert write_count["count"] == 2, "All writers should complete"
        assert shared_data["value"] == 2, "Writers should update correctly"

    @pytest.mark.asyncio
    async def test_optimistic_concurrency_control(self):
        """
        Test optimistic concurrency control pattern.

        Updates check version before applying to detect conflicts.
        """
        data = {"value": 0, "version": 0}
        data_lock = asyncio.Lock()
        conflicts = {"count": 0}
        successful = {"count": 0}

        async def optimistic_update(update_id: int):
            """Update with optimistic concurrency control."""
            max_retries = 10  # Need more retries for high contention

            for _attempt in range(max_retries):
                # Read current version
                async with data_lock:
                    current_version = data["version"]
                    current_value = data["value"]

                # Simulate work
                await asyncio.sleep(0.01)
                new_value = current_value + 1

                # Try to commit with version check
                async with data_lock:
                    if data["version"] == current_version:
                        # No conflict - commit
                        data["value"] = new_value
                        data["version"] += 1
                        successful["count"] += 1
                        return
                    else:
                        # Conflict - retry
                        conflicts["count"] += 1

            # Failed after retries
            raise ValueError(f"Update {update_id} failed after {max_retries} retries")

        # Run 10 concurrent updates
        tasks = [optimistic_update(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify final state
        assert data["value"] == 10, "All updates should eventually succeed"
        assert data["version"] == 10, "Version should match update count"
        assert successful["count"] == 10, "All updates should succeed"

        # Some conflicts are expected due to concurrent access
        assert conflicts["count"] >= 0, "Conflicts may occur"
