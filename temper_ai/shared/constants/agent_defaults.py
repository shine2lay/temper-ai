"""Agent execution default constants shared across agent and storage modules.

These constants were originally in ``temper_ai.agent.utils.constants`` but are
needed by ``temper_ai.storage.schemas.agent_config`` for schema defaults.  Moving
them here avoids the infrastructure→business layer violation.
"""

# Agent Execution
MAX_TOOL_CALLS_PER_EXECUTION = 20
MAX_EXECUTION_TIME_SECONDS = 300  # 5 minutes
MAX_PROMPT_LENGTH = 32_000  # Maximum prompt length in characters
DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS = 8000  # Max chars for auto-injected dialogue context

# Pre-Command Execution
PRE_COMMAND_DEFAULT_TIMEOUT = 60
PRE_COMMAND_MAX_TIMEOUT = 300
