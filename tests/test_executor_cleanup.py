"""
Tests for ToolExecutor thread pool cleanup.

Tests cover:
- Explicit shutdown
- Context manager cleanup
- Garbage collection cleanup
- Weakref finalizer cleanup
- Duplicate shutdown protection
- Thread leak prevention
"""
import gc
import threading
import time
import pytest
from unittest.mock import Mock, MagicMock

from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry
from src.tools.base import BaseTool, ToolResult, ToolMetadata


class DummyTool(BaseTool):
    """Dummy tool for testing."""

    def __init__(self, name="dummy"):
        self._name = name  # Set before super().__init__()
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self._name,
            description="Test tool",
            version="1.0",
            category="test",
            requires_network=False,
            requires_credentials=False
        )

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result="test result")


class TestExplicitShutdown:
    """Tests for explicit shutdown."""

    def test_shutdown_closes_executor(self):
        """Test that shutdown() properly closes the thread pool."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry, max_workers=2)

        # Executor should be active
        assert not executor.is_shutdown()

        # Shutdown
        executor.shutdown(wait=True)

        # Executor should be shutdown
        assert executor.is_shutdown()

    def test_shutdown_waits_for_pending_tasks(self):
        """Test that shutdown waits for pending tasks when wait=True."""
        registry = ToolRegistry(auto_discover=False)

        # Create a slow tool
        slow_tool = DummyTool(name="slow")
        original_execute = slow_tool.execute

        def slow_execute(**kwargs):
            time.sleep(0.5)
            return original_execute(**kwargs)

        slow_tool.execute = slow_execute
        registry.register(slow_tool)

        executor = ToolExecutor(registry, max_workers=1)

        # Submit a task
        import concurrent.futures
        future = executor._executor.submit(slow_tool.execute)

        # Shutdown with wait=True
        start = time.time()
        executor.shutdown(wait=True)
        duration = time.time() - start

        # Should have waited for the task
        assert duration >= 0.5

        # Task should have completed
        assert future.done()

    def test_shutdown_can_cancel_futures(self):
        """Test that shutdown can cancel pending futures."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry, max_workers=1)

        # Submit multiple tasks
        futures = []
        for i in range(10):
            future = executor._executor.submit(time.sleep, 1)
            futures.append(future)

        # Shutdown with cancel_futures=True (don't wait)
        executor.shutdown(wait=False, cancel_futures=True)

        # Some futures should be cancelled
        # (At least those that haven't started yet)
        time.sleep(0.1)
        cancelled_count = sum(1 for f in futures if f.cancelled())
        assert cancelled_count > 0

    def test_duplicate_shutdown_ignored(self):
        """Test that duplicate shutdown calls are ignored."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry)

        executor.shutdown()
        assert executor.is_shutdown()

        # Second shutdown should not raise
        executor.shutdown()
        assert executor.is_shutdown()


class TestContextManager:
    """Tests for context manager pattern."""

    def test_context_manager_cleanup(self):
        """Test that context manager ensures cleanup."""
        registry = ToolRegistry(auto_discover=False)

        with ToolExecutor(registry, max_workers=2) as executor:
            assert not executor.is_shutdown()
            # Do work...

        # After exiting context, should be shut down
        assert executor.is_shutdown()

    def test_context_manager_cleanup_on_exception(self):
        """Test that cleanup happens even if exception is raised."""
        registry = ToolRegistry(auto_discover=False)

        try:
            with ToolExecutor(registry, max_workers=2) as executor:
                assert not executor.is_shutdown()
                raise ValueError("Test error")
        except ValueError:
            pass

        # Should still be shut down
        assert executor.is_shutdown()


class TestGarbageCollection:
    """Tests for cleanup via garbage collection."""

    def test_del_cleanup(self):
        """Test that __del__ attempts cleanup."""
        registry = ToolRegistry(auto_discover=False)

        executor = ToolExecutor(registry, max_workers=2)
        assert not executor.is_shutdown()

        # Delete reference and force GC
        del executor
        gc.collect()

        # Thread pool should be cleaned up
        # (We can't easily verify this directly, but at least no exception)

    def test_weakref_finalizer_cleanup(self):
        """Test that weakref.finalize() ensures cleanup."""
        registry = ToolRegistry(auto_discover=False)

        # Get initial thread count
        initial_threads = threading.active_count()

        def create_and_abandon_executor():
            executor = ToolExecutor(registry, max_workers=4)
            # Don't call shutdown - just let it go out of scope
            return executor._finalizer

        # Create executor and let it go out of scope
        finalizer = create_and_abandon_executor()

        # Force garbage collection
        gc.collect()

        # Give finalizer time to run
        time.sleep(0.1)

        # Finalizer should have been called (it's now dead)
        # When a finalizer runs, it becomes "dead"
        assert not finalizer.alive  # Finalizer has been executed

        # Thread count should return to normal (or close to it)
        # Note: This is a bit flaky as thread cleanup is asynchronous
        final_threads = threading.active_count()
        assert final_threads <= initial_threads + 2  # Allow small variation


class TestThreadLeakPrevention:
    """Tests to ensure no thread leaks."""

    def test_no_thread_leak_with_context_manager(self):
        """Test that using context manager doesn't leak threads."""
        registry = ToolRegistry(auto_discover=False)

        initial_threads = threading.active_count()

        # Create and destroy multiple executors
        for _ in range(5):
            with ToolExecutor(registry, max_workers=4):
                pass

        # Give threads time to shut down
        time.sleep(0.2)

        # Thread count should be back to initial (or close)
        final_threads = threading.active_count()
        assert final_threads <= initial_threads + 2

    def test_no_thread_leak_with_explicit_shutdown(self):
        """Test that explicit shutdown doesn't leak threads."""
        registry = ToolRegistry(auto_discover=False)

        initial_threads = threading.active_count()

        # Create and shutdown multiple executors
        for _ in range(5):
            executor = ToolExecutor(registry, max_workers=4)
            executor.shutdown(wait=True)

        # Give threads time to shut down
        time.sleep(0.2)

        # Thread count should be back to initial
        final_threads = threading.active_count()
        assert final_threads <= initial_threads + 2

    def test_no_thread_leak_without_shutdown(self):
        """Test that finalizer prevents thread leak even without explicit shutdown."""
        registry = ToolRegistry(auto_discover=False)

        initial_threads = threading.active_count()

        # Create executors without shutting down
        for _ in range(3):
            executor = ToolExecutor(registry, max_workers=3)
            # Don't call shutdown - let finalizer handle it

        # Force garbage collection
        gc.collect()

        # Give finalizers time to run
        time.sleep(0.3)

        # Thread count should be back to normal
        final_threads = threading.active_count()
        # Allow more variation since cleanup is asynchronous
        assert final_threads <= initial_threads + 5


