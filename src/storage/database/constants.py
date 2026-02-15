"""Constants for the database module.

Centralized constants for database models, relationships, and constraints.
"""

# ============================================================================
# Foreign Key Constraints
# ============================================================================

FK_CASCADE = "CASCADE"
FK_WORKFLOW_EXECUTIONS_ID = "workflow_executions.id"
FK_STAGE_EXECUTIONS_ID = "stage_executions.id"
FK_AGENT_EXECUTIONS_ID = "agent_executions.id"

# ============================================================================
# Relationship Cascade Options
# ============================================================================

CASCADE_ALL_DELETE_ORPHAN = "all, delete-orphan"
CASCADE_SIMPLE = "cascade"

# ============================================================================
# Field Names (JSON Column Keys)
# ============================================================================

FIELD_WORKFLOW_CONFIG_SNAPSHOT = "workflow_config_snapshot"
FIELD_STAGE_CONFIG_SNAPSHOT = "stage_config_snapshot"
FIELD_AGENT_CONFIG_SNAPSHOT = "agent_config_snapshot"
FIELD_INPUT_DATA = "input_data"
FIELD_OUTPUT_DATA = "output_data"
FIELD_EXTRA_METADATA = "extra_metadata"

# ============================================================================
# Status Constraints
# ============================================================================

STATUS_CONSTRAINT = "status IN ('running', 'completed', 'failed', 'halted', 'timeout')"
