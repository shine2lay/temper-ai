"""Constants for the agents module.

Agent execution parameters, confidence scoring, preview/truncation,
pre-command execution, and agent type constants.

LLM-specific constants (HTTP, model defaults, streaming, cost, pricing)
live in ``src.llm.constants``.
"""

from src.constants.limits import DEFAULT_MAX_TOKENS as DEFAULT_MAX_TOKENS  # noqa: F401
from src.constants.limits import DEFAULT_TEMPERATURE as DEFAULT_TEMPERATURE  # noqa: F401

# ============================================================================
# Agent Execution
# ============================================================================

MAX_TOOL_CALLS_PER_EXECUTION = 20
MAX_EXECUTION_TIME_SECONDS = 300  # 5 minutes
MAX_PROMPT_LENGTH = 32_000  # Maximum prompt length in characters
DEFAULT_CACHE_TTL_SECONDS = 3600  # 1 hour
DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS = 8000  # Max chars for auto-injected dialogue context

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
# Pre-Command Execution
# ============================================================================

PRE_COMMAND_DEFAULT_TIMEOUT = 60
PRE_COMMAND_MAX_TIMEOUT = 300
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
