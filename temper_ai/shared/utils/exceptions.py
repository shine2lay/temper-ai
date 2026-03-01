"""Enhanced exception classes with execution context and error codes.

Provides base exception classes that include:
- Execution context (workflow_id, stage_id, agent_id)
- Error codes for programmatic handling
- Stack traces and debugging info
- Structured error messages
- Automatic sanitization of sensitive data (API keys, passwords, tokens)
"""

import re
import traceback
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from temper_ai.shared.core.context import ExecutionContext


def _build_error_sanitizers() -> list[tuple[re.Pattern[str], str]]:
    """Build compiled sanitizers from the central secret pattern registry."""
    from temper_ai.shared.utils.secret_patterns import (
        GENERIC_SECRET_PATTERNS,
        SECRET_PATTERNS,
    )

    # Map pattern names to specific redaction labels
    _LABEL_MAP: dict[str, str] = {
        "openai_project_key": "[REDACTED-API-KEY]",
        "openai_key": "[REDACTED-API-KEY]",
        "anthropic_key": "[REDACTED-API-KEY]",
        "aws_access_key": "[REDACTED-AWS-KEY]",
        "aws_secret_key": "[REDACTED-AWS-KEY]",
        "github_token": "[REDACTED-TOKEN]",
        "google_api_key": "[REDACTED-API-KEY]",
        "google_oauth": "[REDACTED-TOKEN]",
        "slack_token": "[REDACTED-TOKEN]",
        "stripe_key": "[REDACTED-API-KEY]",
        "connection_string": "[REDACTED-CREDENTIALS]",
        "jwt_token": "[REDACTED-JWT-TOKEN]",
        "bearer_token": "[REDACTED-TOKEN]",
        "private_key": "[REDACTED-PRIVATE-KEY]",
        "http_auth_header": "[REDACTED-TOKEN]",
        "url_query_secret": "[REDACTED]",
        "api_key": "[REDACTED-API-KEY]",
        "generic_api_key": "[REDACTED-API-KEY]",
        "generic_secret": "[REDACTED-PASSWORD]",
        "generic_token": "[REDACTED-TOKEN]",
        "password_disclosure": "[REDACTED-PASSWORD]",
        "db_credentials": "[REDACTED-CREDENTIALS]",
    }

    sanitizers = []
    for name, pattern in SECRET_PATTERNS.items():
        label = _LABEL_MAP.get(name, "[REDACTED]")
        sanitizers.append((re.compile(pattern, re.IGNORECASE), label))
    for name, pattern in GENERIC_SECRET_PATTERNS.items():
        label = _LABEL_MAP.get(name, "[REDACTED]")
        sanitizers.append((re.compile(pattern, re.IGNORECASE), label))

    # Additional broad patterns for error-message sanitization.
    # These catch shorter or dash-separated keys common in error messages.
    extra = [
        # sk- prefixed keys with dashes (e.g. sk-test-1234567890abcdef)
        (r"\bsk-[a-zA-Z0-9][a-zA-Z0-9-]{6,200}\b", "[REDACTED-API-KEY]"),
        # Partial JWT header (eyJ... without full 3-part structure)
        (r"\beyJ[a-zA-Z0-9_-]{10,2000}(?:\.[a-zA-Z0-9_-]+)*", "[REDACTED-JWT-TOKEN]"),
        # password/pwd/passwd=<value> with short values (>= 4 chars)
        (
            r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"]?(\S{4,500})['\"]?",
            "[REDACTED-PASSWORD]",
        ),
    ]
    for pat, label in extra:
        sanitizers.append((re.compile(pat, re.IGNORECASE), label))

    return sanitizers


_ERROR_SANITIZERS: list[tuple[re.Pattern[str], str]] | None = None


