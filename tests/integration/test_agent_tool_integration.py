"""
Integration tests for agent + tool execution.

Tests end-to-end integration of agents calling tools with real tool implementations.
"""
import time

import pytest

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.calculator import Calculator
from temper_ai.tools.executor import ToolExecutor
from temper_ai.tools.registry import ToolRegistry


class SlowTool(BaseTool):
    """Tool that sleeps for testing timeouts."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="SlowTool",
            description="A tool that sleeps for a specified duration",
            version="1.0"
        )

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "Number of seconds to sleep"
                }
            },
            "required": ["seconds"]
        }

    def execute(self, **kwargs) -> ToolResult:
        seconds = kwargs.get("seconds", 1)
        time.sleep(seconds)
        return ToolResult(
            success=True,
            result=f"Slept for {seconds} seconds"
        )


class FailingTool(BaseTool):
    """Tool that always fails for testing error handling."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="FailingTool",
            description="A tool that always fails",
            version="1.0"
        )

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "error_message": {
                    "type": "string",
                    "description": "Error message to return"
                }
            }
        }

    def execute(self, **kwargs) -> ToolResult:
        error_msg = kwargs.get("error_message", "Tool failed")
        return ToolResult(
            success=False,
            error=error_msg
        )


class LargeOutputTool(BaseTool):
    """Tool that generates large output for testing limits."""

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="LargeOutputTool",
            description="Generates large output",
            version="1.0"
        )

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {
                "size_mb": {
                    "type": "number",
                    "description": "Size of output in MB"
                }
            },
            "required": ["size_mb"]
        }

    def execute(self, **kwargs) -> ToolResult:
        size_mb = kwargs.get("size_mb", 1)
        # Generate size_mb megabytes of data (1MB = 1024 * 1024 bytes)
        size_bytes = int(size_mb * 1024 * 1024)
        large_data = "x" * size_bytes

        return ToolResult(
            success=True,
            result=large_data,
            metadata={"size_bytes": size_bytes}
        )


