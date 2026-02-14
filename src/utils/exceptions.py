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
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from src.core.context import ExecutionContext


def _sanitize_aws_keys(message: str) -> str:
    """Sanitize AWS API keys from message."""
    return re.sub(
        r'\b(AKIA|ASIA)[A-Z0-9]{16}\b',
        '[REDACTED-AWS-KEY]',
        message
    )


def _sanitize_api_keys(message: str) -> str:
    """Sanitize API keys from message."""
    # Pattern keys (sk-*, api-*, key-*, etc.)
    message = re.sub(
        r'\b(sk|api|key|secret)[-_][a-zA-Z0-9\-_]{3,}\b',
        '[REDACTED-API-KEY]',
        message,
        flags=re.IGNORECASE
    )
    # Assignment format (api_key=*, apiKey=*, etc.)
    message = re.sub(
        r'(api[_-]?key|apikey)\s*[:=]\s*["\']?[a-zA-Z0-9\-_]{10,}["\']?',
        r'\1=[REDACTED-API-KEY]',
        message,
        flags=re.IGNORECASE
    )
    return message


def _sanitize_jwt_tokens(message: str) -> str:
    """Sanitize JWT tokens from message."""
    # Bearer tokens
    message = re.sub(
        r'Bearer\s+[a-zA-Z0-9._-]+',
        'Bearer [REDACTED-TOKEN]',
        message
    )
    # Bare JWT tokens
    message = re.sub(
        r'\beyJ[a-zA-Z0-9._-]{20,}',
        '[REDACTED-JWT-TOKEN]',
        message
    )
    return message


def _sanitize_passwords(message: str) -> str:
    """Sanitize passwords from message."""
    return re.sub(
        r'(password|passwd|pwd|pass)\s*[:=]\s*["\']?[^\s"\']{3,}["\']?',
        r'\1=[REDACTED-PASSWORD]',
        message,
        flags=re.IGNORECASE
    )


def _sanitize_generic_tokens(message: str) -> str:
    """Sanitize generic tokens and auth headers from message."""
    return re.sub(
        r'(token|auth|authorization|x-api-key)\s*[:=]\s*["\']?[a-zA-Z0-9\-_]{10,}["\']?',
        r'\1=[REDACTED-TOKEN]',
        message,
        flags=re.IGNORECASE
    )


def _sanitize_connection_strings(message: str) -> str:
    """Sanitize database connection strings from message."""
    # Connection string credentials
    message = re.sub(
        r'(mysql|postgres|postgresql|mongodb|redis)://[^:]+:[^@]+@',
        r'\1://[REDACTED-CREDENTIALS]@',
        message,
        flags=re.IGNORECASE
    )
    # Query param passwords
    message = re.sub(
        r'[?&](password|pwd|pass|token|key|secret)=[^&\s]+',
        r'?\1=[REDACTED]',
        message,
        flags=re.IGNORECASE
    )
    return message


def sanitize_error_message(message: str) -> str:
    """Sanitize sensitive data from error messages.

    Redacts the following sensitive patterns:
    - API keys (sk-*, api-*, api_key=*, apiKey:*, etc.)
    - AWS keys (AKIA*, ASIA*)
    - JWT tokens (Bearer, eyJ*)
    - Passwords (password=*, password:*, pwd=*, etc.)
    - Generic tokens (token=*, auth=*, authorization=*, etc.)
    - Connection strings (mysql://, postgres://, mongodb://, redis://, etc.)

    Args:
        message: Error message that may contain sensitive data

    Returns:
        Sanitized message with sensitive data redacted

    Example:
        >>> sanitize_error_message("API key sk-test-123 failed")
        "API key [REDACTED-API-KEY] failed"

        >>> sanitize_error_message("Password='secret123' invalid")
        "Password=[REDACTED-PASSWORD] invalid"
    """
    if not message:
        return message

    # Apply each sanitization helper
    message = _sanitize_aws_keys(message)
    message = _sanitize_api_keys(message)
    message = _sanitize_jwt_tokens(message)
    message = _sanitize_passwords(message)
    message = _sanitize_generic_tokens(message)
    message = _sanitize_connection_strings(message)

    return message


