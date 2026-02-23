"""Constants for the core module.

Centralized constants for circuit breaker configuration and metrics.
"""

# ============================================================================
# Circuit Breaker
# ============================================================================

DEFAULT_HALF_OPEN_SEMAPHORE = 1  # Max concurrent calls in half-open state
MAX_CIRCUIT_BREAKER_NAME_LENGTH = 100
MIN_FAILURE_THRESHOLD = 1
MAX_FAILURE_THRESHOLD = 1000
MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 86400  # 24 hours
MIN_SUCCESS_THRESHOLD = 1
MAX_SUCCESS_THRESHOLD = 100

# ============================================================================
# Circuit Breaker Field Names (Dictionary Keys)
# ============================================================================

FIELD_STATE = "state"
FIELD_FAILURE_COUNT = "failure_count"
FIELD_SUCCESS_COUNT = "success_count"
FIELD_LAST_FAILURE_TIME = "last_failure_time"
FIELD_CONFIG = "config"

# ============================================================================
# Error Message Fragments
# ============================================================================

ERROR_GOT_SEPARATOR = ", got "
