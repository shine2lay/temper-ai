"""
Race condition and concurrency security tests.

Tests for race conditions in shared state, concurrent workflow execution,
and multi-agent data integrity.
"""

import asyncio
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


class TestRaceConditions:
    """Test race conditions in multi-agent execution."""

    @pytest.mark.asyncio
    async def test_shared_state_race_condition_unprotected(self):
        """
        Test concurrent modifications to shared workflow state WITHOUT locking.

        This test demonstrates the race condition by showing that concurrent
        modifications without locks lead to incorrect results.
        """
        state = {"counter": 0}

        async def increment_unsafe():
            """Increment counter without locking (race condition)."""
            for _ in range(100):
                current = state["counter"]
                await asyncio.sleep(0.001)  # Yield to other tasks
                state["counter"] = current + 1

        # Run 10 concurrent incrementers (should reach 1000 total)
        tasks = [increment_unsafe() for _ in range(10)]
        await asyncio.gather(*tasks)

        # Without locking, counter will be < 1000 (race condition)
        # This is the EXPECTED FAILURE demonstrating the problem
        assert (
            state["counter"] < 1000
        ), f"Race condition should occur! Got {state['counter']}, expected <1000"

    @pytest.mark.asyncio
    async def test_shared_state_race_condition_protected(self):
        """
        Test concurrent modifications to shared workflow state WITH locking.

        This test shows that proper locking prevents race conditions.
        """
        state = {"counter": 0}
        lock = asyncio.Lock()

        async def increment_safe():
            """Increment counter with locking (no race condition)."""
            for _ in range(100):
                async with lock:
                    current = state["counter"]
                    await asyncio.sleep(0.001)  # Yield while holding lock
                    state["counter"] = current + 1

        # Run 10 concurrent incrementers (should reach 1000 total)
        tasks = [increment_safe() for _ in range(10)]
        await asyncio.gather(*tasks)

        # With locking, counter should be exactly 1000
        assert (
            state["counter"] == 1000
        ), f"Locking should prevent race condition! Got {state['counter']}"

    @pytest.mark.asyncio
    async def test_agent_deadlock_detection(self):
        """
        Test deadlock detection in multi-agent workflows.

        Two agents try to acquire locks in opposite order, causing deadlock.
        System should timeout rather than hang forever.
        """
        lock_a = asyncio.Lock()
        lock_b = asyncio.Lock()

        async def agent_1():
            """Agent 1 acquires lock_a then lock_b."""
            async with lock_a:
                await asyncio.sleep(0.1)
                # Try to acquire lock_b (agent_2 holds it)
                async with lock_b:
                    pass

        async def agent_2():
            """Agent 2 acquires lock_b then lock_a (opposite order)."""
            async with lock_b:
                await asyncio.sleep(0.1)
                # Try to acquire lock_a (agent_1 holds it)
                async with lock_a:
                    pass

        # Should timeout rather than deadlock forever
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(agent_1(), agent_2()), timeout=2.0)

    @pytest.mark.asyncio
    async def test_file_write_race_condition(self):
        """
        Test concurrent file writes for race conditions.

        Multiple agents writing to the same file concurrently can lead to
        data corruption without proper locking.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "shared.txt"

            async def write_lines_unsafe(agent_id: int):
                """Write lines without file locking."""
                for i in range(10):
                    # Read, modify, write pattern (race condition)
                    try:
                        content = file_path.read_text() if file_path.exists() else ""
                    except FileNotFoundError:
                        content = ""

                    await asyncio.sleep(0.001)  # Simulate work
                    content += f"Agent {agent_id}, Line {i}\n"

                    file_path.write_text(content)

            # Run 5 agents writing concurrently
            tasks = [write_lines_unsafe(i) for i in range(5)]
            await asyncio.gather(*tasks)

            # Count total lines written
            content = file_path.read_text()
            lines = [line for line in content.split("\n") if line.strip()]

            # Should have 50 lines (5 agents × 10 lines), but likely less due to race
            # This demonstrates the problem - lines are lost
            assert (
                len(lines) < 50
            ), f"Race condition should cause lost writes! Got {len(lines)} lines, expected <50"

    @pytest.mark.asyncio
    async def test_counter_increment_with_threading_lock(self):
        """
        Test that threading.Lock prevents race conditions in thread pool.

        This uses threading primitives instead of asyncio for thread-based concurrency.
        """
        state = {"counter": 0}
        lock = threading.Lock()

        def increment_threadsafe():
            """Increment counter with threading lock."""
            for _ in range(100):
                with lock:
                    current = state["counter"]
                    time.sleep(0.0001)  # Small delay to encourage race
                    state["counter"] = current + 1

        # Run 10 threads incrementing concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(increment_threadsafe) for _ in range(10)]
            for future in futures:
                future.result()

        # With threading lock, should be exactly 1000
        assert (
            state["counter"] == 1000
        ), f"Threading lock should prevent race! Got {state['counter']}"


class TestAsyncExceptionSafety:
    """Test async exception propagation and cleanup."""

    @pytest.mark.asyncio
    async def test_async_exception_propagation_and_cleanup(self):
        """
        Test that exceptions in async tasks propagate correctly and cleanup happens.

        Verifies that:
        1. Exceptions in child tasks propagate to parent
        2. Resources are cleaned up even when exceptions occur
        3. No resources are leaked
        """
        cleanup_called = {"count": 0}

        async def failing_task(task_id: int):
            """Task that raises an exception after some work."""
            try:
                await asyncio.sleep(0.01)
                if task_id % 2 == 0:
                    raise ValueError(f"Task {task_id} failed")
            finally:
                # Cleanup should always run
                cleanup_called["count"] += 1

        # Run 10 tasks, half will fail
        tasks = [failing_task(i) for i in range(10)]

        # Gather with return_exceptions=True to capture all exceptions
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify that 5 tasks failed (even IDs)
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 5, f"Expected 5 exceptions, got {len(exceptions)}"

        # Verify all 10 cleanup calls happened
        assert (
            cleanup_called["count"] == 10
        ), f"Cleanup should run for all tasks! Got {cleanup_called['count']}"

    @pytest.mark.asyncio
    async def test_async_resource_cleanup_on_cancellation(self):
        """
        Test that resources are cleaned up when async tasks are cancelled.
        """
        cleanup_called = {"count": 0}

        async def long_running_task():
            """Task that can be cancelled."""
            try:
                await asyncio.sleep(10)  # Long sleep
            except asyncio.CancelledError:
                # Cleanup on cancellation
                cleanup_called["count"] += 1
                raise

        # Start task
        task = asyncio.create_task(long_running_task())

        # Let it start
        await asyncio.sleep(0.01)

        # Cancel it
        task.cancel()

        # Wait for cancellation to complete
        with pytest.raises(asyncio.CancelledError):
            await task

        # Verify cleanup happened
        assert cleanup_called["count"] == 1, "Cleanup should run on cancellation"

    @pytest.mark.asyncio
    async def test_async_context_manager_cleanup(self):
        """
        Test that async context managers clean up correctly on exceptions.
        """
        enter_count = {"count": 0}
        exit_count = {"count": 0}

        class AsyncResource:
            """Async context manager that tracks enter/exit."""

            async def __aenter__(self):
                enter_count["count"] += 1
                await asyncio.sleep(0.001)
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                exit_count["count"] += 1
                await asyncio.sleep(0.001)
                return False  # Don't suppress exceptions

        async def use_resource_and_fail():
            """Use resource then raise exception."""
            async with AsyncResource():
                raise ValueError("Something went wrong")

        # Should raise exception
        with pytest.raises(ValueError):
            await use_resource_and_fail()

        # Verify cleanup happened
        assert enter_count["count"] == 1, "__aenter__ should be called once"
        assert exit_count["count"] == 1, "__aexit__ should be called even on exception"


class TestMemoryLeaks:
    """Test memory leaks in async execution."""

    @pytest.mark.asyncio
    async def test_no_memory_leak_in_workflow_execution(self):
        """
        Test that executing 1000+ workflows doesn't leak memory.

        This simulates high-load scenario with many concurrent workflows.
        """
        import gc

        # Simple workflow task
        async def mini_workflow(workflow_id: int):
            """Minimal workflow that creates some state and completes."""
            state = {"id": workflow_id, "data": list(range(100))}
            await asyncio.sleep(0.001)
            return state

        # Force garbage collection and measure baseline
        gc.collect()
        baseline_objects = len(gc.get_objects())

        # Run 1000 workflows
        batch_size = 100
        for batch_start in range(0, 1000, batch_size):
            tasks = [
                mini_workflow(i) for i in range(batch_start, batch_start + batch_size)
            ]
            await asyncio.gather(*tasks)

            # Periodic garbage collection
            if batch_start % 200 == 0:
                gc.collect()

        # Final garbage collection
        gc.collect()
        final_objects = len(gc.get_objects())

        # Object count should not grow significantly
        # Allow 10% growth for interpreter overhead
        max_allowed = baseline_objects * 1.1

        assert (
            final_objects < max_allowed
        ), f"Memory leak detected! Objects grew from {baseline_objects} to {final_objects}"

    @pytest.mark.asyncio
    async def test_no_task_leak_in_concurrent_execution(self):
        """
        Test that tasks are properly cleaned up after completion.

        Verifies that completed tasks don't accumulate in memory.
        """
        initial_tasks = len(asyncio.all_tasks())

        # Create and complete many tasks
        for _ in range(100):
            task = asyncio.create_task(asyncio.sleep(0.001))
            await task

        final_tasks = len(asyncio.all_tasks())

        # Should not accumulate tasks (allow current test task)
        assert (
            final_tasks <= initial_tasks + 1
        ), f"Task leak detected! Tasks grew from {initial_tasks} to {final_tasks}"

    @pytest.mark.asyncio
    async def test_no_lock_leak_in_concurrent_access(self):
        """
        Test that locks are released even when exceptions occur.

        Verifies that lock leaks don't prevent future access.
        """
        lock = asyncio.Lock()
        access_count = {"count": 0}

        async def access_with_exception():
            """Acquire lock then raise exception."""
            async with lock:
                access_count["count"] += 1
                raise ValueError("Intentional error")

        # First access should fail but release lock
        with pytest.raises(ValueError):
            await access_with_exception()

        # Second access should succeed (lock was released)
        with pytest.raises(ValueError):
            await access_with_exception()

        # Verify both accessed (lock wasn't leaked)
        assert (
            access_count["count"] == 2
        ), f"Lock leak prevented second access! Only {access_count['count']} accesses"


class TestDataIntegrity:
    """Test data integrity under concurrent access."""

    @pytest.mark.asyncio
    async def test_list_append_race_condition(self):
        """
        Test concurrent list appends for race conditions.

        Lists in Python are thread-safe for append(), but not for
        read-modify-write operations.
        """
        shared_list = []

        async def append_items(start: int):
            """Append 100 items to shared list."""
            for i in range(100):
                shared_list.append(start + i)
                await asyncio.sleep(0.0001)

        # Run 10 concurrent appenders
        tasks = [append_items(i * 100) for i in range(10)]
        await asyncio.gather(*tasks)

        # Should have 1000 items (append is thread-safe)
        assert len(shared_list) == 1000, f"Expected 1000 items, got {len(shared_list)}"

        # All items should be unique
        assert len(set(shared_list)) == 1000, "Duplicate items detected!"

    @pytest.mark.asyncio
    async def test_dict_update_race_condition(self):
        """
        Test concurrent dict updates for race conditions.

        Dict operations are NOT thread-safe for read-modify-write.
        """
        shared_dict = {}
        lock = asyncio.Lock()

        async def update_dict_safe(key: str, value: int):
            """Update dict with locking."""
            async with lock:
                current = shared_dict.get(key, 0)
                await asyncio.sleep(0.001)
                shared_dict[key] = current + value

        # 10 tasks each incrementing "counter" by 10
        tasks = [update_dict_safe("counter", 10) for _ in range(10)]
        await asyncio.gather(*tasks)

        # With locking, should be exactly 100
        assert (
            shared_dict["counter"] == 100
        ), f"Expected 100, got {shared_dict['counter']}"
