"""Constants for observability module.

Centralized constants to avoid magic numbers throughout the codebase.
"""

# Performance Monitoring
MAX_LATENCY_SAMPLES = 1000  # Maximum number of latency samples to keep in memory
MAX_SLOW_OPERATIONS = 100  # Maximum number of slow operations to track
DEFAULT_CLEANUP_INTERVAL = 1000  # Run cleanup every N records
DEFAULT_SLOW_THRESHOLD_MS = 1000.0  # Default threshold (1 second)
MS_PER_SECOND = 1000.0  # Milliseconds per second conversion factor

# Default operation thresholds (in milliseconds)
DEFAULT_THRESHOLDS_MS = {
    "llm_call": 5000.0,  # 5 seconds
    "tool_execution": 3000.0,  # 3 seconds
    "stage_execution": 10000.0,  # 10 seconds
    "agent_execution": 30000.0,  # 30 seconds
    "workflow_execution": 60000.0,  # 1 minute
}

# Buffer Configuration
DEFAULT_BUFFER_SIZE = 100  # Default number of records to buffer before flush
DEFAULT_BUFFER_TIMEOUT_SECONDS = 5.0  # Flush after N seconds even if buffer not full
MAX_RETRY_ATTEMPTS = 3  # Maximum number of retry attempts for failed operations
RETRY_DELAY_SECONDS = 1.0  # Delay between retry attempts

# ============================================================================
# Alerting Thresholds
# ============================================================================

DEFAULT_ALERT_COOLDOWN_SECONDS = 300  # 5 minutes between alerts
MAX_ALERT_HISTORY = 1000
DEFAULT_PERSISTED_ALERTS_LIMIT = 50  # Default limit for DB alert queries
DEFAULT_ERROR_RATE_ALERT_THRESHOLD = 0.1  # 10% error rate
DEFAULT_ERROR_SPIKE_THRESHOLD = 10  # Same error 10+ times triggers spike alert
DEFAULT_LATENCY_ALERT_MULTIPLIER = 2.0  # 2x normal latency

# ============================================================================
# Display & Formatting
# ============================================================================

DEFAULT_TRACE_DEPTH = 10  # Max trace depth for visualization
MAX_TRACE_DISPLAY_ITEMS = 50
DEFAULT_INDENT_SIZE = 2  # Spaces per indent level
SANITIZATION_MAX_LENGTH = 10000  # Max string length before truncation
SANITIZATION_REPLACEMENT = "***"

# ============================================================================
# Dead Letter Queue (DLQ)
# ============================================================================

DEFAULT_DLQ_MAX_SIZE = 10000
DEFAULT_DLQ_RETRY_INTERVAL = 60  # seconds
MAX_DLQ_RETRY_ATTEMPTS = 5

# ============================================================================
# Merit Score Service
# ============================================================================

DEFAULT_MERIT_DECAY_RATE = 0.95
DEFAULT_MERIT_WINDOW_DAYS = 30
MIN_OBSERVATIONS_FOR_MERIT = 5

# ============================================================================
# Decision Tracker
# ============================================================================

MAX_DECISION_HISTORY = 10000
DECISION_CONTEXT_MAX_LENGTH = 5000

# ============================================================================
# SQL Backend
# ============================================================================

DEFAULT_QUERY_LIMIT = 1000
DEFAULT_AGGREGATION_INTERVAL_SECONDS = 60

# ============================================================================
# Logging Separators
# ============================================================================

LOG_SEPARATOR_STATUS = " status="
LOG_MESSAGE_METRICS_CREATED = " metrics created for period "


# ============================================================================
# Lifecycle Events (pre-execution pipeline)
# ============================================================================

EVENT_CONFIG_LOADED = "config_loaded"
EVENT_LIFECYCLE_ADAPTED = "lifecycle_adapted"
EVENT_WORKFLOW_COMPILING = "workflow_compiling"
EVENT_WORKFLOW_COMPILED = "workflow_compiled"
EVENT_VALIDATION_PASSED = "validation_passed"
EVENT_VALIDATION_FAILED = "validation_failed"

# ============================================================================
# Database Field Names
# ============================================================================


class ObservabilityFields:
    """Standard field names for observability tracking and database operations."""

    # Execution hierarchy IDs
    WORKFLOW_ID = "workflow_id"
    STAGE_ID = "stage_id"
    AGENT_ID = "agent_id"
    CHECKPOINT_ID = "checkpoint_id"

    # Status tracking
    STATUS = "status"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    # Timing fields
    START_TIME = "start_time"
    END_TIME = "end_time"
    DURATION_SECONDS = "duration_seconds"

    # Metrics aggregation
    TOTAL_TOKENS = "total_tokens"
    TOTAL_COST_USD = "total_cost_usd"
    TOTAL_LLM_CALLS = "total_llm_calls"
    TOTAL_TOOL_CALLS = "total_tool_calls"

    # Agent/Stage data
    AGENT_NAME = "agent_name"
    STAGE_OUTPUTS = "stage_outputs"
    INPUT_DATA = "input_data"
    OUTPUT_DATA = "output_data"

    # Error tracking
    ERROR_MESSAGE = "error_message"
    ERROR_STACK_TRACE = "error_stack_trace"
    ERROR_FINGERPRINT = "error_fingerprint"

    # Configuration
    WORKFLOW_CONFIG = "workflow_config"
    WORKFLOW_VERSION = "workflow_version"
    OPTIMIZATION_TARGET = "optimization_target"
    PRODUCT_TYPE = "product_type"
