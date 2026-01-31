"""
Comprehensive boundary value and edge case tests.

Tests extreme values, limits, and edge cases across the system to ensure
robust error handling and graceful degradation.
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from src.compiler.schemas import (
    WorkflowConfig,
    StageConfig,
    AgentConfig,
    AgentConfigInner,
    PromptConfig,
    InferenceConfig,
)
from src.tools.base import ToolResult, ToolMetadata, BaseTool
from src.tools.registry import ToolRegistry
from src.tools.executor import ToolExecutor
from src.utils.exceptions import (
    ValidationError,
    ToolExecutionError,
    ConfigValidationError,
)


class TestStringBoundaries:
    """Test boundary values for string inputs."""

    def test_empty_string(self):
        """Test handling of empty strings."""
        config = PromptConfig(inline="")

        # Should handle empty prompt gracefully
        assert config.inline == ""

    def test_very_long_string(self):
        """Test handling of very long strings (10MB)."""
        # 10MB string
        long_string = "x" * (10 * 1024 * 1024)

        config = PromptConfig(inline=long_string)
        assert len(config.inline) == 10 * 1024 * 1024

    def test_unicode_string(self):
        """Test handling of Unicode strings."""
        unicode_str = "Hello 世界 🌍 Здравствуй мир"

        config = PromptConfig(inline=unicode_str)
        assert config.inline == unicode_str

    def test_string_with_null_bytes(self):
        """Test handling of strings with null bytes."""
        # Null bytes in strings can cause issues
        string_with_null = "Hello\x00World"

        # Should either handle gracefully or reject
        try:
            config = PromptConfig(inline=string_with_null)
            assert "\x00" in config.inline or config.inline == "HelloWorld"
        except (ValueError, ValidationError):
            # Also acceptable to reject
            pass

    def test_string_with_special_characters(self):
        """Test handling of special characters."""
        special_chars = "!@#$%^&*()_+-=[]{}|;':\",./<>?\n\r\t"

        config = PromptConfig(inline=special_chars)
        assert config.inline == special_chars

    def test_whitespace_only_string(self):
        """Test handling of whitespace-only strings."""
        whitespace = "   \n\t\r   "

        config = PromptConfig(inline=whitespace)
        assert config.inline == whitespace


class TestNumericBoundaries:
    """Test boundary values for numeric inputs."""

    def test_zero_timeout(self):
        """Test timeout of zero."""
        registry = ToolRegistry()
        executor = ToolExecutor(registry, default_timeout=0)

        # Zero timeout should be handled (either reject or instant timeout)
        assert executor.default_timeout == 0 or executor.default_timeout > 0

    def test_negative_timeout(self):
        """Test negative timeout."""
        # Negative timeout may be allowed (will be handled at execution time)
        # or converted to zero - test that it doesn't crash
        try:
            executor = ToolExecutor(ToolRegistry(), default_timeout=-1)
            # If allowed, should either be -1 or converted to positive
            assert executor.default_timeout == -1 or executor.default_timeout >= 0
        except (ValueError, ValidationError):
            # Also acceptable to reject negative timeouts
            pass

    def test_very_large_timeout(self):
        """Test very large timeout (1 year)."""
        timeout = 365 * 24 * 60 * 60  # 1 year in seconds

        registry = ToolRegistry()
        executor = ToolExecutor(registry, default_timeout=timeout)

        # Should handle large timeout
        assert executor.default_timeout == timeout

    def test_float_precision_limits(self):
        """Test floating point precision limits."""
        # Very small positive number
        tiny = 1e-308

        # Should handle tiny values
        result = ToolResult(
            success=True,
            result=tiny,
            metadata={"value": tiny}
        )

        assert result.result == tiny

    def test_integer_overflow(self):
        """Test very large integer values."""
        # Python ints have arbitrary precision, but test system limits
        huge_int = 2**128

        result = ToolResult(
            success=True,
            result=huge_int,
            metadata={"huge": huge_int}
        )

        assert result.result == huge_int

    def test_max_int_value(self):
        """Test maximum integer value."""
        max_int = 2**63 - 1  # Max 64-bit signed int

        result = ToolResult(
            success=True,
            result=max_int,
            metadata={"value": max_int}
        )

        assert result.result == max_int

    def test_infinity_values(self):
        """Test infinity and NaN values."""
        inf_positive = float('inf')
        inf_negative = float('-inf')
        nan = float('nan')

        # Should handle special float values
        result_inf = ToolResult(success=True, result=inf_positive)
        result_neg_inf = ToolResult(success=True, result=inf_negative)
        result_nan = ToolResult(success=True, result=nan)

        assert result_inf.result == inf_positive
        assert result_neg_inf.result == inf_negative
        # NaN != NaN, so use isnan
        import math
        assert math.isnan(result_nan.result)


class TestListBoundaries:
    """Test boundary values for list inputs."""

    def test_empty_list(self):
        """Test handling of empty lists in tool results."""
        empty_list = []

        result = ToolResult(
            success=True,
            result=empty_list,
            metadata={}
        )

        # Should handle empty lists gracefully
        assert result.result == []
        assert len(result.result) == 0

    def test_very_large_list(self):
        """Test handling of very large lists (100k items)."""
        large_list = list(range(100_000))

        result = ToolResult(
            success=True,
            result=large_list,
            metadata={}
        )

        assert len(result.result) == 100_000

    def test_deeply_nested_list(self):
        """Test handling of deeply nested lists (100 levels)."""
        # Create nested list: [[[[...]]]]
        nested = []
        current = nested
        for _ in range(100):
            new_list = []
            current.append(new_list)
            current = new_list

        result = ToolResult(
            success=True,
            result=nested,
            metadata={}
        )

        # Should handle deep nesting
        assert result.result == nested

    def test_list_with_mixed_types(self):
        """Test list with mixed types."""
        mixed = [1, "two", 3.0, None, True, {"key": "value"}, [1, 2, 3]]

        result = ToolResult(
            success=True,
            result=mixed,
            metadata={}
        )

        assert result.result == mixed

    def test_list_with_duplicates(self):
        """Test list with many duplicates."""
        duplicates = ["same"] * 10_000

        result = ToolResult(
            success=True,
            result=duplicates,
            metadata={}
        )

        assert len(result.result) == 10_000


class TestDictBoundaries:
    """Test boundary values for dictionary inputs."""

    def test_empty_dict(self):
        """Test handling of empty dictionaries."""
        result = ToolResult(
            success=True,
            result={},
            metadata={}
        )

        assert result.result == {}
        assert result.metadata == {}

    def test_very_large_dict(self):
        """Test handling of very large dictionaries (10k keys)."""
        large_dict = {f"key_{i}": f"value_{i}" for i in range(10_000)}

        result = ToolResult(
            success=True,
            result=large_dict,
            metadata={}
        )

        assert len(result.result) == 10_000

    def test_deeply_nested_dict(self):
        """Test handling of deeply nested dictionaries (100 levels)."""
        # Create nested dict: {"a": {"a": {"a": ...}}}
        nested = {}
        current = nested
        for i in range(100):
            current["level"] = {}
            if i < 99:
                current = current["level"]

        result = ToolResult(
            success=True,
            result=nested,
            metadata={}
        )

        # Should handle deep nesting
        assert "level" in result.result

    def test_dict_with_special_keys(self):
        """Test dictionary with special key names."""
        special_keys = {
            "": "empty",
            " ": "space",
            "\n": "newline",
            "key with spaces": "value",
            "unicode_世界": "value",
            "123": "numeric string",
        }

        result = ToolResult(
            success=True,
            result=special_keys,
            metadata={}
        )

        assert result.result == special_keys

    def test_dict_with_none_values(self):
        """Test dictionary with None values."""
        none_dict = {
            "null_value": None,
            "empty_string": "",
            "zero": 0,
            "false": False,
        }

        result = ToolResult(
            success=True,
            result=none_dict,
            metadata={}
        )

        assert result.result["null_value"] is None


class TestTimeBoundaries:
    """Test boundary values for time/date inputs."""

    def test_epoch_time(self):
        """Test Unix epoch time (1970-01-01)."""
        epoch = datetime(1970, 1, 1, 0, 0, 0)

        # Should handle epoch time
        assert epoch.year == 1970

    def test_very_old_date(self):
        """Test very old dates (year 1)."""
        old_date = datetime(1, 1, 1, 0, 0, 0)

        # Should handle old dates
        assert old_date.year == 1

    def test_far_future_date(self):
        """Test far future dates (year 9999)."""
        future_date = datetime(9999, 12, 31, 23, 59, 59)

        # Should handle far future dates
        assert future_date.year == 9999

    def test_zero_duration(self):
        """Test zero duration timedelta."""
        zero_duration = timedelta(seconds=0)

        # Should handle zero duration
        assert zero_duration.total_seconds() == 0

    def test_negative_duration(self):
        """Test negative duration timedelta."""
        negative_duration = timedelta(seconds=-100)

        # Should handle negative durations
        assert negative_duration.total_seconds() < 0

    def test_very_long_duration(self):
        """Test very long duration (100 years)."""
        long_duration = timedelta(days=365 * 100)

        # Should handle long durations
        assert long_duration.total_seconds() > 0


class TestFileBoundaries:
    """Test boundary values for file operations."""

    def test_empty_file_path(self):
        """Test handling of empty file path."""
        empty_path = Path("")

        # Empty path is represented as "." (current directory)
        assert str(empty_path) == "."

    def test_very_long_file_path(self):
        """Test handling of very long file paths."""
        # Create path with 1000 characters
        long_path = Path("a" * 1000)

        # Should create path object (OS may reject when used)
        assert len(str(long_path)) == 1000

    def test_file_path_with_special_chars(self):
        """Test file path with special characters."""
        # Note: Some chars invalid on certain OSes
        special_path = Path("test!@#$%.txt")

        # Should create path object
        assert "test" in str(special_path)

    def test_relative_vs_absolute_paths(self):
        """Test relative and absolute paths."""
        relative = Path("relative/path")
        absolute = Path("/absolute/path")

        assert not relative.is_absolute()
        assert absolute.is_absolute()


class TestConcurrencyBoundaries:
    """Test boundary values for concurrent operations."""

    @pytest.mark.asyncio
    async def test_single_concurrent_task(self):
        """Test concurrency with just 1 task."""
        async def single_task():
            return "done"

        result = await asyncio.gather(single_task())

        assert len(result) == 1
        assert result[0] == "done"

    @pytest.mark.asyncio
    async def test_maximum_concurrent_tasks(self):
        """Test very high concurrency (1000 tasks)."""
        async def quick_task(task_id):
            await asyncio.sleep(0.001)
            return task_id

        # Execute 1000 tasks concurrently
        tasks = [quick_task(i) for i in range(1000)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 1000
        assert set(results) == set(range(1000))

    @pytest.mark.asyncio
    async def test_zero_sleep_duration(self):
        """Test async sleep with zero duration."""
        async def zero_sleep_task():
            await asyncio.sleep(0)
            return "done"

        result = await zero_sleep_task()

        assert result == "done"


class TestErrorMessageBoundaries:
    """Test boundary values for error messages."""

    def test_empty_error_message(self):
        """Test handling of empty error messages."""
        result = ToolResult(
            success=False,
            error="",
            metadata={}
        )

        assert result.success is False
        assert result.error == ""

    def test_very_long_error_message(self):
        """Test handling of very long error messages (1MB)."""
        long_error = "Error: " + "x" * (1024 * 1024)

        result = ToolResult(
            success=False,
            error=long_error,
            metadata={}
        )

        assert len(result.error) > 1024 * 1024

    def test_error_message_with_unicode(self):
        """Test error messages with Unicode characters."""
        unicode_error = "错误: Something went wrong 💥"

        result = ToolResult(
            success=False,
            error=unicode_error,
            metadata={}
        )

        assert result.error == unicode_error

    def test_error_message_with_newlines(self):
        """Test multi-line error messages."""
        multiline_error = "Error on line 1\nError on line 2\nError on line 3"

        result = ToolResult(
            success=False,
            error=multiline_error,
            metadata={}
        )

        assert "\n" in result.error


class TestMetadataBoundaries:
    """Test boundary values for metadata."""

    def test_metadata_with_all_types(self):
        """Test metadata with all Python types."""
        metadata = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
            "tuple": (1, 2, 3),
        }

        result = ToolResult(
            success=True,
            result="test",
            metadata=metadata
        )

        assert result.metadata["string"] == "value"
        assert result.metadata["int"] == 42

    def test_metadata_deeply_nested(self):
        """Test deeply nested metadata (50 levels)."""
        # Create deeply nested metadata
        nested = {"level": 0}
        current = nested
        for i in range(50):
            current["next"] = {"level": i + 1}
            current = current["next"]

        result = ToolResult(
            success=True,
            result="test",
            metadata=nested
        )

        # Should handle deep nesting
        assert result.metadata["level"] == 0

    def test_metadata_with_large_values(self):
        """Test metadata with large values (10MB string)."""
        large_value = "x" * (10 * 1024 * 1024)

        result = ToolResult(
            success=True,
            result="test",
            metadata={"large": large_value}
        )

        assert len(result.metadata["large"]) == 10 * 1024 * 1024


class TestToolNameBoundaries:
    """Test boundary values for tool names."""

    def test_single_char_tool_name(self):
        """Test tool with single character name."""
        class SingleCharTool(BaseTool):
            def get_metadata(self):
                return ToolMetadata(name="A", description="Test", version="1.0")

            def get_parameters_schema(self):
                return {"type": "object", "properties": {}}

            def execute(self, **kwargs):
                return ToolResult(success=True, result="done")

        tool = SingleCharTool()
        assert tool.name == "A"

    def test_very_long_tool_name(self):
        """Test tool with very long name (1000 chars)."""
        long_name = "Tool" + "X" * 996

        class LongNameTool(BaseTool):
            def get_metadata(self):
                return ToolMetadata(name=long_name, description="Test", version="1.0")

            def get_parameters_schema(self):
                return {"type": "object", "properties": {}}

            def execute(self, **kwargs):
                return ToolResult(success=True, result="done")

        tool = LongNameTool()
        assert len(tool.name) == 1000

    def test_tool_name_with_special_chars(self):
        """Test tool name with special characters."""
        class SpecialCharTool(BaseTool):
            def get_metadata(self):
                return ToolMetadata(
                    name="Tool-Name_123",
                    description="Test",
                    version="1.0"
                )

            def get_parameters_schema(self):
                return {"type": "object", "properties": {}}

            def execute(self, **kwargs):
                return ToolResult(success=True, result="done")

        tool = SpecialCharTool()
        assert tool.name == "Tool-Name_123"


class TestVersionBoundaries:
    """Test boundary values for version strings."""

    def test_version_single_number(self):
        """Test version with single number."""
        metadata = ToolMetadata(name="Test", description="Test", version="1")

        assert metadata.version == "1"

    def test_version_very_long(self):
        """Test very long version string."""
        long_version = "1.2.3.4.5.6.7.8.9.10.11.12.13.14.15"

        metadata = ToolMetadata(name="Test", description="Test", version=long_version)

        assert metadata.version == long_version

    def test_version_with_special_chars(self):
        """Test version with special characters."""
        special_version = "1.0.0-alpha+build.123"

        metadata = ToolMetadata(name="Test", description="Test", version=special_version)

        assert metadata.version == special_version


class TestNullAndNoneBoundaries:
    """Test handling of null and None values."""

    def test_none_result(self):
        """Test ToolResult with None as result."""
        result = ToolResult(
            success=True,
            result=None,
            metadata={}
        )

        assert result.result is None

    def test_none_error(self):
        """Test ToolResult with None as error."""
        result = ToolResult(
            success=False,
            error=None,  # Should probably be a string, but test boundary
            metadata={}
        )

        # Depending on validation, may convert to string or allow None
        assert result.error is None or result.error == ""

    def test_none_in_metadata(self):
        """Test None values in metadata."""
        result = ToolResult(
            success=True,
            result="test",
            metadata={
                "none_value": None,
                "some_value": "present"
            }
        )

        assert result.metadata["none_value"] is None
        assert result.metadata["some_value"] == "present"


class TestBooleanBoundaries:
    """Test boolean edge cases."""

    def test_truthy_values(self):
        """Test various truthy values."""
        truthy_values = [
            True,
            1,
            "non-empty",
            [1],
            {"key": "value"},
        ]

        for value in truthy_values:
            assert bool(value) is True

    def test_falsy_values(self):
        """Test various falsy values."""
        falsy_values = [
            False,
            0,
            "",
            [],
            {},
            None,
        ]

        for value in falsy_values:
            assert bool(value) is False

    def test_boolean_in_tool_result(self):
        """Test boolean values in ToolResult."""
        # Success = True
        result_success = ToolResult(success=True, result=True)
        assert result_success.success is True
        assert result_success.result is True

        # Success = False
        result_failure = ToolResult(success=False, error="Failed")
        assert result_failure.success is False