class TestBasicToolExecution:
    """Test basic tool execution scenarios."""

    def test_calculator_tool_success(self):
        """Test successful calculator tool execution."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Execute calculator with valid expression
        result = executor.execute("Calculator", {"expression": "15 * 23"})

        assert result.success is True, f"Tool should succeed: {result.error}"
        assert result.result == 345, f"Expected 345, got {result.result}"
        assert "execution_time_seconds" in result.metadata

    def test_calculator_tool_with_functions(self):
        """Test calculator with mathematical functions."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Test sqrt
        result = executor.execute("Calculator", {"expression": "sqrt(16)"})
        assert result.success is True
        assert result.result == 4.0

        # Test power
        result = executor.execute("Calculator", {"expression": "2 ** 10"})
        assert result.success is True
        assert result.result == 1024

        # Test trigonometry
        result = executor.execute("Calculator", {"expression": "round(sin(0))"})
        assert result.success is True
        assert result.result == 0

    def test_tool_parameter_validation(self):
        """Test that tool parameter validation works before execution."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Missing required parameter
        result = executor.execute("Calculator", {})
        assert result.success is False
        assert "expression" in result.error.lower() or "required" in result.error.lower()

        # Invalid parameter type
        result = executor.execute("Calculator", {"expression": 123})
        assert result.success is False

    def test_tool_execution_error_handling(self):
        """Test that tool errors are handled gracefully."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Division by zero
        result = executor.execute("Calculator", {"expression": "10 / 0"})
        assert result.success is False
        assert "zero" in result.error.lower()

        # Syntax error
        result = executor.execute("Calculator", {"expression": "2 ++"})
        assert result.success is False
        assert "syntax" in result.error.lower()

        # Unsupported function
        result = executor.execute("Calculator", {"expression": "eval('2+2')"})
        assert result.success is False
        assert "unsupported" in result.error.lower() or "error" in result.error.lower()

    def test_tool_not_found_error(self):
        """Test error when requesting non-existent tool."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry)

        result = executor.execute("NonExistentTool", {})
        assert result.success is False
        assert "not found" in result.error.lower()


class TestToolTimeout:
    """Test tool timeout enforcement."""

    def test_tool_timeout_enforcement(self):
        """Test that tool execution times out after configured limit."""
        registry = ToolRegistry()
        registry.register(SlowTool())
        executor = ToolExecutor(registry, default_timeout=2)

        start = time.time()
        result = executor.execute("SlowTool", {"seconds": 60}, timeout=2)
        elapsed = time.time() - start

        # Should timeout in ~2 seconds, not wait 60 seconds
        assert result.success is False, "Tool should timeout"
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()
        assert elapsed < 5, f"Timeout should be enforced quickly, took {elapsed}s"

    def test_tool_timeout_default(self):
        """Test that default timeout is applied when not specified."""
        registry = ToolRegistry()
        registry.register(SlowTool())
        executor = ToolExecutor(registry, default_timeout=1)

        start = time.time()
        # Don't specify timeout - should use default of 1s
        result = executor.execute("SlowTool", {"seconds": 10})
        elapsed = time.time() - start

        assert result.success is False, "Tool should timeout with default"
        assert elapsed < 3, f"Should timeout in ~1s, took {elapsed}s"

    def test_tool_timeout_override(self):
        """Test that per-call timeout overrides default."""
        registry = ToolRegistry()
        registry.register(SlowTool())
        executor = ToolExecutor(registry, default_timeout=1)

        # Override default 1s timeout with 5s
        result = executor.execute("SlowTool", {"seconds": 2}, timeout=5)

        # Should succeed because 2s < 5s timeout
        assert result.success is True, f"Tool should succeed: {result.error}"
        assert "2 seconds" in result.result


class TestConcurrentToolExecution:
    """Test concurrent tool calls from multiple contexts."""

    def test_concurrent_calculator_calls(self):
        """Test multiple concurrent calculator calls don't interfere."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        expressions = [
            ("2 + 2", 4),
            ("3 * 7", 21),
            ("sqrt(16)", 4.0),
            ("10 - 3", 7),
            ("100 / 4", 25.0),
        ]

        # Execute all concurrently
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {}
            for expr, expected in expressions:
                future = pool.submit(
                    executor.execute,
                    "Calculator",
                    {"expression": expr}
                )
                futures[future] = (expr, expected)

            # Verify all results
            for future in as_completed(futures):
                expr, expected = futures[future]
                result = future.result()

                assert result.success is True, \
                    f"Expression '{expr}' failed: {result.error}"
                assert result.result == expected, \
                    f"Expression '{expr}' expected {expected}, got {result.result}"

    def test_concurrent_mixed_tool_calls(self):
        """Test concurrent calls to different tools."""
        registry = ToolRegistry()
        registry.register(Calculator())
        registry.register(SlowTool())
        registry.register(FailingTool())
        executor = ToolExecutor(registry)

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=3) as pool:
            # Submit different tool calls concurrently
            calc_future = pool.submit(
                executor.execute,
                "Calculator",
                {"expression": "5 * 5"}
            )
            slow_future = pool.submit(
                executor.execute,
                "SlowTool",
                {"seconds": 0.5},
                timeout=2
            )
            fail_future = pool.submit(
                executor.execute,
                "FailingTool",
                {"error_message": "Expected failure"}
            )

            # Wait for all to complete
            calc_result = calc_future.result()
            slow_result = slow_future.result()
            fail_result = fail_future.result()

            # Verify each result
            assert calc_result.success is True
            assert calc_result.result == 25

            assert slow_result.success is True
            assert "0.5 seconds" in slow_result.result

            assert fail_result.success is False
            assert "Expected failure" in fail_result.error

    def test_concurrent_tool_resource_safety(self):
        """Test that concurrent tool calls don't cause resource conflicts."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Run 50 concurrent calculator calls
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = []
            for i in range(50):
                future = pool.submit(
                    executor.execute,
                    "Calculator",
                    {"expression": f"{i} + {i}"}
                )
                futures.append((future, i))

            # Verify all complete successfully
            success_count = 0
            for future, i in futures:
                result = future.result()
                if result.success:
                    assert result.result == i + i
                    success_count += 1

            assert success_count == 50, f"Only {success_count}/50 succeeded"


class TestToolOutputLimits:
    """Test tool output size limits."""

    def test_tool_output_within_limit(self):
        """Test that tool output within limits succeeds."""
        registry = ToolRegistry()
        registry.register(LargeOutputTool())
        executor = ToolExecutor(registry)

        # 1MB output (within typical limits)
        result = executor.execute("LargeOutputTool", {"size_mb": 1})

        assert result.success is True
        assert len(result.result) == 1024 * 1024

    def test_tool_output_metadata(self):
        """Test that tool execution metadata is captured."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        result = executor.execute("Calculator", {"expression": "2 + 2"})

        assert result.success is True
        # Check that executor adds execution time metadata
        assert "execution_time_seconds" in result.metadata
        assert result.metadata["execution_time_seconds"] > 0

        # Check that tool's own metadata is preserved
        assert "expression" in result.metadata
        assert result.metadata["expression"] == "2 + 2"


