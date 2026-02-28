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
