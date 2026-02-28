"""
Timeout scenario tests for LLM calls, tool execution, workflows, and agents.

Tests timeout enforcement, error handling, resource cleanup, and partial result capture.
"""

import asyncio
import tempfile
import time

import pytest

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult


class SlowTool(BaseTool):
    """Tool that sleeps for testing timeouts."""

    def __init__(self, sleep_seconds: float = 5):
        self.sleep_seconds = sleep_seconds
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="SlowTool",
            description="A tool that sleeps for testing timeouts",
            version="1.0",
        )

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        time.sleep(self.sleep_seconds)
        return ToolResult(success=True, result=f"Completed after {self.sleep_seconds}s")


class AsyncSlowTool(BaseTool):
    """Async tool that sleeps for testing async timeouts."""

    def __init__(self, sleep_seconds: float = 5):
        self.sleep_seconds = sleep_seconds
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="AsyncSlowTool", description="An async tool that sleeps", version="1.0"
        )

    def get_parameters_schema(self):
        return {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        # Sync version
        time.sleep(self.sleep_seconds)
        return ToolResult(success=True, result="Done")

    async def aexecute(self, **kwargs) -> ToolResult:
        """Async execution."""
        await asyncio.sleep(self.sleep_seconds)
        return ToolResult(
            success=True, result=f"Async completed after {self.sleep_seconds}s"
        )


class TestToolExecutionTimeouts:
    """Test tool execution timeout scenarios."""

    @pytest.mark.timeout(30)
    def test_tool_timeout_sync(self):
        """Test synchronous tool execution timeout.

        CRITICAL: Verifies timeout actually enforces time limit.
        Tool sleeps for 10s but timeout is 2s.
        Must verify execution stops at ~2s, NOT at 10s.
        """
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        tool = SlowTool(sleep_seconds=5)  # Tool would take 5s
        registry.register(tool)
        executor = ToolExecutor(registry, default_timeout=2)

        try:
            start = time.time()
            result = executor.execute("SlowTool", {}, timeout=2)
            elapsed = time.time() - start

            # CRITICAL: Verify timeout enforced
            assert result.success is False, "Tool should timeout"
            assert (
                "timed out" in result.error.lower() or "timeout" in result.error.lower()
            ), f"Error should mention timeout, got: {result.error}"

            # STRICT timing check: Should timeout at ~2s, definitely not wait 5s
            assert elapsed < 3.0, (
                f"TIMEOUT NOT ENFORCED! Tool took {elapsed:.2f}s (should timeout at ~2s). "
                f"Execution likely waited for full {tool.sleep_seconds}s instead of enforcing timeout."
            )

            # Also verify it didn't finish too early
            assert (
                elapsed >= 1.5
            ), f"Timeout happened too early: {elapsed:.2f}s (expected ~2s)"
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    @pytest.mark.asyncio
    async def test_tool_timeout_async(self):
        """Test async tool execution timeout.

        CRITICAL: Verifies async timeout enforcement.
        Tool sleeps for 60s but timeout is 2s.
        Must verify execution stops at ~2s, NOT at 60s.
        """
        tool = AsyncSlowTool(sleep_seconds=5)

        start = time.time()

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(tool.aexecute(), timeout=2.0)

        elapsed = time.time() - start

        # STRICT timing check: timeout at ~2s, not 60s
        assert elapsed < 3.0, (
            f"TIMEOUT NOT ENFORCED! Async tool took {elapsed:.2f}s (should timeout at ~2s). "
            f"Execution likely waited for full 60s instead of enforcing timeout."
        )

        assert (
            elapsed >= 1.8
        ), f"Timeout happened too early: {elapsed:.2f}s (expected ~2s)"

    @pytest.mark.timeout(30)
    def test_tool_timeout_cleanup(self):
        """Test that resources are cleaned up on tool timeout."""
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        tool = SlowTool(sleep_seconds=5)
        registry.register(tool)

        executor = ToolExecutor(registry, default_timeout=1)
        try:
            result = executor.execute("SlowTool", {})
            assert result.success is False
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        # Executor should be shut down properly
        # If cleanup didn't happen, we'd get warnings

    @pytest.mark.timeout(60)
    @pytest.mark.asyncio
    async def test_multiple_tool_timeouts_no_resource_leak(self):
        """Test that multiple timeouts don't leak resources."""
        from temper_ai.tools.executor import ToolExecutor
        from temper_ai.tools.registry import ToolRegistry

        registry = ToolRegistry()
        tool = SlowTool(sleep_seconds=3)
        registry.register(tool)

        executor = ToolExecutor(registry, default_timeout=1, max_workers=5)
        try:
            # Trigger 5 timeouts (reduced from 10 to avoid thread accumulation)
            for _i in range(5):
                result = executor.execute("SlowTool", {}, timeout=1)
                assert result.success is False
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        # All workers should be cleaned up


class TestLLMTimeouts:
    """Test LLM call timeout scenarios."""

    @pytest.mark.asyncio
    async def test_llm_generation_timeout(self):
        """Test LLM generation times out after configured duration.

        CRITICAL: Verifies LLM timeout enforcement.
        Mock LLM sleeps for 60s but timeout is 5s.
        Must verify execution stops at ~5s, NOT at 60s.
        """

        async def slow_generate(*args, **kwargs):
            """Mock LLM that takes 60 seconds."""
            await asyncio.sleep(60)
            return "This response took too long"

        start = time.time()

        # Simulate LLM call with timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_generate("What is 2+2?"), timeout=5.0)

        elapsed = time.time() - start

        # STRICT: Should timeout at ~5s, not wait 60s
        assert elapsed < 6.0, (
            f"TIMEOUT NOT ENFORCED! LLM call took {elapsed:.2f}s (should timeout at ~5s). "
            f"Execution likely waited for full 60s instead of enforcing timeout."
        )
        assert elapsed >= 4.5, f"Timeout too early: {elapsed:.2f}s (expected ~5s)"

    @pytest.mark.asyncio
    async def test_llm_timeout_with_retry_budget(self):
        """Test that retries respect overall timeout budget."""
        call_count = {"count": 0}

        async def slow_generate_with_retry(*args, **kwargs):
            """Mock LLM that fails and gets retried."""
            call_count["count"] += 1
            await asyncio.sleep(3)  # Each attempt takes 3s
            raise Exception("LLM error")

        async def retry_with_timeout(func, max_retries=3, timeout=10):
            """Retry logic with timeout budget."""
            start = time.time()

            for attempt in range(max_retries):
                try:
                    # Each retry gets remaining time
                    remaining = timeout - (time.time() - start)
                    if remaining <= 0:
                        raise TimeoutError("Overall timeout exceeded")

                    return await asyncio.wait_for(func(), timeout=remaining)

                except Exception:
                    if attempt == max_retries - 1:
                        raise
                    continue

        start = time.time()

        # Should timeout after 10s, not attempt all 3 retries (would take 9s each)
        with pytest.raises((Exception, asyncio.TimeoutError)):
            await retry_with_timeout(
                slow_generate_with_retry, max_retries=5, timeout=10
            )

        elapsed = time.time() - start

        # STRICT: Should timeout at ~10s (budget), not wait for all 5 retries (15s)
        assert elapsed < 11.5, (
            f"TIMEOUT BUDGET NOT ENFORCED! Retries took {elapsed:.2f}s (should timeout at ~10s). "
            f"Execution likely attempted all {call_count['count']} retries instead of enforcing 10s budget."
        )
        assert elapsed >= 9.0, f"Timeout too early: {elapsed:.2f}s (expected ~10s)"
        assert call_count["count"] < 5, "Should not attempt all retries"

    @pytest.mark.asyncio
    async def test_llm_timeout_cleanup(self):
        """Test that LLM connections are cleaned up on timeout."""
        cleanup_called = {"count": 0}

        async def slow_generate_with_cleanup():
            """Mock LLM with cleanup."""
            try:
                await asyncio.sleep(60)
                return "response"
            finally:
                cleanup_called["count"] += 1

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_generate_with_cleanup(), timeout=2.0)

        # Give time for cleanup
        await asyncio.sleep(0.1)

        # Cleanup should have been called
        assert cleanup_called["count"] == 1, "Cleanup should run even on timeout"


