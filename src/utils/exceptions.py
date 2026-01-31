"""Enhanced exception classes with execution context and error codes.

Provides base exception classes that include:
- Execution context (workflow_id, stage_id, agent_id)
- Error codes for programmatic handling
- Stack traces and debugging info
- Structured error messages
"""
from typing import Optional, Dict, Any
from enum import Enum
import traceback
from datetime import datetime, timezone


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


class ExecutionContext:
    """Execution context for error tracking.

    Captures information about where an error occurred in the execution flow.

    Attributes:
        workflow_id: ID of the workflow being executed
        stage_id: ID of the current stage
        agent_id: ID of the current agent
        tool_name: Name of the tool being executed
        metadata: Additional contextual information
    """

    def __init__(
        self,
        workflow_id: Optional[str] = None,
        stage_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.workflow_id = workflow_id
        self.stage_id = stage_id
        self.agent_id = agent_id
        self.tool_name = tool_name
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "stage_id": self.stage_id,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "metadata": self.metadata
        }

    def __repr__(self) -> str:
        parts = []
        if self.workflow_id:
            parts.append(f"workflow={self.workflow_id}")
        if self.stage_id:
            parts.append(f"stage={self.stage_id}")
        if self.agent_id:
            parts.append(f"agent={self.agent_id}")
        if self.tool_name:
            parts.append(f"tool={self.tool_name}")
        return f"ExecutionContext({', '.join(parts)})"


class BaseError(Exception):
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
        context: Optional[ExecutionContext] = None,
        cause: Optional[Exception] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.context = context or ExecutionContext()
        self.cause = cause
        self.timestamp = datetime.now(timezone.utc)
        self.extra_data = extra_data or {}

        # Build detailed message
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        """Build detailed error message with context."""
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
            parts.append(f"Caused by: {type(self.cause).__name__}: {str(self.cause)}")

        return " | ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code.value,
            "context": self.context.to_dict(),
            "timestamp": self.timestamp.isoformat(),
            "cause": str(self.cause) if self.cause else None,
            "extra_data": self.extra_data,
            "traceback": traceback.format_exc() if self.cause else None
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.error_code.value}, message='{self.message}', context={self.context})"


# Configuration Exceptions

class ConfigurationError(BaseError):
    """Base class for configuration-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.CONFIG_INVALID,
        context: Optional[ExecutionContext] = None,
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
        context: Optional[ExecutionContext] = None,
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


class LLMRateLimitError(LLMError):
    """Raised when rate limited by LLM provider."""

    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs: Any) -> None:
        extra_data = kwargs.get('extra_data', {})
        if retry_after:
            extra_data['retry_after'] = retry_after
        kwargs['extra_data'] = extra_data

        super().__init__(
            message=message,
            error_code=ErrorCode.LLM_RATE_LIMIT,
            **kwargs
        )


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
        context: Optional[ExecutionContext] = None,
        cause: Optional[Exception] = None,
        tool_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        # Ensure tool_name is in context
        if tool_name and context:
            context.tool_name = tool_name
        elif tool_name:
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
        context: Optional[ExecutionContext] = None,
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
        context: Optional[ExecutionContext] = None,
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


# Safety Exceptions

class SafetyError(BaseError):
    """Base class for safety-related errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.SAFETY_VIOLATION,
        context: Optional[ExecutionContext] = None,
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

class ValidationError(BaseError):
    """Base class for validation errors."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.VALIDATION_ERROR,
        context: Optional[ExecutionContext] = None,
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


# Utility Functions

def wrap_exception(
    exc: Exception,
    message: str,
    error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
    context: Optional[ExecutionContext] = None
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
