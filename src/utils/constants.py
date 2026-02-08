"""Constants for the utils module.

Centralized constants for logging configuration, path safety,
and utility parameters.
"""

# ============================================================================
# Logging Configuration
# ============================================================================

DEFAULT_LOG_BACKUP_COUNT = 5
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_LOG_FORMAT_WIDTH = 80

# ============================================================================
# Path Safety
# ============================================================================

MAX_PATH_LENGTH = 4096  # Typical Linux PATH_MAX
MAX_COMPONENT_LENGTH = 255  # Typical NAME_MAX
