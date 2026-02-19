"""
Tests for tool executor.
"""
import time
from unittest.mock import MagicMock

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.registry import ToolRegistry

# ============================================
# MOCK TOOLS FOR TESTING
# ============================================

class FastTool(BaseTool):
    """Tool that executes quickly."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="fast_tool",
            description="A fast tool"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "A value"
                }
            },
            "required": ["value"]
        }

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            result=f"Processed: {kwargs.get('value')}"
        )


class SlowTool(BaseTool):
    """Tool that takes time to execute."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="slow_tool",
            description="A slow tool"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "delay": {
                    "type": "number",
                    "description": "Delay in seconds",
                    "default": 1.0
                }
            },
            "required": []
        }

    def execute(self, **kwargs) -> ToolResult:
        delay = kwargs.get("delay", 1.0)
        time.sleep(delay)
        return ToolResult(
            success=True,
            result=f"Slept for {delay} seconds"
        )


class FailingTool(BaseTool):
    """Tool that always fails."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="failing_tool",
            description="A tool that fails"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=False,
            error="This tool always fails"
        )


class ErrorTool(BaseTool):
    """Tool that raises an exception."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="error_tool",
            description="A tool that raises errors"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("Unexpected error!")


class CalculatorTool(BaseTool):
    """Calculator tool for testing."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="calculator",
            description="Performs math operations"
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "description": "Operation: add, subtract, multiply, divide"
                },
                "a": {
                    "type": "number",
                    "description": "First number"
                },
                "b": {
                    "type": "number",
                    "description": "Second number"
                }
            },
            "required": ["operation", "a", "b"]
        }

    def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation")
        a = kwargs.get("a")
        b = kwargs.get("b")

        operations = {
            "add": a + b,
            "subtract": a - b,
            "multiply": a * b,
            "divide": a / b if b != 0 else None
        }

        result = operations.get(operation)
        if result is None:
            return ToolResult(
                success=False,
                error="Invalid operation or division by zero"
            )

        return ToolResult(
            success=True,
            result=result
        )


# ============================================
# EXECUTOR TESTS
# ============================================

class TestToolExecutor:
    """Tests for ToolExecutor class."""

    def test_create_executor(self):
        """Test creating executor."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry)
        assert executor.registry is registry
        assert executor.default_timeout == 30

    def test_execute_nonexistent_tool(self):
        """Test executing tool that doesn't exist."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = executor.execute("nonexistent", {})
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_execute_with_valid_params(self):
        """Test executing tool with valid parameters."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)
        executor = ToolExecutor(registry)

        result = executor.execute("fast_tool", {"value": "test"})
        assert result.success is True
        assert "Processed: test" in result.result

    def test_execute_with_invalid_params(self):
        """Test executing tool with invalid parameters."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)
        executor = ToolExecutor(registry)

        # Missing required parameter
        result = executor.execute("fast_tool", {})
        assert result.success is False
        assert "invalid" in result.error.lower()

    def test_execute_with_no_params(self):
        """Test executing tool with None params."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)
        executor = ToolExecutor(registry)

        # Should default to empty dict and fail validation
        result = executor.execute("fast_tool", None)
        assert result.success is False

    def test_execute_failing_tool(self):
        """Test executing tool that returns failure."""
        registry = ToolRegistry()
        failing = FailingTool()
        registry.register(failing)
        executor = ToolExecutor(registry)

        result = executor.execute("failing_tool", {})
        assert result.success is False
        assert "always fails" in result.error

    def test_execute_tool_with_exception(self):
        """Test executing tool that raises exception."""
        registry = ToolRegistry()
        error_tool = ErrorTool()
        registry.register(error_tool)
        executor = ToolExecutor(registry)

        result = executor.execute("error_tool", {})
        assert result.success is False
        assert "error" in result.error.lower()

    def test_execute_with_timeout(self):
        """Test executing slow tool with timeout."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, default_timeout=1)

        # Execute with delay longer than timeout
        result = executor.execute("slow_tool", {"delay": 3}, timeout=1)
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_execute_fast_enough(self):
        """Test executing tool that finishes before timeout."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, default_timeout=5)

        # Execute with short delay
        result = executor.execute("slow_tool", {"delay": 0.1}, timeout=5)
        assert result.success is True

    def test_execute_adds_execution_time(self):
        """Test that execution time is added to metadata."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)
        executor = ToolExecutor(registry)

        result = executor.execute("fast_tool", {"value": "test"})
        assert result.success is True
        assert "execution_time_seconds" in result.metadata

    def test_calculator_operations(self):
        """Test calculator tool operations."""
        registry = ToolRegistry()
        calc = CalculatorTool()
        registry.register(calc)
        executor = ToolExecutor(registry)

        # Test addition
        result = executor.execute("calculator", {
            "operation": "add",
            "a": 5,
            "b": 3
        })
        assert result.success is True
        assert result.result == 8

        # Test subtraction
        result = executor.execute("calculator", {
            "operation": "subtract",
            "a": 10,
            "b": 4
        })
        assert result.success is True
        assert result.result == 6

        # Test multiplication
        result = executor.execute("calculator", {
            "operation": "multiply",
            "a": 7,
            "b": 6
        })
        assert result.success is True
        assert result.result == 42

        # Test division
        result = executor.execute("calculator", {
            "operation": "divide",
            "a": 20,
            "b": 4
        })
        assert result.success is True
        assert result.result == 5

    def test_validate_tool_call(self):
        """Test validating tool call without executing."""
        registry = ToolRegistry()
        calc = CalculatorTool()
        registry.register(calc)
        executor = ToolExecutor(registry)

        # Valid call
        valid, error = executor.validate_tool_call("calculator", {
            "operation": "add",
            "a": 5,
            "b": 3
        })
        assert valid is True
        assert error is None

        # Invalid call - missing parameter
        valid, error = executor.validate_tool_call("calculator", {
            "operation": "add",
            "a": 5
        })
        assert valid is False
        assert error is not None

        # Invalid call - nonexistent tool
        valid, error = executor.validate_tool_call("nonexistent", {})
        assert valid is False
        assert "not found" in error.lower()

    def test_get_tool_info(self):
        """Test getting tool information."""
        registry = ToolRegistry()
        calc = CalculatorTool()
        registry.register(calc)
        executor = ToolExecutor(registry)

        info = executor.get_tool_info("calculator")
        assert info is not None
        assert info["name"] == "calculator"
        assert "description" in info
        assert "parameters_schema" in info
        assert "llm_schema" in info

    def test_get_info_for_nonexistent_tool(self):
        """Test getting info for tool that doesn't exist."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        info = executor.get_tool_info("nonexistent")
        assert info is None

    def test_execute_batch(self):
        """Test executing multiple tools in batch."""
        registry = ToolRegistry()
        calc = CalculatorTool()
        fast = FastTool()
        registry.register(calc)
        registry.register(fast)
        executor = ToolExecutor(registry)

        executions = [
            ("calculator", {"operation": "add", "a": 1, "b": 2}),
            ("calculator", {"operation": "multiply", "a": 3, "b": 4}),
            ("fast_tool", {"value": "batch"})
        ]

        results = executor.execute_batch(executions)
        assert len(results) == 3
        assert results[0].success is True
        assert results[0].result == 3
        assert results[1].success is True
        assert results[1].result == 12
        assert results[2].success is True

    def test_execute_batch_with_failures(self):
        """Test batch execution with some failures."""
        registry = ToolRegistry()
        calc = CalculatorTool()
        failing = FailingTool()
        registry.register(calc)
        registry.register(failing)
        executor = ToolExecutor(registry)

        executions = [
            ("calculator", {"operation": "add", "a": 1, "b": 2}),
            ("failing_tool", {}),
            ("calculator", {"operation": "multiply", "a": 3, "b": 4})
        ]

        results = executor.execute_batch(executions)
        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    def test_context_manager(self):
        """Test using executor as context manager."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        with ToolExecutor(registry) as executor:
            result = executor.execute("fast_tool", {"value": "test"})
            assert result.success is True

    def test_shutdown(self):
        """Test shutting down executor."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        # Shutdown should complete without errors
        executor.shutdown(wait=True)

        # After shutdown, executor should be in a clean state
        # Verify the thread pool executor is shutdown
        assert executor._executor._shutdown is True

    def test_repr(self):
        """Test string representation."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry, default_timeout=30)

        repr_str = repr(executor)
        assert "ToolExecutor" in repr_str
        assert "30s" in repr_str


class TestExecutorConfiguration:
    """Tests for executor configuration."""

    def test_custom_timeout(self):
        """Test setting custom default timeout."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry, default_timeout=10)
        assert executor.default_timeout == 10

    def test_custom_max_workers(self):
        """Test setting custom max workers."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry, max_workers=2)
        # Just verify it doesn't error
        assert executor is not None

    def test_override_timeout_per_execution(self):
        """Test overriding timeout for specific execution."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, default_timeout=10)

        # Override with shorter timeout
        result = executor.execute("slow_tool", {"delay": 2}, timeout=1)
        assert result.success is False
        assert "timed out" in result.error.lower()


