"""Constants for the LLM subsystem.

HTTP configuration, model defaults, streaming sentinels, cost estimation,
pricing, error messages, and pool sizing constants used by LLM providers
and the LLM service layer.
"""

from src.shared.constants.limits import DEFAULT_MAX_TOKENS as DEFAULT_MAX_TOKENS  # noqa: F401
from src.shared.constants.limits import DEFAULT_TEMPERATURE as DEFAULT_TEMPERATURE  # noqa: F401

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
# Error Messages
# ============================================================================

ERROR_MSG_RATE_LIMIT_EXCEEDED = "LLM rate limit exceeded"
ERROR_MSG_VALID_PROVIDERS_SUFFIX = "'. Valid providers: "
ERROR_MSG_TOOL_PREFIX = "Tool '"
MAX_ERROR_MESSAGE_LENGTH = 500

# ============================================================================
# Streaming & API Sentinels
# ============================================================================

SSE_STREAM_DONE_MARKER = "[DONE]"

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

# ============================================================================
# Pricing & Fallbacks
# ============================================================================

PRICING_DEFAULT_KEY = "_default"
FALLBACK_UNKNOWN_VALUE = "unknown"

# ============================================================================
# Regex Patterns
# ============================================================================

REGEX_XML_TAG_CLOSING = ">(.*?)</"