class ErrorCode(str, Enum):
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
    # Configuration errors (1000-1099)
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_PARSE_ERROR = "CONFIG_PARSE_ERROR"
    CONFIG_VALIDATION_ERROR = "CONFIG_VALIDATION_ERROR"

    # LLM errors (1100-1199)
    LLM_CONNECTION_ERROR = "LLM_CONNECTION_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"
    LLM_AUTHENTICATION_ERROR = "LLM_AUTHENTICATION_ERROR"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    LLM_MODEL_NOT_FOUND = "LLM_MODEL_NOT_FOUND"

    # Tool errors (1200-1299)
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    TOOL_VALIDATION_ERROR = "TOOL_VALIDATION_ERROR"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_REGISTRY_ERROR = "TOOL_REGISTRY_ERROR"

    # Agent errors (1300-1399)
    AGENT_INITIALIZATION_ERROR = "AGENT_INITIALIZATION_ERROR"
    AGENT_EXECUTION_ERROR = "AGENT_EXECUTION_ERROR"
    AGENT_TIMEOUT = "AGENT_TIMEOUT"
    AGENT_INVALID_OUTPUT = "AGENT_INVALID_OUTPUT"

    # Workflow errors (1400-1499)
    WORKFLOW_COMPILATION_ERROR = "WORKFLOW_COMPILATION_ERROR"
    WORKFLOW_EXECUTION_ERROR = "WORKFLOW_EXECUTION_ERROR"
    WORKFLOW_STAGE_ERROR = "WORKFLOW_STAGE_ERROR"
    WORKFLOW_TIMEOUT = "WORKFLOW_TIMEOUT"

    # Safety errors (1500-1599)
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    SAFETY_POLICY_ERROR = "SAFETY_POLICY_ERROR"
    SAFETY_ACTION_BLOCKED = "SAFETY_ACTION_BLOCKED"

    # Validation errors (1600-1699)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    VALIDATION_TYPE_ERROR = "VALIDATION_TYPE_ERROR"
    VALIDATION_RANGE_ERROR = "VALIDATION_RANGE_ERROR"

    # System errors (1700-1799)
    SYSTEM_ERROR = "SYSTEM_ERROR"
    SYSTEM_TIMEOUT = "SYSTEM_TIMEOUT"
    SYSTEM_RESOURCE_ERROR = "SYSTEM_RESOURCE_ERROR"

    # Unknown/Generic (9999)
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class FrameworkException(Exception):  # noqa: N818 — intentional: base exception, not a specific error
    """Root exception for the entire meta-autonomous framework.

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
        cause: Optional[Exception] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        # Lazy import to avoid circular dependency
        if context is None:
            from src.core.context import ExecutionContext
            context = ExecutionContext()
        self.context = context
        self.cause = cause
        self.timestamp = datetime.now(timezone.utc)
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

    def to_dict(self) -> Dict[str, Any]:
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
            "traceback": sanitize_error_message(traceback.format_exc()) if self.cause else None
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
        cause: Optional[Exception] = None,
        config_path: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        extra_data = kwargs.get('extra_data', {})
        if config_path:
            extra_data['config_path'] = config_path

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            extra_data=extra_data
        )


class ConfigNotFoundError(ConfigurationError):
    """Raised when a configuration file cannot be found."""

    def __init__(self, message: str, config_path: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.CONFIG_NOT_FOUND,
            config_path=config_path,
            **kwargs
        )


class ConfigValidationError(ConfigurationError):
    """Raised when configuration fails validation."""

    def __init__(self, message: str, validation_errors: Optional[list[Any]] = None, **kwargs: Any) -> None:
        extra_data = kwargs.get('extra_data', {})
        if validation_errors:
            extra_data['validation_errors'] = validation_errors
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=ErrorCode.CONFIG_VALIDATION_ERROR,
            **kwargs
        )


# LLM Exceptions

class LLMError(BaseError):
    """Base class for LLM provider errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.LLM_CONNECTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Optional[Exception] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        extra_data = kwargs.get('extra_data', {})
        if provider:
            extra_data['provider'] = provider
        if model:
            extra_data['model'] = model
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
        )


class LLMTimeoutError(LLMError):
    """Raised when LLM call times out."""

    def __init__(self, message: str, timeout_seconds: Optional[int] = None, **kwargs: Any) -> None:
        extra_data = kwargs.get('extra_data', {})
        if timeout_seconds:
            extra_data['timeout_seconds'] = timeout_seconds
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=ErrorCode.LLM_TIMEOUT,
            **kwargs
        )


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

    def __init__(self, message: str, retry_after: Optional[int] = None) -> None:
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

    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs: Any) -> None:
        extra_data = kwargs.get('extra_data', {})
        if retry_after:
            extra_data['retry_after'] = retry_after
        kwargs['extra_data'] = extra_data

        # Initialize LLMError (which handles BaseError and FrameworkException)
        LLMError.__init__(
            self,
            message=message,
            error_code=ErrorCode.LLM_RATE_LIMIT,
            **kwargs
        )
        # Store retry_after on self (from RateLimitError interface)
        self.retry_after = retry_after


class LLMAuthenticationError(LLMError):
    """Raised when authentication fails."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.LLM_AUTHENTICATION_ERROR,
            **kwargs
        )


# Tool Exceptions

class ToolError(BaseError):
    """Base class for tool-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.TOOL_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Optional[Exception] = None,
        tool_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        # Ensure tool_name is in context
        if tool_name and context:
            context.tool_name = tool_name
        elif tool_name:
            from src.core.context import ExecutionContext
            context = ExecutionContext(tool_name=tool_name)

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
        )


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""

    def __init__(self, message: str, tool_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.TOOL_EXECUTION_ERROR,
            tool_name=tool_name,
            **kwargs
        )