def sanitize_error_message(message: str) -> str:
    """Sanitize sensitive data from error messages.

    Uses the central secret pattern registry to redact all known secret
    patterns including vendor API keys, connection strings, JWTs, passwords,
    auth headers, and URL query-param secrets.

    Args:
        message: Error message that may contain sensitive data

    Returns:
        Sanitized message with sensitive data redacted
    """
    if not message:
        return message

    global _ERROR_SANITIZERS  # noqa: PLW0603
    if _ERROR_SANITIZERS is None:
        _ERROR_SANITIZERS = _build_error_sanitizers()

    for compiled_pattern, replacement in _ERROR_SANITIZERS:
        message = compiled_pattern.sub(replacement, message)

    return message


class ErrorCode(StrEnum):
    """Standard error codes for programmatic handling.

    Error codes follow format: CATEGORY_SPECIFIC_ERROR
    - CONFIG_*: Configuration errors
    - LLM_*: LLM provider errors
    - TOOL_*: Tool execution errors
    - AGENT_*: Agent execution errors
    - WORKFLOW_*: Workflow execution errors
    - SAFETY_*: Safety policy errors
    - VALIDATION_*: Validation errors
    """

    # Configuration errors
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_VALIDATION_ERROR = "CONFIG_VALIDATION_ERROR"

    # LLM errors
    LLM_CONNECTION_ERROR = "LLM_CONNECTION_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"
    LLM_AUTHENTICATION_ERROR = "LLM_AUTHENTICATION_ERROR"

    # Tool errors
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_REGISTRY_ERROR = "TOOL_REGISTRY_ERROR"

    # Agent errors
    AGENT_EXECUTION_ERROR = "AGENT_EXECUTION_ERROR"
    AGENT_MAX_ITERATIONS = "AGENT_MAX_ITERATIONS"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"

    # Workflow errors
    WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"
    WORKFLOW_STAGE_ERROR = "WORKFLOW_STAGE_ERROR"
    WORKFLOW_TIMEOUT = "WORKFLOW_TIMEOUT"

    # Safety errors
    SAFETY_VIOLATION = "SAFETY_VIOLATION"

    # Validation errors
    VALIDATION_ERROR = "VALIDATION_ERROR"

    # System errors
    SYSTEM_ERROR = "SYSTEM_ERROR"
    SYSTEM_TIMEOUT = "SYSTEM_TIMEOUT"
    SYSTEM_RESOURCE_ERROR = "SYSTEM_RESOURCE_ERROR"

    # Unknown/Generic
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class FrameworkException(  # noqa: N818 — intentional: base exception, not a specific error
    Exception
):
    """Root exception for Temper AI.

    All framework-specific exceptions should ultimately inherit from this class,
    providing a single catch-all base for framework error handling.

    Example:
        >>> try:
        ...     run_workflow()
        ... except FrameworkException:
        ...     # Catches any framework-originated error
        ...     handle_error()
    """

    pass


