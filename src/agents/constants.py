"""Constants for the agents module.

Centralized constants for HTTP configuration, LLM defaults, timeout settings,
rate limiting, and agent execution parameters.
"""

from src.constants.limits import DEFAULT_MAX_TOKENS as DEFAULT_MAX_TOKENS  # noqa: F401
from src.constants.limits import DEFAULT_TEMPERATURE as DEFAULT_TEMPERATURE  # noqa: F401

# ============================================================================
# HTTP Pool & Connection Limits
# ============================================================================

DEFAULT_MAX_HTTP_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_KEEPALIVE_EXPIRY_SECONDS = 30.0
DEFAULT_MAX_HTTP_CLIENTS = 50  # LRU eviction threshold for shared client pool
DEFAULT_MAX_CIRCUIT_BREAKERS = 100  # LRU eviction threshold for circuit breakers

# ============================================================================
# LLM Model Defaults
# ============================================================================

DEFAULT_TOP_P = 0.9
DEFAULT_TIMEOUT_SECONDS = 600  # 10 minutes for LLM calls
DEFAULT_RETRY_DELAY_SECONDS = 2.0
OLLAMA_DEFAULT_PORT = 11434

# ============================================================================
# Rate Limiting
# ============================================================================

RATE_LIMIT_CRITICAL_THRESHOLD_SECONDS = 3600  # 1 hour

# ============================================================================
# Agent Execution
# ============================================================================

MAX_TOOL_CALLS_PER_EXECUTION = 20
MAX_EXECUTION_TIME_SECONDS = 300  # 5 minutes
MAX_PROMPT_LENGTH = 32_000  # Maximum prompt length in characters
DEFAULT_CACHE_TTL_SECONDS = 3600  # 1 hour

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
MAX_ERROR_MESSAGE_LENGTH = 500

# ============================================================================
# Pool Sizing
# ============================================================================

CPU_MULTIPLIER = 2  # Multiplier for CPU count in pool sizing
CPU_OFFSET = 4  # Offset added to pool size calculation

# ============================================================================
# Cost Estimation
# ============================================================================

TOKENS_PER_MILLION = 1_000_000
MAX_REASONABLE_PRICE_PER_MILLION = 1000  # $1000 max per million tokens
DEFAULT_INPUT_TOKEN_RATIO = 0.6
DEFAULT_OUTPUT_TOKEN_RATIO = 0.4
