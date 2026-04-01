"""Base exception and shared utilities for error handling.

Two ideas ported from main codebase (temper_ai/shared/utils/exceptions.py):
1. ErrorCode enum for programmatic error handling in API responses
2. Secret sanitization to prevent API key leakage in error messages

Module-specific exceptions inherit from TemperError but live in their
own modules:
  - llm/exceptions.py:      LLMError, PromptBudgetError
  - tools/exceptions.py:    ToolError
  - agent/exceptions.py:    AgentError
  - safety/exceptions.py:   SafetyError, BudgetExceededError
  - workflow/exceptions.py: WorkflowError
  - config/exceptions.py:   ConfigError
  - memory/exceptions.py:   MemoryError
"""

import re
from enum import StrEnum


class ErrorCode(StrEnum):
    """Programmatic error codes for API responses and logging."""

    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_VALIDATION = "CONFIG_VALIDATION"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_AUTH = "LLM_AUTH"
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    AGENT_MAX_ITERATIONS = "AGENT_MAX_ITERATIONS"
    AGENT_INPUT_MISSING = "AGENT_INPUT_MISSING"
    WORKFLOW_STAGE_FAILED = "WORKFLOW_STAGE_FAILED"
    SAFETY_POLICY_DENIED = "SAFETY_POLICY_DENIED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PROMPT_BUDGET = "PROMPT_BUDGET"
    MEMORY_ERROR = "MEMORY_ERROR"


# Patterns that look like API keys / secrets — stripped from error messages
_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI keys
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}"),  # Anthropic keys
    re.compile(r"AIza[a-zA-Z0-9_-]{35}"),  # Google API keys
    re.compile(r"[a-f0-9]{32,}"),  # Generic hex tokens (32+ chars)
]


def sanitize_message(msg: str) -> str:
    """Remove potential secrets from error messages."""
    for pattern in _SECRET_PATTERNS:
        msg = pattern.sub("[REDACTED]", msg)
    return msg


class TemperError(Exception):
    """Base exception for all Temper errors. All module exceptions inherit from this."""

    def __init__(
        self,
        message: str,
        code: ErrorCode | None = None,
        cause: Exception | None = None,
    ):
        self.message = sanitize_message(message)
        self.code = code
        self.cause = cause
        super().__init__(self.message)
