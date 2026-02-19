"""Tests for src/utils/exceptions.py.

Tests enhanced exception classes with execution context and error codes.
"""
import pytest

from temper_ai.shared.core.context import ExecutionContext
from temper_ai.shared.utils.exceptions import (
    AgentError,
    BaseError,
    ConfigNotFoundError,
    ConfigurationError,
    ConfigValidationError,
    ErrorCode,
    FrameworkException,
    FrameworkValidationError,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    RateLimitError,
    SafetyError,
    SecurityError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolRegistryError,
    ValidationError,
    WorkflowError,
    get_error_info,
    sanitize_error_message,
    wrap_exception,
)


class TestSanitizeErrorMessage:
    """Test sanitize_error_message function."""

    def test_sanitize_api_key(self):
        """Test sanitizing API keys."""
        message = "API key sk-test-123 failed"
        sanitized = sanitize_error_message(message)
        assert "sk-test-123" not in sanitized
        assert "[REDACTED-API-KEY]" in sanitized

    def test_sanitize_aws_key(self):
        """Test sanitizing AWS keys."""
        message = "AWS key AKIAIOSFODNN7EXAMPLE failed"
        sanitized = sanitize_error_message(message)
        assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
        assert "[REDACTED-AWS-KEY]" in sanitized

    def test_sanitize_password(self):
        """Test sanitizing passwords."""
        message = "Password='secret123' invalid"
        sanitized = sanitize_error_message(message)
        assert "secret123" not in sanitized
        assert "[REDACTED-PASSWORD]" in sanitized

    def test_sanitize_jwt_token(self):
        """Test sanitizing JWT tokens."""
        message = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        sanitized = sanitize_error_message(message)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
        assert "[REDACTED-TOKEN]" in sanitized

    def test_sanitize_connection_string(self):
        """Test sanitizing database connection strings."""
        message = "Failed to connect: postgres://user:pass@localhost/db"
        sanitized = sanitize_error_message(message)
        assert "user:pass" not in sanitized
        assert "[REDACTED-CREDENTIALS]" in sanitized

    def test_empty_message(self):
        """Test that empty message is returned as-is."""
        assert sanitize_error_message("") == ""
        assert sanitize_error_message(None) is None


class TestErrorCode:
    """Test ErrorCode enum."""

    def test_error_codes_exist(self):
        """Test that all major error codes are defined."""
        assert ErrorCode.CONFIG_NOT_FOUND == "CONFIG_NOT_FOUND"
        assert ErrorCode.LLM_CONNECTION_ERROR == "LLM_CONNECTION_ERROR"
        assert ErrorCode.TOOL_EXECUTION_ERROR == "TOOL_EXECUTION_ERROR"
        assert ErrorCode.AGENT_EXECUTION_ERROR == "AGENT_EXECUTION_ERROR"
        assert ErrorCode.WORKFLOW_EXECUTION_ERROR == "WORKFLOW_EXECUTION_ERROR"
        assert ErrorCode.SAFETY_VIOLATION == "SAFETY_VIOLATION"
        assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"
        assert ErrorCode.UNKNOWN_ERROR == "UNKNOWN_ERROR"


class TestFrameworkException:
    """Test FrameworkException base class."""

    def test_framework_exception(self):
        """Test FrameworkException can be raised and caught."""
        with pytest.raises(FrameworkException):
            raise FrameworkException("test error")


class TestBaseError:
    """Test BaseError class."""

    def test_basic_initialization(self):
        """Test basic BaseError initialization."""
        error = BaseError("test message")
        assert error.message == "test message"
        assert error.error_code == ErrorCode.UNKNOWN_ERROR
        assert error.cause is None
        assert error.extra_data == {}

    def test_with_error_code(self):
        """Test BaseError with custom error code."""
        error = BaseError("test", error_code=ErrorCode.CONFIG_INVALID)
        assert error.error_code == ErrorCode.CONFIG_INVALID

    def test_with_context(self):
        """Test BaseError with execution context."""
        context = ExecutionContext(workflow_id="wf-123", stage_id="stage-1")
        error = BaseError("test", context=context)
        assert error.context.workflow_id == "wf-123"
        assert error.context.stage_id == "stage-1"

    def test_with_cause(self):
        """Test BaseError with cause exception."""
        cause = ValueError("original error")
        error = BaseError("wrapped error", cause=cause)
        assert error.cause is cause
        assert "Caused by" in str(error)

    def test_with_extra_data(self):
        """Test BaseError with extra data."""
        error = BaseError("test", extra_data={"key": "value"})
        assert error.extra_data["key"] == "value"

    def test_to_dict(self):
        """Test converting BaseError to dictionary."""
        context = ExecutionContext(workflow_id="wf-123")
        error = BaseError("test", error_code=ErrorCode.CONFIG_INVALID, context=context)
        error_dict = error.to_dict()

        assert error_dict["error_type"] == "BaseError"
        assert error_dict["message"] == "test"
        assert error_dict["error_code"] == "CONFIG_INVALID"
        assert "timestamp" in error_dict

    def test_sanitized_str(self):
        """Test that str() output is sanitized."""
        error = BaseError("API key sk-test-123 failed")
        error_str = str(error)
        assert "sk-test-123" not in error_str
        assert "[REDACTED-API-KEY]" in error_str

    def test_sanitized_repr(self):
        """Test that repr() output is sanitized."""
        error = BaseError("Password='secret' invalid")
        error_repr = repr(error)
        assert "secret" not in error_repr
        assert "[REDACTED-PASSWORD]" in error_repr


