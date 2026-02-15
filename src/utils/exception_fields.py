"""Field name constants for exception metadata."""


class ExceptionFields:
    """Standard field names in exception extra_data dictionaries."""

    # Primary metadata container
    EXTRA_DATA = "extra_data"

    # Common exception fields
    AGENT_NAME = "agent_name"
    STAGE_ID = "stage_id"
    WORKFLOW_ID = "workflow_id"

    # LLM-specific
    PROVIDER = "provider"
    MODEL = "model"
    RETRY_AFTER = "retry_after"
    STATUS_CODE = "status_code"

    # Tool-specific
    TOOL_NAME = "tool_name"
    EXIT_CODE = "exit_code"
    COMMAND = "command"
