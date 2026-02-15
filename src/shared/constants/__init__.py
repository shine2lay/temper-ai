"""Common constants used across the framework."""

# Probabilities and weights
# Time and durations
from src.shared.constants.durations import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_SESSION_TTL_SECONDS,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
)

# Limits and thresholds
from src.shared.constants.limits import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_ITEMS,
    DEFAULT_POOL_SIZE,
)
from src.shared.constants.probabilities import (
    PROB_CRITICAL,
    PROB_HIGH,
    PROB_LOW,
    PROB_MEDIUM,
    PROB_MINIMAL,
    PROB_NEAR_CERTAIN,
    PROB_VERY_HIGH,
    PROB_VERY_LOW,
    WEIGHT_LARGE,
    WEIGHT_MEDIUM,
    WEIGHT_SMALL,
)

# Retries and backoff
from src.shared.constants.retries import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
)

# Sizes and buffers
from src.shared.constants.sizes import (
    BYTES_PER_GB,
    BYTES_PER_KB,
    BYTES_PER_MB,
)

__all__ = [
    # Probabilities
    "PROB_MINIMAL",
    "PROB_VERY_LOW",
    "PROB_LOW",
    "PROB_MEDIUM",
    "PROB_HIGH",
    "PROB_VERY_HIGH",
    "PROB_CRITICAL",
    "PROB_NEAR_CERTAIN",
    "WEIGHT_SMALL",
    "WEIGHT_MEDIUM",
    "WEIGHT_LARGE",
    # Durations
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_SESSION_TTL_SECONDS",
    # Sizes
    "BYTES_PER_KB",
    "BYTES_PER_MB",
    "BYTES_PER_GB",
    # Retries
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_BACKOFF_MULTIPLIER",
    # Limits
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_POOL_SIZE",
]
