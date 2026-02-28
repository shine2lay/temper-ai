"""Field name constants for tool execution results."""


class ToolResultFields:
    """Standard field names in tool execution result dictionaries."""

    # Process execution fields
    EXIT_CODE = "exit_code"
    STDOUT = "stdout"
    STDERR = "stderr"
    COMMAND = "command"

    # Execution metadata
    DURATION_SECONDS = "duration_seconds"
    TIMEOUT = "timeout"

    # Error tracking
    ERROR = "error"
