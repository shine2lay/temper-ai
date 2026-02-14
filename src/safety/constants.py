"""Safety module constants.

Shared constants used across safety components to ensure consistency.
"""

from src.constants.durations import SECONDS_PER_DAY

# ============================================================================
# Policy Priorities (higher = runs first)
# ============================================================================

RATE_LIMIT_PRIORITY = 85  # Prevent resource exhaustion before other policies
SECRET_DETECTION_PRIORITY = 95  # High priority for secrets
FORBIDDEN_OPS_PRIORITY = 90
FILE_ACCESS_PRIORITY = 80
BLAST_RADIUS_PRIORITY = 70
CONFIG_CHANGE_PRIORITY = 60

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
# Token Bucket / Rate Limiting
# ============================================================================

DEFAULT_REFILL_PERIOD = 1.0  # seconds
MAX_TOKEN_BUCKET_CAPACITY = 100000

# ============================================================================
# Approval Workflow
# ============================================================================

DEFAULT_APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour
DEFAULT_REQUIRED_APPROVERS = 1
MAX_APPROVAL_HISTORY = 1000

# ============================================================================
# File Access
# ============================================================================

DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
DEFAULT_MAX_PATH_DEPTH = 20

# ============================================================================
# Rollback
# ============================================================================

MAX_ROLLBACK_HISTORY = 100
ROLLBACK_COOLDOWN_SECONDS = 60

# ============================================================================
# Violation Dictionary Keys
# ============================================================================

VIOLATION_MESSAGE = "message"
VIOLATION_SEVERITY = "severity"
VIOLATION_PATTERN = "pattern"
