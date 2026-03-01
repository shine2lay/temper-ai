"""Safety module constants.

Shared constants used across safety components to ensure consistency.
"""

from temper_ai.shared.constants.durations import SECONDS_PER_DAY

# ============================================================================
# Policy Priorities (higher = runs first)
# ============================================================================

RATE_LIMIT_PRIORITY = 85  # Prevent resource exhaustion before other policies
SECRET_DETECTION_PRIORITY = 95  # High priority for secrets

# ============================================================================
# Validation Limits
# ============================================================================

DEFAULT_MAX_ITEMS = 1000  # Default max items in validated lists
DEFAULT_MAX_ITEM_LENGTH = 1000  # Default max string length in lists
DEFAULT_MAX_STRING_LENGTH = 1000  # Default max string length for validation
MAX_VALIDATION_TIME_SECONDS = SECONDS_PER_DAY  # 86400 = 24 hours

# ============================================================================
# Blast Radius Limits
# ============================================================================

DEFAULT_MAX_FILES = 10  # Max files per operation
DEFAULT_MAX_LINES_PER_FILE = 500
DEFAULT_MAX_TOTAL_LINES = 2000
DEFAULT_MAX_ENTITIES = 100
DEFAULT_MAX_OPS_PER_MINUTE = 20

# Blast radius validation bounds
MAX_FILES_UPPER_BOUND = 10000
MAX_LINES_UPPER_BOUND = 1000000
MAX_TOTAL_LINES_UPPER_BOUND = 10000000
MAX_ENTITIES_UPPER_BOUND = 100000
MAX_OPS_UPPER_BOUND = 1000

# ============================================================================
# Entropy Thresholds (Shannon entropy, 0.0 to 8.0 bits per char)
# ============================================================================

MAX_SHANNON_ENTROPY = 8.0
DEFAULT_ENTROPY_THRESHOLD = 4.5  # High severity secret threshold
DEFAULT_ENTROPY_THRESHOLD_GENERIC = 3.5  # Generic pattern threshold
MIN_ENTROPY_VALUE = 0.0

# ============================================================================
# Secret Detection
# ============================================================================

MAX_EXCLUDED_PATH_LENGTH = 500
MAX_EXCLUDED_PATHS = 1000
SECRET_DETECTION_SESSION_KEY_SIZE = 32  # bytes

# ============================================================================
# Approval Workflow
# ============================================================================

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour

# ============================================================================
# Violation Dictionary Keys
# ============================================================================

VIOLATION_MESSAGE = "message"
VIOLATION_SEVERITY = "severity"
VIOLATION_PATTERN = "pattern"

# ============================================================================
# Context/Action Dictionary Keys
# ============================================================================

ACTION_TYPE_KEY = "action_type"
AGENT_ID_KEY = "agent_id"
WORKFLOW_ID_KEY = "workflow_id"
STAGE_ID_KEY = "stage_id"
POLICY_KEY = "policy"

# ============================================================================
# Policy Execution Keys
# ============================================================================

MODE_KEY = "mode"
REASON_KEY = "reason"
FAIL_OPEN_KEY = "fail_open"
NO_POLICIES_REGISTERED_KEY = "no_policies_registered"
CACHE_HITS_KEY = "cache_hits"
POLICIES_CHECKED_KEY = "policies_checked"
SHORT_CIRCUIT_KEY = "short_circuit"

# ============================================================================
# Configuration Keys
# ============================================================================

# Rate limiting config keys
MAX_TOKENS_KEY = "max_tokens"
REFILL_RATE_KEY = "refill_rate"
RATE_LIMITS_KEY = "rate_limits"
GLOBAL_LIMITS_KEY = "global_limits"
FILL_PERCENTAGE_KEY = "fill_percentage"

# Action type keys for rate limiting
ACTION_TYPE_COMMIT = "commit"
ACTION_TYPE_DEPLOY = "deploy"
ACTION_TYPE_TOOL_CALL = "tool_call"
ACTION_TYPE_LLM_CALL = "llm_call"
ACTION_TYPE_API_CALL = "api_call"

# Scope keys
SCOPE_GLOBAL = "global"

# Secret detection config keys
ENTROPY_THRESHOLD_KEY = "entropy_threshold"
ENTROPY_THRESHOLD_GENERIC_KEY = "entropy_threshold_generic"
ALLOW_TEST_SECRETS_KEY = "allow_test_secrets"

# File access config keys
PATHS_KEY = "paths"

# Forbidden operations config keys
CATEGORY_KEY = "category"
REGEX_KEY = "regex"
COMMAND_KEY = "command"
ARGS_KEY = "args"
BASH_KEY = "bash"

# Config change policy keys
MODEL_KEY = "model"
OLD_MODEL_KEY = "old_model"
NEW_MODEL_KEY = "new_model"
FIELD_KEY = "field"

# Resource limit keys
PERCENT_KEY = "percent"

# Rollback keys
STRATEGY_PREFIX = "strategy_"
EXISTED_SUFFIX = "_existed"

# ============================================================================
# Error Message Fragments
# ============================================================================

# Validation error fragments
ERROR_MUST_BE_NUMBER = " must be a number, got "
ERROR_MUST_BE_GTE = " must be >= "
ERROR_MUST_BE_LTE = " must be <= "
ERROR_CANNOT_BE_EMPTY = " cannot be empty"
ERROR_GOT_PREFIX = ", got "
ERROR_CHARS_GOT = " characters, got "
ERROR_ITEMS_GOT = " items, got "

# File/path error fragments
PATH_KEY = "path"
VIOLATION_KEY = "violation"

# Blast radius separator
BLAST_RADIUS_SEPARATOR = " > "

# ============================================================================
# Format Strings
# ============================================================================

FORMAT_ONE_DECIMAL = ".1f"

# ============================================================================
# Environment/Mode Values
# ============================================================================

ENV_DEVELOPMENT = "development"
ENV_KEY = "environments"

# ============================================================================
# Pattern Keys
# ============================================================================

CUSTOM_FORBIDDEN_PATTERNS_PREFIX = "custom_forbidden_patterns['"
