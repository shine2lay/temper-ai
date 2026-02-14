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

# ============================================================================
# Execution Modes
# ============================================================================

EXECUTION_MODE_PARALLEL = "parallel"
EXECUTION_MODE_SEQUENTIAL = "sequential"
EXECUTION_MODE_LANGGRAPH = "langgraph"

# ============================================================================
# Execution Status Values
# ============================================================================

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_HALT = "halt"
STATUS_UNKNOWN = "unknown"

# ============================================================================
# Workflow ID Prefix
# ============================================================================

WORKFLOW_ID_PREFIX = "wf-"

# ============================================================================
# Default Version
# ============================================================================

DEFAULT_VERSION = "1.0"

# ============================================================================
# Error Message Templates
# ============================================================================

ERROR_MSG_ENV_VAR_PREFIX = "Environment variable '"
ERROR_MSG_QUALITY_GATE_FAILED = "Quality gates failed for stage '"
ERROR_MSG_STAGE_PREFIX = "Stage '"
ERROR_MSG_AGENT_PREFIX = "Agent '"

# ============================================================================
# Logging Prefixes
# ============================================================================

LOG_PREFIX_CHECKPOINT = "Checkpoint "
LOG_PREFIX_CHECKPOINT_LABEL = "checkpoint:"
LOG_PREFIX_CHECKPOINT_INDEX = "checkpoint_index:"

# ============================================================================
# Stage Transition Actions
# ============================================================================

STAGE_ACTION_EXECUTE = "execute"
STAGE_ACTION_AFTER = "after"

# ============================================================================
# Adaptive Execution Metadata Keys
# ============================================================================

ADAPTIVE_META_STARTED_WITH = "started_with"
ADAPTIVE_META_SWITCHED_TO = "switched_to"
ADAPTIVE_META_DISAGREEMENT_RATE = "disagreement_rate"

# ============================================================================
# Collaboration Event Types
# ============================================================================

COLLAB_EVENT_MODE_SWITCH = "mode_switch"
COLLAB_EVENT_TRACK_COLLABORATION = "track_collaboration_event"

# ============================================================================
# LangGraph Node Types
# ============================================================================

LANGGRAPH_NODE_INIT = "init"
LANGGRAPH_NODE_COLLECT = "collect"
LANGGRAPH_NODE_EXECUTION = "execution"

# ============================================================================
# Agent Roles
# ============================================================================

AGENT_ROLE_LEADER = "leader"
