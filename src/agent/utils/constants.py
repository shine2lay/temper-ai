"""Constants for the agents module.

Agent execution parameters, confidence scoring, preview/truncation,
pre-command execution, and agent type constants.

LLM-specific constants (HTTP, model defaults, streaming, cost, pricing)
live in ``src.llm.constants``.

Cross-layer constants (used by storage schemas) are canonical in
``src.shared.constants`` and re-exported here for backward compatibility.
"""

from src.shared.constants.limits import DEFAULT_MAX_TOKENS as DEFAULT_MAX_TOKENS  # noqa: F401
from src.shared.constants.limits import DEFAULT_TEMPERATURE as DEFAULT_TEMPERATURE  # noqa: F401
from src.shared.constants.agent_defaults import (  # noqa: F401
    DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS,
    MAX_EXECUTION_TIME_SECONDS,
    MAX_PROMPT_LENGTH,
    MAX_TOOL_CALLS_PER_EXECUTION,
    PRE_COMMAND_DEFAULT_TIMEOUT,
    PRE_COMMAND_MAX_TIMEOUT,
)

# ============================================================================
# Confidence Scoring
# ============================================================================

BASE_CONFIDENCE = 1.0
REASONING_BONUS = 0.1
TOOL_FAILURE_MAJOR_PENALTY = 0.2
TOOL_FAILURE_MINOR_PENALTY = 0.1
MIN_OUTPUT_LENGTH = 10  # Minimum output length for confidence
MIN_REASONING_LENGTH = 20  # Minimum reasoning length for bonus

# ============================================================================
# Text Preview & Truncation
# ============================================================================

PROMPT_PREVIEW_LENGTH = 200
OUTPUT_PREVIEW_LENGTH = 150

# ============================================================================
# Pre-Command Execution (additional constants)
# ============================================================================

PRE_COMMAND_MAX_OUTPUT_CHARS = 2000

# ============================================================================
# Environment Variables
# ============================================================================

ENV_VAR_PATH = "PATH"
ENV_VAR_VIRTUAL_ENV = "VIRTUAL_ENV"

# ============================================================================
# Agent Types
# ============================================================================

AGENT_TYPE_STANDARD = "standard"