class TestConfigurationError:
    """Test ConfigurationError and subclasses."""

    def test_configuration_error(self):
        """Test ConfigurationError initialization."""
        error = ConfigurationError("Invalid config")
        assert error.error_code == ErrorCode.CONFIG_INVALID

    def test_config_not_found_error(self):
        """Test ConfigNotFoundError."""
        error = ConfigNotFoundError("Config missing", config_path="/path/to/config.yaml")
        assert error.error_code == ErrorCode.CONFIG_NOT_FOUND
        assert error.extra_data["config_path"] == "/path/to/config.yaml"

    def test_config_validation_error(self):
        """Test ConfigValidationError."""
        validation_errors = [{"field": "timeout", "error": "must be positive"}]
        error = ConfigValidationError("Validation failed", validation_errors=validation_errors)
        assert error.error_code == ErrorCode.CONFIG_VALIDATION_ERROR
        assert error.extra_data["validation_errors"] == validation_errors


class TestLLMError:
    """Test LLMError and subclasses."""

    def test_llm_error(self):
        """Test LLMError initialization."""
        error = LLMError("Connection failed")
        assert error.error_code == ErrorCode.LLM_CONNECTION_ERROR

    def test_llm_error_with_provider(self):
        """Test LLMError with provider and model."""
        error = LLMError("Timeout", provider="openai", model="gpt-4")
        assert error.extra_data["provider"] == "openai"
        assert error.extra_data["model"] == "gpt-4"

    def test_llm_timeout_error(self):
        """Test LLMTimeoutError."""
        error = LLMTimeoutError("Request timed out", timeout_seconds=30)
        assert error.error_code == ErrorCode.LLM_TIMEOUT
        assert error.extra_data["timeout_seconds"] == 30

    def test_llm_rate_limit_error(self):
        """Test LLMRateLimitError."""
        error = LLMRateLimitError("Rate limited", retry_after=60)
        assert error.error_code == ErrorCode.LLM_RATE_LIMIT
        assert error.retry_after == 60
        assert error.extra_data["retry_after"] == 60
        assert isinstance(error, RateLimitError)

    def test_llm_authentication_error(self):
        """Test LLMAuthenticationError."""
        error = LLMAuthenticationError("Invalid API key")
        assert error.error_code == ErrorCode.LLM_AUTHENTICATION_ERROR


class TestToolError:
    """Test ToolError and subclasses."""

    def test_tool_error(self):
        """Test ToolError initialization."""
        error = ToolError("Tool failed")
        assert error.error_code == ErrorCode.TOOL_EXECUTION_ERROR

    def test_tool_execution_error(self):
        """Test ToolExecutionError."""
        error = ToolExecutionError("Execution failed", tool_name="calculator")
        assert error.error_code == ErrorCode.TOOL_EXECUTION_ERROR
        assert error.context.tool_name == "calculator"

    def test_tool_not_found_error(self):
        """Test ToolNotFoundError."""
        error = ToolNotFoundError("Tool not found", tool_name="missing_tool")
        assert error.error_code == ErrorCode.TOOL_NOT_FOUND
        assert error.context.tool_name == "missing_tool"

    def test_tool_registry_error(self):
        """Test ToolRegistryError."""
        error = ToolRegistryError("Registry failed")
        assert error.error_code == ErrorCode.TOOL_REGISTRY_ERROR


