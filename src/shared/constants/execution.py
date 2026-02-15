"""Execution-related constants shared across workflow, stage, and tools modules.

These constants were originally in ``src.workflow.constants`` but are used by
multiple modules across layer boundaries.  Keeping them here avoids circular
dependencies and upward layer violations while remaining a single source of
truth.
"""

# ============================================================================
# Default Version
# ============================================================================

DEFAULT_VERSION = "1.0"

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
# Error Message Templates
# ============================================================================

ERROR_MSG_ENV_VAR_PREFIX = "Environment variable '"
ERROR_MSG_QUALITY_GATE_FAILED = "Quality gates failed for stage '"
ERROR_MSG_STAGE_PREFIX = "Stage '"
ERROR_MSG_AGENT_PREFIX = "Agent '"
ERROR_MSG_FOR_STAGE_SUFFIX = " for stage '"

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
# Agent Roles
# ============================================================================

AGENT_ROLE_LEADER = "leader"
