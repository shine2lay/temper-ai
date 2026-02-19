"""
Helper functions for error propagation testing.

Provides:
- Mock tools that fail in controlled ways
- Agent configurations with failing tools
- Workflow configs with failing stages
- Error assertion helpers
"""
import time
from typing import Any, Dict, List, Type

from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult


class FailingTool(BaseTool):
    """Tool that always fails with specified error."""

    def __init__(self, error_type: type = Exception, error_message: str = "Tool failed"):
        self.error_type = error_type
        self.error_message = error_message
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="FailingTool",
            description="Always fails for testing",
            version="1.0"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self, **kwargs) -> ToolResult:
        raise self.error_type(self.error_message)


class TimeoutTool(BaseTool):
    """Tool that times out after specified duration."""

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds
        super().__init__()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="TimeoutTool",
            description="Sleeps for specified duration",
            version="1.0"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self, **kwargs) -> ToolResult:
        time.sleep(self.timeout_seconds)
        return ToolResult(success=True, result="completed")


class FlakyTool(BaseTool):
    """Tool that fails first N times, then succeeds.

    Note: Use reset() between test runs or create new instance to avoid
    shared state issues in parallel tests.
    """

    def __init__(self, fail_count: int = 2, error_message: str = "Transient failure"):
        self.fail_count = fail_count
        self.error_message = error_message
        super().__init__()
        self.reset()

    def reset(self) -> None:
        """Reset tool state between test runs."""
        self.call_count = 0

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="FlakyTool",
            description="Fails first N times, then succeeds",
            version="1.0"
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    def execute(self, **kwargs) -> ToolResult:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise TimeoutError(self.error_message)
        return ToolResult(success=True, result={"retry_count": self.call_count - 1})


def assert_error_chain(error: Exception, expected_chain: List[Type[Exception]]) -> None:
    """Assert error has expected cause chain.

    Args:
        error: The top-level exception
        expected_chain: List of exception types in order (top to bottom)

    Example:
        >>> assert_error_chain(workflow_error, [WorkflowError, AgentError, ToolError])

    Note:
        This function checks both __cause__ (Python standard) and .cause (our custom field)
        for error chaining, supporting both patterns.
    """
    current = error
    for i, expected_type in enumerate(expected_chain):
        assert isinstance(current, expected_type), \
            f"Level {i}: expected {expected_type.__name__}, got {type(current).__name__}"

        if i < len(expected_chain) - 1:
            # Not the last item, should have a cause
            # Check both __cause__ (Python standard) and .cause (our custom field)
            next_error = getattr(current, '__cause__', None) or getattr(current, 'cause', None)
            assert next_error is not None, \
                f"Level {i} ({expected_type.__name__}) missing __cause__ or .cause"
            current = next_error


def assert_context_preserved(error: Exception, expected_context: Dict[str, Any]) -> None:
    """Assert error context contains expected fields.

    Args:
        error: Exception with context attribute
        expected_context: Dict of field names and expected values
    """
    for field, expected_value in expected_context.items():
        actual_value = getattr(error.context, field, None)
        assert actual_value == expected_value, \
            f"Context mismatch: {field}={actual_value}, expected {expected_value}"


def assert_secrets_sanitized(error_message: str) -> None:
    """Assert secrets are sanitized in error message.

    Args:
        error_message: The error message to check
    """
    # Check for common secret patterns
    secret_patterns = [
        "api_key=sk-",
        "token=ghp_",
        "password=",
        "secret=",
        "key=",
    ]

    for pattern in secret_patterns:
        assert pattern.lower() not in error_message.lower(), \
            f"Secret pattern '{pattern}' found in error message: {error_message}"