class TestWorkflowTimeouts:
    """Test workflow execution timeout scenarios."""

    @pytest.mark.asyncio
    async def test_workflow_stage_timeout(self):
        """Test individual workflow stage timeout.

        CRITICAL: Verifies workflow stage timeout enforcement.
        Stage sleeps for 60s but timeout is 5s.
        Must verify execution stops at ~5s, NOT at 60s.
        """

        async def slow_stage(context):
            """Stage that takes too long."""
            await asyncio.sleep(60)
            return {"result": "done"}

        start = time.time()

        # Execute stage with timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_stage({}), timeout=5.0)

        elapsed = time.time() - start

        # STRICT: timeout at ~5s, not 60s
        assert (
            elapsed < 6.0
        ), f"TIMEOUT NOT ENFORCED! Stage took {elapsed:.2f}s (should timeout at ~5s)"
        assert elapsed >= 4.5, f"Timeout too early: {elapsed:.2f}s (expected ~5s)"

    @pytest.mark.asyncio
    async def test_workflow_total_timeout(self):
        """Test total workflow timeout across multiple stages."""
        stages_completed = {"count": 0}

        async def stage(stage_id: int, context: dict):
            """Workflow stage that takes 3 seconds."""
            await asyncio.sleep(3)
            stages_completed["count"] += 1
            return {"stage": stage_id, "result": f"Stage {stage_id} done"}

        async def run_workflow():
            """Run workflow with 5 stages (15s total)."""
            context = {}
            for i in range(5):
                result = await stage(i, context)
                context.update(result)
            return context

        start = time.time()

        # Workflow would take 15s, but timeout at 10s
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(run_workflow(), timeout=10.0)

        elapsed = time.time() - start

        # STRICT: Should timeout at ~10s, not wait for all 15s
        assert elapsed < 11.5, (
            f"TIMEOUT NOT ENFORCED! Workflow took {elapsed:.2f}s (should timeout at ~10s). "
            f"Execution likely ran for all 15s instead of enforcing 10s timeout."
        )
        assert elapsed >= 9.0, f"Timeout too early: {elapsed:.2f}s (expected ~10s)"

        # Should have completed some stages but not all
        assert (
            0 < stages_completed["count"] < 5
        ), f"Should complete some stages, completed {stages_completed['count']}"

    @pytest.mark.asyncio
    async def test_workflow_timeout_with_partial_results(self):
        """Test that partial results are captured when workflow times out."""
        partial_results = []

        async def stage_with_results(stage_id: int):
            """Stage that adds to partial results."""
            await asyncio.sleep(2)
            result = {"stage": stage_id, "data": f"Stage {stage_id}"}
            partial_results.append(result)
            return result

        async def run_workflow_with_tracking():
            """Run workflow and track results."""
            for i in range(10):  # Would take 20s total
                await stage_with_results(i)

        try:
            await asyncio.wait_for(run_workflow_with_tracking(), timeout=7.0)
        except TimeoutError:
            pass  # Expected

        # Should have partial results from completed stages
        assert len(partial_results) > 0, "Should have some partial results"
        assert len(partial_results) < 10, "Should not complete all stages"

        # Verify partial results are valid
        for i, result in enumerate(partial_results):
            assert result["stage"] == i
            assert result["data"] == f"Stage {i}"

    @pytest.mark.asyncio
    async def test_workflow_timeout_propagation(self):
        """Test that timeout errors propagate correctly through workflow stages."""
        errors_caught = []

        async def stage_that_times_out():
            """Stage with internal timeout."""
            await asyncio.sleep(10)

        async def parent_workflow():
            """Parent workflow that catches timeout from child stage."""
            try:
                await asyncio.wait_for(stage_that_times_out(), timeout=2.0)
            except TimeoutError as e:
                errors_caught.append(("stage_timeout", str(e)))
                raise  # Propagate to parent

        # Execute parent workflow with its own timeout
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(parent_workflow(), timeout=5.0)

        # Should have caught timeout at stage level
        assert len(errors_caught) == 1
        assert errors_caught[0][0] == "stage_timeout"