class TestToolRegistryIntegration:
    """Test tool registry integration."""

    def test_tool_registration_and_retrieval(self):
        """Test that tools can be registered and retrieved."""
        registry = ToolRegistry()

        # Register tool
        calc = Calculator()
        registry.register(calc)

        # Retrieve tool
        retrieved = registry.get("Calculator")
        assert retrieved is not None
        assert retrieved.name == "Calculator"

        # Check tool is in list
        assert "Calculator" in registry.list_tools()

    def test_duplicate_tool_registration_error(self):
        """Test that duplicate tool registration raises error."""
        from temper_ai.shared.utils.exceptions import ToolRegistryError

        registry = ToolRegistry()

        # Register once - should succeed
        registry.register(Calculator())

        # Register again - should fail
        with pytest.raises(ToolRegistryError) as exc_info:
            registry.register(Calculator())

        assert "already registered" in str(exc_info.value).lower()

    def test_tool_unregistration(self):
        """Test that tools can be unregistered."""
        registry = ToolRegistry()

        # Register and verify
        registry.register(Calculator())
        assert registry.has("Calculator")

        # Unregister and verify
        registry.unregister("Calculator")
        assert not registry.has("Calculator")

    def test_multiple_tool_registration(self):
        """Test registering multiple tools at once."""
        registry = ToolRegistry()

        tools = [Calculator(), SlowTool(), FailingTool()]
        registry.register_multiple(tools)

        assert len(registry.list_tools()) == 3
        assert registry.has("Calculator")
        assert registry.has("SlowTool")
        assert registry.has("FailingTool")


class TestToolExecutionMetadata:
    """Test tool execution metadata tracking."""

    def test_execution_time_metadata(self):
        """Test that execution time is tracked in metadata."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        result = executor.execute("Calculator", {"expression": "2 + 2"})

        assert "execution_time_seconds" in result.metadata
        assert isinstance(result.metadata["execution_time_seconds"], (int, float))
        assert result.metadata["execution_time_seconds"] >= 0

    def test_tool_metadata_preserved(self):
        """Test that tool's own metadata is preserved."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        result = executor.execute("Calculator", {"expression": "sqrt(16)"})

        # Tool adds its own metadata
        assert "expression" in result.metadata
        assert "result_type" in result.metadata

        # Executor adds execution metadata
        assert "execution_time_seconds" in result.metadata

    def test_error_metadata(self):
        """Test that errors are properly captured in ToolResult."""
        registry = ToolRegistry()
        registry.register(Calculator())
        executor = ToolExecutor(registry)

        # Use calculator with error
        result = executor.execute("Calculator", {"expression": "1 / 0"})

        assert result.success is False
        assert "zero" in result.error.lower()
        # Result and error are mutually exclusive
        assert result.result is None