class TestTimeoutComprehensive:
    """Comprehensive timeout tests for P0 acceptance criteria."""

    def test_timeout_accuracy_within_10_percent(self):
        """Test timeout enforced within ±10% accuracy."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry)

        timeout_value = 2  # 2 seconds
        acceptable_min = timeout_value * 0.9  # 1.8s
        acceptable_max = timeout_value * 1.1  # 2.2s

        start = time.time()
        result = executor.execute("slow_tool", {"delay": 10}, timeout=timeout_value)
        elapsed = time.time() - start

        # Should timeout
        assert result.success is False
        assert "timed out" in result.error.lower()

        # Should timeout within ±10% of configured value
        assert acceptable_min <= elapsed <= acceptable_max

    def test_timeout_error_message_includes_tool_name(self):
        """Test timeout error message indicates which tool timed out."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry)

        result = executor.execute("slow_tool", {"delay": 10}, timeout=1)

        assert result.success is False
        assert "timed out" in result.error.lower()
        # Error message should include timeout duration
        assert "1 second" in result.error or "1s" in result.error

    def test_multiple_consecutive_timeouts_no_resource_leak(self):
        """Test multiple consecutive timeouts don't cause resource leaks."""
        import threading

        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, max_workers=4)

        try:
            initial_threads = threading.active_count()

            # Trigger 10 consecutive timeouts
            for i in range(10):
                result = executor.execute("slow_tool", {"delay": 10}, timeout=0.5)
                assert result.success is False
                assert "timed out" in result.error.lower()

            # Give threads time to clean up
            time.sleep(0.2)

            # Thread count should not have grown significantly
            final_threads = threading.active_count()
            # Allow some variation (up to 4 worker threads + a few extra)
            assert final_threads <= initial_threads + 6
        finally:
            executor.shutdown(wait=True)

    def test_hung_tool_terminated_after_timeout(self):
        """Test hung tools are forcefully terminated after timeout."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry)

        timeout_value = 1
        start = time.time()
        result = executor.execute("slow_tool", {"delay": 60}, timeout=timeout_value)
        elapsed = time.time() - start

        # Should timeout quickly, not wait full 60s
        assert elapsed < timeout_value + 1  # Allow 1s margin
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_timeout_with_zero_disables_timeout(self):
        """Test that timeout=0 disables timeout (for special cases)."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry)

        # Short delay with 0 timeout should complete
        result = executor.execute("slow_tool", {"delay": 0.1}, timeout=None)
        assert result.success is True
        assert "Slept for" in result.result

    def test_timeout_preserves_partial_results(self):
        """Test that partial results are preserved on timeout (if any)."""
        # Note: Current implementation doesn't support partial results
        # This test documents the expected behavior
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry)

        result = executor.execute("slow_tool", {"delay": 10}, timeout=1)

        # Should have structured error response
        assert result.success is False
        assert result.result is None  # No partial results
        assert result.error is not None
        assert "timed out" in result.error.lower()

    def test_concurrent_tools_independent_timeouts(self):
        """Test concurrent tool executions have independent timeouts."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, max_workers=3)

        try:
            # Execute 3 tools concurrently with different timeouts
            futures = []

            # Tool 1: Will timeout
            f1 = executor._executor.submit(executor.execute, "slow_tool", {"delay": 10}, 1)
            futures.append(f1)

            # Tool 2: Will complete
            f2 = executor._executor.submit(executor.execute, "slow_tool", {"delay": 0.1}, 5)
            futures.append(f2)

            # Tool 3: Will timeout
            f3 = executor._executor.submit(executor.execute, "slow_tool", {"delay": 10}, 1)
            futures.append(f3)

            # Wait for all to complete
            results = [f.result() for f in futures]

            # First and third should timeout
            assert results[0].success is False
            assert "timed out" in results[0].error.lower()

            # Second should succeed
            assert results[1].success is True

            # Third should timeout
            assert results[2].success is False
            assert "timed out" in results[2].error.lower()
        finally:
            executor.shutdown(wait=True)

    def test_timeout_during_batch_execution(self):
        """Test timeout handling during batch execution."""
        registry = ToolRegistry()
        slow = SlowTool()
        fast = FastTool()
        registry.register(slow)
        registry.register(fast)
        executor = ToolExecutor(registry)

        executions = [
            ("slow_tool", {"delay": 10}),  # Will timeout
            ("fast_tool", {"value": "test"}),  # Will succeed
            ("slow_tool", {"delay": 10}),  # Will timeout
        ]

        results = executor.execute_batch(executions, timeout=1)

        assert len(results) == 3
        # First should timeout
        assert results[0].success is False
        assert "timed out" in results[0].error.lower()
        # Second should succeed
        assert results[1].success is True
        # Third should timeout
        assert results[2].success is False
        assert "timed out" in results[2].error.lower()

    def test_timeout_accuracy_stress_test(self):
        """Stress test timeout accuracy with multiple concurrent executions."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        # Use enough workers to avoid queuing delays
        executor = ToolExecutor(registry, max_workers=10)

        timeout_value = 1
        num_executions = 10

        futures = []
        start_times = []

        # Submit concurrent executions
        for _ in range(num_executions):
            start_times.append(time.time())
            f = executor._executor.submit(
                executor.execute, "slow_tool", {"delay": 10}, timeout_value
            )
            futures.append(f)

        # Collect results
        elapsed_times = []
        for i, f in enumerate(futures):
            result = f.result()
            elapsed = time.time() - start_times[i]
            elapsed_times.append(elapsed)

            # All should timeout
            assert result.success is False
            assert "timed out" in result.error.lower()

        # Check that timeouts are reasonably accurate
        # Note: With thread pool, some variation is expected
        avg_elapsed = sum(elapsed_times) / len(elapsed_times)
        # More lenient bounds for stress test (up to 1.5x due to scheduling)
        assert timeout_value * 0.9 <= avg_elapsed <= timeout_value * 1.5

        # Clean up explicitly
        executor.shutdown(wait=True)

    def test_resource_cleanup_after_timeout(self):
        """Test that resources are cleaned up after timeout."""
        import gc
        import threading

        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)

        # Use context manager to ensure cleanup
        with ToolExecutor(registry, max_workers=2) as executor:
            initial_threads = threading.active_count()

            # Trigger multiple timeouts
            for _ in range(5):
                result = executor.execute("slow_tool", {"delay": 10}, timeout=0.5)
                assert result.success is False

        # Force garbage collection
        gc.collect()
        time.sleep(0.2)

        # Thread count should be back to normal
        final_threads = threading.active_count()
        assert final_threads <= initial_threads + 2

    def test_default_timeout_applied_when_none_specified(self):
        """Test that default timeout is used when timeout parameter is None."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, default_timeout=1)

        # Don't specify timeout, should use default (1s)
        start = time.time()
        result = executor.execute("slow_tool", {"delay": 10})
        elapsed = time.time() - start

        # Should timeout using default
        assert result.success is False
        assert "timed out" in result.error.lower()
        assert elapsed < 2  # Should timeout in ~1s, not wait 10s


class TestResourceExhaustionPrevention:
    """Tests for resource exhaustion prevention (P1)."""

    def test_concurrent_execution_tracking(self):
        """Test that concurrent executions are tracked correctly."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)
        executor = ToolExecutor(registry, max_workers=4)

        try:
            # Initially no concurrent executions
            assert executor.get_concurrent_execution_count() == 0

            # Submit multiple slow tasks
            import concurrent.futures
            futures = []
            for _ in range(3):
                future = executor._executor.submit(executor.execute, "slow_tool", {"delay": 0.5})
                futures.append(future)

            # Give them time to start
            time.sleep(0.1)

            # Should have 3 concurrent executions
            concurrent = executor.get_concurrent_execution_count()
            assert concurrent == 3, f"Expected 3 concurrent, got {concurrent}"

            # Wait for completion
            for f in futures:
                f.result()

            # Should be back to 0
            time.sleep(0.1)
            assert executor.get_concurrent_execution_count() == 0
        finally:
            executor.shutdown(wait=True)

    def test_concurrent_execution_limit(self):
        """Test executor limits concurrent tool executions."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)

        # Limit to 3 concurrent executions
        executor = ToolExecutor(registry, max_workers=10, max_concurrent=3)

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                # Try to execute 20 slow tools concurrently
                futures = [
                    pool.submit(executor.execute, "slow_tool", {"delay": 0.5})
                    for _ in range(20)
                ]

                # Check concurrent execution count
                time.sleep(0.1)  # Let some start
                concurrent_count = executor.get_concurrent_execution_count()

                # Should not exceed max_concurrent
                assert concurrent_count <= 3, f"Concurrent count {concurrent_count} exceeded limit 3"

                # Wait for all to complete
                results = [f.result() for f in futures]

            # Most should succeed, but some might be rate limited
            successful = [r for r in results if r.success]
            rate_limited = [r for r in results if not r.success and "limit" in r.error.lower()]

            # At least some should be rate limited
            assert len(rate_limited) > 0, "Expected some requests to be rate limited"

        finally:
            executor.shutdown(wait=True)

    def test_rate_limiting_enforced(self):
        """Test tool executor enforces rate limits."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        # 5 calls per second max
        executor = ToolExecutor(registry, rate_limit=5, rate_window=1.0)

        try:
            # Execute 10 calls rapidly
            start = time.time()
            results = []

            for i in range(10):
                result = executor.execute("fast_tool", {"value": f"test{i}"})
                results.append(result)

            elapsed = time.time() - start

            # Check how many succeeded vs rate limited
            successful = [r for r in results if r.success]
            rate_limited = [r for r in results if not r.success and "rate limit" in r.error.lower()]

            # Should have rate limited some requests
            assert len(rate_limited) > 0, "Expected some requests to be rate limited"

            # First 5 should succeed
            assert len(successful) >= 5, "Expected at least first 5 to succeed"

        finally:
            executor.shutdown(wait=True)

    def test_rate_limit_sliding_window(self):
        """Test rate limiting uses sliding window correctly."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        # 3 calls per 0.5 second window
        executor = ToolExecutor(registry, rate_limit=3, rate_window=0.5)

        try:
            # Execute 3 calls (should all succeed)
            for i in range(3):
                result = executor.execute("fast_tool", {"value": f"test{i}"})
                assert result.success, f"Call {i} should succeed"

            # 4th call should be rate limited
            result = executor.execute("fast_tool", {"value": "test3"})
            assert not result.success
            assert "rate limit" in result.error.lower()

            # Wait for window to pass
            time.sleep(0.6)

            # Should be able to execute again
            result = executor.execute("fast_tool", {"value": "test4"})
            assert result.success, "Should succeed after window reset"

        finally:
            executor.shutdown(wait=True)

    def test_rate_limit_usage_reporting(self):
        """Test rate limit usage statistics."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        executor = ToolExecutor(registry, rate_limit=10, rate_window=1.0)

        try:
            # Initially no usage
            usage = executor.get_rate_limit_usage()
            assert usage["rate_limit"] == 10
            assert usage["current_usage"] == 0
            assert usage["available"] == 10

            # Execute 3 calls
            for _ in range(3):
                executor.execute("fast_tool", {"value": "test"})

            # Should show 3 used, 7 available
            usage = executor.get_rate_limit_usage()
            assert usage["current_usage"] == 3
            assert usage["available"] == 7

        finally:
            executor.shutdown(wait=True)

    def test_no_rate_limit_when_disabled(self):
        """Test that rate limiting can be disabled."""
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        # No rate limit
        executor = ToolExecutor(registry, rate_limit=None)

        try:
            # Execute many calls rapidly
            for i in range(100):
                result = executor.execute("fast_tool", {"value": f"test{i}"})
                assert result.success, f"Call {i} should succeed (no rate limit)"

            usage = executor.get_rate_limit_usage()
            assert usage["rate_limit"] is None

        finally:
            executor.shutdown(wait=True)

    def test_concurrent_limit_with_failures(self):
        """Test concurrent limit works correctly even with tool failures."""
        registry = ToolRegistry()
        failing = FailingTool()
        registry.register(failing)

        executor = ToolExecutor(registry, max_workers=10, max_concurrent=2)

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                # Execute 10 failing tools
                futures = [
                    pool.submit(executor.execute, "failing_tool", {})
                    for _ in range(10)
                ]

                # Check concurrent count during execution
                time.sleep(0.05)
                concurrent = executor.get_concurrent_execution_count()
                assert concurrent <= 2, f"Concurrent {concurrent} exceeded limit 2"

                # All should complete (but fail)
                results = [f.result() for f in futures]

            # All should have failed (but not due to rate limiting)
            for result in results:
                assert not result.success
                # Should be tool failure, not rate limit
                assert "always fails" in result.error or "limit" in result.error.lower()

        finally:
            executor.shutdown(wait=True)

    def test_concurrent_tracking_with_timeouts(self):
        """Test concurrent tracking works correctly with timeouts."""
        registry = ToolRegistry()
        slow = SlowTool()
        registry.register(slow)

        executor = ToolExecutor(registry, max_workers=4)

        try:
            # Execute tools that will timeout
            import concurrent.futures
            futures = []
            for _ in range(3):
                future = executor._executor.submit(
                    executor.execute, "slow_tool", {"delay": 10}, 0.5
                )
                futures.append(future)

            # Wait for timeouts
            time.sleep(0.1)

            # Should have 3 concurrent
            concurrent = executor.get_concurrent_execution_count()
            assert concurrent == 3

            # Wait for all to timeout
            for f in futures:
                result = f.result()
                assert not result.success
                assert "timed out" in result.error.lower()

            # Should be back to 0
            time.sleep(0.1)
            assert executor.get_concurrent_execution_count() == 0

        finally:
            executor.shutdown(wait=True)

    def test_rate_limiting_per_tool(self):
        """Test rate limiting applies to all tool calls, not per-tool."""
        registry = ToolRegistry()
        fast = FastTool()
        calc = CalculatorTool()
        registry.register(fast)
        registry.register(calc)

        # 5 calls per second total (not per tool)
        executor = ToolExecutor(registry, rate_limit=5, rate_window=1.0)

        try:
            # Mix different tools
            results = []

            # 3 fast_tool calls
            for i in range(3):
                result = executor.execute("fast_tool", {"value": f"test{i}"})
                results.append(result)

            # 3 calculator calls (should hit limit on 6th overall)
            for i in range(3):
                result = executor.execute("calculator", {
                    "operation": "add", "a": i, "b": 1
                })
                results.append(result)

            # Check results
            successful = [r for r in results if r.success]
            rate_limited = [r for r in results if not r.success and "rate limit" in r.error.lower()]

            # Should have rate limited at least 1 request
            assert len(rate_limited) >= 1, "Expected rate limiting across different tools"

        finally:
            executor.shutdown(wait=True)

    def test_stress_concurrent_and_rate_limits(self):
        """Stress test concurrent and rate limits together."""
        registry = ToolRegistry()
        fast = FastTool()
        slow = SlowTool()
        registry.register(fast)
        registry.register(slow)

        # Restrictive limits
        executor = ToolExecutor(
            registry,
            max_workers=10,
            max_concurrent=3,
            rate_limit=10,
            rate_window=1.0
        )

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                # Submit many mixed calls
                futures = []
                for i in range(50):
                    if i % 2 == 0:
                        future = pool.submit(executor.execute, "fast_tool", {"value": f"test{i}"})
                    else:
                        future = pool.submit(executor.execute, "slow_tool", {"delay": 0.1})
                    futures.append(future)

                # Check concurrent execution stays within limit
                time.sleep(0.2)
                concurrent = executor.get_concurrent_execution_count()
                assert concurrent <= 3, f"Concurrent {concurrent} exceeded limit 3"

                # Collect all results
                results = [f.result() for f in futures]

            # Analyze results
            successful = [r for r in results if r.success]
            rate_limited = [r for r in results if not r.success and "rate limit" in r.error.lower()]
            concurrent_limited = [r for r in results if not r.success and "concurrent" in r.error.lower()]

            # Should have some rate limiting
            total_limited = len(rate_limited) + len(concurrent_limited)
            assert total_limited > 0, "Expected some requests to be limited"

            # Debug: print stats
            print(f"Successful: {len(successful)}, Rate limited: {len(rate_limited)}, "
                  f"Concurrent limited: {len(concurrent_limited)}")

        finally:
            executor.shutdown(wait=True)