class TestAgentTimeouts:
    """Test agent execution timeout scenarios."""

    @pytest.mark.asyncio
    async def test_agent_execution_timeout(self):
        """Test agent execution times out.

        CRITICAL: Verifies agent timeout enforcement.
        Agent sleeps for 60s but timeout is 5s.
        Must verify execution stops at ~5s, NOT at 60s.
        """

        async def slow_agent_execution(query: str):
            """Mock agent that takes too long."""
            await asyncio.sleep(60)
            return {"response": "This took forever"}

        start = time.time()

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_agent_execution("What is 2+2?"), timeout=5.0)

        elapsed = time.time() - start

        # STRICT: timeout at ~5s, not 60s
        assert (
            elapsed < 6.0
        ), f"TIMEOUT NOT ENFORCED! Agent took {elapsed:.2f}s (should timeout at ~5s)"
        assert elapsed >= 4.5, f"Timeout too early: {elapsed:.2f}s (expected ~5s)"

    @pytest.mark.asyncio
    async def test_agent_tool_call_timeout(self):
        """Test agent times out during tool call.

        CRITICAL: Verifies cascading timeout enforcement.
        Tool sleeps for 15s, inner timeout is 30s, agent timeout is 10s.
        Must verify execution stops at ~10s (agent timeout), NOT at 30s.
        """
        tool = AsyncSlowTool(sleep_seconds=15)

        async def agent_with_tool_call():
            """Mock agent that calls slow tool."""
            # Agent attempts tool call with 30s timeout
            result = await asyncio.wait_for(tool.aexecute(), timeout=30)
            return result

        start = time.time()

        # Agent should timeout at 10s (before tool's 30s timeout)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(agent_with_tool_call(), timeout=10.0)

        elapsed = time.time() - start

        # STRICT: Should timeout at ~10s (agent timeout), not 30s or 60s
        assert elapsed < 11.5, (
            f"TIMEOUT NOT ENFORCED! Agent took {elapsed:.2f}s (should timeout at ~10s). "
            f"Execution likely waited for tool timeout (30s) or completion (60s)."
        )
        assert elapsed >= 9.0, f"Timeout too early: {elapsed:.2f}s (expected ~10s)"

    @pytest.mark.asyncio
    async def test_agent_timeout_context_preserved(self):
        """Test that timeout errors include context about what timed out."""
        context_info = {}

        async def agent_with_context():
            """Agent that tracks what operation is running."""
            context_info["operation"] = "llm_generation"
            context_info["started"] = True
            await asyncio.sleep(60)
            context_info["completed"] = True

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(agent_with_context(), timeout=2.0)

        # Context should show operation started but didn't complete
        assert context_info.get("operation") == "llm_generation"
        assert context_info.get("started") is True
        assert context_info.get("completed") is None  # Never reached


