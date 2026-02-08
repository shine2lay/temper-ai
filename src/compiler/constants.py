"""Constants for the compiler module.

Centralized constants for checkpoint configuration, security limits,
environment variable validation, and executor settings.
"""

# ============================================================================
# Security Limits
# ============================================================================

MAX_YAML_NESTING_DEPTH = 50
MAX_YAML_NODES = 100_000
MAX_CONFIG_SIZE = 10 * 1024 * 1024  # 10MB
MAX_ENV_VAR_SIZE = 10 * 1024  # 10KB

# ============================================================================
# Checkpoint Configuration
# ============================================================================

DEFAULT_MAX_CHECKPOINTS = 10
CHECKPOINT_CLEANUP_INTERVAL = 100  # Every N operations

# ============================================================================
# Config Loader
# ============================================================================

DEFAULT_MAX_CACHE_SIZE = 120  # Max cached configs

# ============================================================================
# Executor Settings
# ============================================================================

DEFAULT_DISAGREEMENT_THRESHOLD = 0.5  # 50% disagreement triggers re-evaluation