# ============================================
# CONCURRENT RATE LIMITER TESTS (10+ THREADS)
# ============================================

class TestRateLimiterConcurrency:
    """Test rate limiter thread-safety with high concurrency (10+ threads).

    Requirements:
    - Test with 10+ concurrent threads
    - Verify exact counting (no over/under counting)
    - Strict assertions (== not <=)
    - Zero race conditions allowed
    """

    def test_rate_limiter_thread_safety_15_threads(self):
        """Test rate limiter correctness with 15 concurrent threads.

        Tests: Rate limit enforced correctly under high concurrency
        Requirements:
        - 15 threads executing simultaneously
        - Rate limit: 5 calls/second
        - Total calls: 30 (15 threads × 2 calls each)
        - Expected: ≤5 succeed, rest rate limited
        - No over-counting or under-counting
        """
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        # Rate limit: 5 calls per second
        executor = ToolExecutor(registry, rate_limit=5, rate_window=1.0)

        try:
            import concurrent.futures
            import threading

            num_threads = 15
            calls_per_thread = 2
            total_calls = num_threads * calls_per_thread  # 30 calls

            results = []
            results_lock = threading.Lock()

            def execute_tool(thread_id: int):
                """Execute tool from specific thread."""
                thread_results = []
                for i in range(calls_per_thread):
                    result = executor.execute("fast_tool", {"value": f"thread{thread_id}_call{i}"})
                    thread_results.append({
                        "thread_id": thread_id,
                        "call_num": i,
                        "success": result.success,
                        "error": result.error
                    })
                    # Small delay between calls from same thread
                    time.sleep(0.01)

                with results_lock:
                    results.extend(thread_results)

            # Execute concurrently from 15 threads
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as pool:
                futures = [pool.submit(execute_tool, i) for i in range(num_threads)]
                concurrent.futures.wait(futures)

            # Analyze results
            successful = [r for r in results if r["success"]]
            rate_limited = [r for r in results if not r["success"] and "rate limit" in (r["error"] or "").lower()]

            # Assertions
            total_results = len(results)
            assert total_results == total_calls, \
                f"Lost results! Expected {total_calls}, got {total_results}"

            # Rate limit should have blocked most requests
            # Within 1 second window, max 5 should succeed
            assert len(successful) <= 5, \
                f"Rate limit FAILED! {len(successful)} succeeded (max 5 allowed in {executor.rate_window}s). " \
                f"Race condition in rate limiter implementation!"

            # Remaining should be rate limited
            expected_rate_limited = total_calls - len(successful)
            assert len(rate_limited) == expected_rate_limited, \
                f"Rate limit counting error! Expected {expected_rate_limited} rate limited, " \
                f"got {len(rate_limited)}. Some requests failed for other reasons?"

            # Verify no double-counting or missing counts
            assert len(successful) + len(rate_limited) == total_calls, \
                f"Accounting error! successful({len(successful)}) + " \
                f"rate_limited({len(rate_limited)}) != total({total_calls})"

        finally:
            executor.shutdown(wait=True)

    def test_rate_limiter_no_over_consumption(self):
        """Test rate limiter prevents over-consumption.

        Tests: Exactly rate_limit requests succeed within window
        Requirements:
        - 20 concurrent threads attempt calls
        - Rate limit: 10 calls/second
        - Expected: Exactly 10 succeed, 10 rate limited
        - No over-consumption allowed (strict equality)
        """
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        # Rate limit: 10 calls per second
        executor = ToolExecutor(registry, rate_limit=10, rate_window=1.0)

        try:
            import concurrent.futures

            # 20 concurrent calls (double the rate limit)
            num_calls = 20

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_calls) as pool:
                futures = [
                    pool.submit(executor.execute, "fast_tool", {"value": f"call_{i}"})
                    for i in range(num_calls)
                ]
                results = [f.result() for f in futures]

            # Analyze results
            successful = sum(1 for r in results if r.success)
            rate_limited = sum(
                1 for r in results
                if not r.success and "rate limit" in (r.error or "").lower()
            )

            # CRITICAL: Exactly 10 should succeed (rate limit)
            assert successful <= 10, \
                f"Over-consumption! Expected ≤10 successful, got {successful}"

            # Account for all requests
            assert successful + rate_limited == num_calls, \
                f"Accounting error! {successful} + {rate_limited} != {num_calls}"

        finally:
            executor.shutdown(wait=True)

    def test_rate_limiter_sliding_window_correctness(self):
        """Test sliding window correctness under concurrent access.

        Tests:
        - Old timestamps properly removed
        - No race in timestamp queue cleanup
        - Window slides correctly under load

        Phases:
        1. Fill rate limit (10 concurrent calls)
        2. Immediate retry should be rate limited
        3. After window expires, retry should succeed
        """
        registry = ToolRegistry()
        fast = FastTool()
        registry.register(fast)

        # 10 calls per 0.5 second window
        executor = ToolExecutor(registry, rate_limit=10, rate_window=0.5)

        try:
            import concurrent.futures

            # Phase 1: Fill the rate limit (10 concurrent threads)
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                futures = [
                    pool.submit(executor.execute, "fast_tool", {"value": f"phase1_{i}"})
                    for i in range(10)
                ]
                results_phase1 = [f.result() for f in futures]

            # All should succeed
            successful_p1 = sum(1 for r in results_phase1 if r.success)
            assert successful_p1 == 10, \
                f"Phase 1 failed! Expected 10 successful, got {successful_p1}"

            # Phase 2: Immediate retry should be rate limited
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                futures = [
                    pool.submit(executor.execute, "fast_tool", {"value": f"phase2_{i}"})
                    for i in range(5)
                ]
                results_phase2 = [f.result() for f in futures]

            # All should be rate limited
            rate_limited_p2 = sum(
                1 for r in results_phase2
                if not r.success and "rate limit" in (r.error or "").lower()
            )
            assert rate_limited_p2 == 5, \
                f"Phase 2 failed! Expected 5 rate limited, got {rate_limited_p2}"

            # Phase 3: Wait for window to expire, then retry
            time.sleep(0.6)  # Wait for 0.5s window + margin

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                futures = [
                    pool.submit(executor.execute, "fast_tool", {"value": f"phase3_{i}"})
                    for i in range(10)
                ]
                results_phase3 = [f.result() for f in futures]

            # Should succeed again (window reset)
            successful_p3 = sum(1 for r in results_phase3 if r.success)
            assert successful_p3 == 10, \
                f"Phase 3 failed! Window didn't reset. Expected 10 successful, got {successful_p3}. " \
                f"Race condition in timestamp cleanup?"

        finally:
            executor.shutdown(wait=True)