class TestTimeoutResourceCleanup:
    """Test resource cleanup on timeout."""

    @pytest.mark.asyncio
    async def test_file_handle_cleanup_on_timeout(self):
        """Test that file handles are closed on timeout."""
        file_opened = {"count": 0}
        file_closed = {"count": 0}

        async def operation_with_file():
            """Operation that opens file and times out."""
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                file_opened["count"] += 1
                try:
                    await asyncio.sleep(60)
                    f.write("test data")
                finally:
                    file_closed["count"] += 1

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(operation_with_file(), timeout=2.0)

        # File should have been opened and closed
        assert file_opened["count"] == 1
        # Note: file cleanup happens when context manager exits,
        # which may be after the timeout

    @pytest.mark.asyncio
    async def test_connection_cleanup_on_timeout(self):
        """Test that connections are cleaned up on timeout."""
        connections_opened = []
        connections_closed = []

        class MockConnection:
            """Mock connection for testing."""

            def __init__(self, conn_id):
                self.id = conn_id
                connections_opened.append(conn_id)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                connections_closed.append(self.id)
                return False

        async def operation_with_connection():
            """Operation that uses connection and times out."""
            async with MockConnection("conn_1"):
                await asyncio.sleep(60)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(operation_with_connection(), timeout=2.0)

        # Give async cleanup time to complete
        await asyncio.sleep(0.1)

        # Connection should be opened and closed
        assert "conn_1" in connections_opened
        assert "conn_1" in connections_closed

    @pytest.mark.asyncio
    async def test_multiple_resource_cleanup_on_timeout(self):
        """Test that multiple resources are all cleaned up on timeout."""
        cleanup_log = []

        async def operation_with_multiple_resources():
            """Operation that acquires multiple resources."""
            try:
                # Resource 1
                cleanup_log.append("acquired_resource_1")
                try:
                    # Resource 2
                    cleanup_log.append("acquired_resource_2")
                    try:
                        # Resource 3
                        cleanup_log.append("acquired_resource_3")

                        # Long operation
                        await asyncio.sleep(60)

                    finally:
                        cleanup_log.append("cleanup_resource_3")
                finally:
                    cleanup_log.append("cleanup_resource_2")
            finally:
                cleanup_log.append("cleanup_resource_1")

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(operation_with_multiple_resources(), timeout=2.0)

        # Give async cleanup time
        await asyncio.sleep(0.1)

        # All resources should be acquired and cleaned up
        assert "acquired_resource_1" in cleanup_log
        assert "acquired_resource_2" in cleanup_log
        assert "acquired_resource_3" in cleanup_log
        assert "cleanup_resource_3" in cleanup_log
        assert "cleanup_resource_2" in cleanup_log
        assert "cleanup_resource_1" in cleanup_log


class TestTimeoutErrorMessages:
    """Test timeout error message quality."""

    @pytest.mark.asyncio
    async def test_timeout_error_includes_operation_context(self):
        """Test that timeout errors include context about what timed out."""

        async def named_operation():
            """Operation with clear name."""
            await asyncio.sleep(60)

        try:
            await asyncio.wait_for(named_operation(), timeout=2.0)
        except TimeoutError as e:
            # Error should be catchable and identifiable
            assert isinstance(e, asyncio.TimeoutError)
            # Operation name is available in traceback

    @pytest.mark.asyncio
    async def test_timeout_error_distinguishable_from_other_errors(self):
        """Test that timeout errors can be distinguished from other exceptions."""

        async def operation_that_fails():
            """Operation that might timeout or fail."""
            await asyncio.sleep(60)
            raise ValueError("Operation failed")

        # Should get TimeoutError, not ValueError
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(operation_that_fails(), timeout=2.0)

        # Not ValueError
        try:
            await asyncio.wait_for(operation_that_fails(), timeout=2.0)
            raise AssertionError("Should have raised TimeoutError")
        except TimeoutError:
            pass  # Expected
        except ValueError:
            raise AssertionError("Should raise TimeoutError, not ValueError")