class ToolNotFoundError(ToolError):
    """Raised when a tool cannot be found."""

    def __init__(self, message: str, tool_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.TOOL_NOT_FOUND,
            tool_name=tool_name,
            **kwargs
        )


class ToolRegistryError(ToolError):
    """Raised when tool registry operations fail."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.TOOL_REGISTRY_ERROR,
            **kwargs
        )


# Agent Exceptions

class AgentError(BaseError):
    """Base class for agent-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.AGENT_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Optional[Exception] = None,
        agent_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        extra_data = kwargs.get('extra_data', {})
        if agent_name:
            extra_data['agent_name'] = agent_name
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
        )


# Workflow Exceptions

class WorkflowError(BaseError):
    """Base class for workflow-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.WORKFLOW_EXECUTION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Optional[Exception] = None,
        workflow_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        extra_data = kwargs.get('extra_data', {})
        if workflow_name:
            extra_data['workflow_name'] = workflow_name
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
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
        cause: Optional[Exception] = None,
        **kwargs: Any
    ) -> None:
        self.stage_name = stage_name
        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
        )


# Safety Exceptions

class SecurityError(FrameworkException):
    """Raised when a security requirement or constraint is violated.

    A lightweight exception for security violations across modules
    (tools, auth, pricing, etc.). Unlike SafetyError, this does not
    require ExecutionContext or ErrorCode.

    Inherits from FrameworkException so that a top-level
    ``except FrameworkException`` handler can catch security errors
    without needing a separate ``except Exception`` fallback.
    """
    pass


class SafetyError(BaseError):
    """Base class for safety-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.SAFETY_VIOLATION,
        context: Optional["ExecutionContext"] = None,
        cause: Optional[Exception] = None,
        policy_name: Optional[str] = None,
        severity: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        extra_data = kwargs.get('extra_data', {})
        if policy_name:
            extra_data['policy_name'] = policy_name
        if severity:
            extra_data['severity'] = severity
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
        )


# Validation Exceptions

class FrameworkValidationError(BaseError):
    """Base class for validation errors.

    Note: Previously named ``ValidationError``. Renamed to avoid collision
    with ``pydantic.ValidationError`` which is used extensively across
    the codebase for schema validation.  The old name is available as a
    backward-compatible alias that emits a ``DeprecationWarning``.
    """

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        context: Optional["ExecutionContext"] = None,
        cause: Optional[Exception] = None,
        field_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        extra_data = kwargs.get('extra_data', {})
        if field_name:
            extra_data['field_name'] = field_name
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=error_code,
            context=context,
            cause=cause,
            **kwargs
        )


# Backward-compat alias (deprecated)
class ValidationError(FrameworkValidationError):
    """Backward-compatible ValidationError alias.

    DEPRECATED: Use FrameworkValidationError directly.
    """
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        import warnings
        warnings.warn(
            "ValidationError is deprecated. Use FrameworkValidationError instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(*args, **kwargs)


# Utility Functions

def wrap_exception(
    exc: Exception,
    message: str,
    error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
    context: Optional["ExecutionContext"] = None
) -> BaseError:
    """Wrap a standard exception in a BaseError with context.

    Useful for converting third-party exceptions into our error format.

    Args:
        exc: Original exception
        message: Descriptive message for the error
        error_code: ErrorCode for categorization
        context: ExecutionContext for tracking

    Returns:
        BaseError wrapping the original exception

    Example:
        >>> try:
        ...     some_library_call()
        ... except ValueError as e:
        ...     raise wrap_exception(
        ...         e,
        ...         "Invalid configuration value",
        ...         ErrorCode.CONFIG_INVALID,
        ...         ExecutionContext(workflow_id="wf-123")
        ...     )
    """
    return BaseError(
        message=message,
        error_code=error_code,
        context=context,
        cause=exc
    )


def get_error_info(exc: Exception) -> Dict[str, Any]:
    """Extract error information from any exception.

    If the exception is a BaseError, returns full context.
    Otherwise, returns basic information.

    Args:
        exc: Any exception

    Returns:
        Dictionary with error information

    Example:
        >>> try:
        ...     raise ValueError("Bad value")
        ... except Exception as e:
        ...     info = get_error_info(e)
        ...     print(info['error_type'])  # "ValueError"
    """
    if isinstance(exc, BaseError):
        return exc.to_dict()

    return {
        "error_type": type(exc).__name__,
        "message": str(exc),
        "error_code": ErrorCode.UNKNOWN_ERROR.value,
        "context": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "traceback": traceback.format_exc()
    }
