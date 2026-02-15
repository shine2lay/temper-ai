"""Constants for the compiler module.

Centralized constants for checkpoint configuration, security limits,
environment variable validation, and executor settings.

Execution-related constants shared with stage/tools modules are canonical
in ``src.shared.constants.execution`` and re-exported here for backward
compatibility.
"""

from src.shared.constants.execution import (  # noqa: F401
    ADAPTIVE_META_DISAGREEMENT_RATE,
    ADAPTIVE_META_STARTED_WITH,
    ADAPTIVE_META_SWITCHED_TO,
    AGENT_ROLE_LEADER,
    COLLAB_EVENT_MODE_SWITCH,
    COLLAB_EVENT_TRACK_COLLABORATION,
    DEFAULT_VERSION,
    ERROR_MSG_AGENT_PREFIX,
    ERROR_MSG_ENV_VAR_PREFIX,
    ERROR_MSG_FOR_STAGE_SUFFIX,
    ERROR_MSG_QUALITY_GATE_FAILED,
    ERROR_MSG_STAGE_PREFIX,
    EXECUTION_MODE_LANGGRAPH,
    EXECUTION_MODE_PARALLEL,
    EXECUTION_MODE_SEQUENTIAL,
    STATUS_FAILED,
    STATUS_HALT,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    WORKFLOW_ID_PREFIX,
)

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

# ============================================================================
# Logging Prefixes
# ============================================================================

LOG_PREFIX_CHECKPOINT = "Checkpoint "
LOG_PREFIX_CHECKPOINT_LABEL = "checkpoint:"
LOG_PREFIX_CHECKPOINT_INDEX = "checkpoint_index:"
LOG_SEPARATOR_CHECKPOINT = ", checkpoint="

# ============================================================================
# Stage Transition Actions
# ============================================================================

STAGE_ACTION_EXECUTE = "execute"
STAGE_ACTION_AFTER = "after"

# ============================================================================
# LangGraph Node Types
# ============================================================================

LANGGRAPH_NODE_INIT = "init"
LANGGRAPH_NODE_COLLECT = "collect"
LANGGRAPH_NODE_EXECUTION = "execution"

# ============================================================================
# LangGraph Internal Keys
# ============================================================================

LANGGRAPH_DICT_CACHE_KEY = "_dict_cache"
