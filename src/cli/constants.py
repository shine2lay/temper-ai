"""Constants for the CLI module.

Centralized constants for CLI display, database paths, and report formatting.
"""

# ============================================================================
# Display Configuration
# ============================================================================

TABLE_COLUMN_MAX_WIDTH = 20
OUTPUT_PREVIEW_LENGTH = 500
DEFAULT_TABLE_ROW_LIMIT = 50

# ============================================================================
# CLI Defaults
# ============================================================================

DEFAULT_ANALYSIS_WINDOW_HOURS = 168  # 1 week (24 * 7)
SIGNAL_EXIT_CODE = 130  # Standard exit code for SIGINT

# ============================================================================
# Configuration Paths and Names
# ============================================================================

DEFAULT_CONFIG_ROOT = "configs"
AGENTS_DIR_NAME = "agents"
WORKFLOWS_DIR_NAME = "workflows"
STAGES_DIR_NAME = "stages"

# ============================================================================
# File Patterns and Extensions
# ============================================================================

YAML_FILE_EXTENSION = ".yaml"
YAML_GLOB_PATTERN = "*.yaml"

# ============================================================================
# Network Configuration
# ============================================================================

DEFAULT_SERVER_HOST = "0.0.0.0"  # noqa: S104  # nosec B104

# ============================================================================
# Database Configuration
# ============================================================================

SQLITE_URL_PREFIX = "sqlite:///"

# ============================================================================
# CLI Options and Environment Variables
# ============================================================================

CLI_OPTION_CONFIG_ROOT = "--config-root"
CLI_OPTION_DB = "--db"
ENV_VAR_CONFIG_ROOT = "MAF_CONFIG_ROOT"

# ============================================================================
# Help Text
# ============================================================================

HELP_CONFIG_ROOT = "Config directory root"

# ============================================================================
# Table Column Headers
# ============================================================================

COLUMN_NAME = "Name"
COLUMN_DESCRIPTION = "Description"

# ============================================================================
# Error Message Prefixes
# ============================================================================

ERROR_DIR_NOT_FOUND = "[red]Directory not found:[/red] "
