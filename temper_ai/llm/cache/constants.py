"""Constants for cache module.

Centralized constants to avoid magic numbers throughout the codebase.
"""

from temper_ai.shared.constants.durations import TTL_LONG
from temper_ai.shared.constants.limits import DEFAULT_QUEUE_SIZE

# LLM Cache Configuration
DEFAULT_CACHE_SIZE = (
    DEFAULT_QUEUE_SIZE  # Default maximum number of cached LLM responses
)
DEFAULT_TTL_SECONDS = TTL_LONG  # Default TTL (1 hour)

# Hit Ratio Thresholds
GOOD_HIT_RATIO = 0.7  # 70% hit ratio considered good
POOR_HIT_RATIO = 0.3  # Below 30% needs investigation

# ============================================================================
# LLM Cache Field Names (Dictionary Keys)
# ============================================================================

FIELD_MODEL = "model"
FIELD_PROMPT = "prompt"
FIELD_TEMPERATURE = "temperature"
FIELD_MAX_TOKENS = "max_tokens"
FIELD_USER_ID = "user_id"
FIELD_TENANT_ID = "tenant_id"
FIELD_SESSION_ID = "session_id"

# ============================================================================
# Display Strings
# ============================================================================

DISPLAY_ELLIPSIS = "..."
