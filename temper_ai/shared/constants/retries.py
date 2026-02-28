"""Retry and backoff constants for resilient operations.

These constants standardize retry behavior across the framework.
"""

# Default retry attempts
DEFAULT_MAX_RETRIES = 3
MIN_RETRY_ATTEMPTS = 1
MAX_RETRY_ATTEMPTS = 10
EXTENDED_MAX_RETRIES = 5

# Backoff timing (seconds)
DEFAULT_RETRY_BACKOFF_SECONDS = 5
MIN_BACKOFF_SECONDS = 1
SHORT_BACKOFF_SECONDS = 2
MEDIUM_BACKOFF_SECONDS = 5
LONG_BACKOFF_SECONDS = 10
EXTENDED_BACKOFF_SECONDS = 30

# Backoff multipliers
DEFAULT_BACKOFF_MULTIPLIER = 2.0
EXPONENTIAL_BACKOFF_BASE = 2
LINEAR_BACKOFF_MULTIPLIER = 1.0

# Jitter ranges for retry randomization
RETRY_JITTER_MIN = 0.5
RETRY_JITTER_MAX = 1.0
RETRY_JITTER_RANGE = 0.5