class TestAgentError:
    """Test AgentError class."""

    def test_agent_error(self):
        """Test AgentError initialization."""
        error = AgentError("Agent failed")
        assert error.error_code == ErrorCode.AGENT_EXECUTION_ERROR

    def test_agent_error_with_name(self):
        """Test AgentError with agent name."""
        error = AgentError("Failed", agent_name="test-agent")
        assert error.extra_data["agent_name"] == "test-agent"


class TestWorkflowError:
    """Test WorkflowError class."""

    def test_workflow_error(self):
        """Test WorkflowError initialization."""
        error = WorkflowError("Workflow failed")
        assert error.error_code == ErrorCode.WORKFLOW_EXECUTION_ERROR

    def test_workflow_error_with_name(self):
        """Test WorkflowError with workflow name."""
        error = WorkflowError("Failed", workflow_name="test-workflow")
        assert error.extra_data["workflow_name"] == "test-workflow"


class TestSecurityError:
    """Test SecurityError class."""

    def test_security_error(self):
        """Test SecurityError can be raised."""
        with pytest.raises(SecurityError):
            raise SecurityError("Security violation")

    def test_security_error_is_framework_exception(self):
        """Test that SecurityError inherits from FrameworkException."""
        error = SecurityError("test")
        assert isinstance(error, FrameworkException)


class TestSafetyError:
    """Test SafetyError class."""

    def test_safety_error(self):
        """Test SafetyError initialization."""
        error = SafetyError("Policy violation")
        assert error.error_code == ErrorCode.SAFETY_VIOLATION

    def test_safety_error_with_policy(self):
        """Test SafetyError with policy name and severity."""
        error = SafetyError("Blocked", policy_name="rate_limit", severity="high")
        assert error.extra_data["policy_name"] == "rate_limit"
        assert error.extra_data["severity"] == "high"


class TestFrameworkValidationError:
    """Test FrameworkValidationError class."""

    def test_framework_validation_error(self):
        """Test FrameworkValidationError initialization."""
        error = FrameworkValidationError("Validation failed")
        assert error.error_code == ErrorCode.VALIDATION_ERROR

    def test_validation_error_with_field(self):
        """Test with field name."""
        error = FrameworkValidationError("Invalid", field_name="timeout")
        assert error.extra_data["field_name"] == "timeout"

    def test_deprecated_validation_error(self):
        """Test deprecated ValidationError alias."""
        with pytest.warns(DeprecationWarning, match="ValidationError is deprecated"):
            error = ValidationError("test")
            assert isinstance(error, FrameworkValidationError)


class TestUtilityFunctions:
    """Test utility functions."""

    def test_wrap_exception(self):
        """Test wrapping exception in BaseError."""
        original = ValueError("original error")
        context = ExecutionContext(workflow_id="wf-123")

        wrapped = wrap_exception(
            original,
            "Wrapped error",
            error_code=ErrorCode.CONFIG_INVALID,
            context=context
        )

        assert isinstance(wrapped, BaseError)
        assert wrapped.message == "Wrapped error"
        assert wrapped.error_code == ErrorCode.CONFIG_INVALID
        assert wrapped.cause is original
        assert wrapped.context.workflow_id == "wf-123"

    def test_get_error_info_base_error(self):
        """Test get_error_info with BaseError."""
        error = BaseError("test", error_code=ErrorCode.CONFIG_INVALID)
        info = get_error_info(error)

        assert info["error_type"] == "BaseError"
        assert info["message"] == "test"
        assert info["error_code"] == "CONFIG_INVALID"

    def test_get_error_info_standard_exception(self):
        """Test get_error_info with standard exception."""
        error = ValueError("test error")
        info = get_error_info(error)

        assert info["error_type"] == "ValueError"
        assert info["message"] == "test error"
        assert info["error_code"] == "UNKNOWN_ERROR"
        assert "timestamp" in info

    def test_get_error_info_dict_format(self):
        """Test get_error_info returns dict format."""
        error = ValueError("test")
        result = get_error_info(error)

        assert result["error_type"] == "ValueError"
        assert result["message"] == "test"


class TestRateLimitError:
    """Test RateLimitError base class."""

    def test_rate_limit_error(self):
        """Test RateLimitError initialization."""
        error = RateLimitError("Rate limited", retry_after=60)
        assert error.retry_after == 60
        assert isinstance(error, FrameworkException)

    def test_rate_limit_error_no_retry_after(self):
        """Test RateLimitError without retry_after."""
        error = RateLimitError("Rate limited")
        assert error.retry_after is None
