"""Constants for cache module.

Centralized constants to avoid magic numbers throughout the codebase.
"""
from src.constants.durations import TTL_LONG
from src.constants.limits import DEFAULT_QUEUE_SIZE

# LLM Cache Configuration
DEFAULT_CACHE_SIZE = DEFAULT_QUEUE_SIZE  # Default maximum number of cached LLM responses
DEFAULT_TTL_SECONDS = TTL_LONG  # Default TTL (1 hour)

# Redis Configuration
DEFAULT_REDIS_PORT = 6379
DEFAULT_REDIS_DB = 0
DEFAULT_REDIS_SOCKET_TIMEOUT = 5  # seconds

# Hit Ratio Thresholds
GOOD_HIT_RATIO = 0.7  # 70% hit ratio considered good
POOR_HIT_RATIO = 0.3  # Below 30% needs investigation