class BaseError(FrameworkException):
    """Base exception class with execution context and error codes.

    All custom exceptions should inherit from this class to get
    consistent error handling with context preservation.

    Attributes:
        message: Error message
        error_code: ErrorCode for programmatic handling
        context: ExecutionContext with workflow/stage/agent info
        cause: Original exception that caused this error
        timestamp: When the error occurred
        extra_data: Additional error-specific data

    Example:
        >>> try:
        ...     # Some operation
        ...     pass
        ... except Exception as e:
        ...     raise BaseError(
        ...         message="Operation failed",
        ...         error_code=ErrorCode.SYSTEM_ERROR,
        ...         context=ExecutionContext(workflow_id="wf-123"),
        ...         cause=e
        ...     )
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        extra_data: dict[str, Any] | None = None,
    ):
        self.message = message
        self.error_code = error_code
        # Lazy import to avoid circular dependency
        if context is None:
            from temper_ai.shared.core.context import ExecutionContext

            context = ExecutionContext()
        self.context = context
        self.cause = cause
        self.timestamp = datetime.now(UTC)
        self.extra_data = extra_data or {}

        # Build detailed message
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        """Build detailed error message with context.

        SECURITY: All messages are sanitized to remove sensitive data
        (API keys, passwords, tokens) before being returned.
        """
        # Start with error code and base message
        parts = [f"[{self.error_code.value}] {self.message}"]

        # Add context information
        context_parts = []
        if self.context.workflow_id:
            context_parts.append(f"workflow_id={self.context.workflow_id}")
        if self.context.stage_id:
            context_parts.append(f"stage_id={self.context.stage_id}")
        if self.context.agent_id:
            context_parts.append(f"agent_id={self.context.agent_id}")
        if self.context.tool_name:
            context_parts.append(f"tool={self.context.tool_name}")

        if context_parts:
            parts.append(f"Context: {', '.join(context_parts)}")

        # Add cause if present
        if self.cause:
            # Sanitize cause message as well
            cause_str = sanitize_error_message(str(self.cause))
            parts.append(f"Caused by: {type(self.cause).__name__}: {cause_str}")

        # Build full message and sanitize it
        full_message = " | ".join(parts)
        return sanitize_error_message(full_message)

    def __str__(self) -> str:
        """Return sanitized error message.

        SECURITY: Ensures sensitive data is redacted even when
        error is converted to string directly.
        """
        # The message was already sanitized in _build_message(),
        # but sanitize again for safety in case message was modified
        return sanitize_error_message(super().__str__())

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for serialization.

        SECURITY: All string fields are sanitized to remove sensitive data.
        """
        return {
            "error_type": self.__class__.__name__,
            "message": sanitize_error_message(self.message),
            "error_code": self.error_code.value,
            "context": self.context.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "cause": sanitize_error_message(str(self.cause)) if self.cause else None,
            "extra_data": self.extra_data,
            "traceback": (
                sanitize_error_message(traceback.format_exc()) if self.cause else None
            ),
        }

    def __repr__(self) -> str:
        """Return sanitized repr.

        SECURITY: Sanitizes message to prevent secrets in debug output.
        """
        sanitized_message = sanitize_error_message(self.message)
        return f"{self.__class__.__name__}(code={self.error_code.value}, message='{sanitized_message}', context={self.context})"


# Configuration Exceptions


class ConfigurationError(BaseError):
    """Base class for configuration-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.CONFIG_INVALID,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        config_path: str | None = None,
        **kwargs: Any,
    ) -> None:
        extra_data = kwargs.get("extra_data", {})
        if config_path:
            extra_data["config_path"] = config_path

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            extra_data=extra_data,
        )


class ConfigNotFoundError(ConfigurationError):
    """Raised when a configuration file cannot be found."""

    def __init__(self, message: str, config_path: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFIG_NOT_FOUND,
            config_path=config_path,
            **kwargs,
        )


class ConfigValidationError(ConfigurationError):
    """Raised when configuration fails validation."""

    def __init__(
        self,
        message: str,
        validation_errors: list[Any] | None = None,
        config_errors: list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.config_errors = config_errors or []
        extra_data = kwargs.get("extra_data", {})
        if validation_errors:
            extra_data["validation_errors"] = validation_errors
        kwargs["extra_data"] = extra_data

        super().__init__(
            message=message, error_code=ErrorCode.CONFIG_VALIDATION_ERROR, **kwargs
        )


# LLM Exceptions


class LLMError(BaseError):
    """Base class for LLM provider errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.LLM_CONNECTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        provider: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        extra_data = kwargs.get("extra_data", {})
        if provider:
            extra_data["provider"] = provider
        if model:
            extra_data["model"] = model
        kwargs["extra_data"] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs,
        )


class LLMTimeoutError(LLMError):
    """Raised when LLM call times out."""

    def __init__(
        self, message: str, timeout_seconds: int | None = None, **kwargs: Any
    ) -> None:
        extra_data = kwargs.get("extra_data", {})
        if timeout_seconds:
            extra_data["timeout_seconds"] = timeout_seconds
        kwargs["extra_data"] = extra_data

        super().__init__(message=message, error_code=ErrorCode.LLM_TIMEOUT, **kwargs)


class RateLimitError(FrameworkException):
    """Base class for all rate limit exceptions across the framework.

    Provides unified rate limit handling for:
    - LLM providers (LLMRateLimitError)
    - Tool executors (ToolRateLimitError)
    - OAuth/Auth services (OAuthRateLimitError)

    Attributes:
        message: Error message
        retry_after: Optional seconds until rate limit resets
    """

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        """Initialize rate limit exception.

        Args:
            message: Error message
            retry_after: Optional seconds until rate limit resets
        """
        self.retry_after = retry_after
        super().__init__(message)