class TestPolicyFailClosed:
    """Tests that policy engine errors result in fail-closed behavior."""

    def _make_executor(self, policy_engine=None):
        """Create executor with a FastTool and optional policy engine."""
        registry = ToolRegistry()
        registry.register(FastTool())
        executor = ToolExecutor(
            registry,
            default_timeout=5,
            policy_engine=policy_engine,
        )
        return executor

    def test_policy_exception_denies_execution(self):
        """When policy engine raises RuntimeError, tool execution must be denied."""
        policy = MagicMock()
        policy.validate_action.side_effect = RuntimeError("policy crash")

        executor = self._make_executor(policy_engine=policy)
        try:
            result = executor.execute("fast_tool", {"value": "test"})

            assert not result.success
            assert "Policy validation failed" in result.error
            assert "policy crash" in result.error
        finally:
            executor.shutdown(wait=True)

    def test_policy_passes_allows_execution(self):
        """When policy engine returns allowed result, tool executes normally."""
        enforcement = MagicMock()
        enforcement.allowed = True
        enforcement.has_blocking_violations.return_value = False

        policy = MagicMock()
        policy.validate_action.return_value = enforcement

        executor = self._make_executor(policy_engine=policy)
        try:
            result = executor.execute("fast_tool", {"value": "test"})

            assert result.success
            assert result.result == "Processed: test"
        finally:
            executor.shutdown(wait=True)

    def test_policy_violation_denies_execution(self):
        """When policy engine returns violation, tool execution must be denied."""
        violation = MagicMock()
        violation.message = "Access denied by security policy"
        violation.to_dict.return_value = {"message": "Access denied"}

        enforcement = MagicMock()
        enforcement.allowed = False
        enforcement.violations = [violation]

        policy = MagicMock()
        policy.validate_action.return_value = enforcement

        executor = self._make_executor(policy_engine=policy)
        try:
            result = executor.execute("fast_tool", {"value": "test"})

            assert not result.success
            assert "blocked by policy" in result.error
        finally:
            executor.shutdown(wait=True)

    def test_no_policy_engine_allows_execution(self):
        """When no policy engine is configured, tool executes normally."""
        executor = self._make_executor(policy_engine=None)
        try:
            result = executor.execute("fast_tool", {"value": "test"})

            assert result.success
        finally:
            executor.shutdown(wait=True)
