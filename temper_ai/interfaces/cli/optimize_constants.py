"""Constants for optimization CLI commands."""

# CLI defaults (mirrored from temper_ai.optimization.constants to avoid fan-out)
CLI_DEFAULT_MIN_TRAINING_EXAMPLES = 10
CLI_DEFAULT_MAX_DEMOS = 3

OPTIMIZE_GROUP_HELP = "DSPy prompt optimization commands."
COMPILE_HELP = "Compile optimized prompts for an agent using execution history."
LIST_HELP = "List compiled optimization programs."
PREVIEW_HELP = "Preview what an optimized prompt looks like for an agent."
DRY_RUN_HELP = "Show training data stats without compiling."
AGENT_FILTER_HELP = "Filter by agent name."
OPTIMIZER_HELP = "Optimizer to use: bootstrap or mipro."
MIN_EXAMPLES_HELP = "Minimum training examples required."
MAX_DEMOS_HELP = "Maximum few-shot demos to include."
NO_PROGRAMS_MSG = "No compiled programs found."
COMPILE_SUCCESS_MSG = "Compilation complete for agent '{agent_name}'."
INSUFFICIENT_DATA_MSG = (
    "Insufficient training data: {count}/{required} examples."
)
DSPY_NOT_INSTALLED_MSG = (
    "DSPy is not installed. Install with: pip install 'temper-ai[dspy]'"
)
PREVIEW_NO_PROGRAM_MSG = "No compiled program found for agent '{agent_name}'."
CONFIG_LOAD_ERROR_MSG = "Failed to load config: {error}"
DB_INIT_ERROR_MSG = "Database not available: {error}"
DEFAULT_OPTIMIZE_DB_PATH = ".meta-autonomous/observability.db"
