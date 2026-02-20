"""Constants for DSPy prompt optimization."""

from typing import Literal

DEFAULT_MIN_TRAINING_EXAMPLES = 10
DEFAULT_MIN_QUALITY_SCORE = 0.7
DEFAULT_LOOKBACK_HOURS = 720  # 30 days
DEFAULT_MAX_DEMOS = 3
DEFAULT_NUM_THREADS = 4
DEFAULT_PROGRAM_STORE_DIR = "configs/optimization"
DEFAULT_OPTIMIZER: Literal["bootstrap", "mipro"] = "bootstrap"
INSTALL_HINT = "Install with: pip install 'temper-ai[dspy]'"

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
