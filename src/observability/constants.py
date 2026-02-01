"""Constants for observability module.

Centralized constants to avoid magic numbers throughout the codebase.
"""

# Performance Monitoring
MAX_LATENCY_SAMPLES = 1000  # Maximum number of latency samples to keep in memory
MAX_SLOW_OPERATIONS = 100   # Maximum number of slow operations to track
DEFAULT_CLEANUP_INTERVAL = 1000  # Run cleanup every N records
DEFAULT_SLOW_THRESHOLD_MS = 1000.0  # Default threshold (1 second)
MS_PER_SECOND = 1000.0  # Milliseconds per second conversion factor

# Default operation thresholds (in milliseconds)
DEFAULT_THRESHOLDS_MS = {
    "llm_call": 5000.0,           # 5 seconds
    "tool_execution": 3000.0,     # 3 seconds
    "stage_execution": 10000.0,   # 10 seconds
    "agent_execution": 30000.0,   # 30 seconds
    "workflow_execution": 60000.0, # 1 minute
}

# Buffer Configuration
DEFAULT_BUFFER_SIZE = 100  # Default number of records to buffer before flush
DEFAULT_BUFFER_TIMEOUT_SECONDS = 5.0  # Flush after N seconds even if buffer not full
MAX_RETRY_ATTEMPTS = 3  # Maximum number of retry attempts for failed operations
RETRY_DELAY_SECONDS = 1.0  # Delay between retry attempts
