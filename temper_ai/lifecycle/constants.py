"""Shared constants for lifecycle module."""

# Profile sources
SOURCE_MANUAL = "manual"
SOURCE_LEARNED = "learned"
SOURCE_EXPERIMENT = "experiment"

# Profile statuses
PROFILE_STATUS_ENABLED = "enabled"
PROFILE_STATUS_DISABLED = "disabled"

# Adaptation defaults
DEFAULT_LIST_LIMIT = 100
DEFAULT_LOOKBACK_HOURS = 720  # 30 days
DEFAULT_DEGRADATION_WINDOW = 10
DEFAULT_DEGRADATION_THRESHOLD = 0.05  # 5% success rate drop

# Classifier defaults
DEFAULT_COMPLEXITY = 0.5
MIN_COMPLEXITY = 0.0
MAX_COMPLEXITY = 1.0

# Rule priority range
MIN_PRIORITY = 0
MAX_PRIORITY = 100

# Jinja2 condition truthy values
TRUTHY_VALUES = frozenset({"true", "1", "yes"})

# SQL result column indices for stage metrics query
COL_RUN_COUNT = 3

# Display constants
CONDITION_DISPLAY_WIDTH = 40