class TestExecutorState:
    """Tests for executor state tracking."""

    def test_is_shutdown_reflects_state(self):
        """Test that is_shutdown() accurately reflects executor state."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry)

        assert not executor.is_shutdown()

        executor.shutdown()

        assert executor.is_shutdown()

    def test_repr_shows_status(self):
        """Test that __repr__ includes shutdown status."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry, default_timeout=30)

        # Active state
        repr_active = repr(executor)
        assert "active" in repr_active
        assert "30s" in repr_active

        # Shutdown state
        executor.shutdown()
        repr_shutdown = repr(executor)
        assert "shutdown" in repr_shutdown


class TestConcurrentExecution:
    """Tests for concurrent tool execution with cleanup."""

    def test_execute_tool_with_cleanup(self):
        """Test that tool execution works and cleanup happens."""
        registry = ToolRegistry(auto_discover=False)
        tool = DummyTool()
        registry.register(tool)

        with ToolExecutor(registry, max_workers=2) as executor:
            result = executor.execute("dummy", {})
            assert result.success
            assert result.result == "test result"

        # Executor should be cleaned up
        assert executor.is_shutdown()

    def test_multiple_executions_with_cleanup(self):
        """Test that multiple executions work and cleanup happens."""
        registry = ToolRegistry(auto_discover=False)
        tool = DummyTool()
        registry.register(tool)

        with ToolExecutor(registry, max_workers=3, default_timeout=5) as executor:
            # Execute multiple times
            results = []
            for _ in range(5):
                result = executor.execute("dummy", {})
                results.append(result)

            assert len(results) == 5
            assert all(r.success for r in results)

        # Executor should be cleaned up
        assert executor.is_shutdown()


class TestErrors:
    """Tests for error scenarios during cleanup."""

    def test_shutdown_exception_propagated(self):
        """Test that exceptions during shutdown are propagated."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry)

        # Mock the executor to raise an exception
        original_shutdown = executor._executor.shutdown

        def failing_shutdown(*args, **kwargs):
            raise RuntimeError("Shutdown failed")

        executor._executor.shutdown = failing_shutdown

        # Shutdown should raise
        with pytest.raises(RuntimeError, match="Shutdown failed"):
            executor.shutdown()

    def test_del_handles_exceptions_gracefully(self):
        """Test that __del__ handles exceptions without crashing."""
        registry = ToolRegistry(auto_discover=False)
        executor = ToolExecutor(registry)

        # Mock shutdown to raise
        def failing_shutdown(*args, **kwargs):
            raise RuntimeError("Shutdown failed")

        executor.shutdown = failing_shutdown

        # __del__ should not propagate the exception
        try:
            executor.__del__()
            # If we get here, __del__ handled the exception
        except RuntimeError:
            pytest.fail("__del__ should not propagate exceptions")
