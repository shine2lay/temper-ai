"""Constants for DSPy prompt optimization."""

DEFAULT_MIN_TRAINING_EXAMPLES = 10
DEFAULT_MIN_QUALITY_SCORE = 0.7
DEFAULT_LOOKBACK_HOURS = 720  # 30 days
DEFAULT_MAX_DEMOS = 3
DEFAULT_NUM_THREADS = 4
DEFAULT_PROGRAM_STORE_DIR = "configs/optimization"
DEFAULT_OPTIMIZER: str = "bootstrap"
DEFAULT_TRAINING_METRIC = "exact_match"
INSTALL_HINT = "Install with: pip install 'temper-ai[dspy]'"

# Supported types for documentation and validation
SUPPORTED_OPTIMIZERS = ("bootstrap", "mipro", "copro", "simba", "gepa")
SUPPORTED_METRICS = ("exact_match", "contains", "fuzzy", "llm_judge", "gepa_feedback")
SUPPORTED_MODULES = (
    "predict",
    "chain_of_thought",
    "program_of_thought",
    "multi_chain_comparison",
    "react",
    "best_of_n",
    "refine",
)

# Optimizer-specific defaults
DEFAULT_COPRO_BREADTH = 10
DEFAULT_COPRO_DEPTH = 3
DEFAULT_SIMBA_NUM_CANDIDATES = 6
DEFAULT_SIMBA_MAX_STEPS = 8

# LLM judge default rubric
DEFAULT_JUDGE_RUBRIC = (
    "Score 0.0 to 1.0 based on correctness, completeness, and relevance."
)

# Prompt injection markers
OPTIMIZATION_SECTION_SEPARATOR = "\n\n---\n\n"
OPTIMIZATION_HEADER = "# Optimized Guidance"
EXAMPLES_HEADER = "# Reference Examples"

# Train/validation split ratio (DSPy convention: 20% train / 80% val)
TRAIN_SPLIT_RATIO = 0.2

# Maximum field name length for DSPy signatures
MAX_FIELD_NAME_LENGTH = 64

# Default quality score for executions without explicit scoring
DEFAULT_FALLBACK_QUALITY_SCORE = 1.0
