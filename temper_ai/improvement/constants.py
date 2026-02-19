"""Named constants for the improvement module."""

# Evaluation score bounds
MIN_SCORE = 0.0
MAX_SCORE = 1.0

# Default limits
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_RUNS = 3
DEFAULT_TIMEOUT_SECONDS = 600

# Comparison outcomes
FIRST_BETTER = -1
TIE = 0
SECOND_BETTER = 1

# Evaluator type names
EVALUATOR_CRITERIA = "criteria"
EVALUATOR_COMPARATIVE = "comparative"
EVALUATOR_SCORED = "scored"
EVALUATOR_HUMAN = "human"

# Optimizer type names
OPTIMIZER_REFINEMENT = "refinement"
OPTIMIZER_SELECTION = "selection"
OPTIMIZER_TUNING = "tuning"

# Check methods
CHECK_METHOD_PROGRAMMATIC = "programmatic"
CHECK_METHOD_LLM = "llm"