class LLMRateLimitError(LLMError, RateLimitError):
    """Raised when rate limited by LLM provider.

    Multiple inheritance:
    - LLMError: Provides LLM-specific context and error codes
    - RateLimitError: Unified rate limit base class for isinstance checks
    """

    def __init__(
        self, message: str, retry_after: int | None = None, **kwargs: Any
    ) -> None:
        extra_data = kwargs.get("extra_data", {})
        if retry_after:
            extra_data["retry_after"] = retry_after
        kwargs["extra_data"] = extra_data

        # Initialize LLMError (which handles BaseError and FrameworkException)
        LLMError.__init__(
            self, message=message, error_code=ErrorCode.LLM_RATE_LIMIT, **kwargs
        )
        # Store retry_after on self (from RateLimitError interface)
        self.retry_after = retry_after


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=message, error_code=ErrorCode.LLM_AUTHENTICATION_ERROR, **kwargs
        )


# Tool Exceptions


class ToolError(BaseError):
    """Base class for tool-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.TOOL_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        tool_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        # Ensure tool_name is in context
        if tool_name and context:
            context.tool_name = tool_name
        elif tool_name:
            from temper_ai.shared.core.context import ExecutionContext

            context = ExecutionContext(tool_name=tool_name)

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs,
        )


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""

    def __init__(self, message: str, tool_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            tool_name=tool_name,
            **kwargs,
        )


class ToolNotFoundError(ToolError):
    """Raised when a tool cannot be found."""

    def __init__(self, message: str, tool_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.TOOL_NOT_FOUND,
            tool_name=tool_name,
            **kwargs,
        )


class ToolRegistryError(ToolError):
    """Raised when tool registry operations fail."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=message, error_code=ErrorCode.TOOL_REGISTRY_ERROR, **kwargs
        )


# Agent Exceptions


class AgentError(BaseError):
    """Base class for agent-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.AGENT_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        agent_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        extra_data = kwargs.get("extra_data", {})
        if agent_name:
            extra_data["agent_name"] = agent_name
        kwargs["extra_data"] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs,
        )


class MaxIterationsError(AgentError):
    """Raised when the LLM tool-calling loop exceeds the max iterations limit."""

    def __init__(
        self,
        iterations: int,
        tool_calls: list | None = None,
        tokens: int = 0,
        cost: float = 0.0,
        last_output: str = "",
        last_reasoning: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.iterations = iterations
        self.tool_calls = tool_calls or []
        self.tokens = tokens
        self.cost = cost
        self.last_output = last_output
        self.last_reasoning = last_reasoning
        super().__init__(
            message=f"Max tool calling iterations reached ({iterations})",
            error_code=ErrorCode.AGENT_MAX_ITERATIONS,
            **kwargs,
        )


# Workflow Exceptions


class WorkflowError(BaseError):
    """Base class for workflow-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.WORKFLOW_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        workflow_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        extra_data = kwargs.get("extra_data", {})
        if workflow_name:
            extra_data["workflow_name"] = workflow_name
        kwargs["extra_data"] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs,
        )


class WorkflowStageError(WorkflowError):
    """Raised when a stage fails and the workflow's error policy requires halting.

    Attributes:
        stage_name: Name of the failed stage
    """

    def __init__(
        self,
        message: str,
        stage_name: str,
        error_code: ErrorCode = ErrorCode.WORKFLOW_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        self.stage_name = stage_name
        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs,
        )


# Safety Exceptions


class SecurityError(FrameworkException):
    """Raised when a security requirement or constraint is violated.

    A lightweight exception for security violations across modules
    (tools, auth, pricing, etc.).

    Inherits from FrameworkException so that a top-level
    ``except FrameworkException`` handler can catch security errors
    without needing a separate ``except Exception`` fallback.
    """

    pass
