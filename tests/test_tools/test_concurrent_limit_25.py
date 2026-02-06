"""Tests for code-high-concurrent-limit-25.

Verifies that _acquire_concurrent_slot() atomically checks and increments
the concurrent count, preventing TOCTOU race conditions.
"""

import threading
import time

import pytest

from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.executor import ToolExecutor
from src.tools.registry import ToolRegistry


class SlowTestTool(BaseTool):
    """Tool that takes configurable time to execute."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="slow_test_tool",
            description="Slow tool for concurrency testing",
            version="1.0",
            category="test",
        )

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "delay": {"type": "number", "default": 0.2}
            },
        }

    def execute(self, **kwargs) -> ToolResult:
        delay = kwargs.get("delay", 0.2)
        time.sleep(delay)
        return ToolResult(success=True, result="done")


class TestAtomicConcurrentSlot:
    """Verify _acquire_concurrent_slot is atomic."""

    def _make_executor(self, max_concurrent=3):
        registry = ToolRegistry()
        registry.register(SlowTestTool())
        return ToolExecutor(registry, max_workers=20, max_concurrent=max_concurrent)

    def test_acquire_and_release_basic(self):
        """Acquire increments, release decrements."""
        executor = self._make_executor(max_concurrent=5)
        try:
            assert executor.get_concurrent_execution_count() == 0
            executor._acquire_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 1
            executor._acquire_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 2
            executor._release_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 1
            executor._release_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 0
        finally:
            executor.shutdown(wait=True)

    def test_acquire_rejects_at_limit(self):
        """Cannot acquire when already at max_concurrent."""
        executor = self._make_executor(max_concurrent=2)
        try:
            executor._acquire_concurrent_slot()
            executor._acquire_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 2

            from src.tools.executor import RateLimitError
            with pytest.raises(RateLimitError, match="Concurrent execution limit"):
                executor._acquire_concurrent_slot()

            # Count should still be 2 (not incremented)
            assert executor.get_concurrent_execution_count() == 2

            executor._release_concurrent_slot()
            executor._release_concurrent_slot()
        finally:
            executor.shutdown(wait=True)

    def test_no_toctou_under_contention(self):
        """Concurrent threads cannot exceed max_concurrent."""
        max_concurrent = 3
        executor = self._make_executor(max_concurrent=max_concurrent)

        peak_concurrent = [0]
        peak_lock = threading.Lock()

        try:
            results = []
            barrier = threading.Barrier(20)

            def worker():
                barrier.wait()
                result = executor.execute("slow_test_tool", {"delay": 0.3})
                results.append(result)

            threads = [threading.Thread(target=worker) for _ in range(20)]
            for t in threads:
                t.start()

            # Sample the concurrent count multiple times
            for _ in range(30):
                time.sleep(0.02)
                count = executor.get_concurrent_execution_count()
                with peak_lock:
                    peak_concurrent[0] = max(peak_concurrent[0], count)

            for t in threads:
                t.join(timeout=10)

            # Peak should never exceed the limit
            assert peak_concurrent[0] <= max_concurrent, (
                f"Peak concurrent {peak_concurrent[0]} exceeded limit {max_concurrent}"
            )

            # Some should have been rejected
            rejected = [r for r in results if not r.success and "concurrent" in (r.error or "").lower()]
            succeeded = [r for r in results if r.success]
            assert len(succeeded) > 0
        finally:
            executor.shutdown(wait=True)

    def test_max_concurrent_one_sequential(self):
        """max_concurrent=1 enforces strictly sequential execution."""
        executor = self._make_executor(max_concurrent=1)
        peak_concurrent = [0]
        peak_lock = threading.Lock()

        try:
            results = []

            def worker():
                result = executor.execute("slow_test_tool", {"delay": 0.1})
                results.append(result)

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()

            # Sample concurrent count
            for _ in range(20):
                time.sleep(0.02)
                count = executor.get_concurrent_execution_count()
                with peak_lock:
                    peak_concurrent[0] = max(peak_concurrent[0], count)

            for t in threads:
                t.join(timeout=10)

            assert peak_concurrent[0] <= 1
        finally:
            executor.shutdown(wait=True)

    def test_slot_released_after_completion(self):
        """After tool execution completes, slot is released."""
        executor = self._make_executor(max_concurrent=1)
        try:
            # Execute one tool (should succeed and release slot)
            result = executor.execute("slow_test_tool", {"delay": 0.05})
            assert result.success

            # Should be able to execute again (slot was released)
            result2 = executor.execute("slow_test_tool", {"delay": 0.05})
            assert result2.success

            assert executor.get_concurrent_execution_count() == 0
        finally:
            executor.shutdown(wait=True)

    def test_slot_released_on_error(self):
        """Slot is released even when tool execution fails."""
        registry = ToolRegistry()

        class FailingTool(BaseTool):
            def get_metadata(self):
                return ToolMetadata(
                    name="failing_tool", description="Fails", version="1.0", category="test"
                )
            def get_parameters_schema(self):
                return {"type": "object", "properties": {}}
            def execute(self, **kwargs):
                raise RuntimeError("intentional failure")

        registry.register(FailingTool())
        executor = ToolExecutor(registry, max_concurrent=2)
        try:
            result = executor.execute("failing_tool")
            # Tool should have failed but slot should be released
            assert executor.get_concurrent_execution_count() == 0
        finally:
            executor.shutdown(wait=True)

    def test_no_limit_still_tracks_count(self):
        """Without max_concurrent, count is still tracked for observability."""
        registry = ToolRegistry()
        registry.register(SlowTestTool())
        executor = ToolExecutor(registry, max_workers=4, max_concurrent=None)
        try:
            assert executor.get_concurrent_execution_count() == 0

            executor._acquire_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 1

            executor._release_concurrent_slot()
            assert executor.get_concurrent_execution_count() == 0
        finally:
            executor.shutdown(wait=True)
